"""
YFinance 数据适配器 — 港股/美股实时行情

架构决策(ADR-026): 港股/美股数据源采用 yfinance 补充 AKShare 的覆盖不足。

覆盖市场：
- 美股 (us): AAPL, TSLA, MSFT 等
- 港股 (hk): 0700.HK, 3690.HK 等

Symbol 格式：
- 美股: 纯字母 ticker，如 "AAPL"
- 港股: xxxx.HK 或纯数字（自动补 .HK），如 "0700.HK" / "0700"
"""

from __future__ import annotations

import asyncio
from typing import List, Optional

from data.adapters.base import DataAdapter, QuoteData
from data.yfinance_client import yfinance_client


class YFinanceAdapter(DataAdapter):
    """YFinance 港股/美股实时行情适配器（带缓存 + 重试 + 降级）"""

    name = "yfinance"
    priority = 2  # 优先级低于 AKShare（CN 市场优先）

    def __init__(self, market: str = "us") -> None:
        self.market = market  # "us" | "hk"

    def is_available(self) -> bool:
        # 轻量检查：仅验证库已安装。
        # 不做网络探测（Ticker.info 国内网络可阻塞数十秒且同步阻塞 event loop），
        # 真实可用性由 YFinanceClient 降级状态 + HealthChecker 负责
        try:
            import yfinance  # noqa: F401

            return True
        except Exception:
            return False

    def _normalize_symbol(self, symbol: str) -> str:
        """标准化 symbol 为 yfinance 格式"""
        symbol = symbol.strip().upper()
        if self.market == "hk":
            code = symbol[:-3] if symbol.endswith(".HK") else symbol
            if code.isdigit():
                # Yahoo 港股代码为 4 位数字格式（0700.HK）；HKEX 官方 5 位代码
                # （如 00700.HK）Yahoo 虽返回 200 但 meta 全空，必须去前导零补齐 4 位
                code = (code.lstrip("0") or "0").zfill(4)
                return f"{code}.HK"
        return symbol

    async def get_quote(self, symbol: str) -> Optional[QuoteData]:
        """获取单只标的实时行情（走 YFinanceClient 缓存 + 重试）"""
        normalized = self._normalize_symbol(symbol)
        quote, degraded = await yfinance_client.fetch(
            symbol=normalized,
            market=self.market,
            interval="1d",
            period="1d",
        )
        if quote is None:
            return None
        # 标记降级状态
        quote.is_degraded = degraded  # type: ignore[attr-defined]
        # 返回用户输入的原始 symbol
        quote.symbol = symbol
        return quote

    async def get_batch_quotes(self, symbols: List[str]) -> List[QuoteData]:
        """批量获取行情（并发 + 单只 12s 硬超时；yfinance 批量 API 不稳定故逐个拉取）

        原串行实现下，3 只港股最坏可阻塞 100s+（每只最多 3 次重试 × 退避），
        直接拖垮 get_portfolio_quotes 的 8s 批量窗口与整个 portfolio.list。
        并发 + 超时兜底后，批量在单只超时上限内返回，慢源失败由 quote_service 跳过。
        """
        results: List[QuoteData] = []

        async def fetch_one(sym: str) -> Optional[QuoteData]:
            try:
                return await asyncio.wait_for(self.get_quote(sym), timeout=12.0)
            except (asyncio.TimeoutError, Exception) as e:
                print(f"[YFinance] 批量获取失败 {sym}: {e}", file=sys.stderr, flush=True)
                return None

        for sym, quote in zip(symbols, await asyncio.gather(*(fetch_one(s) for s in symbols))):
            if quote:
                results.append(quote)
        return results


class USYFinanceAdapter(YFinanceAdapter):
    """美股专用适配器"""

    name = "yfinance_us"

    def __init__(self) -> None:
        super().__init__(market="us")


class HKYFinanceAdapter(YFinanceAdapter):
    """港股专用适配器"""

    name = "yfinance_hk"

    def __init__(self) -> None:
        super().__init__(market="hk")
