"""
MoFox Period Plugin - 月经周期状态插件
使用双周期锚定模型来模拟真实的月经周期变化

重构版本 - 模块化设计，易于维护
"""
from typing import List, Tuple, Type

from src.plugin_system import BasePlugin, register_plugin, ComponentInfo, ConfigField
from src.common.logger import get_logger

# 导入组件
from .components import (
    PeriodStatePrompt,
    PeriodStatusCommand,
    RegenerateCycleCommand,
    PeriodStateUpdateHandler,
    MessageReliefHandler
)

logger = get_logger("mofox_period_plugin")


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
        "dysmenorrhea": {
            "prob_none": ConfigField(
                type=float,
                default=0.25,
                description="无痛经概率（0.0-1.0）"
            ),
            "prob_mild": ConfigField(
                type=float,
                default=0.30,
                description="轻度痛经概率（1-2级，0.0-1.0）"
            ),
            "prob_moderate": ConfigField(
                type=float,
                default=0.25,
                description="中度痛经概率（3-4级，0.0-1.0）"
            ),
            "prob_severe": ConfigField(
                type=float,
                default=0.20,
                description="重度痛经概率（5-6级，0.0-1.0）"
            ),
            "enable_llm_relief": ConfigField(
                type=bool,
                default=True,
                description="是否启用LLM判定消息缓解痛经功能"
            ),
            "relief_duration_minutes": ConfigField(
                type=int,
                default=60,
                description="缓解效果持续时间（分钟）"
            ),
            "relief_reduction": ConfigField(
                type=int,
                default=1,
                description="缓解时降低的痛经等级（0-6）"
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
            # 注册消息缓解判定处理器（如果启用LLM缓解功能）
            if self.get_config("dysmenorrhea.enable_llm_relief", True):
                components.append((
                    MessageReliefHandler.get_handler_info(),
                    MessageReliefHandler
                ))
            
            # Prompt组件
            components.append((
                PeriodStatePrompt.get_prompt_info(),
                PeriodStatePrompt
            ))
            
            # Command组件
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
        logger.info("月经周期插件已加载（双周期锚定模型 v3.0 - 重构版）")
