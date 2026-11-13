"""Orchestrator — 解析新 Skill6 扁平/嵌套输出"""
from __future__ import annotations
import asyncio, time, math
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional

# 编排层专用线程池 — 避免和其他模块的默认池竞争
# 20 核 CPU / I/O 密集型网络请求 → 给 8 线程足够并发
_ORCH_EXECUTOR = ThreadPoolExecutor(max_workers=8, thread_name_prefix="orchestrator")
from skills.analysis_engine import (
    skill6_market_overview_analysis, skill5_margin_trade_analysis)

_SKILL6_CACHE: Dict[str, Any] = {"result": None, "ts": 0.0, "ttl": 30.0}


def _parse_skill6_raw(raw: Dict[str, Any]) -> Dict[str, Any]:
    """把 Skill6 原始输出（嵌套中文键）拉平成 orchestrator 需要的统一格式"""
    if not isinstance(raw, dict):
        return {}

    # 综合评分 → market_env_score（0-10 映射）
    # Skill6 score 范围 ~0-5，映射到 0-10
    score = raw.get("综合评分", None)
    if score is not None:
        # Skill6 内部 score 大概 0-5 范围，乘 2 映射到 0-10
        score_10 = max(0, min(10, score * 2))
        market_env_score = round(score_10, 1)
    else:
        market_env_score = 5  # 保守默认

    # 指数趋势 — 取上证指数
    index_trend = raw.get("核心指数趋势", {}) or {}
    sh = index_trend.get("上证指数", {})
    trend_parts = []
    for name in ["上证指数", "创业板指", "科创50"]:
        idx = index_trend.get(name, {})
        if isinstance(idx, dict) and idx.get("短期趋势"):
            trend_parts.append(f"{name}{idx['短期趋势']}")
    trend = "; ".join(trend_parts)

    # 周期状态
    cycle = str(raw.get("周期状态", ""))

    # 资金面验证 → money 简要
    fund = raw.get("资金面验证", {}) or {}
    money_parts = []
    if fund.get("北向资金净流入(亿)") is not None:
        money_parts.append(f"北向{fund['北向状态']}")
    if fund.get("行业总成交额(亿)") is not None:
        money_parts.append(f"成交额{fund['行业总成交额(亿)']}亿")
        money_parts.append(f"{fund.get('量能状态','')}")
    money = " ".join(money_parts)

    # 赛道强弱（取领涨前3）
    boards = raw.get("赛道强弱排行", {}) or {}
    top = boards.get("领涨板块", []) or []
    bottom = boards.get("领跌板块", []) or []

    # events — 新 Skill6 没显式 P0/P1，这里给个简化生成
    events: List[Dict[str, Any]] = []
    if isinstance(sh, dict):
        if sh.get("短期趋势") == "下降" and sh.get("中期趋势") == "下降":
            events.append({"level": "P1", "desc": "指数短中期双降"})
    if score is not None and score < 2.5:
        events.append({"level": "P2", "desc": f"综合评分偏低({score})"})

    return {
        "market_env_score": market_env_score,
        "trend": trend,
        "cycle": cycle,
        "money": money,
        "top_boards": top,
        "bottom_boards": bottom,
        "events": events,
    }


async def ensure_market_overview(force: bool = False) -> Dict[str, Any]:
    now = time.time()
    if not force and _SKILL6_CACHE["result"] and (now - _SKILL6_CACHE["ts"]) < _SKILL6_CACHE["ttl"]:
        cached = dict(_SKILL6_CACHE["result"])
        cached["source"] = "cache"
        cached["ok"] = True
        return cached
    try:
        # Skill6 是同步函数（akshare 非 async），放到线程池执行
        loop = asyncio.get_running_loop()
        raw = await asyncio.wait_for(
            loop.run_in_executor(_ORCH_EXECUTOR, skill6_market_overview_analysis),
            timeout=25.0
        )
    except asyncio.TimeoutError:
        return _fallback("Skill6 timeout 25s")
    except Exception as e:
        return _fallback(f"Skill6 error: {e!s}")

    parsed = _parse_skill6_raw(raw)

    # 根据 market_env_score 映射 position_level
    env_score = parsed["market_env_score"]
    if env_score >= 8:
        pos_level = "激进"
    elif env_score >= 6:
        pos_level = "积极"
    elif env_score >= 4:
        pos_level = "中性"
    elif env_score >= 2:
        pos_level = "谨慎"
    else:
        pos_level = "保守"

    result = {
        "ok": True,
        "market_env_score": env_score,
        "position_level": pos_level,
        "trend": parsed["trend"],
        "structure": "",  # 日线不提供分钟结构
        "cycle": parsed["cycle"],
        "money": parsed["money"],
        "top_boards": parsed["top_boards"],
        "bottom_boards": parsed["bottom_boards"],
        "events": parsed["events"],
        "source": "skill6",
        "_raw_excerpt": {
            name: raw.get(name) for name in [
                "核心指数趋势", "资金面验证", "赛道强弱排行",
                "当前操作窗口", "全市场仓位基准", "建议仓位区间",
            ]
        } if isinstance(raw, dict) else {},
    }
    _SKILL6_CACHE["result"] = dict(result)
    _SKILL6_CACHE["ts"] = now
    return result


def _fallback(note: str) -> Dict[str, Any]:
    return {
        "ok": False,
        "market_env_score": 5,
        "position_level": "中性",
        "trend": "", "structure": "", "cycle": "", "money": "",
        "events": [],
        "source": "fallback",
        "note": note,
    }


async def verify_margin(code: Optional[str], level: str = "stock") -> Dict[str, Any]:
    if not code:
        return {"ok": False, "note": "no code"}
    try:
        loop = asyncio.get_running_loop()
        raw = await asyncio.wait_for(
            loop.run_in_executor(_ORCH_EXECUTOR, lambda: skill5_margin_trade_analysis(level=level, stock_code=code)),
            timeout=6.0)
        return {"ok": True, "data": raw, "source": "skill5"}
    except Exception as e:
        return {"ok": False, "note": f"Skill5 skip: {e!s}"}


async def run_pipeline(
    intent: str, handler_result: Dict[str, Any],
    msg: str = "", params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    params = params or {}
    codes = params.get("stock_codes", [])
    code = codes[0] if codes else None
    # 轻量意图：不跑大盘总控、不追加 [risk] 注记（身份/寒暄/解释/澄清等非分析类
    # 回复不应带事件提示，也省一次行情网络请求）
    lightweight = {"portfolio_query", "quote_query", "alert_set", "alert_list", "help",
                   "identity", "chitchat", "explanation", "default", "unknown",
                   "skin_switch"}
    market_ctx: Dict[str, Any] = {}
    margin_ctx: Dict[str, Any] = {}
    if intent not in lightweight:
        tasks: List[asyncio.Task] = [asyncio.create_task(ensure_market_overview())]
        need_margin = intent in {"stock_review", "trend_recommendation",
                                  "stock_screening", "industry_analysis", "intraday"}
        if need_margin and code:
            tasks.append(asyncio.create_task(verify_margin(code)))
        results = await asyncio.gather(*tasks, return_exceptions=False)
        market_ctx = results[0] or {}
        if len(results) > 1:
            margin_ctx = results[1] or {}
    data = dict(handler_result.get("data", {}) or {})
    if market_ctx:
        data["market_context"] = market_ctx
    if margin_ctx:
        data["margin_context"] = margin_ctx
    risk_notes: List[str] = []
    if market_ctx.get("source") == "fallback":
        risk_notes.append(f"[risk] 大盘评估降级：{market_ctx.get('note','')}")
    pos_level = market_ctx.get("position_level", "")
    if pos_level in {"谨慎", "保守"} and intent in {"trend_recommendation", "stock_screening"}:
        risk_notes.append(f"[risk] 大盘仓位等级「{pos_level}」，建议降低风险偏好")
    for ev in market_ctx.get("events", []):
        if isinstance(ev, dict) and ev.get("level") in {"P0", "P1"}:
            risk_notes.append(f"[risk] {ev.get('level')}事件：{ev.get('desc','')}")
            break
    result = dict(handler_result)
    result["data"] = data
    if risk_notes:
        result["reply"] = result.get("reply", "") + "\n\n" + "\n".join(risk_notes)
        result["_risk_notes"] = risk_notes
    return result
