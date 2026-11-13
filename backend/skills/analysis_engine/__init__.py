"""
股大师分析引擎 v1.1

6个核心Skill：
- skill1_support_pressure: 三档支撑/压力、筹码峰、区间定性
- skill2_trend_predict: MACD+KDJ+量能+板块+两融五因子趋势预测
- skill3_stock_review: 四类矛盾检测、真假突破、多情景推演
- skill4_intraday: 有效突破三重确认、分时强弱、异动告警
- skill5_margin_trade: 全市场/板块/个股三层两融分析
- skill6_market_overview: 趋势+结构+周期+资金+事件五维大盘概览
"""

from .gudashi_analysis_engine import GLOBAL_CONFIG, get_previous_trade_date, calc_price_percentile, get_stock_kline
from .skill1_support_pressure import skill1_support_pressure_review
from .skill2_trend_predict import skill2_tomorrow_trend_predict
from .skill3_stock_review import skill3_stock_special_review
from .skill4_intraday import skill4_intraday_analysis
from .skill5_margin_trade import skill5_margin_trade_analysis, skill5_backtest_verify
from .skill6_market_overview import skill6_market_overview_analysis

__all__ = [
    "GLOBAL_CONFIG",
    "get_previous_trade_date",
    "calc_price_percentile",
    "get_stock_kline",
    "skill1_support_pressure_review",
    "skill2_tomorrow_trend_predict",
    "skill3_stock_special_review",
    "skill4_intraday_analysis",
    "skill5_margin_trade_analysis",
    "skill5_backtest_verify",
    "skill6_market_overview_analysis",
]
