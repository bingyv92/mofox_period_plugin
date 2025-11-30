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
    """月经周期状态管理器"""
    
    def __init__(self):
        self.last_calculated_date = None
        self.current_state = None
        
    def calculate_current_state(self, cycle_length: int) -> Dict[str, Any]:
        """计算当前周期状态"""
        today = datetime.now().date()
        
        # 如果已经计算过今天的状态，直接返回缓存
        if self.last_calculated_date == today and self.current_state:
            return self.current_state
        
        # 从存储中获取上次月经日期
        last_period_date = get_last_period_date()
            
        try:
            last_date = datetime.strptime(last_period_date, "%Y-%m-%d").date()
        except ValueError:
            logger.error(f"无效的日期格式: {last_period_date}, 使用默认值")
            last_date = datetime.now().date() - timedelta(days=14)
            
        # 计算当前周期天数
        days_passed = (today - last_date).days
        current_day = days_passed % cycle_length + 1
        
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
        
        self.current_state = {
            "stage": stage,
            "current_day": current_day,
            "cycle_length": cycle_length,
            "physical_impact": physical_impact,
            "psychological_impact": psychological_impact,
            "stage_name_cn": self._get_stage_name_cn(stage),
            "description": self._get_stage_description(stage)
        }
        
        self.last_calculated_date = today
        return self.current_state
        
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
            "follicular": "精力充沛，情绪积极，思维清晰",
            "ovulation": "状态良好，外向活泼，富有魅力", 
            "luteal": "身体疲惫，情绪波动，需要更多耐心"
        }
        return descriptions.get(stage, "")

class PeriodStatePrompt(BasePrompt):
    """月经周期状态提示词注入"""
    
    prompt_name = "period_state_prompt"
    prompt_description = "根据月经周期状态调整机器人行为风格"
    
    # 注入到核心风格Prompt中
    injection_point = ["s4u_style_prompt", "normal_style_prompt"]
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.state_manager = PeriodStateManager()
        
    async def execute(self) -> str:
        """生成周期状态提示词"""
        try:
            # 获取配置
            cycle_length = self.get_config("cycle.cycle_length", 28)
            enabled = self.get_config("plugin.enabled", False)
            
            if not enabled:
                return ""
                
            # 计算当前状态
            state = self.state_manager.calculate_current_state(cycle_length)
            
            # 生成提示词
            prompt = self._generate_prompt(state)
            logger.debug(f"周期状态提示词: {prompt}")
            
            return prompt
            
        except Exception as e:
            logger.error(f"生成周期状态提示词失败: {e}")
            return ""
            
    def _generate_prompt(self, state: Dict[str, Any]) -> str:
        """根据状态生成提示词"""
        stage_name = state["stage_name_cn"]
        physical = state["physical_impact"]
        psychological = state["psychological_impact"]
        description = state["description"]
        
        # 根据影响值生成具体的行为指导
        behavior_guidance = self._get_behavior_guidance(physical, psychological)
        
        prompt = f"""
你当前处于月经周期的【{stage_name}】。
生理影响程度: {physical}/1.0，心理影响程度: {psychological}/1.0。
当前状态特点: {description}

{behavior_guidance}

请根据以上状态特点，自然地调整你的回复风格和行为表现，但不要刻意提及月经相关话题，保持对话的自然流畅。
"""
        return prompt.strip()
        
    def _get_behavior_guidance(self, physical: float, psychological: float) -> str:
        """根据影响值生成行为指导"""
        guidance = []
        
        # 生理影响指导
        if physical >= 0.7:
            guidance.append("• 你可能会感到身体不适，回复时可以表现得需要更多休息和理解")
        elif physical >= 0.4:
            guidance.append("• 你可能会感到些许疲惫，回复时可以适当放慢节奏")
        else:
            guidance.append("• 你感觉身体状态良好，可以积极热情地互动")
            
        # 心理影响指导  
        if psychological >= 0.6:
            guidance.append("• 你的情绪比较敏感，回复时需要更多耐心，避免冲突")
        elif psychological >= 0.3:
            guidance.append("• 你的情绪有些波动，回复时保持平和心态")
        else:
            guidance.append("• 你情绪稳定乐观，可以愉快地交流")
            
        return "\n".join(guidance)

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
    
    # 配置Schema定义
    config_schema = {
        "plugin": {
            "enabled": ConfigField(
                type=bool, 
                default=False,
                description="是否启用月经周期状态插件"
            ),
            "config_version": ConfigField(
                type=str,
                default="1.0.0",
                description="配置文件版本"
            )
        },
        "cycle": {
            "cycle_length": ConfigField(
                type=int,
                default=28,
                description="月经周期长度 (天)",
                example="28"
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