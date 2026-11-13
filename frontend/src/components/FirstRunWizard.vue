<script setup lang="ts">
/**
 * 首启向导（M2-3：选择卡片）
 *
 * 首次启动（config.first_run_done 未标记）时在宠物窗口叠加展示。
 * 两个选择：
 * - 仅持仓管理：核心版，无 AI 对话 UI、无模型请求
 * - 开启 AI 对话：M3 接入 Ollama 静默安装引导链路
 */
import { ref } from "vue";
import { useSettingsStore } from "@/stores/settings";
import { panelToggle } from "@/core/windows";

const settings = useSettingsStore();
const submitting = ref(false);

/** 完成向导：core=仅持仓管理；ai=开启 AI 对话 */
async function choose(mode: "core" | "ai"): Promise<void> {
  if (submitting.value) return;
  submitting.value = true;
  try {
    if (mode === "ai") {
      await settings.setAiEnabled(true);
    }
    await settings.markFirstRunDone();
    // 引导用户进入持仓管理主流程
    await panelToggle();
  } finally {
    submitting.value = false;
  }
}
</script>

<template>
  <div class="wizard-mask">
    <div class="wizard">
      <h2 class="wizard-title">欢迎使用股大师</h2>
      <p class="wizard-sub">选择你需要的启动模式（之后可随时在设置中更改）</p>

      <button class="choice" :disabled="submitting" @click="choose('core')">
        <span class="choice-icon">📈</span>
        <span class="choice-body">
          <span class="choice-title">仅持仓管理</span>
          <span class="choice-desc">三市场持仓 · 实时行情 · 阈值提醒 · 零依赖秒启动</span>
        </span>
      </button>

      <button class="choice" :disabled="submitting" @click="choose('ai')">
        <span class="choice-icon">🤖</span>
        <span class="choice-body">
          <span class="choice-title">开启 AI 对话</span>
          <span class="choice-desc">在持仓管理基础上增加本地大模型对话与分析</span>
        </span>
      </button>

      <p class="wizard-note">AI 能力完全本地运行，不上传任何数据</p>
    </div>
  </div>
</template>

<style scoped>
.wizard-mask {
  position: fixed;
  inset: 0;
  z-index: 200;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(10, 12, 18, 0.82);
  backdrop-filter: blur(6px);
}

.wizard {
  width: 216px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 18px 16px;
  border-radius: 16px;
  background: var(--gd-bg-panel);
  border: 1px solid var(--gd-border);
  box-shadow: 0 16px 48px rgba(0, 0, 0, 0.5);
}

.wizard-title {
  font-size: 15px;
  font-weight: 700;
  text-align: center;
}

.wizard-sub {
  font-size: 10px;
  color: var(--gd-text-muted);
  text-align: center;
  margin-top: -6px;
}

.choice {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px;
  border: 1px solid var(--gd-border);
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.03);
  cursor: pointer;
  text-align: left;
  transition: all var(--gd-dur-fast) var(--gd-ease);
}

.choice:hover:not(:disabled) {
  border-color: var(--gd-primary);
  background: var(--gd-primary-soft);
  transform: translateY(-1px);
}

.choice:disabled {
  opacity: 0.5;
  cursor: wait;
}

.choice-icon {
  font-size: 22px;
  flex-shrink: 0;
}

.choice-body {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.choice-title {
  font-size: 13px;
  font-weight: 600;
}

.choice-desc {
  font-size: 10px;
  color: var(--gd-text-muted);
  line-height: 1.4;
}

.wizard-note {
  font-size: 9px;
  color: var(--gd-text-muted);
  text-align: center;
}
</style>
