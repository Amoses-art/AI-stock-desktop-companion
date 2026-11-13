use serde::{Deserialize, Serialize};
use tauri::State;

use crate::AppState;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct QuoteData {
    pub symbol: String,
    pub name: String,
    pub market: String,
    pub asset_type: String,
    pub current_price: f64,
    pub pre_close: f64,
    pub open_price: f64,
    pub high_price: f64,
    pub low_price: f64,
    pub change_amount: f64,
    pub change_percent: f64,
    pub volume: f64,
    pub turnover: f64,
    /// 数据源快照时间（yyyymmddHHMMSS；M2-4 收盘态展示）
    #[serde(default)]
    pub timestamp: Option<String>,
}

#[tauri::command(rename_all = "snake_case")]
pub async fn quote_get(
    state: State<'_, AppState>,
    symbol: String,
    market: String,
) -> Result<QuoteData, String> {
    let bridge = state.bridge.read().await;
    let (_, result) = bridge
        .call("quote.get", serde_json::json!({"symbol": symbol, "market": market}))
        .await;
    result
        .map_err(|e| e.to_string())
        .and_then(|v| serde_json::from_value(v).map_err(|e| e.to_string()))
}

#[tauri::command(rename_all = "snake_case")]
pub async fn quote_subscribe(
    state: State<'_, AppState>,
    symbols: Vec<String>,
) -> Result<serde_json::Value, String> {
    let bridge = state.bridge.read().await;
    let (_, result) = bridge
        .call("quote.subscribe", serde_json::json!({"symbols": symbols}))
        .await;
    result.map_err(|e| e.to_string())
}

#[tauri::command(rename_all = "snake_case")]
pub async fn quote_refresh(
    state: State<'_, AppState>,
    symbols: Vec<String>,
    force: Option<bool>,
) -> Result<Vec<QuoteData>, String> {
    let bridge = state.bridge.read().await;
    let (_, result) = bridge
        .call(
            "quote.refresh",
            serde_json::json!({"symbols": symbols, "force": force.unwrap_or(true)}),
        )
        .await;
    result.map_err(|e| e.to_string())
        .and_then(|v| serde_json::from_value(v).map_err(|e| e.to_string()))
}

/// 解析证券代码 → 名称/市场（添加持仓自动填充 + 校验）
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct QuoteResolve {
    pub symbol: String,
    pub name: String,
    pub market: String,
    pub asset_type: String,
    #[serde(default)]
    pub current_price: f64,
    #[serde(default)]
    pub pre_close: f64,
}

#[tauri::command(rename_all = "snake_case")]
pub async fn quote_resolve(
    state: State<'_, AppState>,
    symbol: String,
    asset_type: Option<String>,
) -> Result<QuoteResolve, String> {
    let bridge = state.bridge.read().await;
    let (_, result) = bridge
        .call(
            "quote.resolve",
            serde_json::json!({"symbol": symbol, "asset_type": asset_type.unwrap_or_else(|| "stock".to_string())}),
        )
        .await;
    result
        .map_err(|e| e.to_string())
        .and_then(|v| serde_json::from_value(v).map_err(|e| e.to_string()))
}

/// 分时K线点
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct KlinePoint {
    pub t: String,
    pub price: f64,
    #[serde(default)]
    pub vol: f64,
}

/// 分时K线序列（单日）
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct KlineSeries {
    pub date: String,
    pub points: Vec<KlinePoint>,
}

/// 分时K线响应
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct KlineData {
    pub symbol: String,
    pub market: String,
    pub days: i64,
    #[serde(default)]
    pub pre_close: f64,
    pub series: Vec<KlineSeries>,
}

#[tauri::command(rename_all = "snake_case")]
pub async fn kline_get(
    state: State<'_, AppState>,
    symbol: String,
    market: Option<String>,
    asset_type: Option<String>,
    days: Option<i64>,
) -> Result<KlineData, String> {
    let bridge = state.bridge.read().await;
    let (_, result) = bridge
        .call(
            "kline.get",
            serde_json::json!({
                "symbol": symbol,
                "market": market,
                "asset_type": asset_type.unwrap_or_else(|| "stock".to_string()),
                "days": days.unwrap_or(1),
            }),
        )
        .await;
    result
        .map_err(|e| e.to_string())
        .and_then(|v| serde_json::from_value(v).map_err(|e| e.to_string()))
}
