"""
双周期锚定管理器
负责生成和管理双周期数据
"""
from datetime import datetime, timedelta
from calendar import monthrange
from typing import Optional, Tuple
import random

from src.plugin_system.apis import storage_api
from src.common.logger import get_logger

from ..models import CyclePhase, DualCycleData

logger = get_logger("mofox_period_plugin.cycle_manager")
plugin_storage = storage_api.get_local_storage("mofox_period_plugin")


class DualCycleManager:
    """双周期锚定管理器"""
    
    def __init__(self, get_config_func=None):
        """
        初始化管理器
        
        Args:
            get_config_func: 配置获取函数，用于从config读取anchor_day
        """
        self.current_cycle: Optional[DualCycleData] = None
        self.get_config = get_config_func
        self._sync_anchor_day_from_config()  # 同步配置到storage
        self._load_or_generate_cycle()
    
    def _sync_anchor_day_from_config(self):
        """从配置文件同步锚点日期到storage"""
        if self.get_config:
            config_anchor = self.get_config("cycle.anchor_day", None)
            if config_anchor is not None:
                storage_anchor = plugin_storage.get("anchor_day", None)
                if storage_anchor != config_anchor:
                    logger.info(f"同步锚点日期: config={config_anchor}, storage={storage_anchor} → {config_anchor}")
                    plugin_storage.set("anchor_day", config_anchor)
                    # 清除旧的双周期数据，强制重新生成
                    plugin_storage.delete("dual_cycle_data")
    
    def _load_or_generate_cycle(self):
        """
        加载或生成双周期数据
        
        逻辑流程：
        1. 从配置文件读取当前锚点日期
        2. 尝试加载已存储的周期数据
        3. 如果存储的周期锚点与配置不同 → 重新生成并保存
        4. 如果周期已过期 → 重新生成并保存
        5. 否则 → 使用已存储的周期（状态化读取）
        """
        stored_cycle = plugin_storage.get("dual_cycle_data", None)
        # 从配置文件读取当前配置的锚点日期
        config_anchor = self.get_config("cycle.anchor_day", 15) if self.get_config else 15
        
        if stored_cycle:
            try:
                self.current_cycle = DualCycleData.from_dict(stored_cycle)
                today = datetime.now()
                
                # 优先级1: 检查锚点配置是否改变
                if self.current_cycle.anchor_day != config_anchor:
                    logger.warning(
                        f"⚠️ 检测到锚点日期配置变更: {self.current_cycle.anchor_day}号 → {config_anchor}号\n"
                        f"   原周期: {self.current_cycle.start_date.date()} ~ {self.current_cycle.end_date.date()}\n"
                        f"   正在重新生成周期并保存..."
                    )
                    self._generate_new_cycle()
                    logger.info(f"✅ 新周期已生成并保存（锚点={config_anchor}号），之后将使用此固定周期")
                # 优先级2: 检查周期是否已过期
                elif today >= self.current_cycle.end_date:
                    logger.info(f"双周期已过期（结束日期={self.current_cycle.end_date.date()}），重新生成")
                    self._generate_new_cycle()
                    logger.info(f"✅ 新周期已生成并保存，之后将使用此固定周期")
                # 正常情况: 读取已存储的固定周期
                else:
                    logger.debug(
                        f"📖 读取已存储的双周期数据:\n"
                        f"   锚点日期: {self.current_cycle.anchor_day}号\n"
                        f"   周期范围: {self.current_cycle.start_date.date()} ~ {self.current_cycle.end_date.date()}\n"
                        f"   剩余天数: {(self.current_cycle.end_date - today).days}天"
                    )
            except Exception as e:
                logger.error(f"加载双周期数据失败: {e}，重新生成")
                self._generate_new_cycle()
        else:
            logger.info("首次运行，生成双周期数据并保存")
            self._generate_new_cycle()
            logger.info(f"✅ 首次周期已生成并保存（锚点={config_anchor}号），之后将使用此固定周期")
    
    def _generate_new_cycle(self):
        """
        生成新的双周期数据
        ⚠️ 锚点日期 = 月经期第1天
        """
        # 从配置文件获取锚点日期配置，默认为15号
        anchor_day = self.get_config("cycle.anchor_day", 15) if self.get_config else 15
        
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
        
        # 计算到下下个月锚点的总天数（双周期模型）
        next_next_anchor_date = self._get_next_next_anchor_date(start_date, anchor_day)
        total_days = (next_next_anchor_date - start_date).days
        
        # 生成周期长度
        cycle1_length, cycle2_length = self._calculate_cycle_lengths(total_days)
        
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
        
        logger.info(
            f"生成新双周期（锚点={anchor_day}号=月经开始）: "
            f"起始={start_date.date()}, "
            f"结束={next_next_anchor_date.date()}, "
            f"周期1={cycle1_length}天(月经{cycle1_menstrual_days}天), "
            f"周期2={cycle2_length}天(月经{cycle2_menstrual_days}天), "
            f"总计={total_days}天"
        )
    
    def _calculate_cycle_lengths(self, total_days: int) -> Tuple[int, int]:
        """计算两个周期的长度"""
        # 确保总天数足够（至少50天才能容纳两个25天周期）
        if total_days < 50:
            logger.warning(f"两个锚点间隔太短({total_days}天)，调整周期长度")
            cycle1_length = total_days // 2
            cycle2_length = total_days - cycle1_length
        else:
            # 正常情况：生成第一周期（25-35天）
            min_cycle1 = 25
            max_cycle1 = min(35, total_days - 25)  # 保证第二周期至少25天
            
            if max_cycle1 < min_cycle1:
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
        
        return cycle1_length, cycle2_length
    
    def _get_next_next_anchor_date(self, from_date: datetime, anchor_day: int) -> datetime:
        """计算下下个月的锚点日期（双周期模型）"""
        current = from_date
        
        # 第一次跳：跳到下一个月
        if current.month == 12:
            next_month = current.replace(year=current.year + 1, month=1, day=1)
        else:
            next_month = current.replace(month=current.month + 1, day=1)
        
        # 第二次跳：跳到下下个月
        if next_month.month == 12:
            next_next_month = next_month.replace(year=next_month.year + 1, month=1, day=1)
        else:
            next_next_month = next_month.replace(month=next_month.month + 1, day=1)
        
        # 获取下下个月的锚点日
        days_in_month = monthrange(next_next_month.year, next_next_month.month)[1]
        anchor = min(anchor_day, days_in_month)
        
        return next_next_month.replace(day=anchor)
    
    def get_current_phase(self, query_date: Optional[datetime] = None) -> Tuple[CyclePhase, int, int]:
        """
        获取指定日期的周期阶段
        
        Args:
            query_date: 查询日期，默认为当天
            
        Returns:
            Tuple[CyclePhase, 周期编号(1或2), 周期内第几天]
        """
        if query_date is None:
            query_date = datetime.now()
        
        # 确保有有效的周期数据
        if not self.current_cycle:
            self._generate_new_cycle()
        
        # 如果查询日期超出当前周期，重新生成
        if self.current_cycle and query_date >= self.current_cycle.end_date:
            self._generate_new_cycle()
        
        # 再次确认 current_cycle 存在
        if not self.current_cycle:
            raise RuntimeError("生成周期数据失败")
        
        # 计算距离起始日期的天数
        days_from_start = (query_date - self.current_cycle.start_date).days
        
        # 如果是负数，说明查询日期在当前周期之前，需要重新生成
        if days_from_start < 0:
            self._generate_new_cycle()
            if not self.current_cycle:
                raise RuntimeError("生成周期数据失败")
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
    
    def _calculate_phase(self, day_in_cycle: int, cycle_length: int, menstrual_days: int) -> CyclePhase:
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
