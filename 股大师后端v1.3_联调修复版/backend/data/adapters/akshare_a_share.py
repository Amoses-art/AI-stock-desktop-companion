"""
AKShare A股数据适配器 — 主数据源
覆盖：A股实时行情、场内ETF/LOF实时行情
"""

from __future__ import annotations

import asyncio
import sys
import time
from typing import List, Optional

import akshare as ak
import pandas as pd

from data.adapters.base import DataAdapter, QuoteData


class AKShareAStockAdapter(DataAdapter):
    """AKShare A股实时行情适配器（东财主源 + 新浪备源 + 全量快照缓存）"""

    name = "akshare_a_stock"
    priority = 1

    # 全市场快照缓存 TTL：东财快照 1-3s 可勤刷新；新浪全量分页约 15-20s，只作备源
    SPOT_CACHE_TTL_EM = 10
    SPOT_CACHE_TTL_SINA = 300
    # 东财熔断冷却：失败一次后 10 分钟内跳过东财直接走新浪（东财被网络封锁时每次失败浪费 ~6s）
    EM_CIRCUIT_COOLDOWN = 600

    def __init__(self) -> None:
        self._spot_df: Optional[pd.DataFrame] = None
        self._last_fetch: float = 0
        self._spot_ttl: float = self.SPOT_CACHE_TTL_EM
        # 单飞锁：并发调用共享同一次全量拉取，避免多个并发新浪分页拉取互相限流雪崩
        self._fetch_lock = asyncio.Lock()
        # 东财熔断状态：最近一次东财失败的时间戳（0 = 从未失败）
        self._em_failed_at: float = 0
        # 后台快照刷新任务句柄（避免被 GC，也避免重复刷新）
        self._bg_refresh: Optional[asyncio.Task] = None

    def is_available(self) -> bool:
        # 轻量检查：仅验证库已安装。
        # 不做网络探测（拉全市场快照数秒且同步阻塞 event loop），真实可用性由 HealthChecker 负责
        try:
            import akshare  # noqa: F401

            return True
        except Exception:
            return False

    async def _get_spot_df(self) -> Optional[pd.DataFrame]:
        """获取全市场快照：东财优先（快），失败回退新浪（慢但可用）；结果缓存；并发单飞"""
        now = time.time()
        if self._spot_df is not None and now - self._last_fetch < self._spot_ttl:
            return self._spot_df

        async with self._fetch_lock:
            # 双重检查：等锁期间其它协程可能已完成拉取
            now = time.time()
            if self._spot_df is not None and now - self._last_fetch < self._spot_ttl:
                return self._spot_df

            # 1) 东方财富（快）；熔断期内直接跳过（失败一次冷却 EM_CIRCUIT_COOLDOWN 秒）
            if now - self._em_failed_at > self.EM_CIRCUIT_COOLDOWN:
                try:
                    df = await asyncio.to_thread(ak.stock_zh_a_spot_em)
                    self._spot_df, self._last_fetch, self._spot_ttl = (
                        df,
                        now,
                        self.SPOT_CACHE_TTL_EM,
                    )
                    return df
                except Exception as e:
                    self._em_failed_at = now
                    print(f"[AKShare] 东财接口失败，回退新浪: {e}", file=sys.stderr, flush=True)
            elif self._em_failed_at:
                print("[AKShare] 东财熔断中，直接走新浪备源", file=sys.stderr, flush=True)

            # 2) 新浪（慢，约 15-20s 全量分页；东财被网络环境封锁时的备源）
            try:
                df = await asyncio.to_thread(ak.stock_zh_a_spot)
                self._spot_df, self._last_fetch, self._spot_ttl = (
                    df,
                    now,
                    self.SPOT_CACHE_TTL_SINA,
                )
                return df
            except Exception as e:
                print(f"[AKShare] 新浪接口也失败: {e}", file=sys.stderr, flush=True)

            return None

    @staticmethod
    def _match_row(df: pd.DataFrame, symbol: str):
        """按代码匹配行：东财代码为 000001，新浪代码为 sz000001（带市场前缀）"""
        row = df[df["代码"] == symbol]
        if row.empty:
            row = df[df["代码"].str.endswith(symbol)]
        return row.iloc[0] if not row.empty else None

    @staticmethod
    def _row_to_quote(symbol: str, r) -> QuoteData:
        """统一行转换（东财/新浪列名一致：名称/最新价/昨收/今开/最高/最低/涨跌额/涨跌幅/成交量/成交额）"""
        return QuoteData(
            symbol=symbol,
            name=str(r.get("名称", "")),
            market="cn",
            asset_type="stock",
            current_price=float(r.get("最新价", 0) or 0),
            pre_close=float(r.get("昨收", 0) or 0),
            open_price=float(r.get("今开", 0) or 0),
            high_price=float(r.get("最高", 0) or 0),
            low_price=float(r.get("最低", 0) or 0),
            change_amount=float(r.get("涨跌额", 0) or 0),
            change_percent=float(r.get("涨跌幅", 0) or 0),
            volume=float(r.get("成交量", 0) or 0),
            turnover=float(r.get("成交额", 0) or 0),
        )

    async def get_quote(self, symbol: str) -> Optional[QuoteData]:
        """获取单只A股实时行情（四级路径，保证冷启动也能秒级返回）

        1) 全量快照缓存命中 → 直接查表（毫秒级）
        2) 缓存未命中 → 腾讯单股实时接口直查（约 0.3s），同时后台异步刷新全量快照
        3) 腾讯失败 → 新浪单股实时接口直查（约 0.5s）
        4) 单股接口均失败 → 等待全量快照拉取（东财→新浪备源，约 6-20s）
        """
        try:
            # 1) 快照缓存命中
            df = self._cached_spot()
            if df is not None:
                r = self._match_row(df, symbol)
                if r is not None:
                    return self._row_to_quote(symbol, r)

            # 2) 腾讯单股直查（快路径，~0.3s）
            tencent = await self._fetch_batch_tencent([symbol])
            if tencent:
                # 后台刷新全量快照，供批量/轮询/后续查询使用
                self._refresh_spot_background()
                return tencent[0]

            # 3) 新浪单股直查（腾讯失败时的备源，~0.5s）
            quote = await self._fetch_single_sina(symbol)
            if quote is not None:
                self._refresh_spot_background()
                return quote

            # 4) 回退：等待全量快照拉取
            df = await self._get_spot_df()
            if df is None:
                return None
            r = self._match_row(df, symbol)
            if r is None:
                return None
            return self._row_to_quote(symbol, r)
        except Exception as e:
            print(f"[AKShare] get_quote error for {symbol}: {e}", file=sys.stderr, flush=True)
            return None

    def _cached_spot(self) -> Optional[pd.DataFrame]:
        """TTL 内的全量快照缓存（不触发网络拉取）"""
        if self._spot_df is not None and time.time() - self._last_fetch < self._spot_ttl:
            return self._spot_df
        return None

    def _refresh_spot_background(self) -> None:
        """后台异步刷新全量快照（不阻塞当前查询；单飞锁防并发雪崩）"""
        if self._bg_refresh is not None and not self._bg_refresh.done():
            return
        try:
            self._bg_refresh = asyncio.create_task(self._get_spot_df())
        except RuntimeError:
            pass  # 无运行中的 event loop（同步上下文调用）时忽略

    @staticmethod
    def _market_prefix(symbol: str) -> str:
        """A股代码 → 新浪/东财市场前缀：6/9/5 开头沪市，4/8 开头北交所，其余深市"""
        if symbol.startswith(("6", "9", "5")):
            return "sh"
        if symbol.startswith(("4", "8")):
            return "bj"
        return "sz"

    # ===================== 腾讯行情接口（第三源，批量快路径） =====================

    def _fetch_batch_tencent_sync(self, symbols: List[str]) -> List[QuoteData]:
        """腾讯批量行情接口（qt.gtimg.cn，同步实现，供 to_thread 调用）

        一次请求最多 ~60 只代码，约 0.3s；无 Referer 限制，无全量拉取开销。
        响应（GBK）每行形如：v_sz000001="51~平安银行~000001~11.92~...";
        字段索引（2026-09-01 实测校正，M1-R3 修复）：
        1=名称 2=代码 3=现价 4=昨收 5=今开 6~28=买卖五档
        30=时间戳 31=涨跌额 32=涨跌幅(%) 33=最高 34=最低
        36=成交量(手) 37=成交额(万)
        原实现误用 23/24/25/26/28/29（买卖五档区间），导致涨跌幅=档位量、最低=卖四量等错乱。
        """
        import requests

        codes = ",".join(f"{self._market_prefix(s)}{s}" for s in symbols)
        resp = requests.get(
            f"https://qt.gtimg.cn/q={codes}",
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
            timeout=5,
        )
        resp.encoding = "gbk"
        results: List[QuoteData] = []
        for line in resp.text.strip().splitlines():
            if '"' not in line:
                continue
            body = line.split('"')[1]
            f = body.split("~")
            if len(f) < 38 or not f[1]:
                continue
            try:
                price = float(f[3] or 0)
                pre_close = float(f[4] or 0)
                if price <= 0:
                    continue
                results.append(
                    QuoteData(
                        symbol=f[2],
                        name=f[1],
                        market="cn",
                        asset_type="stock",
                        current_price=price,
                        pre_close=pre_close,
                        open_price=float(f[5] or 0),
                        high_price=float(f[33] or 0),
                        low_price=float(f[34] or 0),
                        change_amount=float(f[31] or 0),
                        change_percent=float(f[32] or 0),
                        volume=float(f[36] or 0) * 100,      # 手 → 股
                        turnover=float(f[37] or 0) * 10000,   # 万 → 元
                        timestamp=f[30],                      # 数据源快照时间（yyyymmddHHMMSS，收盘态展示用）
                    )
                )
            except (ValueError, IndexError):
                continue
        return results

    async def _fetch_batch_tencent(self, symbols: List[str]) -> List[QuoteData]:
        """腾讯批量行情（异步包装；失败返回空列表由调用方走备源）"""
        try:
            return await asyncio.to_thread(self._fetch_batch_tencent_sync, symbols)
        except Exception as e:
            print(f"[AKShare] 腾讯批量接口失败: {e}", file=sys.stderr, flush=True)
            return []

    async def _fetch_single_sina(self, symbol: str) -> Optional[QuoteData]:
        """新浪单股实时行情接口（hq.sinajs.cn，约 0.5s）

        响应格式：var hq_str_sz000001="名称,今开,昨收,最新,最高,最低,买一,卖一,成交量(股),成交额(元),...";
        """
        import requests

        prefix = self._market_prefix(symbol)
        url = f"https://hq.sinajs.cn/list={prefix}{symbol}"
        try:
            resp = await asyncio.to_thread(
                lambda: requests.get(
                    url,
                    headers={
                        "Referer": "https://finance.sina.com.cn",
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                    },
                    timeout=5,
                )
            )
            resp.encoding = "gbk"
            fields = resp.text.split('"')[1].split(",")
            if len(fields) < 10:
                return None
            name = fields[0]
            open_price = float(fields[1] or 0)
            pre_close = float(fields[2] or 0)
            price = float(fields[3] or 0)
            high = float(fields[4] or 0)
            low = float(fields[5] or 0)
            volume = float(fields[8] or 0)
            turnover = float(fields[9] or 0)
            if not name or price <= 0:
                return None
            change = price - pre_close if pre_close > 0 else 0.0
            pct = (change / pre_close * 100) if pre_close > 0 else 0.0
            return QuoteData(
                symbol=symbol,
                name=name,
                market="cn",
                asset_type="stock",
                current_price=price,
                pre_close=pre_close,
                open_price=open_price,
                high_price=high,
                low_price=low,
                change_amount=round(change, 3),
                change_percent=round(pct, 3),
                volume=volume,
                turnover=turnover,
            )
        except Exception as e:
            print(f"[AKShare] 新浪单股接口失败 {symbol}: {e}", file=sys.stderr, flush=True)
            return None

    async def get_batch_quotes(self, symbols: List[str]) -> List[QuoteData]:
        """批量获取A股行情（腾讯批量接口优先，~0.3s；失败回退全市场快照过滤）

        持仓轮询场景只有几只股票，直接按需批量查询，
        不再为几只代码拉取全市场快照（新浪全量 ~15-20s 的主要来源）。
        """
        try:
            # 1) 腾讯批量直查（按需、快）
            quotes = await self._fetch_batch_tencent(symbols)
            if quotes:
                by_sym = {q.symbol: q for q in quotes}
                # 按请求顺序返回（腾讯可能忽略无效代码，缺失的走快照补齐）
                if len(quotes) == len(symbols):
                    return [by_sym.get(s) for s in symbols if by_sym.get(s)]

            # 2) 快照缓存命中 → 补齐腾讯缺失的代码
            df = self._cached_spot()
            if df is not None:
                by_sym = {q.symbol: q for q in quotes}
                results: List[QuoteData] = []
                for sym in symbols:
                    if sym in by_sym:
                        results.append(by_sym[sym])
                        continue
                    r = self._match_row(df, sym)
                    if r is not None:
                        results.append(self._row_to_quote(sym, r))
                if results:
                    return results

            # 3) 全量快照兜底（腾讯与缓存都失败时才拉全市场）
            df = await self._get_spot_df()
            if df is None:
                return quotes  # 腾讯部分结果也比空强
            by_sym = {q.symbol: q for q in quotes}
            results = []
            for sym in symbols:
                if sym in by_sym:
                    results.append(by_sym[sym])
                    continue
                r = self._match_row(df, sym)
                if r is not None:
                    results.append(self._row_to_quote(sym, r))
            return results
        except Exception as e:
            print(f"[AKShare] get_batch_quotes error: {e}", file=sys.stderr, flush=True)
            return []

    async def get_all_spot(self) -> pd.DataFrame:
        """获取全市场A股快照（用于本地缓存和筛选）"""
        df = await self._get_spot_df()
        return df if df is not None else pd.DataFrame()


class AKShareETFAdapter(DataAdapter):
    """AKShare 场内ETF/LOF实时行情适配器"""

    name = "akshare_etf"
    priority = 1

    def is_available(self) -> bool:
        # 轻量检查：仅验证库已安装，不做网络探测（同 AKShareAStockAdapter）
        try:
            import akshare  # noqa: F401

            return True
        except Exception:
            return False

    async def get_quote(self, symbol: str) -> Optional[QuoteData]:
        try:
            df = await asyncio.to_thread(ak.fund_etf_category_sina)
            row = df[df["代码"] == symbol]
            if row.empty:
                return None
            r = row.iloc[0]
            return QuoteData(
                symbol=symbol,
                name=str(r.get("名称", "")),
                market="cn",
                asset_type="fund_etf",
                current_price=float(r.get("最新价", 0) or 0),
                pre_close=float(r.get("昨收", 0) or 0),
                open_price=float(r.get("今开", 0) or 0),
                high_price=float(r.get("最高", 0) or 0),
                low_price=float(r.get("最低", 0) or 0),
                change_amount=float(r.get("涨跌额", 0) or 0),
                change_percent=float(r.get("涨跌幅", 0) or 0),
                volume=float(r.get("成交量", 0) or 0),
                turnover=float(r.get("成交额", 0) or 0),
            )
        except Exception as e:
            print(f"[AKShare ETF] get_quote error for {symbol}: {e}")
            return None

    async def get_batch_quotes(self, symbols: List[str]) -> List[QuoteData]:
        try:
            df = await asyncio.to_thread(ak.fund_etf_category_sina)
            results: List[QuoteData] = []
            for sym in symbols:
                row = df[df["代码"] == sym]
                if row.empty:
                    continue
                r = row.iloc[0]
                results.append(
                    QuoteData(
                        symbol=sym,
                        name=str(r.get("名称", "")),
                        market="cn",
                        asset_type="fund_etf",
                        current_price=float(r.get("最新价", 0) or 0),
                        pre_close=float(r.get("昨收", 0) or 0),
                        open_price=float(r.get("今开", 0) or 0),
                        high_price=float(r.get("最高", 0) or 0),
                        low_price=float(r.get("最低", 0) or 0),
                        change_amount=float(r.get("涨跌额", 0) or 0),
                        change_percent=float(r.get("涨跌幅", 0) or 0),
                        volume=float(r.get("成交量", 0) or 0),
                        turnover=float(r.get("成交额", 0) or 0),
                    )
                )
            return results
        except Exception as e:
            print(f"[AKShare ETF] get_batch_quotes error: {e}")
            return []
