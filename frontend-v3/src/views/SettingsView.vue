<script setup lang="ts">
/**
 * 设置视图（M2-2：面板窗口设置页）
 *
 * 皮肤选择 / 交易时段刷新频率 / AI 对话开关。
 * 刷新频率与 AI 开关经 config RPC 后端持久化、热更新生效。
 */
import { onMounted, ref } from "vue";
import { useSettingsStore, SKINS, type SkinId } from "@/stores/settings";

const settings = useSettingsStore();

/** 刷新频率档位（秒）— 交易时段内支持 1s 秒级轮询 */
const INTERVAL_OPTIONS = [1, 5, 10, 15, 30, 60];

onMounted(async () => {
  await settings.loadConfig();
});

const savingInterval = ref(false);
const savingAi = ref(false);
const saveError = ref("");

async function onIntervalChange(e: Event): Promise<void> {
  const sec = Number((e.target as HTMLSelectElement).value);
  savingInterval.value = true;
  saveError.value = "";
  try {
    await settings.setPollInterval(sec);
  } catch (err) {
    saveError.value = err instanceof Error ? err.message : "保存失败";
  } finally {
    savingInterval.value = false;
  }
}

async function onAiToggle(): Promise<void> {
  savingAi.value = true;
  saveError.value = "";
  try {
    await settings.setAiEnabled(!settings.aiEnabled);
  } catch (err) {
    saveError.value = err instanceof Error ? err.message : "保存失败";
  } finally {
    savingAi.value = false;
  }
}

function onSkinChoose(id: SkinId): void {
  settings.skin = id;
}
</script>

<template>
  <div class="settings">
    <!-- 皮肤 -->
    <section class="group">
      <h3 class="group-title">桌宠皮肤</h3>
      <div class="skin-row">
        <button
          v-for="s in SKINS"
          :key="s.id"
          class="skin-card"
          :class="{ active: s.id === settings.skin }"
          @click="onSkinChoose(s.id)"
        >
          <img class="skin-img" :src="`/skins/${s.id}/idle.png`" alt="" draggable="false" />
          <span class="skin-label">{{ s.label }}</span>
          <span v-if="s.id === settings.skin" class="skin-check">✓</span>
        </button>
      </div>
    </section>

    <!-- 刷新频率 -->
    <section class="group">
      <h3 class="group-title">行情刷新频率</h3>
      <p class="group-desc">交易时段内自动轮询持仓行情的间隔（非交易时段不请求）</p>
      <div class="row">
        <select
          class="select"
          :value="settings.pollIntervalSec"
          :disabled="savingInterval"
          @change="onIntervalChange"
        >
          <option v-for="opt in INTERVAL_OPTIONS" :key="opt" :value="opt">
            {{ opt }} 秒
          </option>
        </select>
        <span v-if="savingInterval" class="saving">保存中…</span>
        <span v-else class="saved">已生效</span>
      </div>
    </section>

    <!-- AI 对话开关 -->
    <section class="group">
      <h3 class="group-title">AI 对话能力</h3>
      <div class="row">
        <div class="ai-text">
          <p class="ai-title">启用 AI 对话与智能分析</p>
          <p class="ai-desc">
            开启后可使用本地大模型对话（Ollama）；关闭则仅保留持仓管理核心功能
          </p>
        </div>
        <button
          class="toggle"
          :class="{ on: settings.aiEnabled }"
          :disabled="savingAi"
          role="switch"
          :aria-checked="settings.aiEnabled"
          @click="onAiToggle"
        >
          <span class="toggle-knob" />
        </button>
      </div>
    </section>

    <p v-if="saveError" class="error">{{ saveError }}</p>

    <footer class="settings-footer">
      版本 v0.3（核心版）· 提醒规则与皮肤即刻生效
    </footer>
  </div>
</template>

<style scoped>
.settings {
  flex: 1;
  overflow-y: auto;
  padding: 4px 14px 12px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.group {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.group-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--gd-text);
}

.group-desc {
  font-size: 11px;
  color: var(--gd-text-muted);
  margin-top: -4px;
}

/* 皮肤卡片 */
.skin-row {
  display: flex;
  gap: 8px;
}

.skin-card {
  position: relative;
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  padding: 10px 6px 8px;
  border: 1px solid var(--gd-border);
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.03);
  cursor: pointer;
  transition: all var(--gd-dur-fast) var(--gd-ease);
}

.skin-card:hover {
  background: rgba(255, 255, 255, 0.07);
}

.skin-card.active {
  border-color: var(--gd-primary);
  background: var(--gd-primary-soft);
}

.skin-img {
  width: 52px;
  height: 52px;
  object-fit: contain;
}

.skin-label {
  font-size: 11px;
}

.skin-check {
  position: absolute;
  top: 4px;
  right: 6px;
  font-size: 11px;
  color: var(--gd-primary);
}

/* 刷新频率 */
.row {
  display: flex;
  align-items: center;
  gap: 10px;
}

.select {
  padding: 6px 10px;
  border: 1px solid var(--gd-border);
  border-radius: 8px;
  background: var(--gd-bg-panel);
  color: var(--gd-text);
  font-size: 12px;
  font-family: var(--gd-font-mono);
  cursor: pointer;
}

.select:disabled {
  opacity: 0.5;
}

.saving {
  font-size: 11px;
  color: var(--gd-text-muted);
}

.saved {
  font-size: 11px;
  color: var(--gd-primary);
}

/* AI 开关 */
.ai-text {
  flex: 1;
}

.ai-title {
  font-size: 12px;
}

.ai-desc {
  font-size: 10px;
  color: var(--gd-text-muted);
  margin-top: 2px;
}

.toggle {
  position: relative;
  width: 40px;
  height: 22px;
  border: none;
  border-radius: 11px;
  background: rgba(255, 255, 255, 0.15);
  cursor: pointer;
  flex-shrink: 0;
  transition: background var(--gd-dur-fast) var(--gd-ease);
}

.toggle.on {
  background: var(--gd-primary);
}

.toggle-knob {
  position: absolute;
  top: 2px;
  left: 2px;
  width: 18px;
  height: 18px;
  border-radius: 9px;
  background: #fff;
  transition: transform var(--gd-dur-fast) var(--gd-ease);
}

.toggle.on .toggle-knob {
  transform: translateX(18px);
}

.toggle:disabled {
  opacity: 0.5;
}

.error {
  font-size: 11px;
  color: var(--gd-up);
}

.settings-footer {
  margin-top: auto;
  padding-top: 12px;
  border-top: 1px solid var(--gd-border);
  font-size: 10px;
  color: var(--gd-text-muted);
  text-align: center;
}
</style>
