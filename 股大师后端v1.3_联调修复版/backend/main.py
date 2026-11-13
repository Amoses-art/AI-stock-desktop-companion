"""股大师 Python 后端主入口 — 装配层（M1-R1 重构后）

与 Rust(Tauri) 通过 stdin/stdout 通信，每行一个 JSON 对象。

职责（仅装配，不含业务逻辑）：
- 数据库初始化 + 配置加载
- 搜索服务配置（环境变量优先，配置兜底）
- 行情轮询启动（含 AlertEngine 评估）+ 全市场预热 + 健康检查
- RPC 服务器生命周期

业务 handler 见 handlers/，RPC 分发见 rpc/，输入解析 v2 见 core/nlu_v2.py。
"""
from __future__ import annotations

import asyncio
import sys

# ===== PyInstaller 管道修复：强制 stdin/stdout 行缓冲 + utf-8 =====
# PyInstaller onefile + Windows Stdio::piped 模式下 stdout 默认为全缓冲，
# 即使 print(..., flush=True) 也可能失效，强制 reconfigure 为 line_buffering。
def _fix_pipe_buffering() -> None:
    try:
        if hasattr(sys.stdout, 'reconfigure'):
            sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)
        if hasattr(sys.stdin, 'reconfigure'):
            sys.stdin.reconfigure(encoding='utf-8')
    except Exception:
        pass

_fix_pipe_buffering()

# ===== PyInstaller 管道修复：stderr 直写 fd，吞掉 EINVAL（09/18 最终版修复项）=====
# PyInstaller + Windows Stdio::piped 下 print(..., file=sys.stderr, flush=True)
# 间歇性抛 [Errno 22] Invalid argument，导致 _stdin_reader 线程异常退出、
# 后续请求无法调度甚至后端死亡。用 os.write 直写 fd 2 绕过 Python 缓冲层。
import os as _os


class _SafeStderr:
    def __init__(self, fd):
        self._fd = fd

    def write(self, s):
        try:
            if isinstance(s, str):
                _os.write(self._fd, s.encode("utf-8", errors="replace"))
            else:
                _os.write(self._fd, s)
        except Exception:
            pass
        return len(s) if isinstance(s, str) else 0

    def flush(self):
        pass

    def fileno(self):
        return self._fd

    def isatty(self):
        return False


try:
    _stderr_fd = sys.stderr.fileno()
    sys.stderr = _SafeStderr(_stderr_fd)
except Exception:
    pass

from config.global_config import config_manager
from data.quote_service import quote_service
from core.search_service import search_service
from local.db import init_database
from rpc.server import run_rpc_server


async def _configure_search_service() -> None:
    """初始化搜索服务配置（环境变量优先，配置兜底）"""
    search_backend = config_manager.get("search_backend", "")
    serpapi_key = config_manager.get("serpapi_api_key", "")
    bing_key = config_manager.get("bing_search_api_key", "")
    if search_backend and (serpapi_key or bing_key):
        api_key = serpapi_key if search_backend == "serpapi" else bing_key
        search_service.configure(search_backend, api_key)
        print(f"[Gudashi] SearchService configured: {search_backend}", file=sys.stderr, flush=True)
    elif search_service._backend:
        print(f"[Gudashi] SearchService auto-configured from env: {search_service._backend}", file=sys.stderr, flush=True)
    else:
        print("[Gudashi] SearchService running in mock mode (no API key)", file=sys.stderr, flush=True)


async def main() -> None:
    """后端主入口 — 先 bind RPC socket，再后台初始化其余（启动时序优化）"""
    # ===== ① 毫秒级初始化 =====
    print("[Gudashi] Initializing database...", file=sys.stderr, flush=True)
    await init_database()
    await config_manager.load_from_db()
    print("[Gudashi] Database ready, config loaded.", file=sys.stderr, flush=True)

    # ===== ② 立刻 bind RPC socket — Rust 端秒检测 ready =====
    # 之前 run_rpc_server 在所有初始化最后才调用，akshare 加载 70 文件 ~15s
    # 导致 Rust 端等不到 ready marker。现在先 create_task，bind 后立刻打印 ready。
    rpc_task = asyncio.create_task(run_rpc_server())

    # ===== ③ 继续其余初始化（RPC server 已在监听） =====

    # 交易时段配置接线（M1-R2 G1）：user_config 优先，未配置默认 09:00-15:00
    from core.trading_hours_guard import TradingHoursGuard
    TradingHoursGuard.configure(
        start=config_manager.get("trading_hours_default_start", "09:00"),
        end=config_manager.get("trading_hours_default_end", "15:00"),
    )
    print(
        f"[Gudashi] Trading hours: {config_manager.get('trading_hours_default_start', '09:00')}-"
        f"{config_manager.get('trading_hours_default_end', '15:00')}",
        file=sys.stderr, flush=True,
    )

    await _configure_search_service()

    # 启动行情轮询（含 AlertEngine 评估）
    await quote_service.start_polling(interval_seconds=10)
    print("[Gudashi] Quote polling started.", file=sys.stderr, flush=True)

    # 后台预热 A股全市场快照（东财失败自动回退新浪），首次对话/查询直接命中缓存
    asyncio.create_task(quote_service.warmup())

    # ARCH-6: 启动健康检查器
    from data.health_checker import health_checker
    await health_checker.start()

    # ===== ④ 等 RPC 结束（永远不会） =====
    try:
        await rpc_task
    finally:
        await quote_service.stop_polling()
        await search_service.close()
        print("[Gudashi] Shutdown complete.", file=sys.stderr, flush=True)

if __name__ == "__main__":
    asyncio.run(main())
