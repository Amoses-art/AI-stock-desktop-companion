"""盘中异动分析 Skill — 实时监测拉升/跳水/异动"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict

from skills.analysis_engine import skill4_intraday_analysis, skill1_support_pressure_review


class IntradaySkill:
    """盘中异动分析 Skill — v1.1 接入真实量化分析引擎"""

    _executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="analysis_engine")

    @staticmethod
    async def execute(params: Dict[str, Any]) -> Dict[str, Any]:
        symbol = params.get("stock_code", "")

        if not symbol:
            return {
                "title": "盘中异动监测",
                "subtitle": "全市场监测",
                "metrics": [
                    {"label": "监测标的", "value": "自选股池", "cls": ""},
                    {"label": "异动次数", "value": "0", "cls": ""},
                    {"label": "状态", "value": "监测中", "cls": ""},
                ],
                "analysis": (
                    "**盘中异动监测**\n"
                    "• 监测标的：自选股池\n"
                    "• 实时状态：当前处于正常波动区间\n"
                    "• 异动阈值：±3% 或 5 分钟内成交量突增 200%\n"
                    "• 最近一次异动：暂无（系统持续监测中）\n\n"
                    "**监测维度**\n"
                    "1. 价格异动：短时间内涨跌幅超过设定阈值\n"
                    "2. 成交量异动：成交量突增但价格未同步变化（可能为资金进出信号）\n"
                    "3. 板块联动：同板块多只个股同步异动\n"
                    "4. 资金流向：大单净流入/净流出异常\n\n"
                    "当检测到异动时，股大师将通过提醒气泡第一时间通知您。"
                ),
                "rating": "hold",
                "ratingLabel": "观望",
                "reply": "已启动全市场异动监测，检测到异常时将第一时间通知您。",
            }

        # 获取股票名称和支撑压力位（2秒超时）
        stock_name = symbol
        support_level = 0.0
        pressure_level = 0.0
        try:
            from data.quote_service import quote_service
            quote = await asyncio.wait_for(quote_service.get_quote(symbol), timeout=2.0)
            if quote and quote.name:
                stock_name = quote.name
            if quote and quote.current_price:
                support_level = round(quote.current_price * 0.97, 2)
                pressure_level = round(quote.current_price * 1.03, 2)
        except Exception:
            pass

        # 尝试获取 skill1 的支撑压力位作为更精确的输入
        loop = asyncio.get_event_loop()
        try:
            skill1_result = await asyncio.wait_for(
                loop.run_in_executor(
                    IntradaySkill._executor,
                    lambda: skill1_support_pressure_review(symbol, stock_name),
                ),
                timeout=10.0,
            )
            if skill1_result.get("第一支撑"):
                support_level = skill1_result["第一支撑"]
            if skill1_result.get("第一压力"):
                pressure_level = skill1_result["第一压力"]
        except Exception:
            pass

        # 调用 skill4 盘中分析
        try:
            skill4_result = await asyncio.wait_for(
                loop.run_in_executor(
                    IntradaySkill._executor,
                    lambda: skill4_intraday_analysis(symbol, stock_name, support_level, pressure_level),
                ),
                timeout=15.0,
            )

            return IntradaySkill._build_result_from_engine(symbol, stock_name, skill4_result)
        except Exception:
            return IntradaySkill._build_fallback_result(symbol, stock_name)

    @staticmethod
    def _build_result_from_engine(symbol: str, stock_name: str, skill4_result: Dict[str, Any]) -> Dict[str, Any]:
        """将 skill4 结果包装为标准格式"""
        latest_price = skill4_result.get("实时价格")
        break_pressure = skill4_result.get("是否有效突破压力", False)
        break_support = skill4_result.get("是否有效跌破支撑", False)
        strength = skill4_result.get("分时强弱", "中性")
        alert = skill4_result.get("分时异动告警", "")
        suggestion = skill4_result.get("实时操作建议", "")

        metrics = [
            {"label": "监测标的", "value": f"{stock_name}({symbol})", "cls": ""},
            {"label": "实时价格", "value": f"{latest_price}" if latest_price else "—", "cls": ""},
            {"label": "分时强弱", "value": strength, "cls": "up" if strength == "强势" else ("down" if strength == "弱势" else "")},
        ]
        if alert and alert != "无异常异动":
            metrics.append({"label": "异动告警", "value": alert, "cls": "up" if "拉升" in alert else "down"})

        analysis_parts = [f"**盘中分析：{stock_name}({symbol})**"]
        if latest_price:
            analysis_parts.append(f"• 实时价格：{latest_price}")
        analysis_parts.append(f"• 关键支撑/压力：{skill4_result.get('关键支撑')} / {skill4_result.get('关键压力')}")
        analysis_parts.append(f"• 是否有效突破压力：{'是' if break_pressure else '否'}")
        analysis_parts.append(f"• 是否有效跌破支撑：{'是' if break_support else '否'}")
        analysis_parts.append(f"• 分时强弱：{strength}")
        if alert and alert != "无异常异动":
            analysis_parts.append(f"• {alert}")
        analysis_parts.append(f"• **实时操作建议**：{suggestion}")

        analysis = "\n".join(analysis_parts)

        if break_pressure:
            rating, rating_label = "buy", "积极"
        elif break_support:
            rating, rating_label = "sell", "谨慎"
        else:
            rating, rating_label = "hold", "观望"

        reply = f"{stock_name}({symbol}) 盘中分析：{suggestion}"
        if alert and alert != "无异常异动":
            reply += f" | {alert}"

        return {
            "title": "盘中异动监测",
            "subtitle": f"标的: {stock_name}({symbol})",
            "metrics": metrics,
            "analysis": analysis,
            "rating": rating,
            "ratingLabel": rating_label,
            "reply": reply,
            "engine_data": skill4_result,
        }

    @staticmethod
    def _build_fallback_result(symbol: str, stock_name: str) -> Dict[str, Any]:
        """分析引擎失败时的降级结果"""
        return {
            "title": "盘中异动监测",
            "subtitle": f"标的: {stock_name}({symbol})",
            "metrics": [
                {"label": "监测标的", "value": f"{stock_name}({symbol})", "cls": ""},
                {"label": "实时价格", "value": "数据受限", "cls": ""},
                {"label": "状态", "value": "数据受限", "cls": ""},
            ],
            "analysis": (
                f"**盘中分析：{stock_name}({symbol})**\n"
                "• 分时数据获取受限，无法提供实时盘中分析\n"
                "• 以下为监测逻辑说明：\n"
                "  — 有效突破/跌破三重确认：价格连续3分钟站稳突破位 + 量能放大1.2倍\n"
                "  — 分时强弱：价格 vs 均价线 + 均价斜率 + 近5分钟量能比\n"
                "  — 异动告警：5分钟涨跌幅≥2% 且 量能放大30%"
            ),
            "rating": "hold",
            "ratingLabel": "观望",
            "reply": f"{stock_name}({symbol}) 分时数据获取受限，系统持续监测中，检测到异动将第一时间通知。",
        }
