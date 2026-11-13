"""输入解析 v2 — 四层漏斗（从 main.py 拆出，M1-R1；M1-R3 调整定位）

执行流程：HardFilter → SchemaExtractor（规则→LLM兜底）→ DateParser → Validator → Clarifier

定位（M1-R3 裁定）：
- 主路由为 core/nlu.py 的 nlu_manager（12 意图全覆盖），本模块**未接入主路由**，
  handle_chat 不再双跑对比（规则层仅覆盖 2 意图，对比无增量信息）。
- 保留价值：SchemaExtractor 的 LLM 兜底层将在 M3 接入本地 Ollama，
  作为低置信度意图的兜底解析路径；届时按新架构重新评估接入方式。
- log_intent_comparison 已无调用方，保留实现供 M3 恢复对比评估用。

接口契约：异步方法；所有降级路径均不抛异常，始终返回结构化 dict。
"""
from __future__ import annotations

import sys
from typing import Any

from core.hard_filter import HardFilter
from core.schema_extractor import SchemaExtractor, ExtractedParams
from core.validator import Validator
from core.clarifier import Clarifier
from core.date_parser import DateParser

# === 输入解析 v2 组件实例 ===
_hard_filter = HardFilter()
_schema_extractor = SchemaExtractor()
_validator = Validator()
_clarifier = Clarifier()
_date_parser = DateParser()

# === 新旧逻辑对比日志收集（迁移期） ===
_intent_comparison_logs: list[dict] = []
_MAX_COMPARISON_LOGS = 1000


async def parse_intent_v2(message: str) -> dict[str, Any]:
    """四层漏斗输入解析 v2 — 独立封装，便于与旧逻辑并行对比。"""
    raw_text = message.strip()

    # Layer 1: HardFilter
    filter_result = _hard_filter.filter(raw_text)
    if not filter_result.passed:
        return {
            "intent": "blocked",
            "confidence": 0.0,
            "params": {},
            "tier": 0,
            "reply": filter_result.response_message or "输入未通过安全检查",
            "needs_clarification": True,
            "block_reason": filter_result.block_reason,
        }

    # Layer 2: SchemaExtractor
    extract_result = await _schema_extractor.extract(raw_text)
    intent = extract_result.intent
    confidence = extract_result.confidence
    params = extract_result.params

    # Layer 2.5: DateParser（解析日期参数）
    if params.target_date:
        parsed = _date_parser.parse(params.target_date)
        if parsed:
            params = ExtractedParams(
                stock_codes=params.stock_codes,
                stock_names=params.stock_names,
                target_date=parsed.iso_date,
                threshold_percent=params.threshold_percent,
                target_price=params.target_price,
                direction=params.direction,
                raw_slots={**params.raw_slots, "parsed_date": parsed.iso_date},
            )

    # 从文本中补充提取日期（如果参数里没有但文本中有）
    if not params.target_date:
        parsed = _date_parser.extract_date_from_text(raw_text)
        if parsed:
            params = ExtractedParams(
                stock_codes=params.stock_codes,
                stock_names=params.stock_names,
                target_date=parsed.iso_date,
                threshold_percent=params.threshold_percent,
                target_price=params.target_price,
                direction=params.direction,
                raw_slots={**params.raw_slots, "parsed_date": parsed.iso_date},
            )

    # Layer 3: Validator
    validation = _validator.validate(intent, {
        "stock_codes": params.stock_codes,
        "target_date": params.target_date,
        "threshold_percent": params.threshold_percent,
        "target_price": params.target_price,
        "direction": params.direction,
    })

    # Layer 4: Clarifier
    clarification = _clarifier.clarify(
        intent=intent,
        confidence=confidence,
        params={
            "stock_codes": params.stock_codes,
            "target_date": params.target_date,
            "threshold_percent": params.threshold_percent,
            "target_price": params.target_price,
            "direction": params.direction,
        },
        validation=validation,
        tier=extract_result.tier,
    )

    if clarification.needs_clarification:
        return {
            "intent": intent if confidence >= 0.3 else "unknown",
            "confidence": confidence,
            "params": {
                "stock_codes": params.stock_codes,
                "target_date": params.target_date,
                "threshold_percent": params.threshold_percent,
                "target_price": params.target_price,
                "direction": params.direction,
            },
            "tier": extract_result.tier,
            "reply": clarification.clarification_message or "我没太理解，能再说清楚一点吗？",
            "needs_clarification": True,
            "missing_required": clarification.missing_required,
            "validation_errors": [e.message for e in validation.errors if e.severity == "error"],
            "validation_warnings": [e.message for e in validation.warnings],
        }

    # 无需澄清，返回结构化结果
    return {
        "intent": intent,
        "confidence": confidence,
        "params": {
            "stock_codes": params.stock_codes,
            "target_date": params.target_date,
            "threshold_percent": params.threshold_percent,
            "target_price": params.target_price,
            "direction": params.direction,
        },
        "tier": extract_result.tier,
        "reply": "",  # 由 handle_chat 根据 intent 生成业务回复
        "needs_clarification": False,
        "validation_errors": [],
        "validation_warnings": [e.message for e in validation.warnings],
    }


def log_intent_comparison(
    text: str,
    old_result: dict[str, Any],
    new_result: dict[str, Any],
) -> None:
    """记录新旧意图解析结果对比，用于迁移期准确率评估。"""
    match = old_result.get("intent") == new_result.get("intent")
    log_entry = {
        "text": text,
        "old_intent": old_result.get("intent"),
        "old_confidence": old_result.get("confidence"),
        "new_intent": new_result.get("intent"),
        "new_confidence": new_result.get("confidence"),
        "match": match,
        "needs_clarification": new_result.get("needs_clarification"),
    }
    _intent_comparison_logs.append(log_entry)
    if len(_intent_comparison_logs) > _MAX_COMPARISON_LOGS:
        _intent_comparison_logs.pop(0)

    # 每 100 条输出一次聚合日志（采样）
    if len(_intent_comparison_logs) % 100 == 0:
        total = len(_intent_comparison_logs)
        matches = sum(1 for log in _intent_comparison_logs if log["match"])
        rate = matches / total if total > 0 else 0
        print(f"[IntentV2] 对比日志累计 {total} 条，意图匹配率 {rate:.1%}", file=sys.stderr, flush=True)
