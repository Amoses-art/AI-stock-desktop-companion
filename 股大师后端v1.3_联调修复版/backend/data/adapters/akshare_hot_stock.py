"""
涨停池/热度适配器 — AKShare 数据源

架构决策(ADR-018): 单源超时降级，失败返回空列表。
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List

from data.adapters.base import DataAdapter


class AKShareHotStockAdapter(DataAdapter):
    """涨停池/热度适配器"""

    _executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="akshare_hot")

    def is_available(self) -> bool:
        try:
            import akshare as ak
            return hasattr(ak, "stock_zt_pool")
        except Exception:
            return False

    async def get_hot_stocks(self) -> List[Dict[str, Any]]:
        """获取涨停池热度，超时 10 秒降级为空列表"""
        try:
            import akshare as ak
            from datetime import datetime

            loop = asyncio.get_event_loop()
            today = datetime.now().strftime("%Y%m%d")

            df = await asyncio.wait_for(
                loop.run_in_executor(
                    self._executor,
                    lambda: ak.stock_zt_pool(date=today),
                ),
                timeout=10.0,
            )

            results: List[Dict[str, Any]] = []
            for _, row in df.head(10).iterrows():
                try:
                    symbol = str(row.get("代码", "")).zfill(6)
                    name = str(row.get("名称", ""))
                    results.append({
                        "symbol": symbol,
                        "name": name,
                        "reason": f"今日涨停，{name}热度较高",
                        "risk": "高",
                    })
                except (ValueError, TypeError):
                    continue
            return results
        except Exception:
            return []

    async def get_quote(self, symbol: str) -> Any:
        """本适配器不支持单股行情"""
        return None
