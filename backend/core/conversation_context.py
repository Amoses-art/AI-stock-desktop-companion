"""
对话上下文管理器 — LRU + 容量上限

架构决策(ADR-019): SQLite 表 + 内存热缓存，热数据内存缓存（最近 10 轮），
冷数据 SQLite，启动时预热。系统回复存摘要（前 200 字 / 结构化关键信息）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class ConversationRound:
    """单轮对话记录"""
    role: str  # "user" | "assistant"
    content: str
    intent: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())


class ConversationContext:
    """对话上下文管理器 — LRU + 容量上限"""

    MAX_ROUNDS = 10
    MAX_CHARS = 30000  # 约 128K token 的字符估算
    TABLE_NAME = "conversation_history"

    def __init__(self) -> None:
        # 内存缓存: session_id -> List[ConversationRound]
        self._cache: Dict[str, List[ConversationRound]] = {}

    async def load(self, session_id: str) -> List[ConversationRound]:
        """加载最近 N 轮对话"""
        # 内存缓存命中
        if session_id in self._cache:
            return self._cache[session_id]

        # 查 SQLite
        from local.db import db

        rows = await db.fetchall(
            f"""
            SELECT role, content, intent, created_at
            FROM {self.TABLE_NAME}
            WHERE session_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (session_id, self.MAX_ROUNDS),
        )

        rounds: List[ConversationRound] = []
        for row in reversed(rows):  # 按时间正序
            rounds.append(
                ConversationRound(
                    role=row["role"],
                    content=row["content"],
                    intent=row["intent"],
                    created_at=row["created_at"],
                )
            )

        # 写入内存缓存
        self._cache[session_id] = rounds
        return rounds

    async def append(
        self,
        session_id: str,
        user_msg: str,
        system_reply: str,
        intent: Optional[str] = None,
    ) -> None:
        """追加一轮对话，触发容量检查"""
        # 摘要化系统回复
        summary = self._summarize_reply(system_reply, intent)

        # 写入 SQLite
        from local.db import db

        await db.execute(
            f"""
            INSERT INTO {self.TABLE_NAME} (session_id, role, content, intent, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (session_id, "user", user_msg, intent, datetime.now().isoformat()),
        )
        await db.execute(
            f"""
            INSERT INTO {self.TABLE_NAME} (session_id, role, content, intent, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (session_id, "assistant", summary, intent, datetime.now().isoformat()),
        )

        # 更新内存缓存
        if session_id not in self._cache:
            self._cache[session_id] = []
        self._cache[session_id].append(
            ConversationRound(role="user", content=user_msg, intent=intent)
        )
        self._cache[session_id].append(
            ConversationRound(role="assistant", content=summary, intent=intent)
        )

        # 容量检查 + LRU 淘汰
        await self._evict_if_oversized(session_id)

    async def _evict_if_oversized(self, session_id: str) -> None:
        """LRU 淘汰：超容量时删除最旧的 20%"""
        rounds = self._cache.get(session_id, [])
        if not rounds:
            return

        # 按轮数淘汰
        if len(rounds) > self.MAX_ROUNDS * 2:  # user + assistant = 2 条/轮
            excess = len(rounds) - self.MAX_ROUNDS * 2
            # 删除最旧的 excess 条
            self._cache[session_id] = rounds[excess:]

            # 同步删除数据库中的旧记录
            from local.db import db

            # 找到当前保留的最旧记录的 created_at
            oldest_kept = self._cache[session_id][0].created_at
            await db.execute(
                f"""
                DELETE FROM {self.TABLE_NAME}
                WHERE session_id = ? AND created_at < ?
                """,
                (session_id, oldest_kept),
            )

        # 按字符数淘汰
        total_chars = sum(len(r.content) for r in self._cache[session_id])
        if total_chars > self.MAX_CHARS:
            # 删除最旧的 20%
            to_remove = max(1, int(len(self._cache[session_id]) * 0.2))
            self._cache[session_id] = self._cache[session_id][to_remove:]

    def _summarize_reply(self, reply: str, intent: Optional[str]) -> str:
        """摘要化系统回复

        - 文本回复：存前 200 字
        - Skill 卡片：存结构化关键信息
        """
        # 尝试解析为 JSON（Skill 卡片）
        try:
            data = json.loads(reply)
            if isinstance(data, dict):
                # 提取关键字段
                summary_fields = {}
                if "intent" in data or "skill_name" in data:
                    summary_fields["intent"] = data.get("intent") or data.get("skill_name")
                if "symbol" in data:
                    summary_fields["symbol"] = data["symbol"]
                if "rating" in data:
                    summary_fields["rating"] = data["rating"]
                if "reply" in data and isinstance(data["reply"], str):
                    summary_fields["reply_preview"] = data["reply"][:100]
                return json.dumps(summary_fields, ensure_ascii=False)
        except (json.JSONDecodeError, TypeError):
            pass

        # 纯文本：截断到 200 字
        if len(reply) > 200:
            return reply[:200] + "..."
        return reply

    async def get_context_for_prompt(self, session_id: str, max_turns: int = 6):
        """加载 SQLite 历史 + 格式化为 prompt 可用的 list[str]。
        P0-1 修复：自动从 DB load，返回 list[str] 给调用方拼装。"""
        await self.load(session_id)
        rounds = self._cache.get(session_id, [])
        if not rounds:
            return []

        result: List[str] = []
        for r in rounds[-max_turns:]:
            role_label = "用户" if r.role == "user" else "助手"
            result.append(f"{role_label}: {r.content}")
        return result



# 全局单例
conversation_context = ConversationContext()
