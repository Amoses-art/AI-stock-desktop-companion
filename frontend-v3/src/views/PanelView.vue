<script setup lang="ts">
/**
 * 功能面板视图（持仓 + 设置）
 *
 * 持仓清单（增强版）：
 * 1) 名称 + 代码
 * 2) 持仓数量 + 成本价
 * 3) 实时股价 + 涨跌幅（点击展开当日K线）
 * 4) 当日盈亏金额 + 百分比
 * 5) 修改icon（数量/成本价）+ 删除icon
 */
import { computed, onMounted, ref } from "vue";
import { storeToRefs } from "pinia";
import { usePortfolioStore } from "@/stores/portfolio";
import HoldingForm from "@/components/HoldingForm.vue";
import SettingsView from "@/views/SettingsView.vue";
import { api } from "@/core/rpc";
import type { Holding, KlineData, KlineSeries, QuoteData } from "@/core/contracts";

const store = usePortfolioStore();
const { loading } = storeToRefs(store);
const activeTab = ref<"stock" | "fund">("stock");
const activePage = ref<"holdings" | "settings">("holdings");
const expandedKline = ref<Set<number>>(new Set());

const list = computed(() =>
  activeTab.value === "stock" ? store.stockList : store.fundList,
);

// ---------- 浮层状态 ----------
const showAddForm = ref(false);
const editingHolding = ref<Holding | null>(null);

// ---------- 交易时段 ----------
type SessionState = "trading" | "lunch" | "closed";

function sessionState(): SessionState {
  const now = new Date();
  const day = now.getDay();
  const mins = now.getHours() * 60 + now.getMinutes();
  if (day === 0 || day === 6) return "closed";
  if (mins >= 540 && mins < 690) return "trading";
  if (mins >= 690 && mins < 780) return "lunch";
  if (mins >= 780 && mins <= 900) return "trading";
  return "closed";
}

const session = ref<SessionState>(sessionState());

const quoteTime = computed<string | null>(() => {
  let latest = "";
  for (const q of Object.values(store.quotes)) {
    const ts = q.timestamp ?? "";
    if (/^\d{14}$/.test(ts) && ts > latest) latest = ts;
  }
  if (!latest) return null;
  return `${latest.slice(8, 10)}:${latest.slice(10, 12)}:${latest.slice(12, 14)}`;
});

const dataAsOf = computed(() => {
  if (quoteTime.value) return `数据截至 ${quoteTime.value}`;
  if (store.lastRefreshAt)
    return `更新于 ${new Date(store.lastRefreshAt).toLocaleTimeString()}`;
  return "";
});

onMounted(async () => {
  await store.init();
  if (Object.keys(store.quotes).length === 0 && store.holdings.length > 0) {
    void store.manualRefresh();
  }
});

// ---------- 删除持仓 ----------
const removingId = ref<number | null>(null);

async function removeHolding(h: Holding): Promise<void> {
  if (removingId.value !== null) return;
  removingId.value = h.id;
  try {
    await store.removeHolding(h.id);
  } catch { /* 静默 */ }
  finally {
    removingId.value = null;
  }
}

// ---------- K线展开（真实分时数据） ----------
function toggleKline(h: Holding): void {
  const id = h.id;
  if (expandedKline.value.has(id)) {
    expandedKline.value.delete(id);
  } else {
    expandedKline.value.add(id);
    void loadKline(h);
  }
  expandedKline.value = new Set(expandedKline.value);
}

function isKlineExpanded(id: number): boolean {
  return expandedKline.value.has(id);
}

// ---------- 展示辅助 ----------
function getQuote(h: Holding): QuoteData | undefined {
  return store.quotes[h.symbol];
}

// ============ 安全取 pre_close（有就用，没有用 change_percent 反推） ============
function safePreClose(h: Holding): number {
  const q = getQuote(h);
  if (q?.pre_close && q.pre_close > 0) return q.pre_close;
  // fallback: pre_close = current / (1 + change%/100)
  const price = q?.current_price ?? h.current_price;
  const chg = q?.change_percent ?? h.change_percent;
  if (Number.isFinite(price) && Number.isFinite(chg) && chg !== -100) {
    const pc = price / (1 + chg / 100);
    if (pc > 0) return pc;
  }
  return 0;
}

function displayPrice(h: Holding): string {
  const q = getQuote(h);
  const p = q?.current_price ?? h.current_price;
  return Number.isFinite(p) ? p.toFixed(2) : "--";
}

/** 0.6.0（用户实测反馈4）：状态语义拆分
 *  - code_invalid：代码格式/市场不匹配 → 「代码错误」
 *  - data_pending：代码合法但数据源未响应 → 「数据获取中」；
 *    列表内已有缓存价时优先显示缓存，取到最新行情后自动刷新
 *  若已有真实行情（代码已修正/行情恢复），一律按正常显示 */
function isCodeInvalid(h: Holding): boolean {
  if (getQuote(h)) return false;
  if (h.quote_state) return h.quote_state === "code_invalid";
  return !!h.quote_error && !(h.current_price > 0);
}
function isDataPending(h: Holding): boolean {
  if (getQuote(h)) return false;
  return h.quote_state === "data_pending";
}
/** data_pending 且无任何缓存价 → 只显示「数据获取中」占位 */
function isPendingWithoutCache(h: Holding): boolean {
  return isDataPending(h) && !(h.current_price > 0);
}

function displayChange(h: Holding): number {
  const q = getQuote(h);
  const c = q?.change_percent ?? h.change_percent;
  return Number.isFinite(c) ? c : 0;
}

function displayPnlAmount(h: Holding): string {
  const q = getQuote(h);
  const price = q?.current_price ?? h.current_price;
  const preClose = safePreClose(h);
  if (!Number.isFinite(price) || !Number.isFinite(preClose) || preClose <= 0 || !Number.isFinite(h.quantity)) return "--";
  const amount = (price - preClose) * h.quantity;
  const sign = amount > 0 ? "+" : "";
  return `${sign}${amount.toFixed(2)}`;
}

function displayPnlPercent(h: Holding): string {
  const q = getQuote(h);
  const price = q?.current_price ?? h.current_price;
  const preClose = safePreClose(h);
  if (!Number.isFinite(price) || !Number.isFinite(preClose) || preClose <= 0) return "--";
  const pct = ((price - preClose) / preClose) * 100;
  const sign = pct > 0 ? "+" : "";
  return `${sign}${pct.toFixed(2)}%`;
}

function pnlPercentNum(h: Holding): number {
  const q = getQuote(h);
  const price = q?.current_price ?? h.current_price;
  const preClose = safePreClose(h);
  if (!Number.isFinite(price) || !Number.isFinite(preClose) || preClose <= 0) return 0;
  return ((price - preClose) / preClose) * 100;
}

function changeClass(pct: number): string {
  if (pct > 0) return "up";
  if (pct < 0) return "down";
  return "flat";
}

const totalPnl = computed(() => store.totalPnlPercent.toFixed(2));

/** 金额格式化：≥1万 → x.xx万；否则保留两位小数 */
function formatMoney(v: number): string {
  if (!Number.isFinite(v)) return "--";
  const sign = v < 0 ? "-" : "";
  const abs = Math.abs(v);
  const body = abs >= 10000 ? `${(abs / 10000).toFixed(2)}万` : abs.toFixed(2);
  return `${sign}${body}`;
}

// ============ K线（真实分时数据 kline.get） ============
/** 分时K线缓存：`${symbol}:${days}` → 后端返回 */
const klineData = ref<Record<string, KlineData | null>>({});
const klineLoading = ref<Set<string>>(new Set());
const klineError = ref<Record<string, string>>({});
/** 展开天数：1 = 当日分时；5 = 近5日分时趋势 */
const klineDays = ref<1 | 5>(1);

function klineKey(h: Holding, days: number = klineDays.value): string {
  return `${h.symbol}:${days}`;
}

async function loadKline(h: Holding, days: number = klineDays.value): Promise<void> {
  const key = klineKey(h, days);
  if (klineLoading.value.has(key) || klineData.value[key]) return;
  klineLoading.value.add(key);
  klineLoading.value = new Set(klineLoading.value);
  try {
    const data = await api.getKline(h.symbol, {
      market: h.market,
      asset_type: h.asset_type,
      days,
    });
    klineData.value[key] = data;
    delete klineError.value[key];
  } catch (e: any) {
    klineError.value[key] = e?.message || "K线获取失败";
  } finally {
    klineLoading.value.delete(key);
    klineLoading.value = new Set(klineLoading.value);
  }
}

async function changeKlineDays(days: 1 | 5): Promise<void> {
  klineDays.value = days;
  const expanded = [...expandedKline.value];
  for (const id of expanded) {
    const h = store.holdings.find((x) => x.id === id);
    if (h) void loadKline(h, days);
  }
}

// ---------- K线 SVG 生成（真实分时数据） ----------

interface KlineRender {
  W: number;
  totalH: number;
  pricePath: string;
  areaPath: string;
  avgPricePath: string;
  color: string;
  preCloseY: number | null;
  volBars: { x: number; y: number; w: number; h: number; fill: string }[];
  labels: { text: string; x: number; y: number; anchor?: string; cls?: string }[];
  yTicks: { y: number; label: string }[];
}

/** 单日分时 → SVG 渲染结构 */
function buildSingleDay(series: KlineSeries, preClose: number): KlineRender | null {
  const pts = series.points;
  if (!pts || pts.length < 2) return null;

  const W = 280;
  const H = 100;
  const VH = 30;
  const padTop = 6;
  const padBottom = 4;
  const priceAreaBottom = H - padBottom;

  let priceLo = Infinity, priceHi = -Infinity;
  for (const p of pts) {
    if (p.price < priceLo) priceLo = p.price;
    if (p.price > priceHi) priceHi = p.price;
  }
  if (!Number.isFinite(priceLo) || !Number.isFinite(priceHi)) return null;
  if (preClose > 0) {
    priceLo = Math.min(priceLo, preClose);
    priceHi = Math.max(priceHi, preClose);
  }
  const pricePad = (priceHi - priceLo) * 0.08 || Math.abs(priceHi) * 0.01;
  priceLo -= pricePad;
  priceHi += pricePad;
  const priceRange = priceHi - priceLo || 1;

  const yOf = (p: number) => padTop + (priceHi - p) / priceRange * (priceAreaBottom - padTop);
  const preCloseY = preClose > 0 ? yOf(preClose) : null;

  const N = pts.length;
  const coords = pts.map((p, i) => ({
    x: (i / (N - 1)) * W,
    y: yOf(p.price),
  }));
  const pricePath = smoothPath(coords);
  const areaPath = pricePath + ` L${W} ${priceAreaBottom} L0 ${priceAreaBottom} Z`;

  // 均价线：成交量加权累计（缺少 vol 时退化为简单均值）
  let cumSum = 0, cumW = 0;
  const avgCoords = coords.map((c, i) => {
    if (i === 0) { cumSum = pts[0].price; cumW = 1; }
    else {
      const w = (pts[i].vol + pts[i - 1].vol) / 2 || 1;
      cumSum += pts[i].price * w;
      cumW += w;
    }
    return { x: c.x, y: yOf(cumSum / cumW) };
  });
  const avgPricePath = smoothPath(avgCoords);

  const maxVol = Math.max(...pts.map((p) => p.vol), 1);
  const volBars = pts.map((p, i) => {
    const x = (i / (N - 1)) * W;
    const barH = (p.vol / maxVol) * (VH - 4) * 0.85;
    const prev = i === 0 ? p : pts[i - 1];
    return {
      x: x - 3, y: priceAreaBottom + 6 + (VH - 4 - barH),
      w: 6, h: barH,
      fill: p.price >= prev.price ? "var(--gd-up)" : "var(--gd-down)",
    };
  });

  const open = pts[0].price;
  const close = pts[pts.length - 1].price;
  const color = close >= preClose ? "var(--gd-up)" : "var(--gd-down)";
  const labels: KlineRender["labels"] = [
    { text: priceFmt(open), x: 2, y: yOf(open) - 2, cls: "dim" },
    { text: priceFmt(close), x: W - 2, y: yOf(close) - 2, anchor: "end", cls: "main" },
  ];

  // 最高/最低价标签（与锚点价拉开距离才显示）
  let hiP = -Infinity, loP = Infinity;
  for (const p of pts) { if (p.price > hiP) hiP = p.price; if (p.price < loP) loP = p.price; }
  const hiI = pts.findIndex((p) => p.price === hiP);
  const loI = pts.findIndex((p) => p.price === loP);
  if (hiP - Math.max(open, close) > priceRange * 0.15)
    labels.push({ text: priceFmt(hiP), x: Math.min((hiI / (N - 1)) * W + 4, W - 32), y: yOf(hiP) - 2, cls: "dim" });
  if (Math.min(open, close) - loP > priceRange * 0.15)
    labels.push({ text: priceFmt(loP), x: Math.min((loI / (N - 1)) * W + 4, W - 32), y: yOf(loP) + 10, cls: "dim" });

  labels.push({ text: "09:30", x: 0, y: H + VH + 10, cls: "axis" });
  labels.push({ text: "11:30", x: W * 0.41, y: H + VH + 10, cls: "axis" });
  labels.push({ text: "13:00", x: W * 0.5, y: H + VH + 10, cls: "axis" });
  labels.push({ text: "15:00", x: W, y: H + VH + 10, anchor: "end", cls: "axis" });

  const yTicks = [
    { y: padTop + 8, label: priceFmt(priceHi - priceRange * 0.15) },
    { y: priceAreaBottom - 2, label: priceFmt(priceLo + priceRange * 0.15) },
  ];

  return { W, totalH: H + VH + 14, pricePath, areaPath, avgPricePath, color, preCloseY, volBars, labels, yTicks };
}

/** 近5日分时迷你图 */
interface DayMiniRender {
  date: string;   // MM-DD 标签
  path: string;
  color: string;
  pct: string;    // 当日涨跌幅
  W: number;
  H: number;
}

function buildMiniDay(series: KlineSeries, preClose: number, W: number): DayMiniRender | null {
  const pts = series.points;
  if (!pts || pts.length < 2) return null;
  let priceLo = Infinity, priceHi = -Infinity;
  for (const p of pts) {
    if (p.price < priceLo) priceLo = p.price;
    if (p.price > priceHi) priceHi = p.price;
  }
  if (!Number.isFinite(priceLo) || !Number.isFinite(priceHi)) return null;
  if (preClose > 0) {
    priceLo = Math.min(priceLo, preClose);
    priceHi = Math.max(priceHi, preClose);
  }
  const range = (priceHi - priceLo) || 1;
  priceLo -= range * 0.08;
  priceHi += range * 0.08;
  const H = 34;
  const yOf = (p: number) => 2 + (priceHi - p) / (priceHi - priceLo || 1) * (H - 6);
  const coords = pts.map((p, i) => ({ x: (i / (pts.length - 1)) * W, y: yOf(p.price) }));
  const first = pts[0].price;
  const last = pts[pts.length - 1].price;
  const pct = first > 0 ? ((last - first) / first) * 100 : 0;
  return {
    date: series.date ? `${series.date.slice(4, 6)}-${series.date.slice(6, 8)}` : "",
    path: smoothPath(coords),
    color: pct >= 0 ? "var(--gd-up)" : "var(--gd-down)",
    pct: `${pct >= 0 ? "+" : ""}${pct.toFixed(2)}%`,
    W, H,
  };
}

/** 单日渲染缓存（key = `${symbol}:1`） */
const klineRender = computed<Record<string, KlineRender | null>>(() => {
  const out: Record<string, KlineRender | null> = {};
  for (const key of Object.keys(klineData.value)) {
    const data = klineData.value[key];
    if (!data) { out[key] = null; continue; }
    if (data.days <= 1) {
      out[key] = data.series[0] ? buildSingleDay(data.series[0], data.pre_close) : null;
    }
  }
  return out;
});

/** 近5日迷你渲染缓存（key = `${symbol}:5`） */
const klineMini = computed<Record<string, DayMiniRender[]>>(() => {
  const out: Record<string, DayMiniRender[]> = {};
  for (const key of Object.keys(klineData.value)) {
    const data = klineData.value[key];
    if (!data || data.days <= 1) continue;
    out[key] = data.series
      .map((s) => buildMiniDay(s, data.pre_close, 240))
      .filter((d): d is DayMiniRender => d !== null);
  }
  return out;
});

function smoothPath(pts: { x: number; y: number }[]): string {
  if (pts.length < 2) return "";
  let d = `M${pts[0].x.toFixed(1)} ${pts[0].y.toFixed(1)}`;
  for (let i = 0; i < pts.length - 1; i++) {
    const p0 = pts[Math.max(0, i - 1)];
    const p1 = pts[i];
    const p2 = pts[i + 1];
    const p3 = pts[Math.min(pts.length - 1, i + 2)];
    const cp1x = p1.x + (p2.x - p0.x) / 6;
    const cp1y = p1.y + (p2.y - p0.y) / 6;
    const cp2x = p2.x - (p3.x - p1.x) / 6;
    const cp2y = p2.y - (p3.y - p1.y) / 6;
    d += ` C${cp1x.toFixed(1)} ${cp1y.toFixed(1)}, ${cp2x.toFixed(1)} ${cp2y.toFixed(1)}, ${p2.x.toFixed(1)} ${p2.y.toFixed(1)}`;
  }
  return d;
}

function priceFmt(p: number): string {
  return Number.isFinite(p) ? p.toFixed(2) : "--";
}
</script>
<template>
  <div class="panel">
    <header class="panel-header">
      <template v-if="activePage === 'holdings'">
        <span class="panel-title">持仓管理</span>
        <span class="pnl-summary" :class="changeClass(store.totalPnlPercent)">
          总盈亏 {{ totalPnl }}%（{{ formatMoney(store.totalPnlAmount) }}）
        </span>
        <button class="refresh-btn" :disabled="store.refreshing" title="手动刷新" @click="store.manualRefresh()">
          {{ store.refreshing ? "…" : "⟳" }}
        </button>
        <button class="refresh-btn" title="添加持仓" @click="showAddForm = true">＋</button>
      </template>
      <template v-else>
        <span class="panel-title">设置</span>
      </template>
      <button class="refresh-btn" :class="{ 'page-on': activePage === 'settings' }" title="设置"
        @click="activePage = activePage === 'holdings' ? 'settings' : 'holdings'">⚙</button>
    </header>

    <SettingsView v-if="activePage === 'settings'" />

    <template v-else>
      <nav class="tabs">
        <button class="tab" :class="{ active: activeTab === 'stock' }" @click="activeTab = 'stock'">
          个股清单<span class="badge">{{ store.stockList.length }}</span>
        </button>
        <!-- 0.7.0：恢复基金清单 tab——场外基金新浪净值+东财lsjz双通道已修复，
             场内ETF/LOF复用A股腾讯通道，基金数据真实可获取 -->
        <button class="tab" :class="{ active: activeTab === 'fund' }" @click="activeTab = 'fund'">
          基金清单<span class="badge">{{ store.fundList.length }}</span>
        </button>
      </nav>

      <main class="holding-list">
        <div v-if="loading" class="loading-skeleton">
          <div v-for="n in 3" :key="n" class="skeleton-row">
            <div class="skeleton-col skeleton-name"></div>
            <div class="skeleton-col skeleton-pos"></div>
            <div class="skeleton-col skeleton-quote"></div>
            <div class="skeleton-col skeleton-pnl"></div>
          </div>
        </div>
        <div v-else-if="list.length === 0" class="empty-state">暂无持仓，点击 ＋ 添加</div>

        <template v-for="h in list" :key="h.id">
          <div class="holding-row">
            <div class="col col-name">
              <div class="holding-name" :class="{ long: h.name.length > 6 }">{{ h.name }}</div>
              <div class="holding-code">{{ h.symbol }}·{{ h.market.toUpperCase() }}</div>
            </div>
            <div class="col col-pos">
              <div class="pos-cell"><span class="pos-lbl">量</span><span class="pos-val">{{ h.quantity }}</span></div>
              <div class="pos-cell"><span class="pos-lbl">本</span><span class="pos-val">{{ h.cost_price.toFixed(2) }}</span></div>
            </div>
            <div class="col col-quote" @click="toggleKline(h)">
              <template v-if="isCodeInvalid(h)">
                <div class="price quote-err" title="代码无法匹配市场/类型，请检查代码或删除后重新添加">代码错误</div>
              </template>
              <template v-else-if="isPendingWithoutCache(h)">
                <div class="price quote-pending" title="代码合法，行情数据源获取中，稍候自动刷新">数据获取中…</div>
              </template>
              <template v-else>
                <div class="price" :class="changeClass(displayChange(h))">{{ displayPrice(h) }}</div>
                <div v-if="isDataPending(h)" class="pending-hint" title="当前展示上一次缓存价，最新行情获取中">⟳ 获取中</div>
                <div class="change" :class="changeClass(displayChange(h))">
                  <span class="arrow">{{ displayChange(h) > 0 ? "▲" : displayChange(h) < 0 ? "▼" : "—" }}</span>
                  <span>{{ Math.abs(displayChange(h)).toFixed(2) }}%</span>
                </div>
              </template>
              <div class="kline-hint">{{ isKlineExpanded(h.id) ? "收起 ▲" : "K线 ▼" }}</div>
            </div>
            <div class="col col-pnl" :class="changeClass(pnlPercentNum(h))">
              <div class="pnl-amount">{{ displayPnlAmount(h) }}</div>
              <div class="pnl-percent">{{ displayPnlPercent(h) }}</div>
              <div class="pnl-sub">当日</div>
            </div>
            <div class="col col-actions">
              <button class="act-btn edit-btn" title="修改" @click.stop="editingHolding = h">
              <svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
            </button>
              <button class="act-btn del-btn" title="删除" @click.stop="removeHolding(h)">
              <svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-2 14a2 2 0 0 1-2 2H9a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/><path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/></svg>
            </button>
            </div>
          </div>

          <Transition name="kline-expand">
            <div v-if="isKlineExpanded(h.id)" class="kline-row">
              <div class="kline-toolbar">
                <div class="days-toggle">
                  <button type="button" class="days-btn" :class="{ active: klineDays === 1 }"
                    @click.stop="changeKlineDays(1)">当日</button>
                  <button type="button" class="days-btn" :class="{ active: klineDays === 5 }"
                    @click.stop="changeKlineDays(5)">近5日</button>
                </div>
                <span v-if="klineLoading.has(klineKey(h))" class="kline-loading">⏳ 加载中…</span>
              </div>

              <template v-if="klineDays === 1">
                <div v-if="klineRender[klineKey(h)]" class="kline-wrap">
                  <svg :width="klineRender[klineKey(h)]!.W" :height="klineRender[klineKey(h)]!.totalH">
                    <!-- 昨收虚线 -->
                    <line v-if="klineRender[klineKey(h)]!.preCloseY !== null" :x1="0" :y1="klineRender[klineKey(h)]!.preCloseY!"
                      :x2="klineRender[klineKey(h)]!.W" :y2="klineRender[klineKey(h)]!.preCloseY!" stroke="var(--gd-text-muted)"
                      stroke-width="1" stroke-dasharray="3,3" opacity="0.4" />
                    <!-- 价格面积 -->
                    <path :d="klineRender[klineKey(h)]!.areaPath" :fill="klineRender[klineKey(h)]!.color" opacity="0.08" />
                    <!-- 价格曲线 -->
                    <path :d="klineRender[klineKey(h)]!.pricePath" :stroke="klineRender[klineKey(h)]!.color" stroke-width="1.6" fill="none" />
                    <!-- 均价线 -->
                    <path :d="klineRender[klineKey(h)]!.avgPricePath" stroke="var(--gd-primary)" stroke-width="1" fill="none" stroke-dasharray="4,2" opacity="0.7" />
                    <!-- Y 轴刻度 -->
                    <text v-for="(t, i) in klineRender[klineKey(h)]!.yTicks" :key="'y'+i" :x="2" :y="t.y"
                      fill="var(--gd-text-muted)" font-size="8" font-family="var(--gd-font-mono)">{{ t.label }}</text>
                    <!-- 成交量柱 -->
                    <rect v-for="(b, i) in klineRender[klineKey(h)]!.volBars" :key="'v'+i" :x="b.x" :y="b.y"
                      :width="b.w" :height="b.h" :fill="b.fill" opacity="0.55" rx="1" />
                    <!-- 文字标签 -->
                    <text v-for="(lbl, i) in klineRender[klineKey(h)]!.labels" :key="'l'+i" :x="lbl.x" :y="lbl.y"
                      :text-anchor="lbl.anchor || 'start'"
                      :fill="lbl.cls === 'main' ? klineRender[klineKey(h)]!.color : 'var(--gd-text-muted)'"
                      :font-size="lbl.cls === 'axis' ? 8 : 9"
                      font-family="var(--gd-font-mono)"
                      :font-weight="lbl.cls === 'main' ? '600' : '400'">{{ lbl.text }}</text>
                  </svg>
                </div>
                <div v-else-if="klineError[klineKey(h)]" class="kline-empty">{{ klineError[klineKey(h)] }}</div>
                <div v-else class="kline-empty">暂无行情</div>
              </template>

              <template v-else>
                <div v-if="klineMini[klineKey(h)]?.length" class="kline-multi">
                  <div v-for="(d, di) in klineMini[klineKey(h)]" :key="di" class="mini-row">
                    <span class="mini-date">{{ d.date }}</span>
                    <svg :width="d.W" :height="d.H">
                      <path :d="d.path" :stroke="d.color" stroke-width="1.4" fill="none" />
                    </svg>
                    <span class="mini-pct" :style="{ color: d.color }">{{ d.pct }}</span>
                  </div>
                </div>
                <div v-else-if="klineError[klineKey(h)]" class="kline-empty">{{ klineError[klineKey(h)] }}</div>
                <div v-else class="kline-empty">暂无行情</div>
              </template>
            </div>
          </Transition>
        </template>
      </main>

      <footer class="panel-footer">
        <span v-if="session === 'trading'" class="session on">● 交易时段</span>
        <span v-else-if="session === 'lunch'" class="session lunch">◐ 午间休市</span>
        <span v-else class="session off">○ 已收盘</span>
        <span v-if="dataAsOf" class="last-update">{{ dataAsOf }}</span>
        <!-- 0.6.0（用户实测反馈1）：手动刷新 RPC 失败不再静默，提示用户重试 -->
        <span v-if="store.refreshFailed" class="refresh-failed">⚠ 刷新失败，请点击 ⟳ 重试</span>
      </footer>
    </template>

    <HoldingForm v-if="showAddForm" @close="showAddForm = false" />
    <HoldingForm v-if="editingHolding" :holding="editingHolding" mode="edit" @close="editingHolding = null" />
  </div>
</template>

<style scoped>
.panel { width: 100%; height: 100%; box-sizing: border-box; display: flex; flex-direction: column;
  background: var(--gd-bg-panel); backdrop-filter: blur(18px);
  border: 1px solid var(--gd-border); border-radius: var(--gd-radius);
  box-shadow: var(--gd-shadow); overflow: hidden; font-size: 12px; }
.panel-header { display: flex; align-items: center; gap: 10px; padding: 12px 14px 8px; }
.panel-title { font-size: 14px; font-weight: 600; }
.pnl-summary { flex: 1; font-family: var(--gd-font-mono); font-size: 12px; }
.refresh-btn { width: 26px; height: 26px; border: 1px solid var(--gd-border); border-radius: 8px;
  background: var(--gd-primary-soft); color: var(--gd-primary); cursor: pointer; font-size: 13px;
  transition: transform .15s ease; }
.refresh-btn:hover:not(:disabled) { transform: rotate(90deg); }
.refresh-btn.page-on { background: var(--gd-primary); color: #fff; }
.tabs { display: flex; gap: 6px; padding: 0 14px 8px; }
.tab { display: flex; align-items: center; gap: 6px; padding: 5px 12px;
  border: 1px solid transparent; border-radius: 8px; background: transparent;
  color: var(--gd-text-muted); font-size: 12px; cursor: pointer; }
.tab.active { background: var(--gd-primary-soft); border-color: var(--gd-border); color: var(--gd-primary); }
.badge { font-family: var(--gd-font-mono); font-size: 10px; }
.holding-list { flex: 1; overflow-y: auto; min-height: 0; padding: 0 4px; }
.empty-state { padding: 32px 0; text-align: center; color: var(--gd-text-muted); font-size: 12px; }

/* ====== 持仓行：flex 布局 ====== */
.holding-row { display: flex; align-items: stretch; gap: 6px; padding: 10px 8px;
  border-radius: 10px; border-top: 1px solid rgba(255,255,255,.03); transition: background .15s; }
.holding-row:hover { background: rgba(255,255,255,.04); }
.col { overflow: hidden; flex-shrink: 0; }

/* 列1：名称 flex:1 自适应 */
.col-name { flex: 1.6 1 0; min-width: 0; display: flex; flex-direction: column; justify-content: center; gap: 2px; overflow: hidden; }
.holding-name { font-size: 13px; font-weight: 600; color: var(--gd-text);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.holding-name.long { animation: scrollName 6s linear infinite; }
@keyframes scrollName {
  0%, 15% { transform: translateX(0); }
  85%, 100% { transform: translateX(calc(-100% + 120px)); }
}
.holding-code { font-family: var(--gd-font-mono); font-size: 10px; color: var(--gd-text-muted);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

/* 列2：数量+成本 固定92px */
.col-pos { width: 96px; display: flex; flex-direction: column; justify-content: center; gap: 1px; }
.pos-cell { display: flex; align-items: baseline; gap: 3px; }
.pos-lbl { font-size: 9px; color: var(--gd-text-muted); line-height: 1; flex-shrink: 0; }
.pos-val { font-family: var(--gd-font-mono); font-size: 11px; color: var(--gd-text); white-space: nowrap; }

/* 列3：行情 固定110px */
.col-quote { width: 108px; text-align: center; font-family: var(--gd-font-mono);
  cursor: pointer; user-select: none; padding: 2px 0; border-radius: 6px;
  transition: background .15s; display: flex; flex-direction: column; justify-content: center; gap: 1px; }
.col-quote:hover { background: rgba(0,212,255,.08); }
.price { font-size: 13px; font-weight: 600; }
.quote-err { color: var(--gd-up); font-size: 10px; font-weight: 500; letter-spacing: 1px; }
/* 0.6.0：数据获取中（代码合法、行情未到）——中性色，非错误语义 */
.quote-pending { color: var(--gd-text-muted); font-size: 10px; font-weight: 500; letter-spacing: 1px; }
.pending-hint { font-size: 9px; color: var(--gd-text-muted); opacity: .75; }
.change { font-size: 10px; display: flex; align-items: center; justify-content: center; gap: 2px; }
.arrow { font-size: 9px; line-height: 1; }
.kline-hint { font-size: 9px; color: var(--gd-text-muted); opacity: .5; }

/* 列4：当日盈亏 固定100px */
.col-pnl { width: 96px; text-align: right; font-family: var(--gd-font-mono);
  display: flex; flex-direction: column; justify-content: center; gap: 1px; }
.pnl-amount { font-size: 12px; font-weight: 600; white-space: nowrap; }
.pnl-percent { font-size: 10px; white-space: nowrap; }
.pnl-sub { font-size: 9px; color: var(--gd-text-muted); font-family: var(--gd-font); opacity: .5; }

/* 列5：操作 固定48px */
.col-actions { width: 52px; display: flex; gap: 4px; justify-content: center; align-items: center; opacity: .3; transition: opacity .15s; }
.holding-row:hover .col-actions { opacity: 1; }
.act-btn { width: 22px; height: 22px; border: none; border-radius: 6px;
  background: rgba(255,255,255,0.05); color: var(--gd-text-muted); cursor: pointer;
  transition: all .15s; display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
.act-btn:hover.edit-btn { background: rgba(0,212,255,.15); color: var(--gd-primary); }
.act-btn:hover.del-btn { background: rgba(255,77,94,.15); color: var(--gd-up); }

/* K线 */
.kline-row { padding: 0 8px 10px; overflow: hidden; }
.kline-toolbar { display: flex; align-items: center; justify-content: space-between; padding: 0 2px 6px; }
.days-toggle { display: flex; gap: 4px; }
.days-btn { padding: 2px 8px; border: 1px solid var(--gd-border); border-radius: 6px;
  background: transparent; color: var(--gd-text-muted); font-size: 10px; cursor: pointer;
  transition: all .15s ease; }
.days-btn.active { background: var(--gd-primary-soft); border-color: var(--gd-primary); color: var(--gd-primary); }
.kline-loading { font-size: 10px; color: var(--gd-text-muted); }
.kline-wrap { background: rgba(0,0,0,.25); border: 1px solid var(--gd-border); border-radius: 8px; padding: 6px; text-align: center; }
.kline-multi { display: flex; flex-direction: column; gap: 6px;
  background: rgba(0,0,0,.25); border: 1px solid var(--gd-border); border-radius: 8px; padding: 8px; }
.mini-row { display: flex; align-items: center; gap: 8px; }
.mini-date { width: 36px; font-size: 10px; color: var(--gd-text-muted);
  font-family: var(--gd-font-mono); flex-shrink: 0; }
.mini-pct { width: 54px; font-size: 10px; text-align: right; font-family: var(--gd-font-mono); flex-shrink: 0; }
.kline-empty { font-size: 11px; color: var(--gd-text-muted); text-align: center; padding: 12px 0; }

/* K线展开/收起过渡动画 */
.kline-expand-enter-active,
.kline-expand-leave-active {
  transition: all 0.28s cubic-bezier(0.4, 0, 0.2, 1);
  overflow: hidden;
}
.kline-expand-enter-from,
.kline-expand-leave-to {
  max-height: 0;
  opacity: 0;
  padding-top: 0;
  padding-bottom: 0;
  transform: translateY(-4px);
}
.kline-expand-enter-to,
.kline-expand-leave-from {
  max-height: 200px;
  opacity: 1;
  padding-top: 0;
  padding-bottom: 10px;
}

/* 状态色 */
.up { color: var(--gd-up); }
.down { color: var(--gd-down); }
.flat { color: var(--gd-flat); }
.panel-footer { display: flex; align-items: center; gap: 10px; padding: 6px 14px; font-size: 10px; color: var(--gd-text-muted); }
.refresh-failed { color: #e5484d; }
.session.on { color: var(--gd-up); }
.session.lunch { color: var(--gd-flat); }
.last-update { font-family: var(--gd-font-mono); }

/* 加载骨架屏 */
.loading-skeleton { padding: 8px 4px; display: flex; flex-direction: column; gap: 12px; }
.skeleton-row { display: flex; gap: 6px; padding: 10px 8px; border-radius: 10px; }
.skeleton-col { background: rgba(255,255,255,.06); border-radius: 6px; position: relative; overflow: hidden; }
.skeleton-col::after {
  content: ''; position: absolute; inset: 0;
  background: linear-gradient(90deg, transparent, rgba(255,255,255,.08), transparent);
  animation: skeleton-shimmer 1.4s infinite;
}
.skeleton-name { flex: 1.6; height: 32px; }
.skeleton-pos { width: 96px; height: 32px; }
.skeleton-quote { width: 108px; height: 32px; }
.skeleton-pnl { width: 96px; height: 32px; }
@keyframes skeleton-shimmer {
  0% { transform: translateX(-100%); }
  100% { transform: translateX(100%); }
}
</style>
