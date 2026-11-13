"""
提醒引擎 — 绑定 QuoteService 轮询生命周期

架构决策(ADR-016): AlertEngine 作为 QuoteService 的回调组件，不复用独立定时器，
避免多轮询竞争。评估为同步方法（CPU 轻量），所有异常被包裹，不中断轮询。
"""

from __future__ import annotations

import calendar
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from data.adapters.base import QuoteData


@dataclass
class AlertEvent:
    """提醒事件"""
    symbol: str
    name: str
    direction: str  # "up" | "down"
    percent: float
    message: str
    current_price: float = 0.0  # 触发时现价（前端契约字段）
    rule_id: Optional[int] = None  # None 表示默认规则触发
    timestamp: float = field(default_factory=time.time)


@dataclass
class AlertRule:
    """提醒规则（内存表示）"""
    id: int
    portfolio_id: int
    symbol: str
    name: str
    threshold_percent: float
    direction: str  # "up" | "down" | "both"
    is_active: bool
    last_triggered_at: Optional[float]
    cooldown_minutes: int


class AlertEngine:
    """提醒引擎 — 绑定 QuoteService 轮询生命周期"""

    # 默认骤然涨跌阈值
    DEFAULT_THRESHOLD_PERCENT = 3.0
    # 默认 cooldown（分钟）
    DEFAULT_COOLDOWN_MINUTES = 5

    def __init__(self) -> None:
        # 默认规则的 cooldown 记录：symbol -> 上次触发时间戳
        self._default_cooldowns: Dict[str, float] = {}
        # 阈值穿越状态：symbol -> 上一轮是否处于提醒区间内（|change|>=阈值）
        # 仅当从区间外穿越到区间内时才触发，区间内持续不重复提醒
        self._default_in_zone: Dict[str, bool] = {}
        # 用户规则的阈值穿越状态：rule_id -> 上一轮是否处于提醒区间内
        self._user_rule_in_zone: Dict[int, bool] = {}

    async def evaluate(self, quotes: List[QuoteData]) -> List[AlertEvent]:
        """评估所有活跃规则，返回触发事件列表。

        执行流程：
        1. 从数据库加载所有活跃的用户自定义规则
        2. 对每个 quote，依次检查默认规则和用户规则
        3. 返回所有触发事件（已按 symbol 去重 cooldown）
        """
        events: List[AlertEvent] = []

        # 加载用户自定义规则
        rules = await self._load_active_rules()
        rules_by_symbol: Dict[str, List[AlertRule]] = {}
        for rule in rules:
            rules_by_symbol.setdefault(rule.symbol, []).append(rule)

        for quote in quotes:
            symbol = quote.symbol

            # 1. 检查默认骤然涨跌规则
            #    用户已为该标的自定义阈值规则时（如添加持仓时设置 1-20% 阈值），
            #    默认 3% 规则被替代，不再触发，避免双重提醒
            if symbol not in rules_by_symbol:
                default_event = self._check_default_rules(quote)
                if default_event:
                    events.append(default_event)

            # 2. 检查用户自定义规则
            user_rules = rules_by_symbol.get(symbol, [])
            for rule in user_rules:
                event = self._check_user_rule(quote, rule)
                if event:
                    events.append(event)

        # 批量更新触发时间（用户规则写入 DB，默认规则更新内存）
        await self._mark_triggered(events)
        return events

    def _check_default_rules(self, quote: QuoteData) -> Optional[AlertEvent]:
        """默认骤然涨跌检测：阈值穿越触发

        逻辑：
        - 跟踪每轮 |change_percent| 是否 >= 阈值（处于提醒区间）
        - 仅当从区间外穿越到区间内时触发提醒
        - 区间内持续不重复提醒
        - 回落到区间内后再次上穿才会重新提醒
        - cooldown 作为辅助防抖（防止阈值附近反复穿越刷屏）
        """
        symbol = quote.symbol
        now = time.time()
        threshold = self.DEFAULT_THRESHOLD_PERCENT

        # 当前是否处于提醒区间
        in_zone = abs(quote.change_percent) >= threshold

        # 上一轮是否在区间内（首次评估视为区间外，允许首次触及即提醒）
        was_in_zone = self._default_in_zone.get(symbol, False)

        # 更新状态
        self._default_in_zone[symbol] = in_zone

        # 仅在穿越（区间外 → 区间内）时才可能触发
        if not in_zone or was_in_zone:
            return None

        # cooldown 防抖：穿越后短时间内不重复提醒
        last_triggered = self._default_cooldowns.get(symbol)
        if last_triggered and (now - last_triggered) < (self.DEFAULT_COOLDOWN_MINUTES * 60):
            return None

        change = quote.change_percent
        direction = "up" if change >= 0 else "down"
        self._default_cooldowns[symbol] = now
        return AlertEvent(
            symbol=symbol,
            name=quote.name or symbol,
            direction=direction,
            percent=change,
            message=f"{quote.name or symbol} 骤然{('上涨' if direction == 'up' else '下跌')} {abs(change):.2f}%",
            current_price=quote.current_price,
            rule_id=None,
            timestamp=now,
        )

    def _check_user_rule(self, quote: QuoteData, rule: AlertRule) -> Optional[AlertEvent]:
        """用户自定义阈值规则检测 — 阈值穿越触发

        同默认规则逻辑：仅当涨跌幅从阈值下方穿越到上方（或上方穿越到下方）时触发，
        持续在阈值外侧不重复提醒，回落后再次穿越才重新提醒。
        """
        now = time.time()
        change = quote.change_percent
        threshold = rule.threshold_percent
        direction = rule.direction

        # 判断当前是否处于提醒区间
        if direction == "up":
            in_zone = change >= threshold
        elif direction == "down":
            in_zone = change <= -threshold
        else:  # both
            in_zone = abs(change) >= threshold

        # 上一轮是否在区间内（首次评估视为区间外，允许首次触及即提醒）
        was_in_zone = self._user_rule_in_zone.get(rule.id, False)

        # 更新状态
        self._user_rule_in_zone[rule.id] = in_zone

        # 仅在穿越（区间外 → 区间内）时才可能触发
        if not in_zone or was_in_zone:
            return None

        # cooldown 防抖
        if rule.last_triggered_at and (now - rule.last_triggered_at) < (rule.cooldown_minutes * 60):
            return None

        actual_direction = "up" if change >= 0 else "down"
        return AlertEvent(
            symbol=quote.symbol,
            name=quote.name or rule.name or quote.symbol,
            direction=actual_direction,
            percent=change,
            message=f"{rule.name or quote.symbol} 触发阈值提醒：{change:+.2f}%",
            current_price=quote.current_price,
            rule_id=rule.id,
            timestamp=now,
        )

    async def _load_active_rules(self) -> List[AlertRule]:
        """从数据库加载所有活跃的用户自定义规则，关联 portfolio 信息"""
        from local.db import db

        rows = await db.fetchall(
            """
            SELECT ar.*, p.symbol, p.name
            FROM alert_rules ar
            JOIN portfolio p ON ar.portfolio_id = p.id
            WHERE ar.is_active = 1
            """
        )

        rules: List[AlertRule] = []
        for row in rows:
            rules.append(
                AlertRule(
                    id=row["id"],
                    portfolio_id=row["portfolio_id"],
                    symbol=row["symbol"],
                    name=row["name"],
                    threshold_percent=row["threshold_percent"],
                    direction=row["direction"],
                    is_active=bool(row["is_active"]),
                    last_triggered_at=(
                        # SQLite CURRENT_TIMESTAMP 为 UTC，须用 timegm 按 UTC 语义解析；
                        # 若用 mktime（本地时区）会偏差时区小时数，导致 cooldown 误判失效、提醒重复轰炸
                        calendar.timegm(time.strptime(row["last_triggered_at"], "%Y-%m-%d %H:%M:%S"))
                        if row["last_triggered_at"]
                        else None
                    ),
                    cooldown_minutes=row["cooldown_minutes"],
                )
            )
        return rules

    async def _mark_triggered(self, events: List[AlertEvent]) -> None:
        """更新用户规则的 last_triggered_at（默认规则已在内存中更新）"""
        from local.db import db

        user_rule_ids = [e.rule_id for e in events if e.rule_id is not None]
        if not user_rule_ids:
            return

        # 使用 parameterized query 批量更新
        placeholders = ",".join(["?"] * len(user_rule_ids))
        await db.execute(
            f"""
            UPDATE alert_rules
            SET last_triggered_at = CURRENT_TIMESTAMP
            WHERE id IN ({placeholders})
            """,
            tuple(user_rule_ids),
        )


# 全局单例
alert_engine = AlertEngine()
