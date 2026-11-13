"""
行业分析 Skill — 行业深度研究与趋势判断

架构决策(ADR-023/025): 深度研究类 Skill 采用 Agent 委托
当前状态：桩实现，返回友好降级提示
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from skills.agent_delegation import AgentDelegationService

delegation_service = AgentDelegationService()


class IndustryAnalysisSkill:
    """行业分析 Skill — 委托 aily Agent 执行深度行业研究"""

    @staticmethod
    async def execute(params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        params = params or {}
        message = params.get("message", "")

        # 提取行业名
        industry_name = params.get("industry_name", "")
        if not industry_name:
            industry_name = IndustryAnalysisSkill._extract_industry(message)

        # 构建 Agent 委托参数
        agent_params = {
            "analysis_type": "industry_analysis",
            "industry_name": industry_name,
            "query": message,
            "depth": params.get("depth", "standard"),  # standard | deep
        }

        agent_result = await delegation_service.delegate(
            skill_name="industry_analysis",
            params=agent_params,
        )

        return {
            "reply": agent_result.get("reply", "行业分析正在准备中，请稍后再试~"),
            "data": agent_result.get("data", {}),
            "attachments": agent_result.get("attachments", []),
        }

    @staticmethod
    def _extract_industry(message: str) -> str:
        """从用户消息中提取行业名称"""
        industries = [
            "半导体", "芯片", "新能源", "光伏", "电动车", "锂电池",
            "医药", "医疗", "消费", "白酒", "食品饮料", "互联网",
            "人工智能", "AI", "通信", "5G", "银行", "保险", "证券",
            "房地产", "基建", "钢铁", "煤炭", "石油", "化工",
            "航空", "物流", "教育", "传媒", "游戏", "零售",
        ]
        lowered = message.lower()
        for ind in industries:
            if ind in lowered:
                return ind
        return ""
