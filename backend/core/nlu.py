"""
NLU 意图识别 — 三层降级架构

L1: 规则引擎（关键词 + 正则）— 覆盖 90%+ 高频意图
L2: 本地 LLM（Ollama Qwen2.5:7b）— L1 未命中时
L3: 直接澄清 — L2 置信度 < 0.6
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
import json
import json
from typing import Any, Dict, List, Optional

try:
    from core.ollama_client import ollama
except ImportError:
    ollama = None


class Intent(str, Enum):
    QUOTE_QUERY = "quote_query"           # 查询行情
    PORTFOLIO_QUERY = "portfolio_query"   # 查询持仓
    STOCK_REVIEW = "stock_review"         # 个股复盘
    MARKET_REVIEW = "market_review"       # 大盘复盘
    SIMULATION = "simulation"             # 预演分析
    INTRADAY = "intraday"                 # 盘中分析
    TREND_RECOMMENDATION = "trend_recommendation"  # 趋势推荐
    ALERT_SET = "alert_set"               # 设置提醒
    ALERT_LIST = "alert_list"             # 查看提醒
    STOCK_SCREENING = "stock_screening"   # 选股
    INDUSTRY_ANALYSIS = "industry_analysis"  # 行业分析
    ANNOUNCEMENT_ANALYSIS = "announcement_analysis"  # 公告解读
    EARNINGS_REVIEW = "earnings_review"   # 财报周期复盘
    MARKET_OVERVIEW = "market_overview"  # 大盘整体研判（Skill6 入口）
    DEEP_RESEARCH = "deep_research"       # 深度研究（Skill3+Skill7 组合）
    SKIN_SWITCH = "skin_switch"           # 切换皮肤
    IDENTITY = "identity"                 # 身份/能力介绍（你是谁/你能干嘛）
    CHITCHAT = "chitchat"                 # 寒暄（你好/谢谢/再见）
    EXPLANATION = "explanation"           # 追问解释（为什么/凭什么/理由）
    HELP = "help"                         # 帮助
    UNKNOWN = "unknown"                   # 未知


@dataclass
class IntentResult:
    intent: Intent
    confidence: float  # 0.0 ~ 1.0
    params: Dict[str, Any]
    tier: int  # 1, 2, 3


class RuleEngine:
    """L1 规则引擎 — 关键词 + 正则匹配"""

    RULES: List[tuple] = [
        # (intent, keywords, regex_patterns)
        # ---- 身份/寒暄/追问：最高优先级，防止被业务意图劫持（"你是谁"误答持仓的根因修复） ----
        (Intent.IDENTITY,
         ["你是谁", "你叫什么", "你有什么能力", "你能干什么", "你能干嘛", "你能做什么",
          "你会什么", "你想要做到的能力", "自我介绍", "介绍你自己", "介绍下自己",
          "你是什么", "你是啥", "你能帮我做什么", "你有什么用", "你的功能"],
         [r"你是谁", r"你叫什么", r"介绍.{0,2}(一下)?自己", r"你.{0,4}(能力|功能|本事)",
          r"你(是|能|会)(干|做)什么"]),

        (Intent.CHITCHAT,
         ["你好", "您好", "嗨", "哈喽", "早上好", "中午好", "晚上好",
          "在吗", "谢谢", "多谢", "再见", "拜拜", "辛苦了"],
         [r"^(你好|您好|嗨|哈喽|hi|hello|早上好|中午好|晚上好|在吗|谢谢|多谢|再见|拜拜)[!！~。？?\s]*$"]),

        (Intent.EXPLANATION,
         ["为什么", "凭什么", "理由", "怎么讲", "怎么解释", "什么意思", "怎么理解",
          "解释一下", "说明一下", "为啥", "何意", "什么道理", "怎么说的"],
         [r"(为什么|凭什么|为啥|什么意思|怎么理解|解释一下|说明一下|什么道理)"]),

        (Intent.QUOTE_QUERY,
         ["多少钱", "行情", "价格", "现价", "走势", "股价", "报价"],
         [r"\d{6}", r"[沪深].*?指", r"\d{1,5}\.HK\b",                                   # 港股代码：00700.HK / 0700.HK
          r"\b[A-Z]{2,5}\b\s*(行情|股价|价格|多少钱)",          # 美股 ticker + 行情关键词：AAPL 行情
          r"^[A-Z]{2,5}$",                                     # 整条消息就是美股 ticker：AAPL
          r"(查询|查一下|查|看看|搜)\s*[A-Z]{2,5}\b"]),          # 查询类动词 + 美股 ticker：查询 AAPL

        (Intent.PORTFOLIO_QUERY,
         ["持仓", "我的股票", "盈亏", "赚了多少", "亏了多少", "持仓收益", "基金怎么样"],
         []),

        (Intent.STOCK_REVIEW,
         ["复盘", "分析", "研判", "拆解", "怎么样", "如何", "好不好", "行吗", "咋样", "稳吗"],
         [r"复盘.*?\d{6}", r"分析.*?\d{6}",
          r".*?(怎么样|如何|好不好|行吗|咋样|稳吗).*?(股票|股|标的|这只|它)",
          r"\d{6}.*?(怎么样|如何|好不好|咋样|稳吗)",
          r"(贵州茅台|五粮液|立讯精密|宁德时代|比亚迪|海康威视|埃斯顿|寒武纪|中科曙光|中际旭创|天孚通信|新易盛|东方财富|科大讯飞|工业富联|药明康德|美的集团|格力电器|招商银行|中国平安|三一重工|海天味业|紫金矿业|隆基绿能|平安银行|中信证券|伊利股份).*?(怎么样|如何|好不好|咋样|稳吗)"]),

        (Intent.MARKET_REVIEW,
         # 0.6.0 修复（用户实测反馈5）：「上证指数」「A股市场」等指数词此前未命中任何规则，
         # 落入 default 后被 ≤4 字碎片继承闸门劫持为上一轮的 stock_review（问上证指数答茅台）
         ["大盘", "市场", "沪指", "深成指", "创业板", " today",
          "上证指数", "上证", "深证成指", "创业板指", "科创50", "沪深300",
          "北证50", "中证500", "A股", "A股指数", "A股市场", "股市", "指数"],
         [r"大盘.*?怎么样", r"今天.*?市场",
          r"^(上证指数|上证|深证成指|创业板指|科创50|沪深300|北证50|中证500|万得全A)[!！。？?\s]*$",
          r"^(A股|A股指数|A股市场|股市|大盘|指数)(怎么样|如何|走势|行情|分析|复盘)?[!！。？?\s]*$",
          # 0.6.0：指数名+疑问词组合（「上证怎么样」「沪深300怎么样」）此前无正则命中，
          # 仅关键词 0.3 与 STOCK_REVIEW 的「怎么样」0.3 平手且规则在后被先到先胜劫持
          r"(上证指数|上证|深证成指|创业板指|科创50|沪深300|北证50|中证500|A股指数|A股市场|股市|大盘|沪指|深成指).*(怎么样|如何|走势|行情|分析|复盘)"]),

        (Intent.SIMULATION,
         ["如果", "假设", "预演", "跌到", "涨到", "赚多少", "亏多少"],
         [r"如果.*?跌到", r"假设.*?涨"]),

        (Intent.INTRADAY,
         ["盘中", "异动", "拉升", "跳水"],
         [r".*?拉升", r".*?跳水"]),

        (Intent.ALERT_SET,
         ["提醒", "预警", "通知", "设置提醒"],
         [r".*?涨跌.*?提醒", r".*?设.*?提醒"]),

        (Intent.ALERT_LIST,
         ["查看提醒", "提醒设置", "我的提醒"],
         []),

        (Intent.TREND_RECOMMENDATION,
         ["推荐", "趋势", "买什么", "看好", "机会", "板块", "热点"],
         [r"推荐", r"推荐.*?股票", r"买.*?什么", r"看好.*?板块"]),

        (Intent.STOCK_SCREENING,
         ["选股", "筛股票", "找龙头", "推荐股票", "有哪些优质股", "股票池", "筛选"],
         [r"选股", r"筛.*?股票", r"找.*?龙头", r"推荐.*?只.*?股"]),

        (Intent.INDUSTRY_ANALYSIS,
         ["行业研究", "行业分析", "产业链", "行业深度", "行业趋势", "行业报告"],
         [r"(.+?)行业.*(分析|研究|趋势)", r"产业链.*分析"]),

        (Intent.ANNOUNCEMENT_ANALYSIS,
         ["公告", "解读公告", "公司公告", "公告解读", "什么公告"],
         [r"(.+?)公告.*(解读|分析|怎么看)", r"解读.*?公告"]),

        (Intent.EARNINGS_REVIEW,
         ["财报", "业绩", "年报", "季报", "业绩点评", "中报"],
         [r"(.+?)(Q[1-4]|年报|季报|中报).*业绩", r"财报.*解读", r"业绩.*点评"]),

        (Intent.SKIN_SWITCH,
         ["皮肤", "换肤", "切换皮肤", "主题"],
         []),

        (Intent.HELP,
         ["帮助", "怎么用", "能做什么", "功能"],
         []),
    ]

    @classmethod
    def parse(cls, text: str) -> Optional[IntentResult]:

        import sys as _sys2

        lowered = text.lower()
        best_result: Optional[IntentResult] = None
        best_score = 0.0

        for intent, keywords, patterns in cls.RULES:
            score = 0.0
            params: Dict[str, Any] = {}

            # 关键词匹配
            for kw in keywords:
                if kw in lowered:
                    score += 0.3

            # 正则匹配
            for pat in patterns:
                if re.search(pat, text):
                    score += 0.4

            # 提取股票代码（A股6位数字 / 港股xxxx.HK / 美股字母ticker）
            codes = re.findall(r"\d{6}", text)
            codes += [c.upper() for c in re.findall(r"\d{1,5}\.hk\b", text, re.IGNORECASE)]
            # 美股 ticker：用 lookaround 代替 \b（\b 对中文字符无效，「查询AAPL」无空格也能命中）
            codes += [t for t in re.findall(r"(?<![A-Za-z])[A-Z]{2,5}(?![A-Za-z])", text) if t.upper() != "HK"]
            if codes:
                params["stock_codes"] = list(dict.fromkeys(codes))  # 去重保序
                score += 0.1

            # 提取百分比
            pct_match = re.search(r"(\d+(?:\.\d+)?)\s*%", text)
            if pct_match:
                params["threshold_percent"] = float(pct_match.group(1))
                score += 0.1

            if score > best_score:
                best_score = score
                best_result = IntentResult(
                    intent=intent,
                    confidence=min(score, 1.0),
                    params=params,
                    tier=1,
                )

        # ===== 二次校验：防止泛词误命中 =====
        # quote_query 必须有行情实质证据：要么含"多少钱/行情/价格/现价/走势"之一，
        # 要么匹配到股票代码/名称正则。仅有"怎么样"这种泛词不算。
        _QUOTE_STRONG_KWS = {"多少钱", "行情", "价格", "现价", "走势", "股价", "报价"}
        if best_result and best_result.intent == Intent.QUOTE_QUERY:
            has_strong_kw = any(kw in lowered for kw in _QUOTE_STRONG_KWS)
            has_entity = bool(codes)  # 已在上文提取
            if not has_strong_kw and not has_entity:

                best_result = None  # 丢弃无实质证据的 quote_query

        # intraday 必须有盘中相关词，"为什么/怎么回事" 单独不足以触发
        if best_result and best_result.intent == Intent.INTRADAY:
            _INTRADAY_STRONG = {"盘中", "异动", "拉升", "跳水"}

            has_strong = any(kw in lowered for kw in _INTRADAY_STRONG)
            if not has_strong:
                best_result = None

        # portfolio_query 必须有持仓/盈亏实质词
        _PORTFOLIO_STRONG = {"持仓", "我的股票", "盈亏", "赚了多少", "亏了多少", "持仓收益", "基金"}
        if best_result and best_result.intent == Intent.PORTFOLIO_QUERY:
            has_strong = any(kw in lowered for kw in _PORTFOLIO_STRONG)
            if not has_strong:
                best_result = None

        # alert_set 必须有动作动词，否则查询场景被误判
        _ALERT_SET_VERBS = {"设", "设置", "加", "添加", "创建", "开", "开启", "打开", "增加"}
        if best_result and best_result.intent == Intent.ALERT_SET:
            has_verb = any(kw in lowered for kw in _ALERT_SET_VERBS)
            if not has_verb:
                # 丢弃 alert_set，重新在 RULES 中找次高分（避开 ALERT_SET）
                _alt_best = None
                _alt_score = 0.0
                for _alt_intent, _alt_kws, _alt_pats in cls.RULES:
                    if _alt_intent == Intent.ALERT_SET:
                        continue
                    _s = 0.0
                    for _kw in _alt_kws:
                        if _kw in lowered:
                            _s += 0.3
                    for _pat in _alt_pats:
                        if re.search(_pat, text):
                            _s += 0.4

                    if _s > _alt_score:
                        _alt_score = _s
                        _alt_best = _alt_intent
                if _alt_best and _alt_score >= 0.3:
                    codes = re.findall(r'\d{6}', text)
                    best_result = IntentResult(_alt_best, _alt_score, {'stock_codes': codes}, tier=1)
                else:
                    best_result = None

        # 只返回置信度 >= 0.3 的结果，否则视为未命中
        if best_result and best_result.confidence >= 0.3:
            return best_result
        return None


_INTENT_SYSTEM_PROMPT = """你是股票分析助手"股大师"的意图分类器。根据用户输入的自然语言消息，判断它属于哪个意图。

可选意图列表：
- quote_query: 查询个股行情/价格/走势/现价
- portfolio_query: 查询持仓/盈亏/我的股票
- stock_review: 个股复盘/分析/研判
- market_review: 大盘/市场/沪指/深成指/创业板整体表现
- simulation: 情景预演（如果涨到X/跌到X会怎么样）
- intraday: 盘中异动/拉升/跳水分析
- trend_recommendation: 趋势推荐/买什么/看好什么板块
- stock_screening: 选股/筛选/找龙头
- industry_analysis: 行业分析/产业链研究
- announcement_analysis: 公告解读/公司公告分析
- earnings_review: 财报/业绩/年报/季报分析
- alert_set: 设置价格提醒/预警
- alert_list: 查看已设提醒
- skin_switch: 切换宠物皮肤/主题
- identity: 问你是谁/你有什么能力/自我介绍
- chitchat: 打招呼/谢谢/再见等寒暄
- explanation: 对上一轮回答的追问（为什么/凭什么/理由是什么）
- help: 帮助/使用说明
- unknown: 以上都不是

规则：
1. 先提取消息中的股票代码（6位A股数字 / xxxx.HK港股 / 2-5位英文ticker）
2. 输出严格的JSON格式，不要额外文字
3. confidence 是 0.0-1.0 的置信度，有明确关键词就给 0.7+，模糊匹配 0.4-0.6
"""

_INTENT_USER_PROMPT = """请分类这条消息的意图：「{text}」

输出JSON格式（只输出JSON，不要markdown）：
{{"intent": "<intent_name>", "confidence": <0.0-1.0>, "stock_codes": ["code1", "code2"]}}
"""


class NLUManager:
    """NLU 三层降级管理器

    L1: 规则引擎（关键词 + 正则）— confidence >= 0.6 直接返回
    L2: Ollama 本地 LLM — L1 完全未命中（RuleEngine 返回 None）时兜底
    L3: 直接澄清 — L2 也失败或 confidence < 0.5
    """

    L1_HIGH_THRESHOLD = 0.3
    L1_LOW_THRESHOLD = 0.3
    L2_THRESHOLD = 0.5

    def __init__(self) -> None:
        self.rule_engine = RuleEngine()

    async def parse(self, text: str) -> IntentResult:
        result = self.rule_engine.parse(text)
        if result and result.confidence >= self.L1_HIGH_THRESHOLD:
            return result

        # RuleEngine 完全没命中 → 尝试 L2 Ollama 兜底
        llm_result = await self._llm_fallback(text)
        if llm_result is not None:
            return llm_result

        return IntentResult(intent=Intent.UNKNOWN, confidence=0.0, params={}, tier=3)

    async def _llm_fallback(self, text: str):
        """调用 Ollama 做意图分类。返回 None 表示不可用或无法解析。"""
        if ollama is None or not ollama.enabled:
            return None
        if not await ollama.is_available():
            return None
        try:
            raw = await ollama.generate(
                prompt=_INTENT_USER_PROMPT.format(text=text[:200]),
                system=_INTENT_SYSTEM_PROMPT,
                temperature=0.1,
            )
        except Exception:
            return None
        if not raw:
            return None

        data = self._parse_llm_json(raw)
        if data is None:
            return None

        intent_name = data.get("intent", "")
        confidence = float(data.get("confidence", 0.0))
        codes = data.get("stock_codes", [])

        try:
            intent = Intent(intent_name)
        except ValueError:
            return None

        if confidence < self.L2_THRESHOLD:
            return None

        params = {}
        if codes:
            params["stock_codes"] = codes

        return IntentResult(intent=intent, confidence=confidence, params=params, tier=2)

    @staticmethod
    def _parse_llm_json(raw):
        """从 Ollama 输出中提取 JSON"""
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass
        m = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', raw, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1))
            except json.JSONDecodeError:
                pass
        m = re.search(r'(\{.*?\})', raw, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1))
            except json.JSONDecodeError:
                pass
        return None

