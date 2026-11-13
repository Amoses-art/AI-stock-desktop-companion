股大师・A 股大盘择时与个股交易一体化智能分析系统
版本：V1.0 正式封装版
定位：融合徐小明《投资明见》技术体系 + 量化资金验证 + 财报基本面 + 专属持仓风控的四维闭环交易辅助工具
核心原则：无结构不操作、趋势不可逆、量价验真假、事件优先于技术

一、产品概述
1.1 能力定位
「股大师」是一套标准化、可落地、可回溯的 A 股全场景交易分析系统，以大盘择时为总闸门、个股技术为核心、两融资金为验证、基本面为安全垫，覆盖盘后复盘、盘前预测、个股深度拆解、盘中实时研判全交易周期，彻底解决 “只看个股不看大盘、只看情绪不看结构、只靠主观不靠规则” 的散户交易痛点。
1.2 核心价值
1. 大盘择时前置：用《投资明见》趋势 + 结构体系定市场可操作窗口，避免逆市抄底接飞刀
2. 分析规则固化：所有支撑压力、涨跌概率、买卖信号均有量化阈值，无主观臆断
3. 全品类覆盖：支持 A 股个股、ETF、LOF、指数联接基金的统一分析框架
4. 风控内嵌：题材标的只减不补、破位优先风控、大跌不抄底，纪律内置到每一个分析环节
5. 可迭代优化：所有参数统一收口，支持日校验、周优化、月校准，持续提升准确率
1.3 适用场景
● 每日收盘后：批量持仓复盘、验证昨日推演、更新支撑压力位
● 每日开盘前：大盘环境定性、个股涨跌概率推演、制定当日交易计划
● 个股深度研究：单只标的量价 / 指标 / 资金 / 板块矛盾拆解、多情景推演
● 交易日盘中：实时分时研判、有效突破 / 跌破判定、实时操作建议
● 全账户风控：大盘仓位管控、赛道集中度校验、持仓风险分级

二、核心角色定位与底层原则
2.1 角色核心定位
专注于 A 股市场个股短期技术分析与实时交易辅助，以东方财富、同花顺官方真实行情数据 + 上交所 / 深交所官方两融数据为唯一数据依据，不主观臆断、不预测长期行情，核心服务于短期交易决策（做 T、仓位管控、实时加减仓）。
所有分析强制标注「仅技术推演，不构成投资建议」，明确无法覆盖突发政策、外围波动、重大公告等不可控变量。
2.2 底层交易哲学（四大支柱）
1. 趋势为王，结构修边：对齐徐小明《投资明见》核心体系，大趋势定方向，分钟级结构定买卖点，无底部结构不抄底，无顶部结构不空仓
2. 量价验证，资金辨伪：缩量止跌为真企稳，放量下跌为真破位；北向资金、两融资金交叉验证情绪真实性
3. 基本面定容错率：业绩硬逻辑标的可逢低分批布局，纯题材无业绩标的只减不补
4. 事件优先技术：美联储议息、重大政策、外围黑天鹅等重大事件，优先级高于所有技术结构，事件期自动降级操作等级
2.3 全场景工作闭环
形成「大盘定环境 → 数据采集 → 分析推演 → 交易落地 → 复盘验证 → 迭代优化」的完整闭环，两融数据作为辅助验证维度贯穿全流程，不独立主导决策。

三、核心能力架构总览
整套系统由1 个总控前置 Skill + 4 个核心业务 Skill + 1 个辅助验证 Skill组成，六大 Skill 协同复用，层级不可逆。
表格
Skill 编号	Skill 名称	能力定位	调用场景	优先级
Skill 6	大盘视角多维交易分析	全场景总控闸门，定市场环境与操作窗口	所有场景前置执行	最高
Skill 1	个股短期支撑压力复盘	盘后定支撑压力、判短期强弱	每日盘后批量复盘	核心
Skill 2	个股明日涨跌趋势预测	盘前推演涨跌概率、定强弱等级	每日开盘前预测	核心
Skill 3	个股专项复盘	单只标的深度拆解矛盾、多情景推演	个股深度研究	核心
Skill 4	个股实时专项分析	盘中实时分时研判、有效突破判定	交易日盘中实时	核心
Skill 5	两融数据辅助交易决策	全市场 / 板块 / 个股杠杆资金验证	全场景辅助校验	辅助

四、六大核心 Skill 详细手册
Skill 1：个股短期支撑压力复盘 Skill
能力定位
盘后核心技能，通过「昨日推演→今日验证→区间定性」逻辑，精准划定个股短线支撑与压力位，判断短期强弱。
核心拆解规则
1. 支撑位三档划分
  ○ 第一支撑：5 日、10 日均线最小值
  ○ 第二支撑：近 20 日震荡低点 + 短期筹码密集峰
  ○ 强支撑：近 60 日阶段低点 + 中期筹码峰 + 60 日均线（短期生命线）
2. 压力位三档划分
  ○ 第一压力：20 日均线
  ○ 第二压力：近 20 日震荡高点 + 短期筹码密集峰
  ○ 强压力：近 60 日中期震荡高点 + 上方套牢筹码密集峰（趋势分水岭）
3. 区间定性四档：强势区、中性偏强、中性偏弱、弱势区
4. 昨日验证闭环：自动校验昨日支撑压力的有效性，记录偏差用于迭代优化
配套 Python 脚本
import akshare as ak
import pandas as pd
import numpy as np
import talib
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings("ignore")

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
    except:
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
        except:
            continue
    return pd.DataFrame()

# Skill1 主函数
def skill1_support_pressure_review(stock_code, stock_name, trade_date=None):
    cfg = GLOBAL_CONFIG
    df = get_stock_kline(stock_code, period="daily", days=120)
    if df.empty:
        return {"标的": stock_name, "状态": "数据获取失败"}
    
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
        yest_low = low[-1]
        yest_high = high[-1]
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
输出标准
标准化表格，包含个股名称、昨收、今收、三档支撑压力、收盘区间、定性解读与实操参考。

Skill 2：个股明日涨跌趋势预测 Skill
能力定位
盘前核心技能，基于多维度技术指标、板块联动、资金动向及两融辅助信号，预判个股明日涨跌概率区间，提供情景可能性参考。
核心拆解规则
1. 五因子权重固化：MACD 30% + KDJ 20% + 量能 15% + 板块 20% + 两融 15%
2. 两融权重约束：常态下两融权重不超过 25%，极值情景上浮至 40%
3. 大盘环境修正：联动 Skill6 大盘得分，自动修正上涨 / 下跌概率
4. 四档强弱定性：强势（≥65%）、中性偏强（55%-65%）、中性偏弱（45%-55%）、弱势（<45%）
配套 Python 脚本
def skill2_tomorrow_trend_predict(stock_code, stock_name, board_code=None, market_env_score=3):
    cfg = GLOBAL_CONFIG
    df = get_stock_kline(stock_code, days=120)
    if df.empty:
        return {"标的": stock_name, "状态": "数据获取失败"}
    
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
        except:
            factor_detail["板块"] = "板块数据获取失败"
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
    except:
        factor_detail["两融"] = "两融数据获取失败"
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
输出标准
标准化表格，包含个股名称、昨收、关键指标、资金动向、强弱定性、涨跌概率区间及核心原因。

Skill 3：个股专项复盘 Skill
能力定位
单只个股深度分析技能，以盘面客观事实为优先，拆解量价、板块、指标、两融四类矛盾点，做多情景明日推演，输出分角色实操建议。
核心拆解规则
1. 四类矛盾检测：量价背离、指标背离、板块 - 个股联动矛盾、两融 - 价格背离
2. 多周期校验：短 / 中 / 长三周期同步检测，避免单一周期误判
3. 真假突破判定：幅度≥3% + 连续 3 根 K 线站稳 + 量能放大 20%，三者同时满足为有效突破
4. 三情景推演：基准情景（60%）、乐观情景（20%）、悲观情景（20%），概率随大盘环境动态调整
配套 Python 脚本
def skill3_stock_special_review(stock_code, stock_name, board_code=None, market_env="neutral"):
    cfg = GLOBAL_CONFIG
    df = get_stock_kline(stock_code, days=120)
    if df.empty:
        return {"标的": stock_name, "状态": "数据获取失败"}
    
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
        except:
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
    except:
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
输出标准
完整分析报告，包含客观事实、多情景推演、关键档位、分角色建议、风险提醒。

Skill 4：个股实时专项分析 Skill
能力定位
盘中实时研判技能，以实时时间节点为基准，继承日线与两融前置基准，采集实时盘口与板块新闻，识别盘中真假信号，输出带价格条件的实时操作建议。
核心拆解规则
1. 有效突破三重确认：价格超阈值 0.5% + 连续 3 根 1 分钟 K 线站稳 + 对应时段量能超均量 1.2 倍
2. 分时强弱判定：均价线位置 + 均价线斜率 + 分时量价配合，三重维度
3. 异动告警：5 分钟涨跌幅≥2% 且量能放大 30%，自动提示异动
4. 分级操作建议：根据大盘当日风险等级，动态调整操作激进程度
配套 Python 脚本
def skill4_intraday_analysis(stock_code, stock_name, support_level, pressure_level, market_risk_level="normal"):
    cfg = GLOBAL_CONFIG
    df = ak.stock_zh_a_minute(symbol=stock_code, period='1', adjust="qfq")
    if df.empty or len(df) < 30:
        return {"标的": stock_name, "状态": "分时数据不足"}
    
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
输出标准
实时分析报告，包含日线基准、盘中事实、多维拆解、短窗口推演、关键档位、实操建议、利空利好提醒。

Skill 5：两融数据辅助交易决策 Skill
能力定位
全场景辅助验证技能，以上交所 / 深交所官方两融数据为唯一依据，作为杠杆资金情绪的验证工具，辅助仓位管控、波段止盈与风险预警，不独立生成买卖决策。
核心拆解规则
1. 三层拆解：全市场层（总仓位管控）、行业板块层（赛道轮动辅助）、个股 / 基金层（标的交易辅助）
2. 区间定性
  ○ 常态区间：单日融资净买入 ±50 亿以内，无方向性预测价值，权重 25%
  ○ 极值区间：单日变动超 100 亿、连续 3 日同向变动、买入占比突破阈值，权重 35%-40%
3. 位置约束：同一两融数据，结合股价所处位置反向解读：低位净买入为利好，高位净买入为风险
4. 二次验证机制：每日验证信号有效性，周度汇总优化阈值，月度校准不同市场环境下的信号有效性
配套 Python 脚本
def skill5_margin_trade_analysis(level="market", stock_code=None, stock_close_arr=None):
    cfg = GLOBAL_CONFIG
    trade_date = get_previous_trade_date()

    # 全市场层级
    if level == "market":
        try:
            df = ak.stock_margin_summary_sse(date=trade_date)
            total_net_buy = float(df["融资净买入额"].sum()) / 1e8
        except:
            return {"分析层级": "全市场", "状态": "两融数据获取失败"}

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
        except:
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
        except:
            return {"分析层级": "个股", "状态": "两融数据获取失败"}

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
输出标准
两融专项分析表，包含核心数据、资金定性、对应行情验证、实操参考；非两融标的明确标注「两融数据无效」。

Skill 6：大盘视角多维交易分析 Skill（总控前置）
能力定位
全场景前置总控技能，融合徐小明《投资明见》「趋势为王、结构修边」技术体系，叠加资金面、基本面、事件面四维校验，对大盘指数做周期、趋势、结构三重定性，输出全市场可操作 / 观望窗口，作为所有个股交易的总风控基准。
核心拆解规则
1. 趋势维度：短 / 中期趋势判定，区分上升、下降、震荡三档
2. 结构维度：跟踪 60/90/120 分钟级别钝化、顶部 / 底部结构、序列高低点，严格执行「无底部结构不抄底、无顶部结构不空仓」
3. 周期维度：识别调整周期、反弹周期的时间窗口，判定当前处于可操作阶段还是观望阶段
4. 资金验证：北向资金、两市成交额、全市场两融，交叉验证结构真实性
5. 事件优先级：重大事件优先级高于技术结构，事件期自动降级操作等级
6. 赛道映射：将大盘环境映射到各赛道，分别给出操作等级
配套 Python 脚本
def skill6_market_overview_analysis(major_event=False, event_level="normal"):
    cfg = GLOBAL_CONFIG

    # 1. 核心指数趋势判定
    index_list = {
        "上证指数": "000001",
        "创业板指": "399006",
        "科创50": "000688"
    }

    index_trend = {}
    for name, code in index_list.items():
        try:
            df = ak.stock_zh_index_daily(symbol=code)
            df = df.tail(120).reset_index(drop=True)
            close = df["close"].values
            ma20 = talib.MA(close, 20)[-1]
            ma60 = talib.MA(close, 60)[-1]

            if close[-1] > ma20 and ma20 > talib.MA(close, 20)[-2]:
                short_trend = "上升"
            elif close[-1] < ma20 and ma20 < talib.MA(close, 20)[-2]:
                short_trend = "下降"
            else:
                short_trend = "震荡"

            if close[-1] > ma60 and ma60 > talib.MA(close, 60)[-2]:
                mid_trend = "上升"
            elif close[-1] < ma60 and ma60 < talib.MA(close, 60)[-2]:
                mid_trend = "下降"
            else:
                mid_trend = "震荡"

            index_trend[name] = {
                "最新点位": round(close[-1], 2),
                "短期趋势": short_trend,
                "中期趋势": mid_trend,
                "20日均线": round(ma20, 2),
                "60日均线": round(ma60, 2)
            }
        except:
            index_trend[name] = {"状态": "数据获取失败"}

    # 2. 分钟级别结构钝化判定
    def check_divergence_struct(index_code, period=60):
        try:
            df = ak.stock_zh_index_minute(symbol=index_code, period=str(period))
            close = df["收盘"].values
            macd, _, _ = talib.MACD(close)
            lookback = cfg["divergence_lookback"]

            price_new_low = close[-1] < np.min(close[-lookback:-3])
            macd_not_new_low = macd[-1] > np.min(macd[-lookback:-3])
            bottom_divergence = price_new_low and macd_not_new_low

            price_new_high = close[-1] > np.max(close[-lookback:-3])
            macd_not_new_high = macd[-1] < np.max(macd[-lookback:-3])
            top_divergence = price_new_high and macd_not_new_high

            bottom_struct = bottom_divergence and macd[-1] > macd[-2]
            top_struct = top_divergence and macd[-1] < macd[-2]

            return {
                f"{period}分钟底部钝化": bottom_divergence,
                f"{period}分钟顶部钝化": top_divergence,
                f"{period}分钟底部结构": bottom_struct,
                f"{period}分钟顶部结构": top_struct
            }
        except:
            return {}

    struct_60m = check_divergence_struct("000001", 60)
    struct_90m = check_divergence_struct("000001", 90)
    struct_120m = check_divergence_struct("000001", 120)

    # 3. 周期状态
    cycle_status = "震荡整理"
    cycle_remain_days = 0
    if struct_60m.get("60分钟顶部结构", False):
        cycle_status = "调整周期中"
        cycle_remain_days = cfg["adjust_cycle_days"]

    # 4. 资金面验证
    fund_verify = {}
    try:
        north_df = ak.stock_hsgt_north_net_flow_in_em()
        north_today = north_df.iloc[-1]["净流入"]
        fund_verify["北向资金"] = f"{north_today:.2f}亿元"
        fund_verify["北向状态"] = "流入" if north_today > 0 else "流出"

        market_df = ak.stock_zh_a_spot_em()
        total_vol = market_df["成交额"].sum() / 1e8
        fund_verify["两市成交额"] = f"{total_vol:.0f}亿元"
        fund_verify["量能状态"] = "放量" if total_vol > 18000 else "缩量" if total_vol < 15000 else "常态"
    except:
        fund_verify["状态"] = "资金数据获取失败"

    # 5. 赛道强弱映射
    try:
        board_df = ak.stock_board_industry_name_em()
        board_df = board_df.sort_values("涨跌幅", ascending=False)
        top_5 = board_df.head(5)["板块名称"].tolist()
        bottom_5 = board_df.tail(5)["板块名称"].tolist()
    except:
        top_5 = []
        bottom_5 = []

    # 6. 可操作窗口与仓位基准（五档）
    score = 3
    if index_trend.get("上证指数", {}).get("短期趋势") == "上升":
        score += 1
    elif index_trend.get("上证指数", {}).get("短期趋势") == "下降":
        score -= 1

    if struct_60m.get("60分钟底部结构", False) or struct_90m.get("90分钟底部结构", False):
        score += 1
    elif struct_60m.get("60分钟顶部结构", False) or struct_90m.get("90分钟顶部结构", False):
        score -= 1

    if fund_verify.get("北向状态") == "流入" and fund_verify.get("量能状态") == "放量":
        score += 0.5
    elif fund_verify.get("北向状态") == "流出" and fund_verify.get("量能状态") == "放量":
        score -= 0.5

    # 事件优先级
    if major_event:
        if event_level == "important":
            score -= 0.5
        elif event_level == "extreme":
            score = 2

    # 五档仓位映射
    if score >= 4.5:
        window = "积极操作窗口"
        position_level = "激进"
        position_suggest = "70%-90%仓位"
    elif score >= 3.5:
        window = "可操作窗口"
        position_level = "积极"
        position_suggest = "50%-70%仓位"
    elif score >= 2.5:
        window = "中性观望窗口"
        position_level = "中性"
        position_suggest = "30%-50%仓位"
    elif score >= 1.5:
        window = "谨慎观望窗口"
        position_level = "谨慎"
        position_suggest = "20%-30%仓位"
    else:
        window = "风险管控窗口"
        position_level = "保守"
        position_suggest = "20%以下仓位"

    return {
        "核心指数趋势": index_trend,
        "分钟级技术结构": {**struct_60m, **struct_90m, **struct_120m},
        "周期状态": f"{cycle_status}，剩余基准天数{cycle_remain_days}天",
        "资金面验证": fund_verify,
        "赛道强弱排行": {"领涨板块": top_5, "领跌板块": bottom_5},
        "当前操作窗口": window,
        "全市场仓位基准": position_level,
        "建议仓位区间": position_suggest,
        "事件影响标记": "重大事件进行中，技术结构有效性降级" if major_event else "无重大事件干扰",
        "风险提示": "仅技术推演，不构成投资建议"
    }
输出标准
大盘复盘报告 + 明日多情景推演 + 可操作 / 观望窗口 + 全市场仓位基准 + 各赛道操作提示。

五、Skill 协同调用机制
5.1 总调用原则
层级不可逆：所有场景必须先执行 Skill6 定大盘环境，再调用对应主 Skill，最后用 Skill5 做资金验证，禁止跳过大盘直接分析个股。
5.2 盘后批量复盘标准链路
Skill6（大盘复盘 + 环境定性）
    → Skill1（批量个股支撑压力复盘）
        → Skill5（全市场两融验证强弱）
            → 整合输出最终复盘报告
5.3 盘前涨跌预测标准链路
Skill6（明日大盘推演 + 操作窗口判定）
    → Skill2（批量个股明日涨跌概率预测）
        → Skill5（两融极值信号修正概率）
            → 输出次日交易计划
5.4 单只个股深度研判链路
Skill6（大盘与板块周期背景）
    → Skill3（个股专项深度复盘 + 多情景推演）
        → Skill5（个股两融背离分析）
            → 输出深度研判报告
5.5 盘中实时操作研判链路
Skill6（当日大盘操作等级）
    → Skill4（个股实时分时分析 + 有效突破判定）
        → Skill5（两融前置风控基准）
            → 输出实时操作建议

六、全局约束与风控铁律
6.1 数据真实性约束
1. 行情数据仅采信东方财富、同花顺官方口径；两融数据以上交所、深交所官方披露为底层基准
2. 严格遵循 A 股交易日历，周末 / 节假日无交易数据，周五数据跨周末顺延至下周一
3. 两融余额为 T-1 收盘统计值，无实时余额数据，不得误导为实时变动
4. 技术结构判定以真实 K 线、量能为准，不得主观臆断钝化与结构
6.2 交易纪律铁律
1. 大跌当日不抄底，无底部结构不加仓
2. 题材无业绩标的只减不补，禁止通过补仓摊薄成本
3. 放量跌破关键支撑，优先风控减仓，不心存侥幸
4. 重大事件落地前，控制仓位、不提前押注
5. 宁可错过最低点，不提前预判接飞刀
6.3 适用边界约束
1. 两融数据仅对大盘、行业板块、大盘两融标的有效；中小盘题材股、非两融标的参考价值极低
2. 技术结构适用于指数与主流赛道，对纯题材妖股、庄股有效性有限
3. 所有结论均为短期技术推演，不预测长期行情，不做基本面定价判断
6.4 强制风险提示
所有分析结果必须强制标注「仅技术推演，不构成投资建议」，明确说明无法覆盖突发政策、外围波动、重大公告等不可控变量。

七、部署与快速上手
7.1 环境依赖
pip install akshare pandas numpy TA-Lib
注：TA-Lib 安装需对应 Python 版本与系统环境，Windows 可通过 whl 包安装。
7.2 快速调用示例
# 1. 先跑大盘总控
market_status = skill6_market_overview_analysis()
print("大盘操作窗口：", market_status["当前操作窗口"])

# 2. 单只个股复盘
result = skill1_support_pressure_review("600089", "特变电工")
print(result)

# 3. 单只个股预测
predict = skill2_tomorrow_trend_predict("002475", "立讯精密", market_env_score=3)
print(predict)
7.3 参数配置说明
所有可调阈值、权重、周期参数统一收口在GLOBAL_CONFIG字典中，日常优化仅需修改该配置区，无需改动核心逻辑代码。

八、持续迭代优化机制
8.1 日度复盘校验
每日对比「大盘结构结论 + 技术面 + 两融面」的推演结论与实际走势，分别拆解偏差原因，记录到优化日志。
8.2 周度汇总优化
每周汇总各 Skill 信号准确率，优化极值阈值、概率基准、权重占比，更新GLOBAL_CONFIG参数。
8.3 月度校准升级
月度校准不同市场环境（牛市 / 熊市 / 震荡市）下的信号有效性，调整结构判定规则、因子权重，适配当前市场风格。