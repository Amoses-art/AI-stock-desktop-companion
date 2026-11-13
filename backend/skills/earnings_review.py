"""
财报周期复盘 Skill — 财报解读与业绩点评

架构决策(ADR-023/025): 深度研究类 Skill 采用 Agent 委托
当前状态：桩实现，返回友好降级提示
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from skills.agent_delegation import AgentDelegationService

delegation_service = AgentDelegationService()


class EarningsReviewSkill:
    """财报周期复盘 Skill — 委托 aily Agent 执行财报深度分析"""

    @staticmethod
    async def execute(params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        params = params or {}
        stock_codes = params.get("stock_codes", [])
        message = params.get("message", "")

        # 构建 Agent 委托参数
        agent_params = {
            "analysis_type": "earnings_review",
            "stock_codes": stock_codes,
            "query": message,
            "period": EarningsReviewSkill._extract_period(message),
        }

        agent_result = await delegation_service.delegate(
            skill_name="earnings_review",
            params=agent_params,
        )

        return {
            "reply": agent_result.get("reply", "财报分析正在准备中，请稍后再试~"),
            "data": agent_result.get("data", {}),
            "attachments": agent_result.get("attachments", []),
        }

    @staticmethod
    def _extract_period(message: str) -> str:
        """从用户消息中提取财报周期"""
        import re
        # Q1/Q2/Q3/Q4
        m = re.search(r"Q[1-4]", message, re.IGNORECASE)
        if m:
            return m.group(0).upper()
        # 年报/季报/中报
        if "年报" in message:
            return "年报"
        if "中报" in message or "半年报" in message:
            return "中报"
        if "季报" in message:
            return "季报"
        # 默认空（由 Agent 判断最近一期）
        return ""
