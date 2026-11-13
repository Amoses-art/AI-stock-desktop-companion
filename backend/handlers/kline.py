"""K线 handler — 分时K线获取（当日分时 / 近5日分时趋势）"""
from __future__ import annotations

import asyncio
from typing import Any, Dict

from data.kline_service import kline_service


async def get_kline(params: Dict[str, Any]) -> Dict[str, Any]:
    """获取分时K线数据

    params: {symbol, market?, asset_type?, days?}
       - symbol: 证券代码（如 600519 / 0700.HK / AAPL）
       - days: 1（当日分时，默认）| 2-5（近N日分时趋势）
    returns: {symbol, market, days, pre_close, series: [{date, points:[{t,price,vol}]}]}
    """
    symbol = str(params.get("symbol", "")).strip()
    if not symbol:
        raise ValueError("symbol is required")
    market = params.get("market")
    asset_type = params.get("asset_type", "stock")
    try:
        days = max(1, min(int(params.get("days", 1)), 5))
    except (TypeError, ValueError):
        days = 1

    # 场外基金无盘中分时数据
    if asset_type == "fund_open":
        return {
            "symbol": symbol,
            "market": market or "cn",
            "days": 0,
            "pre_close": 0.0,
            "series": [],
        }

    data = await asyncio.wait_for(
        kline_service.get_intraday(symbol, market, days), timeout=10.0
    )
    if not data:
        return {
            "symbol": symbol,
            "market": market or "cn",
            "days": 0,
            "pre_close": 0.0,
            "series": [],
        }
    return data
