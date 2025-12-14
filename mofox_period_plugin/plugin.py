
from typing import List, Tuple, Type, Dict, Any, Optional
from datetime import datetime, timedelta
from calendar import monthrange
import random
from src.plugin_system import (
    BasePlugin, register_plugin, ComponentInfo, ConfigField,
    BasePrompt, BaseCommand, ChatType
)
from src.plugin_system import BaseEventHandler, EventType
from src.plugin_system.base.base_event import HandlerResult
from src.plugin_system.base.component_types import InjectionRule, InjectionType
from src.plugin_system.apis import storage_api
from src.common.logger import get_logger

logger = get_logger("mofox_period_plugin")

# 获取插件的本地存储实例
plugin_storage = storage_api.get_local_storage("mofox_period_plugin")


# ============================================================================
# 双周期锚定模型 - 核心数据结构
# ============================================================================

class CyclePhase:
    """周期阶段定义"""
    def __init__(self, name: str, name_cn: str, duration: int, day_in_phase: int):
        self.name = name  # 阶段英文名
        self.name_cn = name_cn  # 阶段中文名
        self.duration = duration  # 阶段持续天数
        self.day_in_phase = day_in_phase  # 阶段内第几天


class DualCycleData:
    """双周期数据"""
    def __init__(self, anchor_day: int, start_date: datetime, 
                 cycle1_length: int, cycle2_length: int,
                 cycle1_menstrual_days: int, cycle2_menstrual_days: int):
        self.anchor_day = anchor_day  # 锚点日期（1-31）
        self.start_date = start_date  # 起始锚点日期
        self.cycle1_length = cycle1_length  # 第一周期天数
        self.cycle2_length = cycle2_length  # 第二周期天数
        self.cycle1_menstrual_days = cycle1_menstrual_days  # 第一周期月经天数
        self.cycle2_menstrual_days = cycle2_menstrual_days  # 第二周期月经天数
        self.total_days = cycle1_length + cycle2_length  # 总天数
        self.end_date = self._calculate_end_date()  # 结束锚点日期
        
    def _calculate_end_date(self) -> datetime:
        """计算结束锚点日期（下下个月的锚点日）"""
        # 从起始日期开始，找到第二个锚点
        current = self.start_date
        # 跳到下一个月
        if current.month == 12:
            next_month = current.replace(year=current.year + 1, month=1, day=1)
        else:
            next_month = current.replace(month=current.month + 1, day=1)
        
        # 获取下一个月的锚点日
        days_in_month = monthrange(next_month.year, next_month.month)[1]
        anchor = min(self.anchor_day, days_in_month)
        
        return next_month.replace(day=anchor)
    
    def to_dict(self) -> dict:
        """转换为字典以便存储"""
        return {
            "anchor_day": self.anchor_day,
            "start_date": self.start_date.isoformat(),
            "cycle1_length": self.cycle1_length,
            "cycle2_length": self.cycle2_length,
            "cycle1_menstrual_days": self.cycle1_menstrual_days,
            "cycle2_menstrual_days": self.cycle2_menstrual_days,
            "total_days": self.total_days,
            "end_date": self.end_date.isoformat()
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'DualCycleData':
        """从字典恢复"""
        return cls(
            anchor_day=data["anchor_day"],
            start_date=datetime.fromisoformat(data["start_date"]),
            cycle1_length=data["cycle1_length"],
            cycle2_length=data["cycle2_length"],
            cycle1_menstrual_days=data["cycle1_menstrual_days"],
            cycle2_menstrual_days=data["cycle2_menstrual_days"]
        )


# ============================================================================
# 双周期锚定管理器
# ============================================================================

class DualCycleManager:
    """双周期锚定管理器"""
    
    def __init__(self):
        self.current_cycle: Optional[DualCycleData] = None
        self._load_or_generate_cycle()
    
    def _load_or_generate_cycle(self):
        """加载或生成双周期数据"""
        stored_cycle = plugin_storage.get("dual_cycle_data", None)
        
        if stored_cycle:
            try:
                self.current_cycle = DualCycleData.from_dict(stored_cycle)
                # 检查是否已过期
                today = datetime.now()
                if today >= self.current_cycle.end_date:
                    logger.info("双周期已过期，重新生成")
                    self._generate_new_cycle()
                else:
                    logger.info(f"加载已存储的双周期数据，有效期至 {self.current_cycle.end_date.date()}")
            except Exception as e:
                logger.error(f"加载双周期数据失败: {e}，重新生成")
                self._generate_new_cycle()
        else:
            logger.info("首次运行，生成双周期数据")
            self._generate_new_cycle()
    
    def _generate_new_cycle(self):
        """生成新的双周期数据"""
        # 从存储获取锚点日期配置，默认为15号
        anchor_day = plugin_storage.get("anchor_day", 15)
        
        # 计算当前锚点日期
        today = datetime.now()
        days_in_month = monthrange(today.year, today.month)[1]
        anchor = min(anchor_day, days_in_month)
        
        # 如果今天已经过了本月锚点，从本月锚点开始，否则从上月锚点开始
        if today.day >= anchor:
            start_date = today.replace(day=anchor)
        else:
            # 回到上个月
            if today.month == 1:
                last_month = today.replace(year=today.year - 1, month=12, day=1)
            else:
                last_month = today.replace(month=today.month - 1, day=1)
            days_in_last_month = monthrange(last_month.year, last_month.month)[1]
            anchor_last = min(anchor_day, days_in_last_month)
            start_date = last_month.replace(day=anchor_last)
        
        # 计算到下一个锚点的总天数
        next_anchor_date = self._get_next_anchor_date(start_date, anchor_day)
        total_days = (next_anchor_date - start_date).days
        
        # 确保总天数足够（至少50天才能容纳两个25天周期）
        if total_days < 50:
            logger.warning(f"两个锚点间隔太短({total_days}天)，调整周期长度")
            # 如果总天数不够，平均分配
            cycle1_length = total_days // 2
            cycle2_length = total_days - cycle1_length
        else:
            # 正常情况：生成第一周期（25-35天）
            # 确保min <= max
            min_cycle1 = 25
            max_cycle1 = min(35, total_days - 25)  # 保证第二周期至少25天
            
            if max_cycle1 < min_cycle1:
                # 如果还是不够，平均分配
                cycle1_length = total_days // 2
                cycle2_length = total_days - cycle1_length
            else:
                cycle1_length = random.randint(min_cycle1, max_cycle1)
                cycle2_length = total_days - cycle1_length
                
                # 验证第二周期是否在合理范围内
                if cycle2_length < 25:
                    cycle1_length = total_days - 25
                    cycle2_length = 25
                elif cycle2_length > 35:
                    cycle1_length = total_days - 35
                    cycle2_length = 35
        
        # 随机生成月经天数（3-7天）
        cycle1_menstrual_days = random.randint(3, 7)
        cycle2_menstrual_days = random.randint(3, 7)
        
        self.current_cycle = DualCycleData(
            anchor_day=anchor_day,
            start_date=start_date,
            cycle1_length=cycle1_length,
            cycle2_length=cycle2_length,
            cycle1_menstrual_days=cycle1_menstrual_days,
            cycle2_menstrual_days=cycle2_menstrual_days
        )
        
        # 保存到存储
        plugin_storage.set("dual_cycle_data", self.current_cycle.to_dict())
        
        logger.info(f"生成新双周期: 起始={start_date.date()}, "
                   f"周期1={cycle1_length}天(月经{cycle1_menstrual_days}天), "
                   f"周期2={cycle2_length}天(月经{cycle2_menstrual_days}天), "
                   f"总计={total_days}天")
    
    def _get_next_anchor_date(self, from_date: datetime, anchor_day: int) -> datetime:
        """获取下一个锚点日期"""
        # 跳到下一个月
        if from_date.month == 12:
            next_month = from_date.replace(year=from_date.year + 1, month=1, day=1)
        else:
            next_month = from_date.replace(month=from_date.month + 1, day=1)
        
        days_in_month = monthrange(next_month.year, next_month.month)[1]
        anchor = min(anchor_day, days_in_month)
        
        return next_month.replace(day=anchor)
    
    def get_current_phase(self, query_date: Optional[datetime] = None) -> Tuple[CyclePhase, int, int]:
        """
        获取指定日期的周期阶段
        
        Returns:
            Tuple[CyclePhase, 周期编号(1或2), 周期内第几天]
        """
        if query_date is None:
            query_date = datetime.now()
        
        # 确保有有效的周期数据
        if not self.current_cycle:
            self._generate_new_cycle()
        
        # 如果查询日期超出当前周期，重新生成
        if query_date >= self.current_cycle.end_date:
            self._generate_new_cycle()
        
        # 计算距离起始日期的天数
        days_from_start = (query_date - self.current_cycle.start_date).days
        
        # 如果是负数，说明查询日期在当前周期之前，需要重新生成
        if days_from_start < 0:
            self._generate_new_cycle()
            days_from_start = (query_date - self.current_cycle.start_date).days
        
        # 确定在哪个周期
        if days_from_start < self.current_cycle.cycle1_length:
            # 第一周期
            cycle_num = 1
            day_in_cycle = days_from_start + 1
            cycle_length = self.current_cycle.cycle1_length
            menstrual_days = self.current_cycle.cycle1_menstrual_days
        else:
            # 第二周期
            cycle_num = 2
            day_in_cycle = days_from_start - self.current_cycle.cycle1_length + 1
            cycle_length = self.current_cycle.cycle2_length
            menstrual_days = self.current_cycle.cycle2_menstrual_days
        
        # 计算阶段
        phase = self._calculate_phase(day_in_cycle, cycle_length, menstrual_days)
        
        return phase, cycle_num, day_in_cycle
    
    def _calculate_phase(self, day_in_cycle: int, cycle_length: int, 
                        menstrual_days: int) -> CyclePhase:
        """
        计算周期内的阶段
        
        固定分配：
        - 月经期：随机3-7天
        - 卵泡期：剩余天数 - 16
        - 排卵期：固定2天
        - 黄体期：固定14天
        """
        # 月经期
        if day_in_cycle <= menstrual_days:
            return CyclePhase("menstrual", "月经期", menstrual_days, day_in_cycle)
        
        # 卵泡期天数 = 周期总长 - 月经天数 - 2（排卵）- 14（黄体）
        follicular_days = cycle_length - menstrual_days - 2 - 14
        
        # 卵泡期
        if day_in_cycle <= menstrual_days + follicular_days:
            day_in_phase = day_in_cycle - menstrual_days
            return CyclePhase("follicular", "卵泡期", follicular_days, day_in_phase)
        
        # 排卵期
        if day_in_cycle <= menstrual_days + follicular_days + 2:
            day_in_phase = day_in_cycle - menstrual_days - follicular_days
            return CyclePhase("ovulation", "排卵期", 2, day_in_phase)
        
        # 黄体期
        day_in_phase = day_in_cycle - menstrual_days - follicular_days - 2
        return CyclePhase("luteal", "黄体期", 14, day_in_phase)
    
    def regenerate_cycle(self):
        """强制重新生成周期"""
        self._generate_new_cycle()


# ============================================================================
# 提示词模板系统
# ============================================================================

class PromptTemplates:
    """提示词模板系统 - 客观中性的等级描述"""
    
    # 生理影响等级提示词（1-10）- 客观描述
    PHYSICAL_TEMPLATES = {
        1: "身体状态良好，精力充沛。",
        2: "身体状态正常，偶有轻微疲惫。",
        3: "有轻度疲劳感，腰腹略有不适。",
        4: "感到较明显的疲劳，腰腹有酸痛感。",
        5: "疲劳感较强，腰腹持续不适，需要更多休息。",
        6: "疲劳明显，身体较为沉重，活动意愿降低。",
        7: "疲劳严重，身体不适感强烈，倾向卧床休息。",
        8: "身体极度疲惫，明显不适，活动困难。",
        9: "身体状况很差，严重不适。",
        10: "身体状况极差，需要医疗关注。"
    }
    
    # 心理影响等级提示词（1-10）- 客观描述
    PSYCHOLOGICAL_TEMPLATES = {
        1: "情绪稳定，心情平和。",
        2: "情绪基本稳定，偶有小波动。",
        3: "情绪略有波动，对事物较为敏感。",
        4: "情绪波动明显，耐心有所下降。",
        5: "情绪不太稳定，容易受影响。",
        6: "情绪波动较大，较为敏感易怒。",
        7: "情绪很不稳定，控制力下降。",
        8: "情绪控制困难，波动剧烈。",
        9: "情绪极不稳定，需要更多理解。",
        10: "情绪状态很差，需要特别关注。"
    }
    
    # 痛经等级提示词（0-10）- 客观描述
    DYSMENORRHEA_TEMPLATES = {
        0: "无痛经症状。",
        1: "有非常轻微的下腹不适。",
        2: "有轻微的下腹疼痛感。",
        3: "下腹有轻度疼痛，略感不适。",
        4: "下腹疼痛较明显，需要注意休息。",
        5: "下腹疼痛感较强，影响日常活动。",
        6: "下腹疼痛明显，活动受限。",
        7: "下腹疼痛严重，需要充分休息。",
        8: "下腹剧烈疼痛，严重影响状态。",
        9: "疼痛非常严重，需要医疗帮助。",
        10: "疼痛极其剧烈，需要紧急医疗。"
    }
    
    @classmethod
    def get_physical_prompt(cls, level: int) -> str:
        """获取生理影响等级的提示词"""
        return cls.PHYSICAL_TEMPLATES.get(level, cls.PHYSICAL_TEMPLATES[5])
    
    @classmethod
    def get_psychological_prompt(cls, level: int) -> str:
        """获取心理影响等级的提示词"""
        return cls.PSYCHOLOGICAL_TEMPLATES.get(level, cls.PSYCHOLOGICAL_TEMPLATES[5])
    
    @classmethod
    def get_dysmenorrhea_prompt(cls, level: int) -> str:
        """获取痛经等级的提示词"""
        return cls.DYSMENORRHEA_TEMPLATES.get(level, cls.DYSMENORRHEA_TEMPLATES[0])


# ============================================================================
# 周期状态管理器
# ============================================================================

class PeriodStateManager:
    """月经周期状态管理器 - 使用双周期锚定模型"""
    
    def __init__(self):
        self.cycle_manager = DualCycleManager()
        self.last_calculated_date = None
        self.current_state = None
        
    def calculate_current_state(self, config: dict) -> Dict[str, Any]:
        """
        计算当前周期状态
        
        Args:
            config: 配置字典，包含各阶段的等级配置
        """
        today = datetime.now()
        
        # 如果已经计算过今天的状态，直接返回缓存
        if self.last_calculated_date == today.date() and self.current_state:
            return self.current_state
        
        try:
            # 获取当前阶段
            phase, cycle_num, day_in_cycle = self.cycle_manager.get_current_phase(today)
            
            # 从配置获取等级
            physical_level = config.get(f"levels.{phase.name}.physical", 5)
            psychological_level = config.get(f"levels.{phase.name}.psychological", 5)
            
            # 确保等级在1-10范围内
            physical_level = max(1, min(10, physical_level))
            psychological_level = max(1, min(10, psychological_level))
            
            # 痛经等级随机生成（仅在月经期）
            if phase.name == "menstrual":
                dysmenorrhea_level = self._generate_dysmenorrhea_level()
            else:
                dysmenorrhea_level = 0
            
            self.current_state = {
                "stage": phase.name,
                "stage_name_cn": phase.name_cn,
                "cycle_num": cycle_num,
                "day_in_cycle": day_in_cycle,
                "day_in_phase": phase.day_in_phase,
                "phase_duration": phase.duration,
                "physical_level": physical_level,
                "psychological_level": psychological_level,
                "dysmenorrhea_level": dysmenorrhea_level,
                "description": self._get_stage_description(phase.name),
                "last_updated": today.date().isoformat(),
                "status": "normal"
            }
            
            self.last_calculated_date = today.date()
            
            return self.current_state
            
        except Exception as e:
            logger.error(f"计算周期状态失败: {e}")
            # 返回默认状态
            return {
                "stage": "follicular",
                "stage_name_cn": "卵泡期",
                "cycle_num": 1,
                "day_in_cycle": 10,
                "day_in_phase": 5,
                "phase_duration": 10,
                "physical_level": 2,
                "psychological_level": 2,
                "dysmenorrhea_level": 0,
                "description": "状态恢复，情绪平稳，思维清晰",
                "last_updated": today.date().isoformat(),
                "status": "error",
                "error": str(e)
            }
    
    def _generate_dysmenorrhea_level(self) -> int:
        """生成痛经等级"""
        rand = random.random()
        if rand < 0.3:  # 30%概率无痛经
            return 0
        elif rand < 0.7:  # 40%概率轻度痛经(1-3)
            return random.randint(1, 3)
        elif rand < 0.9:  # 20%概率中度痛经(4-6)
            return random.randint(4, 6)
        else:  # 10%概率重度痛经(7-10)
            return random.randint(7, 10)
    
    def _get_stage_description(self, stage: str) -> str:
        """获取阶段描述"""
        descriptions = {
            "menstrual": "身体不适，情绪敏感，需要更多休息和理解",
            "follicular": "状态恢复，情绪平稳，思维清晰",
            "ovulation": "状态较佳，情绪积极，表达流畅",
            "luteal": "身体疲惫，情绪波动，需要更多耐心"
        }
        return descriptions.get(stage, "")


# ============================================================================
# Prompt组件
# ============================================================================

class PeriodStatePrompt(BasePrompt):
    """月经周期状态提示词注入"""
    
    prompt_name = "period_state_prompt"
    prompt_description = "根据月经周期状态调整机器人行为风格"
    
    injection_rules = [
        InjectionRule(
            target_prompt="s4u_style_prompt",
            injection_type=InjectionType.APPEND,
            priority=200
        ),
        InjectionRule(
            target_prompt="normal_style_prompt",
            injection_type=InjectionType.APPEND,
            priority=200
        ),
        InjectionRule(
            target_prompt="kfc_main",
            injection_type=InjectionType.APPEND,
            priority=200
        ),
        InjectionRule(
            target_prompt="kfc_replyer",
            injection_type=InjectionType.APPEND,
            priority=200
        )
    ]
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.state_manager = PeriodStateManager()
        
    async def execute(self) -> str:
        """生成周期状态提示词"""
        try:
            enabled = self.get_config("plugin.enabled", False)
            debug_mode = self.get_config("plugin.debug_mode", False)
            
            if not enabled:
                if debug_mode:
                    logger.debug("插件未启用，不生成提示词")
                return ""
            
            # 收集配置
            config = {
                "levels.menstrual.physical": self.get_config("levels.menstrual_physical", 5),
                "levels.menstrual.psychological": self.get_config("levels.menstrual_psychological", 4),
                "levels.follicular.physical": self.get_config("levels.follicular_physical", 2),
                "levels.follicular.psychological": self.get_config("levels.follicular_psychological", 2),
                "levels.ovulation.physical": self.get_config("levels.ovulation_physical", 3),
                "levels.ovulation.psychological": self.get_config("levels.ovulation_psychological", 2),
                "levels.luteal.physical": self.get_config("levels.luteal_physical", 4),
                "levels.luteal.psychological": self.get_config("levels.luteal_psychological", 3),
            }
            
            # 计算当前状态
            state = self.state_manager.calculate_current_state(config)
            
            # 获取目标提示词名称（通过属性访问）
            target_prompt = getattr(self, 'target_prompt_name', None)
            
            # 生成提示词
            prompt = self._generate_prompt(state)
            
            if debug_mode:
                logger.debug(f"周期状态提示词: {prompt}")
            
            return prompt
            
        except Exception as e:
            logger.error(f"生成周期状态提示词失败: {e}")
            return ""
            
    def _generate_prompt(self, state: Dict[str, Any]) -> str:
        """根据状态生成提示词"""
        stage_name = state["stage_name_cn"]
        physical_level = state["physical_level"]
        psychological_level = state["psychological_level"]
        dysmenorrhea_level = state["dysmenorrhea_level"]
        
        # 获取等级对应的提示词
        physical_prompt = PromptTemplates.get_physical_prompt(physical_level)
        psychological_prompt = PromptTemplates.get_psychological_prompt(psychological_level)
        
        # 简洁的提示词
        prompt_parts = [
            f"【当前状态：{stage_name} 第{state['day_in_phase']}天】",
            f"生理: {physical_prompt}",
            f"心理: {psychological_prompt}"
        ]
        
        # 如果有痛经，添加痛经提示词
        if dysmenorrhea_level > 0 and state["stage"] == "menstrual":
            dysmenorrhea_prompt = PromptTemplates.get_dysmenorrhea_prompt(dysmenorrhea_level)
            prompt_parts.append(f"痛经: {dysmenorrhea_prompt}")
        
        prompt_parts.append("以上状态会自然地影响你的回复风格，保持真实感即可。")
        
        return "\n".join(prompt_parts)


# ============================================================================
# Command组件
# ============================================================================

class PeriodStatusCommand(BaseCommand):
    """查询当前月经周期状态命令"""
    
    command_name = "period_status"
    command_description = "查询当前月经周期状态"
    command_pattern = r"^/(period|月经状态|周期状态)$"
    chat_type_allow = ChatType.PRIVATE
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.state_manager = PeriodStateManager()
        
    async def execute(self) -> Tuple[bool, str, bool]:
        """执行状态查询"""
        try:
            enabled = self.get_config("plugin.enabled", False)
            
            if not enabled:
                await self.send_text("❌ 月经周期插件未启用")
                return True, "插件未启用", True
            
            # 收集配置
            config = {
                "levels.menstrual.physical": self.get_config("levels.menstrual_physical", 5),
                "levels.menstrual.psychological": self.get_config("levels.menstrual_psychological", 4),
                "levels.follicular.physical": self.get_config("levels.follicular_physical", 2),
                "levels.follicular.psychological": self.get_config("levels.follicular_psychological", 2),
                "levels.ovulation.physical": self.get_config("levels.ovulation_physical", 3),
                "levels.ovulation.psychological": self.get_config("levels.ovulation_psychological", 2),
                "levels.luteal.physical": self.get_config("levels.luteal_physical", 4),
                "levels.luteal.psychological": self.get_config("levels.luteal_psychological", 3),
            }
            
            # 计算当前状态
            state = self.state_manager.calculate_current_state(config)
            
            # 生成状态报告
            report = self._generate_status_report(state)
            await self.send_text(report)
            
            return True, "发送周期状态报告", True
            
        except Exception as e:
            logger.error(f"查询周期状态失败: {e}")
            await self.send_text("❌ 查询状态失败")
            return False, f"查询失败: {e}", True
            
    def _generate_status_report(self, state: Dict[str, Any]) -> str:
        """生成状态报告"""
        stage_emoji = {
            "menstrual": "🩸",
            "follicular": "🌱", 
            "ovulation": "🥚",
            "luteal": "🍂"
        }
        
        emoji = stage_emoji.get(state["stage"], "❓")
        
        # 获取双周期信息
        cycle_manager = self.state_manager.cycle_manager
        cycle_data = cycle_manager.current_cycle
        
        report = f"""
{emoji} 月经周期状态报告（双周期模型）
━━━━━━━━━━━━━━━━━━
📅 当前阶段: {state['stage_name_cn']} 第{state['day_in_phase']}天/{state['phase_duration']}天
🔄 周期编号: 第{state['cycle_num']}周期 第{state['day_in_cycle']}天
📆 锚点日期: 每月{cycle_data.anchor_day}号
⏰ 周期有效期: {cycle_data.start_date.date()} 至 {cycle_data.end_date.date()}

💊 生理影响: 等级 {state['physical_level']}/10
💭 心理影响: 等级 {state['psychological_level']}/10"""

        if state.get('dysmenorrhea_level', 0) > 0 and state['stage'] == 'menstrual':
            report += f"\n🔥 痛经程度: 等级 {state['dysmenorrhea_level']}/10"
        
        report += f"""

📝 状态描述:
{state['description']}
━━━━━━━━━━━━━━━━━━
💡 提示: 等级越高影响越严重
💡 痛经等级在月经期自动随机生成
💡 使用 /regenerate_cycle 重新生成双周期
💡 可在配置文件中调整各阶段影响等级"""
        
        return report.strip()


class RegenerateCycleCommand(BaseCommand):
    """重新生成双周期命令"""
    
    command_name = "regenerate_cycle"
    command_description = "强制重新生成双周期数据"
    command_pattern = r"^/(regenerate_cycle|重新生成周期|刷新周期)$"
    chat_type_allow = ChatType.PRIVATE
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.state_manager = PeriodStateManager()
        
    async def execute(self) -> Tuple[bool, str, bool]:
        """执行重新生成周期"""
        try:
            enabled = self.get_config("plugin.enabled", False)
            
            if not enabled:
                await self.send_text("❌ 月经周期插件未启用")
                return True, "插件未启用", True
            
            # 重新生成周期
            self.state_manager.cycle_manager.regenerate_cycle()
            cycle_data = self.state_manager.cycle_manager.current_cycle
            
            msg = f"""
✅ 双周期已重新生成

📅 锚点日期: 每月{cycle_data.anchor_day}号
📆 起始日期: {cycle_data.start_date.date()}
📆 结束日期: {cycle_data.end_date.date()}

🔄 第一周期: {cycle_data.cycle1_length}天（月经{cycle_data.cycle1_menstrual_days}天）
🔄 第二周期: {cycle_data.cycle2_length}天（月经{cycle_data.cycle2_menstrual_days}天）
📊 总天数: {cycle_data.total_days}天

使用 /period 查看当前状态"""
            
            await self.send_text(msg)
            return True, "重新生成双周期", True
            
        except Exception as e:
            logger.error(f"重新生成周期失败: {e}")
            await self.send_text("❌ 重新生成失败")
            return False, f"重新生成失败: {e}", True


# ============================================================================
# Event Handler
# ============================================================================

class PeriodStateUpdateHandler(BaseEventHandler):
    """周期状态更新处理器"""
    
    handler_name = "period_state_updater"
    handler_description = "初始化月经周期状态管理（双周期模型）"
    init_subscribe = [EventType.ON_START]
    
    async def execute(self, params: dict) -> HandlerResult:
        """初始化状态管理器"""
        try:
            enabled = self.get_config("plugin.enabled", False)
            
            if enabled:
                # 将配置的anchor_day保存到storage，供DualCycleManager使用
                anchor_day = self.get_config("cycle.anchor_day", 15)
                plugin_storage.set("anchor_day", anchor_day)
                
                # 初始化双周期管理器
                cycle_manager = DualCycleManager()
                logger.info(f"双周期锚定模型初始化完成（锚点日期: 每月{anchor_day}号）")
                
                if cycle_manager.current_cycle:
                    logger.info(f"当前双周期: 起始={cycle_manager.current_cycle.start_date.date()}, "
                               f"结束={cycle_manager.current_cycle.end_date.date()}, "
                               f"总天数={cycle_manager.current_cycle.total_days}")
                
        except Exception as e:
            logger.error(f"周期状态管理器初始化失败: {e}")
            
        return HandlerResult(success=True, continue_process=True)


# ============================================================================
# 插件主类
# ============================================================================

@register_plugin
class MofoxPeriodPlugin(BasePlugin):
    """月经周期状态插件 - 双周期锚定模型版本"""
    
    plugin_name = "mofox_period_plugin"
    enable_plugin = True
    dependencies = []
    python_dependencies = []
    config_file_name = "config.toml"
    
    # 配置Schema定义 - 扁平化结构
    config_schema = {
        "plugin": {
            "enabled": ConfigField(
                type=bool,
                default=True,
                description="是否启用月经周期状态插件"
            ),
            "config_version": ConfigField(
                type=str,
                default="3.0.0",
                description="配置文件版本（3.0使用双周期锚定模型）"
            ),
            "debug_mode": ConfigField(
                type=bool,
                default=False,
                description="是否启用调试模式"
            )
        },
        "cycle": {
            "anchor_day": ConfigField(
                type=int,
                default=15,
                description="锚点日期（1-31），每月固定号数作为周期计算基准"
            )
        },
        "levels": {
            "menstrual_physical": ConfigField(
                type=int,
                default=5,
                description="月经期生理影响等级（1-10）"
            ),
            "menstrual_psychological": ConfigField(
                type=int,
                default=4,
                description="月经期心理影响等级（1-10）"
            ),
            "follicular_physical": ConfigField(
                type=int,
                default=2,
                description="卵泡期生理影响等级（1-10）"
            ),
            "follicular_psychological": ConfigField(
                type=int,
                default=2,
                description="卵泡期心理影响等级（1-10）"
            ),
            "ovulation_physical": ConfigField(
                type=int,
                default=3,
                description="排卵期生理影响等级（1-10）"
            ),
            "ovulation_psychological": ConfigField(
                type=int,
                default=2,
                description="排卵期心理影响等级（1-10）"
            ),
            "luteal_physical": ConfigField(
                type=int,
                default=4,
                description="黄体期生理影响等级（1-10）"
            ),
            "luteal_psychological": ConfigField(
                type=int,
                default=3,
                description="黄体期心理影响等级（1-10）"
            )
        }
    }
    
    def get_plugin_components(self) -> List[Tuple[ComponentInfo, Type]]:
        """注册插件组件"""
        components = []
        
        # 总是注册状态更新处理器
        components.append((
            PeriodStateUpdateHandler.get_handler_info(),
            PeriodStateUpdateHandler
        ))
        
        # 根据配置决定是否注册其他组件
        if self.get_config("plugin.enabled", False):
            # Prompt组件
            components.append((
                PeriodStatePrompt.get_prompt_info(),
                PeriodStatePrompt
            ))
            
            # Command组件 - 使用BaseCommand
            components.append((
                PeriodStatusCommand.get_command_info(),
                PeriodStatusCommand
            ))
            
            components.append((
                RegenerateCycleCommand.get_command_info(),
                RegenerateCycleCommand
            ))
            
        return components
    
    def __init__(self, *args, **kwargs):
        """插件初始化"""
        super().__init__(*args, **kwargs)
        logger.info("月经周期插件已加载（双周期锚定模型 v3.0）")