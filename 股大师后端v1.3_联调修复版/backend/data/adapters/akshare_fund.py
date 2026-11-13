"""
AKShare 基金数据适配器 — 场外开放式基金日终净值
"""

from __future__ import annotations

import asyncio
from typing import List, Optional

import akshare as ak
import pandas as pd

from data.adapters.base import DataAdapter, QuoteData


class AKShareFundAdapter(DataAdapter):
    """AKShare 场外开放式基金净值适配器"""

    name = "akshare_fund_open"
    priority = 1

    def is_available(self) -> bool:
        # 轻量检查：仅验证库已安装，不做网络探测（同 AKShareAStockAdapter）
        try:
            import akshare  # noqa: F401

            return True
        except Exception:
            return False

    async def get_quote(self, symbol: str) -> Optional[QuoteData]:
        """获取单只基金净值"""
        try:
            df = await asyncio.to_thread(ak.fund_open_fund_daily_em)
            row = df[df["基金代码"] == symbol]
            if row.empty:
                return None
            r = row.iloc[0]
            nav = float(r.get("单位净值", 0) or 0)
            pre_nav = float(r.get("前交易日-单位净值", 0) or 0)
            change_pct = float(r.get("日增长率", 0) or 0)

            return QuoteData(
                symbol=symbol,
                name=str(r.get("基金简称", "")),
                market="cn",
                asset_type="fund_open",
                current_price=nav,
                pre_close=pre_nav,
                change_percent=change_pct,
            )
        except Exception as e:
            print(f"[AKShare Fund] get_quote error for {symbol}: {e}")
            return None

    async def get_batch_quotes(self, symbols: List[str]) -> List[QuoteData]:
        try:
            df = await asyncio.to_thread(ak.fund_open_fund_daily_em)
            results: List[QuoteData] = []
            for sym in symbols:
                row = df[df["基金代码"] == sym]
                if row.empty:
                    continue
                r = row.iloc[0]
                nav = float(r.get("单位净值", 0) or 0)
                pre_nav = float(r.get("前交易日-单位净值", 0) or 0)
                change_pct = float(r.get("日增长率", 0) or 0)
                results.append(
                    QuoteData(
                        symbol=sym,
                        name=str(r.get("基金简称", "")),
                        market="cn",
                        asset_type="fund_open",
                        current_price=nav,
                        pre_close=pre_nav,
                        change_percent=change_pct,
                    )
                )
            return results
        except Exception as e:
            print(f"[AKShare Fund] get_batch_quotes error: {e}")
            return []
