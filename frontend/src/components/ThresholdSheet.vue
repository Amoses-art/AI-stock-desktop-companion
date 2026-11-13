<script setup lang="ts">
/**
 * 阈值提醒浮层（单持仓）
 *
 * B3-2：列出该持仓的提醒规则，支持添加（涨/跌 + 阈值%）与删除。
 * 规则走 alert.add / alert.remove RPC，冷却默认 30 分钟（PRD v3.1）。
 */
import { computed, reactive, ref } from "vue";
import { usePortfolioStore } from "@/stores/portfolio";
import type { Holding } from "@/core/contracts";

const props = defineProps<{ holding: Holding }>();
const emit = defineEmits<{ close: [] }>();

const store = usePortfolioStore();

/** 该持仓的规则（按 portfolio_id 关联） */
const rules = computed(() =>
  store.alerts.filter((r) => r.portfolio_id === props.holding.id),
);

const form = reactive({
  direction: "up" as "up" | "down",
  percent: "" as string,
});
const submitting = ref(false);
const error = ref("");

async function addRule(): Promise<void> {
  error.value = "";
  const pct = Number(form.percent);
  if (!Number.isFinite(pct) || pct <= 0 || pct > 100) {
    error.value = "阈值需为 0~100 之间的正数";
    return;
  }
  submitting.value = true;
  try {
    await store.addAlert({
      portfolio_id: props.holding.id,
      threshold_percent: pct,
      direction: form.direction,
      is_active: true,
      cooldown_minutes: 30,
    });
    form.percent = "";
  } catch (e) {
    error.value = e instanceof Error ? e.message : "添加失败";
  } finally {
    submitting.value = false;
  }
}

async function removeRule(id: number): Promise<void> {
  try {
    await store.removeAlert(id);
  } catch {
    /* 删除失败静默：列表下次 reload 会纠正 */
  }
}

function dirLabel(d: string): string {
  return d === "up" ? "涨幅 ≥" : "跌幅 ≥";
}
</script>

<template>
  <div class="overlay" @mousedown.self="emit('close')">
    <div class="sheet">
      <header class="sheet-header">
        <div class="sheet-title-wrap">
          <span class="sheet-title">阈值提醒</span>
          <span class="sheet-sub">{{ holding.name }} {{ holding.symbol }}</span>
        </div>
        <button class="sheet-close" title="关闭" @click="emit('close')">✕</button>
      </header>

      <!-- 已有规则 -->
      <div v-if="rules.length > 0" class="rule-list">
        <div v-for="r in rules" :key="r.id" class="rule-item">
          <span class="rule-text">
            {{ dirLabel(r.direction) }}
            <span :class="r.direction">{{ r.threshold_percent.toFixed(1) }}%</span>
            <template v-if="!r.is_active">（已停用）</template>
          </span>
          <span class="rule-cd">冷却 {{ r.cooldown_minutes }} 分钟</span>
          <button class="rule-del" title="删除规则" @click="removeRule(r.id)">
            ✕
          </button>
        </div>
      </div>
      <div v-else class="rule-empty">暂无提醒规则</div>

      <!-- 新增规则 -->
      <form class="rule-form" @submit.prevent="addRule">
        <div class="seg">
          <button
            type="button"
            class="seg-item"
            :class="{ active: form.direction === 'up' }"
            @click="form.direction = 'up'"
          >
            涨幅
          </button>
          <button
            type="button"
            class="seg-item"
            :class="{ active: form.direction === 'down' }"
            @click="form.direction = 'down'"
          >
            跌幅
          </button>
        </div>
        <input
          v-model="form.percent"
          inputmode="decimal"
          placeholder="阈值 %"
          autocomplete="off"
        />
        <button type="submit" class="add-btn" :disabled="submitting">添加</button>
      </form>
      <div v-if="error" class="form-error">{{ error }}</div>
    </div>
  </div>
</template>

<style scoped>
.overlay {
  position: absolute;
  inset: 0;
  z-index: 10;
  background: rgba(0, 0, 0, 0.12);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  display: flex;
  align-items: center;
  justify-content: center;
}

.sheet {
  width: calc(100% - 32px);
  background: var(--gd-bg-panel);
  border: 1px solid var(--gd-border);
  border-radius: 14px;
  box-shadow: var(--gd-shadow);
  padding: 14px 16px 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.sheet-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
}

.sheet-title-wrap {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.sheet-title {
  font-size: 14px;
  font-weight: 600;
}

.sheet-sub {
  font-size: 11px;
  color: var(--gd-text-muted);
  font-family: var(--gd-font-mono);
}

.sheet-close {
  border: none;
  background: transparent;
  color: var(--gd-text-muted);
  font-size: 12px;
  cursor: pointer;
  padding: 4px;
}

.sheet-close:hover {
  color: var(--gd-text);
}

.rule-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-height: 180px;
  overflow-y: auto;
}

.rule-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.04);
  font-size: 12px;
}

.rule-text {
  flex: 1;
}

.rule-cd {
  font-size: 10px;
  color: var(--gd-text-muted);
}

.rule-del {
  border: none;
  background: transparent;
  color: var(--gd-text-muted);
  font-size: 11px;
  cursor: pointer;
  padding: 2px 4px;
}

.rule-del:hover {
  color: var(--gd-up);
}

.rule-empty {
  font-size: 12px;
  color: var(--gd-text-muted);
  text-align: center;
  padding: 10px 0;
}

.rule-form {
  display: flex;
  gap: 8px;
  align-items: stretch;
}

.seg {
  display: flex;
  gap: 4px;
}

.seg-item {
  padding: 0 10px;
  border: 1px solid var(--gd-border);
  border-radius: 8px;
  background: transparent;
  color: var(--gd-text-muted);
  font-size: 12px;
  cursor: pointer;
  transition: all var(--gd-dur-fast) var(--gd-ease);
}

.seg-item.active {
  background: var(--gd-primary-soft);
  border-color: var(--gd-primary);
  color: var(--gd-primary);
}

.rule-form input {
  box-sizing: border-box;
  flex: 1;
  min-width: 0;
  padding: 7px 10px;
  border: 1px solid var(--gd-border);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.05);
  color: var(--gd-text);
  font-size: 13px;
  font-family: var(--gd-font-mono);
  outline: none;
}

.rule-form input:focus {
  border-color: var(--gd-primary);
}

.add-btn {
  padding: 0 16px;
  border: none;
  border-radius: 8px;
  background: var(--gd-primary);
  color: #fff;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
}

.add-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.form-error {
  font-size: 12px;
  color: var(--gd-up);
  padding: 0 2px;
}

.up {
  color: var(--gd-up);
}

.down {
  color: var(--gd-down);
}
</style>
