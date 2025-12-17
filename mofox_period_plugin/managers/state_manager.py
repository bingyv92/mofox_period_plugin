"""
周期状态管理器
负责计算和管理月经周期状态
"""
from datetime import datetime
from typing import Dict, Any, Optional
import random

from src.plugin_system.apis import storage_api
from src.common.logger import get_logger

from .cycle_manager import DualCycleManager

logger = get_logger("mofox_period_plugin.state_manager")
plugin_storage = storage_api.get_local_storage("mofox_period_plugin")


class PeriodStateManager:
    """月经周期状态管理器"""
    
    def __init__(self, get_config_func=None):
        """初始化状态管理器
        
        Args:
            get_config_func: 配置获取函数，用于从config读取配置值
        """
        self.cycle_manager = DualCycleManager(get_config_func=get_config_func)
        self.last_calculated_date = None
        self.current_state = None
    
    def calculate_current_state(self, config: dict) -> Dict[str, Any]:
        """
        计算当前周期状态
        
        Args:
            config: 配置字典，包含各阶段的等级配置
            
        Returns:
            包含当前状态信息的字典
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
            
            # 痛经等级计算（仅在月经期）
            if phase.name == "menstrual":
                dysmenorrhea_level = self._calculate_dysmenorrhea_level(
                    phase.day_in_phase, 
                    cycle_num,
                    today,
                    config
                )
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
    
    def _calculate_dysmenorrhea_level(self, day_in_phase: int, cycle_num: int, today: datetime, config: dict) -> int:
        """
        计算痛经等级
        
        新逻辑：
        1. 痛经随机发生（每个周期独立随机，概率可配置）
        2. 第一天是峰值-1（次一级）
        3. 第二天是峰值
        4. 之后逐天下降
        5. 等级必须 <= 剩余天数（避免出现等级6但只剩1天的情况）
        6. 支持LLM判定的临时缓解效果
        
        Args:
            day_in_phase: 月经期内第几天
            cycle_num: 第几个周期
            today: 当前日期
            config: 配置字典，包含痛经概率配置
            
        Returns:
            痛经等级 0-6
        """
        # 为当前周期生成痛经信息（使用周期编号作为key）
        cycle_key = f"dysmenorrhea_cycle{cycle_num}"
        dysmenorrhea_data = plugin_storage.get(cycle_key, None)
        
        # 检查是否需要重新生成（新周期或日期变化）
        current_date_str = today.date().isoformat()
        
        if dysmenorrhea_data is None or dysmenorrhea_data.get("last_check_date") != current_date_str:
            # 第一次进入该周期的月经期，随机生成痛经等级
            if dysmenorrhea_data is None:
                # 从配置读取概率（使用可配置的概率）
                prob_none = config.get("dysmenorrhea.prob_none", 0.25)
                prob_mild = config.get("dysmenorrhea.prob_mild", 0.30)
                prob_moderate = config.get("dysmenorrhea.prob_moderate", 0.25)
                # prob_severe = 1.0 - prob_none - prob_mild - prob_moderate
                
                # 随机是否有痛经
                rand = random.random()
                threshold_none = prob_none
                threshold_mild = threshold_none + prob_mild
                threshold_moderate = threshold_mild + prob_moderate
                
                if rand < threshold_none:  # 无痛经
                    peak_level = 0
                elif rand < threshold_mild:  # 轻度痛经(1-2)
                    peak_level = random.randint(1, 2)
                elif rand < threshold_moderate:  # 中度痛经(3-4)
                    peak_level = random.randint(3, 4)
                else:  # 重度痛经(5-6)
                    peak_level = random.randint(5, 6)
                
                dysmenorrhea_data = {
                    "peak_level": peak_level,
                    "last_check_date": current_date_str
                }
                plugin_storage.set(cycle_key, dysmenorrhea_data)
                logger.info(f"周期{cycle_num}痛经峰值等级: {peak_level}")
            else:
                # 只更新检查日期
                dysmenorrhea_data["last_check_date"] = current_date_str
                plugin_storage.set(cycle_key, dysmenorrhea_data)
        
        peak_level = dysmenorrhea_data["peak_level"]
        
        # 如果没有痛经，直接返回0
        if peak_level == 0:
            return 0
        
        # 计算当前痛经等级
        if day_in_phase == 1:
            # 第一天：峰值-1（但不低于1）
            current_level = max(1, peak_level - 1)
        elif day_in_phase == 2:
            # 第二天：峰值
            current_level = peak_level
        else:
            # 第三天及以后：逐天下降
            days_after_peak = day_in_phase - 2
            current_level = max(0, peak_level - days_after_peak)
        
        # 确保等级不超过剩余天数（关键约束）
        # 如果等级为6，至少需要6天（第1天等级5，第2天等级6，第3-7天递减）
        # 如果等级为5，至少需要5天（第1天等级4，第2天等级5，第3-6天递减）
        # 通用公式：等级 N 需要至少 N+1 天
        max_level_for_remaining = day_in_phase - 1  # 当前是第几天，最大等级就是几
        if day_in_phase == 1:
            max_level_for_remaining = 6  # 第一天可以是任何等级（因为还不知道总共几天）
        
        current_level = min(current_level, max_level_for_remaining)
        
        # 检查是否有LLM判定的临时缓解效果
        relief_data = plugin_storage.get("dysmenorrhea_relief", None)
        if relief_data and config.get("dysmenorrhea.enable_llm_relief", True):
            try:
                relief_end_time = datetime.fromisoformat(relief_data["end_time"])
                now = datetime.now()
                if now < relief_end_time:
                    # 缓解效果仍在持续
                    original_level = current_level
                    relief_reduction = config.get("dysmenorrhea.relief_reduction", 1)
                    current_level = max(0, current_level - relief_reduction)
                    
                    remaining_minutes = int((relief_end_time - now).total_seconds() / 60)
                    logger.info(f"💊 痛经缓解效果生效中！")
                    logger.info(f"   原始等级: {original_level}级")
                    logger.info(f"   降低等级: {relief_reduction}级")
                    logger.info(f"   当前等级: {current_level}级")
                    logger.info(f"   剩余时间: {remaining_minutes}分钟")
                    logger.info(f"   失效时间: {relief_end_time.strftime('%H:%M:%S')}")
                else:
                    # 缓解效果已过期
                    logger.info(f"⏰ 痛经缓解效果已过期（失效时间: {relief_end_time.strftime('%H:%M:%S')}），自动清除")
                    plugin_storage.delete("dysmenorrhea_relief")
            except Exception as e:
                logger.warning(f"解析缓解数据失败: {e}", exc_info=True)
        
        return current_level
    
    def _get_stage_description(self, stage: str) -> str:
        """获取阶段描述"""
        descriptions = {
            "menstrual": "身体不适，情绪敏感，需要更多休息和理解",
            "follicular": "状态恢复，情绪平稳，思维清晰",
            "ovulation": "状态较佳，情绪积极，表达流畅",
            "luteal": "身体疲惫，情绪波动，需要更多耐心"
        }
        return descriptions.get(stage, "")
