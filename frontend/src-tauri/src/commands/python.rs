//! 通用 Python RPC 转发命令
//! 允许前端调用任意已在 Python bridge 注册的 method，
//! 免去 Rust 端为每个新 RPC 方法写 wrapper 的重复劳动。

use serde::Deserialize;
use serde_json::{Value, json};
use tauri::State;

use crate::AppState;

#[derive(Debug, Clone, Deserialize)]
pub struct PythonCallInput {
    pub method: String,
    pub params: Option<Value>,
}

/// 通用 Python RPC 转发
///
/// 前端：invoke("python_call", { method: "chat_history.list", params: { session_id: "default", limit: 50 } })
/// 后端：bridge.call("chat_history.list", json!({ session_id: "default", limit: 50 }))
#[tauri::command]
pub async fn python_call(
    state: State<'_, AppState>,
    input: PythonCallInput,
) -> Result<Value, String> {
    tracing::info!(method = %input.method, "python_call invoked");
    let bridge = state.bridge.read().await;
    let params = input.params.unwrap_or(json!({}));
    let (_req_id, result) = bridge
        .call(&input.method, params)
        .await;
    match result {
        Ok(v) => {
            // Python RPC 返回格式: {"status":"ok","result":...} —— 取 result
            Ok(v.get("result").cloned().unwrap_or(v))
        }
        Err(e) => Err(e.to_string()),
    }
}
