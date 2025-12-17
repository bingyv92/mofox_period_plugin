"""
EventHandler组件
处理插件生命周期事件和用户消息事件
"""
from src.plugin_system import BaseEventHandler, EventType
from src.plugin_system.base.base_event import HandlerResult
from src.plugin_system.apis import storage_api, llm_api
from src.common.logger import get_logger

from ..managers import DualCycleManager, PeriodStateManager, LLMReliefManager

logger = get_logger("mofox_period_plugin.event_handlers")


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
                # 获取插件存储实例
                plugin_storage = storage_api.get_local_storage("mofox_period_plugin")
                
                # 初始化双周期管理器（传递配置获取函数）
                cycle_manager = DualCycleManager(get_config_func=self.get_config)
                
                anchor_day = self.get_config("cycle.anchor_day", 15)
                logger.info(f"双周期锚定模型初始化完成（锚点日期: 每月{anchor_day}号）")
                
                if cycle_manager.current_cycle:
                    logger.info(
                        f"当前双周期: 起始={cycle_manager.current_cycle.start_date.date()}, "
                        f"结束={cycle_manager.current_cycle.end_date.date()}, "
                        f"总天数={cycle_manager.current_cycle.total_days}"
                    )
                
        except Exception as e:
            logger.error(f"周期状态管理器初始化失败: {e}")
            
        return HandlerResult(success=True, continue_process=True)


class MessageReliefHandler(BaseEventHandler):
    """消息痛经缓解判定处理器
    
    订阅 ON_MESSAGE 事件，当用户发送消息时判断是否具有痛经缓解作用。
    如果判定有缓解作用，将临时降低痛经等级。
    """
    
    handler_name = "message_relief_handler"
    handler_description = "使用LLM判定用户消息是否对痛经有缓解作用"
    
    # 订阅消息事件（系统中只有 EventType.ON_MESSAGE）
    init_subscribe = [EventType.ON_MESSAGE]
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.state_manager = PeriodStateManager(get_config_func=self.get_config)
        self.relief_manager = None
    
    async def execute(self, params: dict) -> HandlerResult:
        """处理用户消息，判定是否有缓解作用
        
        Args:
            params: 事件参数，格式为 {"message": DatabaseMessages, ...}
        """
        try:
            # 检查是否启用LLM缓解功能
            enabled = self.get_config("plugin.enabled", False)
            llm_relief_enabled = self.get_config("dysmenorrhea.enable_llm_relief", True)
            
            if not enabled or not llm_relief_enabled:
                return HandlerResult(success=True, continue_process=True)
            
            # 初始化relief_manager
            if not self.relief_manager:
                config = self._collect_config()
                self.relief_manager = LLMReliefManager(config)
            
            # 检查当前是否在月经期
            config = self._collect_config()
            state = self.state_manager.calculate_current_state(config)
            current_stage = state.get("stage")
            dysmenorrhea_level = state.get("dysmenorrhea_level", 0)
            
            logger.debug(f"当前周期状态: 阶段={current_stage}, 痛经等级={dysmenorrhea_level}")
            
            # 只在月经期且有痛经时才进行判定
            if current_stage != "menstrual":
                logger.debug(f"跳过缓解判定: 当前非月经期（{current_stage}）")
                return HandlerResult(success=True, continue_process=True)
            
            if dysmenorrhea_level == 0:
                logger.debug("跳过缓解判定: 当前无痛经症状")
                return HandlerResult(success=True, continue_process=True)
            
            # 获取 DatabaseMessages 对象
            db_message = params.get("message")
            if not db_message or not hasattr(db_message, "processed_plain_text"):
                logger.debug("跳过缓解判定: 无法获取消息对象或文本内容")
                return HandlerResult(success=True, continue_process=True)
            
            # 获取消息文本内容
            message_text = db_message.processed_plain_text
            if not message_text or len(message_text.strip()) == 0:
                logger.debug("跳过缓解判定: 消息内容为空")
                return HandlerResult(success=True, continue_process=True)
            
            logger.info(f"📝 触发痛经缓解判定流程")
            logger.info(f"   当前痛经等级: {dysmenorrhea_level}级")
            logger.info(f"   消息内容: {message_text}")
            
            # 使用 LLM API 进行缓解判定
            has_relief = await self._judge_relief_with_llm(message_text)
            
            if has_relief:
                # 应用缓解效果
                self.relief_manager.apply_relief()
                logger.info(f"✅ 痛经缓解效果已生效！")
            else:
                logger.debug(f"❌ 消息未被判定为有缓解作用")
            
        except Exception as e:
            logger.error(f"消息缓解判定失败: {e}")
        
        return HandlerResult(success=True, continue_process=True)
    
    async def _judge_relief_with_llm(self, message_text: str) -> bool:
        """
        使用 LLM API 判断消息是否有缓解作用
        
        Args:
            message_text: 用户消息内容
            
        Returns:
            bool: True 表示有缓解作用
        """
        try:
            logger.info(f"========== 痛经缓解LLM判定开始 ==========")
            
            # 构造判定提示词
            prompt = f"""请判断以下用户消息是否对痛经有缓解作用。

缓解作用包括但不限于：
- 表达关心、安慰、理解
- 提供实用建议（热敷、喝热水、休息等）
- 询问需要帮助
- 提供情感支持和陪伴
- 物理安慰动作（抽抱、摸头、温暖的手等）
- 分散注意力的有趣内容

不包括：
- 普通闲聊
- 无关话题
- 责备或不理解的言论

用户消息："{message_text}"

请只回答"是"或"否"。"""
            
            logger.info(f"待判定消息: {message_text}")
            
            # 获取可用的LLM模型
            models = llm_api.get_available_models()
            if not models:
                logger.warning("⚠️ 无可用LLM模型，跳过判定")
                return False
            
            # 使用配置的模型或第一个可用模型
            model_name = self.get_config("dysmenorrhea.llm_model", "default")
            model_config = models.get(model_name) or next(iter(models.values()))
            
            # 获取模型名称
            actual_model_name = (
                getattr(model_config, "name", None) or
                getattr(model_config, "model_name", None) or
                getattr(model_config, "id", None) or
                str(model_name)
            )
            
            logger.info(f"🤖 使用模型: {actual_model_name}")
            
            # 调用LLM
            success, response, _, _ = await llm_api.generate_with_model(
                prompt=prompt,
                model_config=model_config,
                request_type="mofox_period_plugin.relief_judgment",
                temperature=0.3,
                max_tokens=10
            )
            
            if not success:
                logger.warning(f"❌ LLM调用失败: {response}")
                logger.info(f"========== 痛经缓解LLM判定失败 ==========\n")
                return False
            
            logger.info(f"LLM原始响应: '{response}'")
            
            # 解析响应
            result = response.strip().lower()
            has_relief = "是" in result or "yes" in result or "有" in result
            
            logger.info(f"判定结果: {'✅ 有缓解作用' if has_relief else '❌ 无缓解作用'}")
            
            if has_relief:
                duration = self.get_config("dysmenorrhea.relief_duration_minutes", 60)
                reduction = self.get_config("dysmenorrhea.relief_reduction", 1)
                logger.info(f"🌟 消息被判定具有痛经缓解作用！")
                logger.info(f"   缓解参数: 降低{reduction}级, 持续{duration}分钟")
            
            logger.info(f"========== 痛经缓解LLM判定结束 ==========\n")
            return has_relief
            
        except Exception as e:
            logger.error(f"❌ LLM判定过程出错: {e}", exc_info=True)
            return False
    
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
            "dysmenorrhea.prob_none": self.get_config("dysmenorrhea.prob_none", 0.25),
            "dysmenorrhea.prob_mild": self.get_config("dysmenorrhea.prob_mild", 0.30),
            "dysmenorrhea.prob_moderate": self.get_config("dysmenorrhea.prob_moderate", 0.25),
            "dysmenorrhea.prob_severe": self.get_config("dysmenorrhea.prob_severe", 0.20),
            "dysmenorrhea.enable_llm_relief": self.get_config("dysmenorrhea.enable_llm_relief", True),
            "dysmenorrhea.relief_duration_minutes": self.get_config("dysmenorrhea.relief_duration_minutes", 60),
            "dysmenorrhea.relief_reduction": self.get_config("dysmenorrhea.relief_reduction", 1),
        }
