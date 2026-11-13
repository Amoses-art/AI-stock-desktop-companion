"""预演分析 Skill — 假设涨跌情景分析"""

from __future__ import annotations

import asyncio
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict

from skills.analysis_engine import skill3_stock_special_review, skill2_tomorrow_trend_predict


class SimulationSkill:
    """预演分析 Skill — v1.1 接入真实量化分析引擎"""

    _executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="analysis_engine")

    @staticmethod
    async def execute(params: Dict[str, Any]) -> Dict[str, Any]:
        symbol = params.get("stock_code", "")
        current_price = params.get("current_price", 0.0)
        msg = params.get("message", "")

        if current_price <= 0:
            current_price = 100.0

        # 尝试从消息中提取涨跌百分比
        pct_match = re.search(r"(\d+(?:\.\d+)?)\s*%", msg)
        target_pct = float(pct_match.group(1)) if pct_match else 10.0

        target_price = current_price * (1 + target_pct / 100)
        loss_price = current_price * (1 - target_pct / 100)

        stock_name = symbol
        try:
            from data.quote_service import quote_service
            quote = await asyncio.wait_for(quote_service.get_quote(symbol), timeout=2.0)
            if quote and quote.name:
                stock_name = quote.name
        except Exception:
            pass

        # 调用分析引擎获取真实分析结果
        loop = asyncio.get_event_loop()
        skill3_result = None
        skill2_result = None

        if symbol:
            try:
                skill3_result = await asyncio.wait_for(
                    loop.run_in_executor(
                        SimulationSkill._executor,
                        lambda: skill3_stock_special_review(symbol, stock_name),
                    ),
                    timeout=15.0,
                )
            except Exception:
                pass

            try:
                skill2_result = await asyncio.wait_for(
                    loop.run_in_executor(
                        SimulationSkill._executor,
                        lambda: skill2_tomorrow_trend_predict(symbol, stock_name),
                    ),
                    timeout=15.0,
                )
            except Exception:
                pass

        return SimulationSkill._build_result(
            symbol, stock_name, current_price, target_pct, target_price, loss_price,
            skill3_result, skill2_result
        )

    @staticmethod
    def _build_result(
        symbol: str,
        stock_name: str,
        current_price: float,
        target_pct: float,
        target_price: float,
        loss_price: float,
        skill3_result: Dict[str, Any] = None,
        skill2_result: Dict[str, Any] = None,
    ) -> Dict[str, Any]:
        """构建预演分析结果"""

        analysis_parts = [f"**假设预演：{stock_name or symbol or '当前标的'}**"]
        analysis_parts.append(f"• 当前价格：{current_price:.2f} 元")
        analysis_parts.append(f"• 假设上涨 {target_pct}%：目标价 {target_price:.2f} 元")

        # 基于真实分析引擎结果增强预演
        if skill3_result and not skill3_result.get("突破/跌破判定", "").startswith("数据获取受限"):
            break_conclusion = skill3_result.get("突破/跌破判定", "")
            analysis_parts.append(f"• 当前突破状态：{break_conclusion}")

            scenarios = skill3_result.get("多情景推演", [])
            if scenarios:
                analysis_parts.append("\n**基于量化模型的情景推演**")
                for s in scenarios:
                    line = f"• {s.get('情景', '')}（概率 {s.get('概率', '')}）"
                    if s.get("目标价位"):
                        line += f" — 目标价 {s['目标价位']}"
                    analysis_parts.append(line)

            contradictions = skill3_result.get("核心矛盾清单", [])
            if contradictions and contradictions != ["无明显背离矛盾"]:
                analysis_parts.append("\n**风险提示**：")
                for c in contradictions[:3]:
                    analysis_parts.append(f"  — {c}")

        if skill2_result and not skill2_result.get("上涨概率", "").startswith("50"):
            analysis_parts.append(
                f"\n• 趋势预测：上涨概率 {skill2_result.get('上涨概率', '')}，"
                f"定性为{skill2_result.get('强弱定性', '')}"
            )
            factors = skill2_result.get("各因子明细", {})
            if factors:
                analysis_parts.append("• 因子明细：")
                for k, v in factors.items():
                    analysis_parts.append(f"  — {k}：{v}")

        # 通用预演逻辑
        analysis_parts.append(
            f"\n• 假设下跌 {target_pct}%：目标价 {loss_price:.2f} 元\n"
            f"  — 关注 MA20 / MA60 支撑是否有效\n"
            f"  — 若跌破支撑且放量，需警惕趋势反转"
        )

        analysis_parts.append(
            "\n**结论**：预演仅供参考，实际走势受宏观政策、行业事件、资金流向等多因素影响，"
            "建议结合大盘环境和个股基本面综合判断。"
        )

        analysis = "\n".join(analysis_parts)

        # 基于 skill2 的上涨概率决定 rating
        rating, rating_label = "hold", "观望"
        if skill2_result:
            prob_str = skill2_result.get("上涨概率", "50%").replace("%", "")
            try:
                prob = float(prob_str)
                if prob >= 65:
                    rating, rating_label = "buy", "买入"
                elif prob <= 40:
                    rating, rating_label = "sell", "谨慎"
            except ValueError:
                pass

        reply = f"{stock_name or symbol} 预演分析：上涨{target_pct}%目标价{target_price:.2f}元，"
        if skill2_result:
            reply += f"上涨概率{skill2_result.get('上涨概率', '未知')}。"
        else:
            reply += "数据获取受限，预演基于通用模型。"

        return {
            "title": "预演分析",
            "subtitle": f"标的: {stock_name}({symbol})" if symbol else "通用情景",
            "metrics": [
                {"label": "当前价", "value": f"{current_price:.2f}", "cls": ""},
                {"label": f"+{target_pct}%", "value": f"{target_price:.2f}", "cls": "up"},
                {"label": f"-{target_pct}%", "value": f"{loss_price:.2f}", "cls": "down"},
            ],
            "analysis": analysis,
            "rating": rating,
            "ratingLabel": rating_label,
            "reply": reply,
            "engine_data": {
                "skill2": skill2_result,
                "skill3": skill3_result,
            },
        }
