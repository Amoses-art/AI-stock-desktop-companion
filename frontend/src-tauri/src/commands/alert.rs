use serde::{Deserialize, Serialize};
use tauri::{Emitter, Manager, State};

use crate::AppState;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AlertRule {
    pub id: i64,
    pub portfolio_id: i64,
    pub threshold_percent: f64,
    pub direction: String,
    pub is_active: bool,
    pub cooldown_minutes: i32,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct NewAlertRule {
    pub portfolio_id: i64,
    pub threshold_percent: f64,
    pub direction: String,
    pub cooldown_minutes: i32,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AlertEvent {
    pub symbol: String,
    pub name: String,
    pub current_price: f64,
    /// "up" | "down" | "sudden"
    pub trigger_type: String,
    pub triggered_at: i64,
    /// 扩展字段（契约允许新增）：涨跌幅（%）
    #[serde(default)]
    pub percent: f64,
    /// 扩展字段：系统通知文案
    #[serde(default)]
    pub message: String,
}

#[tauri::command(rename_all = "snake_case")]
pub async fn alert_list(state: State<'_, AppState>) -> Result<Vec<AlertRule>, String> {
    let bridge = state.bridge.read().await;
    let (_, result) = bridge.call("alert.list", serde_json::json!({})).await;
    result
        .map_err(|e| e.to_string())
        .and_then(|v| serde_json::from_value(v).map_err(|e| e.to_string()))
}

#[tauri::command(rename_all = "snake_case")]
pub async fn alert_add(
    state: State<'_, AppState>,
    rule: NewAlertRule,
) -> Result<AlertRule, String> {
    let bridge = state.bridge.read().await;
    let (_, result) = bridge
        .call("alert.add", serde_json::to_value(rule).map_err(|e| e.to_string())?)
        .await;
    result
        .map_err(|e| e.to_string())
        .and_then(|v| serde_json::from_value(v).map_err(|e| e.to_string()))
}

#[tauri::command(rename_all = "snake_case")]
pub async fn alert_remove(state: State<'_, AppState>, id: i64) -> Result<(), String> {
    let bridge = state.bridge.read().await;
    let (_, result) = bridge.call("alert.remove", serde_json::json!({"id": id})).await;
    result.map_err(|e| e.to_string())?;
    Ok(())
}

/// 最近提醒事件缓存上限（bubble 窗口挂载后拉取展示）
const RECENT_ALERTS_MAX: usize = 10;

/// ARCH-1: 推送提醒事件到系统通知 + 前端事件（双通道）
/// 前端契约（PRD v3.1 §4.2）：quote:alert 事件载荷为 AlertEvent 数组，广播到全部窗口
/// 调用方：alert_notify 命令（显式触发）与 lib.rs 通知转发任务（Python alert.notify 推送）
pub fn push_alert_events<R: tauri::Runtime>(app: &tauri::AppHandle<R>, events: &[AlertEvent]) {
    if events.is_empty() {
        return;
    }

    // 1. 系统通知（Tauri Notification，逐条）
    #[cfg(any(target_os = "macos", target_os = "windows"))]
    {
        use tauri_plugin_notification::NotificationExt;
        for event in events {
            let _ = app
                .notification()
                .builder()
                .title("股大师提醒")
                .body(&event.message)
                .show();
        }
    }

    // 2. 前端事件推送：数组载荷一次性广播（main/panel/chat/bubble 均可接收）
    let _ = app.emit("quote:alert", events);

    // 3. 托盘图标切换为提醒态（用户左键点击托盘后恢复）
    if let Some(tray) = app.tray_by_id("main-tray") {
        if let Some(icon) = crate::tray::tray_image(true) {
            let _ = tray.set_icon(Some(icon));
        }
    }

    // 4. 写入最近事件缓存（bubble 窗口创建晚于事件推送，挂载后拉取，规避竞态）
    if let Some(state) = app.try_state::<AppState>() {
        if let Ok(mut cache) = state.recent_alerts.lock() {
            cache.extend(events.iter().cloned());
            let len = cache.len();
            if len > RECENT_ALERTS_MAX {
                cache.drain(0..len - RECENT_ALERTS_MAX);
            }
        }
    }

    tracing::info!(action = "alert_push", count = events.len(), "Alert events pushed");
}

/// 提醒气泡窗口拉取最近提醒事件（挂载时调用，解决窗口创建竞态）
#[tauri::command(rename_all = "snake_case")]
pub async fn bubble_recent_alerts(state: State<'_, AppState>) -> Result<Vec<AlertEvent>, String> {
    let cache = state
        .recent_alerts
        .lock()
        .map_err(|e| e.to_string())?
        .clone();
    Ok(cache)
}

/// ARCH-1: 接收提醒通知，推送系统通知 + 前端事件
#[tauri::command(rename_all = "snake_case")]
pub async fn alert_notify(
    app: tauri::AppHandle,
    _state: State<'_, AppState>,
    events: Vec<AlertEvent>,
) -> Result<(), String> {
    push_alert_events(&app, &events);
    Ok(())
}
