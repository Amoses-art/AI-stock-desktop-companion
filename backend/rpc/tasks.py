"""Skill 任务注册表 — skill.execute 的 Task 跟踪与取消（ARCH-4，M1-R1 拆出）

独立成模块以避免 registry ↔ server 循环导入：
registry 需要引用 cancel_skill，server 需要引用 _active_requests。
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict

# 活跃 skill 任务表：request_id -> asyncio.Task
_active_requests: Dict[int, asyncio.Task] = {}


async def cancel_skill(params: Dict[str, Any]) -> Dict[str, Any]:
    """取消正在执行的 Skill 请求

    通过 request_id 查找 _active_requests 中的 Task，调用 cancel()。
    取消是 best-effort：若任务正处于同步阻塞调用中，需等该调用返回后
    才能在下一个 await 点抛出 CancelledError。
    """
    request_id = int(params.get("request_id", 0))
    task = _active_requests.get(request_id)
    if task and not task.done():
        task.cancel()
        return {"success": True, "cancelled": True, "request_id": request_id}
    return {"success": True, "cancelled": False, "request_id": request_id, "reason": "task_not_found_or_done"}
