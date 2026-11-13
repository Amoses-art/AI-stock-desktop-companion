/**
 * 应用级 store：AI 状态、后端错误
 *
 * 首启向导与产品配置已迁移至 settings store（M2-2/M2-3）。
 */
import { defineStore } from "pinia";
import { ref } from "vue";
import { api } from "@/core/rpc";
import { on, SubscriptionGroup } from "@/core/events";
import type { AiState } from "@/core/contracts";

export const useAppStore = defineStore("app", () => {
  const subs = new SubscriptionGroup();

  const aiState = ref<AiState>({ ai_enabled: false, ai_status: "disabled" });
  const backendError = ref<string | null>(null);

  async function init(): Promise<void> {
    // 订阅 AI 状态变化与后端错误
    subs.add(on("ai:state", (s) => (aiState.value = s)));
    subs.add(on("backend:error", (msg) => (backendError.value = msg)));

    // 读取持久化状态
    try {
      const state = await api.getAiState();
      if (state) aiState.value = state;
    } catch {
      // 后端未就绪时保持默认值（核心层容错：AI 状态读不到不影响持仓功能）
    }
  }

  /** 设置端开启：启用 AI 对话（触发 Ollama 引导链路，M3） */
  async function enableAi(): Promise<void> {
    await api.enableAi();
  }

  async function disableAi(): Promise<void> {
    await api.disableAi();
  }

  function dispose(): void {
    subs.dispose();
  }

  return {
    aiState,
    backendError,
    init,
    enableAi,
    disableAi,
    dispose,
  };
});
