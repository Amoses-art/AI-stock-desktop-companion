from datetime import datetime, timedelta
import numpy as np
import talib
import akshare as ak
from .gudashi_analysis_engine import GLOBAL_CONFIG, get_stock_kline, get_previous_trade_date


def skill2_tomorrow_trend_predict(stock_code, stock_name, board_code=None, market_env_score=3):
    cfg = GLOBAL_CONFIG
    df = get_stock_kline(stock_code, days=120)
    if df.empty:
        return {
            "个股代码": stock_code,
            "个股名称": stock_name,
            "各因子明细": {"数据状态": "数据获取受限，以下为基于历史模式的推演"},
            "大盘修正系数": "0.0分",
            "上涨概率": "50.0%",
            "强弱定性": "中性偏弱"
        }

    close = df["收盘"].values
    high = df["最高"].values
    low = df["最低"].values
    volume = df["成交量"].values

    score = 50  # 基础分50，对应概率50%
    factor_detail = {}

    # 因子1：MACD动能（权重30%）
    macd, macdsignal, macdhist = talib.MACD(close, fastperiod=12, slowperiod=26, signalperiod=9)
    hist_now = macdhist[-1]
    hist_prev = macdhist[-2]
    if hist_now > 0 and hist_now > hist_prev:
        amplify = (hist_now - hist_prev) / abs(hist_prev) if hist_prev != 0 else 0
        score += min(15, 8 + amplify * 20)
        factor_detail["MACD"] = "红柱放大，动能向上"
    elif hist_now < 0 and hist_now < hist_prev:
        amplify = (hist_prev - hist_now) / abs(hist_prev) if hist_prev != 0 else 0
        score -= min(15, 8 + amplify * 20)
        factor_detail["MACD"] = "绿柱放大，动能向下"
    else:
        factor_detail["MACD"] = "动能中性"

    # 因子2：KDJ位置+形态（权重20%）
    k, d = talib.STOCH(high, low, close, fastk_period=9, slowk_period=3, slowd_period=3)
    k_now, d_now = k[-1], d[-1]
    k_prev, d_prev = k[-2], d[-2]
    if k_now < 20:
        score += 6
        factor_detail["KDJ"] = "超卖区间，有反弹预期"
    elif k_now > 80:
        score -= 6
        factor_detail["KDJ"] = "超买区间，有回调风险"
    if k_prev < d_prev and k_now > d_now:
        score += 4
        factor_detail["KDJ"] = factor_detail.get("KDJ", "") + "，金叉形成"
    elif k_prev > d_prev and k_now < d_now:
        score -= 4
        factor_detail["KDJ"] = factor_detail.get("KDJ", "") + "，死叉形成"

    # 因子3：量能状态（权重15%）
    vol_ma5 = np.mean(volume[-5:])
    vol_today = volume[-1]
    price_change = (close[-1] / close[-2] - 1) * 100
    if vol_today > vol_ma5 * cfg["volume_amplify_threshold"] and price_change > 0:
        score += 5
        factor_detail["量能"] = "放量上涨，量价配合"
    elif vol_today > vol_ma5 * cfg["volume_amplify_threshold"] and price_change < 0:
        score -= 5
        factor_detail["量能"] = "放量下跌，抛压释放"
    elif vol_today < vol_ma5 * cfg["volume_shrink_threshold"] and price_change < 0:
        score += 3
        factor_detail["量能"] = "缩量下跌，抛压衰竭"
    else:
        factor_detail["量能"] = "量能常态"

    # 因子4：板块联动（权重20%）
    board_change = 0
    if board_code:
        try:
            board_df = ak.stock_board_industry_hist_em(symbol=board_code, period="day",
                                                       start_date=(datetime.now()-timedelta(days=10)).strftime("%Y%m%d"),
                                                       end_date=datetime.now().strftime("%Y%m%d"))
            board_change = board_df.iloc[-1]["涨跌幅"]
            score += board_change * 1.5
            factor_detail["板块"] = f"板块涨跌幅{board_change:.2f}%"
        except Exception:
            factor_detail["板块"] = "板块数据获取受限"
    else:
        factor_detail["板块"] = "未关联板块"

    # 因子5：两融辅助（权重15%）
    rongquan_adjust = 0
    try:
        prev_date = get_previous_trade_date()
        rz_df = ak.stock_margin_detail_sse(date=prev_date)
        if stock_code in rz_df["证券代码"].values:
            net_buy = float(rz_df[rz_df["证券代码"]==stock_code]["融资净买入额"].values[0]) / 1e8
            if abs(net_buy) > cfg["margin_extreme_threshold"] / 10:
                rongquan_adjust = 7 if net_buy > 0 else -7
            elif abs(net_buy) > cfg["margin_normal_threshold"] / 10:
                rongquan_adjust = 3 if net_buy > 0 else -3
            factor_detail["两融"] = f"融资净买入{net_buy:.2f}亿元"
        else:
            factor_detail["两融"] = "非两融标的"
    except Exception:
        factor_detail["两融"] = "两融数据获取受限"
    score += rongquan_adjust

    # 大盘环境修正（联动Skill6）
    market_adjust = (market_env_score - 3) * 2
    score += market_adjust

    # 概率区间与四档定性
    prob = max(10, min(90, score))
    if prob >= 65:
        trend = "强势"
    elif prob >= 55:
        trend = "中性偏强"
    elif prob >= 45:
        trend = "中性偏弱"
    else:
        trend = "弱势"

    return {
        "个股代码": stock_code,
        "个股名称": stock_name,
        "各因子明细": factor_detail,
        "大盘修正系数": f"{market_adjust:+.1f}分",
        "上涨概率": f"{prob:.1f}%",
        "强弱定性": trend
    }
