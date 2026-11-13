"""
腾讯实时行情适配器 — A股/港股/美股 秒级行情主源

腾讯行情接口 https://qt.gtimg.cn/q= 支持一次请求批量拉取（逗号分隔），
返回字段稳定、速度快（~0.3s），是 1s 秒级刷新的核心支撑。

响应示例：
    v_sh600519="1~贵州茅台~600519~1285.13~1290.88~1291.00~...~20260910161448~-5.75~-0.45~...";
字段索引（~ 分隔）：
  [0]  未知标记      [1] 名称      [2] 代码      [3] 现价      [4] 昨收
  [5]  今开          [6] 成交量(手) [30] 时间(YYYYMMDDHHMMSS) [31] 涨跌额
  [32] 涨跌幅%       [33] 最高      [34] 最低     [36] 成交量(手) [37] 成交额(万)
"""

from __future__ import annotations

import asyncio
import re
import sys
from typing import List, Optional

import httpx

from data.adapters.base import DataAdapter, QuoteData

_TENCENT_URL = "https://qt.gtimg.cn/q={}"


class TencentQuoteAdapter(DataAdapter):
    """腾讯实时行情适配器（A股/港股/美股 + 场内ETF/LOF）"""

    name = "tencent_quote"
    priority = 0  # 高于 AKShare（10s 缓存），秒级刷新时优先命中
    # 服务范围：A股/港股/美股个股 + 场内基金（ETF/LOF）；场外基金走估值适配器
    asset_types = ["stock", "fund_etf", "fund_lof"]

    # 单次批量查询上限（保守值，接口允许 50+）
    BATCH_LIMIT = 40

    def is_available(self) -> bool:
        try:
            import httpx  # noqa: F401

            return True
        except Exception:
            return False

    # ---------- 市场前缀映射 ----------
    @staticmethod
    def _detect_market(symbol: str) -> str:
        """从 symbol 推断市场（路由层未显式传 market 时的兜底）"""
        sym = symbol.strip().upper()
        if sym.endswith(".HK") or re.fullmatch(r"HK\d{4,5}", sym):
            return "hk"
        if sym.endswith((".OQ", ".N")) or re.fullmatch(r"[A-Z][A-Z\.]{0,4}", sym):
            return "us"
        if sym.endswith((".SS", ".SZ", ".BJ")):
            return "cn"
        if re.fullmatch(r"\d{4,5}", sym):
            return "hk"
        return "cn"

    @staticmethod
    def _prefix_for(symbol: str, market: Optional[str] = None) -> str:
        """腾讯查询前缀：A股按代码段分 sh/sz/bj；港股 hk+5位补零；美股 us+ticker

        0.7.0 修复（用户实测反馈2）：
        - 港股内部代码为 5 位补零格式（1810.HK → hk01810），旧逻辑未补零导致
          查询恒无匹配，进而落入被墙的 yfinance 兜底超时；
        - 兼容 HK1810 / 1810.HK / 00700 / 700 等多种用户输入形态（统一剥前缀补零）；
        - market 参数默认 None：router 不传 market 时按 symbol 自检（旧默认 "cn"
          把港美股拼成 sz 前缀垃圾请求，港美股通道从未真正生效）。
        """
        sym = symbol.upper()
        market = market or TencentQuoteAdapter._detect_market(symbol)
        if market == "hk":
            code = sym.removesuffix(".HK")
            code = re.sub(r"^HK", "", code)
            return "hk" + code.zfill(5)
        if market == "us":
            return "us" + sym.removesuffix(".OQ").removesuffix(".N")
        # cn：A股/ETF/LOF
        if sym.startswith(("6", "9", "5", "68")):
            return "sh" + sym
        if sym.startswith(("0", "1", "2", "3")):
            return "sz" + sym
        if sym.startswith(("4", "8")):
            return "bj" + sym
        return "sz" + sym

    def _build_query(self, symbols: List[str], market: str) -> str:
        return ",".join(self._prefix_for(s, market) for s in symbols)

    @staticmethod
    def _parse_timestamp(raw: str) -> str:
        """归一化为 yyyymmddHHMMSS（契约 QuoteData.timestamp 格式）"""
        if not raw:
            return ""
        digits = re.sub(r"\D", "", raw)
        if len(digits) >= 14:
            return digits[:14]
        return digits

    @staticmethod
    def _f(v: str, default: float = 0.0) -> float:
        try:
            return float(v) if v not in ("", "-") else default
        except (TypeError, ValueError):
            return default

    @classmethod
    def _parse_line(cls, symbol: str, market: str, fields: List[str]) -> Optional[QuoteData]:
        """从腾讯单行字段数组构造 QuoteData"""
        if len(fields) < 35:
            return None
        name = fields[1] or fields[2] or symbol
        current = cls._f(fields[3])
        pre_close = cls._f(fields[4])
        open_price = cls._f(fields[5])
        high = cls._f(fields[33])
        low = cls._f(fields[34])
        change_amount = cls._f(fields[31])
        change_percent = cls._f(fields[32])
        volume = cls._f(fields[36])
        turnover_wan = cls._f(fields[37])
        currency = {"cn": "CNY", "hk": "HKD", "us": "USD"}.get(market, "CNY")
        return QuoteData(
            symbol=symbol,
            name=name,
            market=market,
            asset_type="stock",
            current_price=current,
            pre_close=pre_close,
            open_price=open_price,
            high_price=high,
            low_price=low,
            change_amount=change_amount,
            change_percent=change_percent,
            volume=volume,
            turnover=turnover_wan * 10000,
            currency=currency,
            timestamp=cls._parse_timestamp(fields[30]) if len(fields) > 30 else "",
        )

    def _fetch_raw(self, query: str) -> Optional[str]:
        try:
            resp = httpx.get(_TENCENT_URL.format(query), timeout=6.0,
                             headers={"User-Agent": "Mozilla/5.0"})
            resp.raise_for_status()
            return resp.text
        except Exception as e:
            print(f"[Tencent] fetch failed: {e}", file=sys.stderr, flush=True)
            return None

    @staticmethod
    async def resolve_name_fast(symbol: str, market: str = "cn") -> tuple:
        """快速解析代码名称（单请求 ~0.3s，盘后同样返回收盘快照）

        用于添加持仓时的名称自动填充与代码校验，不依赖交易时段。
        返回: (name, current_price, pre_close)
        """
        prefix = TencentQuoteAdapter._prefix_for(symbol, market)
        try:
            resp = await asyncio.to_thread(
                httpx.get, _TENCENT_URL.format(prefix),
                timeout=6.0, headers={"User-Agent": "Mozilla/5.0"},
            )
            resp.raise_for_status()
        except Exception:
            return "", 0.0, 0.0
        m = re.search(r'v_[^=]+="([^"]*)"', resp.text)
        if not m:
            return "", 0.0, 0.0
        fields = m.group(1).split("~")
        if len(fields) < 5:
            return "", 0.0, 0.0
        name = fields[1] or ""
        current = TencentQuoteAdapter._f(fields[3])
        pre_close = TencentQuoteAdapter._f(fields[4])
        return name, current, pre_close

    async def get_quote(self, symbol: str, market: Optional[str] = None) -> Optional[QuoteData]:
        """获取单只标的实时行情（market 缺省按 symbol 自检——0.7.0 修复）"""
        query = self._prefix_for(symbol, market)
        text = await asyncio.to_thread(self._fetch_raw, query)
        if not text:
            return None
        return self._parse_response(text, symbol, market or self._detect_market(symbol))

    async def get_batch_quotes(self, symbols: List[str], market: Optional[str] = None) -> List[QuoteData]:
        """批量获取行情（按 BATCH_LIMIT 分片并行；market 缺省逐只自检）"""
        results: List[QuoteData] = []
        chunks = [symbols[i:i + self.BATCH_LIMIT] for i in range(0, len(symbols), self.BATCH_LIMIT)]

        async def fetch(chunk: List[str]) -> List[QuoteData]:
            query = self._build_query(chunk, market)
            text = await asyncio.to_thread(self._fetch_raw, query)
            if not text:
                return []
            out = []
            for sym in chunk:
                q = self._parse_response(text, sym, market or self._detect_market(sym))
                if q:
                    out.append(q)
            return out

        for chunk in chunks:
            results.extend(await fetch(chunk))
        return results

    @staticmethod
    def _norm_code(symbol: str) -> str:
        """归一化代码用于响应匹配（0.7.0 修复）：
        - 剥交易所后缀（.HK/.OQ/.N）与 HK 前缀（HK1810 → 1810）
        - 纯数字补零到 5 位对齐腾讯港股内部代码（1810 → 01810）；
          A股 6 位 zfill(5) 无副作用
        - 美股 ticker 原样（腾讯返回 NVDA.OQ，剥后缀后与 NVDA 对齐）"""
        s = symbol.upper().removesuffix(".HK").removesuffix(".OQ").removesuffix(".N")
        s = re.sub(r"^HK", "", s)
        if s.isdigit():
            s = s.zfill(5)
        return s

    def _parse_response(self, text: str, symbol: str, market: str) -> Optional[QuoteData]:
        """从批量响应文本中解析目标 symbol 的行情

        响应为多行 v_xxx="..."，符号会被腾讯变换：
        - 美股：usNVDA 查询 → 返回行内代码 NVDA.OQ（旧逻辑 "NVDA.OQ" != "NVDA" 恒不匹配）
        - 港股：hk01810 查询 → 返回行内代码 01810（旧逻辑 "01810" != "1810" 恒不匹配）
        因此用 _norm_code 双侧归一化后再比对，另保留名称兜底。
        """
        target = self._norm_code(symbol)
        for m in re.finditer(r'v_[^=]+="([^"]*)"', text):
            payload = m.group(1)
            fields = payload.split("~")
            if len(fields) < 3:
                continue
            if self._norm_code(fields[2]) == target:
                return self._parse_line(symbol, market, fields)
            # 名称兜底（代码差异场景）
            line_name = fields[1]
            if line_name and (line_name in symbol or symbol.upper() in line_name.upper()):
                return self._parse_line(symbol, market, fields)
        return None
