"""
公告解读 Skill — 公司公告分析与要点提取

架构决策(ADR-023/025): 深度研究类 Skill 采用 Agent 委托
当前状态：桩实现，返回友好降级提示
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from skills.agent_delegation import AgentDelegationService

delegation_service = AgentDelegationService()


class AnnouncementSkill:
    """公告解读 Skill — 委托 aily Agent 执行公告深度解读"""

    @staticmethod
    async def execute(params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        params = params or {}
        stock_codes = params.get("stock_codes", [])
        message = params.get("message", "")

        # 构建 Agent 委托参数
        agent_params = {
            "analysis_type": "announcement_analysis",
            "stock_codes": stock_codes,
            "query": message,
            "announcement_type": AnnouncementSkill._extract_type(message),
        }

        agent_result = await delegation_service.delegate(
            skill_name="announcement_analysis",
            params=agent_params,
        )

        return {
            "reply": agent_result.get("reply", "公告解读正在准备中，请稍后再试~"),
            "data": agent_result.get("data", {}),
            "attachments": agent_result.get("attachments", []),
        }

    @staticmethod
    def _extract_type(message: str) -> str:
        """从用户消息中提取公告类型关注点"""
        types = {
            "业绩预告": ["业绩预告", "业绩快报"],
            "增减持": ["增持", "减持", "回购"],
            "并购": ["收购", "并购", "重组"],
            "股权激励": ["股权激励", "员工持股"],
            "分红": ["分红", "派息", "送转"],
            "定增": ["定增", "非公开发行", "配股"],
            "重大合同": ["重大合同", "中标", "订单"],
        }
        lowered = message.lower()
        for ann_type, keywords in types.items():
            for kw in keywords:
                if kw in lowered:
                    return ann_type
        return ""
