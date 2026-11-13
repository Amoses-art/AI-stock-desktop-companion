from datetime import datetime, timedelta
import akshare as ak
from .gudashi_analysis_engine import GLOBAL_CONFIG, get_previous_trade_date, calc_price_percentile


def skill5_margin_trade_analysis(level="market", stock_code=None, stock_close_arr=None):
    cfg = GLOBAL_CONFIG
    trade_date = get_previous_trade_date()

    # 全市场层级
    if level == "market":
        try:
            df = ak.stock_margin_summary_sse(date=trade_date)
            total_net_buy = float(df["融资净买入额"].sum()) / 1e8
        except Exception:
            return {
                "分析层级": "全市场",
                "数据日期": trade_date,
                "融资净买入额": "—",
                "区间定性": "数据获取受限",
                "连续同向天数": 0,
                "决策权重": "25%",
                "结论": "两融数据获取受限，决策以技术面为主"
            }

        if abs(total_net_buy) <= cfg["margin_normal_threshold"]:
            zone = "常态区间"
            weight = cfg["margin_normal_weight"]
            conclusion = "两融资金变动平缓，无明确方向性信号，决策以技术面为主"
        elif abs(total_net_buy) >= cfg["margin_extreme_threshold"]:
            zone = "极值区间"
            weight = cfg["margin_extreme_weight"]
            direction = "杠杆资金大幅进场，情绪偏多" if total_net_buy > 0 else "杠杆资金大幅出逃，情绪偏空"
            conclusion = f"全市场两融极值信号：{direction}，对大盘方向有较强参考意义"
        else:
            zone = "温和区间"
            weight = 0.30
            direction = "杠杆资金温和流入" if total_net_buy > 0 else "杠杆资金温和流出"
            conclusion = f"两融资金{direction}，辅助验证趋势持续性"

        # 连续变动检测
        continuous_days = 0
        try:
            for i in range(1, cfg["margin_continuous_days"]+1):
                d = get_previous_trade_date((datetime.strptime(trade_date, "%Y%m%d") - timedelta(days=i)).strftime("%Y%m%d"))
                df_i = ak.stock_margin_summary_sse(date=d)
                net_i = float(df_i["融资净买入额"].sum()) / 1e8
                if (total_net_buy > 0 and net_i > 0) or (total_net_buy < 0 and net_i < 0):
                    continuous_days += 1
                else:
                    break
        except Exception:
            pass

        if continuous_days >= cfg["margin_continuous_days"]:
            conclusion += f"；连续{continuous_days}日同向变动，趋势确认度提升"
            weight = min(weight + 0.05, cfg["margin_extreme_weight"])

        return {
            "分析层级": "全市场",
            "数据日期": trade_date,
            "融资净买入额": f"{total_net_buy:.2f}亿元",
            "区间定性": zone,
            "连续同向天数": continuous_days,
            "决策权重": f"{int(weight*100)}%",
            "结论": conclusion
        }

    # 个股层级
    elif level == "stock" and stock_code:
        try:
            df = ak.stock_margin_detail_sse(date=trade_date)
            stock_data = df[df["证券代码"] == stock_code]
            if stock_data.empty:
                return {"分析层级": "个股", "提示": "非两融标的，两融数据无效"}
        except Exception:
            return {
                "分析层级": "个股",
                "数据日期": trade_date,
                "融资净买入": "—",
                "融资买入占比": "—",
                "股价位置": "未知",
                "位置匹配信号": "两融数据获取受限",
                "异常提醒": "无异常",
                "决策权重": "25%"
            }

        net_buy = float(stock_data["融资净买入额"].values[0]) / 1e8
        buy_ratio = float(stock_data["融资买入额占成交额比例"].values[0])

        # 自动计算股价位置分位
        position = "中位"
        if stock_close_arr is not None and len(stock_close_arr) >= 30:
            pct = calc_price_percentile(stock_close_arr)
            if pct < cfg["position_low_threshold"]:
                position = "低位"
            elif pct > cfg["position_high_threshold"]:
                position = "高位"

        # 位置约束反向解读
        if position == "低位" and net_buy > 0:
            signal = "偏利好：低位融资净买入，杠杆资金逆势布局"
        elif position == "低位" and net_buy < 0:
            signal = "偏利空：低位融资净卖出，杠杆资金止损离场"
        elif position == "高位" and net_buy > 0:
            signal = "偏风险：高位融资追涨，后续易回调兑现"
        elif position == "高位" and net_buy < 0:
            signal = "偏谨慎：高位融资兑现，杠杆资金提前离场"
        else:
            signal = "中性：中位区间，两融变动无明确指向性"

        # 买入占比异常检测
        ratio_alert = ""
        if buy_ratio > 20:
            ratio_alert = "异常提醒：融资买入占比超20%，杠杆参与度过高，波动放大"

        weight = cfg["margin_normal_weight"]
        if abs(net_buy) > 2:
            weight = 0.35

        return {
            "分析层级": "个股",
            "数据日期": trade_date,
            "融资净买入": f"{net_buy:.2f}亿元",
            "融资买入占比": f"{buy_ratio}%",
            "股价位置": position,
            "位置匹配信号": signal,
            "异常提醒": ratio_alert if ratio_alert else "无异常",
            "决策权重": f"{int(weight*100)}%"
        }

# 二次验证接口
def skill5_backtest_verify(signal_date, actual_next_day_change, signal_direction):
    hit = False
    if signal_direction == "多" and actual_next_day_change > 0:
        hit = True
    elif signal_direction == "空" and actual_next_day_change < 0:
        hit = True
    return {
        "信号日期": signal_date,
        "信号方向": signal_direction,
        "次日实际涨跌幅": f"{actual_next_day_change:.2f}%",
        "是否命中": hit
    }
