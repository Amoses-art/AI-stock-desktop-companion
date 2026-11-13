/**
 * IPC 契约类型定义
 *
 * 与《PRD v3.1 对齐文档》4.x 契约冻结表一一对应。
 * 字段变更规则：新增允许，删改禁止（需走版本协商）。
 */

// ---------- 基础数据结构 ----------

/** 行情快照（Python QuoteData 的前端镜像） */
export interface QuoteData {
  symbol: string;
  name: string;
  market: "cn" | "hk" | "us";
  asset_type: "stock" | "fund";
  current_price: number;
  pre_close: number;
  open_price: number;
  high_price: number;
  low_price: number;
  change_amount: number;
  change_percent: number;
  volume: number;
  turnover: number;
  /** 数据源快照时间（yyyymmddHHMMSS；M2-4 收盘态展示，旧数据可能缺失） */
  timestamp?: string;
}

/** 持仓项（对齐 Rust PortfolioItem / Python 后端返回） */
export interface Holding {
  id: number;
  symbol: string;
  name: string;
  market: string;
  asset_type: string;
  quantity: number;
  cost_price: number;
  currency: string;
  current_price: number;
  change_percent: number;
  pnl_amount: number;
  pnl_percent: number;
  /** 自定义涨跌幅提醒阈值（1-20%，替代默认 3%；未设置时为 null/缺省） */
  alert_threshold?: number | null;
  /** 代码无法匹配市场/类型 或 查询不到行情 → 【实时股价】列提示"代码错误" */
  quote_error?: boolean;
  /** 0.6.0：行情状态语义拆分——
   *  "code_invalid"：代码格式/市场不匹配 → 显示「代码错误」
   *  "data_pending"：代码合法但数据源未响应 → 显示「数据获取中」，
   *                 已有缓存价时优先显示缓存，取到最新行情后自动刷新
   *  "ok"：正常。缺省时按旧 quote_error 布尔兼容判断 */
  quote_state?: "ok" | "code_invalid" | "data_pending";
}

/** 代码解析结果（添加持仓自动填充 + 校验）
 *  - found=true：完整结果；found=false：本地未命中（不阻塞，名称手动填写）
 */
export interface QuoteResolve {
  /** local_only 未命中时为 false（前端静默跳过） */
  found?: boolean;
  symbol: string;
  name?: string;
  market: string;
  asset_type: string;
  current_price?: number;
  pre_close?: number;
}

/** 分时K线点 */
export interface KlinePoint {
  t: string; // "HH:MM" 标签
  price: number;
  vol: number;
}

/** 分时K线单日序列 */
export interface KlineSeries {
  date: string; // yyyymmdd
  points: KlinePoint[];
}

/** 分时K线响应（days=1 当日分时；days>1 近N日分时趋势） */
export interface KlineData {
  symbol: string;
  market: string;
  days: number;
  pre_close: number;
  series: KlineSeries[];
}

/** 阈值提醒规则 */
export interface AlertRule {
  id: number;
  portfolio_id: number;
  threshold_percent: number;
  direction: "up" | "down";
  is_active: boolean;
  cooldown_minutes: number;
}

/** 新建提醒规则参数（对齐 Rust NewAlertRule / Python 后端） */
export type NewAlertRule = Omit<AlertRule, "id">;

/** 提醒触发事件 */
export interface AlertEvent {
  symbol: string;
  name: string;
  current_price: number;
  trigger_type: "up" | "down" | "sudden";
  triggered_at: number;
  /** 扩展字段（契约允许新增）：涨跌幅（%） */
  percent?: number;
}

/** AI 能力状态（feature flag） */
export type AiStatus = "disabled" | "installing" | "ready" | "failed";

export interface AiState {
  ai_enabled: boolean;
  ai_status: AiStatus;
}

/** Ollama 引导进度（事件载荷） */
export interface OllamaProgress {
  phase: "detect" | "install" | "mirror" | "pull" | "done" | "error";
  percent: number;
  detail: string;
}

// ---------- RPC 返回包装 ----------

/** Python RPC 统一响应包装 */
export interface RpcResult<T> {
  ok: boolean;
  data?: T;
  error?: string;
}

// ---------- 桌宠状态机 ----------

/** 桌宠视觉状态（对应皮肤素材 6 态） */
export type PetVisualState =
  | "idle"
  | "happy"
  | "sad"
  | "blink"
  | "alert"
  | "sleep";

/** 状态机允许的转换表（blink 为瞬态，由渲染层叠加） */
export const PET_TRANSITIONS: Record<PetVisualState, PetVisualState[]> = {
  idle: ["happy", "sad", "alert", "sleep", "blink"],
  happy: ["idle", "alert", "sleep", "blink"],
  sad: ["idle", "alert", "sleep", "blink"],
  blink: ["idle", "happy", "sad", "alert", "sleep"],
  alert: ["idle", "happy", "sad", "sleep"],
  sleep: ["idle"], // 仅活动唤醒
};
