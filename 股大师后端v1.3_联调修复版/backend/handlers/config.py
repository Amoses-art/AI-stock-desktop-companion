"""配置 handler — 从 main.py 拆出（M1-R1）"""
from __future__ import annotations

from typing import Any, Dict

from config.global_config import config_manager


async def get_config() -> Dict[str, Any]:
    return config_manager.get_all()


async def set_config(params: Dict[str, Any]) -> Dict[str, Any]:
    key = params["key"]
    value = params["value"]
    await config_manager.set(key, value)
    return {"success": True, "key": key, "value": value}
