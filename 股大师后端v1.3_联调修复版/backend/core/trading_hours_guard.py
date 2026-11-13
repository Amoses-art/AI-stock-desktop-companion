"""
交易时段守卫 — 减少非交易时间无效请求

架构决策(ADR-021): 拦截放在 QuoteService 统一入口，默认时段 09:20-15:00，
节假日用 chinese_calendar 判断。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Optional


@dataclass
class TradingHoursConfig:
    start_time: time = time(9, 20)
    end_time: time = time(15, 0)


class TradingHoursGuard:
    """交易时段守卫"""

    DEFAULT_CONFIG = TradingHoursConfig()

    @classmethod
    def configure(cls, start: str = "09:00", end: str = "15:00") -> None:
        """从配置注入交易时段（M1-R2 G1：接线 user_config，main.py 启动时调用）

        格式 "HH:MM"；解析失败保持默认值不抛异常（守卫是基础设施，不能阻塞启动）。
        """
        try:
            sh, sm = start.split(":")
            eh, em = end.split(":")
            cls.DEFAULT_CONFIG = TradingHoursConfig(
                start_time=time(int(sh), int(sm)),
                end_time=time(int(eh), int(em)),
            )
        except (ValueError, AttributeError):
            pass

    @staticmethod
    def is_lunch_break(now: Optional[datetime] = None) -> bool:
        """是否 A 股午休（11:30-13:00）——用于轮询降频"""
        if now is None:
            now = datetime.now()
        return time(11, 30) <= now.time() < time(13, 0)

    @staticmethod
    def is_trading_time(now: Optional[datetime] = None) -> bool:
        """判断当前是否为交易时段"""
        if now is None:
            now = datetime.now()

        # 1. 周末一律休市（A股/港股/美股周末均不交易；
        #    chinese_calendar 的"调休补班"只影响企事业单位，不影响股市）
        if now.weekday() >= 5:  # 周六=5, 周日=6
            return False

        # 2. 法定节假日休市（chinese_calendar 处理调休工作日）
        try:
            import chinese_calendar as cc
            if not cc.is_workday(now.date()):
                return False
        except ImportError:
            pass  # 未安装时仅靠 weekday 过滤周末

        # 3. 是否在交易时段内
        cfg = TradingHoursGuard.DEFAULT_CONFIG
        return cfg.start_time <= now.time() <= cfg.end_time

    @staticmethod
    def get_next_trading_time(now: Optional[datetime] = None) -> Optional[datetime]:
        """返回下一个交易开始时间（用于缓存 TTL 计算）"""
        if now is None:
            now = datetime.now()

        cfg = TradingHoursGuard.DEFAULT_CONFIG
        today_start = datetime.combine(now.date(), cfg.start_time)

        if now < today_start:
            return today_start

        # 找下一个工作日
        try:
            import chinese_calendar as cc
            next_day = now.date() + timedelta(days=1)
            while not cc.is_workday(next_day):
                next_day += timedelta(days=1)
            return datetime.combine(next_day, cfg.start_time)
        except ImportError:
            next_day = now.date() + timedelta(days=1)
            while next_day.weekday() >= 5:
                next_day += timedelta(days=1)
            return datetime.combine(next_day, cfg.start_time)

    @staticmethod
    def get_trading_hours_comment(now: Optional[datetime] = None) -> str:
        """获取当前交易时段状态说明"""
        if TradingHoursGuard.is_trading_time(now):
            return "交易中"

        if now is None:
            now = datetime.now()

        cfg = TradingHoursGuard.DEFAULT_CONFIG
        if now.time() < cfg.start_time:
            return "盘前"
        if now.time() > cfg.end_time:
            return "盘后"
        return "非交易日"
