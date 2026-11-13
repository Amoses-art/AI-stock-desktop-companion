/**
 * 窗口控制 API
 *
 * 多窗口（B1）前端侧出口：面板开合 / 对话窗开合 / 提醒气泡。
 * 业务组件通过本模块操控窗口，禁止直接 invoke 窗口命令。
 */
import { invoke } from "@tauri-apps/api/core";
import { isMockMode } from "./rpc";
import type { AlertEvent } from "./contracts";

/** 气泡定位信息（Rust BubblePlacement 镜像） */
export interface BubblePlacement {
  x: number;
  y: number;
  /** 尾巴锚点：宠物中心 X 相对气泡左缘偏移（逻辑像素） */
  tail_offset: number;
  side: "above" | "below";
}

/** 切换持仓面板窗口（返回切换后是否打开） */
export async function panelToggle(): Promise<boolean> {
  if (isMockMode) return false;
  return invoke<boolean>("panel_toggle");
}

/** 切换 AI 对话窗口（返回切换后是否打开）— 与 panelToggle 语义一致 */
export async function chatToggle(): Promise<boolean> {
  if (isMockMode) return false;
  return invoke<boolean>("chat_toggle");
}

/** 关闭 AI 对话窗口 */
export async function chatClose(): Promise<void> {
  if (isMockMode) return;
  await invoke("chat_close");
}

/** 显示提醒气泡（返回定位信息，用于渲染尾巴） */
export async function bubbleShow(): Promise<BubblePlacement | null> {
  if (isMockMode) return null;
  return invoke<BubblePlacement>("bubble_show");
}

/** 关闭提醒气泡 */
export async function bubbleDismiss(): Promise<void> {
  if (isMockMode) return;
  await invoke("bubble_dismiss");
}

/** 一次性关闭所有子窗口（panel / chat / bubble）
 *  托盘 reset/toggle、pet 边缘吸附时调用，避免子窗口悬空
 */
export async function closeSubWindows(): Promise<void> {
  if (isMockMode) return;
  await invoke("sub_windows_close");
}

/** 拉取最近提醒事件（bubble 窗口挂载时调用，解决窗口创建晚于事件推送的竞态） */
export async function bubbleRecentAlerts(): Promise<AlertEvent[]> {
  if (isMockMode) return [];
  return invoke<AlertEvent[]>("bubble_recent_alerts");
}

// ---------- 宠物窗口原语（M2-1 收口：拖拽/吸附所需的 4 个命令） ----------

/** 窗口几何（物理像素） */
export interface WindowGeometry {
  x: number;
  y: number;
  w: number;
  h: number;
  scale: number;
}

/** 显示器矩形（物理像素） */
export interface MonitorRect {
  x: number;
  y: number;
  w: number;
  h: number;
}

/** 边缘吸附检测结果 */
export interface SnapResult {
  edge: "none" | "left" | "right" | "top" | "bottom";
  monitor: MonitorRect;
}

/** 获取全局光标位置（物理像素） */
export async function getCursorPosition(): Promise<[number, number]> {
  if (isMockMode) return [0, 0];
  return invoke<[number, number]>("get_cursor_position");
}

/** 获取当前窗口位置（物理像素） */
export async function getWindowPosition(): Promise<{ x: number; y: number }> {
  const geo = await invoke<WindowGeometry>("get_window_geometry");
  return { x: geo.x, y: geo.y };
}

/** 设置窗口位置（物理像素） */
export async function windowSetPosition(x: number, y: number): Promise<void> {
  if (isMockMode) return;
  await invoke("window_set_position", { x, y });
}

/** 边缘吸附检测（threshold 物理像素） */
export async function windowEdgeSnap(threshold: number): Promise<SnapResult> {
  if (isMockMode) return { edge: "none", monitor: { x: 0, y: 0, w: 0, h: 0 } };
  return invoke<SnapResult>("window_edge_snap", { threshold });
}

/** 获取当前窗口完整几何（吸附计算用） */
export async function getWindowGeometry(): Promise<WindowGeometry> {
  return invoke<WindowGeometry>("get_window_geometry");
}

/** 设置窗口边界（物理像素）— 折叠/展开 pet 窗口用 */
export async function setWindowBounds(
  x: number,
  y: number,
  w: number,
  h: number,
): Promise<void> {
  if (isMockMode) return;
  await invoke("set_window_bounds", { x, y, w, h });
}

/** 折叠窗口尺寸（仅显示铃铛按钮）— 逻辑像素 */
export const COLLAPSED_W = 40;
export const COLLAPSED_H = 40;

/** 展开后完整窗口尺寸 — 逻辑像素（对齐 Rust PET_WIN_W/H） */
export const PET_WIN_W = 240;
export const PET_WIN_H = 220;
