"""
YFinance 客户端 — 带本地缓存 + 指数退避重试 + 降级策略

封装 yfinance 调用，提供：
- 内存 LRU 缓存（100条）+ SQLite 持久化缓存
- 指数退避重试（1s → 2s → 4s，最多3次）
- 降级策略：重试失败后返回缓存/Mock
- 健康检查器同步感知降级状态
"""

from __future__ import annotations

import asyncio
import sys
import time
from collections import OrderedDict
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

from data.adapters.base import QuoteData
from data.health_checker import health_checker
from local.db import db


def _ensure_ascii_ca_bundle() -> None:
    """curl_cffi(libcurl) 在 Windows 上无法加载含非 ASCII（中文）路径的 CA 证书 bundle，
    报 curl(77) error adding trust anchors。本项目 venv 位于中文目录
    （...\\股大师后端v1.3_联调修复版\\backend\\.venv），yfinance 所有 HTTPS 请求会
    因此失败并静默降级到 Mock 行情。修复：将 certifi 证书复制到临时目录的纯 ASCII
    路径，并通过 CURLCA_BUNDLE 环境变量指定给 libcurl。须在首次 import yfinance 前执行。
    """
    import os
    import shutil
    import tempfile
    from pathlib import Path

    try:
        if os.environ.get("CURLCA_BUNDLE"):
            return
        import certifi

        src = Path(certifi.where())
        try:
            str(src).encode("ascii")
        except UnicodeEncodeError:
            pass
        else:
            return  # 证书路径本身为 ASCII，无需处理
        dst = Path(tempfile.gettempdir()) / "gudashi_cacert.pem"
        if not dst.exists() or dst.stat().st_size != src.stat().st_size:
            shutil.copyfile(src, dst)
        os.environ["CURLCA_BUNDLE"] = str(dst)
    except Exception:
        pass  # 修复失败不影响主流程（yfinance 按原路径继续尝试）


_ensure_ascii_ca_bundle()

# 日志降噪：yfinance 库内部的 Cookie/crumb 警告与 "possibly delisted" 误报
# 在轮询场景每分钟刷屏 stderr（实际行情由 Yahoo chart API 直连兜底，不影响功能），
# 将 yfinance logger 提升到 CRITICAL 级别抑制
try:
    import logging

    logging.getLogger("yfinance").setLevel(logging.CRITICAL)
    logging.getLogger("peewee").setLevel(logging.CRITICAL)  # yfinance 缓存依赖
except Exception:
    pass


# 可重试的网络异常类型
_RETRYABLE_EXCEPTIONS = (
    TimeoutError,
    ConnectionError,
    OSError,
)


class _YahooBlockedError(Exception):
    """Yahoo 通道被封（HTTP 403/429）：重试与回退 yfinance 库均无意义，须快速失败"""


# 通道封锁/证书类错误标记：命中即不可重试，避免每次轮询都烧数秒重试
_BLOCKED_MARKERS = (
    "403",
    "forbidden",
    "429",
    "too many requests",
    "curl: (77)",
    "trust anchors",
    "certificate verify",
    "certificate",
)


def _is_retryable_exception(exc: Exception) -> bool:
    """判断异常是否属于可重试的网络错误（非 404/无效 symbol/通道封锁）"""
    if isinstance(exc, _YahooBlockedError):
        return False
    if isinstance(exc, _RETRYABLE_EXCEPTIONS):
        return True
    # yfinance 内部可能抛出其他异常，检查消息
    msg = str(exc).lower()
    # 明确不可重试的情况
    if any(k in msg for k in ("not found", "invalid symbol", "no data found", "404")):
        return False
    # 通道封锁/证书错误：重试只会继续烧时间，直接快速失败
    if any(k in msg for k in _BLOCKED_MARKERS):
        return False
    # 其他异常默认可重试（网络相关）
    return True


def _is_trading_hours() -> bool:
    """判断当前是否处于盘中交易时间（09:30-15:00，简化版，仅用于缓存 TTL）"""
    now = datetime.now()
    weekday = now.weekday()
    if weekday >= 5:  # 周末
        return False
    hour_min = now.hour * 100 + now.minute
    return 930 <= hour_min <= 1500


def _cache_ttl_seconds() -> int:
    """返回当前缓存有效期（秒）：盘中 5 分钟，盘后 30 分钟"""
    return 300 if _is_trading_hours() else 1800


class YFinanceClient:
    """YFinance 缓存客户端

    缓存键格式: {symbol}_{interval}_{period}
    默认 interval="1d", period="1d"
    """

    MAX_MEMORY_CACHE = 100
    MAX_RETRIES = 3
    BACKOFF_DELAYS = [1.0, 2.0, 4.0]  # 指数退避间隔
    # 通道熔断：连续失败达到阈值即判定 Yahoo 通道不可用，
    # 冷却期内所有请求直接走缓存/mock（秒回），不再发起注定失败的网络请求
    BREAKER_FAIL_THRESHOLD = 2
    BREAKER_COOLDOWN_SECONDS = 600

    def __init__(self) -> None:
        self._memory_cache: OrderedDict[str, Dict[str, Any]] = OrderedDict()
        self._degraded = False
        self._last_degraded_at: Optional[float] = None
        self._fail_count = 0
        self._breaker_open_until = 0.0

    @property
    def is_degraded(self) -> bool:
        return self._degraded

    def _cache_key(self, symbol: str, interval: str = "1d", period: str = "1d") -> str:
        return f"{symbol}_{interval}_{period}"

    def _get_memory(self, cache_key: str) -> Optional[Dict[str, Any]]:
        """从内存 LRU 缓存获取"""
        if cache_key not in self._memory_cache:
            return None
        # 移到末尾（最近使用）
        self._memory_cache.move_to_end(cache_key)
        entry = self._memory_cache[cache_key]
        ttl = _cache_ttl_seconds()
        if time.time() - entry["cached_at"] > ttl:
            return None  # 已过期，但暂不删除（降级时可用）
        return entry

    def _set_memory(self, cache_key: str, data: Dict[str, Any]) -> None:
        """写入内存 LRU 缓存"""
        if len(self._memory_cache) >= self.MAX_MEMORY_CACHE:
            # 淘汰最旧的
            self._memory_cache.popitem(last=False)
        self._memory_cache[cache_key] = data

    async def _get_db_cache(self, cache_key: str) -> Optional[Dict[str, Any]]:
        """从 SQLite 缓存获取"""
        row = await db.fetchone(
            "SELECT * FROM quote_cache WHERE symbol = ?",
            (cache_key,),
        )
        if not row:
            return None
        ttl = _cache_ttl_seconds()
        updated_at = row.get("updated_at")
        if updated_at:
            try:
                from datetime import datetime
                dt = datetime.fromisoformat(str(updated_at).replace("Z", "+00:00"))
                if (datetime.now(dt.tzinfo) - dt).total_seconds() > ttl:
                    return None
            except Exception:
                pass
        return {
            "quote": QuoteData(
                symbol=row.get("symbol", "").split("_")[0],
                name=row.get("name", ""),
                market=row.get("market", "us"),
                asset_type="stock",
                current_price=row.get("current_price", 0.0),
                pre_close=row.get("pre_close", 0.0),
                open_price=row.get("open_price", 0.0),
                high_price=row.get("high_price", 0.0),
                low_price=row.get("low_price", 0.0),
                change_amount=row.get("change_amount", 0.0),
                change_percent=row.get("change_percent", 0.0),
                volume=row.get("volume", 0.0),
                turnover=row.get("turnover", 0.0),
                currency=row.get("currency", "USD"),
            ),
            "cached_at": time.time(),
        }

    async def _set_db_cache(self, cache_key: str, quote: QuoteData) -> None:
        """写入 SQLite 缓存"""
        await db.execute(
            """
            INSERT INTO quote_cache (symbol, market, name, current_price, pre_close, open_price, high_price, low_price,
                                     change_amount, change_percent, volume, turnover, currency, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(symbol) DO UPDATE SET
                market=excluded.market,
                name=excluded.name,
                current_price=excluded.current_price,
                pre_close=excluded.pre_close,
                open_price=excluded.open_price,
                high_price=excluded.high_price,
                low_price=excluded.low_price,
                change_amount=excluded.change_amount,
                change_percent=excluded.change_percent,
                volume=excluded.volume,
                turnover=excluded.turnover,
                currency=excluded.currency,
                updated_at=CURRENT_TIMESTAMP
            """,
            (
                cache_key,
                quote.market,
                quote.name,
                quote.current_price,
                quote.pre_close,
                quote.open_price,
                quote.high_price,
                quote.low_price,
                quote.change_amount,
                quote.change_percent,
                quote.volume,
                quote.turnover,
                quote.currency,
            ),
        )

    def _build_mock_quote(self, symbol: str, market: str) -> QuoteData:
        """生成 Mock 行情数据（降级用）"""
        import random
        base = 50 + random.randint(0, 300)
        change = round(random.uniform(-5, 5), 2)
        pre = round(base * (1 - change / 100), 2)
        return QuoteData(
            symbol=symbol,
            name=f"{symbol} (Mock)",
            market=market,
            asset_type="stock",
            current_price=round(base, 2),
            pre_close=pre,
            open_price=round(base * 0.99, 2),
            high_price=round(base * 1.03, 2),
            low_price=round(base * 0.97, 2),
            change_amount=round(base - pre, 2),
            change_percent=change,
            volume=float(random.randint(100000, 10000000)),
            turnover=0.0,
            currency="HKD" if market == "hk" else "USD",
        )

    async def fetch(
        self,
        symbol: str,
        market: str = "us",
        interval: str = "1d",
        period: str = "1d",
    ) -> Tuple[Optional[QuoteData], bool]:
        """获取行情，带缓存 + 重试 + 降级

        Returns:
            (quote, degraded): quote 为行情数据，degraded 表示是否处于降级模式
        """
        cache_key = self._cache_key(symbol, interval, period)

        # 1. 检查内存缓存
        mem_entry = self._get_memory(cache_key)
        if mem_entry:
            quote = mem_entry.get("quote")
            if quote:
                return quote, False

        # 2. 检查数据库缓存
        db_entry = await self._get_db_cache(cache_key)
        if db_entry:
            quote = db_entry.get("quote")
            if quote:
                # 回写内存
                self._set_memory(cache_key, db_entry)
                return quote, False

        # 3. 通道熔断：冷却期内不再发起注定失败的网络请求，直接降级回退（秒回）
        if self._breaker_open_until > time.time():
            self._degraded = True
            self._last_degraded_at = time.time()
            return await self._degraded_fallback(cache_key, symbol, market), True

        # 3. 调用 yfinance（带指数退避重试）
        last_exc: Optional[Exception] = None
        for attempt in range(self.MAX_RETRIES):
            try:
                quote = await self._fetch_from_yfinance(symbol, market, interval, period)
                if quote:
                    # 缓存结果
                    entry = {"quote": quote, "cached_at": time.time()}
                    self._set_memory(cache_key, entry)
                    await self._set_db_cache(cache_key, quote)
                    # 恢复正常 + 熔断复位
                    self._fail_count = 0
                    self._breaker_open_until = 0.0
                    if self._degraded:
                        self._degraded = False
                        self._last_degraded_at = None
                        print(f"[YFinanceClient] 恢复正常: {symbol}", file=sys.stderr, flush=True)
                    return quote, False
            except Exception as e:
                last_exc = e
                self._fail_count += 1
                if self._fail_count >= self.BREAKER_FAIL_THRESHOLD:
                    # 连续失败达标：打开熔断，冷却期内不再发起网络请求
                    self._breaker_open_until = time.time() + self.BREAKER_COOLDOWN_SECONDS
                    print(
                        f"[YFinanceClient] Yahoo 通道熔断 {self.BREAKER_COOLDOWN_SECONDS}s: {symbol}",
                        file=sys.stderr, flush=True,
                    )
                if not _is_retryable_exception(e):
                    # 不可重试，直接失败
                    print(f"[YFinanceClient] 不可重试错误 ({symbol}): {e}", file=sys.stderr, flush=True)
                    break
                delay = self.BACKOFF_DELAYS[attempt] if attempt < len(self.BACKOFF_DELAYS) else 4.0
                print(f"[YFinanceClient] 第 {attempt + 1} 次重试失败 ({symbol}): {e}, {delay}s 后重试...", file=sys.stderr, flush=True)
                await asyncio.sleep(delay)

        # 4. 重试均失败 -> 降级策略
        self._degraded = True
        self._last_degraded_at = time.time()
        print(f"[YFinanceClient] 降级模式: {symbol}, last_error={last_exc}", file=sys.stderr, flush=True)
        return await self._degraded_fallback(cache_key, symbol, market), True

    async def _degraded_fallback(
        self, cache_key: str, symbol: str, market: str
    ) -> QuoteData:
        """降级回退：过期缓存 → Mock（保证快速返回，绝不阻塞列表）"""
        # 4a. 返回缓存数据（即使过期）
        # 先查内存过期数据
        if cache_key in self._memory_cache:
            stale = self._memory_cache[cache_key].get("quote")
            if stale:
                print(f"[YFinanceClient] 返回过期内存缓存: {symbol}", file=sys.stderr, flush=True)
                return stale

        # 再查数据库过期数据
        row = await db.fetchone(
            "SELECT * FROM quote_cache WHERE symbol = ?",
            (cache_key,),
        )
        if row:
            stale = QuoteData(
                symbol=symbol,
                name=row.get("name", ""),
                market=market,
                asset_type="stock",
                current_price=row.get("current_price", 0.0),
                pre_close=row.get("pre_close", 0.0),
                open_price=row.get("open_price", 0.0),
                high_price=row.get("high_price", 0.0),
                low_price=row.get("low_price", 0.0),
                change_amount=row.get("change_amount", 0.0),
                change_percent=row.get("change_percent", 0.0),
                volume=row.get("volume", 0.0),
                turnover=row.get("turnover", 0.0),
                currency=row.get("currency", "USD"),
            )
            print(f"[YFinanceClient] 返回过期数据库缓存: {symbol}", file=sys.stderr, flush=True)
            return stale

        # 4b. 无缓存 -> Mock 数据
        mock = self._build_mock_quote(symbol, market)
        print(f"[YFinanceClient] 返回 Mock 数据: {symbol}", file=sys.stderr, flush=True)
        return mock

    def _fetch_chart_meta(self, symbol: str) -> Optional[dict]:
        """直连 Yahoo v8 chart API 获取行情 meta（同步，供 to_thread 调用）

        稳定性优于 yfinance 库：无需 cookie/crumb 握手，requests + certifi 走
        Python 原生 SSL，不受 curl_cffi 在中文 venv 路径下 CA 加载失败
        （curl 77）影响。
        """
        import requests

        r = requests.get(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
            params={"range": "1d", "interval": "1d"},
            timeout=10,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
        )
        if r.status_code in (403, 429):
            # 通道被封锁：重试/回退 yfinance 库只会继续烧时间，直接快速失败
            raise _YahooBlockedError(f"Yahoo channel blocked: HTTP {r.status_code}")
        r.raise_for_status()
        result = r.json().get("chart", {}).get("result")
        if not result:
            return None
        return result[0].get("meta")

    def _quote_from_chart_meta(self, symbol: str, market: str, meta: dict) -> Optional[QuoteData]:
        """从 chart API meta 构造 QuoteData"""
        price = meta.get("regularMarketPrice")
        if price is None:
            return None
        pre_close = meta.get("chartPreviousClose") or meta.get("previousClose") or price
        change_amount = price - pre_close
        change_percent = (change_amount / pre_close * 100) if pre_close > 0 else 0.0
        return QuoteData(
            symbol=symbol,
            name=meta.get("shortName") or meta.get("longName") or symbol,
            market=market,
            asset_type="stock",
            current_price=round(float(price), 2),
            pre_close=round(float(pre_close), 2),
            open_price=round(float(meta.get("regularMarketOpen") or 0), 2),
            high_price=round(float(meta.get("regularMarketDayHigh") or 0), 2),
            low_price=round(float(meta.get("regularMarketDayLow") or 0), 2),
            change_amount=round(change_amount, 2),
            change_percent=round(change_percent, 2),
            volume=float(meta.get("regularMarketVolume") or 0),
            turnover=0.0,
            currency=meta.get("currency", "USD" if market == "us" else "HKD"),
        )

    async def _fetch_from_yfinance(
        self,
        symbol: str,
        market: str,
        interval: str,
        period: str,
    ) -> Optional[QuoteData]:
        """底层行情获取：优先 Yahoo chart API 直连，失败回退 yfinance 库"""
        try:
            meta = await asyncio.to_thread(self._fetch_chart_meta, symbol)
            if meta:
                quote = self._quote_from_chart_meta(symbol, market, meta)
                if quote:
                    return quote
        except _YahooBlockedError:
            # 通道被封：不回退 yfinance 库（同样会被封锁），向上快速失败
            raise
        except Exception as e:
            print(
                f"[YFinanceClient] chart API 失败 ({symbol}): {e}，回退 yfinance 库",
                file=sys.stderr, flush=True,
            )

        import yfinance as yf

        ticker = yf.Ticker(symbol)
        hist = await asyncio.to_thread(ticker.history, period=period, interval=interval)
        if hist is None or hist.empty:
            return None

        latest = hist.iloc[-1]
        info = await asyncio.to_thread(lambda: ticker.info)

        close = float(latest.get("Close", 0) or 0)
        pre_close = float(latest.get("Previous Close", info.get("previousClose", close)) or close)
        change_amount = close - pre_close
        change_percent = (change_amount / pre_close * 100) if pre_close > 0 else 0.0

        return QuoteData(
            symbol=symbol,
            name=info.get("longName", info.get("shortName", symbol)),
            market=market,
            asset_type="stock",
            current_price=round(close, 2),
            pre_close=round(pre_close, 2),
            open_price=round(float(latest.get("Open", 0) or 0), 2),
            high_price=round(float(latest.get("High", 0) or 0), 2),
            low_price=round(float(latest.get("Low", 0) or 0), 2),
            change_amount=round(change_amount, 2),
            change_percent=round(change_percent, 2),
            volume=float(latest.get("Volume", 0) or 0),
            turnover=0.0,
            currency=info.get("currency", "USD" if market == "us" else "HKD"),
        )

    def get_degraded_status(self) -> Dict[str, Any]:
        """获取降级状态（供健康检查器同步）"""
        return {
            "degraded": self._degraded,
            "last_degraded_at": self._last_degraded_at,
            "memory_cache_size": len(self._memory_cache),
        }


# 全局单例
yfinance_client = YFinanceClient()
