<script setup lang="ts">
/**
 * 桌宠视图（宠物窗口）
 *
 * 热区分层（ipet 模式）：身体=拖拽/点击（面板）、铃铛=开面板+清提醒红点、右键=换肤。
 * 交互逻辑已拆出 composables（M2-1）：
 * - usePetDrag：拖拽与点击统一判定 + 边缘吸附
 * - usePetDisplay：展示状态优先级 + 帧动画调度
 * - useTicker：信息条轮播
 */
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { usePetStore } from "@/stores/pet";
import { usePortfolioStore } from "@/stores/portfolio";
import { useSettingsStore } from "@/stores/settings";
import {
  panelToggle,
  chatToggle,
  closeSubWindows,
  getWindowGeometry,
  setWindowBounds,
  COLLAPSED_W,
  COLLAPSED_H,
  PET_WIN_W,
  PET_WIN_H,
} from "@/core/windows";
import { usePetDrag } from "@/composables/usePetDrag";
import { usePetDisplay, ENTER_MS } from "@/composables/usePetDisplay";
import { useTicker } from "@/composables/useTicker";
import FirstRunWizard from "@/components/FirstRunWizard.vue";

const pet = usePetStore();
const portfolio = usePortfolioStore();
const settings = useSettingsStore();

/** 首启向导：配置加载完成且未标记完成时展示（M2-3） */
const showWizard = computed(
  () => settings.configLoaded && !settings.firstRunDone,
);

/** AI 对话入口：toggle 语义，与 panel icon 对齐（开/关 + 互斥） */
async function onChatOpen(): Promise<void> {
  pet.resetSleepTimer();
  try {
    await chatToggle();
  } catch (e) {
    // 命令缺失/后端未就绪等失败场景不抛未处理异常，静默降级
    console.error("[chat_toggle] 打开 AI 对话失败:", e);
  }
}

// ---------- 折叠态：吸附边缘后窗口缩小到仅显示铃铛（40×40 逻辑像素） ----------
const collapsed = ref(false);

type Monitor = { x: number; y: number; w: number; h: number };

async function collapseToEdge(edge: string, monitor: Monitor): Promise<void> {
  try {
    const geo = await getWindowGeometry();
    const scale = geo.scale;
    const fw = Math.round(COLLAPSED_W * scale);
    const fh = Math.round(COLLAPSED_H * scale);
    // EDGE_INSET 20 是逻辑像素，需要乘 scale 转物理像素
    const EDGE_INSET_PX = Math.round(20 * scale);
    // 根据 edge 重新定位折叠后的小窗口（因为折叠后尺寸变了）
    let x = geo.x;
    let y = geo.y;
    if (edge === "left") x = monitor.x + EDGE_INSET_PX;
    if (edge === "right") x = monitor.x + monitor.w - fw - EDGE_INSET_PX;
    if (edge === "top") y = monitor.y + EDGE_INSET_PX;
    if (edge === "bottom") y = monitor.y + monitor.h - fh - EDGE_INSET_PX;
    await setWindowBounds(x, y, fw, fh);
    collapsed.value = true;
  } catch {
    /* 折叠失败静默 */
  }
}

async function expandFromEdge(): Promise<void> {
  try {
    const geo = await getWindowGeometry();
    const scale = geo.scale;
    const pw = Math.round(PET_WIN_W * scale);
    const ph = Math.round(PET_WIN_H * scale);
    await setWindowBounds(geo.x, geo.y, pw, ph);
    collapsed.value = false;
  } catch {
    /* 展开失败静默 */
  }
}

// ---------- 交互（composables） ----------
const { dragging, pressing, onBodyDown, onBodyMove, onBodyUp } = usePetDrag({
  onPress: async () => {
    pet.resetSleepTimer();
    // closeSubWindows 移到 onDragStart：只有确认拖拽（移动>5px）才关
    // 避免 mousedown 误关 panel → mouseup toggle 又开 → 闪烁
  },
  onClick: async () => {
    portfolio.clearAlertFeed();
    pet.resetSleepTimer();
    if (collapsed.value) await expandFromEdge();
    await panelToggle();
  },
  onDragStart: async () => {
    // 确认进入拖拽态（移动>5px）才关 panel/bubble/chat
    await closeSubWindows();
  },
  onSnap: async (edge, monitor) => {
    await closeSubWindows();
    await collapseToEdge(edge, monitor);
  },
  onNoSnap: async () => {
    if (collapsed.value) await expandFromEdge();
  },
});

const {
  entering,
  enterDone,
  imgSrc,
  petStyle,
  alertAnimating,
  blinkAnimating,
} = usePetDisplay(dragging, pressing);

const { tickerList, tickerItem, tickerIndex, start: startTicker, stop: stopTicker } =
  useTicker(3000);

// ---------- 热区：铃铛 = 开面板 + 清提醒红点 ----------
async function onBellClick(): Promise<void> {
  pet.resetSleepTimer();
  portfolio.clearAlertFeed();
  await panelToggle();
}

// ---------- 已移除右键皮肤菜单（鸡肋功能，设置页已有入口；2026-09-03） ----------

function changeClass(pct: number): string {
  if (pct > 0) return "up";
  if (pct < 0) return "down";
  return "flat";
}

function formatMoney(v: number): string {
  const sign = v > 0 ? "+" : "";
  if (Math.abs(v) >= 10000) return `${sign}${(v / 10000).toFixed(2)}万`;
  return `${sign}${v.toFixed(2)}`;
}

function formatPct(p: number): string {
  const sign = p > 0 ? "+" : "";
  return `${sign}${p.toFixed(2)}%`;
}


// 当日盈亏 → 桌宠情绪联动：涨红=happy，跌绿=sad
watch(
  () => portfolio.totalDailyPnlPercent,
  (pct) => {
    pet.updateMood(pct);
  },
  { immediate: true }
);

onMounted(() => {
  // 入场动画播放一次后进入正常状态机渲染
  setTimeout(enterDone, ENTER_MS);
  startTicker();
});

onUnmounted(() => {
  stopTicker();
});
</script>

<template>
  <div
    class="pet-stage"
    :class="{ dragging, collapsed }"
    @mousedown="onBodyDown($event)"
    @mousemove="onBodyMove($event)"
    @mouseup="onBodyUp($event)"
    @mouseleave="onBodyUp($event)"
  >
    <!-- 首启向导（M2-3） -->
    <FirstRunWizard v-if="showWizard" />

    <!-- ====== 折叠态：仅显示居中铃铛，整个 stage 是拖拽热区 ====== -->
    <div v-if="collapsed" class="collapsed-bell">
      <img class="cb-img" src="/ui/bell.png" alt="" draggable="false" />
      <img
        v-if="portfolio.unreadAlertCount > 0"
        class="cb-img cb-active"
        src="/ui/bell-active.png"
        alt=""
        draggable="false"
        style="animation: bell-swing 0.9s ease-in-out infinite"
      />
      <span v-if="portfolio.unreadAlertCount > 0" class="cb-badge">
        {{ portfolio.unreadAlertCount > 99 ? "99+" : portfolio.unreadAlertCount }}
      </span>
    </div>

    <!-- ====== 正常态 ====== -->
    <template v-else>
      <!-- AI 对话入口（M2-3 门控：仅 aiEnabled 时显示） -->
      <button
        v-if="settings.aiEnabled"
        class="chat-zone"
        title="AI 对话"
        @mousedown.stop.prevent="onChatOpen"
      >
        💬
      </button>

      <!-- 铃铛热区：提醒红点（mousedown 触发，规避窗口激活吞噬 click） -->
      <button
        class="bell-zone"
        :class="{ active: portfolio.unreadAlertCount > 0 }"
        title="提醒"
        @mousedown.stop.prevent="onBellClick"
      >
        <img class="bell-img" src="/ui/bell.png" alt="" draggable="false" />
        <img
          class="bell-img is-hover"
          src="/ui/bell-hover.png"
          alt=""
          draggable="false"
        />
        <img
          class="bell-img is-active"
          src="/ui/bell-active.png"
          alt=""
          draggable="false"
        />
        <span v-if="portfolio.unreadAlertCount > 0" class="bell-badge">
          {{ portfolio.unreadAlertCount > 99 ? "99+" : portfolio.unreadAlertCount }}
        </span>
      </button>

      <!-- 身体热区：拖拽 + 点击 -->
      <div
        class="drag-zone"
        @mousedown.prevent="onBodyDown"
        @mousemove="onBodyMove"
        @mouseup="onBodyUp"
        @mouseleave="onBodyUp"
      >
        <!-- 帧动画层（sprite sheet）与静态状态图互斥渲染 -->
        <div v-if="entering" class="pet-sprite sprite-enter" />
        <div v-else-if="alertAnimating" class="pet-sprite sprite-alert" />
        <div v-else-if="blinkAnimating" class="pet-sprite sprite-blink" />
        <img
          v-else
          class="pet-avatar"
          :src="imgSrc"
          :style="petStyle"
          alt="桌宠"
          draggable="false"
        />
      </div>

      <!-- 信息条 -->
      <div class="ticker">
        <template v-if="tickerItem && tickerItem.kind === 'summary'">
          <span class="ticker-label">当日盈亏</span>
          <span class="ticker-price" :class="changeClass(tickerItem.dailyPercent)">
            {{ formatMoney(tickerItem.dailyAmount) }}
          </span>
          <span class="ticker-pct" :class="changeClass(tickerItem.dailyPercent)">
            {{ formatPct(tickerItem.dailyPercent) }}
          </span>
        </template>
        <template v-else>
          <span class="ticker-empty">暂无持仓，点击宠物添加</span>
        </template>
        <!-- 轮播指示器 -->
        <div v-if="tickerList.length > 1" class="ticker-dots">
          <span
            v-for="(_, i) in tickerList"
            :key="i"
            class="dot"
            :class="{ active: i === tickerIndex }"
          />
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.pet-stage {
  width: 100vw;
  height: 100vh;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  position: relative;
  cursor: default;
}

.pet-stage.dragging {
  opacity: 0.75;
}

/* 折叠态：吸附边缘后仅显示铃铛 */
.pet-stage.collapsed {
  cursor: grab;
}
.pet-stage.collapsed.dragging {
  cursor: grabbing;
}

.collapsed-bell {
  position: relative;
  width: 40px;
  height: 40px;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: inherit;
}

.cb-img {
  width: 36px;
  height: 36px;
  object-fit: contain;
  position: absolute;
  inset: 2px;
}

.cb-img.cb-active {
  z-index: 2;
}

.cb-badge {
  position: absolute;
  top: 0;
  right: 0;
  min-width: 16px;
  height: 16px;
  padding: 0 4px;
  border-radius: 8px;
  background: var(--gd-up);
  color: #fff;
  font-size: 10px;
  font-family: var(--gd-font-mono);
  line-height: 16px;
  text-align: center;
  z-index: 3;
}

.drag-zone {
  cursor: grab;
}

.pet-stage.dragging .drag-zone {
  cursor: grabbing;
}

.pet-avatar {
  width: 110px;
  height: 110px;
  transition: filter var(--gd-dur-base) var(--gd-ease), transform var(--gd-dur-fast) var(--gd-ease);
  animation: pet-breathe 3.2s ease-in-out infinite;
}

.drag-zone:hover .pet-avatar {
  transform: scale(1.05);
}

/* ---------- 帧动画层（sprite sheet 横帧条，切图 v1-rev1） ---------- */
/* 源帧 256×256，显示 110px；帧数×110 = background-size 宽度 */
.pet-sprite {
  width: 110px;
  height: 110px;
  background-repeat: no-repeat;
}

.sprite-blink {
  background-image: url("/anims/anim-blink.png");
  background-size: 660px 110px; /* 6 帧 */
  animation: sprite-x-6 660ms steps(6) forwards,
    pet-breathe 3.2s ease-in-out infinite;
}

.sprite-alert {
  background-image: url("/anims/anim-alert.png");
  background-size: 660px 110px; /* 6 帧 */
  animation: sprite-x-6 720ms steps(6) infinite,
    pet-breathe 3.2s ease-in-out infinite;
}

.sprite-enter {
  background-image: url("/anims/anim-enter.png");
  background-size: 880px 110px; /* 8 帧 */
  animation: sprite-x-8 800ms steps(8) forwards;
}

@keyframes sprite-x-6 {
  from {
    background-position-x: 0;
  }
  to {
    background-position-x: -660px;
  }
}

@keyframes sprite-x-8 {
  from {
    background-position-x: 0;
  }
  to {
    background-position-x: -880px;
  }
}

/* ---------- 铃铛（切图三态：默认/悬停/提醒中） ---------- */
.bell-zone {
  position: absolute;
  top: 12px;
  right: 16px;
  width: 30px;
  height: 30px;
  padding: 0;
  border: none;
  background: transparent;
  cursor: pointer;
  transition: transform var(--gd-dur-fast) var(--gd-ease);
}

.bell-zone:hover {
  transform: scale(1.15);
}

.bell-img {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  object-fit: contain;
  opacity: 1;
  transition: opacity var(--gd-dur-fast) var(--gd-ease);
}

.bell-img.is-hover {
  opacity: 0;
}

.bell-img.is-active {
  opacity: 0;
}

/* 悬停：默认→悬停图 */
.bell-zone:hover .bell-img:not(.is-hover):not(.is-active) {
  opacity: 0;
}

.bell-zone:hover .bell-img.is-hover {
  opacity: 1;
}

/* 有未读提醒：优先显示激活态并摇晃（切图规范 §5：静态图 + CSS 摇晃） */
.bell-zone.active .bell-img:not(.is-active) {
  opacity: 0;
}

.bell-zone.active .bell-img.is-active {
  opacity: 1;
  animation: bell-swing 0.9s ease-in-out infinite;
}

@keyframes bell-swing {
  0%,
  100% {
    transform: rotate(0deg);
  }
  20% {
    transform: rotate(16deg);
  }
  40% {
    transform: rotate(-13deg);
  }
  60% {
    transform: rotate(9deg);
  }
  80% {
    transform: rotate(-6deg);
  }
}

.bell-badge {
  position: absolute;
  top: -4px;
  right: -6px;
  min-width: 16px;
  height: 16px;
  padding: 0 4px;
  border-radius: 8px;
  background: var(--gd-up);
  color: #fff;
  font-size: 10px;
  font-family: var(--gd-font-mono);
  line-height: 16px;
  text-align: center;
}

/* AI 对话入口（M2-3：仅 aiEnabled 时渲染） */
.chat-zone {
  position: absolute;
  top: 44px;
  right: 16px;
  width: 30px;
  height: 30px;
  padding: 0;
  border: none;
  border-radius: 15px;
  background: var(--gd-bg-panel);
  border: 1px solid var(--gd-border);
  font-size: 14px;
  line-height: 28px;
  cursor: pointer;
  filter: drop-shadow(0 1px 3px rgba(0, 0, 0, 0.4));
  transition: transform var(--gd-dur-fast) var(--gd-ease);
}

.chat-zone:hover {
  transform: scale(1.15);
}

/* 信息条：底部 */
.ticker {
  margin-top: 10px;
  padding: 4px 14px;
  border-radius: 10px;
  background: var(--gd-bg-panel);
  border: 1px solid var(--gd-border);
  font-family: var(--gd-font-mono);
  font-size: 12px;
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 180px;
  justify-content: center;
}

.ticker-name {
  color: var(--gd-text);
  font-family: var(--gd-font);
  max-width: 72px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ticker-empty {
  color: var(--gd-text-muted);
  font-family: var(--gd-font);
  font-size: 11px;
}

.ticker-dots {
  display: flex;
  gap: 3px;
  position: absolute;
  bottom: 2px;
  left: 50%;
  transform: translateX(-50%);
}

.dot {
  width: 4px;
  height: 4px;
  border-radius: 2px;
  background: var(--gd-text-muted);
  opacity: 0.4;
}

.dot.active {
  background: var(--gd-primary);
  opacity: 1;
}

.ticker {
  position: relative;
}

.up {
  color: var(--gd-up);
}

.down {
  color: var(--gd-down);
}

.flat {
  color: var(--gd-flat);
}

@keyframes pet-breathe {
  0%,
  100% {
    transform: translateY(0);
  }
  50% {
    transform: translateY(-4px);
  }
}
</style>
