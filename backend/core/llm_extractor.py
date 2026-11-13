"""
LLM 抽取器 (Layer 2-2) — 异步，Ollama 本地大模型增强

职责：在 RuleEngine 未命中或置信度不足时，通过 Ollama HTTP API 进行意图识别和参数抽取。

架构约束：
- 唯一 async 模块（IO-bound HTTP 调用）
- 所有降级路径不抛异常，fallback 到 RuleEngine 最佳结果或 unknown
- 日志采样：DEBUG 级别内部记录，每 100 条输出 1 条 INFO 聚合日志
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

# === 日志采样计数器（模块级，线程安全由 asyncio 单线程保证）===
_llm_call_count: int = 0


@dataclass(frozen=True)
class LLMConfig:
    """LLM 运行时配置（可由外部 llm_config.json 热更新覆盖）"""

    base_url: str = "http://localhost:11434"
    model_name: str = "qwen2.5:7b"
    timeout_seconds: float = 15.0
    temperature: float = 0.3
    # 三层策略开关
    enable_zero_shot: bool = True
    enable_few_shot: bool = True
    enable_cot: bool = True
    # 策略选择阈值（按输入复杂度）
    few_shot_min_length: int = 15
    cot_min_length: int = 35
    # 可用性探测缓存 TTL
    health_cache_ttl_seconds: float = 30.0


class LLMExtractor:
    """Ollama LLM 抽取器 — 异步、降级安全

    接口契约：
    - extract() 为 async 方法
    - Ollama 不可用时降级，不抛异常
    - 输出统一为 dict，含 intent / confidence / params / tier
    """

    # 支持的意图列表（供 Prompt 使用）
    INTENT_LIST: List[str] = [
        "quote_query",
        "portfolio_query",
        "stock_review",
        "market_review",
        "simulation",
        "intraday",
        "alert_set",
        "alert_list",
        "skin_switch",
        "help",
        "unknown",
    ]

    # 股票名称到代码的静态映射（供 LLM 识别常见股票）
    STOCK_NAME_MAP: Dict[str, str] = {
        "茅台": "600519",
        "贵州茅台": "600519",
        "五粮液": "000858",
        "比亚迪": "002594",
        "宁德时代": "300750",
        "立讯精密": "002475",
        "招商银行": "600036",
        "中国平安": "601318",
        "腾讯": "00700",
        "阿里巴巴": "09988",
        "中芯国际": "688981",
        "美的集团": "000333",
        "中信证券": "600030",
        "东方财富": "300059",
    }

    def __init__(self, config: Optional[LLMConfig] = None) -> None:
        self.config = config or LLMConfig()
        self._client: Optional[httpx.AsyncClient] = None
        # 可用性探测缓存
        self._health_checked_at: float = 0.0
        self._health_status: bool = False

    def _get_client(self) -> httpx.AsyncClient:
        """懒加载 httpx 客户端"""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.config.base_url,
                timeout=httpx.Timeout(self.config.timeout_seconds),
            )
        return self._client

    async def _close(self) -> None:
        """关闭 HTTP 客户端（应用退出时调用）"""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    # ------------------------------------------------------------------
    # 公共接口
    # ------------------------------------------------------------------

    async def extract(self, text: str, rule_best_result: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """LLM 抽取主入口。异步、不抛异常。

        Args:
            text: 用户原始输入
            rule_best_result: 规则引擎的最佳结果（用于降级时 fallback）

        Returns:
            dict: {"intent": str, "confidence": float, "params": dict, "tier": int}
        """
        global _llm_call_count
        _llm_call_count += 1

        try:
            return await self._do_extract(text, rule_best_result)
        except Exception as e:
            logger.debug("LLMExtractor.extract 异常: %s", e, exc_info=True)
            return self._degrade(text, rule_best_result, reason=f"extract_exception: {e}")

    # ------------------------------------------------------------------
    # 内部实现
    # ------------------------------------------------------------------

    async def _do_extract(self, text: str, rule_best_result: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        # 1. 可用性探测（带缓存）
        available = await self._check_availability_cached()
        if not available:
            logger.debug("Ollama 不可用，降级到 RuleEngine")
            return self._degrade(text, rule_best_result, reason="ollama_unavailable")

        # 2. 选择 Prompt 策略
        strategy = self._select_strategy(text)
        prompt = self._build_prompt(text, strategy)

        # 3. 调用 Ollama
        raw_response = await self._call_ollama(prompt)
        if raw_response is None:
            return self._degrade(text, rule_best_result, reason="ollama_no_response")

        # 4. 解析并校验响应
        parsed = self._parse_response(raw_response, text)

        # 5. 后处理：补充股票代码映射
        parsed = self._postprocess_params(parsed, text)

        # 6. 日志采样
        self._sample_log(text, strategy, parsed)

        return parsed

    def _select_strategy(self, text: str) -> str:
        """按输入复杂度自动选择 Prompt 策略"""
        length = len(text.strip())
        if self.config.enable_cot and length >= self.config.cot_min_length:
            return "cot"
        if self.config.enable_few_shot and length >= self.config.few_shot_min_length:
            return "few_shot"
        if self.config.enable_zero_shot:
            return "zero_shot"
        # 全关则 fallback 到 zero_shot
        return "zero_shot"

    def _build_prompt(self, text: str, strategy: str) -> str:
        """根据策略构建 Prompt"""
        base_instruction = (
            "你是一个股票助手意图识别专家。请分析用户的输入，提取意图和参数。\n"
            "你必须严格按以下 JSON 格式输出，不要输出任何其他内容：\n"
            "{\n"
            '  "intent": "意图名称",\n'
            '  "confidence": 0.0~1.0 的浮点数,\n'
            '  "params": {\n'
            '    "stock_codes": ["6位数字代码"],\n'
            '    "stock_names": ["股票名称"],\n'
            '    "target_date": "日期或null",\n'
            '    "threshold_percent": 数字或null,\n'
            '    "target_price": 数字或null,\n'
            '    "direction": "up/down/both或null"\n'
            "  }\n"
            "}\n"
            f"支持的意图：{', '.join(self.INTENT_LIST)}\n"
            "规则：\n"
            "- stock_codes 必须是 6 位数字的 A 股代码\n"
            "- threshold_percent 可为负数（表示下跌）\n"
            "- 如果用户提到股票名称（如茅台、比亚迪），在 stock_names 中记录\n"
            "- confidence 根据你对理解用户意图的确定程度打分\n"
            "- 如果完全无法理解，intent 设为 unknown，confidence 设为 0.0\n"
        )

        if strategy == "zero_shot":
            return base_instruction + f"\n用户输入：{text}\n"

        if strategy == "few_shot":
            examples = (
                "\n示例 1：\n"
                "输入：帮我看看茅台今天怎么样\n"
                '输出：{"intent":"quote_query","confidence":0.9,"params":{"stock_codes":["600519"],"stock_names":["茅台"],"target_date":"今天","threshold_percent":null,"target_price":null,"direction":null}}\n'
                "\n示例 2：\n"
                "输入：如果立讯精密跌了5%，我的持仓会亏多少\n"
                '输出：{"intent":"simulation","confidence":0.85,"params":{"stock_codes":["002475"],"stock_names":["立讯精密"],"target_date":null,"threshold_percent":-5,"target_price":null,"direction":"down"}}\n'
                "\n示例 3：\n"
                "输入：大盘今天什么情况\n"
                '输出：{"intent":"market_review","confidence":0.9,"params":{"stock_codes":[],"stock_names":[],"target_date":"今天","threshold_percent":null,"target_price":null,"direction":null}}\n'
            )
            return base_instruction + examples + f"\n现在请分析：\n用户输入：{text}\n"

        if strategy == "cot":
            cot_instruction = (
                "\n请按以下步骤思考（Chain-of-Thought），但最终只输出 JSON：\n"
                "1. 识别用户的核心需求是什么\n"
                "2. 判断属于哪种意图\n"
                "3. 提取股票代码或名称\n"
                "4. 提取数值参数（如百分比、价格）\n"
                "5. 评估置信度\n"
                "6. 输出最终 JSON\n"
            )
            return base_instruction + cot_instruction + f"\n用户输入：{text}\n"

        # 默认 fallback
        return base_instruction + f"\n用户输入：{text}\n"

    async def _call_ollama(self, prompt: str) -> Optional[str]:
        """调用 Ollama /api/generate 端点"""
        client = self._get_client()
        payload = {
            "model": self.config.model_name,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": self.config.temperature,
                "num_predict": 2048,
            },
        }
        try:
            resp = await client.post("/api/generate", json=payload)
            resp.raise_for_status()
            data = resp.json()
            return data.get("response", "")
        except httpx.TimeoutException:
            logger.debug("Ollama 请求超时 (%.1fs)", self.config.timeout_seconds)
            return None
        except httpx.ConnectError:
            logger.debug("Ollama 连接失败: %s", self.config.base_url)
            return None
        except httpx.HTTPStatusError as e:
            logger.debug("Ollama HTTP 错误: %s", e)
            return None
        except Exception as e:
            logger.debug("Ollama 调用异常: %s", e)
            return None

    def _parse_response(self, raw: str, original_text: str) -> Dict[str, Any]:
        """解析 LLM 输出，容错处理。

        覆盖边缘：JSON 不合法、字段缺失、类型漂移、幻觉字段。
        失败时 fallback 到 unknown + confidence=0.0 + tier=3。
        """
        # 尝试从文本中提取 JSON 块（模型可能输出 markdown 代码块）
        json_str = self._extract_json_block(raw)
        if json_str is None:
            logger.debug("无法从响应中提取 JSON: %s", raw[:200])
            return self._fallback_unknown(original_text)

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            logger.debug("JSON 解析失败: %s", e)
            return self._fallback_unknown(original_text)

        # 校验并提取字段
        intent = self._safe_get_string(data, "intent", "unknown")
        if intent not in self.INTENT_LIST:
            intent = "unknown"

        confidence = self._safe_get_float(data, "confidence", 0.0)
        confidence = max(0.0, min(1.0, confidence))

        params_dict = data.get("params")
        if not isinstance(params_dict, dict):
            params_dict = {}

        # 提取各参数字段，带类型校验
        params: Dict[str, Any] = {
            "stock_codes": self._safe_get_string_list(params_dict, "stock_codes"),
            "stock_names": self._safe_get_string_list(params_dict, "stock_names"),
            "target_date": self._safe_get_string_or_none(params_dict, "target_date"),
            "threshold_percent": self._safe_get_float_or_none(params_dict, "threshold_percent"),
            "target_price": self._safe_get_float_or_none(params_dict, "target_price"),
            "direction": self._safe_get_string_or_none(params_dict, "direction"),
        }

        # 过滤掉 None 值，保持输出简洁
        params = {k: v for k, v in params.items() if v is not None}

        return {
            "intent": intent,
            "confidence": confidence,
            "params": params,
            "tier": 2,
            "raw_response": raw,
        }

    def _extract_json_block(self, text: str) -> Optional[str]:
        """从可能包含 markdown 代码块的文本中提取 JSON"""
        text = text.strip()

        # 尝试直接解析
        if text.startswith("{") and text.endswith("}"):
            return text

        # 尝试提取 ```json ... ``` 块
        import re
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if match:
            return match.group(1)

        # 尝试提取第一个 { ... } 块
        match = re.search(r"(\{.*\})", text, re.DOTALL)
        if match:
            return match.group(1)

        return None

    def _postprocess_params(self, result: Dict[str, Any], original_text: str) -> Dict[str, Any]:
        """后处理：股票名称映射、数值校验"""
        params = dict(result.get("params", {}))

        # 1. 股票名称 -> 代码映射
        stock_names = params.get("stock_names", [])
        stock_codes = list(params.get("stock_codes", []))

        for name in stock_names:
            code = self.STOCK_NAME_MAP.get(name)
            if code and code not in stock_codes:
                stock_codes.append(code)

        # 2. 从原始文本中补充 6 位数字代码
        import re
        text_codes = re.findall(r"\b\d{6}\b", original_text)
        for code in text_codes:
            if code not in stock_codes:
                stock_codes.append(code)

        if stock_codes:
            params["stock_codes"] = stock_codes

        # 3. 从原始文本中补充百分比（如果 LLM 没提取到）
        if "threshold_percent" not in params:
            # 先尝试匹配带符号的百分比（如 -5%、+3%）
            pct_match = re.search(r"([+-]?\d+(?:\.\d+)?)\s*%", original_text)
            if pct_match:
                val = float(pct_match.group(1))
                # 若文本中该百分比前有下跌/跌了/降了/跌等词，取负值
                # 取匹配位置前 10 个字符做上下文判断
                start_pos = max(0, pct_match.start() - 10)
                context = original_text[start_pos:pct_match.start()]
                decline_markers = ["跌了", "下跌", "降了", "下降", "跌"]
                if any(m in context for m in decline_markers) and val > 0:
                    val = -val
                params["threshold_percent"] = val

        # 4. 从原始文本中补充价格（如果 LLM 没提取到）
        if "target_price" not in params:
            price_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:元|块)", original_text)
            if price_match:
                params["target_price"] = float(price_match.group(1))

        result["params"] = params
        return result

    def _degrade(self, text: str, rule_best_result: Optional[Dict[str, Any]], reason: str) -> Dict[str, Any]:
        """降级：Ollama 不可用时返回 RuleEngine 最佳结果或 unknown fallback"""
        if rule_best_result is not None:
            degraded = dict(rule_best_result)
            degraded["tier"] = 1
            degraded["degraded_reason"] = reason
            return degraded

        return {
            "intent": "unknown",
            "confidence": 0.0,
            "params": {},
            "tier": 3,
            "degraded_reason": reason,
        }

    def _fallback_unknown(self, text: str) -> Dict[str, Any]:
        """完全 fallback：解析失败时返回 unknown"""
        return {
            "intent": "unknown",
            "confidence": 0.0,
            "params": {},
            "tier": 3,
        }

    # ------------------------------------------------------------------
    # 可用性探测（带缓存）
    # ------------------------------------------------------------------

    async def _check_availability_cached(self) -> bool:
        """带缓存的 Ollama 可用性探测，避免每次请求都探测"""
        now = time.monotonic()
        if now - self._health_checked_at < self.config.health_cache_ttl_seconds:
            return self._health_status

        self._health_status = await self._check_availability()
        self._health_checked_at = now
        return self._health_status

    async def _check_availability(self) -> bool:
        """探测 Ollama 服务是否可用"""
        try:
            client = self._get_client()
            resp = await client.get("/api/tags", timeout=5.0)
            resp.raise_for_status()
            data = resp.json()
            models = data.get("models", [])
            # 检查目标模型是否在列表中
            model_names = {m.get("name", "") for m in models}
            if self.config.model_name in model_names:
                return True
            # 有些版本返回的 name 带 :latest 后缀
            for name in model_names:
                if name.startswith(self.config.model_name):
                    return True
            logger.debug("Ollama 可用但模型 %s 未加载", self.config.model_name)
            return False
        except Exception as e:
            logger.debug("Ollama 可用性探测失败: %s", e)
            return False

    # ------------------------------------------------------------------
    # 日志采样
    # ------------------------------------------------------------------

    def _sample_log(self, text: str, strategy: str, result: Dict[str, Any]) -> None:
        """DEBUG 级别逐条记录，每 100 条输出 1 条 INFO 聚合日志"""
        intent = result.get("intent", "unknown")
        confidence = result.get("confidence", 0.0)
        logger.debug(
            "[LLM] text=%r strategy=%s intent=%s confidence=%.2f",
            text, strategy, intent, confidence,
        )
        if _llm_call_count % 100 == 0:
            logger.info(
                "[LLM] 聚合日志: 累计调用 %d 次, 最近策略=%s, intent=%s, confidence=%.2f",
                _llm_call_count, strategy, intent, confidence,
            )

    # ------------------------------------------------------------------
    # 类型安全辅助方法
    # ------------------------------------------------------------------

    @staticmethod
    def _safe_get_string(data: Dict[str, Any], key: str, default: str) -> str:
        val = data.get(key)
        if isinstance(val, str):
            return val
        if val is not None:
            try:
                return str(val)
            except Exception:
                pass
        return default

    @staticmethod
    def _safe_get_float(data: Dict[str, Any], key: str, default: float) -> float:
        val = data.get(key)
        if isinstance(val, (int, float)):
            return float(val)
        if isinstance(val, str):
            try:
                return float(val)
            except ValueError:
                pass
        return default

    @staticmethod
    def _safe_get_string_list(data: Dict[str, Any], key: str) -> List[str]:
        val = data.get(key)
        if isinstance(val, list):
            return [str(v) for v in val if v is not None]
        if isinstance(val, str):
            return [val]
        return []

    @staticmethod
    def _safe_get_string_or_none(data: Dict[str, Any], key: str) -> Optional[str]:
        val = data.get(key)
        if val is None:
            return None
        if isinstance(val, str):
            return val if val.strip() else None
        try:
            s = str(val)
            return s if s.strip() else None
        except Exception:
            return None

    @staticmethod
    def _safe_get_float_or_none(data: Dict[str, Any], key: str) -> Optional[float]:
        val = data.get(key)
        if val is None:
            return None
        if isinstance(val, (int, float)):
            return float(val)
        if isinstance(val, str):
            try:
                return float(val)
            except ValueError:
                return None
        return None
