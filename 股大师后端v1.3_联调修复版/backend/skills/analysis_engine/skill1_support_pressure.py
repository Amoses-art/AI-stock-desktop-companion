import numpy as np
import talib
from .gudashi_analysis_engine import GLOBAL_CONFIG, get_stock_kline


def skill1_support_pressure_review(stock_code, stock_name, trade_date=None):
    cfg = GLOBAL_CONFIG
    df = get_stock_kline(stock_code, period="daily", days=120)
    if df.empty:
        return {
            "个股代码": stock_code,
            "个股名称": stock_name,
            "最新收盘价": None,
            "第一支撑": None,
            "第二支撑": None,
            "强支撑": None,
            "第一压力": None,
            "第二压力": None,
            "强压力": None,
            "收盘区间": "数据获取受限",
            "区间强度得分": 0,
            "昨日支撑压力验证": "数据获取受限，无法验证"
        }

    close = df["收盘"].values
    high = df["最高"].values
    low = df["最低"].values
    volume = df["成交量"].values
    latest_close = close[-1]

    # 均线层计算
    ma5 = talib.MA(close, timeperiod=5)[-1]
    ma10 = talib.MA(close, timeperiod=10)[-1]
    ma20 = talib.MA(close, timeperiod=20)[-1]
    ma60 = talib.MA(close, timeperiod=60)[-1]

    # 高低点层计算
    low_20d = np.min(low[-20:])
    low_60d = np.min(low[-60:])
    high_20d = np.max(high[-20:])
    high_60d = np.max(high[-60:])

    # 筹码峰计算
    def calc_chip_peak(price_arr, vol_arr, bins=100):
        p_min, p_max = np.min(price_arr), np.max(price_arr)
        bins_edge = np.linspace(p_min, p_max, bins+1)
        vol_dist = np.zeros(bins)
        for i in range(bins):
            mask = (price_arr >= bins_edge[i]) & (price_arr < bins_edge[i+1])
            vol_dist[i] = np.sum(vol_arr[mask])
        peak_idx = np.argmax(vol_dist)
        return (bins_edge[peak_idx] + bins_edge[peak_idx+1]) / 2

    chip_peak_20d = calc_chip_peak(close[-20:], volume[-20:])
    chip_peak_60d = calc_chip_peak(close[-60:], volume[-60:])

    # 三档支撑压力最终判定
    support_1 = min(ma5, ma10)
    support_2 = min(low_20d, chip_peak_20d)
    support_strong = min(low_60d, chip_peak_60d, ma60)
    pressure_1 = ma20
    pressure_2 = max(high_20d, chip_peak_20d)
    pressure_strong = max(high_60d, chip_peak_60d)

    # 四档区间定性
    if latest_close >= pressure_strong:
        zone = "强势区"
        zone_score = 4
    elif latest_close >= pressure_1:
        zone = "中性偏强"
        zone_score = 3
    elif latest_close >= support_1:
        zone = "中性偏弱"
        zone_score = 2
    else:
        zone = "弱势区"
        zone_score = 1

    # 昨日推演验证
    yesterday_hit = "区间内运行，支撑压力未触发"
    if len(close) >= 2:
        yest_low = low[-2]
        yest_high = high[-2]
        if yest_low <= support_2 and yest_low >= support_strong * 0.99:
            yesterday_hit = "支撑位有效，低点触及第二支撑"
        elif yest_high >= pressure_2 and yest_high <= pressure_strong * 1.01:
            yesterday_hit = "压力位有效，高点触及第二压力"

    return {
        "个股代码": stock_code,
        "个股名称": stock_name,
        "最新收盘价": round(latest_close, 2),
        "第一支撑": round(support_1, 2),
        "第二支撑": round(support_2, 2),
        "强支撑": round(support_strong, 2),
        "第一压力": round(pressure_1, 2),
        "第二压力": round(pressure_2, 2),
        "强压力": round(pressure_strong, 2),
        "收盘区间": zone,
        "区间强度得分": zone_score,
        "昨日支撑压力验证": yesterday_hit
    }
