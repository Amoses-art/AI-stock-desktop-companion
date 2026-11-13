"""handlers 包 — RPC 业务处理函数层（M1-R1 从 main.py 拆出）"""
from handlers.portfolio import list_portfolio, add_portfolio, remove_portfolio
from handlers.quote import get_quote, resolve_quote, subscribe_quotes, refresh_quotes
from handlers.kline import get_kline
from handlers.stats import get_summary
from handlers.config import get_config, set_config
from handlers.alert import alert_list, alert_add, alert_remove, alert_notify
from handlers.chat import handle_chat

__all__ = [
    "list_portfolio", "add_portfolio", "remove_portfolio",
    "get_quote", "resolve_quote", "subscribe_quotes", "refresh_quotes",
    "get_kline",
    "get_summary",
    "get_config", "set_config",
    "alert_list", "alert_add", "alert_remove", "alert_notify",
    "handle_chat",
]
