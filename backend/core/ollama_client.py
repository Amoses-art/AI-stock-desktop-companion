"""
Ollama 本地大模型客户端 — M3 AI 接入层

职责：
1. 健康检查（服务可达 + 模型已加载）
2. Generate / Chat API 封装
3. 优雅降级（服务不可用时返回 None，不抛异常）
4. 与全局配置联动（model / timeout / host 可热更）
"""
from __future__ import annotations

import asyncio
import time
from typing import Optional

import httpx

from config.global_config import config_manager

# 默认值（与 global_config 对齐）
DEFAULT_HOST = "http://127.0.0.1:11434"
DEFAULT_TIMEOUT = 60.0  # 秒


class OllamaClient:
    """Ollama HTTP API 客户端（使用 httpx 异步调用）"""

    def __init__(self) -> None:
        self._host: str = config_manager.get("ollama_host", DEFAULT_HOST)
        self._model: str = config_manager.get("local_model_name", "qwen2.5:3b")
        self._timeout: float = float(config_manager.get("ollama_timeout", DEFAULT_TIMEOUT))
        self._client: Optional[httpx.AsyncClient] = None
        self._available: Optional[bool] = None  # None=未检测, True/False=检测结果
        self._last_check: float = 0.0
        self._check_interval: float = 30.0  # 健康检查间隔（秒）

    # ---------- 属性热更 ----------

    def _refresh_config(self) -> None:
        """从 config_manager 刷新可变参数（每次调用前调一次）"""
        self._host = config_manager.get("ollama_host", DEFAULT_HOST)
        self._model = config_manager.get("local_model_name", "qwen2.5:3b")
        self._timeout = float(config_manager.get("ollama_timeout", DEFAULT_TIMEOUT))

    @property
    def enabled(self) -> bool:
        return bool(config_manager.get("ai_enabled", False))

    # ---------- 健康检查 ----------

    async def is_available(self, force: bool = False) -> bool:
        """检测 Ollama 服务是否可达 + 是否已加载目标模型

        带 30 秒缓存，避免每次 parse 都发 health 请求
        """
        now = time.time()
        if not force and self._available is not None and (now - self._last_check) < self._check_interval:
            return self._available

        self._refresh_config()
        self._last_check = now

        try:
            if self._client is None:
                self._client = httpx.AsyncClient(timeout=httpx.Timeout(self._timeout))
            # 1. 服务可达
            r = await self._client.get(f"{self._host}/api/tags")
            if r.status_code != 200:
                self._available = False
                return False
            # 2. 模型存在
            models = [m["name"] for m in r.json().get("models", [])]
            # Ollama 模型名可能带 tag（如 qwen2.5:3b），也可能是 qwen2.5:3b-q4_K_M 等量化版本
            target = self._model
            if target in models or any(m.startswith(target.split(":")[0]) for m in models):
                self._available = True
                return True
            self._available = False
            return False
        except Exception:
            self._available = False
            return False

    # ---------- 核心 API ----------

    async def chat(self, messages: list[dict], system: str = "", temperature: float = 0.7,
                   max_tokens: int = 512, timeout: Optional[float] = None) -> Optional[str]:
        """多轮对话（/api/chat）

        Args:
            messages: [{"role": "user", "content": "..."}, ...]
            system: system prompt（可选，会插到 messages 最前）
            temperature: 0.0~1.0，越高越发散
            max_tokens: 最大生成长度（CPU 推理默认 512，防止思考过久）
            timeout: 生成硬超时（秒）；None 用配置值（封顶 45s）；超时返回 None 触发规则降级

        Returns:
            模型回复文本；服务不可用/超时/出错返回 None
        """
        if not self.enabled:
            return None

        self._refresh_config()
        if not await self.is_available():
            return None

        payload = {
            "model": self._model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": temperature, "num_predict": max_tokens, "num_gpu": 0},
        }
        if system:
            payload["system"] = system

        # 生成硬超时：CPU 推理下 2048 token 可能 60-180s，超时立即返回 None 走规则降级，
        # 避免请求长时间挂起导致前端/桥接超时（Rust 桥接 30s 会先触发）
        hard_timeout = timeout if timeout is not None else min(self._timeout, 45.0)
        try:
            if self._client is None:
                self._client = httpx.AsyncClient(timeout=httpx.Timeout(self._timeout))
            r = await asyncio.wait_for(
                self._client.post(f"{self._host}/api/chat", json=payload),
                timeout=hard_timeout,
            )
            if r.status_code == 200:
                return r.json().get("message", {}).get("content", "").strip()
            return None
        except Exception:
            return None

    async def generate(self, prompt: str, system: str = "", temperature: float = 0.7) -> Optional[str]:
        """单轮生成（/api/generate）— 适合 NLU 意图分类这种短任务"""
        return await self.chat(
            messages=[{"role": "user", "content": prompt}],
            system=system,
            temperature=temperature,
            max_tokens=128,
            timeout=15.0,
        )

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None


# 全局单例
ollama = OllamaClient()
