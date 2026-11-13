import numpy as np
import akshare as ak
from .gudashi_analysis_engine import GLOBAL_CONFIG


def skill4_intraday_analysis(stock_code, stock_name, support_level, pressure_level, market_risk_level="normal"):
    from .gudashi_analysis_engine import _check_akshare_available
    if not _check_akshare_available():
        return {
            "个股名称": stock_name,
            "实时价格": None,
            "关键支撑": support_level,
            "关键压力": pressure_level,
            "是否有效突破压力": False,
            "是否有效跌破支撑": False,
            "分时强弱": "数据不足",
            "分时异动告警": "分时数据获取受限",
            "实时操作建议": "数据获取受限，无法提供实时操作建议"
        }

    try:
        cfg = GLOBAL_CONFIG
        df = ak.stock_zh_a_minute(symbol=stock_code, period='1', adjust="qfq")
        if df.empty or len(df) < 30:
            return {
                "个股名称": stock_name,
                "实时价格": None,
                "关键支撑": support_level,
                "关键压力": pressure_level,
                "是否有效突破压力": False,
                "是否有效跌破支撑": False,
                "分时强弱": "数据不足",
                "分时异动告警": "分时数据获取受限",
                "实时操作建议": "数据获取受限，无法提供实时操作建议"
            }

        df = df.tail(120).reset_index(drop=True)
        price = df["收盘"].values
        volume = df["成交量"].values
        latest_price = price[-1]

        # 均价线计算
        cum_vol = np.cumsum(volume)
        cum_amount = np.cumsum(price * volume)
        avg_price = cum_amount / cum_vol
        latest_avg = avg_price[-1]

        # 有效突破/跌破三重确认
        def check_effective_break(target_price, direction="up"):
            if len(price) < cfg["break_stand_minutes"]:
                return False
            if direction == "up":
                price_ok = all(price[-cfg["break_stand_minutes"]:] > target_price * (1 + cfg["break_price_threshold"]))
            else:
                price_ok = all(price[-cfg["break_stand_minutes"]:] < target_price * (1 - cfg["break_price_threshold"]))

            vol_recent = np.mean(volume[-cfg["break_stand_minutes"]:])
            vol_prev = np.mean(volume[-10:-cfg["break_stand_minutes"]])
            vol_ok = vol_recent > vol_prev * cfg["volume_amplify_threshold"]

            return price_ok and vol_ok

        break_pressure = check_effective_break(pressure_level, direction="up")
        break_support = check_effective_break(support_level, direction="down")

        # 分时强弱判定
        above_avg = latest_price > latest_avg
        avg_slope = (avg_price[-1] - avg_price[-10]) / avg_price[-10] * 100
        price_5min_chg = (price[-1] / price[-5] - 1) * 100
        vol_5min_ratio = np.mean(volume[-5:]) / np.mean(volume[-20:-5])

        if above_avg and avg_slope > 0 and vol_5min_ratio > 1.1:
            intraday_strength = "强势"
        elif not above_avg and avg_slope < 0 and vol_5min_ratio > 1.1:
            intraday_strength = "弱势"
        else:
            intraday_strength = "中性"

        # 异动告警
        alert = ""
        if abs(price_5min_chg) >= 2 and vol_5min_ratio > 1.3:
            direction = "拉升" if price_5min_chg > 0 else "跳水"
            alert = f"异动提醒：近5分钟{direction}幅度{price_5min_chg:.2f}%，量能放大{vol_5min_ratio-1:.0%}"

        # 分级操作建议（联动大盘风险等级）
        if break_pressure:
            if market_risk_level == "aggressive":
                suggestion = "有效突破压力位，量能确认，可加仓跟进，目标看强压力"
            else:
                suggestion = "有效突破压力位，量能确认，持有为主，不追高加仓"
        elif break_support:
            suggestion = "有效跌破支撑位，量能确认，优先风控减仓，规避继续下行风险"
        elif intraday_strength == "强势" and latest_price < pressure_level:
            suggestion = "分时偏强，未到压力位，持有观望，可择机做T高抛"
        elif intraday_strength == "弱势" and latest_price > support_level:
            suggestion = "分时偏弱，未破支撑，持有观望，可择机做T低吸"
        else:
            suggestion = "分时震荡，区间内运行，持有观望为主"

        return {
            "个股名称": stock_name,
            "实时价格": round(latest_price, 2),
            "关键支撑": support_level,
            "关键压力": pressure_level,
            "是否有效突破压力": break_pressure,
            "是否有效跌破支撑": break_support,
            "分时强弱": intraday_strength,
            "分时异动告警": alert if alert else "无异常异动",
            "实时操作建议": suggestion
        }
    except Exception:
        return {
            "个股名称": stock_name,
            "实时价格": None,
            "关键支撑": support_level,
            "关键压力": pressure_level,
            "是否有效突破压力": False,
            "是否有效跌破支撑": False,
            "分时强弱": "分析失败",
            "分时异动告警": "分时数据获取受限",
            "实时操作建议": "数据获取受限，无法提供实时操作建议"
        }
