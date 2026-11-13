use tracing::warn;
use serde::{Deserialize, Serialize};
use tauri::{Emitter, State};

use crate::AppState;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PortfolioItem {
    pub id: i64,
    pub symbol: String,
    pub name: String,
    pub market: String,
    pub asset_type: String,
    pub quantity: f64,
    pub cost_price: f64,
    pub currency: String,
    #[serde(default)]
    pub current_price: f64,
    #[serde(default)]
    pub change_percent: f64,
    #[serde(default)]
    pub pnl_amount: f64,
    #[serde(default)]
    pub pnl_percent: f64,
    /// 代码无法匹配市场/类型 或 查询不到行情 → 前端【实时股价】列提示"代码错误"
    #[serde(default)]
    pub quote_error: bool,
}

#[tauri::command(rename_all = "snake_case")]
pub async fn debug_add_test(test: String) -> Result<String, String> {
    warn!("[DEBUG] debug_add_test received! test='{}'", test);
    Ok(format!("echo: {}", test))
}

#[tauri::command(rename_all = "snake_case")]
pub async fn portfolio_list(state: State<'_, AppState>) -> Result<Vec<PortfolioItem>, String> {
    warn!("[DEBUG] portfolio_list START");
    let bridge = state.bridge.read().await;
    let (_, result) = bridge.call("portfolio.list", serde_json::json!({})).await;
    result
        .map_err(|e| e.to_string())
        .and_then(|v| serde_json::from_value(v).map_err(|e| e.to_string()))
}

#[tauri::command(rename_all = "snake_case")]
pub async fn portfolio_add(
    state: State<'_, AppState>,
    app: tauri::AppHandle,
    symbol: String,
    name: String,
    market: String,
    asset_type: String,
    quantity: f64,
    cost_price: f64,
    currency: String,
    alert_threshold: Option<f64>,
) -> Result<PortfolioItem, String> {
    warn!("[DEBUG] portfolio_add START symbol={} market={} asset_type={} qty={} cost={} threshold={:?}",
        symbol, market, asset_type, quantity, cost_price, alert_threshold);
    let bridge = state.bridge.read().await;
    let params = serde_json::json!({
        "symbol": symbol,
        "name": name,
        "market": market,
        "asset_type": asset_type,
        "quantity": quantity,
        "cost_price": cost_price,
        "currency": currency,
        "alert_threshold": alert_threshold,
    });
    warn!("[DEBUG] portfolio_add params={}", params);
    let (_, result) = bridge.call("portfolio.add", params).await;
    warn!("[DEBUG] portfolio_add result_ok={} err={:?}", result.is_ok(), result.as_ref().err());
    let item: PortfolioItem = result
        .map_err(|e| e.to_string())
        .and_then(|v| serde_json::from_value(v).map_err(|e| e.to_string()))?;
    // 跨窗口同步：桌宠当日盈亏 / 面板清单立即刷新
    let _ = app.emit("portfolio:changed", serde_json::json!({}));
    Ok(item)
}

#[tauri::command(rename_all = "snake_case")]
pub async fn portfolio_remove(state: State<'_, AppState>, app: tauri::AppHandle, id: i64) -> Result<(), String> {
    let bridge = state.bridge.read().await;
    let (_, result) = bridge
        .call("portfolio.remove", serde_json::json!({"id": id}))
        .await;
    result.map_err(|e| e.to_string())?;
    // 跨窗口同步
    let _ = app.emit("portfolio:changed", serde_json::json!({}));
    Ok(())
}