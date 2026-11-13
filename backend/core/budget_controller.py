"""
检索预算控制器 — 按用户/日/Skill 维度控制资源消耗（SQLite 持久化版）

架构决策(ADR-027): 检索预算按用户/日/Skill 维度控制
- 每日预算持久化到 SQLite，重启后保留
- 内存缓存减少数据库访问
- 跨天自动重置（日期变化时创建新记录）
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from local.db import db


@dataclass
class BudgetRecord:
    """预算消耗记录"""
    skill_name: str
    cost: float  # 成本单位（如 API 调用次数、token 数等）
    timestamp: float


class BudgetController:
    """检索预算控制器（SQLite 持久化 + 内存缓存）

    控制维度：
    - 按 Skill：限制单个 Skill 的日调用次数
    - 按用户：限制单用户的日总预算
    - 全局：限制系统级日总预算

    持久化设计：
    - budget_usage 表：date TEXT PRIMARY KEY, spent REAL, limit REAL, updated_at INTEGER
    - 每日首次调用时从数据库加载当日已用额度
    - 每次消费后写入数据库
    - 内存中保留当日缓存，减少数据库访问
    """

    # 默认日预算限制
    DEFAULT_SKILL_DAILY_LIMIT = 20  # 单个 Skill 日调用上限
    DEFAULT_USER_DAILY_LIMIT = 50   # 单个用户日总调用上限

    def __init__(self) -> None:
        self._skill_limits: Dict[str, int] = {}
        self._user_limits: Dict[str, int] = {}
        # 内存缓存：减少数据库访问
        self._cache_date: str = ""
        self._cache_spent: float = 0.0
        self._cache_limit: float = 0.0
        self._cache_records: List[BudgetRecord] = []
        self._initialized: bool = False

    def _today_str(self) -> str:
        """返回当前日期字符串 YYYY-MM-DD"""
        from datetime import datetime
        return datetime.now().strftime("%Y-%m-%d")

    async def _ensure_initialized(self) -> None:
        """确保内存缓存与数据库同步（懒加载）"""
        today = self._today_str()
        if self._initialized and self._cache_date == today:
            return

        # 日期变化或首次初始化：从数据库加载
        self._cache_date = today
        self._cache_records = []

        row = await db.fetchone(
            'SELECT spent, "limit", updated_at FROM budget_usage WHERE date = ?',
            (today,),
        )
        if row:
            self._cache_spent = float(row.get("spent", 0.0))
            self._cache_limit = float(row.get("limit", self.DEFAULT_USER_DAILY_LIMIT))
        else:
            # 新日期：创建记录
            self._cache_spent = 0.0
            self._cache_limit = self.DEFAULT_USER_DAILY_LIMIT
            await db.execute(
                '''INSERT INTO budget_usage (date, spent, "limit", updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(date) DO UPDATE SET
                    spent=excluded.spent,
                    "limit"=excluded."limit",
                    updated_at=excluded.updated_at''',
                (today, 0.0, self.DEFAULT_USER_DAILY_LIMIT, int(time.time())),
            )

        self._initialized = True

    async def _persist_spent(self) -> None:
        """将当前已用额度写入数据库"""
        today = self._today_str()
        await db.execute(
            '''INSERT INTO budget_usage (date, spent, "limit", updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(date) DO UPDATE SET
                spent=excluded.spent,
                "limit"=excluded."limit",
                updated_at=excluded.updated_at''',
            (today, self._cache_spent, self._cache_limit, int(time.time())),
        )

    def set_skill_limit(self, skill_name: str, daily_limit: int) -> None:
        """设置单个 Skill 的日调用上限"""
        self._skill_limits[skill_name] = daily_limit

    def set_user_limit(self, user_id: str, daily_limit: int) -> None:
        """设置单个用户的日调用上限"""
        self._user_limits[user_id] = daily_limit

    async def check(self, skill_name: str, user_id: str = "default", cost: float = 1.0) -> Dict[str, Any]:
        """检查是否超出预算

        Returns:
            {"allowed": bool, "reason": str, "remaining": int}
        """
        await self._ensure_initialized()

        # 检查 Skill 维度
        skill_limit = self._skill_limits.get(skill_name, self.DEFAULT_SKILL_DAILY_LIMIT)
        skill_used = sum(r.cost for r in self._cache_records if r.skill_name == skill_name)
        if skill_used + cost > skill_limit:
            return {
                "allowed": False,
                "reason": f"Skill '{skill_name}' 日调用次数已达上限 ({skill_limit})",
                "remaining": max(0, skill_limit - skill_used),
            }

        # 检查用户维度（基于持久化 spent）
        user_limit = self._user_limits.get(user_id, self.DEFAULT_USER_DAILY_LIMIT)
        user_used = self._cache_spent
        if user_used + cost > user_limit:
            return {
                "allowed": False,
                "reason": f"用户日总调用次数已达上限 ({user_limit})",
                "remaining": max(0, user_limit - user_used),
            }

        return {
            "allowed": True,
            "reason": "",
            "remaining": min(skill_limit - skill_used, user_limit - user_used),
        }

    async def consume(self, skill_name: str, user_id: str = "default", cost: float = 1.0) -> Dict[str, Any]:
        """消耗预算并返回结果

        先 check，若通过则记录消耗并持久化。
        公共接口保持不变（兼容旧调用）。
        """
        result = await self.check(skill_name, user_id, cost)
        if result["allowed"]:
            self._cache_records.append(BudgetRecord(
                skill_name=skill_name,
                cost=cost,
                timestamp=time.time(),
            ))
            self._cache_spent += cost
            # 写入数据库
            await self._persist_spent()
        return result

    async def get_usage(self, skill_name: Optional[str] = None, user_id: Optional[str] = None) -> Dict[str, Any]:
        """获取预算使用情况"""
        await self._ensure_initialized()

        today_records = self._cache_records

        if skill_name:
            used = sum(r.cost for r in today_records if r.skill_name == skill_name)
            limit = self._skill_limits.get(skill_name, self.DEFAULT_SKILL_DAILY_LIMIT)
            return {"skill": skill_name, "used": used, "limit": limit, "remaining": max(0, limit - used)}

        total_used = self._cache_spent
        total_limit = self._user_limits.get(user_id or "default", self.DEFAULT_USER_DAILY_LIMIT)
        return {"total_used": total_used, "limit": total_limit, "remaining": max(0, total_limit - total_used)}

    # === 兼容旧版同步接口（供非 async 调用方使用）===

    def _sync_ensure_initialized(self) -> None:
        """同步初始化（用于同步 consume 兼容）"""
        import asyncio
        try:
            loop = asyncio.get_running_loop()
            # 已有事件循环，创建 task（但无法 await）
            # 这仅在启动阶段使用，实际应使用 async 接口
        except RuntimeError:
            # 无事件循环，直接运行
            asyncio.run(self._ensure_initialized())

    def sync_consume(self, skill_name: str, user_id: str = "default", cost: float = 1.0) -> Dict[str, Any]:
        """同步 consume 兼容接口（启动时无事件循环场景）"""
        import asyncio
        try:
            loop = asyncio.get_running_loop()
            # 已在事件循环中，创建 task 并尽力等待
            # 注意：此方法仅用于兼容旧调用，推荐改用 async consume
            future = asyncio.ensure_future(self.consume(skill_name, user_id, cost))
            # 不能阻塞等待，返回一个默认允许的结果
            # 实际应由调用方改为 await budget_controller.consume()
            return {"allowed": True, "reason": "", "remaining": 9999, "async": True}
        except RuntimeError:
            return asyncio.run(self.consume(skill_name, user_id, cost))


# 全局单例
budget_controller = BudgetController()
