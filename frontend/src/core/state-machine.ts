/**
 * 桌宠状态机
 *
 * 参照 ipet shared/state-machine.ts 模式：
 * - 转换表集中定义，非法转换抛错（开发期尽早暴露逻辑问题）
 * - 瞬态（blink）由独立开关管理，不污染主状态
 */
import { PET_TRANSITIONS, type PetVisualState } from "./contracts";

export class PetStateMachine {
  private current: PetVisualState = "idle";
  private listeners = new Set<(s: PetVisualState) => void>();

  get state(): PetVisualState {
    return this.current;
  }

  /** 尝试转换状态；非法转换在开发期抛错并拒绝 */
  transition(next: PetVisualState): boolean {
    const allowed = PET_TRANSITIONS[this.current] ?? [];
    if (!allowed.includes(next)) {
      console.warn(
        `[PetStateMachine] 非法转换: ${this.current} → ${next}（已拒绝）`,
      );
      return false;
    }
    this.current = next;
    this.listeners.forEach((fn) => fn(next));
    return true;
  }

  /** 强制设置状态（仅用于初始化/重置，绕过转换表） */
  reset(state: PetVisualState = "idle"): void {
    this.current = state;
    this.listeners.forEach((fn) => fn(state));
  }

  subscribe(fn: (s: PetVisualState) => void): () => void {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }
}

/**
 * A 股交易时间判断（北京时间）：
 *  上午 09:30 - 11:30，下午 13:00 - 15:00，工作日
 */
export function isTradingTime(now: Date = new Date()): boolean {
  // 周末 = 非交易
  const dow = now.getDay();
  if (dow === 0 || dow === 6) return false;
  const h = now.getHours();
  const m = now.getMinutes();
  const mins = h * 60 + m;
  // 09:30 - 11:30 → 570 ~ 690
  // 13:00 - 15:00 → 780 ~ 900
  return (mins >= 570 && mins <= 690) || (mins >= 780 && mins <= 900);
}

/**
 * 由持仓总盈亏 + 交易时间推导初始状态
 *  - 非交易时间 → sleep
 *  - 盈利 > +1% → happy
 *  - 亏损 < -1% → sad
 *  - 其余交易时间 → idle（后续由 store 驱动 blink/idle/alert 轮询）
 */
export function moodFromPnl(pnlPercent: number): PetVisualState {
  if (!isTradingTime()) return "sleep";
  if (pnlPercent > 1) return "happy";
  if (pnlPercent < -1) return "sad";
  return "idle";
}
