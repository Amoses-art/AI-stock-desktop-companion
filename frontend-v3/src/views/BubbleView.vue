<script setup lang="ts">
/**
 * 提醒气泡视图（bubble 窗口）
 *
 * B1：显示最新提醒事件，尾巴锚点跟随宠物中心（bubble:placement 事件）。
 * 点击任意处关闭；8 秒无交互自动关闭。
 *
 * 数据源：挂载时拉取 Rust 缓存的最近提醒（气泡窗创建晚于事件推送，
 * 独立 webview 的 store 收不到历史事件）；挂载后实时监听 quote:alert 追加。
 */
import { onMounted, onUnmounted, ref } from "vue";
import type { AlertEvent } from "@/core/contracts";
import { isMockMode } from "@/core/rpc";
import { bubbleDismiss, bubbleRecentAlerts } from "@/core/windows";

/** 懒加载 tauri event.listen，避免浏览器 mock 模式顶层 import 崩溃 */
async function _listen<T>(evt: string, cb: (e: { payload: T }) => void) {
  if (isMockMode) return () => {};
  const mod = await import("@tauri-apps/api/event");
  return mod.listen<T>(evt, cb as any);
}

/** 本地提醒列表（不经过 store：bubble 是独立 webview，有自己的 Pinia 实例） */
const alerts = ref<AlertEvent[]>([]);
const tailOffset = ref(170); // 默认居中
const side = ref<"above" | "below">("above");

const AUTO_CLOSE_MS = 8000;
let closeTimer: ReturnType<typeof setTimeout> | null = null;
let unlistenPlacement: (() => void) | null = null;
let unlistenAlerts: (() => void) | null = null;

onMounted(async () => {
  // 1. 拉取 Rust 缓存的最近提醒（解决窗口创建竞态）
  try {
    const recent = await bubbleRecentAlerts();
    alerts.value = recent.slice(-5);
  } catch {
    /* 拉取失败则仅显示实时事件 */
  }

  // 2. 实时提醒事件（气泡已打开时的新触发）
  unlistenAlerts = await _listen<AlertEvent[]>("quote:alert", (e) => {
    alerts.value.push(...e.payload);
  });

  // 3. 接收 Rust 推送的定位信息（尾巴锚点 + 上下方向）
  unlistenPlacement = await _listen<{ tail_offset: number; side: string }>(
    "bubble:placement",
    (e) => {
      tailOffset.value = e.payload.tail_offset;
      side.value = e.payload.side === "below" ? "below" : "above";
    },
  );

  // 自动关闭
  closeTimer = setTimeout(() => dismiss(), AUTO_CLOSE_MS);
});

onUnmounted(() => {
  if (closeTimer) clearTimeout(closeTimer);
  if (unlistenPlacement) unlistenPlacement();
  if (unlistenAlerts) unlistenAlerts();
});

async function dismiss(): Promise<void> {
  if (closeTimer) clearTimeout(closeTimer);
  await bubbleDismiss();
}

/** 触发类型文案 */
function triggerText(t: string): string {
  if (t === "up") return "涨幅触及";
  if (t === "down") return "跌幅触及";
  return "骤变";
}
</script>

<template>
  <div class="bubble" :class="side" @click="dismiss">
    <!-- 尾巴（above：气泡底部朝下指宠物；below：顶部朝上）切图 28×14 -->
    <img
      class="tail"
      :class="side"
      :src="side === 'above' ? '/ui/bubble-tail-up.png' : '/ui/bubble-tail-down.png'"
      :style="{ left: `${tailOffset}px` }"
      alt=""
      draggable="false"
    />
    <div class="bubble-header">
      <span class="bubble-title">⚡ 提醒</span>
      <button class="bubble-close" title="关闭">✕</button>
    </div>
    <div v-if="alerts.length === 0" class="bubble-empty">
      暂时没有新提醒
    </div>
    <div
      v-for="(a, i) in alerts.slice(-3).reverse()"
      :key="`${a.symbol}-${a.triggered_at}-${i}`"
      class="alert-row"
    >
      <span class="alert-name">{{ a.name }}</span>
      <span class="alert-info">
        {{ triggerText(a.trigger_type) }}
        <span v-if="a.percent !== undefined" :class="a.percent >= 0 ? 'up' : 'down'">
          {{ a.percent > 0 ? "+" : "" }}{{ a.percent.toFixed(2) }}%
        </span>
        <span class="alert-price">{{ a.current_price.toFixed(2) }}</span>
      </span>
    </div>
  </div>
</template>

<style scoped>
.bubble {
  width: 100vw;
  height: 100vh;
  box-sizing: border-box;
  background: var(--gd-bg-panel);
  backdrop-filter: blur(18px);
  border: 1px solid var(--gd-border);
  border-radius: 14px;
  box-shadow: var(--gd-shadow);
  padding: 14px 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  cursor: pointer;
  position: relative;
  overflow: visible;
}

/* 尾巴：切图 28×14（tail_offset 为宠物中心 X，尾巴图自身左移一半居中） */
.tail {
  position: absolute;
  width: 28px;
  height: 14px;
  transform: translateX(-14px);
}

.tail.above {
  bottom: -13px;
}

.tail.below {
  top: -13px;
}

.bubble-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.bubble-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--gd-primary);
}

.bubble-close {
  border: none;
  background: transparent;
  color: var(--gd-text-muted);
  font-size: 11px;
  cursor: pointer;
}

.bubble-empty {
  color: var(--gd-text-muted);
  font-size: 12px;
  text-align: center;
  padding: 16px 0;
}

.alert-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 10px;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.04);
  animation: alert-in var(--gd-dur-base) var(--gd-ease);
}

.alert-name {
  font-size: 13px;
}

.alert-info {
  font-size: 12px;
  color: var(--gd-text-muted);
}

.alert-price {
  font-family: var(--gd-font-mono);
  color: var(--gd-up);
  font-weight: 600;
}

@keyframes alert-in {
  from {
    opacity: 0;
    transform: translateY(6px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}
</style>
