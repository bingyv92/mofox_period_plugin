"""
LLM判定管理器
负责使用LLM判断用户消息是否具有痛经缓解作用
"""
from datetime import datetime, timedelta
from typing import Optional

from src.plugin_system.apis import storage_api
from src.common.logger import get_logger

logger = get_logger("mofox_period_plugin.llm_relief_manager")
plugin_storage = storage_api.get_local_storage("mofox_period_plugin")


class LLMReliefManager:
    """LLM痛经缓解判定管理器"""
    
    # LLM判定提示词
    RELIEF_JUDGMENT_PROMPT = """请判断以下用户消息是否对痛经有缓解作用。
    
缓解作用包括但不限于：
- 表达关心、安慰、理解
- 提供实用建议（热敷、喝热水、休息等）
- 询问需要帮助
- 提供情感支持
- 分散注意力的有趣内容

不包括：
- 普通闲聊
- 无关话题
- 责备或不理解的言论

用户消息：{message}

请只回答"是"或"否"。"""
    
    def __init__(self, config: dict):
        """
        初始化LLM判定管理器
        
        Args:
            config: 配置字典
        """
        self.config = config
        self.enabled = config.get("dysmenorrhea.enable_llm_relief", True)
        self.duration_minutes = config.get("dysmenorrhea.relief_duration_minutes", 60)
        self.reduction = config.get("dysmenorrhea.relief_reduction", 1)
    
    async def judge_relief_effect(self, message: str, llm_client) -> bool:
        """
        使用LLM判断消息是否有缓解作用
        
        Args:
            message: 用户消息内容
            llm_client: LLM客户端实例
            
        Returns:
            bool: True表示有缓解作用，False表示无缓解作用
        """
        if not self.enabled:
            return False
        
        try:
            # 构造判定提示词
            prompt = self.RELIEF_JUDGMENT_PROMPT.format(message=message)
            
            # 调用LLM进行判断
            response = await llm_client.chat_completion(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,  # 降低随机性，使判断更稳定
                max_tokens=10
            )
            
            # 解析响应
            result = response.strip().lower()
            has_relief = "是" in result or "yes" in result
            
            if has_relief:
                logger.info(f"LLM判定消息具有缓解作用: {message[:50]}...")
            
            return has_relief
            
        except Exception as e:
            logger.error(f"LLM判定失败: {e}")
            return False
    
    def apply_relief(self):
        """应用缓解效果"""
        if not self.enabled:
            return
        
        now = datetime.now()
        end_time = now + timedelta(minutes=self.duration_minutes)
        
        relief_data = {
            "end_time": end_time.isoformat(),
            "reduction": self.reduction,
            "applied_at": now.isoformat()
        }
        
        plugin_storage.set("dysmenorrhea_relief", relief_data)
        logger.info(f"💊 痛经缓解效果已应用！")
        logger.info(f"   降低等级: {self.reduction}级")
        logger.info(f"   持续时间: {self.duration_minutes}分钟")
        logger.info(f"   生效时间: {now.strftime('%H:%M:%S')}")
        logger.info(f"   失效时间: {end_time.strftime('%H:%M:%S')}")
    
    def get_current_relief(self) -> Optional[dict]:
        """获取当前有效的缓解效果"""
        relief_data = plugin_storage.get("dysmenorrhea_relief", None)
        
        if not relief_data:
            return None
        
        try:
            end_time = datetime.fromisoformat(relief_data["end_time"])
            if datetime.now() < end_time:
                return relief_data
            else:
                # 缓解效果已过期，清除数据
                plugin_storage.delete("dysmenorrhea_relief")
                return None
        except Exception as e:
            logger.error(f"解析缓解数据失败: {e}")
            return None
    
    def clear_relief(self):
        """清除缓解效果"""
        plugin_storage.delete("dysmenorrhea_relief")
        logger.info("痛经缓解效果已清除")
