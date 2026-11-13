use serde::Serialize;
use tauri::{AppHandle, Manager, PhysicalPosition, PhysicalSize, WebviewWindow};

use crate::windows::{self, BubblePlacement};

/// 显示器矩形（物理像素，虚拟桌面坐标系）
#[derive(Serialize)]
pub struct MonitorRect {
    pub x: i32,
    pub y: i32,
    pub w: i32,
    pub h: i32,
}

/// 窗口几何信息（物理像素 + 缩放比）
#[derive(Serialize)]
pub struct WindowGeometry {
    pub x: i32,
    pub y: i32,
    pub w: i32,
    pub h: i32,
    pub scale: f64,
}

/// 设置窗口位置（物理像素，虚拟桌面坐标系，支持多屏/负坐标）
#[tauri::command(rename_all = "snake_case")]
pub async fn window_set_position(
    window: WebviewWindow,
    x: i32,
    y: i32,
) -> Result<(), String> {
    window
        .set_position(PhysicalPosition::new(x, y))
        .map_err(|e| e.to_string())
}

/// 获取全局鼠标坐标（物理像素，相对桌面左上角，多屏下可为负）
#[tauri::command(rename_all = "snake_case")]
pub async fn get_cursor_position(window: WebviewWindow) -> Result<(i32, i32), String> {
    // WebviewWindow::cursor_position 返回的是相对桌面左上角的全局物理坐标，
    // 不要再加窗口偏移
    let pos = window
        .cursor_position()
        .map_err(|e| e.to_string())?;
    Ok((pos.x.round() as i32, pos.y.round() as i32))
}

/// 设置鼠标穿透（true = 忽略鼠标事件，点击穿透到桌面）
#[tauri::command(rename_all = "snake_case")]
pub async fn set_cursor_passthrough(window: WebviewWindow, passthrough: bool) -> Result<(), String> {
    window
        .set_ignore_cursor_events(passthrough)
        .map_err(|e| e.to_string())
}

/// 获取当前窗口几何信息（物理像素）+ 缩放比
#[tauri::command(rename_all = "snake_case")]
pub async fn get_window_geometry(window: WebviewWindow) -> Result<WindowGeometry, String> {
    let pos = window.outer_position().map_err(|e| e.to_string())?;
    let size = window.outer_size().map_err(|e| e.to_string())?;
    let scale = window.scale_factor().map_err(|e| e.to_string())?;
    Ok(WindowGeometry {
        x: pos.x,
        y: pos.y,
        w: size.width as i32,
        h: size.height as i32,
        scale,
    })
}

/// 获取所有显示器的矩形（物理像素，虚拟桌面坐标系）
#[tauri::command(rename_all = "snake_case")]
pub async fn get_monitors(window: WebviewWindow) -> Result<Vec<MonitorRect>, String> {
    let monitors = window.available_monitors().map_err(|e| e.to_string())?;
    let mut result = Vec::with_capacity(monitors.len());
    for m in monitors {
        let pos = m.position();
        let size = m.size();
        result.push(MonitorRect {
            x: pos.x,
            y: pos.y,
            w: size.width as i32,
            h: size.height as i32,
        });
    }
    // 空列表防护：显示器拓扑变化瞬间可能返回空，回退主显示器
    if result.is_empty() {
        if let Ok(Some(m)) = window.primary_monitor() {
            let pos = m.position();
            let size = m.size();
            result.push(MonitorRect {
                x: pos.x,
                y: pos.y,
                w: size.width as i32,
                h: size.height as i32,
            });
        }
    }
    Ok(result)
}

/// 设置窗口位置和尺寸（物理像素），用于面板展开/收起时动态调整窗口包围盒
#[tauri::command(rename_all = "snake_case")]
pub async fn set_window_bounds(
    window: WebviewWindow,
    x: i32,
    y: i32,
    w: i32,
    h: i32,
) -> Result<(), String> {
    window
        .set_position(PhysicalPosition::new(x, y))
        .map_err(|e| e.to_string())?;
    window
        .set_size(PhysicalSize::new(w.max(1) as u32, h.max(1) as u32))
        .map_err(|e| e.to_string())?;
    Ok(())
}

/// 边缘吸附检测（物理像素一致）
/// 返回检测结果，由前端决定如何吸附/隐藏：
/// - edge: "left"/"right"/"top"/"bottom"/"none"
/// - monitor: 检测所用显示器矩形（虚拟桌面坐标）
#[derive(Serialize)]
pub struct EdgeSnapResult {
    pub edge: String,
    pub monitor: MonitorRect,
}

#[tauri::command(rename_all = "snake_case")]
pub async fn window_edge_snap(
    window: WebviewWindow,
    threshold: i32,
) -> Result<EdgeSnapResult, String> {
    let monitor = window
        .current_monitor()
        .map_err(|e| e.to_string())?
        .ok_or("No monitor found")?;

    let monitor_size = monitor.size();
    let monitor_pos = monitor.position();
    let window_pos = window.outer_position().map_err(|e| e.to_string())?;
    let window_size = window.outer_size().map_err(|e| e.to_string())?;

    let mx = monitor_pos.x;
    let my = monitor_pos.y;
    let mw = monitor_size.width as i32;
    let mh = monitor_size.height as i32;
    let wx = window_pos.x;
    let wy = window_pos.y;
    let ww = window_size.width as i32;
    let wh = window_size.height as i32;

    let near_left = wx - mx < threshold;
    let near_right = (mx + mw) - (wx + ww) < threshold;
    let near_top = wy - my < threshold;
    let near_bottom = (my + mh) - (wy + wh) < threshold;

    let edge = if near_left {
        "left"
    } else if near_right {
        "right"
    } else if near_top {
        "top"
    } else if near_bottom {
        "bottom"
    } else {
        "none"
    };

    Ok(EdgeSnapResult {
        edge: edge.to_string(),
        monitor: MonitorRect {
            x: mx,
            y: my,
            w: mw,
            h: mh,
        },
    })
}

// ---------- 多窗口管理命令（B1） ----------

/// 切换持仓面板窗口（宠物左侧，空间不足放右侧）
#[tauri::command(rename_all = "snake_case")]
pub async fn panel_toggle(app: AppHandle) -> Result<bool, String> {
    windows::toggle_panel(&app).await
}

/// 切换 AI 对话窗口（返回切换后是否打开）— 与 panel_toggle 语义一致
/// 前端 PetView 的 chatToggle() 调用此命令；缺失会导致 invoke 报
/// "command chat_toggle not found"，AI 弹窗点击无任何反应。
#[tauri::command(rename_all = "snake_case")]
pub async fn chat_toggle(app: AppHandle) -> Result<bool, String> {
    if app.get_webview_window(crate::windows::CHAT_LABEL).is_some() {
        // 已存在：关闭（下次重建以重算位置）
        windows::close_chat(&app).await?;
        Ok(false)
    } else {
        // 不存在：创建并显示
        windows::open_chat(&app).await?;
        Ok(true)
    }
}

/// 打开 AI 对话窗口（宠物右侧；AI 层 ready 后允许调用）
#[tauri::command(rename_all = "snake_case")]
pub async fn chat_open(app: AppHandle) -> Result<(), String> {
    windows::open_chat(&app).await
}

/// 关闭 AI 对话窗口
#[tauri::command(rename_all = "snake_case")]
pub async fn chat_close(app: AppHandle) -> Result<(), String> {
    windows::close_chat(&app).await
}

/// 显示提醒气泡（自动定位：宠物上方/下方翻转 + 工作区 clamp）
#[tauri::command(rename_all = "snake_case")]
pub async fn bubble_show(app: AppHandle) -> Result<BubblePlacement, String> {
    windows::show_bubble(&app).await
}

/// 关闭提醒气泡
#[tauri::command(rename_all = "snake_case")]
pub async fn bubble_dismiss(app: AppHandle) -> Result<(), String> {
    windows::dismiss_bubble(&app).await
}

/// 一次性关闭所有子窗口（panel / chat / bubble）
/// 托盘 reset/toggle、pet 边缘吸附时调用，避免子窗口悬空
#[tauri::command(rename_all = "snake_case")]
pub async fn sub_windows_close(app: AppHandle) -> Result<(), String> {
    for label in ["panel", "chat", "bubble"] {
        if let Some(win) = app.get_webview_window(label) {
            let _ = win.close();
        }
    }
    Ok(())
}
