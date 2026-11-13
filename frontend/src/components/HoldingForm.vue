<script setup lang="ts">
/**
 * 持仓表单（新增 / 修改 双模式）
 *
 * 布局顺序：市场 → 类型 → 证券代码/名称 → 数量/成本价 → 提醒阈值
 *
 * - mode="add"：全字段可填；证券代码/名称均由用户自主填写，不做解析与格式校验
 * - mode="edit"：证券/市场/类型 只读（upsert 冲突键），数量/成本价/提醒阈值可编辑
 * - 代码有效性在列表【实时股价】列提示（"代码错误"），由后端 quote_error 标记
 * - 提醒阈值 1-20%：设置后替代默认 3% 提醒；"默认 3%" 表示不设自定义规则
 */
import { computed, reactive, ref, watch } from "vue";
import { api } from "@/core/rpc";
import { usePortfolioStore } from "@/stores/portfolio";
import type { Holding } from "@/core/contracts";

const props = withDefaults(
  defineProps<{
    /** 修改模式：传入当前持仓；新增模式不传 */
    holding?: Holding | null;
    /** 模式标识 */
    mode?: "add" | "edit";
  }>(),
  { holding: null, mode: "add" },
);

const emit = defineEmits<{ close: [] }>();

const store = usePortfolioStore();

/** 市场档位（id 为表单内部标识；backend 映射 cn/hk/us）
 *  0.7.0：恢复港美股添加入口——后端腾讯通道已修复（港股补零、美股无后缀、
 *  market 参数显式传递、响应双侧归一化匹配），港美股行情数据真实可获取。 */
const MARKETS = [
  { id: "A", label: "A股", currency: "CNY", backend: "cn", ph: "如 000001 / 600519" },
  { id: "HK", label: "港股", currency: "HKD", backend: "hk", ph: "如 00700 / 01810" },
  { id: "US", label: "美股", currency: "USD", backend: "us", ph: "如 AAPL / NVDA" },
] as const;

const isEdit = computed(() => props.mode === "edit" && !!props.holding);

const form = reactive({
  market: "A" as string,
  asset_type: "stock" as "stock" | "fund",
  symbol: "",
  name: "",
  quantity: "" as string,
  cost_price: "" as string,
  /** 提醒阈值："" = 默认 3%；"1"-"20" = 自定义百分比 */
  alert_threshold: "" as string,
});

// Edit 模式：预填（保留原 market 原始值，避免 upsert 冲突键漂移产生重复行）
watch(
  () => props.holding,
  (h) => {
    if (!h) return;
    form.market =
      MARKETS.find((m) => m.backend === h.market || m.id === h.market)?.id ?? "A";
    form.asset_type = (h.asset_type === "stock" ? "stock" : "fund") as "stock" | "fund";
    form.symbol = h.symbol;
    form.name = h.name;
    form.quantity = String(h.quantity);
    form.cost_price = String(h.cost_price);
    form.alert_threshold =
      h.alert_threshold && h.alert_threshold >= 1 && h.alert_threshold <= 20
        ? String(Math.round(h.alert_threshold))
        : "";
  },
  { immediate: true },
);

// ---------- 提交 ----------
const submitting = ref(false);
const error = ref("");

const marketInfo = computed(() =>
  MARKETS.find((m) => m.id === form.market) ?? MARKETS[0],
);

/** 提交给后端的规范代码（与后端 MarketDetector 保持一致的 HK .HK 后缀） */
function normalizeSymbol(code: string): string {
  const c = code.trim().toUpperCase().replace(/\.HK$/, "");
  if (form.market === "HK" && form.asset_type === "stock" && /^\d{4,5}$/.test(c)) {
    return `${c}.HK`;
  }
  return c;
}

function validNum(v: string): boolean {
  return /^\d+(\.\d{1,4})?$/.test(v.trim()) && Number(v) > 0;
}

async function submit(): Promise<void> {
  error.value = "";

  // ====== 必填校验（不做代码格式/解析校验；代码有效性由列表实时股价列提示） ======
  const errs: string[] = [];
  const code = form.symbol.trim();

  if (!code) errs.push("证券代码");
  if (!form.name.trim()) errs.push("名称");

  const qty = Number(form.quantity);
  const cost = Number(form.cost_price);
  if (!form.quantity || qty <= 0) errs.push("数量（必须 > 0）");
  if (!form.cost_price || cost <= 0) errs.push("成本价（必须 > 0）");

  const threshold = form.alert_threshold === "" ? null : Number(form.alert_threshold);

  if (errs.length > 0) {
    error.value = "❌ 请检查：" + errs.join("、");
    return;
  }

  submitting.value = true;
  error.value = "⏳ 保存中...";
  try {
    // 新增模式映射 backend 市场；修改模式保留原值（upsert 冲突键一致性）
    const backendMarket = isEdit.value
      ? (props.holding?.market ?? marketInfo.value.backend)
      : marketInfo.value.backend;

    const result = await api.addHolding({
      symbol: isEdit.value ? props.holding!.symbol : normalizeSymbol(code),
      name: form.name.trim(),
      market: backendMarket,
      asset_type: form.asset_type,
      quantity: qty,
      cost_price: cost,
      currency: isEdit.value ? (props.holding?.currency ?? marketInfo.value.currency) : marketInfo.value.currency,
      alert_threshold: threshold,
    });
    console.log("[portfolio_add] SUCCESS:", result);
    error.value = "✅ 持仓保存成功！";
    await store.reload();
    setTimeout(() => emit("close"), 600);
  } catch (e: any) {
    console.error("[portfolio_add] FAILED:", e);
    const msg = e?.message || (typeof e === "string" ? e : JSON.stringify(e));
    error.value = "❌ " + msg;
  } finally {
    submitting.value = false;
  }
}
</script>

<template>
  <div class="overlay" @mousedown.self="emit('close')">
    <form class="form-sheet" @submit.prevent="submit">
      <header class="sheet-header">
        <span class="sheet-title">{{ isEdit ? "修改持仓" : "添加持仓" }}</span>
        <button type="button" class="sheet-close" title="关闭" @click="emit('close')">
          ✕
        </button>
      </header>

      <!-- 1) 市场 -->
      <div class="field">
        <label>市场</label>
        <div class="seg">
          <button
            v-for="m in MARKETS"
            :key="m.id"
            type="button"
            class="seg-item"
            :class="{ active: form.market === m.id }"
            :disabled="isEdit"
            @click="form.market = m.id"
          >
            {{ m.label }}
          </button>
        </div>
      </div>

      <!-- 2) 类型（0.7.0：恢复基金入口——场外基金新浪净值+东财lsjz双通道已修复，
           场内ETF/LOF复用A股腾讯通道；不再隐藏基金添加入口） -->
      <div class="field">
        <label>类型</label>
        <div class="seg">
          <button
            type="button"
            class="seg-item"
            :class="{ active: form.asset_type === 'stock' }"
            :disabled="isEdit"
            @click="form.asset_type = 'stock'"
          >
            个股
          </button>
          <button
            type="button"
            class="seg-item"
            :class="{ active: form.asset_type === 'fund' }"
            :disabled="isEdit"
            @click="form.asset_type = 'fund'"
          >
            基金
          </button>
        </div>
      </div>

      <!-- 3) 证券代码 / 名称（用户自主填写，不做解析与校验） -->
      <div class="field-row">
        <div class="field grow">
          <label>证券代码</label>
          <input
            v-model="form.symbol"
            :placeholder="marketInfo.ph"
            :readonly="isEdit"
            autocomplete="off"
            spellcheck="false"
          />
        </div>
        <div class="field grow">
          <label>名称</label>
          <input
            v-model="form.name"
            placeholder="如 平安银行"
            :readonly="isEdit"
            autocomplete="off"
            spellcheck="false"
          />
        </div>
      </div>

      <!-- 4) 数量 / 成本价 -->
      <div class="field-row">
        <div class="field grow">
          <label>数量</label>
          <input
            v-model="form.quantity"
            inputmode="decimal"
            placeholder="如 100"
            autocomplete="off"
          />
        </div>
        <div class="field grow">
          <label>成本价</label>
          <input
            v-model="form.cost_price"
            inputmode="decimal"
            placeholder="如 10.50"
            autocomplete="off"
          />
        </div>
      </div>

      <!-- 5) 涨跌幅提醒阈值（1-20%，替代默认 3%） -->
      <div class="field">
        <label>涨跌幅提醒阈值</label>
        <div class="threshold-row">
          <select v-model="form.alert_threshold" class="threshold-select">
            <option value="">默认 3%</option>
            <option v-for="n in 20" :key="n" :value="String(n)">{{ n }}%</option>
          </select>
          <span class="threshold-desc">
            {{ form.alert_threshold === "" ? "沿用系统默认 3% 骤然涨跌提醒" : `涨跌幅达 ${form.alert_threshold}% 时提醒（替代默认 3%）` }}
          </span>
        </div>
      </div>

      <div v-if="error" class="form-error">{{ error }}</div>

      <button type="submit" class="submit-btn" :disabled="submitting">
        {{ submitting ? (isEdit ? "保存中…" : "添加中…") : (isEdit ? "保存修改" : "添加") }}
      </button>
    </form>
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

.form-sheet {
  width: calc(100% - 32px);
  background: var(--gd-bg-panel);
  border: 1px solid var(--gd-border);
  border-radius: 14px;
  box-shadow: var(--gd-shadow);
  padding: 14px 16px 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
  max-height: 92%;
  overflow-y: auto;
}

.sheet-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.sheet-title {
  font-size: 14px;
  font-weight: 600;
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

.field-row {
  display: flex;
  gap: 10px;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.field.grow {
  flex: 1;
}

.field label {
  font-size: 11px;
  color: var(--gd-text-muted);
}

.field input {
  box-sizing: border-box;
  width: 100%;
  padding: 7px 10px;
  border: 1px solid var(--gd-border);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.05);
  color: var(--gd-text);
  font-size: 13px;
  font-family: var(--gd-font-mono);
  outline: none;
  transition: border-color var(--gd-dur-fast) var(--gd-ease);
}

.field input:focus {
  border-color: var(--gd-primary);
}

.field input[readonly] {
  opacity: 0.7;
  cursor: not-allowed;
}

.seg {
  display: flex;
  gap: 6px;
}

.seg-item {
  flex: 1;
  padding: 6px 0;
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

.seg-item:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.threshold-row {
  display: flex;
  align-items: center;
  gap: 10px;
}

.threshold-select {
  padding: 6px 10px;
  border: 1px solid var(--gd-border);
  border-radius: 8px;
  background: var(--gd-bg-panel);
  color: var(--gd-text);
  font-size: 12px;
  font-family: var(--gd-font-mono);
  cursor: pointer;
  flex-shrink: 0;
}

.threshold-desc {
  font-size: 10px;
  color: var(--gd-text-muted);
}

.form-error {
  font-size: 12px;
  color: var(--gd-up);
  padding: 0 2px;
}

.submit-btn {
  padding: 9px 0;
  border: none;
  border-radius: 10px;
  background: var(--gd-primary);
  color: #fff;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: opacity var(--gd-dur-fast) var(--gd-ease);
}

.submit-btn:hover:not(:disabled) {
  opacity: 0.88;
}

.submit-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>
