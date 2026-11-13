/**
 * RPC 统一出口
 *
 * - 前端唯一 invoke 通道，业务代码禁止直接 import @tauri-apps/api
 * - 命令名对齐契约冻结表 v3.2（点分式）；Rust 标识符不支持点，
 *   统一按 `.` → `_` 规则转换（如 portfolio.list → portfolio_list）
 * - dev 模式下 ?mock=1 启用浏览器内 Mock（生产构建剥离）
 */
import type {
  AiState,
  AlertRule,
  Holding,
  KlineData,
  NewAlertRule,
  QuoteData,
  QuoteResolve,
  RpcResult,
} from "./contracts";
import { invoke } from "@tauri-apps/api/core";

/** 是否处于浏览器 Mock 模式（仅 dev 构建且显式 ?mock=1） */
export const isMockMode: boolean =
  import.meta.env.DEV &&
  new URLSearchParams(window.location.search).get("mock") === "1";

/** Mock 实现（动态导入，生产构建不打包） */
let mockImpl: typeof import("./mock") | null = null;
async function loadMock() {
  if (!mockImpl) {
    mockImpl = await import("./mock");
  }
  return mockImpl;
}

/** 统一 invoke：Mock 模式走 mock.ts，否则走 Tauri
 *
 * Tauri v2 Result<T, String> 语义：
 * - 成功 → 返回 T 的值（不是 RpcResult 包装）
 * - 失败 → throw Error(message)
 * 所以不需要检查 result.ok，直接返回 invoke 结果即可
 */
export async function rpc<T>(
  command: string,
  args?: Record<string, unknown>,
): Promise<T> {
  if (isMockMode) {
    const m = await loadMock();
    return m.handle<T>(command, args);
  }
  const target = command.replace(/\./g, "_");
  console.log('[rpc] invoking', command, '->', target, args);
  // invoke 成功直接返回 T；失败 throw Error（带 Rust 返回的 String）
  return invoke<T>(target, args);
}

/** 通用 Python RPC：走 Rust python_call → Python bridge
 *
 * 用于前端尚未显式注册为 Rust command 的 Python RPC 方法（如 chat_history.*）。
 * Mock 模式下自动回退到 mock.ts。
 */
export async function rpcPython<T>(
  method: string,
  params?: Record<string, unknown>,
): Promise<T> {
  if (isMockMode) {
    const m = await loadMock();
    return m.handle<T>(method, params);
  }
  return invoke<T>('python_call', { method, params: params || {} });
}

// ---------- 类型安全的业务 API ----------

export const api = {
  // 持仓
  listHoldings: () => rpc<Holding[]>("portfolio.list"),
  addHolding: (h: {
    symbol: string;
    name: string;
    market: string;
    asset_type: string;
    quantity: number;
    cost_price: number;
    currency?: string;
    /** 自定义涨跌幅提醒阈值（1-20%），不传则使用默认 3% */
    alert_threshold?: number | null;
  }) => rpc<Holding>("portfolio.add", { ...h, alert_threshold: h.alert_threshold ?? null }),
  removeHolding: (id: number) => rpc<void>("portfolio.remove", { id }),

  // 行情
  getQuote: (symbol: string) => rpc<QuoteData>("quote.get", { symbol }),
  /** 解析证券代码 → 名称/市场（自动填充；localOnly=true 仅本地毫秒级查询，不联网） */
  resolveQuote: (
    symbol: string,
    assetType = "stock",
    opts: { localOnly?: boolean } = {},
  ) =>
    rpc<QuoteResolve>("quote.resolve", {
      symbol,
      asset_type: assetType,
      local_only: opts.localOnly ?? false,
    }),
  /** 分时K线（days=1 当日分时 / days=2-5 近N日分时趋势） */
  getKline: (symbol: string, opts: { market?: string; asset_type?: string; days?: number } = {}) =>
    rpc<KlineData>("kline.get", {
      symbol,
      market: opts.market ?? "",
      asset_type: opts.asset_type ?? "stock",
      days: opts.days ?? 1,
    }),
  /** 手动刷新（契约 v3.2：symbols 空 = 全量持仓；force 绕过交易窗口与缓存） */
  refreshQuotes: (symbols: string[], force = true) =>
    rpc<QuoteData[]>("quote.refresh", { symbols, force }),

  // 提醒
  listAlerts: () => rpc<AlertRule[]>("alert.list"),
  addAlert: (rule: NewAlertRule) => rpc<AlertRule>("alert.add", { ...rule }),
  removeAlert: (id: number) => rpc<void>("alert.remove", { id }),

  // 配置
  getConfig: () => rpc<Record<string, unknown>>("config.get"),
  setConfig: (key: string, value: unknown) =>
    rpc<void>("config.set", { key, value }),

  // AI 层
  getAiState: () => rpc<AiState>("ai.get_state"),
  enableAi: () => rpc<void>("ai.enable"),
  disableAi: () => rpc<void>("ai.disable"),

  // Skill（AI 层）— 按 Rust skill_execute 签名组装：{ skill_name, input }
  executeSkill: (message: string, requestId: number) =>
    rpc<unknown>("skill.execute", {
      skill_name: "chat",
      input: { message, request_id: requestId },
    }),
  cancelSkill: (requestId: string) =>
    rpc<void>("skill.cancel", { request_id: requestId }),

  chatHistoryList: (limit = 50) =>
    rpcPython<{ messages: Array<{ role: string; content: string; intent: string; ts: string }> }>("chat_history.list", { session_id: "default", limit }),

  chatHistoryClear: () =>
    rpcPython<{ cleared: boolean }>("chat_history.clear", { session_id: "default" }),
};
