"""
Schema 填空层 (Layer 2) — 规则引擎 + LLM 抽取器

职责：从用户输入中提取结构化意图和参数。
- RuleEngine: 同步执行，关键词/正则匹配，覆盖 80%+ 高频场景
- LLMExtractor: 异步执行，本地 Ollama 兜底，处理歧义和复杂输入
- ResultCache: 同步执行，缓存高频 LLM 解析结果，TTL 5 分钟

接口契约：
- RuleEngine.extract() 为同步方法
- LLMExtractor.extract() 为异步方法
- SchemaExtractor.extract() 异步，先规则后 LLM，含降级策略和缓存
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from core.llm_extractor import LLMConfig, LLMExtractor
from core.result_cache import ResultCache, result_cache

logger = logging.getLogger(__name__)

# === 配置加载 ===

_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "llm_config.json")


def _load_llm_config() -> LLMConfig:
    """从 llm_config.json 加载配置，文件不存在或解析失败时使用默认值"""
    try:
        path = os.path.abspath(_CONFIG_PATH)
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return LLMConfig(
                base_url=data.get("base_url", "http://localhost:11434"),
                model_name=data.get("model_name", "qwen2.5:7b"),
                timeout_seconds=float(data.get("timeout_seconds", 15.0)),
                temperature=float(data.get("temperature", 0.3)),
                enable_zero_shot=data.get("enable_zero_shot", True),
                enable_few_shot=data.get("enable_few_shot", True),
                enable_cot=data.get("enable_cot", True),
                few_shot_min_length=int(data.get("few_shot_min_length", 15)),
                cot_min_length=int(data.get("cot_min_length", 35)),
                health_cache_ttl_seconds=float(data.get("health_cache_ttl_seconds", 30.0)),
            )
    except Exception as e:
        logger.debug("加载 llm_config.json 失败，使用默认配置: %s", e)
    return LLMConfig()


@dataclass(frozen=True)
class ExtractedParams:
    """提取的参数集合"""

    stock_codes: List[str] = field(default_factory=list)
    stock_names: List[str] = field(default_factory=list)
    target_date: Optional[str] = None
    threshold_percent: Optional[float] = None
    target_price: Optional[float] = None
    direction: Optional[str] = None  # "up" | "down" | "both"
    raw_slots: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SchemaExtractorResult:
    """Schema 抽取结果"""

    intent: str
    confidence: float  # 0.0 ~ 1.0
    params: ExtractedParams
    tier: int  # 1=规则引擎, 2=LLM, 3=澄清/unknown
    raw_text: str = ""
    degraded_reason: Optional[str] = None


class RuleEngine:
    """L2-1 规则引擎 — 同步

    遍历全部规则后取最高置信度意图（修复 v2.3 中首个 >=0.3 抢占 bug）。
    支持反触发词做置信度减法。

    接口契约：
    - extract() 为同步方法，不抛异常
    - 未命中时返回 None（由上层进入 LLM 或澄清）
    """

    # 意图规则定义：(intent, keywords, regex_patterns, anti_keywords, weight_map)
    RULES: List[tuple] = [
        (
            "quote_query",
            ["多少钱", "怎么样", "行情", "价格", "现价", "走势", "股价"],
            [r"\d{6}", r"[沪深].*?指", r"茅台", r"比亚迪", r"宁德", r"立讯"],
            ["复盘", "分析"],
            {"keyword": 0.25, "regex": 0.35, "stock_code": 0.15, "percent": 0.05},
        ),
        (
            "portfolio_query",
            ["持仓", "我的股票", "盈亏", "赚了多少", "亏了多少", "持仓收益", "基金怎么样", "我买了什么"],
            [],
            ["大盘", "市场"],
            {"keyword": 0.35, "regex": 0.0, "stock_code": 0.05, "percent": 0.05},
        ),
        (
            "stock_review",
            ["复盘", "分析", "研判", "拆解", "诊断", "看看"],
            [r"复盘.*?\d{6}", r"分析.*?\d{6}", r"诊断.*?\d{6}"],
            ["大盘", "市场", "整体"],
            {"keyword": 0.25, "regex": 0.35, "stock_code": 0.15, "percent": 0.05},
        ),
        (
            "market_review",
            ["大盘", "市场", "沪指", "深成指", "创业板", "今天", "走势"],
            [r"大盘.*?怎么样", r"今天.*?市场", r"大盘.*?走势"],
            ["个股", "股票"],
            {"keyword": 0.30, "regex": 0.30, "stock_code": 0.0, "percent": 0.05},
        ),
        (
            "simulation",
            ["如果", "假设", "预演", "跌到", "涨到", "赚多少", "亏多少", "会怎样"],
            [r"如果.*?跌到", r"假设.*?涨", r"涨到.*?%", r"跌到.*?%"],
            [],
            {"keyword": 0.25, "regex": 0.30, "stock_code": 0.15, "percent": 0.10},
        ),
        (
            "intraday",
            ["盘中", "异动", "拉升", "跳水", "为什么", "怎么回事", "突然"],
            [r".*?拉升", r".*?跳水", r".*?异动"],
            ["复盘", "分析"],
            {"keyword": 0.25, "regex": 0.30, "stock_code": 0.15, "percent": 0.05},
        ),
        (
            "alert_set",
            ["提醒", "预警", "通知", "设置提醒", "涨跌提醒"],
            [r".*?涨跌.*?提醒", r".*?设.*?提醒", r".*?到.*?提醒"],
            [],
            {"keyword": 0.25, "regex": 0.25, "stock_code": 0.15, "percent": 0.15},
        ),
        (
            "alert_list",
            ["查看提醒", "提醒设置", "我的提醒", "有哪些提醒"],
            [],
            [],
            {"keyword": 0.40, "regex": 0.0, "stock_code": 0.0, "percent": 0.0},
        ),
        (
            "skin_switch",
            ["皮肤", "换肤", "切换皮肤", "主题", "换个样子"],
            [],
            [],
            {"keyword": 0.40, "regex": 0.0, "stock_code": 0.0, "percent": 0.0},
        ),
        (
            "help",
            ["帮助", "怎么用", "能做什么", "功能", "你会什么"],
            [],
            [],
            {"keyword": 0.40, "regex": 0.0, "stock_code": 0.0, "percent": 0.0},
        ),
        (
            "stock_screening",
            ["选股", "筛股票", "找龙头", "推荐股票", "有哪些优质股", "股票池", "筛选"],
            [r"选股", r"筛.*?股票", r"找.*?龙头", r"推荐.*?只.*?股"],
            [],
            {"keyword": 0.30, "regex": 0.30, "stock_code": 0.0, "percent": 0.0},
        ),
        (
            "industry_analysis",
            ["行业研究", "行业分析", "产业链", "行业深度", "行业趋势", "行业报告"],
            [r"(.+?)行业.*(分析|研究|趋势)", r"产业链.*分析"],
            [],
            {"keyword": 0.30, "regex": 0.30, "stock_code": 0.0, "percent": 0.0},
        ),
        (
            "announcement_analysis",
            ["公告", "解读公告", "公司公告", "公告解读"],
            [r"(.+?)公告.*(解读|分析|怎么看)", r"解读.*?公告"],
            [],
            {"keyword": 0.30, "regex": 0.30, "stock_code": 0.10, "percent": 0.0},
        ),
        (
            "earnings_review",
            ["财报", "业绩", "年报", "季报", "业绩点评", "中报"],
            [r"(.+?)(Q[1-4]|年报|季报|中报).*业绩", r"财报.*解读", r"业绩.*点评"],
            [],
            {"keyword": 0.30, "regex": 0.30, "stock_code": 0.10, "percent": 0.0},
        ),
    ]

    def extract(self, text: str) -> Optional[SchemaExtractorResult]:
        """规则引擎抽取。同步、不抛异常。"""
        try:
            return self._do_extract(text)
        except Exception:
            return None

    def _do_extract(self, text: str) -> Optional[SchemaExtractorResult]:
        lowered = text.lower()
        best_result: Optional[SchemaExtractorResult] = None
        best_score = 0.0

        for intent, keywords, patterns, anti_keywords, weights in self.RULES:
            score = 0.0
            params = ExtractedParams()

            # 关键词匹配
            kw_hits = sum(1 for kw in keywords if kw in lowered)
            score += kw_hits * weights.get("keyword", 0.3)

            # 正则匹配
            regex_hits = sum(1 for pat in patterns if re.search(pat, text))
            score += regex_hits * weights.get("regex", 0.4)

            # 反触发词减分
            anti_hits = sum(1 for ak in anti_keywords if ak in lowered)
            score -= anti_hits * 0.2

            # 提取股票代码
            codes = re.findall(r"\b\d{6}\b", text)
            if codes:
                params = ExtractedParams(stock_codes=codes)
                score += weights.get("stock_code", 0.1)

            # 提取百分比
            pct_match = re.search(r"(\d+(?:\.\d+)?)\s*%", text)
            if pct_match:
                params = ExtractedParams(
                    stock_codes=params.stock_codes,
                    threshold_percent=float(pct_match.group(1)),
                )
                score += weights.get("percent", 0.1)

            # 提取日期描述（原始文本，后续由 DateParser 解析）
            date_patterns = [
                r"(今天|昨天|前天|大前天)",
                r"(\d{4}[-/]\d{1,2}[-/]\d{1,2})",
                r"(\d{1,2}月\d{1,2}日)",
                r"(T[+-]?\d+)",
            ]
            for pat in date_patterns:
                m = re.search(pat, text)
                if m:
                    params = ExtractedParams(
                        stock_codes=params.stock_codes,
                        threshold_percent=params.threshold_percent,
                        target_date=m.group(1),
                    )
                    break

            # 提取价格
            price_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:元|块)", text)
            if price_match:
                params = ExtractedParams(
                    stock_codes=params.stock_codes,
                    threshold_percent=params.threshold_percent,
                    target_date=params.target_date,
                    target_price=float(price_match.group(1)),
                )

            if score > best_score:
                best_score = score
                best_result = SchemaExtractorResult(
                    intent=intent,
                    confidence=min(best_score, 1.0),
                    params=params,
                    tier=1,
                    raw_text=text,
                )

        # 只返回置信度 >= 0.3 的结果
        if best_result and best_result.confidence >= 0.3:
            return best_result
        return None


class SchemaExtractor:
    """L2 Schema 填空层主入口

    执行顺序：RuleEngine (sync) -> ResultCache (sync) -> LLMExtractor (async，降级可用)。
    接口契约：
    - extract() 为异步方法
    - 所有降级路径均不抛异常
    """

    LLM_TRIGGER_THRESHOLD: float = 0.5  # 规则引擎置信度低于此值时触发 LLM

    def __init__(self, model_name: str = "qwen2.5:7b") -> None:
        self.rule_engine = RuleEngine()
        self.llm_extractor = LLMExtractor(config=_load_llm_config())
        self.result_cache = result_cache

    async def extract(self, text: str) -> SchemaExtractorResult:
        """Schema 抽取主入口。异步、不抛异常。"""
        try:
            return await self._do_extract(text)
        except Exception as e:
            logger.debug("SchemaExtractor.extract 异常: %s", e, exc_info=True)
            # 最终兜底：返回 unknown，不抛异常给外层 RPC
            return SchemaExtractorResult(
                intent="unknown",
                confidence=0.0,
                params=ExtractedParams(),
                tier=3,
                raw_text=text,
                degraded_reason=f"schema_extractor_exception: {e}",
            )

    async def _do_extract(self, text: str) -> SchemaExtractorResult:
        # L2-1: 规则引擎（同步）
        rule_result = self.rule_engine.extract(text)
        if rule_result and rule_result.confidence >= self.LLM_TRIGGER_THRESHOLD:
            return rule_result

        # L2-1.5: 缓存检查（同步）— LLM 结果缓存
        cached = self.result_cache.get(text)
        if cached is not None:
            logger.debug("ResultCache 命中: %r", text[:30])
            return SchemaExtractorResult(
                intent=cached.get("intent", "unknown"),
                confidence=cached.get("confidence", 0.0),
                params=ExtractedParams(
                    stock_codes=cached.get("params", {}).get("stock_codes", []),
                    stock_names=cached.get("params", {}).get("stock_names", []),
                    target_date=cached.get("params", {}).get("target_date"),
                    threshold_percent=cached.get("params", {}).get("threshold_percent"),
                    target_price=cached.get("params", {}).get("target_price"),
                    direction=cached.get("params", {}).get("direction"),
                    raw_slots=cached.get("params", {}),
                ),
                tier=2,
                raw_text=text,
            )

        # L2-2: LLM 兜底（异步，降级安全）
        # 将规则引擎最佳结果传给 LLMExtractor 做降级 fallback
        rule_best = None
        if rule_result is not None:
            rule_best = {
                "intent": rule_result.intent,
                "confidence": rule_result.confidence,
                "params": {
                    "stock_codes": rule_result.params.stock_codes,
                    "stock_names": rule_result.params.stock_names,
                    "target_date": rule_result.params.target_date,
                    "threshold_percent": rule_result.params.threshold_percent,
                    "target_price": rule_result.params.target_price,
                    "direction": rule_result.params.direction,
                },
            }

        llm_result = await self.llm_extractor.extract(text, rule_best_result=rule_best)

        # 构造 SchemaExtractorResult
        llm_params = llm_result.get("params", {})
        result = SchemaExtractorResult(
            intent=llm_result.get("intent", "unknown"),
            confidence=llm_result.get("confidence", 0.0),
            params=ExtractedParams(
                stock_codes=llm_params.get("stock_codes", []),
                stock_names=llm_params.get("stock_names", []),
                target_date=llm_params.get("target_date"),
                threshold_percent=llm_params.get("threshold_percent"),
                target_price=llm_params.get("target_price"),
                direction=llm_params.get("direction"),
                raw_slots=llm_params,
            ),
            tier=llm_result.get("tier", 2),
            raw_text=text,
            degraded_reason=llm_result.get("degraded_reason"),
        )

        # LLM 置信度 >= 0.5 时写入缓存
        if result.confidence >= 0.5 and result.tier == 2:
            self.result_cache.set(text, {
                "intent": result.intent,
                "confidence": result.confidence,
                "params": llm_params,
            })

        # 未命中：如果规则引擎有低置信结果，返回它（比 unknown 好）
        if result.confidence < 0.5 and rule_result is not None:
            return rule_result

        return result
