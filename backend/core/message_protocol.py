"""
通信协议定义 — Rust(Tauri) ↔ Python 子进程 JSON Lines 协议

规则：
1. 每行一个 JSON 对象（\n 分隔）
2. request 必须包含 id（u64 整数）、method、params
3. response 必须包含 id（与 request 对应）、status(ok/error)、result/error
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, Optional


class Status(str, Enum):
    OK = "ok"
    ERROR = "error"


@dataclass
class RpcRequest:
    """JSON Lines 请求格式"""

    id: int = 0
    method: str = ""
    params: Dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, separators=(",", ":"))

    @classmethod
    def from_json(cls, line: str) -> RpcRequest:
        data = json.loads(line)
        return cls(
            id=int(data.get("id", 0)),
            method=data.get("method", ""),
            params=data.get("params", {}),
        )


@dataclass
class RpcResponse:
    """JSON Lines 响应格式"""

    id: int = 0
    status: str = Status.OK
    result: Optional[Dict[str, Any]] = None
    error: Optional[Dict[str, Any]] = None

    def to_json(self) -> str:
        payload = {"id": self.id, "status": self.status}
        if self.result is not None:
            payload["result"] = self.result
        if self.error is not None:
            payload["error"] = self.error
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    @classmethod
    def ok(cls, request_id: int, result: Dict[str, Any]) -> RpcResponse:
        return cls(id=request_id, status=Status.OK, result=result)

    @classmethod
    def err(cls, request_id: int, code: int, message: str) -> RpcResponse:
        """构造错误响应（方法名不能用 error，会与 dataclass 字段冲突）"""
        return cls(
            id=request_id,
            status=Status.ERROR,
            error={"code": code, "message": message},
        )
