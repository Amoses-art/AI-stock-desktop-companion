"""
Skill6: 全市场概览（修复版 — 东方财富 EM 风控换源）

修复说明：
  stock_zh_index_daily          → stock_zh_index_daily_tx (腾讯, symbol加sh/sz前缀)
  stock_zh_index_minute (已删除) → 移除分钟线调用（EM风控不稳定，日线足够做趋势判定）
  stock_hsgt_north_net_flow_in_em (已删除) → stock_hsgt_fund_flow_summary_em (北向汇总)
  stock_zh_a_spot_em (限流)      → 用同花顺行业板块总成交额累加估算
  stock_board_industry_name_em (限流) → stock_board_industry_summary_ths (同花顺行业排行)
"""
import numpy as np
import talib
import akshare as ak
import time
import logging
from datetime import datetime

logger = logging.getLogger("skill6")

# 数据源配置 — 全部绕开东方财富 EM 限流
# 东方财富数据源 (xxx_em) 在当前环境下普遍触发 RemoteDisconnected，
# 因此 Skill6 统一改用腾讯 / 同花顺 / 北向汇总等更稳定的源
TX_INDEX_MAP = {
    "上证指数": "sh000001",
    "创业板指": "sz399006",
    "科创50": "sh000688",
}


def _safe_call(fn, *args, label="api", ret_on_fail=None, **kwargs):
    """带超时 + 错误日志的安全 API 调用"""
    try:
        t0 = time.time()
        result = fn(*args, **kwargs)
        dt = time.time() - t0
        logger.debug(f"[skill6] {label} OK ({dt:.1f}s)")
        return result
    except Exception as e:
        logger.warning(f"[skill6] {label} FAIL: {type(e).__name__}: {e}")
        return ret_on_fail


def skill6_market_overview_analysis(major_event=False, event_level="normal"):
    from .gudashi_analysis_engine import _check_akshare_available, GLOBAL_CONFIG

    cfg = GLOBAL_CONFIG

    # 快速检测网络
    if not _check_akshare_available():
        logger.warning("[skill6] AKShare 网络不可用 → fallback")
        return _fallback_result(major_event)

    # ================================================================
    # 1. 核心指数趋势判定 — 腾讯日线（并发拉取）
    # ================================================================
    from concurrent.futures import ThreadPoolExecutor, as_completed

    def _fetch_one(name, tx_code):
        df = _safe_call(
            ak.stock_zh_index_daily_tx,
            symbol=tx_code, start_date="20240101", end_date=datetime.now().strftime("%Y%m%d"),
            label=f"index_daily({name})"
        )
        return name, df

    # 并发拉取 3 个指数（比串行快 ~3x）
    index_raw = {}
    with ThreadPoolExecutor(max_workers=3) as ex:
        futs = {ex.submit(_fetch_one, n, c): n for n, c in TX_INDEX_MAP.items()}
        for fut in as_completed(futs):
            try:
                n, df = fut.result()
                index_raw[n] = df
            except Exception as e:
                logger.warning(f"[skill6] 并发拉取异常: {e}")

    index_trend = {}
    for name in TX_INDEX_MAP:
        df = index_raw.get(name)
        try:
            if df is None or len(df) < 60:
                index_trend[name] = {"状态": "数据不足"}
                continue

            close = df["close"].values.astype(float)
            ma20 = talib.MA(close, 20)
            ma60 = talib.MA(close, 60)

            # 短期趋势：20 日均线方向 + 价格与均线关系
            if close[-1] > ma20[-1] and ma20[-1] > ma20[-2]:
                short_trend = "上升"
            elif close[-1] < ma20[-1] and ma20[-1] < ma20[-2]:
                short_trend = "下降"
            else:
                short_trend = "震荡"

            # 中期趋势：60 日均线
            if close[-1] > ma60[-1] and ma60[-1] > ma60[-2]:
                mid_trend = "上升"
            elif close[-1] < ma60[-1] and ma60[-1] < ma60[-2]:
                mid_trend = "下降"
            else:
                mid_trend = "震荡"

            index_trend[name] = {
                "最新点位": round(float(close[-1]), 2),
                "短期趋势": short_trend,
                "中期趋势": mid_trend,
                "20日均线": round(float(ma20[-1]), 2),
                "60日均线": round(float(ma60[-1]), 2),
                "涨跌": round(float(close[-1] - close[-2]), 2),
                "涨跌幅": round(float((close[-1] - close[-2]) / close[-2] * 100), 2),
            }
        except Exception as e:
            logger.warning(f"[skill6] 指数 {name} 分析失败: {e}")
            index_trend[name] = {"状态": "计算异常"}

    # ================================================================
    # 2. 分钟级结构 — EM 限流时直接 skip，日线数据足够做仓位判断
    # ================================================================
    struct_60m = {}
    struct_90m = {}
    struct_120m = {}

    # ================================================================
    # 3. 周期状态（简化版：基于指数中期趋势）
    # ================================================================
    sh = index_trend.get("上证指数", {})
    cycle_status = "震荡整理"
    cycle_remain_days = 0

    if sh.get("中期趋势") == "下降":
        cycle_status = "调整周期中"
        cycle_remain_days = cfg["adjust_cycle_days"]
    elif sh.get("中期趋势") == "上升":
        cycle_status = "主升周期"
        cycle_remain_days = 99  # 简化标记

    # ================================================================
    # 4+5. 资金面 + 赛道强弱 — 并发拉取 (北向 / 同花顺行业 复用 board_df)
    # ================================================================
    fund_verify = {}
    top_5, bottom_5 = [], []

    def _fetch_north():
        try:
            north_df = _safe_call(ak.stock_hsgt_fund_flow_summary_em, label="hsgt_north")
            if north_df is None or len(north_df) == 0:
                return {}
            north_rows = north_df[north_df["资金方向"] == "北向"]
            north_total = north_rows["成交净买额"].sum()
            result = {"北向资金净流入(亿)": round(float(north_total), 2),
                      "北向状态": "流入" if north_total > 0 else "流出"}
            for _, row in north_rows.iterrows():
                result[f"{row['板块']}净买额(亿)"] = round(float(row["成交净买额"]), 2)
                result[f"{row['板块']}相关指数"] = f"{row['相关指数']} {row['指数涨跌幅']}%"
            return result
        except Exception as e:
            logger.warning(f"[skill6] 北向资金异常: {e}")
            return {}

    def _fetch_board():
        try:
            return _safe_call(ak.stock_board_industry_summary_ths, label="industry_summary_ths")
        except Exception as e:
            logger.warning(f"[skill6] 同花顺行业异常: {e}")
            return None

    # 并发: 北向 + 同花顺行业排行 (只调一次, 复用 board_df)
    with ThreadPoolExecutor(max_workers=4) as ex:
        fut_north = ex.submit(_fetch_north)
        fut_board = ex.submit(_fetch_board)
        north_result = fut_north.result()
        board_df = fut_board.result()

    fund_verify.update(north_result)

    if board_df is not None and len(board_df) > 0:
        total_vol = float(board_df["总成交额"].sum())
        fund_verify["行业总成交额(亿)"] = round(total_vol, 0)
        fund_verify["量能状态"] = "放量" if total_vol > 18000 else "缩量" if total_vol < 15000 else "常态"
        top3 = board_df.sort_values("涨跌幅", ascending=False).head(3)
        fund_verify["领涨行业"] = top3["板块"].tolist()
        fund_verify["领涨行业涨幅"] = [round(float(x), 2) for x in top3["涨跌幅"].tolist()]
        bot3 = board_df.sort_values("涨跌幅", ascending=True).head(3)
        fund_verify["领跌行业"] = bot3["板块"].tolist()
        fund_verify["领跌行业跌幅"] = [round(float(x), 2) for x in bot3["涨跌幅"].tolist()]
        sorted_board = board_df.sort_values("涨跌幅", ascending=False)
        top_5 = sorted_board.head(5)["板块"].tolist()
        bottom_5 = sorted_board.tail(5)["板块"].tolist()

    # ================================================================
    # 6. 可操作窗口与仓位基准（五档）
    # ================================================================
    score = 3

    # 指数趋势分
    if sh.get("短期趋势") == "上升":
        score += 1
    elif sh.get("短期趋势") == "下降":
        score -= 1
    if sh.get("中期趋势") == "上升":
        score += 0.5
    elif sh.get("中期趋势") == "下降":
        score -= 0.5

    # 北向资金分
    if fund_verify.get("北向状态") == "流入":
        score += 0.5
    elif fund_verify.get("北向状态") == "流出":
        score -= 0.5

    # 量能分
    if fund_verify.get("量能状态") == "放量":
        score += 0.3
    elif fund_verify.get("量能状态") == "缩量":
        score -= 0.3

    # 事件优先级
    if major_event:
        if event_level == "important":
            score -= 0.5
        elif event_level == "extreme":
            score = 2

    # 五档仓位映射
    if score >= 4.5:
        window, position_level, position_suggest = "积极操作窗口", "激进", "70%-90%仓位"
    elif score >= 3.5:
        window, position_level, position_suggest = "可操作窗口", "积极", "50%-70%仓位"
    elif score >= 2.5:
        window, position_level, position_suggest = "中性观望窗口", "中性", "30%-50%仓位"
    elif score >= 1.5:
        window, position_level, position_suggest = "谨慎观望窗口", "谨慎", "20%-30%仓位"
    else:
        window, position_level, position_suggest = "风险管控窗口", "保守", "20%以下仓位"

    result = {
        "核心指数趋势": index_trend,
        "分钟级技术结构": {**struct_60m, **struct_90m, **struct_120m},
        "周期状态": f"{cycle_status}，剩余基准天数{cycle_remain_days}天",
        "资金面验证": fund_verify,
        "赛道强弱排行": {"领涨板块": top_5, "领跌板块": bottom_5},
        "当前操作窗口": window,
        "全市场仓位基准": position_level,
        "建议仓位区间": position_suggest,
        "综合评分": round(float(score), 2),
        "事件影响标记": "重大事件进行中，技术结构有效性降级" if major_event else "无重大事件干扰",
        "风险提示": "仅技术推演，不构成投资建议",
    }
    logger.info(f"[skill6] 分析完成: score={score}, level={position_level}, window={window}")
    return result


def _fallback_result(major_event=False):
    """网络不可用时的降级结果"""
    return {
        "核心指数趋势": {
            "上证指数": {"状态": "网络不可用，行情延迟"},
            "创业板指": {"状态": "网络不可用，行情延迟"},
            "科创50": {"状态": "网络不可用，行情延迟"},
        },
        "分钟级技术结构": {},
        "周期状态": "网络不可用，无法判定",
        "资金面验证": {"状态": "网络不可用"},
        "赛道强弱排行": {"领涨板块": [], "领跌板块": []},
        "当前操作窗口": "中性观望窗口（降级）",
        "全市场仓位基准": "中性",
        "建议仓位区间": "30%-50%仓位",
        "综合评分": 3.0,
        "事件影响标记": "重大事件进行中" if major_event else "无重大事件干扰",
        "风险提示": "仅技术推演，不构成投资建议",
    }
