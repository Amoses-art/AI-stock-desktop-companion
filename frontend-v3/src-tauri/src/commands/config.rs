use serde_json::Value;
use tauri::State;

use crate::AppState;

#[tauri::command(rename_all = "snake_case")]
pub async fn config_get(state: State<'_, AppState>) -> Result<Value, String> {
    let bridge = state.bridge.read().await;
    let (_, result) = bridge.call("config.get", serde_json::json!({})).await;
    result.map_err(|e| e.to_string())
}

#[tauri::command(rename_all = "snake_case")]
pub async fn config_set(
    state: State<'_, AppState>,
    key: String,
    value: serde_json::Value,
) -> Result<(), String> {
    let bridge = state.bridge.read().await;
    let (_, result) = bridge
        .call("config.set", serde_json::json!({"key": key, "value": value}))
        .await;
    result.map_err(|e| e.to_string())?;
    Ok(())
}
