"""
场外开放式基金净值适配器 — A股场外基金（fund_open）净值查询

0.7.0 重写（用户实测反馈2/3）：原 FundMNFInfo 移动端接口已被封（ErrCode 61136），
腾讯 jj 前缀返回不稳定，导致场外基金数据全部失败。切换为：

主源：新浪基金净值接口 `hq.sinajs.cn/list=f_{code}`
  - 需要 Referer: https://finance.sina.com.cn/
  - 返回格式（GBK 编码）：var hq_str_f_110022="名称,单位净值,累计净值,昨净值,日期,?";
  - 78 字节轻量响应，~0.2s

备源：东财 f10 lsjz 历史净值 JSONP
  - https://api.fund.eastmoney.com/f10/lsjz?callback=jQuery1830&fundCode={code}&pageIndex=1&pageSize=1
  - 剥 JSONP 壳取 JSON，字段：DWJZ(单位净值)/FSRQ(日期)/JZZZL(日增长率)/LJJZ(累计净值)
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
from typing import List, Optional

import httpx

from data.adapters.base import DataAdapter, QuoteData

_SINA_FUND_URL = "https://hq.sinajs.cn/list=f_{}"
_EASTMONEY_LSJZ_URL = "https://api.fund.eastmoney.com/f10/lsjz"

# 单次最多查询的基金数（新浪支持批量逗号分隔，保守上限）
BATCH_LIMIT = 50


class FundEstimateAdapter(DataAdapter):
    """场外开放式基金净值适配器（fund_open 专用）"""

    name = "fund_estimate"
    priority = 0
    asset_types = ["fund_open"]

    def is_available(self) -> bool:
        try:
            import httpx  # noqa: F401
            return True
        except Exception:
            return False

    # ---------- 请求 ----------
    def _fetch_sina(self, codes: List[str]) -> Optional[str]:
        """批量请求新浪基金净值接口（同步阻塞，跑在线程池）

        0.7.0：主源替换 FundMNFInfo（已封锁 ErrCode 61136）
        """
        try:
            query = ",".join(f"f_{c}" for c in codes)
            resp = httpx.get(
                _SINA_FUND_URL.format(query),
                timeout=6.0,
                headers={
                    "User-Agent": "Mozilla/5.0",
                    "Referer": "https://finance.sina.com.cn/",
                },
            )
            resp.raise_for_status()
            resp.encoding = "gbk"
            return resp.text
        except Exception as e:
            print(f"[FundEstimate] sina fetch failed: {e}", file=sys.stderr, flush=True)
            return None

    def _fetch_eastmoney(self, code: str) -> Optional[dict]:
        """东财 f10 lsjz JSONP 备用源（0.7.0：替腾讯 jj 不稳定问题）"""
        try:
            params = {
                "callback": "jQuery1830",
                "fundCode": code,
                "pageIndex": 1,
                "pageSize": 1,
            }
            resp = httpx.get(
                _EASTMONEY_LSJZ_URL,
                params=params,
                timeout=6.0,
                headers={
                    "User-Agent": "Mozilla/5.0",
                    "Referer": "https://fundf10.eastmoney.com/",
                },
            )
            resp.raise_for_status()
            text = resp.text
            # 剥 JSONP 壳：jQuery1830({...})
            m = re.search(r"\{.*\}", text)
            if not m:
                return None
            return json.loads(m.group(0))
        except Exception as e:
            print(f"[FundEstimate] eastmoney lsjz fetch failed for {code}: {e}", file=sys.stderr, flush=True)
            return None

    # ---------- 解析 ----------
    @staticmethod
    def _f(v, default: float = 0.0) -> float:
        try:
            return float(v) if v not in (None, "", "--") else default
        except (TypeError, ValueError):
            return default

    def _parse_sina_line(self, text: str, symbol: str) -> Optional[QuoteData]:
        """解析新浪单行：var hq_str_f_110022="名称,单位净值,累计净值,昨净值,日期,...";

        0.7.0 主源解析。格式：fields[0]=名称, [1]=单位净值, [2]=累计净值,
        [3]=昨净值, [4]=净值日期。用单位净值作当前价、昨净值算涨跌幅。
        """
        # 匹配 hq_str_f_{symbol}="..."
        pattern = rf'hq_str_f_{re.escape(symbol)}="([^"]*)"'
        m = re.search(pattern, text)
        if not m:
            return None
        raw = m.group(1)
        if not raw:
            return None
        fields = raw.split(",")
        if len(fields) < 5:
            return None
        name = fields[0] or symbol
        nav = self._f(fields[1])        # 单位净值（当前）
        cum_nav = self._f(fields[2])    # 累计净值
        pre_nav = self._f(fields[3])   # 昨净值
        date_str = fields[4] or ""

        if nav <= 0:
            return None

        # 涨跌幅 = (今净值 - 昨净值) / 昨净值 * 100
        if pre_nav > 0:
            change_percent = round((nav - pre_nav) / pre_nav * 100, 2)
        else:
            change_percent = 0.0
        change_amount = round(nav - pre_nav, 4) if pre_nav > 0 else 0.0

        # timestamp: "2026-10-08" → "20261008000000"
        timestamp = date_str.replace("-", "") + "000000" if date_str else ""

        return QuoteData(
            symbol=symbol,
            name=name,
            market="cn",
            asset_type="fund_open",
            current_price=round(nav, 4),
            pre_close=round(pre_nav, 4),
            change_amount=change_amount,
            change_percent=change_percent,
            timestamp=timestamp,
        )

    def _parse_eastmoney_row(self, data: dict, symbol: str) -> Optional[QuoteData]:
        """解析东财 lsjz 返回（0.7.0 备源）

        Data[0]: DWJZ(单位净值), FSRQ(日期), JZZZL(日增长率), LJJZ(累计净值)
        """
        try:
            data_list = data.get("Data") or data.get("data") or []
            if not data_list:
                return None
            row = data_list[0]
            nav = self._f(row.get("DWJZ"))
            date_str = row.get("FSRQ") or ""
            chg = self._f(row.get("JZZZL"))
            cum_nav = self._f(row.get("LJJZ"))

            if nav <= 0:
                return None

            pre_nav = nav / (1 + chg / 100) if (1 + chg / 100) else 0.0
            timestamp = date_str.replace("-", "") + "000000" if date_str else ""

            return QuoteData(
                symbol=symbol,
                name=symbol,  # 东财 lsjz 不返回名称，用代码占位
                market="cn",
                asset_type="fund_open",
                current_price=round(nav, 4),
                pre_close=round(pre_nav, 4),
                change_amount=round(nav - pre_nav, 4),
                change_percent=round(chg, 2),
                timestamp=timestamp,
            )
        except Exception as e:
            print(f"[FundEstimate] eastmoney parse failed for {symbol}: {e}", file=sys.stderr, flush=True)
            return None

    # ---------- 主入口 ----------
    async def get_quote(self, symbol: str) -> Optional[QuoteData]:
        results = await self.get_batch_quotes([symbol])
        return results[0] if results else None

    async def get_batch_quotes(self, symbols: List[str]) -> List[QuoteData]:
        """批量获取场外基金净值（主源新浪 f_，备源东财 lsjz 逐只兜底）

        0.7.0 重写：FundMNFInfo 已封锁（61136），腾讯 jj 不稳定。
        """
        if not symbols:
            return []

        out: List[QuoteData] = []
        chunks = [symbols[i:i + BATCH_LIMIT] for i in range(0, len(symbols), BATCH_LIMIT)]

        for chunk in chunks:
            # 主源：新浪批量
            text = await asyncio.to_thread(self._fetch_sina, chunk)
            found = set()
            if text:
                for sym in chunk:
                    q = self._parse_sina_line(text, sym)
                    if q:
                        out.append(q)
                        found.add(sym)

            # 备源：东财逐只（仅补主源缺失项）
            missing = [s for s in chunk if s not in found]
            for sym in missing:
                data = await asyncio.to_thread(self._fetch_eastmoney, sym)
                if data:
                    q = self._parse_eastmoney_row(data, sym)
                    if q:
                        out.append(q)

        return out
