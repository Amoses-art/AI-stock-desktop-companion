"""RPC 方法注册表 — 与《契约冻结表 v3.2》§一保持一致（M1-R1 拆出）"""
from __future__ import annotations

from typing import Any, Dict

from handlers import (
    list_portfolio, add_portfolio, remove_portfolio,
    get_quote, resolve_quote, subscribe_quotes, refresh_quotes,
    get_kline,
    get_summary,
    get_config, set_config,
    alert_list, alert_add, alert_remove, alert_notify,
    handle_chat,
)
from handlers.chat import list_chat_history, clear_chat_history
from rpc.tasks import cancel_skill


async def _handle_ping(params: Dict[str, Any] = None) -> Dict[str, Any]:
    """看门狗心跳：快速返回，用于 Rust 端探测后端存活（不触发任何业务）"""
    return {"pong": True}


RPC_HANDLERS: Dict[str, Any] = {
    "ping": _handle_ping,
    "portfolio.list": list_portfolio,
    "portfolio.add": add_portfolio,
    "portfolio.remove": remove_portfolio,
    "quote.get": get_quote,
    "quote.resolve": resolve_quote,
    "quote.subscribe": subscribe_quotes,
    "quote.refresh": refresh_quotes,
    "kline.get": get_kline,
    "skill.execute": handle_chat,
    "skill.cancel": cancel_skill,
    "alert.list": alert_list,
    "alert.add": alert_add,
    "alert.remove": alert_remove,
    "alert.notify": alert_notify,
    "config.get": get_config,
    "config.set": set_config,
    "stats.summary": get_summary,
    "chat_history.list": list_chat_history,
    "chat_history.clear": clear_chat_history,
}
