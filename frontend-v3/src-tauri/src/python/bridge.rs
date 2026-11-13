use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::collections::HashSet;
use std::collections::HashMap;
use std::sync::{atomic::{AtomicU64, Ordering}};
use tokio::sync::Mutex;
use std::time::Duration;
use tokio::sync::{mpsc, oneshot};
use tracing::{debug, error, info, warn};

/// JSON Lines RPC 请求
#[derive(Debug, Serialize)]
pub struct RpcRequest {
    pub id: u64,
    pub method: String,
    pub params: Value,
}

/// JSON Lines RPC 响应
#[derive(Debug, Deserialize)]
pub struct RpcResponse {
    pub id: u64,
    pub status: String,
    pub result: Option<Value>,
    pub error: Option<RpcError>,
}

#[derive(Debug, Deserialize)]
pub struct RpcError {
    pub code: i32,
    pub message: String,
}

/// Python 主动推送的通知（有 method 无 id，区别于 RPC 响应）
/// 如 alert.notify 提醒推送：{"method":"alert.notify","params":{"alerts":[...]}}
#[derive(Debug, Deserialize)]
pub struct PythonNotification {
    pub method: String,
    #[serde(default)]
    pub params: Value,
}

/// 转发给订阅者的通知（携带 method，便于按类型分发：alert.notify / quote.tick）
#[derive(Debug, Clone)]
pub struct PythonNotify {
    pub method: String,
    pub params: Value,
}

/// Python 桥接错误（Display 文案面向用户，直接展示在前端错误提示中）
#[derive(Debug, thiserror::Error)]
pub enum BridgeError {
    #[error("IO error: {0}")]
    Io(#[from] std::io::Error),
    #[error("JSON error: {0}")]
    Json(#[from] serde_json::Error),
    #[error("后端错误: {0}")]
    Python(String),
    #[error("请求超时，请稍后重试")]
    Timeout,
    #[error("后端通信通道已断开（后端进程可能已退出），请重新启动应用")]
    ChannelClosed,
}

/// Python 子进程桥接器 — 通过 stdin/stdout JSON Lines 通信
pub struct PythonBridge {
    request_id: AtomicU64,
    pending: Mutex<HashMap<u64, oneshot::Sender<RpcResponse>>>,
    sender: Option<mpsc::UnboundedSender<String>>,
    // ARCH-4: 已取消的请求 ID 集合
    cancelled_ids: Mutex<HashSet<u64>>,
    // Python 主动通知的转发通道（alert.notify / quote.tick 等）
    notify_tx: Option<mpsc::UnboundedSender<PythonNotify>>,
}

impl PythonBridge {
    pub fn new() -> Self {
        Self {
            request_id: AtomicU64::new(1),
            pending: Mutex::new(HashMap::new()),
            sender: None,
            cancelled_ids: Mutex::new(HashSet::new()),
            notify_tx: None,
        }
    }

    /// 订阅 Python 主动通知（如 alert.notify / quote.tick），返回接收端
    /// 接收到的消息携带 method + params，调用方按 method 分发
    pub fn subscribe_notifications(&mut self) -> mpsc::UnboundedReceiver<PythonNotify> {
        let (tx, rx) = mpsc::unbounded_channel();
        self.notify_tx = Some(tx);
        rx
    }

    pub fn attach_sender(&mut self, sender: mpsc::UnboundedSender<String>) {
        self.sender = Some(sender);
    }

    /// 后端重启清场：使所有 pending 请求立即失败，解除 sender 与通知订阅
    pub async fn reset(&mut self) {
        let pending = std::mem::take(&mut *self.pending.lock().await);
        for (_id, tx) in pending {
            let _ = tx.send(RpcResponse {
                id: 0,
                status: "error".to_string(),
                result: None,
                error: Some(RpcError {
                    code: -32000,
                    message: "后端已重启，请重试".to_string(),
                }),
            });
        }
        self.cancelled_ids.lock().await.clear();
        self.sender = None;
        self.notify_tx = None;
        info!(action = "bridge_reset", "Bridge state reset for backend restart");
    }

    /// 看门狗心跳：3s 短超时探测后端是否存活
    pub async fn ping(&self) -> Result<Value, BridgeError> {
        let id = self.request_id.fetch_add(1, Ordering::SeqCst);
        let req = RpcRequest {
            id,
            method: "ping".to_string(),
            params: json!({}),
        };
        let req_line = match serde_json::to_string(&req) {
            Ok(line) => line,
            Err(e) => return Err(BridgeError::Json(e)),
        };
        debug!(action = "rpc_ping", id, "Watchdog ping sent");

        let (tx, rx) = oneshot::channel();
        {
            let mut pending = self.pending.lock().await;
            pending.insert(id, tx);
        }

        if let Some(sender) = &self.sender {
            if sender.send(req_line).is_err() {
                let mut pending = self.pending.lock().await;
                pending.remove(&id);
                return Err(BridgeError::ChannelClosed);
            }
        } else {
            let mut pending = self.pending.lock().await;
            pending.remove(&id);
            return Err(BridgeError::Python("后端服务未连接".to_string()));
        }

        match tokio::time::timeout(Duration::from_secs(3), rx).await {
            Ok(Ok(resp)) => {
                if resp.status == "ok" {
                    Ok(resp.result.unwrap_or(Value::Null))
                } else if let Some(err) = resp.error {
                    Err(BridgeError::Python(err.message))
                } else {
                    Err(BridgeError::Python("后端返回未知错误".to_string()))
                }
            }
            Ok(Err(_)) => Err(BridgeError::ChannelClosed),
            Err(_) => {
                let mut pending = self.pending.lock().await;
                pending.remove(&id);
                Err(BridgeError::Timeout)
            }
        }
    }

    /// ARCH-4: 取消指定请求
    pub async fn cancel_request(&self, id: u64) {
        let mut set = self.cancelled_ids.lock().await;
        set.insert(id);
        info!(action = "rpc_cancel", id, "Request marked as cancelled");
    }

    /// 发起 RPC 调用，等待响应（10 秒超时）
    /// 返回 (request_id, result)，调用方可凭 request_id 执行取消
    pub async fn call(&self, method: &str, params: Value) -> (u64, Result<Value, BridgeError>) {
        let id = self.request_id.fetch_add(1, Ordering::SeqCst);

        let req = RpcRequest {
            id,
            method: method.to_string(),
            params,
        };

        let req_line = match serde_json::to_string(&req) {
            Ok(line) => line,
            Err(e) => return (id, Err(BridgeError::Json(e))),
        };
        debug!(action = "rpc_send", id, method, line = %req_line);

        // 创建 oneshot channel 并注册到 pending
        let (tx, rx) = oneshot::channel();
        {
            let mut pending = self.pending.lock().await;
            pending.insert(id, tx);
        }

        if let Some(sender) = &self.sender {
            if let Err(_) = sender.send(req_line) {
                let mut pending = self.pending.lock().await;
                pending.remove(&id);
                return (id, Err(BridgeError::ChannelClosed));
            }
        } else {
            let mut pending = self.pending.lock().await;
            pending.remove(&id);
            return (id, Err(BridgeError::Python("后端服务未连接，请重新启动应用".to_string())));
        }

        // 等待响应，差异化超时：
        //   skill.execute → 90s（Ollama CPU 生成 + 行情冷查询备源全量拉取，45s 硬超时后端仍可能先返回规则降级）
        //   其余方法 → 30s（portfolio.add/alert 等快操作，快速失败及时反馈）
        let timeout_secs: u64 = if method == "skill.execute" { 90 } else { 30 };
        match tokio::time::timeout(Duration::from_secs(timeout_secs), rx).await {
            Ok(Ok(resp)) => {
                // ARCH-4: 检查是否已取消
                let was_cancelled = {
                    let mut set = self.cancelled_ids.lock().await;
                    set.remove(&resp.id)
                };
                if was_cancelled {
                    info!(action = "rpc_cancelled_response_dropped", id = resp.id);
                    return (id, Err(BridgeError::Python("请求已取消".to_string())));
                }

                if resp.status == "ok" {
                    (id, Ok(resp.result.unwrap_or(Value::Null)))
                } else if let Some(err) = resp.error {
                    (id, Err(BridgeError::Python(err.message)))
                } else {
                    (id, Err(BridgeError::Python("后端返回未知错误".to_string())))
                }
            }
            Ok(Err(_)) => {
                (id, Err(BridgeError::ChannelClosed))
            }
            Err(_) => {
                let mut pending = self.pending.lock().await;
                pending.remove(&id);
                (id, Err(BridgeError::Timeout))
            }
        }
    }

    /// 处理从 Python 返回的单行 JSON
    /// 优先尝试解析为主动通知（有 method 无 id），否则按 RPC 响应分发
    pub async fn handle_response(&self, line: &str) {
        // Python 主动通知（如 alert.notify / quote.tick）：按 method 转发给订阅者
        if let Ok(note) = serde_json::from_str::<PythonNotification>(line) {
            if let Some(tx) = &self.notify_tx {
                if tx
                    .send(PythonNotify { method: note.method.clone(), params: note.params })
                    .is_ok()
                {
                    info!(action = "rpc_notification_forwarded", method = %note.method, "Python notification forwarded to subscriber");
                    return;
                }
            }
        }

        match serde_json::from_str::<RpcResponse>(line) {
            Ok(resp) => {
                // ARCH-4: 检查是否已取消
                let is_cancelled = {
                    let mut set = self.cancelled_ids.lock().await;
                    set.remove(&resp.id)
                };
                if is_cancelled {
                    info!(action = "rpc_cancelled_response_dropped", id = resp.id);
                    return;
                }

                let tx = {
                    let mut pending = self.pending.lock().await;
                    pending.remove(&resp.id)
                };
                if let Some(tx) = tx {
                    let _ = tx.send(resp);
                } else {
                    warn!(action = "rpc_orphan_response", id = resp.id, "No pending request for response");
                }
            }
            Err(e) => {
                error!(action = "rpc_parse_error", line = %line, error = %e);
            }
        }
    }
}
