"""
选股 Skill — 智能筛选与比较

架构决策(ADR-023/025): 深度研究类 Skill 采用 Agent 委托
当前状态：桩实现，返回友好降级提示
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from skills.agent_delegation import AgentDelegationService

delegation_service = AgentDelegationService()


class StockScreeningSkill:
    """选股 Skill — 委托 aily Agent 执行深度筛选"""

    @staticmethod
    async def execute(params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        params = params or {}
        stock_codes = params.get("stock_codes", [])
        message = params.get("message", "")

        # 构建 Agent 委托参数
        agent_params = {
            "analysis_type": "stock_screening",
            "stock_codes": stock_codes,
            "query": message,
            "criteria": StockScreeningSkill._extract_criteria(message),
        }

        agent_result = await delegation_service.delegate(
            skill_name="stock_screening",
            params=agent_params,
        )

        return {
            "reply": agent_result.get("reply", "选股分析正在准备中，请稍后再试~"),
            "data": agent_result.get("data", {}),
            "attachments": agent_result.get("attachments", []),
        }

    @staticmethod
    def _extract_criteria(message: str) -> Dict[str, Any]:
        """从用户消息中提取选股条件"""
        criteria: Dict[str, Any] = {}
        lowered = message.lower()

        # 市值偏好
        if "大盘" in message or "蓝筹" in message:
            criteria["market_cap"] = "large"
        elif "中小盘" in message or "成长" in message:
            criteria["market_cap"] = "small_mid"

        # 行业偏好
        sectors = ["科技", "医药", "消费", "新能源", "半导体", "金融", "地产"]
        for s in sectors:
            if s in message:
                criteria.setdefault("sectors", []).append(s)

        # 估值偏好
        if "低估" in message or "便宜" in message:
            criteria["valuation"] = "undervalued"
        elif "高成长" in message:
            criteria["valuation"] = "growth"

        # 技术指标
        if "突破" in message:
            criteria["technical"] = "breakout"
        elif "反弹" in message:
            criteria["technical"] = "rebound"

        return criteria
