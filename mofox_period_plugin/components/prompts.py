"""
Prompt组件
负责生成并注入周期状态提示词
"""
from typing import Dict, Any

from src.plugin_system import BasePrompt
from src.plugin_system.base.component_types import InjectionRule, InjectionType
from src.common.logger import get_logger

from ..managers import PeriodStateManager
from ..utils import PromptTemplates

logger = get_logger("mofox_period_plugin.prompts")


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
        self.state_manager = PeriodStateManager(get_config_func=self.get_config)
    
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
            config = self._collect_config()
            
            # 计算当前状态
            state = self.state_manager.calculate_current_state(config)
            
            # 生成提示词
            prompt = self._generate_prompt(state)
            
            if debug_mode:
                logger.debug(f"周期状态提示词: {prompt}")
            
            return prompt
            
        except Exception as e:
            logger.error(f"生成周期状态提示词失败: {e}")
            return ""
    
    def _collect_config(self) -> dict:
        """收集配置信息"""
        return {
            "levels.menstrual.physical": self.get_config("levels.menstrual_physical", 5),
            "levels.menstrual.psychological": self.get_config("levels.menstrual_psychological", 4),
            "levels.follicular.physical": self.get_config("levels.follicular_physical", 2),
            "levels.follicular.psychological": self.get_config("levels.follicular_psychological", 2),
            "levels.ovulation.physical": self.get_config("levels.ovulation_physical", 3),
            "levels.ovulation.psychological": self.get_config("levels.ovulation_psychological", 2),
            "levels.luteal.physical": self.get_config("levels.luteal_physical", 4),
            "levels.luteal.psychological": self.get_config("levels.luteal_psychological", 3),
        }
    
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
