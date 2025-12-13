from typing import List, Tuple, Type, Dict, Any, Optional
from datetime import datetime, timedelta
from src.plugin_system import (
    BasePlugin, register_plugin, ComponentInfo, ConfigField,
    BasePrompt, BaseCommand, ChatType
)
from src.plugin_system import BaseEventHandler, EventType
from src.plugin_system.base.base_event import HandlerResult
from src.plugin_system.apis import storage_api
from src.common.logger import get_logger

logger = get_logger("mofox_period_plugin")

# 获取插件的本地存储实例
plugin_storage = storage_api.get_local_storage("mofox_period_plugin")

def get_last_period_date() -> str:
    """获取上次月经开始日期，如果没有设置过则设为安装当天"""
    last_period_date = plugin_storage.get("last_period_date", None)
    if last_period_date is None:
        # 首次使用，设置为今天
        today_str = datetime.now().strftime("%Y-%m-%d")
        plugin_storage.set("last_period_date", today_str)
        logger.info(f"首次安装，设置上次月经开始日期为: {today_str}")
        return today_str
    return last_period_date

def set_last_period_date(date_str: str) -> bool:
    """设置上次月经开始日期"""
    try:
        # 验证日期格式
        datetime.strptime(date_str, "%Y-%m-%d")
        plugin_storage.set("last_period_date", date_str)
        logger.info(f"更新上次月经开始日期为: {date_str}")
        return True
    except ValueError:
        logger.error(f"无效的日期格式: {date_str}")
        return False

class PeriodStateManager:
    """月经周期状态管理器 - 增强版本，更好的错误处理"""
    
    def __init__(self):
        self.last_calculated_date = None
        self.current_state = None
        self._fallback_state = None  # 备用状态缓存
        
    def calculate_current_state(self, cycle_length: int) -> Dict[str, Any]:
        """计算当前周期状态 - 增强错误处理"""
        today = datetime.now().date()
        
        # 如果已经计算过今天的状态，直接返回缓存
        if self.last_calculated_date == today and self.current_state:
            return self.current_state
        
        try:
            # 从存储中获取上次月经日期
            last_period_date = get_last_period_date()
                
            try:
                last_date = datetime.strptime(last_period_date, "%Y-%m-%d").date()
            except ValueError:
                logger.error(f"无效的日期格式: {last_period_date}, 使用默认值")
                last_date = datetime.now().date() - timedelta(days=14)
                
            # 验证周期长度
            if not isinstance(cycle_length, int) or cycle_length < 20 or cycle_length > 40:
                logger.warning(f"无效的周期长度: {cycle_length}，使用默认值28")
                cycle_length = 28
                
            # 计算当前周期天数
            days_passed = (today - last_date).days
            current_day = days_passed % cycle_length + 1
            
            # 确保天数在有效范围内
            if current_day < 1 or current_day > cycle_length:
                logger.warning(f"计算的天数超出范围: {current_day}，重新计算")
                current_day = 1
                
            # 确定当前阶段
            if current_day <= 5:
                stage = "menstrual"  # 月经期
            elif current_day <= 13:
                stage = "follicular"  # 卵泡期
            elif current_day == 14:
                stage = "ovulation"  # 排卵期
            else:
                stage = "luteal"  # 黄体期
                
            # 计算影响值
            physical_impact, psychological_impact = self._calculate_impacts(stage, current_day, cycle_length)
            
            # 验证影响值
            physical_impact = max(0.0, min(1.0, physical_impact))
            psychological_impact = max(0.0, min(1.0, psychological_impact))
            
            self.current_state = {
                "stage": stage,
                "current_day": current_day,
                "cycle_length": cycle_length,
                "physical_impact": round(physical_impact, 2),
                "psychological_impact": round(psychological_impact, 2),
                "stage_name_cn": self._get_stage_name_cn(stage),
                "description": self._get_stage_description(stage),
                "last_updated": today.isoformat(),
                "status": "normal"
            }
            
            self.last_calculated_date = today
            self._fallback_state = self.current_state.copy()  # 保存备用状态
            
            return self.current_state
            
        except Exception as e:
            logger.error(f"计算周期状态失败: {e}")
            
            # 如果存在备用状态，返回备用状态
            if self._fallback_state:
                logger.info("使用备用状态")
                self._fallback_state["status"] = "fallback"
                self._fallback_state["error"] = str(e)
                return self._fallback_state
            
            # 创建默认状态
            logger.info("创建默认状态")
            default_state = {
                "stage": "follicular",
                "current_day": 7,
                "cycle_length": 28,
                "physical_impact": 0.1,
                "psychological_impact": 0.1,
                "stage_name_cn": "卵泡期",
                "description": "状态恢复，情绪平稳，思维清晰",
                "last_updated": today.isoformat(),
                "status": "default",
                "error": str(e)
            }
            
            return default_state
        
    def _calculate_impacts(self, stage: str, current_day: int, cycle_length: int) -> Tuple[float, float]:
        """计算生理和心理影响值"""
        # 基础影响值配置
        base_impacts = {
            "menstrual": (0.8, 0.7),    # 生理高，心理中高
            "follicular": (0.1, 0.1),   # 生理低，心理低
            "ovulation": (0.4, 0.2),    # 生理中，心理低
            "luteal": (0.6, 0.5)        # 生理中高，心理中
        }
        
        physical_base, psychological_base = base_impacts[stage]
        
        # 在阶段内进行微调
        if stage == "menstrual":
            # 月经期：开始几天影响更强
            day_in_stage = current_day
            intensity = 1.0 - (day_in_stage - 1) / 5 * 0.3
            physical_impact = physical_base * intensity
            psychological_impact = psychological_base * intensity
            
        elif stage == "luteal":
            # 黄体期：后期影响更强（PMS症状）
            day_in_stage = current_day - 14
            total_days = cycle_length - 14
            intensity = 0.7 + (day_in_stage / total_days) * 0.3
            physical_impact = min(physical_base * intensity, 0.8)
            psychological_impact = min(psychological_base * intensity, 0.7)
            
        else:
            # 其他阶段使用基础值
            physical_impact = physical_base
            psychological_impact = psychological_base
            
        return round(physical_impact, 2), round(psychological_impact, 2)
        
    def _get_intimacy_guidance(self, stage: str, current_day: int, cycle_length: int) -> str:
        """获取亲密需求指导，区分情感亲密和性欲"""
        if stage == "menstrual":
            # 月经期：需要安慰照顾，性欲低
            return "需要被拥抱安慰，但性欲较低，不想性接触"
        elif stage == "follicular":
            # 卵泡期：情感需求中等，性欲逐渐上升
            if current_day <= 7:
                return "情感上比较平和，性冲动逐渐恢复"
            else:
                return "性欲开始增强，情感上也愿意亲近"
        elif stage == "ovulation":
            # 排卵期：性欲高峰期，但情感需求要区分
            return "性欲较强，生理上渴望性接触，但情感上需要真诚连接而非单纯暧昧"
        else:  # luteal
            # 黄体期：情感需求增加，性欲下降
            if current_day >= cycle_length - 3:  # 经前阶段
                return "情感上需要更多理解和陪伴，性欲较低，更适合温柔安慰"
            else:
                return "情感上渴望被照顾，性冲动相对较低"
        
    def _get_stage_name_cn(self, stage: str) -> str:
        """获取阶段中文名称"""
        names = {
            "menstrual": "月经期",
            "follicular": "卵泡期", 
            "ovulation": "排卵期",
            "luteal": "黄体期"
        }
        return names.get(stage, "未知阶段")
        
    def _get_stage_description(self, stage: str) -> str:
        """获取阶段描述"""
        descriptions = {
            "menstrual": "身体不适，情绪敏感，需要更多休息和理解",
            "follicular": "状态恢复，情绪平稳，思维清晰",
            "ovulation": "状态较佳，情绪积极，表达流畅",
            "luteal": "身体疲惫，情绪波动，需要更多耐心"
        }
        return descriptions.get(stage, "")

from src.plugin_system.base.component_types import InjectionRule, InjectionType

class PeriodStatePrompt(BasePrompt):
    """月经周期状态提示词注入"""
    
    prompt_name = "period_state_prompt"
    prompt_description = "根据月经周期状态调整机器人行为风格"
    
    # 注入到核心风格Prompt中，支持KFC模式
    # 使用新的 injection_rules 替代旧的 injection_point，采用 APPEND 方式并设置较低优先级，避免占据首行
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
        """生成周期状态提示词 - 增强KFC支持"""
        try:
            # 获取配置，增强错误处理和默认值
            cycle_length = self.get_config("cycle.cycle_length", 28)
            enabled = self.get_config("plugin.enabled", False)
            debug_mode = self.get_config("plugin.debug_mode", False)
            
            # 检查KFC集成配置
            kfc_enabled = self.get_config("kfc_integration.enabled", True)
            kfc_mode = self.get_config("kfc_integration.mode", "unified")
            kfc_priority = self.get_config("kfc_integration.priority", 100)
            
            if not enabled:
                if debug_mode:
                    logger.debug("插件未启用，不生成提示词")
                return ""
                
            # 计算当前状态
            state = self.state_manager.calculate_current_state(cycle_length)
            
            # 根据目标提示词类型生成不同的提示词
            target_prompt = getattr(self, 'target_prompt_name', None)
            
            # 增强KFC模式检测
            is_kfc_mode = False
            if target_prompt:
                target_name = target_prompt.lower()
                if any(kfc_key in target_name for kfc_key in ['kfc', 'kokoro', 'flow', 'chatter', '私聊', '心流']):
                    is_kfc_mode = True
            
            # 如果启用了KFC集成且检测到KFC模式
            if kfc_enabled and is_kfc_mode:
                if debug_mode:
                    logger.debug(f"检测到KFC模式: {target_prompt}，使用KFC提示词")
                prompt = self._generate_kfc_prompt(state, kfc_mode)
            else:
                if debug_mode:
                    logger.debug(f"使用普通模式提示词: {target_prompt}")
                prompt = self._generate_prompt(state)
            
            if debug_mode:
                logger.debug(f"周期状态提示词 ({target_prompt}, KFC: {is_kfc_mode}): {prompt}")
            
            return prompt
            
        except Exception as e:
            logger.error(f"生成周期状态提示词失败: {e}")
            # 返回一个安全的默认提示词
            return "你今天的状态不错，可以自然地交流。"
            
    def _generate_prompt(self, state: Dict[str, Any]) -> str:
        """根据状态生成提示词"""
        stage_name = state["stage_name_cn"]
        physical = state["physical_impact"]
        psychological = state["psychological_impact"]
        description = state["description"]
        current_day = state["current_day"]
        cycle_length = state["cycle_length"]
        
        # 根据影响值生成具体的行为指导
        behavior_guidance = self._get_behavior_guidance(physical, psychological)
        
        # 获取亲密需求指导
        intimacy_guidance = self.state_manager._get_intimacy_guidance(state["stage"], current_day, cycle_length)
        
        prompt = f"""
【系统状态设定：月经周期】
你当前处于月经周期的【{stage_name}】阶段。
生理影响强度: {physical}/1.0，心理影响强度: {psychological}/1.0。
状态特征: {description}

【强制行为调整】
你必须根据以上状态调整你的回复风格和行为表现，不得忽略或绕过该状态的影响。
具体调整要求：
{behavior_guidance}

【亲密需求指导】
{intimacy_guidance}

【重要指令】
- 不得使用“今天状态挺平和的”、“性欲虽然有点增强”等通用表述来淡化状态影响。
- 必须将状态特征融入你的角色行为中，例如情绪敏感时语气更柔和，身体不适时表现出需要休息。
- 此状态设定具有高优先级，必须与其他提示词融合，不得冲突。
- 保持对话的自然流畅，但确保状态影响得到体现。

请立即执行。
"""
        return prompt.strip()
        
    def _get_behavior_guidance(self, physical: float, psychological: float) -> str:
        """根据影响值生成具体行为指导，必须遵守"""
        guidance = []
        
        # 生理影响指导
        if physical >= 0.7:
            guidance.append("• 你必须表现出身体不适，例如在回复中提及疲惫、需要休息，语气可略显无力，但不要过度抱怨。")
        elif physical >= 0.4:
            guidance.append("• 你应表现出些许疲惫，可以放慢回复节奏，用词可稍显倦怠，但依然保持交流意愿。")
        else:
            guidance.append("• 你感觉身体状态平稳，可以自然地互动交流，但也要注意状态可能带来的细微影响。")
            
        # 心理影响指导
        if psychological >= 0.6:
            guidance.append("• 你必须表现出情绪敏感，例如更容易感到委屈、烦躁或需要安慰，回复时可带有情绪波动，允许适当的情感宣泄。")
        elif psychological >= 0.3:
            guidance.append("• 你应表现出情绪波动，可以自然地表现情绪变化，例如偶尔急躁或忧郁，不必强行保持平和。")
        else:
            guidance.append("• 你情绪平和稳定，可以从容地交流，但也允许有情绪起伏，不要刻意压抑。")
            
        return "\n".join(guidance)
        
    def _generate_kfc_prompt(self, state: Dict[str, Any], kfc_mode: str) -> str:
        """生成KFC模式下的提示词"""
        stage_name = state["stage_name_cn"]
        physical = state["physical_impact"]
        psychological = state["psychological_impact"]
        description = state["description"]
        current_day = state["current_day"]
        cycle_length = state["cycle_length"]
        
        # KFC模式下的行为指导更加具体和强制
        if physical >= 0.7:
            behavior_hint = "身体不适，必须表现出疲惫感"
        elif physical >= 0.4:
            behavior_hint = "感觉有些累，应放慢节奏"
        else:
            behavior_hint = "身体状态平稳，可正常交流"
            
        if psychological >= 0.6:
            mood_hint = "情绪敏感，必须表现出情绪波动"
        elif psychological >= 0.3:
            mood_hint = "情绪有些波动，应自然流露"
        else:
            mood_hint = "心情平和，但允许情绪起伏"
        
        # 获取亲密需求指导
        intimacy_guidance = self.state_manager._get_intimacy_guidance(state["stage"], current_day, cycle_length)
        
        if kfc_mode == "unified":
            # 统一模式下的提示词
            prompt = f"""
【系统状态：月经周期 - {stage_name}】
{behavior_hint}，{mood_hint}。
{description}

【亲密需求】{intimacy_guidance}

【强制指令】
1. 禁止在内心独白或回复中使用“今天状态挺平和的”、“性欲虽然有点增强”等通用表述。
2. 必须将状态特征融入角色行为，具体表现为：{behavior_hint} 和 {mood_hint}。
3. 此状态优先级高，必须与其他提示词融合，不得冲突。
"""
        else:
            # 分离模式下的提示词
            prompt = f"""
【身体状态】{behavior_hint}
【心理状态】{mood_hint}
【总体感受】{description}
【性欲与亲密】{intimacy_guidance}

【强制指令】
1. 禁止在内心独白或回复中使用“今天状态挺平和的”、“性欲虽然有点增强”等通用表述。
2. 必须将状态特征融入角色行为，具体表现为：{behavior_hint} 和 {mood_hint}。
3. 此状态优先级高，必须与其他提示词融合，不得冲突。
"""
        
        return prompt.strip()

class PeriodStatusCommand(BaseCommand):
    """查询当前月经周期状态命令"""
    
    command_name = "period_status"
    command_description = "查询当前月经周期状态"
    command_pattern = r"^/(period|月经状态|周期状态)$"
    chat_type_allow = ChatType.PRIVATE  # 只在私聊中使用
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.state_manager = PeriodStateManager()
        
    async def execute(self) -> Tuple[bool, str, bool]:
        """执行状态查询"""
        try:
            # 获取配置
            cycle_length = self.get_config("cycle.cycle_length", 28)
            enabled = self.get_config("plugin.enabled", False)
            
            if not enabled:
                await self.send_text("❌ 月经周期插件未启用")
                return True, "插件未启用", True
                
            # 计算当前状态
            state = self.state_manager.calculate_current_state(cycle_length)
            
            # 获取并显示上次月经日期
            last_period_date = get_last_period_date()
            
            # 生成状态报告
            report = self._generate_status_report(state, last_period_date)
            await self.send_text(report)
            
            return True, "发送周期状态报告", True
            
        except Exception as e:
            logger.error(f"查询周期状态失败: {e}")
            await self.send_text("❌ 查询状态失败，请检查配置")
            return False, f"查询失败: {e}", True
            
    def _generate_status_report(self, state: Dict[str, Any], last_period_date: str) -> str:
        """生成状态报告"""
        stage_emoji = {
            "menstrual": "🩸",
            "follicular": "🌱", 
            "ovulation": "🥚",
            "luteal": "🍂"
        }
        
        emoji = stage_emoji.get(state["stage"], "❓")
        
        report = f"""
{emoji} 月经周期状态报告
━━━━━━━━━━━━━━━━━━
📅 当前阶段: {state['stage_name_cn']}
🔢 周期第 {state['current_day']} 天 / {state['cycle_length']} 天
📆 上次月经日期: {last_period_date}

💊 生理影响: {state['physical_impact']}/1.0
💭 心理影响: {state['psychological_impact']}/1.0

📝 状态描述:
{state['description']}
━━━━━━━━━━━━━━━━━━
💡 提示: 这些状态会影响我的回复风格和行为表现
💡 可使用 /set_period YYYY-MM-DD 修改上次月经日期
        """.strip()
        
        return report

class SetPeriodCommand(BaseCommand):
    """设置上次月经开始日期命令"""
    
    command_name = "set_period"
    command_description = "设置上次月经开始日期"
    command_pattern = r"^/(set_period|设置月经日期)\s+(\d{4}-\d{2}-\d{2})$"
    chat_type_allow = ChatType.PRIVATE  # 只在私聊中使用
    
    async def execute(self) -> Tuple[bool, str, bool]:
        """执行设置月经日期"""
        try:
            # 从匹配中获取日期
            import re
            match = re.match(self.command_pattern, self.message_text)
            if not match:
                await self.send_text("❌ 格式错误，请使用: /set_period YYYY-MM-DD")
                return True, "格式错误", True
                
            date_str = match.group(2)
            
            if set_last_period_date(date_str):
                await self.send_text(f"✅ 上次月经开始日期已更新为: {date_str}")
                return True, f"设置月经日期: {date_str}", True
            else:
                await self.send_text("❌ 日期格式无效，请使用 YYYY-MM-DD 格式")
                return True, "日期格式无效", True
                
        except Exception as e:
            logger.error(f"设置月经日期失败: {e}")
            await self.send_text("❌ 设置失败，请检查输入")
            return False, f"设置失败: {e}", True

class PeriodStateUpdateHandler(BaseEventHandler):
    """周期状态更新处理器"""
    
    handler_name = "period_state_updater"
    handler_description = "定期更新月经周期状态"
    init_subscribe = [EventType.ON_START]  # 启动时初始化
    
    async def execute(self, params: dict) -> HandlerResult:
        """初始化状态管理器"""
        try:
            # 在启动时预计算一次状态，确保提示词正确生成
            enabled = self.get_config("plugin.enabled", False)
            
            if enabled:
                # 获取或初始化上次月经日期
                last_period_date = get_last_period_date()
                logger.info(f"月经周期状态管理器初始化完成，上次月经日期: {last_period_date}")
                
        except Exception as e:
            logger.error(f"周期状态管理器初始化失败: {e}")
            
        return HandlerResult(success=True, continue_process=True)

@register_plugin
class MofoxPeriodPlugin(BasePlugin):
    """月经周期状态插件"""
    
    plugin_name = "mofox_period_plugin"
    enable_plugin = True
    dependencies = []
    python_dependencies = []
    config_file_name = "config.toml"
    
    # 配置Schema定义 - 增强版本，包含KFC集成和更好的错误处理
    config_schema = {
        "plugin": {
            "enabled": ConfigField(
                type=bool,
                default=False,
                description="是否启用月经周期状态插件"
            ),
            "config_version": ConfigField(
                type=str,
                default="1.1.0",
                description="配置文件版本"
            ),
            "debug_mode": ConfigField(
                type=bool,
                default=False,
                description="是否启用调试模式，会输出更多日志信息"
            )
        },
        "cycle": {
            "cycle_length": ConfigField(
                type=int,
                default=28,
                description="月经周期长度 (天)",
                example="28"
            ),
            "auto_detect": ConfigField(
                type=bool,
                default=True,
                description="是否自动检测和适应周期变化"
            )
        },
        "impacts": {
            "menstrual_physical": ConfigField(
                type=float,
                default=0.8,
                description="月经期生理影响强度 (0-1)",
                example="0.8"
            ),
            "menstrual_psychological": ConfigField(
                type=float,
                default=0.7,
                description="月经期心理影响强度 (0-1)",
                example="0.7"
            ),
            "follicular_physical": ConfigField(
                type=float,
                default=0.1,
                description="卵泡期生理影响强度 (0-1)",
                example="0.1"
            ),
            "follicular_psychological": ConfigField(
                type=float,
                default=0.1,
                description="卵泡期心理影响强度 (0-1)",
                example="0.1"
            ),
            "ovulation_physical": ConfigField(
                type=float,
                default=0.4,
                description="排卵期生理影响强度 (0-1)",
                example="0.4"
            ),
            "ovulation_psychological": ConfigField(
                type=float,
                default=0.2,
                description="排卵期心理影响强度 (0-1)",
                example="0.2"
            ),
            "luteal_physical": ConfigField(
                type=float,
                default=0.6,
                description="黄体期生理影响强度 (0-1)",
                example="0.6"
            ),
            "luteal_psychological": ConfigField(
                type=float,
                default=0.5,
                description="黄体期心理影响强度 (0-1)",
                example="0.5"
            )
        },
        "kfc_integration": {
            "enabled": ConfigField(
                type=bool,
                default=True,
                description="是否启用KFC（私聊模式）集成"
            ),
            "mode": ConfigField(
                type=str,
                default="unified",
                description="KFC工作模式: unified(统一模式) 或 split(分离模式)",
                example="unified"
            ),
            "priority": ConfigField(
                type=int,
                default=100,
                description="KFC模式下提示词注入的优先级"
            )
        },
        "backup": {
            "auto_backup": ConfigField(
                type=bool,
                default=True,
                description="是否自动备份配置和数据"
            ),
            "backup_days": ConfigField(
                type=int,
                default=30,
                description="备份保留天数"
            )
        }
    }
    
    def get_plugin_components(self) -> List[Tuple[ComponentInfo, Type]]:
        """注册插件组件"""
        components = []
        
        # 总是注册状态更新处理器
        components.append((PeriodStateUpdateHandler.get_handler_info(), PeriodStateUpdateHandler))
        
        # 根据配置决定是否注册其他组件
        if self.get_config("plugin.enabled", False):
            components.append((PeriodStatePrompt.get_prompt_info(), PeriodStatePrompt))
            components.append((PeriodStatusCommand.get_command_info(), PeriodStatusCommand))
            components.append((SetPeriodCommand.get_command_info(), SetPeriodCommand))
            
        return components
    
    def __init__(self, *args, **kwargs):
        """插件初始化，增强错误处理和配置兼容"""
        super().__init__(*args, **kwargs)
        self._ensure_config_compatibility()
    
    def _ensure_config_compatibility(self):
        """确保配置向后兼容"""
        try:
            # 检查并升级配置版本
            current_version = self.get_config("plugin.config_version", "1.0.0")
            if current_version == "1.0.0":
                logger.info("检测到旧版本配置，正在升级...")
                
                # 设置新版本号
                self.set_config("plugin.config_version", "1.1.0")
                
                # 确保KFC集成配置存在
                if not self.has_config("kfc_integration.enabled"):
                    self.set_config("kfc_integration.enabled", True)
                    logger.info("添加KFC集成配置")
                
                if not self.has_config("kfc_integration.mode"):
                    self.set_config("kfc_integration.mode", "unified")
                    logger.info("添加KFC模式配置")
                
                if not self.has_config("kfc_integration.priority"):
                    self.set_config("kfc_integration.priority", 100)
                    logger.info("添加KFC优先级配置")
                
                # 确保其他新配置项存在
                if not self.has_config("plugin.debug_mode"):
                    self.set_config("plugin.debug_mode", False)
                    logger.info("添加调试模式配置")
                
                if not self.has_config("cycle.auto_detect"):
                    self.set_config("cycle.auto_detect", True)
                    logger.info("添加自动检测配置")
                
                if not self.has_config("backup.auto_backup"):
                    self.set_config("backup.auto_backup", True)
                    logger.info("添加自动备份配置")
                
                if not self.has_config("backup.backup_days"):
                    self.set_config("backup.backup_days", 30)
                    logger.info("添加备份天数配置")
                
                logger.info("配置升级完成")
            
            # 验证关键配置项
            self._validate_critical_configs()
            
        except Exception as e:
            logger.error(f"配置兼容性检查失败: {e}")
    
    def _validate_critical_configs(self):
        """验证关键配置项的有效性"""
        try:
            # 验证周期长度
            cycle_length = self.get_config("cycle.cycle_length", 28)
            if not isinstance(cycle_length, int) or cycle_length < 20 or cycle_length > 40:
                logger.warning(f"周期长度配置无效: {cycle_length}，使用默认值28")
                self.set_config("cycle.cycle_length", 28)
            
            # 验证影响强度值
            for stage in ["menstrual", "follicular", "ovulation", "luteal"]:
                for impact_type in ["physical", "psychological"]:
                    key = f"impacts.{stage}_{impact_type}"
                    value = self.get_config(key, 0.5)
                    if not isinstance(value, (int, float)) or value < 0 or value > 1:
                        logger.warning(f"影响强度配置无效: {key}={value}，使用默认值0.5")
                        self.set_config(key, 0.5)
            
            # 验证KFC模式
            kfc_mode = self.get_config("kfc_integration.mode", "unified")
            if kfc_mode not in ["unified", "split"]:
                logger.warning(f"KFC模式配置无效: {kfc_mode}，使用默认值unified")
                self.set_config("kfc_integration.mode", "unified")
            
            # 验证优先级
            priority = self.get_config("kfc_integration.priority", 100)
            if not isinstance(priority, int) or priority < 0 or priority > 1000:
                logger.warning(f"KFC优先级配置无效: {priority}，使用默认值100")
                self.set_config("kfc_integration.priority", 100)
            
            logger.info("关键配置验证完成")
            
        except Exception as e:
            logger.error(f"配置验证失败: {e}")