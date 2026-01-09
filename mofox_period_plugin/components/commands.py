"""
Command组件
提供用户交互命令
"""
from typing import Tuple, Dict, Any, Optional

from src.plugin_system import PlusCommand, CommandArgs, ChatType
from src.common.logger import get_logger

from ..managers import PeriodStateManager

logger = get_logger("mofox_period_plugin.commands")


class PeriodStatusCommand(PlusCommand):
    """查询当前月经周期状态命令"""
    
    command_name = "period_status"
    command_description = "查询当前月经周期状态"
    command_aliases = ["period", "月经状态", "周期状态"]
    chat_type_allow = ChatType.PRIVATE
    priority = 10
    intercept_message = True  # 确保拦截消息，不进入后续处理流程
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.state_manager = PeriodStateManager(get_config_func=self.get_config)
    
    async def execute(self, args: CommandArgs) -> Tuple[bool, Optional[str], bool]:
        """执行状态查询
        
        Returns:
            Tuple[bool, Optional[str], bool]: (执行成功, 日志描述, 拦截标志)
            注意：第三个参数 True 表示要拦截，message_handler 会对其取反
        """
        try:
            enabled = self.get_config("plugin.enabled", False)
            
            if not enabled:
                await self.send_text("❌ 月经周期插件未启用")
                return True, "插件未启用", True
            
            # 收集配置
            config = self._collect_config()
            
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
            report += f"\n🔥 痛经程度: 等级 {state['dysmenorrhea_level']}/6 (第{state['day_in_phase']}天)"
        
        report += f"""

📝 状态描述:
{state['description']}
━━━━━━━━━━━━━━━━━━
💡 提示: 等级越高影响越严重
💡 痛经等级(0-6)每周期随机生成，第2天达峰值后逐日下降
💡 使用 /regenerate_cycle 重新生成双周期
💡 可在配置文件中调整各阶段影响等级"""
        
        return report.strip()


class RegenerateCycleCommand(PlusCommand):
    """重新生成双周期命令"""
    
    command_name = "regenerate_cycle"
    command_description = "强制重新生成双周期数据"
    command_aliases = ["重新生成周期", "刷新周期", "regenerate"]
    chat_type_allow = ChatType.PRIVATE
    priority = 10
    intercept_message = True  # 确保拦截消息，不进入后续处理流程
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.state_manager = PeriodStateManager(get_config_func=self.get_config)
    
    async def execute(self, args: CommandArgs) -> Tuple[bool, Optional[str], bool]:
        """执行重新生成周期
        
        Returns:
            Tuple[bool, Optional[str], bool]: (执行成功, 日志描述, 拦截标志)
            注意：第三个参数 True 表示要拦截，message_handler 会对其取反
        """
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
