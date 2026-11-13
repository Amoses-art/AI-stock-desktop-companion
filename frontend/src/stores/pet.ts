/**
 * 桌宠 store：状态机 + 休眠唤醒 + 情绪联动
 *
 * 参照 ipet stores/pet.ts：定时器全部托管于 store，组件卸载即清理。
 */
import { defineStore } from "pinia";
import { computed, ref } from "vue";
import { PetStateMachine, moodFromPnl, isTradingTime } from "@/core/state-machine";
import type { PetVisualState } from "@/core/contracts";

const SLEEP_TIMEOUT_MS = 60_000; // 60 秒无操作进入休眠（PRD 4.1.2）
const BLINK_MIN_MS = 3_000; // 眨眼最小间隔
const BLINK_MAX_MS = 8_000; // 眨眼最大间隔
const BLINK_DURATION_MS = 660; // 眨眼持续：与 anim-blink sprite 6 帧 × 110ms 匹配

export const usePetStore = defineStore("pet", () => {
  const machine = new PetStateMachine();
  const state = ref<PetVisualState>("idle");
  const blinking = ref(false);

  machine.subscribe((s) => (state.value = s));

  // ---------- 眨眼（瞬态，不进入主状态机） ----------
  let blinkTimer: ReturnType<typeof setTimeout> | null = null;

  function scheduleBlink(): void {
    const delay = BLINK_MIN_MS + Math.random() * (BLINK_MAX_MS - BLINK_MIN_MS);
    blinkTimer = setTimeout(() => {
      if (state.value !== "sleep") {
        blinking.value = true;
        setTimeout(() => (blinking.value = false), BLINK_DURATION_MS);
      }
      scheduleBlink();
    }, delay);
  }

  // ---------- 待机轮询（交易时间内 idle → blink → alert → idle 循环） ----------
  // 只在主状态为 idle 且交易时间内触发
  const IDLE_CYCLE_MS = 12_000;  // 12s 一轮
  let idleTimer: ReturnType<typeof setTimeout> | null = null;
  let idlePhase = 0;              // 0=blink, 1=idle, 2=alert

  function scheduleIdleCycle(): void {
    if (idleTimer) clearTimeout(idleTimer);
    idleTimer = setTimeout(() => {
      // 非交易时间 → sleep
      if (!isTradingTime()) {
        if (state.value !== "sleep") machine.reset("sleep");
        scheduleIdleCycle();
        return;
      }
      // 交易时间内、状态为 idle 时才轮询
      if (state.value === "idle") {
        idlePhase = (idlePhase + 1) % 3;
        if (idlePhase === 0) {
          // phase 0: blink（用 blinking 开关，state 保持 idle）
          blinking.value = true;
          setTimeout(() => (blinking.value = false), BLINK_DURATION_MS);
        } else if (idlePhase === 1) {
          // phase 1: idle（不动）
          // no-op
        } else {
          // phase 2: alert（短暂切 alert，然后回到 idle）
          machine.transition("alert");
          setTimeout(() => {
            if (state.value === "alert") machine.reset("idle");
          }, 1200);
        }
      }
      scheduleIdleCycle();
    }, IDLE_CYCLE_MS);
  }

  // ---------- 休眠唤醒 ----------
  let sleepTimer: ReturnType<typeof setTimeout> | null = null;

  function resetSleepTimer(): void {
    if (sleepTimer) clearTimeout(sleepTimer);
    if (state.value === "sleep") {
      // 从 sleep 唤醒：非交易时间 → 不唤醒；交易时间 → 回 idle
      if (isTradingTime()) machine.reset("idle");
    }
    sleepTimer = setTimeout(() => machine.transition("sleep"), SLEEP_TIMEOUT_MS);
  }

  // ---------- 情绪联动（由持仓盈亏驱动） ----------
  function updateMood(totalPnlPercent: number): void {
    // 非交易时间强制 sleep（不管盈亏）
    if (!isTradingTime()) {
      if (state.value !== "sleep") machine.reset("sleep");
      return;
    }
    // 交易时间：根据盈亏决定情绪
    machine.reset(moodFromPnl(totalPnlPercent));
  }

  /** 提醒触发：进入 alert 态并延迟回落 */
  function showAlert(holdMs = 4_000): void {
    machine.reset("alert");
    setTimeout(() => {
      if (state.value === "alert") machine.reset("idle");
    }, holdMs);
  }

  const isSleeping = computed(() => state.value === "sleep");

  function init(): void {
    // 初始状态：非交易时间 → sleep；交易时间 → idle（等 updateMood 推情绪）
    if (!isTradingTime()) machine.reset("sleep");
    scheduleBlink();
    scheduleIdleCycle();
    resetSleepTimer();
  }

  function dispose(): void {
    if (blinkTimer) clearTimeout(blinkTimer);
    if (sleepTimer) clearTimeout(sleepTimer);
    if (idleTimer) clearTimeout(idleTimer);
  }

  return {
    state,
    blinking,
    isSleeping,
    updateMood,
    showAlert,
    resetSleepTimer, // 任意用户交互（拖拽/点击）时由组件调用
    init,
    dispose,
  };
});
