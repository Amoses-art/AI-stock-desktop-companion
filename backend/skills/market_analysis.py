"""
市场分析 Skill — 三级分层架构

架构决策(ADR-024/025):
- L1 轻量大盘复盘: Python 本地执行，<1s 响应
- L2 跨市场比较: Agent 委托，港股/美股/A股联动分析
- L3 长期策略研究: Agent 委托，宏观经济+策略深度研究

当前状态：L1 调用 analysis_engine v1.1 skill6；L2/L3 走 Agent 委托桩
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, Optional

from skills.agent_delegation import AgentDelegationService
from skills.analysis_engine import skill6_market_overview_analysis


delegation_service = AgentDelegationService()


class MarketAnalysisSkill:
    """市场分析 Skill — 三级分层

    调用方式:
        await MarketAnalysisSkill.execute(level="l1")  # 轻量复盘
        await MarketAnalysisSkill.execute(level="l2")  # 跨市场比较
        await MarketAnalysisSkill.execute(level="l3")  # 长期策略
    """

    _executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="analysis_engine")

    @staticmethod
    async def execute(level: str = "l1", params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """执行市场分析

        Args:
            level: "l1" | "l2" | "l3"
            params: 可选参数，如 {"market": "global", "focus": "tech"}
        """
        params = params or {}

        if level == "l1":
            return await MarketAnalysisSkill._execute_l1()
        elif level == "l2":
            return await MarketAnalysisSkill._execute_l2(params)
        elif level == "l3":
            return await MarketAnalysisSkill._execute_l3(params)
        else:
            # 默认降级到 L1
            return await MarketAnalysisSkill._execute_l1()

    @staticmethod
    async def _execute_l1() -> Dict[str, Any]:
        """L1: 轻量大盘复盘 — 调用 analysis_engine v1.1 skill6"""
        loop = asyncio.get_event_loop()

        try:
            skill6_result = await asyncio.wait_for(
                loop.run_in_executor(
                    MarketAnalysisSkill._executor,
                    lambda: skill6_market_overview_analysis(),
                ),
                timeout=15.0,
            )

            # 如果数据获取受限，降级到基础 mock
            if all(v.get("状态") == "数据获取受限" for v in skill6_result.get("核心指数趋势", {}).values()):
                return MarketAnalysisSkill._build_mock_l1_result()

            return MarketAnalysisSkill._build_l1_result_from_engine(skill6_result)

        except Exception:
            return MarketAnalysisSkill._build_mock_l1_result()

    @staticmethod
    def _build_l1_result_from_engine(skill6_result: Dict[str, Any]) -> Dict[str, Any]:
        """将 skill6 结果包装为标准格式"""
        index_trend = skill6_result.get("核心指数趋势", {})
        fund_verify = skill6_result.get("资金面验证", {})
        sectors = skill6_result.get("赛道强弱排行", {})
        window = skill6_result.get("当前操作窗口", "中性观望窗口")
        position = skill6_result.get("全市场仓位基准", "中性")
        position_suggest = skill6_result.get("建议仓位区间", "30%-50%仓位")

        # 构造 metrics
        metrics = []
        for name, data in index_trend.items():
            if "最新点位" in data:
                change_str = ""
                short_trend = data.get("短期趋势", "")
                cls = "up" if short_trend == "上升" else ("down" if short_trend == "下降" else "")
                metrics.append({
                    "label": name,
                    "value": f"{data['最新点位']}（{short_trend}）",
                    "cls": cls,
                })

        if fund_verify.get("北向资金"):
            metrics.append({
                "label": "北向资金",
                "value": fund_verify["北向资金"],
                "cls": "up" if fund_verify.get("北向状态") == "流入" else "down",
            })
        if fund_verify.get("两市成交额"):
            metrics.append({
                "label": "两市成交额",
                "value": fund_verify["两市成交额"],
                "cls": "",
            })
        metrics.append({
            "label": "操作窗口",
            "value": window,
            "cls": "up" if "积极" in window else ("down" if "风险" in window else ""),
        })
        metrics.append({
            "label": "仓位建议",
            "value": position_suggest,
            "cls": "",
        })

        # 构造分析正文
        analysis_parts = ["**核心指数趋势**"]
        for name, data in index_trend.items():
            if "最新点位" in data:
                analysis_parts.append(
                    f"• {name}：{data['最新点位']}，短期{data.get('短期趋势', '')}，中期{data.get('中期趋势', '')}"
                )

        struct = skill6_result.get("分钟级技术结构", {})
        if struct:
            analysis_parts.append("\n**分钟级技术结构**")
            for k, v in struct.items():
                if isinstance(v, bool):
                    analysis_parts.append(f"• {k}：{'是' if v else '否'}")

        analysis_parts.append(f"\n**周期状态**：{skill6_result.get('周期状态', '')}")

        if fund_verify.get("北向资金"):
            analysis_parts.append(
                f"\n**资金面**：北向{fund_verify.get('北向状态', '')} {fund_verify.get('北向资金', '')}，"
                f"两市成交 {fund_verify.get('两市成交额', '')}（{fund_verify.get('量能状态', '')}）"
            )

        top_5 = sectors.get("领涨板块", [])
        bottom_5 = sectors.get("领跌板块", [])
        if top_5 or bottom_5:
            analysis_parts.append(f"\n**板块轮动**：领涨 {', '.join(top_5[:3])}；领跌 {', '.join(bottom_5[:3])}")

        analysis_parts.append(f"\n**仓位基准**：{position} — {position_suggest}")

        analysis = "\n".join(analysis_parts)

        # rating
        if "积极" in window or "可操作" in window:
            rating, rating_label = "buy", "积极"
        elif "谨慎" in window or "风险" in window:
            rating, rating_label = "sell", "谨慎"
        else:
            rating, rating_label = "hold", "中性"

        reply = f"大盘五维分析：当前处于{window}，建议{position_suggest}。"
        if skill6_result.get("事件影响标记", "").startswith("重大"):
            reply += " 注意：重大事件进行中，技术结构有效性降级。"

        return {
            "title": "大盘复盘",
            "subtitle": f"五维量化分析 | {window}",
            "metrics": metrics,
            "analysis": analysis,
            "rating": rating,
            "ratingLabel": rating_label,
            "reply": reply,
            "level": "l1",
            "analysis_type": "大盘复盘",
            "engine_data": skill6_result,
        }

    @staticmethod
    def _build_mock_l1_result() -> Dict[str, Any]:
        """数据受限时的降级结果"""
        return {
            "title": "大盘复盘",
            "subtitle": "数据获取受限，以下为基于历史模式的推演",
            "metrics": [
                {"label": "上证指数", "value": "数据受限", "cls": ""},
                {"label": "创业板指", "value": "数据受限", "cls": ""},
                {"label": "北向资金", "value": "数据受限", "cls": ""},
                {"label": "操作窗口", "value": "数据受限", "cls": ""},
            ],
            "analysis": (
                "**数据获取受限**\n"
                "• 当前网络环境无法获取实时大盘数据\n"
                "• 以下为基于历史模式的推演提示：\n"
                "• 建议关注三大指数短期趋势与中期趋势的一致性\n"
                "• 关注北向资金流向与两市成交额变化\n"
                "• 结合板块轮动判断市场结构性机会"
            ),
            "rating": "hold",
            "ratingLabel": "中性",
            "reply": "数据获取受限，以下为基于历史模式的推演。建议关注大盘趋势一致性及资金流向变化。",
            "level": "l1",
            "analysis_type": "大盘复盘",
        }

    @staticmethod
    async def _execute_l2(params: Dict[str, Any]) -> Dict[str, Any]:
        """L2: 跨市场比较分析 — Agent 委托

        分析港股/美股/A股联动，板块映射，资金流向等。
        """
        focus = params.get("focus", "")
        market = params.get("market", "global")

        agent_params = {
            "level": "l2",
            "analysis_type": "cross_market",
            "market": market,
            "focus": focus,
            **params,
        }

        agent_result = await delegation_service.delegate(
            skill_name="market_review_l2",
            params=agent_params,
        )

        return {
            "level": "l2",
            "analysis_type": "跨市场比较分析",
            "title": "跨市场比较分析",
            "reply": agent_result.get("reply", "跨市场分析正在准备中，请稍后再试~"),
            "data": agent_result.get("data", {}),
            "attachments": agent_result.get("attachments", []),
        }

    @staticmethod
    async def _execute_l3(params: Dict[str, Any]) -> Dict[str, Any]:
        """L3: 长期策略研究 — Agent 委托

        宏观经济趋势、政策解读、长期配置策略。
        """
        focus = params.get("focus", "")
        horizon = params.get("horizon", "12个月")

        agent_params = {
            "level": "l3",
            "analysis_type": "long_term_strategy",
            "horizon": horizon,
            "focus": focus,
            **params,
        }

        agent_result = await delegation_service.delegate(
            skill_name="market_review_l3",
            params=agent_params,
        )

        return {
            "level": "l3",
            "analysis_type": "长期策略研究",
            "title": "长期策略研究",
            "reply": agent_result.get("reply", "长期策略研究正在准备中，请稍后再试~"),
            "data": agent_result.get("data", {}),
            "attachments": agent_result.get("attachments", []),
        }
