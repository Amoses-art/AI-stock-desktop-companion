"""
澄清层 (Layer 4) — 同步执行

职责：当 SchemaExtractor 置信度不足或 Validator 校验失败时，
生成精确的反问话术，引导用户补充信息，绝不猜测。

接口契约：
- 同步方法（sync），不抛异常
- 输出包含 clarification_message（反问话术）和 missing_required（缺失字段列表）
- 话术模板可外置配置，支持热更新
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from core.validator import ValidationError, ValidatorResult


@dataclass(frozen=True)
class ClarifierResult:
    """澄清结果"""

    needs_clarification: bool
    clarification_message: Optional[str] = None
    missing_required: List[str] = field(default_factory=list)
    suggested_intent: Optional[str] = None


class Clarifier:
    """L4 澄清器 — 同步

    触发条件：
    1. 意图置信度 < 0.5（歧义）
    2. 必填参数缺失
    3. Validator 校验失败
    4. 多意图冲突（如同时命中 stock_review 和 quote_query）

    话术类型：
    A. 缺失反问 — 用户没给够参数
    B. 歧义澄清 — 用户意图不明确
    C. 校验失败解释 — 参数格式/范围不对

    接口契约：
    - clarify() 为同步方法，不抛异常
    - 所有话术生成失败时 fallback 到通用反问
    """

    # 默认话术模板（可外置热更新）
    DEFAULT_TEMPLATES: Dict[str, List[str]] = {
        # === A. 缺失反问 ===
        "missing_stock_code": [
            "你想分析哪只股票？请告诉我 6 位代码，比如 600519~",
            "请补充股票代码，我才能帮你分析哦~",
        ],
        "missing_date": [
            '你想查哪天的数据？可以说"今天"、"昨天"或具体日期~',
            '请告诉我日期，比如"今天"或"2024-01-15"~',
        ],
        "missing_threshold": [
            "你想设置多少百分比的提醒？比如 3% 或 5%~",
            "请告诉我提醒阈值，比如涨跌 3% 时通知你~",
        ],
        "missing_target_price": [
            "你想在什么价格时收到提醒？",
            "请告诉我目标价格~",
        ],
        "missing_industry_name": [
            "你想研究哪个行业呢？比如新能源、半导体、医药等~",
            "请告诉我行业名称，我才能帮你做行业分析~",
        ],
        "missing_company": [
            "请告诉我是哪家公司？",
            "你想了解哪家公司的信息？",
        ],

        # === B. 歧义澄清 ===
        "ambiguous_intent": [
            "你的问题我好像理解了几种可能，你最想了解的是？\n1. 个股行情查询\n2. 个股复盘分析\n3. 大盘走势",
            "可以再说清楚一点吗？你是想查行情、做复盘，还是看大盘？",
        ],
        "ambiguous_stock": [
            "你提到了多只股票，想重点分析哪一只？",
            "多只股票同时分析可能不够聚焦，先选一只重点看看？",
        ],
        "ambiguous_time": [
            "时间描述有点模糊，是指今天、本周还是某个具体日期？",
            "请问你关注的是哪个时间段的数据？",
        ],

        # === C. 校验失败解释 ===
        "invalid_stock_code": [
            "股票代码格式不太对哦，请输入 6 位数字（如 600519）~",
            "这个代码我看不懂，A 股代码是 6 位数字，比如 000001~",
        ],
        "invalid_date_future": [
            "这个日期还没到呢，我只能查过去和最近几天的数据~",
            "未来太远的日期暂时查不了，换个近一点的日期试试？",
        ],
        "invalid_date_past": [
            "这个日期太久远了，我目前支持最近 5 年的数据~",
            "数据存档有限，换个近一点的日期吧~",
        ],
        "invalid_threshold": [
            "这个阈值有点夸张，涨跌幅提醒一般设在 1%-10% 之间~",
            "阈值超出合理范围了，建议设置在 1% 到 10% 之间~",
        ],
        "non_trading_day": [
            "这一天不是交易日，数据可能为空。需要我映射到最近的交易日吗？",
            "周末或节假日没有交易数据，要看最近交易日的数据吗？",
        ],

        # === 通用兜底 ===
        "generic": [
            "我没太理解你的意思，可以换个说法再说一遍吗？",
            "这个问题我还不太会回答，你可以问我：\n• 持仓查询\n• 个股行情\n• 复盘分析\n• 大盘走势",
            '我还在学习中，可以试着说"查询 600519 行情"或"帮我复盘茅台"~',
        ],
    }

    def __init__(self, templates: Optional[Dict[str, List[str]]] = None) -> None:
        self._templates = templates or self.DEFAULT_TEMPLATES.copy()

    def clarify(
        self,
        intent: str,
        confidence: float,
        params: Dict[str, Any],
        validation: ValidatorResult,
        tier: int = 1,
    ) -> ClarifierResult:
        """根据意图、参数和校验结果生成澄清话术。同步、不抛异常。"""
        try:
            return self._do_clarify(intent, confidence, params, validation, tier)
        except Exception:
            # 任何内部错误都 fallback 到通用话术
            return ClarifierResult(
                needs_clarification=True,
                clarification_message=self._pick("generic"),
                missing_required=[],
            )

    def _do_clarify(
        self,
        intent: str,
        confidence: float,
        params: Dict[str, Any],
        validation: ValidatorResult,
        tier: int,
    ) -> ClarifierResult:
        missing: List[str] = []
        messages: List[str] = []

        # 1. 意图置信度过低 -> 歧义澄清
        if confidence < 0.5 or tier >= 3:
            messages.append(self._pick("ambiguous_intent"))
            return ClarifierResult(
                needs_clarification=True,
                clarification_message="\n".join(messages),
                missing_required=["intent"],
            )

        # 2. 校验失败 -> 解释话术
        for err in validation.errors:
            if err.severity == "error":
                msg = self._map_error_to_message(err)
                if msg:
                    messages.append(msg)
                missing.append(err.field)

        # 3. 必填参数缺失 -> 反问话术
        required_missing = self._check_missing_params(intent, params)
        for field in required_missing:
            msg = self._map_missing_to_message(field)
            if msg:
                messages.append(msg)
            missing.append(field)

        # 4. 多股票歧义
        codes = params.get("stock_codes", [])
        if len(codes) > 1 and intent in ("stock_review", "intraday"):
            messages.append(self._pick("ambiguous_stock"))
            missing.append("focused_stock")

        if messages:
            return ClarifierResult(
                needs_clarification=True,
                clarification_message="\n".join(messages),
                missing_required=list(dict.fromkeys(missing)),  # 去重保持顺序
                suggested_intent=intent if confidence >= 0.5 else None,
            )

        # 无需澄清
        return ClarifierResult(needs_clarification=False)

    def _check_missing_params(self, intent: str, params: Dict[str, Any]) -> List[str]:
        """检查必填参数是否缺失"""
        missing: List[str] = []

        required_map = {
            "stock_review": ["stock_codes"],
            "intraday": ["stock_codes"],
            "simulation": ["stock_codes"],
            "quote_query": [],  # 行情查询可接受无代码（默认展示热门）
            "alert_set": ["stock_codes", "threshold_percent"],
        }

        required = required_map.get(intent, [])
        for field in required:
            val = params.get(field)
            if val is None or val == [] or val == "":
                missing.append(field)

        return missing

    def _map_missing_to_message(self, field: str) -> Optional[str]:
        """将缺失字段映射为反问话术"""
        mapping = {
            "stock_codes": "missing_stock_code",
            "target_date": "missing_date",
            "threshold_percent": "missing_threshold",
            "target_price": "missing_target_price",
            "industry_name": "missing_industry_name",
            "company": "missing_company",
        }
        key = mapping.get(field)
        if key:
            return self._pick(key)
        return None

    def _map_error_to_message(self, error: ValidationError) -> Optional[str]:
        """将校验错误映射为解释话术"""
        field = error.field.lower()
        msg = error.message.lower()

        if "stock_code" in field or "股票代码" in msg:
            return self._pick("invalid_stock_code")
        if "target_date" in field or "日期" in msg:
            if "未来" in msg or "future" in msg:
                return self._pick("invalid_date_future")
            if "久远" in msg or "past" in msg:
                return self._pick("invalid_date_past")
            if "交易日" in msg or "trading" in msg:
                return self._pick("non_trading_day")
            return self._pick("missing_date")
        if "threshold" in field or "阈值" in msg:
            return self._pick("invalid_threshold")

        return None

    def _pick(self, key: str) -> str:
        """从模板中随机选取一条话术"""
        templates = self._templates.get(key, self._templates["generic"])
        return random.choice(templates)

    def update_templates(self, templates: Dict[str, List[str]]) -> None:
        """热更新话术模板"""
        self._templates = templates.copy()
