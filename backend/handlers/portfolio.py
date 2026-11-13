"""持仓 handler — 从 main.py 拆出（M1-R1）"""
from __future__ import annotations

import sys
import time as _time
from typing import Any, Dict, List

from data.quote_service import quote_service


async def list_portfolio() -> List[Dict[str, Any]]:
    """获取全部持仓（含实时盈亏 + 自定义提醒阈值 + 代码有效性标记）"""
    from data.multi_market_router import MarketDetector
    from core.trading_hours_guard import TradingHoursGuard
    from local.db import db

    rows = await db.fetchall("SELECT * FROM portfolio ORDER BY id")

    # 非交易时段：用本地缓存行情，避免网络请求拖慢持仓列表/AI对话（盘后数据已定格）
    if TradingHoursGuard.is_trading_time():
        quotes = await quote_service.get_portfolio_quotes()
    else:
        quotes = await quote_service.get_cached_portfolio_quotes()
    quote_map = {q.symbol: q for q in quotes}

    # 用户自定义提醒阈值（portfolio_id → threshold_percent；未设置则无记录）
    rule_rows = await db.fetchall(
        "SELECT portfolio_id, threshold_percent FROM alert_rules WHERE is_active = 1"
    )
    threshold_map = {r["portfolio_id"]: r["threshold_percent"] for r in rule_rows}

    results: List[Dict[str, Any]] = []
    for row in rows:
        symbol = row["symbol"]
        qty = row["quantity"]
        cost = row["cost_price"]
        quote = quote_map.get(symbol)

        # 0.6.0 修复（用户实测反馈4）：拆分两种状态——
        #   code_invalid：代码格式/市场与录入市场不匹配 → 前端显示「代码错误」
        #   data_pending：代码合法但暂无行情（数据源未响应/首次添加）→ 前端显示「数据获取中」，
        #                列表内已有缓存价时优先显示缓存，取到最新行情后自动刷新
        quote_error = False
        code_invalid = False
        data_pending = False
        try:
            _, detected_market = MarketDetector.normalize(symbol)
        except Exception:
            detected_market = None
        if detected_market is not None and detected_market != row["market"]:
            quote_error = True
            code_invalid = True
        elif detected_market is None:
            quote_error = True
            code_invalid = True
        elif quote is None:
            quote_error = True
            data_pending = True
        elif str(quote.name).startswith("股票"):
            quote_error = True
            data_pending = True
        quote_state = "code_invalid" if code_invalid else ("data_pending" if data_pending else "ok")

        current = quote.current_price if quote else 0.0
        pnl_amount = (current - cost) * qty if current > 0 else 0.0
        pnl_percent = ((current - cost) / cost * 100) if cost > 0 and current > 0 else 0.0

        results.append({
            "id": row["id"],
            "symbol": symbol,
            "name": row["name"],
            "market": row["market"],
            "asset_type": row["asset_type"],
            "quantity": qty,
            "cost_price": cost,
            "currency": row["currency"],
            "current_price": current,
            "change_percent": quote.change_percent if quote else 0.0,
            "pnl_amount": round(pnl_amount, 2),
            "pnl_percent": round(pnl_percent, 2),
            "alert_threshold": threshold_map.get(row["id"]),
            "quote_error": quote_error,
            "quote_state": quote_state,
        })

    return results


async def add_portfolio(params: Dict[str, Any]) -> Dict[str, Any]:
    """添加持仓

    支持 alert_threshold（1-20%）：设置后为该持仓创建用户自定义提醒规则，
    替代默认 3% 骤然涨跌规则（引擎对存在用户规则的标的跳过默认规则）。
    """
    from local.db import db

    _t0 = _time.time()
    print(f"[DEBUG] portfolio.add START params={params}", file=sys.stderr, flush=True)

    symbol = params["symbol"]
    name = params["name"]
    market = params.get("market", "cn")
    asset_type = params.get("asset_type", "stock")
    # 资产类型归一化（前端可能传简称）
    asset_type = _normalize_asset_type(asset_type)
    quantity = float(params["quantity"])
    cost_price = float(params["cost_price"])
    currency = params.get("currency", "CNY")

    # 阈值校验（1-20%，可选）
    alert_threshold = params.get("alert_threshold")
    if alert_threshold is not None:
        alert_threshold = float(alert_threshold)
        if not (1.0 <= alert_threshold <= 20.0):
            raise ValueError("alert_threshold must be in [1, 20]")

    print(f"[DEBUG] portfolio.add before INSERT dt={_time.time()-_t0:.3f}s", file=sys.stderr, flush=True)

    await db.execute(
        """
        INSERT INTO portfolio (symbol, name, market, asset_type, quantity, cost_price, currency)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(symbol, market, asset_type) DO UPDATE SET
            name=excluded.name,
            quantity=excluded.quantity,
            cost_price=excluded.cost_price,
            updated_at=CURRENT_TIMESTAMP
        """,
        (symbol, name, market, asset_type, quantity, cost_price, currency),
    )

    print(f"[DEBUG] portfolio.add before SELECT dt={_time.time()-_t0:.3f}s", file=sys.stderr, flush=True)

    row = await db.fetchone(
        "SELECT * FROM portfolio WHERE symbol = ? AND market = ? AND asset_type = ?",
        (symbol, market, asset_type),
    )
    if not row:
        raise RuntimeError("Failed to insert portfolio")

    # 自定义阈值规则：替换该持仓的提醒规则（先清后插，ON CONFLICT 不适用无唯一索引的 alert_rules）
    if alert_threshold is not None:
        await db.execute(
            "DELETE FROM alert_rules WHERE portfolio_id = ?", (row["id"],)
        )
        await db.execute(
            """
            INSERT INTO alert_rules (portfolio_id, threshold_percent, direction, is_active, cooldown_minutes)
            VALUES (?, ?, 'both', 1, 5)
            """,
            (row["id"], alert_threshold),
        )

    print(f"[DEBUG] portfolio.add SUCCESS dt={_time.time()-_t0:.3f}s row_id={row['id']}", file=sys.stderr, flush=True)

    return {
        "id": row["id"],
        "symbol": row["symbol"],
        "name": row["name"],
        "market": row["market"],
        "asset_type": row["asset_type"],
        "quantity": row["quantity"],
        "cost_price": row["cost_price"],
        "currency": row["currency"],
        "alert_threshold": alert_threshold,
    }


def _normalize_asset_type(asset_type: str) -> str:
    """资产类型归一化（前端表单可能传简称）"""
    aliases = {
        "fund": "fund_open",
        "fund_money": "fund_open",
        "etf": "fund_etf",
        "lof": "fund_lof",
    }
    return aliases.get(asset_type, asset_type)


async def remove_portfolio(params: Dict[str, Any]) -> Dict[str, Any]:
    """删除持仓（级联删除其提醒规则，防止孤儿规则）"""
    from local.db import db

    portfolio_id = int(params["id"])
    await db.execute("DELETE FROM alert_rules WHERE portfolio_id = ?", (portfolio_id,))
    await db.execute("DELETE FROM portfolio WHERE id = ?", (portfolio_id,))
    return {"success": True, "deleted_id": portfolio_id}
