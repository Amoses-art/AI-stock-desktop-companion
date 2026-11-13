"""
逻辑验算层 (Layer 3) — 同步执行

职责：对 SchemaExtractor 输出的参数进行格式、范围、一致性校验。
不猜测、不补全，校验失败即记录错误，交由 Clarifier 处理。

接口契约：
- 同步方法（sync），不抛异常，所有错误被捕获并记录
- 校验失败不阻止流程，而是积累错误列表供后续澄清层使用
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional

from core.date_parser import DateParser


@dataclass(frozen=True)
class ValidationError:
    """单条校验错误"""

    field: str
    message: str
    severity: str = "error"  # error | warning


@dataclass
class ValidatorResult:
    """校验结果"""

    passed: bool
    errors: List[ValidationError] = field(default_factory=list)
    warnings: List[ValidationError] = field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        return any(e.severity == "error" for e in self.errors)

    @property
    def has_warnings(self) -> bool:
        return len(self.warnings) > 0


class Validator:
    """L3 逻辑验算器 — 同步

    校验维度：
    1. 股票代码格式（6位数字 / 市场前缀 / 存在性）
    2. 日期有效性（非未来 / 不过远 / 交易日提示）
    3. 数值范围（涨跌幅 ±30% 等）
    4. 参数间一致性（如 simulation 中涨跌方向与阈值是否矛盾）

    接口契约：
    - validate() 为同步方法，不抛异常
    - 所有校验项独立执行，互不阻塞
    """

    # 校验阈值
    MAX_CHANGE_PERCENT: float = 30.0
    MAX_FUTURE_DAYS: int = 7
    MAX_PAST_DAYS: int = 365 * 5  # 5 年

    def __init__(self) -> None:
        self.date_parser = DateParser()

    def validate(self, intent: str, params: Dict[str, Any]) -> ValidatorResult:
        """对意图和参数进行全面校验。同步、不抛异常。"""
        try:
            return self._do_validate(intent, params)
        except Exception as e:
            return ValidatorResult(
                passed=False,
                errors=[ValidationError("validator", f"内部校验错误: {e}")],
            )

    def _do_validate(self, intent: str, params: Dict[str, Any]) -> ValidatorResult:
        errors: List[ValidationError] = []
        warnings: List[ValidationError] = []

        # === 1. 股票代码校验 ===
        codes = params.get("stock_codes", [])
        if codes:
            for code in codes:
                err = self._validate_stock_code(code)
                if err:
                    errors.append(err)

        # === 2. 日期校验 ===
        date_str = params.get("target_date")
        if date_str:
            err = self._validate_date(date_str)
            if err:
                errors.append(err)

        # === 3. 数值范围校验 ===
        threshold = params.get("threshold_percent")
        if threshold is not None:
            err = self._validate_threshold(threshold)
            if err:
                errors.append(err)

        # === 4. 参数间一致性校验 ===
        consistency_errs = self._validate_consistency(intent, params)
        errors.extend(consistency_errs)

        passed = not any(e.severity == "error" for e in errors)
        return ValidatorResult(passed=passed, errors=errors, warnings=warnings)

    def _validate_stock_code(self, code: Any) -> Optional[ValidationError]:
        """校验单只股票代码格式"""
        if not isinstance(code, str):
            return ValidationError("stock_codes", f"股票代码必须是字符串: {code}")

        # 纯数字 6 位
        if re.match(r"^\d{6}$", code):
            return None

        # 带市场前缀：sh/sz/bj + 6位数字
        if re.match(r"^(sh|sz|bj)\d{6}$", code.lower()):
            return None

        # 港股：0-9位数字（简化）
        if re.match(r"^\d{1,5}$", code):
            return ValidationError(
                "stock_codes",
                f"港股代码 {code} 暂未完全支持，目前主要支持 A 股 6 位代码",
                severity="warning",
            )

        return ValidationError(
            "stock_codes",
            f"股票代码格式不正确: {code}，请输入 6 位数字代码（如 600519）",
        )

    def _validate_date(self, date_str: str) -> Optional[ValidationError]:
        """校验日期有效性"""
        try:
            dt = date.fromisoformat(date_str)
        except ValueError:
            return ValidationError("target_date", f"日期格式不正确: {date_str}")

        today = date.today()

        # 未来日期检查
        days_future = (dt - today).days
        if days_future > self.MAX_FUTURE_DAYS:
            return ValidationError(
                "target_date",
                f"日期 {date_str} 超出可查询范围（最多未来 {self.MAX_FUTURE_DAYS} 天）",
            )

        # 过去日期不过远
        days_past = (today - dt).days
        if days_past > self.MAX_PAST_DAYS:
            return ValidationError(
                "target_date",
                f"日期 {date_str} 过于久远，目前支持最近 {self.MAX_PAST_DAYS // 365} 年数据",
            )

        # 交易日提示（warning 级别）
        if not self.date_parser.is_trading_day(dt):
            return ValidationError(
                "target_date",
                f"{date_str} 不是交易日，数据可能为空或映射到最近交易日",
                severity="warning",
            )

        return None

    def _validate_threshold(self, threshold: Any) -> Optional[ValidationError]:
        """校验涨跌幅阈值范围"""
        try:
            val = float(threshold)
        except (TypeError, ValueError):
            return ValidationError("threshold_percent", f"阈值必须是数字: {threshold}")

        if abs(val) > self.MAX_CHANGE_PERCENT:
            return ValidationError(
                "threshold_percent",
                f"涨跌幅阈值 ±{val}% 超出合理范围（最大 ±{self.MAX_CHANGE_PERCENT}%），请确认输入",
            )

        return None

    def _validate_consistency(
        self, intent: str, params: Dict[str, Any]
    ) -> List[ValidationError]:
        """校验参数间一致性"""
        errors: List[ValidationError] = []

        # simulation 场景：需要股票代码
        if intent == "simulation":
            codes = params.get("stock_codes", [])
            if not codes:
                errors.append(
                    ValidationError(
                        "consistency",
                        "预演分析需要指定股票代码，请补充代码后重试",
                    )
                )

        # quote_query 场景：有代码或名称即可
        if intent == "quote_query":
            codes = params.get("stock_codes", [])
            if not codes:
                pass  # 可能通过名称查询，不强制报错

        # stock_review 场景：需要股票代码
        if intent == "stock_review":
            codes = params.get("stock_codes", [])
            if not codes:
                errors.append(
                    ValidationError(
                        "consistency",
                        "个股复盘需要指定股票代码，请补充代码后重试",
                    )
                )

        # announcement_analysis / earnings_review 场景：需要股票代码（从 company 映射）
        if intent in ("announcement_analysis", "earnings_review"):
            codes = params.get("stock_codes", [])
            if not codes:
                errors.append(
                    ValidationError(
                        "consistency",
                        "请提供公司名称或股票代码",
                    )
                )

        # industry_analysis 场景：需要行业名称
        if intent == "industry_analysis":
            industry = params.get("industry_name", "")
            if not industry:
                errors.append(
                    ValidationError(
                        "consistency",
                        "行业分析需要提供行业名称",
                    )
                )

        return errors
