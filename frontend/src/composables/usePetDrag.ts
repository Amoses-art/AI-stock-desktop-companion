/**
 * 宠物拖拽与点击统一判定（M2-1 从 PetView 拆出）
 *
 * mousedown 记录起点；mousemove 位移超过阈值才进入拖拽；
 * mouseup 时若未拖拽则视为点击（回调 onClick）。
 * 点击动作放在 mouseup 而非 click 事件：面板窗口打开会抢焦点，
 * Windows 对失活窗口的首次点击仅用于激活窗口、click 会被吞噬。
 */
import { ref } from "vue";
import {
  getCursorPosition,
  getWindowGeometry,
  getWindowPosition,
  windowEdgeSnap,
  windowSetPosition,
} from "@/core/windows";

export interface UseDragOptions {
  /** 按下时回调（重置休眠计时等） */
  onPress?: () => void;
  /** 点击（未拖拽）回调 */
  onClick?: () => unknown | Promise<unknown>;
  /** 位移阈值（物理像素），超过才视为拖拽 */
  thresholdPx?: number;
  /** 吸附阈值（物理像素），0 表示不吸附 */
  snapThresholdPx?: number;
  /** 边缘吸附完成后回调（edge = left/right/top/bottom, monitor = 显示器矩形） */
  onSnap?: (edge: string, monitor: { x: number; y: number; w: number; h: number }) => void | Promise<void>;
  /** 开始进入拖拽态时回调（panel 打开时可用来关闭 panel） */
  onDragStart?: () => void;
  /** 拖拽结束但未吸附（折叠态拖离边缘后自动展开用） */
  onNoSnap?: () => void | Promise<void>;
}

export function usePetDrag(options: UseDragOptions = {}) {
  const {
    onPress,
    onClick,
    thresholdPx = 5,
    snapThresholdPx = 24,
    onSnap,
    onNoSnap,
    onDragStart,
  } = options;

  const dragging = ref(false);
  const pressing = ref(false);
  let dragStartCursor = { x: 0, y: 0 };
  let dragStartWin = { x: 0, y: 0 };
  let movePending = false; // rAF 节流标志

  async function onBodyDown(e: MouseEvent): Promise<void> {
    // 仅左键触发按压/拖拽；右键留给 contextmenu（皮肤菜单）
    if (e.button !== 0) return;
    onPress?.();
    pressing.value = true;
    dragging.value = false;
    try {
      const cursor = await getCursorPosition();
      const pos = await getWindowPosition();
      dragStartCursor = { x: cursor[0], y: cursor[1] };
      dragStartWin = { x: pos.x, y: pos.y };
    } catch {
      pressing.value = false;
    }
  }

  async function doMove(): Promise<void> {
    movePending = false;
    if (!pressing.value) return;
    try {
      const cursor = await getCursorPosition();
      const dx = cursor[0] - dragStartCursor.x;
      const dy = cursor[1] - dragStartCursor.y;
      if (!dragging.value) {
        // 位移阈值判定：超过才进入拖拽（否则保持点击候选）
        if (Math.abs(dx) < thresholdPx && Math.abs(dy) < thresholdPx) {
          return;
        }
        dragging.value = true;
        onDragStart?.();
      }
      await windowSetPosition(dragStartWin.x + dx, dragStartWin.y + dy);
    } catch {
      /* 拖拽失败静默 */
    }
  }

  function onBodyMove(_e?: MouseEvent): void {
    if (!pressing.value || movePending) return;
    movePending = true;
    requestAnimationFrame(() => void doMove());
  }

  async function onBodyUp(_e?: MouseEvent): Promise<void> {
    if (!pressing.value) return;
    pressing.value = false;

    if (dragging.value) {
      // 拖拽结束：边缘吸附检测
      dragging.value = false;
      if (snapThresholdPx > 0) {
        try {
          const snap = await windowEdgeSnap(snapThresholdPx);
          if (snap.edge !== "none") {
            const geo = await getWindowGeometry();
            const m = snap.monitor;
            let x = geo.x;
            let y = geo.y;
            // 吸附时留 20 逻辑像素 inset（乘 scale 转物理像素）
            const EDGE_INSET_PX = Math.round(20 * geo.scale);
            if (snap.edge === "left") x = m.x + EDGE_INSET_PX;
            if (snap.edge === "right") x = m.x + m.w - geo.w - EDGE_INSET_PX;
            if (snap.edge === "top") y = m.y + EDGE_INSET_PX;
            if (snap.edge === "bottom") y = m.y + m.h - geo.h - EDGE_INSET_PX;
            await windowSetPosition(x, y);
            // 吸附后：传 monitor 给回调（折叠态需要根据尺寸重定位）
            await Promise.resolve(onSnap?.(snap.edge, snap.monitor));
          } else {
            // 拖拽结束但未吸附（折叠态拖离边缘后自动展开）
            await Promise.resolve(onNoSnap?.());
          }
        } catch {
          /* 吸附失败静默 */
        }
      }
      return;
    }

    // 点击（未发生拖拽）
    await onClick?.();
  }

  return { dragging, pressing, onBodyDown, onBodyMove, onBodyUp };
}
