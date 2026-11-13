/**
 * 事件订阅统一出口
 *
 * 对齐 PRD v3.1 契约冻结表 4.2：
 * quote:tick / quote:alert / pet:state / backend:error / ai:state / ollama:progress
 *
 * 提供带类型的事件订阅，返回退订函数（组件卸载时必须调用，
 * 参照 ipet 集中退订模式，杜绝监听器泄漏）。
 */
import type { AlertEvent, AiState, OllamaProgress, QuoteData } from "./contracts";
import { isMockMode } from "./rpc";

type EventPayloadMap = {
  "quote:tick": QuoteData[];
  "quote:alert": AlertEvent[];
  "pet:state": { state: string };
  "backend:error": string;
  "ai:state": AiState;
  "ollama:progress": OllamaProgress;
  /** 持仓增删改后广播（跨窗口同步：桌宠当日盈亏立即刷新） */
  "portfolio:changed": Record<string, never>;
};

type UnlistenFn = () => void;

/** 懒加载 Tauri event listen——避免浏览器模式下顶层 import 崩溃 */
async function _loadListen() {
  const mod = await import("@tauri-apps/api/event");
  return mod.listen as <T>(event: string, handler: (e: { payload: T }) => void) => Promise<UnlistenFn>;
}

/** 订阅后端事件，返回退订函数 */
export async function on<K extends keyof EventPayloadMap>(
  event: K,
  handler: (payload: EventPayloadMap[K]) => void,
): Promise<UnlistenFn> {
  if (isMockMode) {
    return () => {};
  }
  const listen = await _loadListen();
  return listen<EventPayloadMap[K]>(event, (e) => handler(e.payload));
}

/** 统一管理一组订阅的辅助器（组件作用域内使用） */
export class SubscriptionGroup {
  private unlisteners: UnlistenFn[] = [];

  add(promise: Promise<UnlistenFn>): void {
    promise.then((fn) => {
      if (this.disposed) {
        fn();
      } else {
        this.unlisteners.push(fn);
      }
    });
  }

  private disposed = false;

  dispose(): void {
    this.disposed = true;
    for (const fn of this.unlisteners) fn();
    this.unlisteners = [];
  }
}
