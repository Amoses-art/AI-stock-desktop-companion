"""统计 handler — 从 main.py 拆出（M1-R1）"""
from __future__ import annotations

from typing import Any, Dict

from handlers.portfolio import list_portfolio


async def get_summary() -> Dict[str, Any]:
    """获取持仓总览统计"""
    from data.health_checker import health_checker
    from core.trading_hours_guard import TradingHoursGuard

    portfolio = await list_portfolio()
    total_cost = sum(p["cost_price"] * p["quantity"] for p in portfolio)
    total_value = sum(p["current_price"] * p["quantity"] for p in portfolio)
    total_pnl = total_value - total_cost
    total_pnl_pct = ((total_value - total_cost) / total_cost * 100) if total_cost > 0 else 0

    if total_pnl_pct > 1:
        mood = "happy"
    elif total_pnl_pct < -1:
        mood = "sad"
    else:
        mood = "neutral"

    return {
        "total_cost": round(total_cost, 2),
        "total_value": round(total_value, 2),
        "total_pnl": round(total_pnl, 2),
        "total_pnl_percent": round(total_pnl_pct, 2),
        "holdings_count": len(portfolio),
        "mood": mood,
        # ARCH-5/6: 前端感知字段
        "data_source_mode": health_checker.current_mode,
        "trading_hours_status": TradingHoursGuard.get_trading_hours_comment(),
    }
