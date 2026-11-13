/**
 * 持仓 store：持仓清单 + 行情快照 + 提醒规则
 *
 * 数据流：RPC 拉取 / quote:tick 事件 → store → 组件单向渲染。
 */
import { defineStore } from "pinia";
import { computed, ref } from "vue";
import { api } from "@/core/rpc";
import { on, SubscriptionGroup } from "@/core/events";
import type {
  AlertEvent,
  AlertRule,
  Holding,
  NewAlertRule,
  QuoteData,
} from "@/core/contracts";

export const usePortfolioStore = defineStore("portfolio", () => {
  const subs = new SubscriptionGroup();

  const holdings = ref<Holding[]>([]);
  const quotes = ref<Record<string, QuoteData>>({});
  const alerts = ref<AlertRule[]>([]);
  const alertFeed = ref<AlertEvent[]>([]); // 提醒事件流（未读红点数据源）
  const lastRefreshAt = ref<number | null>(null);
  const refreshing = ref(false);
  /** 0.6.0（用户实测反馈1）：刷新失败可感知——
   *  旧逻辑 RPC 失败静默吞异常，时间戳停留旧值，用户无从得知刷新没成功 */
  const refreshFailed = ref(false);
  const loading = ref(true);  // 首次加载 + reload 期间为 true

  // ---------- 派生数据 ----------
  /** 个股（stock）与基金（fund_open/etf/lof 等）双标签清单 */
  const stockList = computed(() => holdings.value.filter((h) => h.asset_type === "stock"));
  const fundList = computed(() => holdings.value.filter((h) => h.asset_type !== "stock"));


/** 安全取昨收价：优先 quote.pre_close，fallback 用 change_percent 反推 */
function safeQuotePreClose(h: typeof holdings.value[0]): number {
  const q = quotes.value[h.symbol];
  if (q?.pre_close && q.pre_close > 0) return q.pre_close;
  const price = q?.current_price ?? h.current_price;
  const chg = q?.change_percent ?? h.change_percent;
  if (Number.isFinite(price) && Number.isFinite(chg) && chg > -99.99) {
    const pc = price / (1 + chg / 100);
    if (pc > 0) return pc;
  }
  return 0;
}
  /** 总盈亏比例（后端逐项计算；空持仓/异常数据返回 0，驱动桌宠情绪） */
  const totalPnlPercent = computed(() => {
    if (holdings.value.length === 0) return 0;
    let cost = 0;
    let value = 0;
    for (const h of holdings.value) {
      const q = quotes.value[h.symbol];
      const price = q?.current_price ?? h.current_price;
      if (!Number.isFinite(price) || !Number.isFinite(h.cost_price)) continue;
      cost += h.cost_price * h.quantity;
      value += price * h.quantity;
    }
    if (cost <= 0) return 0;
    const pct = ((value - cost) / cost) * 100;
    return Number.isFinite(pct) ? pct : 0;
  });


  /** 总盈亏金额：Σ (现价 - 成本) × 数量（持仓管理弹窗抬头展示） */
  const totalPnlAmount = computed(() => {
    if (holdings.value.length === 0) return 0;
    let amount = 0;
    for (const h of holdings.value) {
      const q = quotes.value[h.symbol];
      const price = q?.current_price ?? h.current_price;
      if (!Number.isFinite(price) || !Number.isFinite(h.cost_price)) continue;
      amount += (price - h.cost_price) * h.quantity;
    }
    return Number.isFinite(amount) ? amount : 0;
  });


  /** 当日浮动盈亏（金额）：Σ (现价 - 昨收) × 持仓数量 */
  const totalDailyPnl = computed(() => {
    if (holdings.value.length === 0) return 0;
    let amount = 0;
    for (const h of holdings.value) {
      const q = quotes.value[h.symbol];
      const price = q?.current_price ?? h.current_price;
      const preClose = safeQuotePreClose(h);
      if (!Number.isFinite(price) || preClose <= 0 || !Number.isFinite(h.quantity)) continue;
      amount += (price - preClose) * h.quantity;
    }
    return Number.isFinite(amount) ? amount : 0;
  });

  /** 当日浮动盈亏比例（%）：Σ (现价 - 昨收) × Q / Σ 昨收市值 */
  const totalDailyPnlPercent = computed(() => {
    if (holdings.value.length === 0) return 0;
    let dailyPnl = 0;
    let preMarketValue = 0;  // 昨日总市值 = Σ pre_close × Q
    for (const h of holdings.value) {
      const q = quotes.value[h.symbol];
      const price = q?.current_price ?? h.current_price;
      const preClose = safeQuotePreClose(h);
      if (preClose <= 0 || !Number.isFinite(h.quantity)) continue;
      dailyPnl += (price - preClose) * h.quantity;
      preMarketValue += preClose * h.quantity;
    }
    if (preMarketValue <= 0) return 0;
    const pct = (dailyPnl / preMarketValue) * 100;
    return Number.isFinite(pct) ? pct : 0;
  });
  const unreadAlertCount = computed(() => alertFeed.value.length);

  // ---------- 动作 ----------
  async function init(): Promise<void> {
    subs.add(on("quote:tick", (list) => applyQuotes(list)));
    subs.add(on("quote:alert", (events) => {
      alertFeed.value.push(...events);
    }));
    // 持仓增删改后跨窗口同步（桌宠窗口/面板窗口各自 reload）
    subs.add(on("portfolio:changed", () => {
      void reload();
    }));
    await reload();
  }

  async function reload(): Promise<void> {
    loading.value = true;
    try {
      const [h, a] = await Promise.all([
        api.listHoldings(),
        api.listAlerts().catch(() => [] as AlertRule[]),
      ]);
      holdings.value = h;
      alerts.value = a;
      // 清理不再持有的标的的旧提醒（防止删除持仓后仍显示该标的的历史提醒）
      const heldSymbols = new Set(h.map((x) => x.symbol));
      alertFeed.value = alertFeed.value.filter((e) => heldSymbols.has(e.symbol));
    } finally {
      loading.value = false;
    }
  }

  async function addHolding(input: {
    symbol: string;
    name: string;
    market: string;
    asset_type: string;
    quantity: number;
    cost_price: number;
    currency?: string;
    alert_threshold?: number | null;
  }): Promise<void> {
    await api.addHolding(input);
    await reload();
  }

  async function removeHolding(id: number): Promise<void> {
    await api.removeHolding(id);
    const h = holdings.value.find((x) => x.id === id);
    if (h) delete quotes.value[h.symbol];
    await reload();
  }

  async function addAlert(rule: NewAlertRule): Promise<void> {
    await api.addAlert(rule);
    alerts.value = await api.listAlerts();
  }

  async function removeAlert(id: number): Promise<void> {
    await api.removeAlert(id);
    alerts.value = await api.listAlerts();
  }

  /** 手动刷新（绕过交易窗口，PRD v3.1 §2.3；symbols 空 = 后端刷新全量持仓） */
  async function manualRefresh(): Promise<void> {
    if (refreshing.value) return;
    refreshing.value = true;
    try {
      const symbols = holdings.value.map((h) => h.symbol);
      const list = await api.refreshQuotes(symbols);
      applyQuotes(list);
      refreshFailed.value = false;
    } catch (err) {
      // 0.6.0：刷新失败不再静默——面板状态栏提示，便于用户重试
      console.error("[portfolio] manualRefresh failed:", err);
      refreshFailed.value = true;
    } finally {
      refreshing.value = false;
    }
  }

  function applyQuotes(list: QuoteData[]): void {
    for (const q of list) {
      quotes.value[q.symbol] = q;
    }
    lastRefreshAt.value = Date.now();
  }

  /** 用户查看提醒列表后清空未读 */
  function clearAlertFeed(): void {
    alertFeed.value = [];
  }

  function dispose(): void {
    subs.dispose();
  }

  return {
    holdings,
    quotes,
    alerts,
    alertFeed,
    lastRefreshAt,
    refreshing,
    refreshFailed,
    loading,
    stockList,
    fundList,
    totalPnlPercent,
    totalPnlAmount,
    totalDailyPnl,
    totalDailyPnlPercent,
    unreadAlertCount,
    init,
    reload,
    addHolding,
    removeHolding,
    addAlert,
    removeAlert,
    manualRefresh,
    clearAlertFeed,
    dispose,
  };
});
