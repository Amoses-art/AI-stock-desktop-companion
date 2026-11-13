/**
 * 浏览器 Mock 数据源（仅 dev 构建加载，生产路径剥离）
 *
 * 用途：?mock=1 时在纯浏览器中开发 UI，无需 Tauri/Python 环境。
 * 覆盖 rpc.ts 契约命令的最小行为集。
 */
import type {
  AiState,
  AlertRule,
  Holding,
  QuoteData,
} from "./contracts";

const holdings: Holding[] = [
  { id: 1, symbol: "000001", name: "平安银行", market: "cn", asset_type: "stock", quantity: 1000, cost_price: 11.2, currency: "CNY", current_price: 11.76, change_percent: 1.2, pnl_amount: 560, pnl_percent: 5.0 },
  { id: 2, symbol: "600519", name: "贵州茅台", market: "cn", asset_type: "stock", quantity: 100, cost_price: 1450, currency: "CNY", current_price: 1521.35, change_percent: 0.8, pnl_amount: 7135, pnl_percent: 4.92 },
  { id: 3, symbol: "510300", name: "沪深300ETF", market: "cn", asset_type: "fund", quantity: 20000, cost_price: 3.85, currency: "CNY", current_price: 3.92, change_percent: -0.3, pnl_amount: 1400, pnl_percent: 1.82 },
];

const alerts: AlertRule[] = [
  { id: 1, portfolio_id: 1, threshold_percent: 3, direction: "up", is_active: true, cooldown_minutes: 30 },
];

const aiState: AiState = { ai_enabled: false, ai_status: "disabled" };

/** 模拟价格波动 */
function jitter(base: number): number {
  return Math.round(base * (1 + (Math.random() - 0.5) * 0.004) * 100) / 100;
}

function makeQuote(h: Holding): QuoteData {
  const price = jitter(h.current_price);
  const pre = jitter(h.current_price * 0.99);
  const pct = ((price - pre) / pre) * 100;
  return {
    symbol: h.symbol,
    name: h.name,
    market: h.market as QuoteData["market"],
    asset_type: h.asset_type as QuoteData["asset_type"],
    current_price: price,
    pre_close: pre,
    open_price: pre,
    high_price: Math.max(price, pre) * 1.002,
    low_price: Math.min(price, pre) * 0.998,
    change_amount: Math.round((price - pre) * 100) / 100,
    change_percent: Math.round(pct * 100) / 100,
    volume: 8_000_000,
    turnover: 95_000_000,
  };
}

let nextId = 100;

export async function handle<T>(command: string, args?: any): Promise<T> {
  // 模拟网络延迟，便于调试加载态
  await new Promise((r) => setTimeout(r, 200));

  switch (command) {
    case "portfolio.list":
      return holdings as T;
    case "portfolio.add": {
      const h = { id: nextId++, ...args } as Holding;
      holdings.push(h);
      return h as T;
    }
    case "portfolio.remove": {
      const i = holdings.findIndex((h) => h.symbol === args?.symbol);
      if (i >= 0) holdings.splice(i, 1);
      return undefined as T;
    }
    case "quote.get": {
      const h = holdings.find((x) => x.symbol === args?.symbol);
      return (h ? makeQuote(h) : null) as T;
    }
    case "quote.resolve": {
      // Mock 解析：命中已知持仓返回真实名称；未命中返回 found:false（静默，不阻塞）
      const sym = String(args?.symbol || "").trim();
      if (!sym) throw new Error("证券代码不能为空");
      const h = holdings.find((x) => x.symbol === sym);
      if (!h) {
        return { found: false, symbol: sym, market: "cn", asset_type: args?.asset_type ?? "stock" } as T;
      }
      return {
        found: true,
        symbol: h.symbol,
        name: h.name,
        market: h.market,
        asset_type: args?.asset_type ?? "stock",
        current_price: h.current_price,
        pre_close: h.cost_price,
      } as T;
    }
    case "kline.get": {
      // Mock 分时：生成 48 个点（09:30-11:30 / 13:00-15:00）
      const sym = String(args?.symbol || "");
      const days = Math.min(Math.max(Number(args?.days ?? 1), 1), 5);
      const base = holdings.find((x) => x.symbol === sym)?.current_price ?? 10;
      const series = [];
      for (let d = 0; d < days; d++) {
        const points = [];
        for (let i = 0; i < 48; i++) {
          const hm = i < 24 ? 540 + i : 780 + (i - 24);
          const label = `${String(Math.floor(hm / 60)).padStart(2, "0")}:${String(hm % 60).padStart(2, "0")}`;
          points.push({
            t: label,
            price: Math.round(base * (1 + (Math.sin(i / 5) + Math.random() * 0.2 - 0.1) * 0.02) * 100) / 100,
            vol: Math.round(10000 + Math.random() * 90000),
          });
        }
        series.push({ date: `2026091${9 - d}`, points });
      }
      return { symbol: sym, market: args?.market ?? "cn", days, pre_close: base * 0.99, series } as T;
    }
    case "quote.refresh":
      return holdings.map(makeQuote) as T;
    case "alert.list":
      return alerts as T;
    case "alert.add": {
      const rule = { id: nextId++, ...args } as AlertRule;
      alerts.push(rule);
      return rule as T;
    }
    case "alert.remove": {
      const i = alerts.findIndex((r) => r.id === args?.id);
      if (i >= 0) alerts.splice(i, 1);
      return undefined as T;
    }
    case "config.get":
      return null as T;
    case "config.set":
      return undefined as T;
    case "ai.get_state":
      return aiState as T;
    case "ai.enable":
      aiState.ai_enabled = true;
      aiState.ai_status = "ready";
      return undefined as T;
    case "ai.disable":
      aiState.ai_enabled = false;
      aiState.ai_status = "disabled";
      return undefined as T;
    case "skill.execute": {
      // 模拟 Python handle_chat 返回格式
      const msg = (args?.input as any)?.message || (args as any)?.message || "";
      let reply = "我是股大师~ 试试问我持仓、行情、提醒？";
      let intent = "default";
      if (/持仓|赚|亏|盈亏/.test(msg)) {
        reply = "当前持仓：平安银行 +560元 (5.0pct)，贵州茅台 +7135元 (4.92pct)，合计盈利约 7695 元。";
        intent = "portfolio_query";
      } else if (/多少钱|行情|价/.test(msg)) {
        reply = "Mock 行情：平安银行 11.76 (+1.20pct)，贵州茅台 1521.35 (+0.80pct)。";
        intent = "quote_query";
      } else if (/提醒|告警|设置/.test(msg)) {
        reply = "好的，已为你添加涨跌幅 3pct 的提醒规则。";
        intent = "alert_set";
      } else if (/推荐|选股/.test(msg)) {
        reply = "Mock 推荐：平安银行、贵州茅台、宁德时代（仅供参考）。";
        intent = "trend_recommendation";
      } else if (msg) {
        reply = "Mock NLU 收到：" + msg.substring(0, 30) + " — 生产模式调 Python handle_chat。";
      }
      return {
        skill_name: "chat",
        result: { reply, intent, nlu_tier: 1, nlu_confidence: 0.9 ,
      thinking_steps: [{step:"NLU",elapsed_ms:2},{step:"Handler",elapsed_ms:6},{step:"LLM",elapsed_ms:35000}],
      reply_source: "mock"},
        warnings: [],
        execution_time_ms: 150,
        request_id: args?.request_id || Date.now(),
      } as T;
    }
    case "chat_history.list": {
      // Return some mock history
      const msgs = [
        { role: "user", content: "你好", intent: "default", ts: new Date(Date.now() - 3600000).toISOString() },
        { role: "assistant", content: "您好！我是股大师，有什么可以帮您？", intent: "default", ts: new Date(Date.now() - 3600000).toISOString() },
        { role: "user", content: "帮我看看持仓", intent: "default", ts: new Date(Date.now() - 1800000).toISOString() },
        { role: "assistant", content: "当前持仓：平安银行 +560元，贵州茅台 +7135元。", intent: "portfolio_query", ts: new Date(Date.now() - 1800000).toISOString() },
      ];
      return { messages: msgs } as T;
    }
    case "chat_history.clear":
      return undefined as T;
    default:
      throw new Error(`[mock] 未实现的命令: ${command}`);
  }
}
