"""
内容质量门禁 — 过滤低质量/违规内容

架构决策(ADR-023 评估项 #7):
- 从公告解读 7 个脚本中提取核心校验逻辑
- 适配桌宠后端的轻量级实现
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class QualityIssue:
    """质量问题"""
    level: str  # error | warning | info
    category: str
    message: str


class ContentQualityGate:
    """内容质量门禁

    校验维度：
    1. 事实一致性：价格/涨跌幅等数值是否在合理范围
    2. 格式规范：关键信息是否缺失
    3. 合规检查：是否包含违规内容
    4. 完整性：分析结论是否有数据支撑
    """

    # 数值合理范围
    PRICE_MAX = 100000.0
    PRICE_MIN = 0.0
    CHANGE_PERCENT_MAX = 30.0  # 日涨跌幅上限（排除新股/复牌）
    CHANGE_PERCENT_MIN = -30.0

    @classmethod
    def check(cls, content: str, data: Optional[Dict[str, Any]] = None) -> List[QualityIssue]:
        """对内容进行质量检查"""
        issues: List[QualityIssue] = []

        # 1. 空内容检查
        if not content or not content.strip():
            issues.append(QualityIssue("error", "completeness", "内容为空"))
            return issues

        # 2. 数值合理性检查
        if data:
            issues.extend(cls._check_numeric_validity(data))

        # 3. 关键信息缺失检查
        issues.extend(cls._check_completeness(content))

        # 4. 合规检查
        issues.extend(cls._check_compliance(content))

        # 5. 格式检查
        issues.extend(cls._check_format(content))

        return issues

    @classmethod
    def _check_numeric_validity(cls, data: Dict[str, Any]) -> List[QualityIssue]:
        """检查数值合理性"""
        issues: List[QualityIssue] = []

        current_price = data.get("current_price")
        if current_price is not None:
            if current_price < cls.PRICE_MIN or current_price > cls.PRICE_MAX:
                issues.append(QualityIssue(
                    "error", "numeric",
                    f"当前价格 {current_price} 超出合理范围"
                ))

        change_percent = data.get("change_percent")
        if change_percent is not None:
            if change_percent < cls.CHANGE_PERCENT_MIN or change_percent > cls.CHANGE_PERCENT_MAX:
                issues.append(QualityIssue(
                    "warning", "numeric",
                    f"涨跌幅 {change_percent}% 超出日常合理范围，请核实是否为新股/复牌"
                ))

        return issues

    @classmethod
    def _check_completeness(cls, content: str) -> List[QualityIssue]:
        """检查内容完整性"""
        issues: List[QualityIssue] = []

        # 分析类内容应有数据支撑
        if "分析" in content or "复盘" in content:
            if not any(kw in content for kw in ["元", "%", "涨", "跌", "价格", "市值"]):
                issues.append(QualityIssue(
                    "warning", "completeness",
                    "分析类内容缺少具体数据支撑"
                ))

        return issues

    @classmethod
    def _check_compliance(cls, content: str) -> List[QualityIssue]:
        """合规检查"""
        issues: List[QualityIssue] = []

        # 检查是否包含绝对化承诺
        absolute_terms = ["必涨", "必跌", "一定涨", "一定跌", "稳赚", "稳赔"]
        for term in absolute_terms:
            if term in content:
                issues.append(QualityIssue(
                    "error", "compliance",
                    f"内容包含绝对化承诺用语：'{term}'，违反投资咨询合规要求"
                ))

        # 检查是否包含内幕信息暗示
        insider_hints = ["内幕", "消息", "听说", "有人告诉我"]
        for hint in insider_hints:
            if hint in content:
                issues.append(QualityIssue(
                    "warning", "compliance",
                    f"内容可能包含未经证实的信息来源暗示：'{hint}'"
                ))

        return issues

    @classmethod
    def _check_format(cls, content: str) -> List[QualityIssue]:
        """格式检查"""
        issues: List[QualityIssue] = []

        # 检查是否有未闭合的括号/引号
        for pair in [("（", "）"), ("(", ")"), ("【", "】"), ('"', '"')]:
            if content.count(pair[0]) != content.count(pair[1]):
                issues.append(QualityIssue(
                    "info", "format",
                    f"括号/引号未闭合：{pair[0]}{pair[1]}"
                ))

        return issues

    @classmethod
    def is_passed(cls, issues: List[QualityIssue]) -> bool:
        """判断质量门禁是否通过（无 error 级别问题）"""
        return not any(i.level == "error" for i in issues)

    @classmethod
    def format_issues(cls, issues: List[QualityIssue]) -> str:
        """格式化问题列表为可读文本"""
        if not issues:
            return "内容质量检查通过"
        lines = ["内容质量检查结果："]
        for i in issues:
            emoji = {"error": "❌", "warning": "⚠️", "info": "ℹ️"}.get(i.level, "•")
            lines.append(f"{emoji} [{i.category}] {i.message}")
        return "\n".join(lines)
