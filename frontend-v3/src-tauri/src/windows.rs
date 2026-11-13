//! 多窗口管理器
//!
//! 参照 ipet 三窗口模型：宠物窗（main）/ 面板窗（panel）/ 对话窗（chat）
//! + 提醒气泡窗（bubble）。窗口由 Rust 运行时创建与定位，
//! 前端通过命令请求开合，通过事件同步状态。
//!
//! 定位算法（气泡窗，参照 ipet bubble-window）：
//! - 默认显示在宠物上方；宠物贴近屏幕顶部时自动翻转到下方
//! - 水平方向 clamp 到显示器工作区内
//! - 尾巴锚点 = 宠物中心 X 相对气泡左缘的偏移（前端据此渲染尾巴）

use tauri::{
    AppHandle, Manager, Monitor, PhysicalPosition, WebviewWindow, WebviewWindowBuilder,
};
use tracing::info;

/// 窗口 label 常量
pub const PET_LABEL: &str = "main";
pub const PANEL_LABEL: &str = "panel";
pub const CHAT_LABEL: &str = "chat";
pub const BUBBLE_LABEL: &str = "bubble";

/// 窗口逻辑尺寸
const PANEL_W: f64 = 460.0;
const PANEL_H: f64 = 540.0;
const CHAT_W: f64 = 380.0;
const CHAT_H: f64 = 560.0;
const BUBBLE_W: f64 = 340.0;
const BUBBLE_H: f64 = 200.0;
const GAP: f64 = 12.0; // 气泡与宠物的间距（逻辑像素）
const MARGIN: f64 = 8.0; // 显示器边缘安全边距（逻辑像素）

/// 创建窗口（若已存在则直接返回）
fn create_window(
    app: &AppHandle,
    label: &str,
    title: &str,
    view: &str,
    w: f64,
    h: f64,
) -> Result<WebviewWindow, String> {
    if let Some(win) = app.get_webview_window(label) {
        return Ok(win);
    }
    let url = format!("index.html?view={}", view);
    WebviewWindowBuilder::new(app, label, tauri::WebviewUrl::App(url.into()))
        .title(title)
        .decorations(false)
        .transparent(true)
        .shadow(false)
        .always_on_top(true)
        .skip_taskbar(true)
        .resizable(false)
        .visible(false)
        .inner_size(w, h)
        .build()
        .map_err(|e| e.to_string())
}

/// 获取宠物窗口当前所在显示器
fn pet_monitor(app: &AppHandle) -> Result<Monitor, String> {
    let pet = app
        .get_webview_window(PET_LABEL)
        .ok_or("宠物窗口未就绪")?;
    pet.current_monitor()
        .map_err(|e| e.to_string())?
        .ok_or_else(|| "未找到当前显示器".to_string())
}

/// 显示器工作区（物理像素；Tauri 2.0 原生 Monitor::work_area() 获取操作系统
/// 真实工作区，自动排除任务栏/Dock——替代旧版硬编码 48px 任务栏高度的近似，
/// 09/18 最终版修复项）
fn work_area(monitor: &Monitor, _scale: f64) -> (i32, i32, i32, i32) {
    let wa = monitor.work_area();
    (
        wa.position.x,
        wa.position.y,
        wa.size.width as i32,
        wa.size.height as i32,
    )
}

// ---------- 面板窗口 ----------

/// 打开（或关闭）持仓面板窗口：定位在宠物左侧，空间不足时放右侧
pub async fn toggle_panel(app: &AppHandle) -> Result<bool, String> {
    if let Some(win) = app.get_webview_window(PANEL_LABEL) {
        // 已存在：隐藏并销毁（下次重建以重算位置）
        let _ = win.close();
        info!(action = "panel_close", "Panel window closed");
        return Ok(false);
    }

    // 互斥：打开面板前关闭对话窗口（panel 与 chat 不同时显示）
    if let Some(win) = app.get_webview_window(CHAT_LABEL) {
        let _ = win.close();
        info!(action = "chat_close_for_panel", "Chat window closed before opening panel");
    }

    let pet = app.get_webview_window(PET_LABEL).ok_or("宠物窗口未就绪")?;
    let monitor = pet_monitor(app)?;
    let scale = pet.scale_factor().map_err(|e| e.to_string())?;
    let (wa_x, wa_y, wa_w, wa_h) = work_area(&monitor, scale);

    let pet_pos = pet.outer_position().map_err(|e| e.to_string())?;
    let pet_size = pet.outer_size().map_err(|e| e.to_string())?;

    // 优先放宠物左侧
    let panel_w_phys = (PANEL_W * scale) as i32;
    let gap_phys = (GAP * scale) as i32;
    let left_x = pet_pos.x - panel_w_phys - gap_phys;
    let right_x = pet_pos.x + pet_size.width as i32 + gap_phys;

    let x = if left_x >= wa_x {
        left_x
    } else {
        right_x.min(wa_x + wa_w - panel_w_phys)
    };

    // 垂直方向与宠物顶对齐，clamp 到工作区
    let panel_h_phys = (PANEL_H * scale) as i32;
    let y = (pet_pos.y).clamp(wa_y, wa_y + wa_h - panel_h_phys);

    let win = create_window(app, PANEL_LABEL, "持仓面板", "panel", PANEL_W, PANEL_H)?;
    win.set_position(PhysicalPosition::new(x, y))
        .map_err(|e| e.to_string())?;
    win.show().map_err(|e| e.to_string())?;
    // 面板为"看一眼"型窗口：不抢焦点，保持宠物窗口激活态，
    // 避免下次点击宠物被 Windows 窗口激活机制吞噬
    info!(action = "panel_open", x = x, y = y, "Panel window opened");
    Ok(true)
}

// ---------- 对话窗口（AI 层，ready 时才允许创建） ----------

/// 打开对话窗口：定位在宠物右侧（面向未来 AI ready 场景）
/// 互斥约定：打开对话窗时自动关闭持仓面板（panel 与 chat 不同时显示）
pub async fn open_chat(app: &AppHandle) -> Result<(), String> {
    // 互斥：打开对话窗前关闭面板窗口
    if let Some(win) = app.get_webview_window(PANEL_LABEL) {
        let _ = win.close();
        info!(action = "panel_close_for_chat", "Panel window closed before opening chat");
    }

    if app.get_webview_window(CHAT_LABEL).is_some() {
        if let Some(win) = app.get_webview_window(CHAT_LABEL) {
            let _ = win.show();
            let _ = win.set_focus();
        }
        return Ok(());
    }

    let pet = app.get_webview_window(PET_LABEL).ok_or("宠物窗口未就绪")?;
    let monitor = pet_monitor(app)?;
    let scale = pet.scale_factor().map_err(|e| e.to_string())?;
    let (wa_x, wa_y, wa_w, wa_h) = work_area(&monitor, scale);

    let pet_pos = pet.outer_position().map_err(|e| e.to_string())?;
    let pet_size = pet.outer_size().map_err(|e| e.to_string())?;

    let chat_w_phys = (CHAT_W * scale) as i32;
    let chat_h_phys = (CHAT_H * scale) as i32;
    let gap_phys = (GAP * scale) as i32;
    let margin_phys = (MARGIN * scale) as i32;

    // 水平：优先宠物右侧，空间不足回退左侧，最终 clamp 到工作区
    let right_x = pet_pos.x + pet_size.width as i32 + gap_phys;
    let left_x = pet_pos.x - chat_w_phys - gap_phys;
    let x = if right_x + chat_w_phys <= wa_x + wa_w - margin_phys {
        right_x
    } else if left_x >= wa_x + margin_phys {
        left_x
    } else {
        // 两侧都放不下 → clamp 到工作区右内侧（贴近宠物但不出界）
        (wa_x + wa_w - chat_w_phys - margin_phys).max(wa_x + margin_phys)
    };

    // 垂直：与宠物中心对齐，clamp 到工作区上下边界
    let pet_center_y = pet_pos.y + pet_size.height as i32 / 2;
    let y = (pet_center_y - chat_h_phys / 2)
        .clamp(wa_y + margin_phys, wa_y + wa_h - chat_h_phys - margin_phys);

    let win = create_window(app, CHAT_LABEL, "AI 对话", "chat", CHAT_W, CHAT_H)?;
    win.set_position(PhysicalPosition::new(x, y))
        .map_err(|e| e.to_string())?;
    win.show().map_err(|e| e.to_string())?;
    let _ = win.set_focus();
    info!(action = "chat_open", x = x, y = y, "Chat window opened");
    Ok(())
}

/// 关闭对话窗口（AI 关闭时调用）
pub async fn close_chat(app: &AppHandle) -> Result<(), String> {
    if let Some(win) = app.get_webview_window(CHAT_LABEL) {
        let _ = win.close();
        info!(action = "chat_close", "Chat window closed");
    }
    Ok(())
}

// ---------- 提醒气泡窗口 ----------

/// 气泡定位结果（物理像素 + 前端渲染所需锚点）
#[derive(serde::Serialize, Clone, Copy)]
pub struct BubblePlacement {
    pub x: i32,
    pub y: i32,
    /// 尾巴锚点：宠物中心 X 相对气泡左缘的偏移（逻辑像素）
    pub tail_offset: f64,
    /// "above" = 宠物上方（尾巴朝下）；"below" = 宠物下方（尾巴朝上）
    pub side: &'static str,
}

/// 计算气泡位置：默认宠物上方，贴近屏幕顶时翻转到下方；水平 clamp 工作区
pub fn calc_bubble_placement(pet: &WebviewWindow) -> Result<BubblePlacement, String> {
    let monitor = pet
        .current_monitor()
        .map_err(|e| e.to_string())?
        .ok_or("未找到当前显示器")?;
    let scale = pet.scale_factor().map_err(|e| e.to_string())?;
    let (wa_x, wa_y, wa_w, _wa_h) = work_area(&monitor, scale);

    let pet_pos = pet.outer_position().map_err(|e| e.to_string())?;
    let pet_size = pet.outer_size().map_err(|e| e.to_string())?;

    let bubble_w_phys = (BUBBLE_W * scale) as i32;
    let bubble_h_phys = (BUBBLE_H * scale) as i32;
    let gap_phys = (GAP * scale) as i32;
    let margin_phys = (MARGIN * scale) as i32;

    let pet_center_x = pet_pos.x + pet_size.width as i32 / 2;

    // 垂直：默认上方，空间不足翻转到下方
    let y_above = pet_pos.y - bubble_h_phys - gap_phys;
    let (side, y) = if y_above >= wa_y + margin_phys {
        ("above", y_above)
    } else {
        (
            "below",
            pet_pos.y + pet_size.height as i32 + gap_phys,
        )
    };

    // 水平：中心对齐宠物，clamp 工作区
    let mut x = pet_center_x - bubble_w_phys / 2;
    let x_min = wa_x + margin_phys;
    let x_max = wa_x + wa_w - bubble_w_phys - margin_phys;
    if x < x_min {
        x = x_min;
    }
    if x > x_max {
        x = x_max;
    }

    // 尾巴锚点（逻辑像素，相对气泡左缘）
    let tail_offset = ((pet_center_x - x) as f64 / scale).clamp(16.0, BUBBLE_W - 16.0);

    Ok(BubblePlacement { x, y, tail_offset, side })
}

/// 显示提醒气泡（定位到宠物旁；内容窗口自行渲染提醒事件）
pub async fn show_bubble(app: &AppHandle) -> Result<BubblePlacement, String> {
    let pet = app.get_webview_window(PET_LABEL).ok_or("宠物窗口未就绪")?;
    let placement = calc_bubble_placement(&pet)?;

    let win = create_window(app, BUBBLE_LABEL, "提醒", "bubble", BUBBLE_W, BUBBLE_H)?;
    win.set_position(PhysicalPosition::new(placement.x, placement.y))
        .map_err(|e| e.to_string())?;
    win.show().map_err(|e| e.to_string())?;
    let _ = win.set_focus();

    // 通知气泡窗口渲染尾巴锚点
    use tauri::Emitter;
    let _ = win.emit("bubble:placement", &placement);

    info!(
        action = "bubble_show",
        x = placement.x,
        y = placement.y,
        side = placement.side,
        "Bubble window shown"
    );
    Ok(placement)
}

/// 关闭提醒气泡
pub async fn dismiss_bubble(app: &AppHandle) -> Result<(), String> {
    if let Some(win) = app.get_webview_window(BUBBLE_LABEL) {
        let _ = win.close();
        info!(action = "bubble_dismiss", "Bubble window dismissed");
    }
    Ok(())
}
