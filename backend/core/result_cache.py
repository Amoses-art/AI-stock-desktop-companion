"""
结果缓存层 — 同步 + 异步混合

职责：缓存 LLM 解析结果，减少重复调用，提升高频输入响应速度。
- TTL 默认 5 分钟
- 基于 asyncio 友好设计（键计算同步，淘汰异步）
- 线程/协程安全由 asyncio 单线程保证

接口契约：
- get() / set() 为同步方法（键计算和内存操作）
- 清理为异步方法（可选后台任务）
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


@dataclass
class _CacheEntry:
    """缓存条目"""

    key: str
    value: Dict[str, Any]
    created_at: float
    ttl_seconds: float

    @property
    def is_expired(self) -> bool:
        return time.monotonic() - self.created_at > self.ttl_seconds


class ResultCache:
    """LLM 解析结果缓存

    设计：
    - 基于内存 dict，key 为输入文本的规范化哈希
    - TTL 驱动过期，访问时懒检查
    - 容量上限防止内存无限增长（FIFO 淘汰，按 created_at 写入时间）
    """

    DEFAULT_TTL_SECONDS: float = 300.0  # 5 分钟
    DEFAULT_MAX_ENTRIES: int = 1000

    def __init__(self, ttl_seconds: float = DEFAULT_TTL_SECONDS, max_entries: int = DEFAULT_MAX_ENTRIES) -> None:
        self._ttl = ttl_seconds
        self._max_entries = max_entries
        self._store: Dict[str, _CacheEntry] = {}
        self._hit_count: int = 0
        self._miss_count: int = 0

    # ------------------------------------------------------------------
    # 公共接口
    # ------------------------------------------------------------------

    def get(self, text: str) -> Optional[Dict[str, Any]]:
        """获取缓存结果。同步、不抛异常。"""
        key = self._make_key(text)
        entry = self._store.get(key)
        if entry is None:
            self._miss_count += 1
            return None

        if entry.is_expired:
            del self._store[key]
            self._miss_count += 1
            return None

        self._hit_count += 1
        # 返回副本，防止外部修改
        return dict(entry.value)

    def set(self, text: str, result: Dict[str, Any]) -> None:
        """写入缓存。同步、不抛异常。"""
        try:
            key = self._make_key(text)
            # 容量检查：超限则淘汰最旧的条目
            if len(self._store) >= self._max_entries and key not in self._store:
                self._evict_oldest(1)

            self._store[key] = _CacheEntry(
                key=key,
                value=dict(result),
                created_at=time.monotonic(),
                ttl_seconds=self._ttl,
            )
        except Exception as e:
            logger.debug("ResultCache.set 异常: %s", e)

    def invalidate(self, text: str) -> bool:
        """使指定输入的缓存失效。同步。"""
        key = self._make_key(text)
        if key in self._store:
            del self._store[key]
            return True
        return False

    def clear(self) -> None:
        """清空所有缓存。同步。"""
        self._store.clear()
        self._hit_count = 0
        self._miss_count = 0

    async def cleanup_expired(self) -> int:
        """异步清理过期条目，返回清理数量。"""
        expired_keys = [k for k, e in self._store.items() if e.is_expired]
        for k in expired_keys:
            del self._store[k]
        return len(expired_keys)

    def stats(self) -> Dict[str, Any]:
        """返回缓存统计信息"""
        total = self._hit_count + self._miss_count
        return {
            "entries": len(self._store),
            "hits": self._hit_count,
            "misses": self._miss_count,
            "hit_rate": self._hit_count / total if total > 0 else 0.0,
            "ttl_seconds": self._ttl,
            "max_entries": self._max_entries,
        }

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    @staticmethod
    def _make_key(text: str) -> str:
        """生成缓存键：文本规范化后取 SHA256 前 16 位"""
        normalized = text.strip().lower().replace(" ", "").replace("，", ",").replace("。", ".")
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]

    def _evict_oldest(self, count: int) -> None:
        """淘汰最早的 count 个条目"""
        if not self._store:
            return
        sorted_items = sorted(self._store.items(), key=lambda x: x[1].created_at)
        for key, _ in sorted_items[:count]:
            del self._store[key]


# 全局单例（SchemaExtractor 使用）
result_cache = ResultCache()
