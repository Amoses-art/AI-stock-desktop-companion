"""行情 handler — 从 main.py 拆出（M1-R1）"""
from __future__ import annotations

import asyncio
from typing import Any, Dict

from data.quote_service import quote_service


async def get_quote(params: Dict[str, Any]) -> Dict[str, Any]:
    """获取单只标的实时行情"""
    symbol = params["symbol"]
    asset_type = params.get("asset_type", "stock")
    # 超时 25s：盘后缓存缺失时允许拉取一次当日收盘快照（内部 20s 超时，含新浪备源全量拉取），此后走缓存
    quote = await asyncio.wait_for(quote_service.get_quote(symbol, asset_type), timeout=25.0)
    if not quote:
        raise RuntimeError(f"Quote not found for {symbol}")
    return quote.to_dict()


async def resolve_quote(params: Dict[str, Any]) -> Dict[str, Any]:
    """解析证券代码 → 名称/市场/价格（添加持仓自动填充 + 代码校验）

    local_only=true：仅本地毫秒级查询（内存 → SQLite → 离线演示数据），
    不发起网络请求。未命中返回 {"found": false}（前端静默跳过，不阻塞不报错）。
    用于添加持仓时的名称自动填充——保证输入代码后的反馈始终是毫秒级。

    完整路径（local_only=false）由快到慢：
      1. 内存行情缓存
      2. SQLite quote_cache（历史成功快照）
      3. 腾讯单请求快速解析（~0.3s，盘后返回收盘快照，不依赖交易时段）
      4. 离线演示数据兜底（MOCK_QUOTES 已知标的）
    均失败 → 抛 ValueError（视为无效代码，前端拦截添加）
    """
    from data.multi_market_router import MarketDetector
    from data.adapters.tencent_adapter import TencentQuoteAdapter
    from local.db import db

    symbol = str(params.get("symbol", "")).strip()
    asset_type = params.get("asset_type", "stock")
    local_only = bool(params.get("local_only", False))
    if not symbol:
        raise ValueError("证券代码不能为空")

    norm_symbol, market = MarketDetector.normalize(symbol)
    if market == "unknown":
        raise ValueError(f"无法识别的代码格式：{symbol}")
    # 0.7.0：normalize() 已统一 HK1810/1810/1810.HK → 01810.HK，
    # 不再手动拼接后缀（旧逻辑不覆盖 HK 前缀形态）

    # 1) 内存缓存
    cached = quote_service._cache.get(f"{market}:{norm_symbol}")
    if cached and cached.name and not cached.name.startswith("股票"):
        return _resolve_result(cached, asset_type)

    # 2) SQLite 缓存
    row = await db.fetchone("SELECT * FROM quote_cache WHERE symbol = ?", (norm_symbol,))
    if row and row["name"] and not str(row["name"]).startswith("股票"):
        return {
            "symbol": norm_symbol,
            "name": row["name"],
            "market": row["market"] or market,
            "asset_type": asset_type,
            "current_price": row["current_price"] or 0.0,
            "pre_close": row["pre_close"] or 0.0,
        }

    # 3) 腾讯快速解析（仅完整路径；local_only 不发起网络请求）
    if not local_only:
        name, current, pre_close = await TencentQuoteAdapter.resolve_name_fast(norm_symbol, market)
        if name and not name.startswith("股票"):
            return {
                "symbol": norm_symbol,
                "name": name,
                "market": market,
                "asset_type": asset_type,
                "current_price": current,
                "pre_close": pre_close,
            }

    # 4) 离线演示数据兜底（0.6.0 已废弃假数据，保留 None 判断以防回归）
    fallback = quote_service._get_fallback_quote(norm_symbol)
    if fallback and fallback.name and not fallback.name.startswith("股票"):
        return _resolve_result(fallback, asset_type)

    # local_only 未命中：静默返回，不抛错（前端不阻塞、不拦截）
    if local_only:
        return {
            "found": False,
            "symbol": norm_symbol,
            "market": market,
            "asset_type": asset_type,
        }

    raise ValueError(f"无法识别代码：{symbol}")


def _resolve_result(quote, asset_type: str) -> Dict[str, Any]:
    """由 QuoteData 构造解析结果"""
    return {
        "symbol": quote.symbol,
        "name": quote.name,
        "market": quote.market,
        "asset_type": asset_type,
        "current_price": quote.current_price,
        "pre_close": quote.pre_close,
    }


async def subscribe_quotes(params: Dict[str, Any]) -> Dict[str, Any]:
    """批量订阅行情"""
    symbols = params.get("symbols", [])
    # 当前仅返回行情数据，后续可加入推送机制
    quotes = []
    for sym in symbols:
        try:
            q = await asyncio.wait_for(quote_service.get_quote(sym), timeout=2.0)
        except asyncio.TimeoutError:
            q = None
        if q:
            quotes.append(q.to_dict())
    return {"success": True, "quotes": quotes}


async def refresh_quotes(params: Dict[str, Any]) -> list:
    """手动刷新行情（契约冻结表 v3.2 §一 #6，M1-R2 修复 G2/G3）

    - symbols 为空时刷新全量持仓
    - force=true：绕过交易时段拦截与缓存，直接拉最新快照（盘后为当日收盘定格）
    - 刷新后触发一次提醒评估（手动刷新语义下阈值触达也应提醒）
    """
    symbols = [str(s) for s in params.get("symbols", []) if s]
    force = bool(params.get("force", True))

    # 0.6.0 修复：symbols 非空时也查真实 asset_type——
    # 旧逻辑强制 "stock" 导致基金/ETF 被当 A 股股票拉取，必然失败
    from local.db import db
    if symbols:
        rows = await db.fetchall(
            "SELECT symbol, asset_type FROM portfolio WHERE symbol IN "
            f"({','.join('?' * len(symbols))})", tuple(symbols)
        )
        type_map = {r["symbol"]: r["asset_type"] for r in rows}
        targets = [(s, type_map.get(s, "stock")) for s in symbols]
    else:
        rows = await db.fetchall("SELECT symbol, asset_type FROM portfolio ORDER BY id")
        targets = [(r["symbol"], r["asset_type"]) for r in rows]

    # 0.6.0 修复：并行拉取 + 每标的独立超时——
    # 旧串行逻辑下，列表含港美股/无效代码时逐个 28s 超时累加，
    # 总耗时 84s+ 必然击穿 Rust 桥 30s 超时 → 整批失败 → 前端时间戳不更新
    async def _fetch_one(sym: str, atype: str):
        try:
            # 盘后/冷启动备源全量拉取最长约 25s，手动刷新是用户显式动作，给足超时
            return await asyncio.wait_for(
                quote_service.get_quote(sym, atype, force=force), timeout=28.0
            )
        except (asyncio.TimeoutError, Exception):
            return None

    fetched = await asyncio.gather(*[_fetch_one(sym, atype) for sym, atype in targets])
    quotes = [q for q in fetched if q]

    # 刷新后提醒评估：仅交易时段评估。
    # 非交易日/盘后行情已定格，涨跌幅不会变化，重复刷新只会反复触发同一阈值提醒（穿越刷屏）。
    from core.trading_hours_guard import TradingHoursGuard
    if TradingHoursGuard.is_trading_time():
        from core.alert_engine import alert_engine
        events = await alert_engine.evaluate(quotes)
        if events:
            await quote_service._notify_alerts(events)

    return [q.to_dict() for q in quotes]
