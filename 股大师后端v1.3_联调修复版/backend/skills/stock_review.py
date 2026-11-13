"""个股复盘 Skill — 技术面 + 基本面 + 资金流向综合分析"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List

from skills.analysis_engine import skill3_stock_special_review, skill1_support_pressure_review
from data.quote_service import quote_service


class StockReviewSkill:
    """个股复盘分析 Skill — v1.1 接入真实量化分析引擎"""

    _executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="analysis_engine")

    @staticmethod
    async def execute(symbol: str) -> Dict[str, Any]:
        """执行个股复盘分析

        1. 优先调用 analysis_engine v1.1 的 skill3 + skill1 进行真实量化分析
        2. 数据获取失败时如实告知（0.6.0：绝不输出假数据冒充分析结果）
        """
        # 获取股票名称 + 行情快照
        # 0.6.0 修复：超时 2s → 28s——盘后/冷启动时 quote_service 内部快照拉取
        # 需 15-25s（备源全量），2s 必然超时导致复盘永远拿不到真实行情而走假数据
        quote = None
        stock_name = symbol
        try:
            quote = await asyncio.wait_for(quote_service.get_quote(symbol), timeout=28.0)
            if quote and quote.name:
                stock_name = quote.name
        except Exception:
            quote = None

        # 在线程池中执行同步的分析引擎（避免阻塞事件循环）
        loop = asyncio.get_event_loop()

        try:
            # 调用 skill3: 个股专项复盘（四类矛盾检测、真假突破、多情景推演）
            skill3_result = await asyncio.wait_for(
                loop.run_in_executor(
                    StockReviewSkill._executor,
                    lambda: skill3_stock_special_review(symbol, stock_name),
                ),
                timeout=15.0,
            )

            # 调用 skill1: 支撑压力复盘（三档支撑/压力、筹码峰、区间定性）
            skill1_result = await asyncio.wait_for(
                loop.run_in_executor(
                    StockReviewSkill._executor,
                    lambda: skill1_support_pressure_review(symbol, stock_name),
                ),
                timeout=15.0,
            )

            # 0.6.0：分析引擎数据受限 → 如实告知，不再降级到假数据
            if skill3_result.get("突破/跌破判定", "").startswith("数据获取受限"):
                return StockReviewSkill._build_unavailable_result(symbol, stock_name, quote)

            return StockReviewSkill._build_result_from_engine(symbol, stock_name, skill3_result, skill1_result)

        except Exception:
            # 0.6.0：分析引擎异常 → 如实告知（绝不输出假指标冒充真实分析）
            return StockReviewSkill._build_unavailable_result(symbol, stock_name, quote)

    @staticmethod
    def _build_unavailable_result(symbol: str, stock_name: str, quote) -> Dict[str, Any]:
        """数据源不可用时的诚实降级（0.6.0）：
        明确告知数据暂不可得，仅展示已取得的真实行情（如有），绝不编造指标。"""
        metrics = []
        if quote:
            chg_cls = "up" if quote.change_percent >= 0 else "down"
            metrics = [
                {"label": "现价", "value": f"{quote.current_price:.2f}", "cls": chg_cls},
                {"label": "涨跌幅", "value": f"{quote.change_percent:+.2f}%", "cls": chg_cls},
            ]
        analysis = (
            "当前数据源暂未响应，暂时无法生成完整复盘分析。\n"
            "建议：稍后重试（说「复盘" + stock_name + "」），或先手动刷新行情。"
        )
        return {
            "title": f"{symbol} {stock_name} 个股复盘",
            "subtitle": "数据源暂未响应",
            "metrics": metrics,
            "analysis": analysis,
            "rating": 0,
            "ratingLabel": "数据受限",
            "reply": f"数据获取受限：{stock_name}({symbol}) 的分析数据源暂时没有响应，为避免误导我不会编造指标。你可以稍后再试一次。",
            "quote": {
                "symbol": symbol,
                "name": stock_name,
                "current_price": quote.current_price if quote else 0.0,
                "change_percent": quote.change_percent if quote else 0.0,
            },
        }

    @staticmethod
    def _build_result_from_engine(
        symbol: str,
        stock_name: str,
        skill3_result: Dict[str, Any],
        skill1_result: Dict[str, Any],
    ) -> Dict[str, Any]:
        """将分析引擎返回结果包装为前端需要的标准格式"""

        # 构造分析正文
        analysis_parts: List[str] = []

        # 1. 突破/跌破判定
        break_conclusion = skill3_result.get("突破/跌破判定", "")
        analysis_parts.append(f"**突破/跌破判定**：{break_conclusion}")

        # 2. 核心矛盾清单
        contradictions = skill3_result.get("核心矛盾清单", [])
        if contradictions and contradictions != ["无明显背离矛盾"]:
            analysis_parts.append("**核心矛盾检测**")
            for c in contradictions:
                analysis_parts.append(f"• {c}")
        else:
            analysis_parts.append("**核心矛盾检测**：未发现显著背离矛盾")

        # 3. 支撑压力
        if skill1_result.get("收盘区间") and skill1_result.get("收盘区间") != "数据获取受限":
            sp_parts = [
                f"**支撑压力分析**",
                f"• 第一支撑/压力：{skill1_result.get('第一支撑')} / {skill1_result.get('第一压力')}",
                f"• 第二支撑/压力：{skill1_result.get('第二支撑')} / {skill1_result.get('第二压力')}",
                f"• 强支撑/强压力：{skill1_result.get('强支撑')} / {skill1_result.get('强压力')}",
                f"• 收盘区间：{skill1_result.get('收盘区间')}（强度得分 {skill1_result.get('区间强度得分', 0)}/4）",
                f"• 昨日验证：{skill1_result.get('昨日支撑压力验证', '')}",
            ]
            analysis_parts.append("\n".join(sp_parts))

        # 4. 多情景推演
        scenarios = skill3_result.get("多情景推演", [])
        if scenarios:
            analysis_parts.append("**多情景推演**")
            for s in scenarios:
                line = f"• {s.get('情景', '')}（概率 {s.get('概率', '')}）"
                if s.get("触发条件"):
                    line += f" — 触发条件：{s['触发条件']}"
                if s.get("目标价位"):
                    line += f" — 目标价：{s['目标价位']}"
                if s.get("止损价位"):
                    line += f" — 止损价：{s['止损价位']}"
                analysis_parts.append(line)

        analysis = "\n\n".join(analysis_parts)

        # 计算 rating
        zone_score = skill1_result.get("区间强度得分", 2)
        break_ok = "有效突破" in break_conclusion
        has_divergence = any("背离" in c for c in contradictions)

        if zone_score >= 3 and break_ok and not has_divergence:
            rating, rating_label = "buy", "买入"
        elif zone_score >= 2:
            rating, rating_label = "hold", "观望"
        else:
            rating, rating_label = "sell", "谨慎"

        # 构造 metrics
        latest_close = skill1_result.get("最新收盘价")
        metrics = []
        if latest_close is not None:
            metrics.append({"label": "最新收盘价", "value": f"{latest_close}", "cls": ""})
        if skill1_result.get("收盘区间"):
            zone_cls = "up" if zone_score >= 3 else ("down" if zone_score <= 1 else "")
            metrics.append({"label": "收盘区间", "value": skill1_result["收盘区间"], "cls": zone_cls})
        metrics.append({"label": "突破判定", "value": break_conclusion, "cls": "up" if break_ok else ""})

        # 构造自然语言摘要
        reply = f"{stock_name}({symbol}) 量化复盘：{break_conclusion}，当前处于{skill1_result.get('收盘区间', '未知区间')}。"
        if scenarios:
            reply += f" 基准情景概率{scenarios[0].get('概率', '')}。"

        return {
            "title": f"{symbol} {stock_name} 个股复盘",
            "subtitle": f"量化分析引擎 v1.1 | {skill1_result.get('收盘区间', '')}",
            "metrics": metrics,
            "analysis": analysis,
            "rating": rating,
            "ratingLabel": rating_label,
            "reply": reply,
            "quote": {
                "symbol": symbol,
                "name": stock_name,
            },
            "engine_data": {
                "skill1": skill1_result,
                "skill3": skill3_result,
            },
        }

