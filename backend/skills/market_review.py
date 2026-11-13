"""大盘复盘 Skill — 指数概况 + 板块轮动 + 市场情绪 + 关键点位"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List

MOCK_MARKET_DATA: Dict[str, Any] = {
    "sh_index": {"name": "上证指数", "current": 3385.42, "change_percent": 0.85, "volume": 385000000},
    "sz_index": {"name": "深证成指", "current": 10892.15, "change_percent": 1.12, "volume": 512000000},
    "cy_index": {"name": "创业板指", "current": 2256.78, "change_percent": 1.45, "volume": 198000000},
    "up_count": 3285,
    "down_count": 1520,
    "limit_up": 68,
    "limit_down": 5,
    "north_inflow": 856000000,
    "leading_sectors": [
        {"name": "半导体", "change": 3.25},
        {"name": "消费电子", "change": 2.80},
        {"name": "通信设备", "change": 2.45},
    ],
    "lagging_sectors": [
        {"name": "银行", "change": -0.55},
        {"name": "保险", "change": -0.32},
        {"name": "煤炭", "change": -0.18},
    ],
    "support": 3350,
    "resistance": 3450,
    "gap_up": 3368,
    "sentiment": "偏乐观",
}


class MarketReviewSkill:
    """大盘复盘分析 Skill"""

    @staticmethod
    async def execute() -> Dict[str, Any]:
        data = await MarketReviewSkill._fetch_data()
        analysis = MarketReviewSkill._build_analysis(data)
        rating, rating_label = MarketReviewSkill._compute_rating(data)

        sh = data["sh_index"]
        sz = data["sz_index"]
        cy = data["cy_index"]

        return {
            "title": "大盘复盘",
            "subtitle": f"A股三大指数 | 涨跌家数 {data['up_count']}:{data['down_count']}",
            "metrics": [
                {"label": "上证指数", "value": f"{sh['current']:.2f} ({sh['change_percent']:+.2f}%)", "cls": "up" if sh['change_percent'] >= 0 else "down"},
                {"label": "深证成指", "value": f"{sz['current']:.2f} ({sz['change_percent']:+.2f}%)", "cls": "up" if sz['change_percent'] >= 0 else "down"},
                {"label": "创业板指", "value": f"{cy['current']:.2f} ({cy['change_percent']:+.2f}%)", "cls": "up" if cy['change_percent'] >= 0 else "down"},
                {"label": "涨停/跌停", "value": f"{data['limit_up']}/{data['limit_down']}", "cls": ""},
                {"label": "北向资金", "value": f"{data['north_inflow'] / 1e8:+.2f}亿", "cls": "up" if data['north_inflow'] >= 0 else "down"},
                {"label": "市场情绪", "value": data['sentiment'], "cls": ""},
            ],
            "analysis": analysis,
            "rating": rating,
            "ratingLabel": rating_label,
        }

    _executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="akshare_market")

    @staticmethod
    async def _fetch_data() -> Dict[str, Any]:
        """获取大盘数据，优先 AKShare，失败回退模拟数据。

        AKShare 为同步库，通过 ThreadPoolExecutor + asyncio.wait_for 包装，
        超时 15 秒后降级返回模拟数据。
        """
        try:
            import akshare as ak

            loop = asyncio.get_event_loop()

            def _fetch_index(symbol: str):
                # 用腾讯日线（更稳定，不受东方财富风控）
                # symbol 格式: sh000001 / sz399001 / sz399006
                import datetime as _dt
                end = _dt.date.today().strftime('%Y%m%d')
                start = (_dt.date.today() - _dt.timedelta(days=365)).strftime('%Y%m%d')
                return ak.stock_zh_index_daily_tx(symbol=symbol, start_date=start, end_date=end)

            # 并行获取三大指数，各 15 秒超时
            sh_df, sz_df, cy_df = await asyncio.wait_for(
                asyncio.gather(
                    loop.run_in_executor(MarketReviewSkill._executor, lambda: _fetch_index("sh000001")),
                    loop.run_in_executor(MarketReviewSkill._executor, lambda: _fetch_index("sz399001")),
                    loop.run_in_executor(MarketReviewSkill._executor, lambda: _fetch_index("sz399006")),
                ),
                timeout=15.0,
            )

            sh_latest = sh_df.iloc[-1]
            sh_prev = sh_df.iloc[-2] if len(sh_df) > 1 else sh_latest
            sh_change = (float(sh_latest["close"]) - float(sh_prev["close"])) / float(sh_prev["close"]) * 100

            sz_latest = sz_df.iloc[-1]
            sz_prev = sz_df.iloc[-2] if len(sz_df) > 1 else sz_latest
            sz_change = (float(sz_latest["close"]) - float(sz_prev["close"])) / float(sz_prev["close"]) * 100

            cy_latest = cy_df.iloc[-1]
            cy_prev = cy_df.iloc[-2] if len(cy_df) > 1 else cy_latest
            cy_change = (float(cy_latest["close"]) - float(cy_prev["close"])) / float(cy_prev["close"]) * 100

            return {
                "sh_index": {
                    "name": "上证指数",
                    "current": float(sh_latest["close"]),
                    "change_percent": sh_change,
                    "volume": float(sh_latest.get("amount", 0)),
                },
                "sz_index": {
                    "name": "深证成指",
                    "current": float(sz_latest["close"]),
                    "change_percent": sz_change,
                    "volume": float(sz_latest.get("amount", 0)),
                },
                "cy_index": {
                    "name": "创业板指",
                    "current": float(cy_latest["close"]),
                    "change_percent": cy_change,
                    "volume": float(cy_latest.get("amount", 0)),
                },
                "up_count": 0,
                "down_count": 0,
                "limit_up": 0,
                "limit_down": 0,
                "north_inflow": 0.0,
                "leading_sectors": [],
                "lagging_sectors": [],
                "support": float(sh_latest["low"]) * 0.98,
                "resistance": float(sh_latest["high"]) * 1.02,
                "gap_up": float(sh_prev["high"]),
                "sentiment": "中性",
            }
        except Exception:
            return MOCK_MARKET_DATA.copy()

    @staticmethod
    def _build_analysis(data: Dict[str, Any]) -> str:
        parts: List[str] = []

        sh = data["sh_index"]
        sz = data["sz_index"]
        cy = data["cy_index"]

        index_summary = (
            f"**指数概况**\n"
            f"• {sh['name']}：{sh['current']:.2f}（{sh['change_percent']:+.2f}%），"
            f"量能 {sh['volume'] / 1e8:.0f}亿\n"
            f"• {sz['name']}：{sz['current']:.2f}（{sz['change_percent']:+.2f}%），"
            f"量能 {sz['volume'] / 1e8:.0f}亿\n"
            f"• {cy['name']}：{cy['current']:.2f}（{cy['change_percent']:+.2f}%），"
            f"量能 {cy['volume'] / 1e8:.0f}亿"
        )
        parts.append(index_summary)

        if data.get("leading_sectors"):
            leading = "、".join([f"{s['name']}({s['change']:+.2f}%)" for s in data["leading_sectors"]])
            lagging = "、".join([f"{s['name']}({s['change']:+.2f}%)" for s in data["lagging_sectors"]])
            sectors = (
                f"**板块轮动**\n"
                f"• 领涨：{leading}\n"
                f"• 领跌：{lagging}"
            )
            parts.append(sectors)

        sentiment = (
            f"**市场情绪**\n"
            f"• 涨跌家数比：{data['up_count']} : {data['down_count']}\n"
            f"• 涨停 {data['limit_up']} 家，跌停 {data['limit_down']} 家\n"
            f"• 北向资金净流入：{data['north_inflow'] / 1e8:+.2f}亿\n"
            f"• 整体情绪：{data['sentiment']}"
        )
        parts.append(sentiment)

        key_levels = (
            f"**关键点位**\n"
            f"• 支撑位：{data['support']:.0f}\n"
            f"• 压力位：{data['resistance']:.0f}\n"
            f"• 近期缺口：{data['gap_up']:.0f}"
        )
        parts.append(key_levels)

        return "\n\n".join(parts)

    @staticmethod
    def _compute_rating(data: Dict[str, Any]) -> tuple:
        sh = data["sh_index"]["change_percent"]
        up_ratio = data["up_count"] / max(data["up_count"] + data["down_count"], 1)
        score = 0
        if sh > 0.5:
            score += 2
        elif sh > 0:
            score += 1
        if up_ratio > 0.55:
            score += 1
        if data["north_inflow"] > 0:
            score += 1
        if data["limit_up"] > data["limit_down"] * 5:
            score += 1

        if score >= 4:
            return ("buy", "积极")
        elif score >= 2:
            return ("hold", "中性")
        else:
            return ("sell", "谨慎")
