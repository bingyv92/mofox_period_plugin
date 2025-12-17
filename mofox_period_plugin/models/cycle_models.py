"""
周期数据模型
"""
from datetime import datetime
from calendar import monthrange


class CyclePhase:
    """周期阶段定义"""
    
    def __init__(self, name: str, name_cn: str, duration: int, day_in_phase: int):
        """
        初始化周期阶段
        
        Args:
            name: 阶段英文名
            name_cn: 阶段中文名
            duration: 阶段持续天数
            day_in_phase: 阶段内第几天
        """
        self.name = name
        self.name_cn = name_cn
        self.duration = duration
        self.day_in_phase = day_in_phase


class DualCycleData:
    """双周期数据模型"""
    
    def __init__(
        self,
        anchor_day: int,
        start_date: datetime,
        cycle1_length: int,
        cycle2_length: int,
        cycle1_menstrual_days: int,
        cycle2_menstrual_days: int
    ):
        """
        初始化双周期数据
        
        Args:
            anchor_day: 锚点日期（1-31）
            start_date: 起始锚点日期
            cycle1_length: 第一周期天数
            cycle2_length: 第二周期天数
            cycle1_menstrual_days: 第一周期月经天数
            cycle2_menstrual_days: 第二周期月经天数
        """
        self.anchor_day = anchor_day
        self.start_date = start_date
        self.cycle1_length = cycle1_length
        self.cycle2_length = cycle2_length
        self.cycle1_menstrual_days = cycle1_menstrual_days
        self.cycle2_menstrual_days = cycle2_menstrual_days
        self.total_days = cycle1_length + cycle2_length
        self.end_date = self._calculate_end_date()
    
    def _calculate_end_date(self) -> datetime:
        """计算结束锚点日期（下下个月的锚点日）"""
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
        """从字典恢复数据"""
        return cls(
            anchor_day=data["anchor_day"],
            start_date=datetime.fromisoformat(data["start_date"]),
            cycle1_length=data["cycle1_length"],
            cycle2_length=data["cycle2_length"],
            cycle1_menstrual_days=data["cycle1_menstrual_days"],
            cycle2_menstrual_days=data["cycle2_menstrual_days"]
        )
