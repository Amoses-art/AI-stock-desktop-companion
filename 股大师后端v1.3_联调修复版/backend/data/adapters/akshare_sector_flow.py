"""
板块资金流向适配器 — AKShare 数据源

架构决策(ADR-018): 单源超时降级，失败返回空列表。
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List

from data.adapters.base import DataAdapter


class AKShareSectorFlowAdapter(DataAdapter):
    """板块资金流向适配器"""

    _executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="akshare_sector")

    def is_available(self) -> bool:
        try:
            import akshare as ak
            return hasattr(ak, "stock_sector_fund_flow")
        except Exception:
            return False

    async def get_sector_flow(self) -> List[Dict[str, Any]]:
        """获取板块资金流向，超时 10 秒降级为空列表"""
        try:
            import akshare as ak

            loop = asyncio.get_event_loop()
            df = await asyncio.wait_for(
                loop.run_in_executor(
                    self._executor,
                    lambda: ak.stock_sector_fund_flow(),
                ),
                timeout=10.0,
            )

            results: List[Dict[str, Any]] = []
            for _, row in df.head(20).iterrows():
                try:
                    name = str(row.get("名称", ""))
                    net_inflow = float(row.get("净流入", 0))
                    results.append({
                        "name": name,
                        "net_inflow": round(net_inflow / 1e8, 2),  # 转为亿
                        "change_percent": float(row.get("涨跌幅", 0)),
                    })
                except (ValueError, TypeError):
                    continue
            return results
        except Exception:
            return []

    async def get_quote(self, symbol: str) -> Any:
        """本适配器不支持单股行情"""
        return None
