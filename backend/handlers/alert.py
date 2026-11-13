"""提醒规则 handler — 从 main.py 拆出（M1-R1，ARCH-1）"""
from __future__ import annotations

from typing import Any, Dict, List


async def alert_list() -> List[Dict[str, Any]]:
    """读取 alert_rules 表，关联 portfolio 名称"""
    from local.db import db

    rows = await db.fetchall(
        """
        SELECT ar.*, p.symbol, p.name
        FROM alert_rules ar
        JOIN portfolio p ON ar.portfolio_id = p.id
        ORDER BY ar.id DESC
        """
    )
    return [
        {
            "id": row["id"],
            "portfolio_id": row["portfolio_id"],
            "symbol": row["symbol"],
            "name": row["name"],
            "threshold_percent": row["threshold_percent"],
            "direction": row["direction"],
            "is_active": bool(row["is_active"]),
            "last_triggered_at": row["last_triggered_at"],
            "cooldown_minutes": row["cooldown_minutes"],
        }
        for row in rows
    ]


async def alert_add(params: Dict[str, Any]) -> Dict[str, Any]:
    """写入 alert_rules 表，返回完整记录"""
    from local.db import db

    portfolio_id = int(params["portfolio_id"])
    threshold_percent = float(params.get("threshold_percent", 3.0))
    direction = params.get("direction", "both")
    cooldown_minutes = int(params.get("cooldown_minutes", 5))

    row_id = await db.execute_insert(
        """
        INSERT INTO alert_rules (portfolio_id, threshold_percent, direction, is_active, cooldown_minutes)
        VALUES (?, ?, ?, 1, ?)
        """,
        (portfolio_id, threshold_percent, direction, cooldown_minutes),
    )

    row = await db.fetchone(
        """
        SELECT ar.*, p.symbol, p.name
        FROM alert_rules ar
        JOIN portfolio p ON ar.portfolio_id = p.id
        WHERE ar.id = ?
        """,
        (row_id,),
    )
    if not row:
        raise RuntimeError("Failed to insert alert rule")

    return {
        "id": row["id"],
        "portfolio_id": row["portfolio_id"],
        "symbol": row["symbol"],
        "name": row["name"],
        "threshold_percent": row["threshold_percent"],
        "direction": row["direction"],
        "is_active": bool(row["is_active"]),
        "cooldown_minutes": row["cooldown_minutes"],
    }


async def alert_remove(params: Dict[str, Any]) -> Dict[str, Any]:
    """按 id 删除规则"""
    from local.db import db

    rule_id = int(params["id"])
    await db.execute("DELETE FROM alert_rules WHERE id = ?", (rule_id,))
    return {"success": True, "deleted_id": rule_id}


async def alert_notify(params: Dict[str, Any]) -> Dict[str, Any]:
    """手动触发 alert 通知广播（测试/调试用）

    参数:
        alerts: list[alert_event] 可选，直接广播给定的 alert 列表
        _broadcast: bool  可选，True 时触发 TCP 主动广播
    """
    from rpc.server import broadcast_notification
    test_alerts = params.get("alerts") or [{
        "symbol": "600519", "name": "贵州茅台",
        "current_price": 1800.0, "trigger_type": "up",
        "percent": 3.5, "message": "手动测试提醒"
    }]
    payload = {"method": "alert.notify", "params": {"alerts": test_alerts}}
    await broadcast_notification(payload)
    return {"success": True, "broadcast": True, "alerts_count": len(test_alerts)}

