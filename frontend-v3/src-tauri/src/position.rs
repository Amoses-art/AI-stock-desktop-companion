//! 桌宠窗口定位与可见性（M1-R4 从 lib.rs 拆出）

use tauri::WebviewWindow;
use tracing::{info, warn};

/// 桌宠窗口逻辑尺寸（与 tauri.conf.json 保持一致，逻辑像素）
pub const PET_WIN_W: f64 = 240.0;
pub const PET_WIN_H: f64 = 220.0;

/// 切换主窗口可见性
pub fn toggle_window_visibility(window: &WebviewWindow) {
    match window.is_visible() {
        Ok(true) => {
            let _ = window.hide();
        }
        Ok(false) => {
            let _ = window.show();
            let _ = window.set_focus();
        }
        Err(e) => {
            warn!(action = "toggle_visibility", error = %e);
        }
    }
}

/// 将桌宠小窗口定位到主显示器右下角默认位置（物理像素计算）
pub fn position_pet_window_default(window: &WebviewWindow) -> Option<(i32, i32)> {
    let monitor = match window.primary_monitor() {
        Ok(Some(m)) => m,
        _ => {
            warn!(action = "position_default", "No primary monitor found");
            return None;
        }
    };

    let monitor_size = monitor.size();
    let scale = window.scale_factor().unwrap_or(1.0);
    let mw = monitor_size.width as i32;
    let mh = monitor_size.height as i32;

    // 右侧留白 40 逻辑像素，底部留白 80 逻辑像素（为任务栏预留）
    let x = mw - ((40.0 + PET_WIN_W) * scale) as i32;
    let y = mh - ((80.0 + PET_WIN_H) * scale) as i32;

    let _ = window.set_size(tauri::LogicalSize::new(PET_WIN_W, PET_WIN_H));
    let _ = window.set_position(tauri::PhysicalPosition::new(x.max(0), y.max(0)));

    info!(action = "position_default", x = x, y = y, scale = scale, "Pet window positioned to bottom-right default");
    Some((x.max(0), y.max(0)))
}
