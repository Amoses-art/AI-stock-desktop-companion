"""RPC server - JSON Lines over stdin/stdout (Python)

Rust(Tauri) 通过管道与后端通信：请求写到子进程 stdin，响应与主动通知从 stdout 读取。
每行一个 JSON 对象，响应通过 req.id 匹配（允许乱序返回）。

设计（M1-R1 验证过的 stdin/stdout 版本，9/10 工作构建即此协议）：
- 独立线程阻塞读 stdin（跨平台兼容，Windows/Linux/macOS 均可用）
- 每条请求 spawn 为独立 asyncio.Task，主循环立即回到读取 stdin，
  这样 skill.cancel 可以在 skill.execute 执行期间被接收并处理（ARCH-4）
- 响应与主动通知均写回 stdout（线程安全加锁，逐行原子）
- stdout 只承载 JSON Lines 协议；启动日志一律走 stderr
"""
from __future__ import annotations

import asyncio
import json
import os
import queue
import sys
import threading
import time as _t
import traceback
from typing import Any, Dict

from core.message_protocol import RpcRequest, RpcResponse
from core.conversation_context import conversation_context
from handlers.chat import handle_chat
from rpc.registry import RPC_HANDLERS
from rpc.tasks import _active_requests

# RPC 调试日志路径（可经环境变量 RPC_DEBUG_LOG 覆盖，默认输出到工作目录）
_RPC_DEBUG_LOG = os.environ.get("RPC_DEBUG_LOG", os.path.join(os.getcwd(), "rpc_debug.log"))

# stdout 写锁：保证响应与主动通知逐行原子写出，不交错
_stdout_lock = asyncio.Lock()


def _log_rpc(req: RpcRequest, resp: RpcResponse = None,
             intent: str = None, reply_len: int = None, src: str = None) -> None:
    """写 RPC 调试日志（可选，不影响主流程）"""
    try:
        with open(_RPC_DEBUG_LOG, "a", encoding="utf-8") as _f:
            if resp is None:
                _f.write(
                    f"REQ id={req.id} method={req.method} "
                    f"params={json.dumps(req.params, ensure_ascii=False)[:500]}\n"
                )
            else:
                parts = [f"RESP id={req.id}"]
                if intent is not None:
                    parts.append(f"intent={intent}")
                if reply_len is not None:
                    parts.append(f"reply_len={reply_len}")
                if src is not None:
                    parts.append(f"src={src}")
                if resp.status == "error" and resp.error:
                    parts.append(f"error={json.dumps(resp.error, ensure_ascii=False)[:300]}")
                _f.write(" ".join(parts) + "\n")
    except Exception:
        pass


def _raw_stdout_write(text: str) -> None:
    """直接写 stdout fd，绕过 Python print 缓冲（PyInstaller 打包后 flush 不可靠）。"""
    data = text.encode("utf-8", errors="replace")
    try:
        fd = sys.stdout.fileno()
        os.write(fd, data)
    except Exception:
        print(text, end="", flush=True)


async def broadcast_notification(payload: Dict[str, Any]) -> None:
    """向 stdout 推送主动通知。

    Protocol: {"method": "...", "params": {...}}  (NO "id" field)
    Rust read_response() 将无 id 的行识别为通知，经 notify_tx 通道按 method 分发
    （alert.notify / quote.tick 等）。
    """
    line = json.dumps(payload, ensure_ascii=False) + "\n"
    async with _stdout_lock:
        _raw_stdout_write(line)


async def _write_response(resp: RpcResponse) -> None:
    """线程安全地写入 stdout（仅 JSON Lines），直写 fd 避免 PyInstaller 缓冲丢包"""
    async with _stdout_lock:
        _raw_stdout_write(resp.to_json() + "\n")


async def handle_rpc_request(req: RpcRequest) -> RpcResponse:
    """处理单个 RPC 请求"""
    print(f"[RPC-DISPATCH] id={req.id} method={req.method}", file=sys.stderr, flush=True)
    _log_rpc(req)
    _t0 = _t.time()

    handler = RPC_HANDLERS.get(req.method)
    if not handler:
        print(f"[RPC-DISPATCH] id={req.id} NOT FOUND!", file=sys.stderr, flush=True)
        return RpcResponse.err(req.id, -32601, f"Method not found: {req.method}")

    try:
        if req.method == "skill.execute":
            skill_input = req.params.get("input", {})
            message = skill_input.get("message") or skill_input.get("stock_code") or skill_input.get("stock_name") or ""
            session_id = skill_input.get("session_id") or "default"
            await conversation_context.load(session_id)
            request_id = int(req.params.get("request_id") or req.id)

            async def _execute_skill() -> Dict[str, Any]:
                result = await handle_chat(message)
                intent = result.get("intent", "unknown")
                reply_text = result.get("reply", "")
                await conversation_context.append(session_id, message, reply_text, intent)
                return result

            task = asyncio.create_task(_execute_skill())
            _active_requests[request_id] = task
            try:
                result = await task
                print(f"[RPC-DISPATCH] id={req.id} OK dt={_t.time()-_t0:.3f}s", file=sys.stderr, flush=True)
                resp = RpcResponse.ok(req.id, result)
                _log_rpc(req, resp,
                         intent=result.get("intent", "?"),
                         reply_len=len(result.get("reply", "")),
                         src=result.get("reply_source", "?"))
                return resp
            except asyncio.CancelledError:
                return RpcResponse.err(req.id, -32800, "Request cancelled")
            finally:
                _active_requests.pop(request_id, None)

        elif req.method == "skill.cancel":
            result = await handler(req.params)
            return RpcResponse.ok(req.id, result)

        elif req.method in ("portfolio.list", "alert.list", "stats.summary", "config.get"):
            result = await handler()
            if isinstance(result, (str, int, float, bool)) or result is None:
                result = {"value": result}
            print(f"[RPC-DISPATCH] id={req.id} OK dt={_t.time()-_t0:.3f}s", file=sys.stderr, flush=True)
            return RpcResponse.ok(req.id, result)
        else:
            result = await handler(req.params)
            if isinstance(result, (str, int, float, bool)) or result is None:
                result = {"value": result}
            print(f"[RPC-DISPATCH] id={req.id} OK dt={_t.time()-_t0:.3f}s", file=sys.stderr, flush=True)
            return RpcResponse.ok(req.id, result)

    except Exception as e:
        traceback.print_exc()
        print(f"[RPC-DISPATCH] id={req.id} ERROR dt={_t.time()-_t0:.3f}s err={e}", file=sys.stderr, flush=True)
        return RpcResponse.err(req.id, -32603, str(e))


async def run_rpc_server() -> None:
    """JSON Lines RPC 主循环：从 stdin 读取请求，写回 stdout"""
    print("[Gudashi] RPC server starting (stdin/stdout)...", file=sys.stderr, flush=True)

    loop = asyncio.get_running_loop()
    eof_event = asyncio.Event()

    async def _process_one(line: str) -> None:
        """处理单行请求（并发：每条请求独立 Task，响应按 req.id 匹配）"""
        line = line.strip()
        if not line:
            return
        try:
            req = RpcRequest.from_json(line)
            print(f"[Gudashi] stdin RPC id={req.id} method={req.method}", file=sys.stderr, flush=True)
            resp = await handle_rpc_request(req)
            await _write_response(resp)
        except Exception as e:
            print(f"[Gudashi] stdin parse error: {e}", file=sys.stderr, flush=True)

    _reader_alive = {"flag": True}

    def _stdin_reader() -> None:
        """独立线程阻塞读 stdin（跨平台兼容）；崩溃时自愈重启，防止后端僵尸"""
        print("[Gudashi] _stdin_reader thread STARTED", file=sys.stderr, flush=True)
        try:
            fd = sys.stdin.fileno()
        except Exception:
            fd = None
        if fd is None:
            print("[Gudashi] _stdin_reader no stdin fd", file=sys.stderr, flush=True)
            loop.call_soon_threadsafe(eof_event.set)
            return
        try:
            buf = b""
            while True:
                try:
                    chunk = os.read(fd, 4096)
                except OSError as e:
                    print(f"[Gudashi] _stdin_reader os.read error: {e}", file=sys.stderr, flush=True)
                    break
                if not chunk:
                    print("[Gudashi] _stdin_reader got EOF", file=sys.stderr, flush=True)
                    break
                buf += chunk
                while b"\n" in buf:
                    line_bytes, buf = buf.split(b"\n", 1)
                    try:
                        line = line_bytes.decode("utf-8", errors="replace").rstrip("\r")
                    except Exception:
                        continue
                    if not line.strip():
                        continue
                    print(f"[Gudashi] _stdin_reader line: {line[:80]}{'...' if len(line) > 80 else ''}", file=sys.stderr, flush=True)
                    asyncio.run_coroutine_threadsafe(_process_one(line), loop)
        except Exception as e:
            # 读取线程异常崩溃：打印堆栈后自愈重启（防止后端存活但不响应请求的僵尸态）
            print(f"[Gudashi] _stdin_reader CRASHED: {e}", file=sys.stderr, flush=True)
            import traceback as _tb
            _tb.print_exc()
            if _reader_alive["flag"]:
                print("[Gudashi] _stdin_reader respawning...", file=sys.stderr, flush=True)
                threading.Thread(target=_stdin_reader, daemon=True).start()
            return
        # stdin 关闭（Rust 端退出）→ 触发服务器退出
        loop.call_soon_threadsafe(eof_event.set)

    threading.Thread(target=_stdin_reader, daemon=True).start()
    print("[Gudashi] RPC server ready", file=sys.stderr, flush=True)

    # 等待 stdin EOF 后退出
    await eof_event.wait()
    print("[Gudashi] RPC stdin closed, server exiting", file=sys.stderr, flush=True)
