"""
回复边界过滤器 — 拦截内部机制暴露
"""

from __future__ import annotations

import re
from typing import List


class ReplyFilter:
    """回复边界过滤器 — 在 handle_chat 输出层拦截违规内容"""

    BANNED_PATTERNS: List[str] = [
        r"本\s*Skill",
        r"Skill\s*名称",
        r"我是通过.*Skill.*查询的",
        r"我使用.*Skill.*分析",
        r"通过.*技能.*",
        r"检索轮次",
        r"内部机制",
        r"lane|tier|门禁|子命题|执行合同",
        r"facts\.json|finalize_report|playbook|check_facts",
        r"Tier\s*[123]|三级调用|Level\s*[123]",
        r"L[123]\s*调用",
        r"AKShare|akshare",
        r"Mock\s*数据|模拟数据|mock",
        r"降级模式|降级到|offline|degraded",
        r"JSON\s*Lines|RPC|Tauri|Python\s*后端",
        r"数据库表结构|字段名称|SQLite",
        r"HealthChecker|TradingHoursGuard|AlertEngine",
        r"_INTERNAL_DO_NOT_DELIVER",
        r"DO_NOT_DELIVER",
        r"00_RESUME_HERE",
        r"已生成.*文件",
        r"中间产物|中间文件",
        r"交付清单|文件列表",
        r"数据来源.*索引",
        r"原始 JSON",
    ]

    REPLACEMENT_MAP: dict[str, str] = {
        "AKShare": "行情数据源",
        "akshare": "行情数据源",
        "Mock": "",
        "mock": "",
        "SQLite": "本地存储",
        "RPC": "通信",
        "Tauri": "桌面框架",
        "JSON Lines": "数据通信",
    }

    @classmethod
    def filter(cls, reply: str) -> str:
        """过滤违规内容 + 剥离 dict repr / code fence。同步、不抛异常。"""
        if not reply:
            return reply
        try:
            filtered = reply
            # 1. 剥离 Markdown 代码块 `...`
            filtered = re.sub(r"`[\w]*\n.*?`", "", filtered, flags=re.DOTALL)
            # 2. 剥离 Python dict 字面量 {'key': 'val', ...}
            filtered = re.sub(r"\{[^{}]*'[\w]+':\s*'[^']*',?[^{}]*\}", "", filtered)
            # 3. 剥离 JSON dict 字面量 {"key": "val", ...}
            filtered = re.sub(r'\{[^{}]*"[\w]+":\s*"[^"]*",?[^{}]*\}', "", filtered)
            # 4. 剥离裸露 list 中的 dict: [{'symbol':...}, {...}]
            filtered = re.sub(r"\[\s*\{[^\[\]]+\}\s*,?\s*\]", "", filtered)
            # 5. BANNED_PATTERNS
            for pattern in cls.BANNED_PATTERNS:
                filtered = re.sub(pattern, "", filtered, flags=re.IGNORECASE)
            # 6. 空白清理
            filtered = re.sub(r"\n{3,}", "\n\n", filtered)
            filtered = re.sub(r" {2,}", " ", filtered)
            return filtered.strip()
        except Exception:
            return reply

    @classmethod
    def add_risk_disclaimer(cls, reply: str, intent: str = "") -> str:
        """为分析类回复统一添加风险提示语"""
        if not reply:
            return reply
        analysis_intents = {
            "stock_review", "market_review", "trend_recommendation",
            "stock_screening", "industry_analysis", "announcement_analysis",
            "earnings_review", "simulation", "intraday",
        }
        if intent not in analysis_intents:
            return reply
        disclaimer = (
            "回答基于AI生成，仅用于信息参考与研究辅助，不构成任何投资建议。"
            "股市有风险，请结合自身风险承受能力决策。"
        )
        if disclaimer in reply:
            return reply
        # 文末追加（角色设定：文末风控声明；开头拼接会阻断"从我的分析来看："语义）
        return f"{reply}\n\n{disclaimer}"

    @classmethod
    def filter_help(cls, reply: str) -> str:
        """Help 回复专用过滤"""
        reply = re.sub(r"[•\-\*]\s*\w+Skill.*", "", reply)
        reply = re.sub(r"\w+Skill", "", reply)
        return cls.filter(reply)
