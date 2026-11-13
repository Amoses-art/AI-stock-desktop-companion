"""
多市场数据路由 — 自动识别市场 + 选择适配器

架构决策(ADR-026): 多市场数据自动路由，支持 A股/港股/美股。
"""

from __future__ import annotations

import re
from dataclasses import replace
from typing import Dict, List, Optional, Tuple

from data.adapters.base import DataAdapter, QuoteData
from data.adapters.yfinance_adapter import USYFinanceAdapter, HKYFinanceAdapter
from data.adapters.tencent_adapter import TencentQuoteAdapter

# AKShare 适配器为可选依赖（打包环境可能未安装）
try:
    from data.adapters.akshare_a_share import AKShareAStockAdapter, AKShareETFAdapter
    from data.adapters.akshare_fund import AKShareFundAdapter
    _AKSHARE_AVAILABLE = True
except Exception:
    _AKSHARE_AVAILABLE = False

# 场外基金估值适配器（httpx 为必装依赖，直接引入）
from data.adapters.fund_estimate_adapter import FundEstimateAdapter


class MarketDetector:
    """市场检测器 — 根据 symbol 自动判断所属市场"""

    # 市场标识规则
    RULES: List[Tuple[str, List[str], List[str]]] = [
        # (market, 后缀匹配, 正则匹配)
        ("cn", [".SS", ".SZ", ".BJ"], [r"^\d{6}$"]),  # A股 6位数字
        # 0.7.0：补 HK1810 形态（用户实测输入；旧规则识别为 unknown → 前端误报「代码错误」）
        ("hk", [".HK"], [r"^\d{4,5}$", r"^HK\d{4,5}$"]),  # 港股 4-5位数字 / .HK 后缀 / HK前缀
        ("us", [], [r"^[A-Z\.]+$"]),  # 美股纯字母
    ]

    @classmethod
    def detect(cls, symbol: str) -> str:
        """检测 symbol 所属市场

        返回: "cn" | "hk" | "us" | "unknown"
        """
        symbol_upper = symbol.strip().upper()

        for market, suffixes, patterns in cls.RULES:
            # 检查后缀
            for suffix in suffixes:
                if symbol_upper.endswith(suffix):
                    return market
            # 检查正则
            for pattern in patterns:
                if re.match(pattern, symbol_upper):
                    return market

        return "unknown"

    @classmethod
    def normalize(cls, symbol: str, market: Optional[str] = None) -> Tuple[str, str]:
        """标准化 symbol 并返回 (标准化后的 symbol, 市场)

        示例：
        - "600519" -> ("600519", "cn")
        - "0700.HK" -> ("0700.HK", "hk")
        - "0700" -> ("0700.HK", "hk")  # 4-5位数字自动识别为港股并补零
        - "HK1810" -> ("01810.HK", "hk")  # 0.7.0：HK前缀形态统一（用户实测输入）
        - "AAPL" -> ("AAPL", "us")
        """
        symbol = symbol.strip()
        detected = market or cls.detect(symbol)

        if detected == "hk":
            # 统一为 XXXXX.HK 格式（内部使用，对齐腾讯港股内部 5 位补零代码）
            # 0.7.0 修复：兼容 HK1810 前缀形态；HK1810/1810/1810.HK → 01810.HK
            sym = symbol.upper().removesuffix(".HK")
            sym = re.sub(r"^HK", "", sym)
            if sym.isdigit():
                symbol = f"{sym.zfill(5)}.HK"

        return symbol, detected


class MultiMarketDataAdapter:
    """多市场数据适配器 — 统一入口，自动路由到对应市场的适配器"""

    def __init__(self) -> None:
        # 按市场注册适配器（按优先级排序）
        cn_adapters: List[DataAdapter] = [
            TencentQuoteAdapter(),   # A股/ETF/LOF 秒级主源
            FundEstimateAdapter(),   # 场外基金盘中估值（fund_open）
        ]
        if _AKSHARE_AVAILABLE:
            cn_adapters.extend([
                AKShareAStockAdapter(),
                AKShareETFAdapter(),
                AKShareFundAdapter(),
            ])

        self._adapters: Dict[str, List[DataAdapter]] = {
            "cn": cn_adapters,
            "hk": [
                TencentQuoteAdapter(),
                HKYFinanceAdapter(),
            ],
            "us": [
                TencentQuoteAdapter(),
                USYFinanceAdapter(),
            ],
        }

    def get_adapters(self, market: str, asset_type: str = "stock") -> List[DataAdapter]:
        """获取指定市场 + 资产类型的适配器列表"""
        adapters = self._adapters.get(market, [])
        if asset_type:
            adapters = [a for a in adapters if a.serves(asset_type)]
        return adapters

    @staticmethod
    def _call_get_quote(adapter: DataAdapter, symbol: str, market: str):
        """鸭子类型调用 get_quote：腾讯适配器扩展了 market 参数（0.7.0 修复），
        yfinance 等旧适配器签名只有 symbol。优先尝试传 market，TypeError 兜底。"""
        try:
            return adapter.get_quote(symbol, market)
        except TypeError:
            return adapter.get_quote(symbol)

    @staticmethod
    def _call_get_batch(adapter: DataAdapter, symbols: List[str], market: str):
        """鸭子类型调用 get_batch_quotes（同上）"""
        try:
            return adapter.get_batch_quotes(symbols, market)
        except TypeError:
            return adapter.get_batch_quotes(symbols)

    async def get_quote(self, symbol: str, market: Optional[str] = None,
                        asset_type: str = "stock") -> Optional[QuoteData]:
        """获取单只标的行情 — 自动检测市场并按资产类型路由

        0.7.0 修复：将 detected_market 传给适配器（旧逻辑只调 adapter.get_quote(symbol)，
        腾讯适配器 market 默认 None 自检虽已修，但显式传递更可靠且日志清晰）。
        0.7.0 修复2：回填原始 symbol——normalize 把 HK1810 → 01810.HK 传给适配器，
        但 QuoteData.symbol 需保持调用方原始值，否则 portfolio quote_map 失配。
        """
        normalized, detected_market = MarketDetector.normalize(symbol, market)

        adapters = self.get_adapters(detected_market, asset_type)
        for adapter in adapters:
            if not adapter.is_available():
                continue
            quote = await self._call_get_quote(adapter, normalized, detected_market)
            if quote:
                quote.symbol = symbol  # 回填原始 symbol（保持 portfolio quote_map 一致）
                return quote

        return None

    async def get_batch_quotes(self, symbols: List[str],
                               asset_type: str = "stock") -> List[QuoteData]:
        """批量获取行情 — 按市场分组后按资产类型路由

        0.7.0 修复：market 分组后传给适配器（旧逻辑只调 adapter.get_batch_quotes(syms)，
        港美股被腾讯适配器内部默认 cn 路由，批量请求拼成 sz 前缀垃圾请求）。
        0.7.0 修复2：回填原始 symbol（同 get_quote，避免 quote_map 失配）。
        """
        # 按市场分组（normalize 后港股统一为 01810.HK 形态）
        market_groups: Dict[str, List[str]] = {}
        norm_to_origs: Dict[str, List[str]] = {}  # normalized → 原始写法列表
        for sym in symbols:
            normalized, market = MarketDetector.normalize(sym)
            norm_to_origs.setdefault(normalized, []).append(sym)
            bucket = market_groups.setdefault(market, [])
            if normalized not in bucket:
                bucket.append(normalized)

        results: List[QuoteData] = []
        for market, syms in market_groups.items():
            adapters = self.get_adapters(market, asset_type)
            for adapter in adapters:
                if not adapter.is_available():
                    continue
                quotes = await self._call_get_batch(adapter, syms, market)
                results.extend(quotes)
                # 如果已获取全部，跳出（用 normalized 匹配）
                found_symbols = {q.symbol for q in quotes}
                syms = [s for s in syms if s not in found_symbols]
                if not syms:
                    break

        # 展开回原始 symbol：HK1810 与 1810.HK 归一后同值，可能对应多个原始写法，
        # 必须逐个还原（旧逻辑用 dict 回填，重复归一化键会丢失其中一个原始 symbol）。
        expanded: List[QuoteData] = []
        for q in results:
            origs = norm_to_origs.get(q.symbol)
            if not origs:
                expanded.append(q)
                continue
            for orig in origs:
                expanded.append(q if orig == q.symbol else replace(q, symbol=orig))
        return expanded

    def is_market_available(self, market: str) -> bool:
        """检查指定市场是否有可用适配器"""
        adapters = self.get_adapters(market)
        return any(adapter.is_available() for adapter in adapters)


# 全局单例
multi_market_adapter = MultiMarketDataAdapter()
