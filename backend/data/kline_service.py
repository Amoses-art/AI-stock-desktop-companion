"""
分时K线服务 — 腾讯分钟线接口（当日分时 + 近5日分时趋势）

接口：
  - 当日分时: https://web.ifzq.gtimg.cn/appstock/app/minute/query?code={prefix}{code}
  - 近5日分时: https://web.ifzq.gtimg.cn/appstock/app/day/query?code={prefix}{code}

分时数据行格式："{HHMM} {price} {volume} {direction}"（空格分隔）
"""

from __future__ import annotations

import asyncio
import re
import sys
import time
from typing import Any, Dict, List, Optional

import httpx

from data.adapters.tencent_adapter import TencentQuoteAdapter

_MINUTE_URL = "https://web.ifzq.gtimg.cn/appstock/app/minute/query?code={}"
_DAY_URL = "https://web.ifzq.gtimg.cn/appstock/app/day/query?code={}"

# 当日分时缓存 TTL（分钟级数据，交易时段内 20s 足够新鲜）
_SINGLE_TTL = 20
# 近5日分时缓存 TTL
_MULTI_TTL = 300


def _to_float(v: Any, default: float = 0.0) -> float:
    try:
        if v is None:
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def _parse_points(raw: str) -> List[Dict[str, Any]]:
    """解析分时数据文本 → [{t, price, vol}]（t 为 "HH:MM" 标签）"""
    points: List[Dict[str, Any]] = []
    for line in raw.split("\n"):
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        hm = parts[0]
        if len(hm) == 4 and hm.isdigit():
            label = f"{hm[:2]}:{hm[2:]}"
        else:
            label = hm
        price = _to_float(parts[1])
        if price <= 0:
            continue
        vol = _to_float(parts[2]) if len(parts) > 2 else 0.0
        points.append({"t": label, "price": price, "vol": vol})
    return points


class KlineService:
    """分时K线服务 — 腾讯分钟线（带短 TTL 内存缓存）"""

    def __init__(self) -> None:
        self._cache: Dict[str, Dict[str, Any]] = {}

    async def get_intraday(self, symbol: str, market: Optional[str] = None,
                           days: int = 1) -> Dict[str, Any]:
        """获取分时K线数据

        days=1 → 当日分时；days>1 → 近 N 日分时趋势（最多 5 日）
        返回: {symbol, market, days, pre_close, series: [{date, points}]}
        """
        from data.multi_market_router import MarketDetector

        norm_symbol, mkt = MarketDetector.normalize(symbol, market)
        cache_key = f"{mkt}:{norm_symbol}:{days}"
        now = time.time()
        cached = self._cache.get(cache_key)
        ttl = _SINGLE_TTL if days <= 1 else _MULTI_TTL
        if cached and now - cached["ts"] < ttl:
            return cached["data"]

        prefix = TencentQuoteAdapter._prefix_for(norm_symbol, mkt)
        if days <= 1:
            url = _MINUTE_URL.format(prefix)
            data = await asyncio.to_thread(self._fetch_json, url)
            result = self._parse_single_day(data, norm_symbol, mkt)
        else:
            url = _DAY_URL.format(prefix)
            data = await asyncio.to_thread(self._fetch_json, url)
            result = self._parse_multi_day(data, norm_symbol, mkt, max_days=min(days, 5))

        if result and result.get("series"):
            self._cache[cache_key] = {"ts": now, "data": result}
        return result

    # ---------- 解析 ----------
    def _parse_single_day(self, data: Any, symbol: str, market: str) -> Dict[str, Any]:
        node = self._find_node(data, symbol, market)
        if not node:
            return {}
        inner = node.get("data") if isinstance(node.get("data"), dict) else node
        raw = inner.get("data") or ""
        points = _parse_points(str(raw))
        if not points:
            return {}
        pre_close = self._extract_pre_close(inner.get("qt") or node.get("qt"))
        date = str(inner.get("date") or "")
        return {
            "symbol": symbol,
            "market": market,
            "days": 1,
            "pre_close": pre_close,
            "series": [{"date": date, "points": points}],
        }

    def _parse_multi_day(self, data: Any, symbol: str, market: str,
                         max_days: int = 5) -> Dict[str, Any]:
        node = self._find_node(data, symbol, market)
        if not node:
            return {}
        days_data = node.get("day") or []
        series: List[Dict[str, Any]] = []
        for item in days_data[:max_days * 2]:
            if not isinstance(item, dict):
                continue
            date = str(item.get("date") or "")
            raw = item.get("data") or ""
            points = _parse_points(str(raw))
            if points:
                series.append({"date": date, "points": points})
            if len(series) >= max_days:
                break
        if not series:
            return {}
        # 按日期升序（最旧在前，今日最后），前端叠加绘制时今日浮于最上层
        series.sort(key=lambda s: s["date"])
        pre_close = self._extract_pre_close(node.get("qt"))
        return {
            "symbol": symbol,
            "market": market,
            "days": len(series),
            "pre_close": pre_close,
            "series": series,
        }

    @staticmethod
    def _find_node(data: Any, symbol: str, market: str) -> Optional[Dict[str, Any]]:
        """在响应 data 节点中定位目标标的节点"""
        if not isinstance(data, dict):
            return None
        d = data.get("data")
        if not isinstance(d, dict):
            return None
        prefix = TencentQuoteAdapter._prefix_for(symbol, market)
        if prefix in d and isinstance(d[prefix], dict):
            return d[prefix]
        # 兜底：任意包含 "data"/"day" 的节点
        for v in d.values():
            if isinstance(v, dict) and ("data" in v or "day" in v):
                return v
        return None

    @staticmethod
    def _extract_pre_close(qt: Any) -> float:
        """从响应 qt 节点提取昨收（兼容字符串/字典两种形态）"""
        if not qt:
            return 0.0
        if isinstance(qt, str):
            parts = qt.split("~")
            return _to_float(parts[4]) if len(parts) > 4 else 0.0
        if isinstance(qt, dict):
            for key in ("prec", "pre_close", "PreClose"):
                if key in qt:
                    return _to_float(qt[key])
        return 0.0

    @staticmethod
    def _fetch_json(url: str) -> Any:
        try:
            resp = httpx.get(url, timeout=6.0, headers={"User-Agent": "Mozilla/5.0"})
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            print(f"[Kline] fetch failed: {url} err={e}", file=sys.stderr, flush=True)
            return None


# 全局单例
kline_service = KlineService()
