/**
 * 信息条轮播（M2-1）
 *
 * 持仓 > 0 时：固定展示【当日总计浮动盈亏】+【盈亏比例】
 * 持仓 = 0 时：显示"暂无持仓"
 */
import { computed, onUnmounted, ref } from "vue";
import { usePortfolioStore } from "@/stores/portfolio";

export interface TickerItem {
  kind: "summary";       // 只显示汇总
  dailyAmount: number;   // 当日浮动盈亏金额
  dailyPercent: number;  // 当日浮动盈亏比例(%)
}

export function useTicker(intervalMs = 3000) {
  const portfolio = usePortfolioStore();
  const tickerIndex = ref(0);
  let timer: ReturnType<typeof setInterval> | null = null;

  /** 只有一个汇总项，长度为 0 或 1 */
  const tickerList = computed(() => {
    if (portfolio.holdings.length === 0) return [];
    return [{
      kind: "summary" as const,
      dailyAmount: portfolio.totalDailyPnl,
      dailyPercent: portfolio.totalDailyPnlPercent,
    }];
  });

  const tickerItem = computed<TickerItem | null>(() => {
    if (tickerList.value.length === 0) return null;
    return tickerList.value[tickerIndex.value % tickerList.value.length];
  });

  function start(): void {
    timer = setInterval(() => {
      if (tickerList.value.length > 0) {
        tickerIndex.value = (tickerIndex.value + 1) % tickerList.value.length;
      }
    }, intervalMs);
  }

  function stop(): void {
    if (timer) clearInterval(timer);
    timer = null;
  }

  onUnmounted(stop);

  return { tickerList, tickerItem, tickerIndex, start, stop };
}
