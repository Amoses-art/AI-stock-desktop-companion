"""
行情服务 — 多数据源路由 + 轮询引擎 + 本地缓存
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from time import monotonic
from typing import Dict, List, Optional

from data.adapters.base import QuoteData
from data.multi_market_router import MultiMarketDataAdapter, MarketDetector
from local.db import db
from core.trading_hours_guard import TradingHoursGuard
from data.health_checker import health_checker

# 模拟数据（沙箱/离线环境演示用）
MOCK_QUOTES: Dict[str, QuoteData] = {
    "600519": QuoteData(
        symbol="600519",
        name="贵州茅台",
        market="cn",
        asset_type="stock",
        current_price=1680.50,
        pre_close=1650.00,
        open_price=1655.00,
        high_price=1690.00,
        low_price=1648.00,
        change_amount=30.50,
        change_percent=1.85,
        volume=25000.0,
        turnover=42000000.0,
    ),
    "002594": QuoteData(
        symbol="002594",
        name="比亚迪",
        market="cn",
        asset_type="stock",
        current_price=245.80,
        pre_close=250.00,
        open_price=249.50,
        high_price=252.00,
        low_price=243.00,
        change_amount=-4.20,
        change_percent=-1.68,
        volume=180000.0,
        turnover=44100000.0,
    ),
    "300750": QuoteData(
        symbol="300750",
        name="宁德时代",
        market="cn",
        asset_type="stock",
        current_price=198.50,
        pre_close=195.00,
        open_price=196.00,
        high_price=201.00,
        low_price=194.00,
        change_amount=3.50,
        change_percent=1.79,
        volume=320000.0,
        turnover=63360000.0,
    ),
    "003095": QuoteData(
        symbol="003095",
        name="中欧医疗健康A",
        market="cn",
        asset_type="fund_open",
        current_price=2.3456,
        pre_close=2.3250,
        change_amount=0.0206,
        change_percent=0.89,
    ),
    "005827": QuoteData(
        symbol="005827",
        name="易方达蓝筹精选",
        market="cn",
        asset_type="fund_open",
        current_price=1.8923,
        pre_close=1.9000,
        change_amount=-0.0077,
        change_percent=-0.41,
    ),
    "510300": QuoteData(
        symbol="510300",
        name="沪深300ETF",
        market="cn",
        asset_type="fund_etf",
        current_price=3.985,
        pre_close=3.950,
        change_amount=0.035,
        change_percent=0.89,
        volume=4500000.0,
    ),
    # 港股 mock
    "0700.HK": QuoteData(
        symbol="0700.HK",
        name="腾讯控股",
        market="hk",
        asset_type="stock",
        current_price=385.20,
        pre_close=380.00,
        open_price=381.00,
        high_price=388.00,
        low_price=379.00,
        change_amount=5.20,
        change_percent=1.37,
        volume=12500000.0,
        currency="HKD",
    ),
    "3690.HK": QuoteData(
        symbol="3690.HK",
        name="美团-W",
        market="hk",
        asset_type="stock",
        current_price=112.50,
        pre_close=115.00,
        open_price=114.00,
        high_price=116.00,
        low_price=111.00,
        change_amount=-2.50,
        change_percent=-2.17,
        volume=8900000.0,
        currency="HKD",
    ),
    # 美股 mock
    "AAPL": QuoteData(
        symbol="AAPL",
        name="Apple Inc.",
        market="us",
        asset_type="stock",
        current_price=189.52,
        pre_close=187.32,
        open_price=187.50,
        high_price=190.10,
        low_price=186.80,
        change_amount=2.20,
        change_percent=1.17,
        volume=45600000.0,
        currency="USD",
    ),
    "TSLA": QuoteData(
        symbol="TSLA",
        name="Tesla Inc.",
        market="us",
        asset_type="stock",
        current_price=245.30,
        pre_close=250.00,
        open_price=249.00,
        high_price=252.00,
        low_price=243.00,
        change_amount=-4.70,
        change_percent=-1.88,
        volume=32100000.0,
        currency="USD",
    ),
}

# MOCK_QUOTES 用于 OFFLINE 模式与盘外兜底（保留真实演示数据）


class QuoteService:
    """行情服务 — 统一管理多市场数据获取（ADR-026 多市场支持）"""

    def __init__(self) -> None:
        # 多市场数据适配器（ADR-026）
        self._multi_market = MultiMarketDataAdapter()
        self._cache: Dict[str, QuoteData] = {}
        self._polling_task: Optional[asyncio.Task] = None
        self._running = False
        self._health_checker = health_checker
        # 冷启动兜底拉取的冷却时间戳（0.7.0：防止数据源不可用时反复空等）
        self._cold_fetch_at: float = 0.0

    def _get_asset_type(self, symbol: str, portfolio_type: str) -> str:
        """根据持仓类型确定资产类型"""
        if portfolio_type.startswith("fund_"):
            return portfolio_type
        return "stock"

    async def warmup(self) -> None:
        """预热 A股全市场快照（东财失败自动回退新浪备源），让首次查询直接命中缓存"""
        try:
            await self._multi_market.get_quote("000001", "cn")
        except Exception:
            pass

    async def get_quote(self, symbol: str, asset_type: str = "stock", force: bool = False) -> Optional[QuoteData]:
        """获取单只标的行情（带缓存 + 持久化 + 交易时段拦截 + 多市场自动路由）

        force=True（M1-R2 G3）：手动刷新语义——绕过交易时段拦截与缓存读取，
        直接拉取最新快照（盘后返回当日收盘定格），成功后回写缓存。
        """
        # 多市场自动检测
        _, market = MarketDetector.normalize(symbol)
        cache_key = f"{market}:{symbol}"

        # 交易时段检查（ARCH-5）— 仅对 A股生效，港股/美股不受限；force 手动刷新绕过
        if market == "cn" and not force and not TradingHoursGuard.is_trading_time():
            # 非交易时间：优先返回缓存
            if cache_key in self._cache:
                cached = self._cache[cache_key]
                cached.is_off_hours = True  # type: ignore[attr-defined]
                return cached

            cached = await db.fetchone(
                "SELECT * FROM quote_cache WHERE symbol = ?", (symbol,)
            )
            if cached:
                quote = self._cached_row_to_quote(cached)
                quote.is_off_hours = True  # type: ignore[attr-defined]
                self._cache[cache_key] = quote
                return quote

            # 缓存缺失 → 拉取一次当日收盘快照填充缓存
            # （AKShare spot 接口盘后返回当日定格的收盘数据，此后走缓存不再请求；
            #   东财被封锁时熔断直连新浪备源，全量拉取约 15-20s，故超时 25s）
            snapshot = None
            try:
                snapshot = await asyncio.wait_for(
                    self._multi_market.get_quote(symbol, market, asset_type), timeout=25.0
                )
            except (asyncio.TimeoutError, Exception):
                snapshot = None
            if snapshot:
                snapshot.is_off_hours = True  # type: ignore[attr-defined]
                self._cache[cache_key] = snapshot
                await self._persist_quote(snapshot)
                return snapshot

            # 数据源不可用 → 如实返回 None（用户实测反馈：随机假价比无数据更糟糕）
            # 前端按「数据获取中」话术展示；下次查询/手动刷新重试真实数据源
            return None

        # ARCH-6: 降级策略（仅影响 A股数据源，港股/美股走独立通道）
        mode = self._health_checker.current_mode
        if mode == "offline":
            return None

        if mode == "degraded" and market == "cn":
            # 先尝试数据源，超时则回退缓存/mock
            try:
                quote = await asyncio.wait_for(
                    self._multi_market.get_quote(symbol, market, asset_type),
                    timeout=3.0,
                )
                if quote:
                    self._cache[cache_key] = quote
                    await self._persist_quote(quote)
                    return quote
            except asyncio.TimeoutError:
                pass
            # 回退缓存
            if cache_key in self._cache:
                return self._cache[cache_key]
            cached = await db.fetchone(
                "SELECT * FROM quote_cache WHERE symbol = ?", (symbol,)
            )
            if cached:
                return self._cached_row_to_quote(cached)
            return None

        # 正常模式（normal）；force 手动刷新跳过缓存读取，直接拉最新快照
        if not force and cache_key in self._cache:
            return self._cache[cache_key]

        # 数据库缓存（仅 A股有持久化缓存，港股/美股不走本地缓存）
        if not force and market == "cn":
            cached = await db.fetchone(
                "SELECT * FROM quote_cache WHERE symbol = ?", (symbol,)
            )
            if cached:
                return self._cached_row_to_quote(cached)

        # 从多市场数据源获取
        quote = await self._multi_market.get_quote(symbol, market, asset_type)
        if quote:
            self._cache[cache_key] = quote
            # 0.7.0：盘后/非交易时段把港美股收盘快照也落库——
            # 历史仅 A 股持久化，导致港美股下次冷启动无缓存可读（显示「数据获取中」）。
            # 交易时段内不落库，避免秒级轮询写放大。
            if market == "cn" or not TradingHoursGuard.is_trading_time():
                await self._persist_quote(quote)
            return quote

        # force 拉取失败：回退现有缓存（如有），避免手动刷新退化为 mock
        if force and cache_key in self._cache:
            return self._cache[cache_key]

        # PRD 4.3.2 调整（0.6.0 用户实测反馈）：数据源失败不再生成假行情，
        # 如实返回 None，由前端按「数据获取中」展示；缓存/重试走真实数据源
        return None

    def _get_fallback_quote(self, symbol: str) -> Optional[QuoteData]:
        """演示数据兜底已废弃（0.6.0）：任何形式的假价格都会误导真实用户。

        历史背景：曾用 MOCK_QUOTES 固定演示 + 随机 mock 兜底，导致用户持仓列表
        出现随机假价（如港股 195 元/基金 67 元）且无从分辨真伪。
        """
        return None

    def _get_mock_quote(self, symbol: str) -> Optional[QuoteData]:
        """随机 mock 生成器已废弃（0.6.0）——保留方法避免旧引用崩溃"""
        return None

    async def get_portfolio_quotes(self) -> List[QuoteData]:
        """获取全部持仓的行情（按资产类型分组批量拉取，1s 秒级轮询性能关键）"""
        portfolio = await db.fetchall("SELECT symbol, asset_type FROM portfolio")
        if not portfolio:
            return []

        results: List[QuoteData] = []
        # 按 asset_type 分组（不同资产走不同适配器，避免串源）
        groups: Dict[str, List[str]] = {}
        for item in portfolio:
            atype = item["asset_type"]
            groups.setdefault(atype, []).append(item["symbol"])

        for atype, syms in groups.items():
            # 批量走 multi_market（Tencent 一次请求多只，秒级完成）
            try:
                batch = await asyncio.wait_for(
                    self._multi_market.get_batch_quotes(syms, atype), timeout=8.0
                )
            except (asyncio.TimeoutError, Exception) as e:
                # 单组批量超时/失败：跳过该组继续，绝不让单个慢源拖垮整个持仓列表
                print(f"[QuoteService] get_batch_quotes fail for {atype}: {e}", file=sys.stderr, flush=True)
                batch = []
            batch_map = {q.symbol: q for q in batch}
            results.extend(batch)
            missing = [sym for sym in syms if sym not in batch_map]
            if not missing:
                continue

            # 批量未覆盖的标的并发补拉（可能刚添加，缓存/接口差异）；
            # 单只 3s 硬超时 + 并发兜底：慢源绝不阻塞列表返回（多只慢票串行会成倍拖长）
            async def _fetch_one(sym: str):
                try:
                    return await asyncio.wait_for(self.get_quote(sym, atype), timeout=3.0)
                except (asyncio.TimeoutError, Exception) as e:
                    print(f"[QuoteService] 补拉行情失败 {sym}: {e}", file=sys.stderr, flush=True)
                    return None

            done = await asyncio.gather(*(_fetch_one(s) for s in missing))
            results.extend(q for q in done if q is not None)

        # 过滤未知代码生成的假行情（"股票{symbol}"）：
        # 列表与 quote:tick 广播均不展示幻影价格，由 list_portfolio 标记 quote_error，
        # 前端【实时股价】列提示"代码错误"；保留 MOCK_QUOTES 固定演示数据（真实名称）。
        return [q for q in results if not (q.name and str(q.name).startswith("股票"))]

    async def get_cached_portfolio_quotes(self) -> List[QuoteData]:
        """非交易时段获取持仓行情：内存缓存 → quote_cache 表 → 冷启动一次性快照兜底。

        用于盘后/非交易日的持仓列表与 AI 对话（"我赚了多少"等），避免每次请求都走网络。
        0.7.0：港美股/场外基金历史无本地持久化缓存，仅靠缓存会全部显示「数据获取中」，
        故对缓存缺失项做一次并发快照拉取（硬超时 + 60s 冷却），成功后写缓存并落库，
        下次启动即直接命中缓存；数据源不可用时快速失败，不长期阻塞列表。
        """
        portfolio = await db.fetchall("SELECT symbol, asset_type, market FROM portfolio")
        if not portfolio:
            return []

        results: List[QuoteData] = []
        misses: List[tuple] = []
        for item in portfolio:
            symbol = item["symbol"]
            atype = item["asset_type"]
            market = item.get("market") or "cn"
            cache_key = f"{market}:{symbol}"

            # 1) 内存缓存
            q = self._cache.get(cache_key)

            # 1.1) 归一化键兜底：港股 HK1810 / 1810 / 1810.HK 语义等价，
            #      历史写入可能用另一种写法作键（0.7.0）
            if q is None:
                norm_symbol, _ = MarketDetector.normalize(symbol)
                if norm_symbol != symbol:
                    q = self._cache.get(f"{market}:{norm_symbol}")

            # 2) quote_cache 表
            if q is None:
                try:
                    row = await db.fetchone(
                        "SELECT * FROM quote_cache WHERE symbol = ?", (symbol,)
                    )
                    if row:
                        q = self._cached_row_to_quote(row)
                        self._cache[cache_key] = q
                except Exception:
                    pass

            if q is not None:
                # 复制并回填持仓行 symbol，避免污染缓存对象（同一行情可能被多行引用）
                results.append(q if q.symbol == symbol else replace(q, symbol=symbol))
            else:
                misses.append((symbol, atype))

        # 3) 冷启动兜底：并发拉取缺失标的的快照（硬超时 8s；60s 冷却防反复空等）
        now = monotonic()
        if misses and (now - self._cold_fetch_at) >= 60.0:
            self._cold_fetch_at = now

            async def _snap(sym: str, atype: str):
                try:
                    return await asyncio.wait_for(
                        self.get_quote(sym, atype, force=True), timeout=8.0
                    )
                except (asyncio.TimeoutError, Exception):
                    return None

            fetched = await asyncio.gather(*(_snap(s, a) for s, a in misses))
            results.extend(q for q in fetched if q is not None)

        return results

    async def _persist_quote(self, quote: QuoteData) -> None:
        """持久化行情到本地缓存表（全字段，盘外/降级重建时才能还原名称与昨收等）"""
        await db.execute(
            """
            INSERT INTO quote_cache (symbol, market, name, current_price, pre_close, open_price, high_price, low_price, change_percent, change_amount, volume, turnover, currency, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(symbol) DO UPDATE SET
                market=excluded.market,
                name=excluded.name,
                current_price=excluded.current_price,
                pre_close=excluded.pre_close,
                open_price=excluded.open_price,
                high_price=excluded.high_price,
                low_price=excluded.low_price,
                change_percent=excluded.change_percent,
                change_amount=excluded.change_amount,
                volume=excluded.volume,
                turnover=excluded.turnover,
                currency=excluded.currency,
                updated_at=CURRENT_TIMESTAMP
            """,
            (
                quote.symbol,
                quote.market,
                quote.name,
                quote.current_price,
                quote.pre_close,
                quote.open_price,
                quote.high_price,
                quote.low_price,
                quote.change_percent,
                quote.change_amount,
                quote.volume,
                quote.turnover,
                quote.currency,
            ),
        )

    @staticmethod
    def _cached_row_to_quote(cached) -> QuoteData:
        """从 quote_cache 行重建完整 QuoteData（盘外/降级/正常缓存三条路径共用）"""
        return QuoteData(
            symbol=cached["symbol"],
            name=cached["name"] or "",
            market=cached["market"] or "cn",
            asset_type="stock",
            current_price=cached["current_price"] or 0.0,
            pre_close=cached["pre_close"] or 0.0,
            open_price=cached["open_price"] or 0.0,
            high_price=cached["high_price"] or 0.0,
            low_price=cached["low_price"] or 0.0,
            change_amount=cached["change_amount"] or 0.0,
            change_percent=cached["change_percent"] or 0.0,
            volume=cached["volume"] or 0.0,
            turnover=cached["turnover"] or 0.0,
            currency=cached["currency"] or "CNY",
        )

    async def start_polling(self, interval_seconds: int = 10) -> None:
        """启动实时轮询（后台任务），集成 AlertEngine + 交易时段智能调度（M1-R2 G1）

        调度策略（PRD v3.1 §2.3）：
        - 交易时段（配置化，默认 09:00-15:00）：interval_seconds 秒级轮询 + 提醒评估
        - 午休（11:30-13:00）：降频至 120s（行情定格，无网络请求）
        - 非交易时段/非交易日：零主动请求，60s 心跳重查（跨天自动恢复）
        """
        if self._polling_task is not None and not self._polling_task.done():
            return  # 已在轮询中，避免重复启动
        self._running = True

        async def poll_loop() -> None:
            from core.trading_hours_guard import TradingHoursGuard
            from config.global_config import config_manager
            while self._running:
                # 交易时段间隔每轮从配置读取（设置页热更新生效）
                sleep_s = config_manager.get_int("quote_polling_interval_cn", interval_seconds)
                try:
                    if TradingHoursGuard.is_trading_time():
                        quotes = await self.get_portfolio_quotes()
                        # 提醒引擎评估（ARCH-1）
                        from core.alert_engine import alert_engine
                        events = await alert_engine.evaluate(quotes)
                        if events:
                            # 推送提醒事件到 Rust 层
                            await self._notify_alerts(events)
                        # 广播行情快照（quote:tick）→ Rust 按 method 分发到前端各窗口
                        await self._broadcast_quotes(quotes)
                    elif TradingHoursGuard.is_lunch_break():
                        # 午休降频：行情定格，不拉取不评估
                        sleep_s = 120
                    else:
                        # 非交易时段：零主动请求，心跳等待开市
                        sleep_s = 60
                except Exception as e:
                    print(f"[QuoteService] polling error: {e}")
                await asyncio.sleep(sleep_s)

        self._polling_task = asyncio.create_task(poll_loop())

    async def _notify_alerts(self, events) -> None:
        """将提醒事件通过 TCP 主动推送到 Rust 层（替代旧 stdout 管道模式）"""
        from rpc.server import broadcast_notification
        payload = {
            "method": "alert.notify",
            "params": {"alerts": [self._event_to_dict(e) for e in events]},
        }
        try:
            await broadcast_notification(payload)
        except Exception:
            import sys as _sys
            import traceback
            traceback.print_exc(file=_sys.stderr)

    async def _broadcast_quotes(self, quotes: List[QuoteData]) -> None:
        """广播行情快照到前端各窗口（quote:tick 通知，驱动桌宠当日盈亏实时更新）"""
        from rpc.server import broadcast_notification
        payload = {
            "method": "quote.tick",
            "params": {"quotes": [q.to_dict() for q in quotes]},
        }
        try:
            await broadcast_notification(payload)
        except Exception:
            import sys as _sys
            import traceback
            traceback.print_exc(file=_sys.stderr)

    @staticmethod
    def _event_to_dict(event) -> dict:
        # 契约字段（PRD v3.1 §4.2 AlertEvent）+ 扩展字段（message 用于系统通知）
        return {
            "symbol": event.symbol,
            "name": event.name,
            "current_price": event.current_price,
            # 默认骤变规则 → "sudden"；用户阈值规则 → 实际方向
            "trigger_type": "sudden" if event.rule_id is None else event.direction,
            "triggered_at": int(event.timestamp),
            # 扩展字段（契约允许新增）
            "percent": event.percent,
            "message": event.message,
        }

    async def stop_polling(self) -> None:
        """停止轮询"""
        self._running = False
        if self._polling_task:
            self._polling_task.cancel()
            try:
                await self._polling_task
            except asyncio.CancelledError:
                pass


# 全局单例
quote_service = QuoteService()
