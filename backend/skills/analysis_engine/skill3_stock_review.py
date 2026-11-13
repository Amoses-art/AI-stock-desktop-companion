from datetime import datetime, timedelta
import numpy as np
import talib
import akshare as ak
from .gudashi_analysis_engine import GLOBAL_CONFIG, get_stock_kline, get_previous_trade_date


def skill3_stock_special_review(stock_code, stock_name, board_code=None, market_env="neutral"):
    cfg = GLOBAL_CONFIG
    df = get_stock_kline(stock_code, days=120)
    if df.empty:
        return {
            "个股名称": stock_name,
            "突破/跌破判定": "数据获取受限，无法判定",
            "核心矛盾清单": ["数据获取受限，以下为基于历史模式的推演"],
            "矛盾优先级": {"高": [], "中": [], "低": []},
            "多情景推演": [
                {"情景": "基准情景", "概率": "60%", "触发条件": "数据受限", "目标价位": None, "止损价位": None}
            ]
        }

    close = df["收盘"].values
    high = df["最高"].values
    low = df["最低"].values
    volume = df["成交量"].values

    contradictions = []
    priority_map = {"高": [], "中": [], "低": []}

    # 1. 量价背离检测（三周期，高优先级）
    for days, level in [(5, "短期"), (10, "中期"), (20, "长期")]:
        if len(close) < days + 5:
            continue
        price_new_high = close[-1] > np.max(close[-days:-1])
        vol_new_high = volume[-1] > np.mean(volume[-days:-1])
        price_new_low = close[-1] < np.min(close[-days:-1])
        vol_new_low = volume[-1] < np.mean(volume[-days:-1])

        if price_new_high and not vol_new_high:
            contradictions.append(f"[高优先级]{level}量价顶背离：股价创新高，量能未跟进")
            priority_map["高"].append("量价顶背离")
        elif price_new_low and vol_new_low:
            contradictions.append(f"[高优先级]{level}量价底背离：股价创新低，量能萎缩抛压衰竭")
            priority_map["高"].append("量价底背离")

    # 2. 指标背离检测（MACD，中优先级）
    macd, _, _ = talib.MACD(close)
    for days, level in [(10, "中期"), (20, "长期")]:
        if len(close) < days + 5:
            continue
        price_lower = close[-1] < np.min(close[-days:-1])
        macd_higher = macd[-1] > np.min(macd[-days:-1])
        if price_lower and macd_higher:
            contradictions.append(f"[中优先级]{level}MACD底背离")
            priority_map["中"].append("MACD底背离")

        price_higher = close[-1] > np.max(close[-days:-1])
        macd_lower = macd[-1] < np.max(macd[-days:-1])
        if price_higher and macd_lower:
            contradictions.append(f"[中优先级]{level}MACD顶背离")
            priority_map["中"].append("MACD顶背离")

    # 3. 板块-个股联动矛盾（中优先级）
    if board_code:
        try:
            board_df = ak.stock_board_industry_hist_em(symbol=board_code, period="day",
                                                       start_date=(datetime.now()-timedelta(days=10)).strftime("%Y%m%d"),
                                                       end_date=datetime.now().strftime("%Y%m%d"))
            board_change = board_df.iloc[-1]["涨跌幅"]
            stock_change = (close[-1]/close[-2] -1)*100
            if stock_change < board_change - 3:
                contradictions.append(f"[中优先级]个股显著弱于板块：个股{stock_change:.2f}%，板块{board_change:.2f}%")
            elif stock_change > board_change + 3:
                contradictions.append(f"[低优先级]个股显著强于板块：个股{stock_change:.2f}%，板块{board_change:.2f}%")
        except Exception:
            pass

    # 4. 两融背离检测（低优先级，仅两融标的）
    try:
        prev_date = get_previous_trade_date()
        rz_df = ak.stock_margin_detail_sse(date=prev_date)
        if stock_code in rz_df["证券代码"].values:
            net_buy = float(rz_df[rz_df["证券代码"]==stock_code]["融资净买入额"].values[0]) / 1e8
            price_up = close[-1] > close[-2]
            if price_up and net_buy < 0:
                contradictions.append("[低优先级]融资顶背离：股价上涨，融资资金净流出")
            elif not price_up and net_buy > 0:
                contradictions.append("[低优先级]融资底背离：股价下跌，融资资金逆势流入")
    except Exception:
        pass

    # 5. 真假突破/跌破判定
    break_20d_high = close[-1] > np.max(high[-20:-1])
    break_20d_low = close[-1] < np.min(low[-20:-1])
    vol_confirm = volume[-1] > np.mean(volume[-20:-1]) * cfg["volume_amplify_threshold"]

    break_conclusion = "区间震荡，无有效突破/跌破"
    if break_20d_high and vol_confirm:
        break_conclusion = "有效突破20日高点，量能确认"
    elif break_20d_high and not vol_confirm:
        break_conclusion = "假突破：突破20日高点但量能不足"
    elif break_20d_low and vol_confirm:
        break_conclusion = "有效跌破20日低点，量能确认，风险加大"
    elif break_20d_low and not vol_confirm:
        break_conclusion = "假跌破：跌破20日低点但量能不足"

    # 6. 多情景推演（动态概率联动大盘）
    base_prob = {"基准": 60, "乐观": 20, "悲观": 20}
    if market_env == "bull":
        base_prob["乐观"] += 10
        base_prob["悲观"] -= 10
    elif market_env == "bear":
        base_prob["乐观"] -= 10
        base_prob["悲观"] += 10

    scenarios = [
        {
            "情景": "基准情景（震荡修复）",
            "概率": f"{base_prob['基准']}%",
            "触发条件": "守住强支撑，量能温和放大，板块无大跌",
            "目标价位": round(np.mean(close[-20:]) * 1.03, 2),
            "止损价位": round(np.mean(close[-20:]) * 0.97, 2)
        },
        {
            "情景": "乐观情景（突破走强）",
            "概率": f"{base_prob['乐观']}%",
            "触发条件": "放量突破强压力，板块共振，大盘环境配合",
            "目标价位": round(np.max(high[-60:]) * 1.02, 2)
        },
        {
            "情景": "悲观情景（破位下行）",
            "概率": f"{base_prob['悲观']}%",
            "触发条件": "放量跌破强支撑，板块走弱，大盘环境偏空",
            "目标价位": round(np.min(low[-60:]) * 0.97, 2)
        }
    ]

    return {
        "个股名称": stock_name,
        "突破/跌破判定": break_conclusion,
        "核心矛盾清单": contradictions if contradictions else ["无明显背离矛盾"],
        "矛盾优先级": priority_map,
        "多情景推演": scenarios
    }
