<script setup lang="ts">
/**
 * 应用外壳：多窗口视图路由
 *
 * 参照 ipet 单入口多窗口模式：三个逻辑窗口（pet/panel/chat）
 * 加载同一构建产物，以 ?view= 区分渲染内容。
 * 窗口本身由 Rust 侧创建/定位（B1 阶段实现）。
 */
import { computed, onMounted, onUnmounted, watch } from "vue";
import PetView from "./views/PetView.vue";
import PanelView from "./views/PanelView.vue";
import ChatView from "./views/ChatView.vue";
import BubbleView from "./views/BubbleView.vue";
import SettingsView from "./views/SettingsView.vue";
import { useAppStore } from "@/stores/app";
import { usePetStore } from "@/stores/pet";
import { usePortfolioStore } from "@/stores/portfolio";
import { useSettingsStore } from "@/stores/settings";

type ViewName = "pet" | "panel" | "chat" | "bubble" | "settings";

const view = computed<ViewName>(() => {
  const v = new URLSearchParams(window.location.search).get("view");
  if (v === "panel" || v === "chat" || v === "bubble" || v === "settings") return v;
  return "pet";
});

const appStore = useAppStore();
const petStore = usePetStore();
const portfolioStore = usePortfolioStore();
const settingsStore = useSettingsStore();

onMounted(async () => {
  petStore.init();
  await Promise.allSettled([
    appStore.init(),
    portfolioStore.init(),
    settingsStore.loadConfig(),
  ]);

  watch(
    () => portfolioStore.totalPnlPercent,
    (pnl) => petStore.updateMood(pnl),
    { immediate: true },
  );

  watch(
    () => portfolioStore.unreadAlertCount,
    (n, old) => {
      if (n > (old ?? 0)) petStore.showAlert();
    },
  );
});

onUnmounted(() => {
  petStore.dispose();
  portfolioStore.dispose();
  appStore.dispose();
});
</script>

<template>
  <PetView v-if="view === 'pet'" />
  <PanelView v-else-if="view === 'panel'" />
  <ChatView v-else-if="view === 'chat'" />
  <SettingsView v-else-if="view === 'settings'" />
  <BubbleView v-else />
</template>
