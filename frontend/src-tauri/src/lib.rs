//! 应用装配层（M1-R4 重构后）
//!
//! 职责：状态注册 / 插件 / 托盘与窗口初始化 / Python 进程与桥接启动 / 命令注册 / 退出清理。
//! 业务模块：commands/*（Tauri 命令）、tray（托盘）、position（窗口定位）、
//! windows（多窗口管理）、python/*（进程与 RPC 桥）。

// Windows/MSVC 链接器输出（创建 .dll.lib 导入库等）会被 rustc 视为 warning，属正常噪音
#![allow(linker_messages)]

pub mod commands;
pub mod position;
pub mod python;
pub mod tray;
pub mod windows;

use commands::*;
use python::{bridge::PythonBridge, process::PythonProcess};
use std::sync::Arc;
use tauri::{AppHandle, Emitter, Manager};
use tokio::sync::RwLock;
use tracing::{error, info, warn};

/// 应用全局状态
pub struct AppState {
    pub python: Arc<RwLock<PythonProcess>>,
    pub bridge: Arc<RwLock<PythonBridge>>,
    /// 最近提醒事件缓存（bubble 窗口挂载后拉取，解决窗口创建晚于事件推送的竞态）
    pub recent_alerts: Arc<std::sync::Mutex<Vec<commands::alert::AlertEvent>>>,
}

impl AppState {
    pub fn new() -> Self {
        Self {
            python: Arc::new(RwLock::new(PythonProcess::new())),
            bridge: Arc::new(RwLock::new(PythonBridge::new())),
            recent_alerts: Arc::new(std::sync::Mutex::new(Vec::new())),
        }
    }
}

/// 安全终止 Python 子进程（提取为独立函数避免生命周期冲突）
fn kill_python_process(python_arc: Arc<RwLock<PythonProcess>>) {
    if let Ok(python) = python_arc.try_write() {
        if let Some(pid) = python.pid() {
            #[cfg(target_os = "windows")]
            {
                let _ = std::process::Command::new("taskkill")
                    .args(["/F", "/T", "/PID", &pid.to_string()])
                    .output();
            }
            #[cfg(not(target_os = "windows"))]
            {
                let _ = std::process::Command::new("kill")
                    .args(["-9", &pid.to_string()])
                    .output();
            }
            info!(action = "exit_cleanup", pid = pid, "Force-killed Python backend via PID");
        }
    }
}

/// 启动 Python 后端子进程并完成桥接接线（初始启动与看门狗重启共用）
async fn spawn_backend(app: &AppHandle) -> Result<(), String> {
    let state = app.state::<AppState>();
    let bridge_arc = state.bridge.clone();

    // 创建响应通道：stdout 读取 task -> bridge handle_response
    let (resp_tx, resp_rx) = tokio::sync::mpsc::unbounded_channel::<String>();
    let mut notify_rx;

    {
        let mut python = state.python.write().await;
        python.set_response_sender(resp_tx);

        if let Err(e) = python.start().await {
            error!(action = "python_spawn_failed", error = %e);
            #[cfg(any(target_os = "macos", target_os = "windows"))]
            {
                use tauri_plugin_notification::NotificationExt;
                let _ = app
                    .notification()
                    .builder()
                    .title("股大师启动失败")
                    .body(&format!("Python 后端启动失败: {}", e))
                    .show();
            }
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.emit("backend:error", &format!("Python 后端启动失败: {}", e));
            }
            return Err(e.to_string());
        }
        info!(action = "python_spawn_ok", "Python backend started");

        // 将 stdin sender attach 到 bridge，并订阅 Python 主动通知（alert.notify）
        notify_rx = {
            let mut bridge = bridge_arc.write().await;
            if let Some(sender) = python.get_sender() {
                bridge.attach_sender(sender);
            }
            bridge.subscribe_notifications()
        };
    }

    // 启动响应处理任务：将 Python stdout 的 JSON Lines 路由到 bridge
    let bridge_for_resp = bridge_arc.clone();
    tokio::spawn(async move {
        let mut resp_rx = resp_rx;
        while let Some(line) = resp_rx.recv().await {
            let bridge = bridge_for_resp.read().await;
            bridge.handle_response(&line).await;
        }
        info!(action = "bridge_resp_handler_exit", "Bridge response handler exited");
    });

    // ARCH-1: 通知转发任务：按 method 分发 Python 主动通知
    //   alert.notify → 系统通知 + 前端 quote:alert 事件 + 气泡窗
    //   quote.tick   → 前端 quote:tick 事件（桌宠当日盈亏实时更新）
    let app_handle_for_notify = app.clone();
    tokio::spawn(async move {
        while let Some(note) = notify_rx.recv().await {
            match note.method.as_str() {
                "alert.notify" => {
                    if let Some(alerts) = note.params.get("alerts").and_then(|v| v.as_array()) {
                        match serde_json::from_value::<Vec<commands::alert::AlertEvent>>(
                            serde_json::Value::Array(alerts.clone()),
                        ) {
                            Ok(events) => {
                                if !events.is_empty() {
                                    commands::alert::push_alert_events(&app_handle_for_notify, &events);
                                    // B1：提醒触发时自动弹出气泡窗（定位到宠物旁）
                                    let app_bubble = app_handle_for_notify.clone();
                                    tauri::async_runtime::spawn(async move {
                                        if let Err(e) = windows::show_bubble(&app_bubble).await {
                                            warn!(action = "alert_bubble_err", error = %e);
                                        }
                                    });
                                }
                            }
                            Err(e) => {
                                warn!(action = "alert_notify_parse_error", error = %e, "Failed to parse alert events from Python notification");
                            }
                        }
                    }
                }
                "quote.tick" => {
                    // 行情快照广播：载荷为 quotes 数组，转发到所有窗口（pet/panel/bubble）
                    if let Some(quotes) = note.params.get("quotes").and_then(|v| v.as_array()) {
                        let _ = app_handle_for_notify.emit("quote:tick", quotes);
                    } else {
                        warn!(action = "quote_tick_malformed", "quote.tick notification missing quotes array");
                    }
                }
                other => {
                    warn!(action = "unknown_notification", method = other, "Unhandled Python notification method");
                }
            }
        }
        info!(action = "notify_handler_exit", "Notification handler exited");
    });

    Ok(())
}

/// 后端看门狗：每 15s 心跳探测；连续 3 次失败判定后端死亡，自动 kill + 重启
fn spawn_watchdog(app: AppHandle) {
    use std::time::Duration;
    tauri::async_runtime::spawn(async move {
        let mut failures: u32 = 0;
        loop {
            tokio::time::sleep(Duration::from_secs(15)).await;
            let state = app.state::<AppState>();

            // 进程不存在（从未启动 / 已崩溃退出）→ 直接尝试启动
            {
                let python = state.python.read().await;
                if !python.is_running() {
                    drop(python);
                    warn!(action = "watchdog_process_gone", "Python process not running, attempting restart");
                    if let Err(e) = spawn_backend(&app).await {
                        error!(action = "watchdog_restart_fail", error = %e, "Backend restart failed");
                    } else {
                        info!(action = "watchdog_restart_ok", "Backend restarted (process gone)");
                    }
                    failures = 0;
                    continue;
                }
            }

            // 心跳探测：ping 失败计入连续失败次数
            let healthy = {
                let bridge = state.bridge.read().await;
                match bridge.ping().await {
                    Ok(_) => true,
                    Err(e) => {
                        warn!(action = "watchdog_ping_fail", error = %e, "Backend ping failed");
                        false
                    }
                }
            };
            if healthy {
                failures = 0;
                continue;
            }
            failures += 1;
            if failures < 3 {
                continue;
            }

            // 连续 3 次失败 → 判定僵尸，kill + 清场 + 重启
            error!(action = "watchdog_restart", failures, "Backend unresponsive (3 consecutive ping failures), killing and restarting");
            {
                let mut python = state.python.write().await;
                let _ = python.stop().await;
            }
            {
                let mut bridge = state.bridge.write().await;
                bridge.reset().await;
            }
            if let Err(e) = spawn_backend(&app).await {
                error!(action = "watchdog_restart_fail", error = %e, "Backend restart failed");
            } else {
                info!(action = "watchdog_restart_ok", "Backend restarted (unresponsive)");
            }
            failures = 0;
        }
    });
}

/// Tauri 应用入口
pub fn run() -> Result<(), Box<dyn std::error::Error>> {
    let app = tauri::Builder::default()
        .manage(AppState::new())
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_notification::init())
        .plugin(tauri_plugin_positioner::init())
        // 单实例插件：阻止多实例启动导致的端口/管道冲突；二次启动时聚焦已有主窗口
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.show();
                let _ = window.set_focus();
            }
        }))
        .setup(|app| {
            info!(action = "tauri_setup", "Tauri application setup started");

            // 创建系统托盘
            #[cfg(any(target_os = "macos", target_os = "windows"))]
            tray::setup_tray(app.handle())?;

            // 桌宠小窗口定位到默认位置（右下角）并显示
            if let Some(window) = app.get_webview_window("main") {
                position::position_pet_window_default(&window);
                let _ = window.show();
                let _ = window.set_focus();
            }

            // 启动 Python 子进程（spawn_backend 内含完整接线）
            tauri::async_runtime::block_on(async {
                let _ = spawn_backend(app.handle()).await;
            });

            // 启动看门狗：后端僵尸 / 崩溃时自动 kill + 重启
            spawn_watchdog(app.handle().clone());

            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            // 持仓命令
            portfolio_list,
            portfolio_add,
            portfolio_remove,
            // 行情命令
            quote_get,
            quote_subscribe,
            quote_refresh,
            quote_resolve,
            kline_get,
            // 提醒命令（ARCH-1）
            alert_list,
            alert_add,
            alert_remove,
            alert_notify,
            bubble_recent_alerts,
            // Skill 命令
            skill_execute,
            skill_cancel,
            // 通用 Python RPC 转发（chat_history.* 等）
            python_call,
            // 配置命令
            config_get,
            config_set,
            // 窗口命令
            window_set_position,
            window_edge_snap,
            get_cursor_position,
            set_cursor_passthrough,
            get_window_geometry,
            get_monitors,
            set_window_bounds,
            // 多窗口管理（B1）
            panel_toggle,
            chat_toggle,
            chat_open,
            chat_close,
            bubble_show,
            bubble_dismiss,
            sub_windows_close,
        ])
        .build(tauri::generate_context!())
        .map_err(|e| Box::new(e) as Box<dyn std::error::Error>)?;

    // 运行应用并监听生命周期事件
    app.run(|app_handle, event| {
        if let tauri::RunEvent::ExitRequested { .. } = event {
            info!(action = "exit_requested", "Application exit requested, performing cleanup");
            // 安全网：同步层尽力终止 Python 进程
            let state = app_handle.state::<AppState>();
            kill_python_process(state.python.clone());
            // 不调用 api.prevent_exit()，允许正常退出
        }
    });

    Ok(())
}
