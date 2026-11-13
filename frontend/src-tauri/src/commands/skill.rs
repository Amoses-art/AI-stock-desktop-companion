use serde::{Deserialize, Serialize};
use serde_json::Value;
use tauri::State;

use crate::AppState;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SkillInput {
    pub message: Option<String>,
    pub stock_code: Option<String>,
    pub stock_name: Option<String>,
    pub board_code: Option<String>,
    pub market_env_score: Option<f64>,
    pub request_id: Option<u64>,
    pub session_id: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SkillOutput {
    pub skill_name: String,
    pub result: Value,
    pub warnings: Vec<String>,
    pub execution_time_ms: u64,
    pub request_id: u64,
}

#[tauri::command(rename_all = "snake_case")]
pub async fn skill_execute(
    state: State<'_, AppState>,
    skill_name: String,
    input: SkillInput,
) -> Result<SkillOutput, String> {
    let start = std::time::Instant::now();
    let bridge = state.bridge.read().await;
    let (req_id, result) = bridge
        .call(
            "skill.execute",
            serde_json::json!({"skill_name": skill_name, "input": input}),
        )
        .await;

    let result = result.map_err(|e| e.to_string())?;
    let execution_time_ms = start.elapsed().as_millis() as u64;

    // Python RPC 返回 { "result": { "reply": "...", "intent": "...", "data": {...} } }
    let inner = result.get("result").cloned().unwrap_or(result);

    Ok(SkillOutput {
        skill_name,
        result: inner,
        warnings: vec![],
        execution_time_ms,
        request_id: req_id,
    })
}

/// ARCH-4: RPC 请求取消
#[tauri::command(rename_all = "snake_case")]
pub async fn skill_cancel(
    state: State<'_, AppState>,
    request_id: u64,
) -> Result<(), String> {
    let bridge = state.bridge.read().await;
    bridge.cancel_request(request_id).await;
    Ok(())
}
