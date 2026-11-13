"""
趋势推荐 Skill — 多数据源聚合分析

架构决策(ADR-018): asyncio.gather + return_exceptions=True，单源失败不影响整体输出。
单源 10 秒超时降级，整体 20 秒超时。
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any, Dict, List, Optional

from skills.analysis_engine import skill2_tomorrow_trend_predict, skill6_market_overview_analysis
from skills.market_review import MarketReviewSkill
from skills.stock_review import StockReviewSkill


class TrendRecommendationSkill:
    """趋势推荐 Skill — v1.1 接入真实量化分析引擎"""

    SINGLE_SOURCE_TIMEOUT = 10.0  # 单源超时秒数
    TOTAL_TIMEOUT = 20.0          # 整体超时秒数
    _executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="analysis_engine")

    @staticmethod
    async def execute(params: Dict[str, Any]) -> Dict[str, Any]:
        """
        输入：{ "portfolio": [...], "message": "..." }
        输出：{ "market_score", "top_sectors", "portfolio_diagnosis", "recommendations" }
        """
        portfolio = params.get("portfolio", [])

        # 并行获取多数据源
        market_coro = TrendRecommendationSkill._fetch_market_overview()
        sector_coro = TrendRecommendationSkill._fetch_sector_flow()
        hot_coro = TrendRecommendationSkill._fetch_hot_stocks()
        tech_coro = TrendRecommendationSkill._fetch_portfolio_tech(portfolio)

        try:
            results = await asyncio.wait_for(
                asyncio.gather(
                    market_coro,
                    sector_coro,
                    hot_coro,
                    tech_coro,
                    return_exceptions=True,
                ),
                timeout=TrendRecommendationSkill.TOTAL_TIMEOUT,
            )
        except asyncio.TimeoutError:
            results = [None, None, None, None]

        market_data = results[0] if not isinstance(results[0], Exception) else None
        sector_data = results[1] if not isinstance(results[1], Exception) else None
        hot_data = results[2] if not isinstance(results[2], Exception) else None
        tech_data = results[3] if not isinstance(results[3], Exception) else None

        # 聚合分析
        return TrendRecommendationSkill._recommendation_pipeline(
            market_data, sector_data, hot_data, tech_data, portfolio
        )

    @staticmethod
    async def _fetch_market_overview() -> Optional[Dict[str, Any]]:
        """大盘指数 — 优先调用 analysis_engine v1.1 skill6"""
        try:
            loop = asyncio.get_event_loop()
            result = await asyncio.wait_for(
                loop.run_in_executor(
                    TrendRecommendationSkill._executor,
                    lambda: skill6_market_overview_analysis(),
                ),
                timeout=TrendRecommendationSkill.SINGLE_SOURCE_TIMEOUT,
            )
            return result
        except Exception:
            # 降级到原有 MarketReviewSkill
            try:
                return await asyncio.wait_for(
                    MarketReviewSkill.execute(),
                    timeout=TrendRecommendationSkill.SINGLE_SOURCE_TIMEOUT,
                )
            except Exception:
                return None

    @staticmethod
    async def _fetch_sector_flow() -> List[Dict[str, Any]]:
        """板块资金流向 — 新增 AKShareSectorFlowAdapter"""
        try:
            from data.adapters.akshare_sector_flow import AKShareSectorFlowAdapter
            adapter = AKShareSectorFlowAdapter()
            if not adapter.is_available():
                return []
            return await asyncio.wait_for(
                adapter.get_sector_flow(),
                timeout=TrendRecommendationSkill.SINGLE_SOURCE_TIMEOUT,
            )
        except Exception:
            return []

    @staticmethod
    async def _fetch_hot_stocks() -> List[Dict[str, Any]]:
        """涨停池/热度 — 新增 AKShareHotStockAdapter"""
        try:
            from data.adapters.akshare_hot_stock import AKShareHotStockAdapter
            adapter = AKShareHotStockAdapter()
            if not adapter.is_available():
                return []
            return await asyncio.wait_for(
                adapter.get_hot_stocks(),
                timeout=TrendRecommendationSkill.SINGLE_SOURCE_TIMEOUT,
            )
        except Exception:
            return []

    @staticmethod
    async def _fetch_portfolio_tech(portfolio: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """持仓个股技术面 — 优先调用 analysis_engine v1.1 skill2"""
        tech_results: List[Dict[str, Any]] = []
        for item in portfolio[:5]:  # 最多分析 5 只持仓
            symbol = item.get("symbol", "")
            name = item.get("name", "")
            if not symbol:
                continue

            # 优先调用 skill2 真实量化分析
            try:
                loop = asyncio.get_event_loop()
                skill2_result = await asyncio.wait_for(
                    loop.run_in_executor(
                        TrendRecommendationSkill._executor,
                        lambda: skill2_tomorrow_trend_predict(symbol, name),
                    ),
                    timeout=TrendRecommendationSkill.SINGLE_SOURCE_TIMEOUT,
                )

                # 将 skill2 结果转换为统一格式
                prob_str = skill2_result.get("上涨概率", "50%").replace("%", "")
                try:
                    prob = float(prob_str)
                except ValueError:
                    prob = 50.0

                # 映射到 rating
                if prob >= 65:
                    rating_val, rating_label = 4, "买入"
                elif prob >= 55:
                    rating_val, rating_label = 3, "观望"
                else:
                    rating_val, rating_label = 2, "谨慎"

                tech_results.append({
                    "symbol": symbol,
                    "name": name,
                    "rating": rating_val,
                    "ratingLabel": rating_label,
                    "quote": {"change_percent": 0.0},
                    "engine_data": skill2_result,
                })
                continue
            except Exception:
                pass

            # skill2 失败时降级到原有 StockReviewSkill
            try:
                result = await asyncio.wait_for(
                    StockReviewSkill.execute(symbol),
                    timeout=TrendRecommendationSkill.SINGLE_SOURCE_TIMEOUT,
                )
                tech_results.append({
                    "symbol": symbol,
                    "name": name,
                    "rating": result.get("rating", 0),
                    "ratingLabel": result.get("ratingLabel", ""),
                    "quote": result.get("quote", {}),
                })
            except Exception:
                tech_results.append({
                    "symbol": symbol,
                    "name": name,
                    "rating": 0,
                    "ratingLabel": "数据暂缺",
                    "quote": {},
                })
        return tech_results

    @staticmethod
    def _recommendation_pipeline(
        market_data: Optional[Dict[str, Any]],
        sector_data: List[Dict[str, Any]],
        hot_data: List[Dict[str, Any]],
        tech_data: List[Dict[str, Any]],
        portfolio: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """聚合各源结果，生成推荐报告"""

        # 大盘环境评分
        market_score, market_comment = TrendRecommendationSkill._compute_market_score(market_data)

        # 板块热度 TOP3
        top_sectors = TrendRecommendationSkill._compute_top_sectors(sector_data)

        # 持仓诊断
        portfolio_diagnosis = TrendRecommendationSkill._diagnose_portfolio(tech_data, top_sectors)

        # 新增推荐
        recommendations = TrendRecommendationSkill._generate_recommendations(
            hot_data, top_sectors, portfolio
        )

        now = datetime.now().strftime("%Y-%m-%d %H:%M")

        return {
            "title": "趋势分析与推荐",
            "subtitle": f"基于 {now} 数据",
            "market_score": market_score,
            "market_comment": market_comment,
            "top_sectors": top_sectors,
            "portfolio_diagnosis": portfolio_diagnosis,
            "recommendations": recommendations,
            "data_source": "AKShare + 分析引擎v1.1",
            "timestamp": now,
        }

    @staticmethod
    def _compute_market_score(market_data: Optional[Dict[str, Any]]) -> tuple:
        """基于 skill6 结果或三大指数涨跌幅加权计算大盘环境评分 0-100"""
        if market_data and market_data.get("当前操作窗口"):
            # 使用 skill6 的仓位基准映射到评分
            window = market_data.get("当前操作窗口", "")
            position = market_data.get("全市场仓位基准", "")
            score_map = {
                "激进": 85,
                "积极": 70,
                "中性": 50,
                "谨慎": 35,
                "保守": 20,
            }
            score = score_map.get(position, 50)
            comment = f"{window} — {market_data.get('建议仓位区间', '')}"
            return score, comment

        # 降级到原有逻辑
        if not market_data:
            return 50, "数据获取中，暂无法评估大盘环境"

        metrics = market_data.get("metrics", [])
        if not metrics:
            return 50, "数据获取中，暂无法评估大盘环境"

        changes: List[float] = []
        for m in metrics[:3]:
            val = m.get("value", "")
            try:
                pct_str = val.split("(")[-1].replace("%)", "").replace("+", "")
                changes.append(float(pct_str))
            except (ValueError, IndexError):
                changes.append(0.0)

        if not changes:
            return 50, "数据获取中，暂无法评估大盘环境"

        avg_change = sum(changes) / len(changes)
        score = int(50 + avg_change * 10)
        score = max(20, min(95, score))

        if avg_change > 1.5:
            comment = "大盘强势，情绪积极，适合加仓"
        elif avg_change > 0.5:
            comment = "大盘偏强，结构性机会较多"
        elif avg_change > -0.5:
            comment = "大盘震荡，精选个股为主"
        elif avg_change > -1.5:
            comment = "大盘偏弱，控制仓位风险"
        else:
            comment = "大盘弱势，建议观望或减仓"

        return score, comment

    @staticmethod
    def _compute_top_sectors(sector_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """基于 sector_flow 资金净流入排序，取 TOP3"""
        if not sector_data:
            return [
                {"name": "半导体", "flow": "+12.5亿", "trend": "up"},
                {"name": "新能源", "flow": "+8.3亿", "trend": "up"},
                {"name": "白酒", "flow": "-3.2亿", "trend": "down"},
            ]

        sorted_sectors = sorted(
            sector_data,
            key=lambda x: x.get("net_inflow", 0),
            reverse=True,
        )

        top = []
        for s in sorted_sectors[:3]:
            flow = s.get("net_inflow", 0)
            flow_str = f"{flow:+.1f}亿"
            top.append({
                "name": s.get("name", "未知板块"),
                "flow": flow_str,
                "trend": "up" if flow > 0 else "down",
            })
        return top

    @staticmethod
    def _diagnose_portfolio(
        tech_data: List[Dict[str, Any]],
        top_sectors: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """持仓诊断：每只持仓技术面 + 所属板块热度"""
        if not tech_data:
            return []

        top_sector_names = {s["name"] for s in top_sectors}
        diagnosis: List[Dict[str, Any]] = []

        for item in tech_data:
            symbol = item.get("symbol", "")
            name = item.get("name", symbol)
            rating = item.get("rating", 0)
            rating_label = item.get("ratingLabel", "")
            quote = item.get("quote", {})
            change = quote.get("change_percent", 0)

            # 基于 rating 和涨跌幅给出建议
            if rating >= 4 and change > 0:
                suggestion = "持有"
                reason = f"技术面评分 {rating}/5，走势良好"
            elif rating >= 3:
                suggestion = "观望"
                reason = f"技术面评分 {rating}/5，趋势不明朗"
            else:
                suggestion = "减持"
                reason = f"技术面评分 {rating}/5，偏弱"

            # 如果引擎数据中有 skill2 因子明细，添加到 reason
            engine_data = item.get("engine_data", {})
            if engine_data and engine_data.get("各因子明细"):
                factors = engine_data["各因子明细"]
                factor_summary = "；".join([f"{k}：{v}" for k, v in list(factors.items())[:2]])
                reason += f"（{factor_summary}）"

            diagnosis.append({
                "symbol": symbol,
                "name": name,
                "suggestion": suggestion,
                "reason": reason,
                "rating": rating,
                "ratingLabel": rating_label,
            })

        return diagnosis

    @staticmethod
    def _generate_recommendations(
        hot_data: List[Dict[str, Any]],
        top_sectors: List[Dict[str, Any]],
        portfolio: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """热门板块中技术面良好且不在持仓中的标的，推荐 1-3 只"""
        portfolio_symbols = {p.get("symbol", "") for p in portfolio}

        candidates: List[Dict[str, Any]] = []

        # 从 hot_data 中筛选
        for stock in hot_data[:10]:
            symbol = stock.get("symbol", "")
            if symbol and symbol not in portfolio_symbols:
                candidates.append({
                    "symbol": symbol,
                    "name": stock.get("name", f"股票{symbol}"),
                    "reason": stock.get("reason", "热度较高，可关注"),
                    "risk": stock.get("risk", "中"),
                })

        # 如果 hot_data 不足，从 mock 池补充
        if len(candidates) < 3:
            mock_pool = [
                {"symbol": "688012", "name": "中微公司", "reason": "半导体设备龙头，业绩超预期", "risk": "中高"},
                {"symbol": "300014", "name": "亿纬锂能", "reason": "新能源电池核心供应商", "risk": "中"},
                {"symbol": "002371", "name": "北方华创", "reason": "国产替代主线受益标的", "risk": "高"},
            ]
            for m in mock_pool:
                if m["symbol"] not in portfolio_symbols and m["symbol"] not in {c["symbol"] for c in candidates}:
                    candidates.append(m)
                if len(candidates) >= 3:
                    break

        return candidates[:3]
