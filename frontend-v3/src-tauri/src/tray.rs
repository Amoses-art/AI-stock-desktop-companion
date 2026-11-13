//! 系统托盘：图标（常规/提醒态）+ 菜单 + 事件处理（M1-R4 从 lib.rs 拆出）

use tauri::{Emitter, Manager};
use tracing::{info, warn};

use crate::position::{position_pet_window_default, PET_WIN_H, PET_WIN_W};
use crate::windows;

/// 托盘图标：常规 / 提醒态（切图 v1-rev1，编译期嵌入）
const TRAY_ICON: &[u8] = include_bytes!("../icons/tray.png");
const TRAY_ALERT_ICON: &[u8] = include_bytes!("../icons/tray-alert.png");

/// 解析托盘图标（PNG → RGBA；解析失败返回 None，调用方回退默认图标）
pub fn tray_image(alert: bool) -> Option<tauri::image::Image<'static>> {
    let bytes = if alert { TRAY_ALERT_ICON } else { TRAY_ICON };
    let img = image::load_from_memory_with_format(bytes, image::ImageFormat::Png).ok()?;
    let rgba = img.to_rgba8();
    let (w, h) = rgba.dimensions();
    Some(tauri::image::Image::new_owned(rgba.into_raw(), w, h))
}

/// 构建系统托盘右键菜单
fn build_tray_menu(
    app: &tauri::AppHandle,
) -> Result<tauri::menu::Menu<tauri::Wry>, Box<dyn std::error::Error>> {
    use tauri::menu::{MenuBuilder, MenuItemBuilder, PredefinedMenuItem};

    let toggle = MenuItemBuilder::with_id("toggle", "显示/隐藏").build(app)?;
    let reset = MenuItemBuilder::with_id("reset", "重置位置").build(app)?;
    let settings = MenuItemBuilder::with_id("settings", "设置").build(app)?;
    let separator = PredefinedMenuItem::separator(app)?;
    let quit = MenuItemBuilder::with_id("quit", "退出").build(app)?;

    let menu = MenuBuilder::new(app)
        .item(&toggle)
        .item(&reset)
        .item(&settings)
        .item(&separator)
        .item(&quit)
        .build()?;

    Ok(menu)
}

/// 创建系统托盘（lib.rs setup 中调用；macOS/Windows 生效）
#[cfg(any(target_os = "macos", target_os = "windows"))]
pub fn setup_tray(
    app: &tauri::AppHandle,
) -> Result<(), Box<dyn std::error::Error>> {
    use tauri::tray::{TrayIconBuilder, MouseButton, TrayIconEvent};

    let menu = build_tray_menu(app)?;

    let mut tray_builder = TrayIconBuilder::with_id("main-tray")
        .tooltip("股大师")
        .menu(&menu)
        .on_menu_event(|app, event| {
            match event.id.as_ref() {
                "toggle" => {
                    if let Some(pet) = app.get_webview_window("main") {
                        match pet.is_visible() {
                            Ok(true) => {
                                // 隐藏：先关闭所有子窗口，再隐藏 pet
                                for label in ["panel", "chat", "bubble"] {
                                    if let Some(win) = app.get_webview_window(label) {
                                        let _ = win.close();
                                    }
                                }
                                let _ = pet.hide();
                            }
                            Ok(false) => {
                                let _ = pet.show();
                                let _ = pet.set_focus();
                            }
                            Err(e) => warn!(action = "tray_toggle", error = %e),
                        }
                    }
                }
                "reset" => {
                    // 先关闭所有子窗口（避免 pet 移走后 panel 悬空）
                    for label in ["panel", "chat", "bubble"] {
                        if let Some(win) = app.get_webview_window(label) {
                            let _ = win.close();
                        }
                    }
                    if let Some(window) = app.get_webview_window("main") {
                        if let Some((x, y)) = position_pet_window_default(&window) {
                            let _ = window.emit(
                                "pet-reset",
                                serde_json::json!({
                                    "x": x,
                                    "y": y,
                                    "w": (PET_WIN_W * window.scale_factor().unwrap_or(1.0)) as i32,
                                    "h": (PET_WIN_H * window.scale_factor().unwrap_or(1.0)) as i32,
                                }),
                            );
                        }
                    }
                }
                "settings" => {
                    // B1：托盘设置 → 打开持仓面板窗口
                    let app_handle = app.clone();
                    tauri::async_runtime::spawn(async move {
                        if let Err(e) = windows::toggle_panel(&app_handle).await {
                            warn!(action = "tray_settings", error = %e);
                        }
                    });
                }
                "quit" => {
                    info!(action = "tray_quit", "User requested quit from tray menu");
                    let app_handle = app.clone();
                    let state = app.state::<crate::AppState>();
                    let python_arc = state.python.clone();
                    // 在异步任务中执行清理并退出
                    tauri::async_runtime::spawn(async move {
                        info!(action = "cleanup_start", "Stopping Python backend...");
                        let mut python = python_arc.write().await;
                        if let Err(e) = python.stop().await {
                            tracing::error!(action = "cleanup_python_err", error = %e);
                        }
                        info!(action = "cleanup_done", "Exiting application");
                        app_handle.exit(0);
                    });
                }
                _ => {}
            }
        })
        .on_tray_icon_event(|tray, event| {
            if let TrayIconEvent::Click { button: MouseButton::Left, .. } = event {
                let app = tray.app_handle();
                if let Some(window) = app.get_webview_window("main") {
                    let _ = window.show();
                    let _ = window.set_focus();
                }
                // 左键点击视为已查看提醒：托盘图标恢复常规态
                if let Some(icon) = tray_image(false) {
                    let _ = tray.set_icon(Some(icon));
                }
            }
        });

    // 优先使用切图托盘图标，解析失败回退应用默认图标
    if let Some(icon) = tray_image(false).or_else(|| app.default_window_icon().cloned()) {
        tray_builder = tray_builder.icon(icon);
    }

    tray_builder.build(app)?;
    Ok(())
}
