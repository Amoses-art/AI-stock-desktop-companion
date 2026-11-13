import akshare as ak
import pandas as pd
import numpy as np
import talib
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings("ignore")

# === 网络可用性检测 ===
_akshare_available = None

def _check_akshare_available() -> bool:
    """检测 AKShare 网络是否可用（缓存结果）
    优先用腾讯源 stock_zh_index_daily_tx（更稳定，不受东方财富风控）
    """
    global _akshare_available
    if _akshare_available is not None:
        return _akshare_available
    try:
        df = ak.stock_zh_index_daily_tx(symbol="sh000001", start_date="20250101", end_date="20260908")
        _akshare_available = len(df) > 0
    except Exception:
        _akshare_available = False
    return _akshare_available


# 全局统一参数配置
GLOBAL_CONFIG = {
    "volume_amplify_threshold": 1.2,
    "volume_shrink_threshold": 0.8,
    "break_stand_minutes": 3,
    "break_price_threshold": 0.005,
    "margin_normal_threshold": 50,
    "margin_extreme_threshold": 100,
    "margin_normal_weight": 0.25,
    "margin_extreme_weight": 0.40,
    "margin_continuous_days": 3,
    "divergence_lookback": 20,
    "adjust_cycle_days": 8,
    "position_low_threshold": 0.3,
    "position_high_threshold": 0.7,
}

# 通用工具函数
def get_previous_trade_date(date=None):
    if date is None:
        date = datetime.now()
    elif isinstance(date, str):
        date = datetime.strptime(date, "%Y%m%d")
    try:
        import bisect
        calendar = ak.tool_trade_date_hist_sse()
        calendar = sorted(calendar["trade_date"].tolist())
        date_str = date.strftime("%Y%m%d")
        idx = bisect.bisect_left(calendar, date_str) - 1
        return calendar[idx]
    except Exception:
        d = date - timedelta(days=1)
        while d.weekday() >= 5:
            d -= timedelta(days=1)
        return d.strftime("%Y%m%d")

def calc_price_percentile(close_array, lookback=60):
    if len(close_array) < lookback:
        lookback = len(close_array)
    recent_close = close_array[-lookback:]
    current = close_array[-1]
    return np.sum(recent_close <= current) / len(recent_close)

def get_stock_kline(stock_code, period="daily", days=120, adjust="qfq"):
    # 快速检测网络可用性，不可用则直接返回空DataFrame
    if not _check_akshare_available():
        return pd.DataFrame()

    end_date = datetime.now().strftime("%Y%m%d")
    start_date = (datetime.now() - timedelta(days=days*2)).strftime("%Y%m%d")
    for _ in range(3):
        try:
            if period == "daily":
                df = ak.stock_zh_a_hist(symbol=stock_code, period="daily",
                                        start_date=start_date, end_date=end_date, adjust=adjust)
            else:
                df = ak.stock_zh_a_minute(symbol=stock_code, period=period, adjust=adjust)
            df = df.sort_values("日期" if period=="daily" else "时间").reset_index(drop=True)
            return df.tail(days)
        except Exception:
            continue
    return pd.DataFrame()

# Skill1 主函数
