"""
Agent 委托服务 — Python 后端调用 aily Agent 执行深度研究 Skill

架构决策(ADR-023/025):
- 深度研究 Skill 输出「摘要 + 链接」而非完整报告
- L2 轻量分析走本地 Python Skill（1~3秒）
- L3 深度研究走后端搜索+分析（3~10秒），不依赖外部 Agent API

方案选择：方案1（后端直接处理）
理由：
1. 不修改前端代码（任务明确约束）
2. 后端 JSON Lines RPC 为同步通信，后端直接处理可保持协议不变
3. 无需等待外部 Agent 异步返回，用户体验更可控
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from core.search_service import search_service


@dataclass
class AgentResult:
    """Agent 委托执行结果"""
    reply: str
    data: Dict[str, Any] = field(default_factory=dict)
    attachments: List[Dict[str, str]] = field(default_factory=list)
    task_id: Optional[str] = None
    status: str = "completed"  # pending / running / completed / failed


class AgentDelegationService:
    """Agent 委托服务

    实现 L2（轻量分析）和 L3（深度研究）两条路径：
    - L2: 直接调用本地分析引擎已有 Skill，结合 SearchService 获取实时信息
    - L3: 基于 SearchService 获取的实时网络数据，生成深度结构化分析报告

    所有输出统一包装为标准卡片格式：
    {title, subtitle, metrics, analysis, rating, reply}
    """

    # Skill 名称 -> 用户友好的功能描述
    SKILL_DESCRIPTIONS: Dict[str, str] = {
        "stock_screening": "智能选股分析",
        "industry_analysis": "行业深度研究",
        "announcement_analysis": "公告解读",
        "earnings_review": "财报周期复盘",
        "market_review_l2": "跨市场比较分析",
        "market_review_l3": "长期策略研究",
    }

    # Skill -> 分析层级映射
    SKILL_LEVEL_MAP: Dict[str, str] = {
        "stock_screening": "l3",
        "industry_analysis": "l3",
        "announcement_analysis": "l3",
        "earnings_review": "l3",
        "market_review_l2": "l2",
        "market_review_l3": "l3",
    }

    async def delegate(self, skill_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """委托 aily Agent 执行深度研究 Skill

        根据 Skill 类型自动路由到 L2 或 L3 处理路径。
        永不抛异常，任何失败都降级到结构化提示。
        """
        try:
            level = self.SKILL_LEVEL_MAP.get(skill_name, "l3")
            if level == "l2":
                return await self._delegate_l2(skill_name, params)
            else:
                return await self._delegate_l3(skill_name, params)
        except Exception:
            # 任何异常都降级到友好的结构化提示
            return self._build_fallback_result(skill_name, params)

    async def _delegate_l2(self, skill_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """L2 轻量分析 — 直接调用本地 Skill + 搜索增强"""
        if skill_name == "market_review_l2":
            return await self._l2_market_cross(params)
        # 其他 Skill 默认走 L3（因为都是深度研究类）
        return await self._delegate_l3(skill_name, params)

    async def _delegate_l3(self, skill_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """L3 深度研究 — 搜索实时信息 + 生成结构化分析"""
        # 并行执行搜索（通用搜索 + 财经搜索）
        query = self._build_search_query(skill_name, params)
        search_coro = search_service.search(query, limit=5)
        finance_coro = search_service.search_finance(query, limit=5)

        try:
            general_results, finance_results = await asyncio.wait_for(
                asyncio.gather(search_coro, finance_coro, return_exceptions=True),
                timeout=12.0,
            )
            if isinstance(general_results, Exception):
                general_results = []
            if isinstance(finance_results, Exception):
                finance_results = []
        except asyncio.TimeoutError:
            general_results = []
            finance_results = []

        # 合并去重
        all_results = self._dedupe_results(general_results + finance_results)

        # 基于 Skill 类型生成结构化报告
        if skill_name == "stock_screening":
            return self._build_stock_screening_report(params, all_results)
        elif skill_name == "industry_analysis":
            return self._build_industry_report(params, all_results)
        elif skill_name == "announcement_analysis":
            return self._build_announcement_report(params, all_results)
        elif skill_name == "earnings_review":
            return self._build_earnings_report(params, all_results)
        elif skill_name == "market_review_l2":
            return self._build_market_l2_report(params, all_results)
        elif skill_name == "market_review_l3":
            return self._build_market_l3_report(params, all_results)
        else:
            return self._build_generic_report(skill_name, params, all_results)

    # === L2 具体实现 ===

    async def _l2_market_cross(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """L2 跨市场比较 — 调用本地 MarketAnalysisSkill L1 + 搜索增强"""
        from skills.market_analysis import MarketAnalysisSkill

        # 获取本地 L1 分析结果
        try:
            l1_result = await asyncio.wait_for(
                MarketAnalysisSkill.execute(level="l1"),
                timeout=10.0,
            )
        except Exception:
            l1_result = {}

        # 搜索跨市场信息
        query = f"A股 港股 美股 联动分析 {params.get('focus', '')}"
        search_results = await search_service.search(query, limit=5)

        # 合并生成 L2 报告
        return self._build_market_l2_report(params, search_results, l1_result)

    # === 报告生成器 ===

    def _build_stock_screening_report(
        self, params: Dict[str, Any], results: List[Any]
    ) -> Dict[str, Any]:
        """选股分析报告"""
        criteria = params.get("criteria", {})
        stock_codes = params.get("stock_codes", [])

        # 从搜索结果中提取关键信息
        snippets = [r.snippet for r in results if r.snippet]
        combined_info = "\n".join(snippets[:3])

        # 构建 metrics
        metrics = []
        sectors = criteria.get("sectors", [])
        if sectors:
            metrics.append({"label": "关注板块", "value": ",".join(sectors), "cls": ""})
        market_cap = criteria.get("market_cap", "")
        if market_cap:
            cap_label = {"large": "大盘蓝筹", "small_mid": "中小盘成长"}.get(market_cap, market_cap)
            metrics.append({"label": "市值偏好", "value": cap_label, "cls": ""})
        valuation = criteria.get("valuation", "")
        if valuation:
            val_label = {"undervalued": "低估值", "growth": "高成长"}.get(valuation, valuation)
            metrics.append({"label": "估值偏好", "value": val_label, "cls": ""})

        # 构建分析正文
        analysis_parts = ["**选股策略分析**"]
        if combined_info:
            analysis_parts.append("**市场信息聚合**")
            for r in results[:3]:
                if r.title and r.snippet:
                    analysis_parts.append(f"• {r.title}：{r.snippet[:80]}...")

        analysis_parts.append("\n**选股条件**")
        if sectors:
            analysis_parts.append(f"• 板块方向：{'、'.join(sectors)}")
        if market_cap:
            analysis_parts.append(f"• 市值偏好：{cap_label}")
        if valuation:
            analysis_parts.append(f"• 估值策略：{val_label}")

        analysis_parts.append(
            "\n**建议筛选维度**\n"
            "1. 基本面：营收增速>15%，ROE>10%，负债率<60%\n"
            "2. 技术面：股价站上MA20，MACD金叉或红柱放大\n"
            "3. 资金面：近5日主力净流入为正，北向资金增持\n"
            "4. 估值面：PE(TTM)处于近3年30%-70%分位"
        )

        if stock_codes:
            analysis_parts.append(
                f"\n**关注标的**：{', '.join(stock_codes)}\n"
                "建议逐一核对上述筛选维度，构建均衡组合。"
            )

        analysis = "\n".join(analysis_parts)

        reply = (
            "选股策略分析已完成。"
            f"当前关注{'、'.join(sectors) if sectors else '全市场'}，"
            f"建议从基本面、技术面、资金面、估值面四个维度进行筛选。"
        )

        return {
            "title": "智能选股分析",
            "subtitle": f"筛选维度：{', '.join(sectors) if sectors else '综合策略'}",
            "metrics": metrics,
            "analysis": analysis,
            "rating": "hold",
            "ratingLabel": "观望",
            "reply": reply,
            "data": {"criteria": criteria, "stock_codes": stock_codes, "search_count": len(results)},
            "attachments": [],
        }

    def _build_industry_report(
        self, params: Dict[str, Any], results: List[Any]
    ) -> Dict[str, Any]:
        """行业深度研究报告"""
        industry_name = params.get("industry_name", "")
        depth = params.get("depth", "standard")

        snippets = [r.snippet for r in results if r.snippet]
        combined_info = "\n".join(snippets[:3])

        metrics = []
        if industry_name:
            metrics.append({"label": "研究行业", "value": industry_name, "cls": ""})
        metrics.append({"label": "研究深度", "value": "深度" if depth == "deep" else "标准", "cls": ""})
        metrics.append({"label": "信息来源", "value": f"{len(results)}条", "cls": ""})

        analysis_parts = [f"**{industry_name}行业深度研究**" if industry_name else "**行业深度研究**"]

        if combined_info:
            analysis_parts.append("**行业动态聚合**")
            for r in results[:3]:
                if r.title and r.snippet:
                    analysis_parts.append(f"• {r.title}：{r.snippet[:100]}...")

        analysis_parts.append(
            "\n**研究框架**\n"
            "1. 行业景气度：跟踪产量、价格、库存等核心指标\n"
            "2. 竞争格局：CR5、市场集中度、进入壁垒\n"
            "3. 政策环境：监管方向、补贴退坡、国产替代政策\n"
            "4. 产业链位置：上游资源、中游制造、下游应用的利润分配\n"
            "5. 估值水平：PE/PB 历史分位、与海外同业对比"
        )

        analysis = "\n".join(analysis_parts)

        reply = (
            f"{industry_name}行业深度研究已完成。" if industry_name else "行业深度研究已完成。"
            "建议关注行业景气度、竞争格局、政策环境、产业链位置与估值水平五个维度。"
        )

        # 根据信息丰富度决定 rating
        rating = "hold"
        rating_label = "中性"
        if len(snippets) >= 3 and any("增长" in s or "上行" in s for s in snippets):
            rating, rating_label = "buy", "积极"
        elif any("下行" in s or "承压" in s for s in snippets):
            rating, rating_label = "sell", "谨慎"

        return {
            "title": f"{industry_name}行业深度研究" if industry_name else "行业深度研究",
            "subtitle": f"{'深度' if depth == 'deep' else '标准'}研究 | {len(results)}条信息源",
            "metrics": metrics,
            "analysis": analysis,
            "rating": rating,
            "ratingLabel": rating_label,
            "reply": reply,
            "data": {"industry_name": industry_name, "depth": depth, "search_count": len(results)},
            "attachments": [],
        }

    def _build_announcement_report(
        self, params: Dict[str, Any], results: List[Any]
    ) -> Dict[str, Any]:
        """公告解读报告"""
        stock_codes = params.get("stock_codes", [])
        ann_type = params.get("announcement_type", "")

        snippets = [r.snippet for r in results if r.snippet]

        metrics = []
        if stock_codes:
            metrics.append({"label": "关注标的", "value": ",".join(stock_codes), "cls": ""})
        if ann_type:
            metrics.append({"label": "公告类型", "value": ann_type, "cls": ""})
        metrics.append({"label": "信息来源", "value": f"{len(results)}条", "cls": ""})

        analysis_parts = ["**公告解读分析**"]

        if snippets:
            analysis_parts.append("**相关信息聚合**")
            for r in results[:3]:
                if r.title and r.snippet:
                    analysis_parts.append(f"• {r.title}：{r.snippet[:100]}...")

        analysis_parts.append(
            "\n**解读要点**\n"
            "1. 业绩类公告：重点关注营收/利润增速是否超预期，毛利率变化趋势\n"
            "2. 增减持公告：关注大股东/管理层增减持比例、价格区间、锁定期\n"
            "3. 并购重组：交易对价、业绩承诺、协同效应、摊薄比例\n"
            "4. 重大合同：订单金额、交付周期、对当年收入贡献比例\n"
            "5. 股权激励：激励目标难度、覆盖范围、行权价格"
        )

        if ann_type:
            type_tips = {
                "业绩预告": "重点关注预告区间中值与一致预期的差异。",
                "增减持": "关注减持方身份、减持方式（集中竞价/大宗交易）。",
                "并购": "关注商誉风险、整合难度、标的资产质量。",
                "股权激励": "关注业绩考核目标是否过于激进或保守。",
                "分红": "关注分红率、股息率、除权除息时间点。",
                "定增": "关注发行价格、认购方、募资用途、对每股收益的摊薄。",
                "重大合同": "关注合同金额占营收比例、履约风险。",
            }
            tip = type_tips.get(ann_type, "")
            if tip:
                analysis_parts.append(f"\n**{ann_type}专项提示**：{tip}")

        analysis = "\n".join(analysis_parts)

        reply = (
            "公告解读分析已完成。"
            f"{'关注' + ','.join(stock_codes) + '的' if stock_codes else ''}"
            f"{ann_type if ann_type else '相关公告'}，"
            "建议重点关注业绩增速、交易对价、订单金额等量化指标。"
        )

        return {
            "title": "公告解读",
            "subtitle": f"{','.join(stock_codes) if stock_codes else '全市场'} | {ann_type if ann_type else '综合'}",
            "metrics": metrics,
            "analysis": analysis,
            "rating": "hold",
            "ratingLabel": "观望",
            "reply": reply,
            "data": {"stock_codes": stock_codes, "announcement_type": ann_type, "search_count": len(results)},
            "attachments": [],
        }

    def _build_earnings_report(
        self, params: Dict[str, Any], results: List[Any]
    ) -> Dict[str, Any]:
        """财报周期复盘报告"""
        stock_codes = params.get("stock_codes", [])
        period = params.get("period", "")

        snippets = [r.snippet for r in results if r.snippet]

        metrics = []
        if stock_codes:
            metrics.append({"label": "关注标的", "value": ",".join(stock_codes), "cls": ""})
        if period:
            metrics.append({"label": "财报周期", "value": period, "cls": ""})
        metrics.append({"label": "信息来源", "value": f"{len(results)}条", "cls": ""})

        analysis_parts = ["**财报周期复盘**"]

        if snippets:
            analysis_parts.append("**业绩信息聚合**")
            for r in results[:3]:
                if r.title and r.snippet:
                    analysis_parts.append(f"• {r.title}：{r.snippet[:100]}...")

        analysis_parts.append(
            "\n**财报分析五维框架**\n"
            "1. 盈利能力：ROE、毛利率、净利率同比变化\n"
            "2. 成长能力：营收增速、净利润增速、扣非增速\n"
            "3. 营运能力：应收账款周转天数、存货周转天数\n"
            "4. 偿债能力：资产负债率、流动比率、有息负债率\n"
            "5. 现金流：经营性现金流净额/净利润、自由现金流"
        )

        analysis_parts.append(
            "\n**环比与同比关注点**\n"
            "• 同比：判断行业周期位置与公司竞争力变化\n"
            "• 环比：判断业绩加速/减速趋势，尤其关注季节性因素\n"
            "• 扣非净利润：排除一次性损益干扰，反映真实经营能力"
        )

        analysis = "\n".join(analysis_parts)

        reply = (
            "财报周期复盘已完成。"
            f"{'关注' + ','.join(stock_codes) + '的' if stock_codes else ''}"
            f"{period if period else '最新财报'}，"
            "建议从盈利能力、成长能力、营运能力、偿债能力、现金流五个维度综合评价。"
        )

        return {
            "title": "财报周期复盘",
            "subtitle": f"{','.join(stock_codes) if stock_codes else '全市场'} | {period if period else '最新财报'}",
            "metrics": metrics,
            "analysis": analysis,
            "rating": "hold",
            "ratingLabel": "观望",
            "reply": reply,
            "data": {"stock_codes": stock_codes, "period": period, "search_count": len(results)},
            "attachments": [],
        }

    def _build_market_l2_report(
        self,
        params: Dict[str, Any],
        results: List[Any],
        l1_result: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """跨市场比较分析报告"""
        focus = params.get("focus", "")
        market = params.get("market", "global")

        snippets = [r.snippet for r in results if r.snippet]

        # 尝试从 L1 结果提取指标
        l1_metrics = l1_result.get("metrics", []) if l1_result else []

        metrics = []
        if l1_metrics:
            for m in l1_metrics[:4]:
                metrics.append({
                    "label": m.get("label", ""),
                    "value": m.get("value", ""),
                    "cls": m.get("cls", ""),
                })
        else:
            metrics = [
                {"label": "上证指数", "value": "数据获取中", "cls": ""},
                {"label": "深证成指", "value": "数据获取中", "cls": ""},
                {"label": "创业板指", "value": "数据获取中", "cls": ""},
            ]

        metrics.append({"label": "关注市场", "value": market, "cls": ""})
        if focus:
            metrics.append({"label": "聚焦方向", "value": focus, "cls": ""})

        analysis_parts = ["**跨市场比较分析**"]

        if snippets:
            analysis_parts.append("**全球市场动态**")
            for r in results[:3]:
                if r.title and r.snippet:
                    analysis_parts.append(f"• {r.title}：{r.snippet[:100]}...")

        analysis_parts.append(
            "\n**跨市场分析框架**\n"
            "1. A股-港股联动：AH溢价率、南向资金流向、同股同权标的表现差异\n"
            "2. A股-美股联动：中概股表现、美联储政策对全球流动性的影响\n"
            "3. 汇率维度：人民币汇率对出口型企业盈利的影响\n"
            "4. 商品维度：原油、铜、黄金等大宗商品对周期股的影响"
        )

        if l1_result and l1_result.get("analysis"):
            analysis_parts.append(f"\n**A股基础面**\n{l1_result['analysis'][:300]}...")

        analysis = "\n".join(analysis_parts)

        reply = (
            "跨市场比较分析已完成。"
            f"当前关注{market}市场"
            f"{f'，聚焦{focus}' if focus else ''}，"
            "建议关注AH溢价、南向资金流向、美联储政策与汇率变化四个联动维度。"
        )

        return {
            "title": "跨市场比较分析",
            "subtitle": f"{market.upper()} | {focus if focus else '综合联动'}",
            "metrics": metrics,
            "analysis": analysis,
            "rating": "hold",
            "ratingLabel": "观望",
            "reply": reply,
            "data": {"market": market, "focus": focus, "search_count": len(results)},
            "attachments": [],
        }

    def _build_market_l3_report(
        self, params: Dict[str, Any], results: List[Any]
    ) -> Dict[str, Any]:
        """长期策略研究报告"""
        focus = params.get("focus", "")
        horizon = params.get("horizon", "12个月")

        snippets = [r.snippet for r in results if r.snippet]

        metrics = [
            {"label": "研究周期", "value": horizon, "cls": ""},
            {"label": "信息来源", "value": f"{len(results)}条", "cls": ""},
        ]
        if focus:
            metrics.append({"label": "聚焦方向", "value": focus, "cls": ""})

        analysis_parts = ["**长期策略研究**"]

        if snippets:
            analysis_parts.append("**宏观与策略信息聚合**")
            for r in results[:3]:
                if r.title and r.snippet:
                    analysis_parts.append(f"• {r.title}：{r.snippet[:100]}...")

        analysis_parts.append(
            "\n**长期策略研究框架**\n"
            "1. 经济周期：当前所处库存周期、信用周期、产能周期位置\n"
            "2. 货币政策：利率方向、流动性松紧、汇率政策\n"
            "3. 财政政策：基建投资力度、减税方向、产业补贴\n"
            "4. 产业趋势：技术迭代、渗透率变化、替代效应\n"
            "5. 估值锚定：历史分位、全球比较、风险溢价"
        )

        analysis_parts.append(
            "\n**配置建议维度**\n"
            "• 权益仓位：基于估值与情绪指标动态调整\n"
            "• 风格配置：成长/价值、大盘/小盘、行业轮动\n"
            "• 行业配置：顺周期/逆周期、内需/外需、传统/新兴\n"
            "• 风险对冲：股债配比、黄金配置、跨境分散"
        )

        analysis = "\n".join(analysis_parts)

        reply = (
            f"长期策略研究（{horizon}）已完成。"
            f"{f'聚焦{focus}方向，' if focus else ''}"
            "建议从经济周期、货币政策、财政政策、产业趋势、估值锚定五个维度构建长期配置框架。"
        )

        return {
            "title": "长期策略研究",
            "subtitle": f"{horizon} | {focus if focus else '综合策略'}",
            "metrics": metrics,
            "analysis": analysis,
            "rating": "hold",
            "ratingLabel": "观望",
            "reply": reply,
            "data": {"horizon": horizon, "focus": focus, "search_count": len(results)},
            "attachments": [],
        }

    def _build_generic_report(
        self, skill_name: str, params: Dict[str, Any], results: List[Any]
    ) -> Dict[str, Any]:
        """通用深度研究报告"""
        desc = self.SKILL_DESCRIPTIONS.get(skill_name, "深度研究")
        snippets = [r.snippet for r in results if r.snippet]

        analysis_parts = [f"**{desc}**"]
        if snippets:
            analysis_parts.append("**相关信息聚合**")
            for r in results[:3]:
                if r.title and r.snippet:
                    analysis_parts.append(f"• {r.title}：{r.snippet[:100]}...")

        analysis = "\n".join(analysis_parts)

        return {
            "title": desc,
            "subtitle": f"基于 {len(results)} 条信息源",
            "metrics": [{"label": "信息来源", "value": f"{len(results)}条", "cls": ""}],
            "analysis": analysis,
            "rating": "hold",
            "ratingLabel": "观望",
            "reply": f"{desc}已完成，基于{len(results)}条信息源生成分析报告。",
            "data": {"skill_name": skill_name, "params": params, "search_count": len(results)},
            "attachments": [],
        }

    def _build_fallback_result(self, skill_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """完全失败时的降级结果"""
        desc = self.SKILL_DESCRIPTIONS.get(skill_name, "深度研究")
        return {
            "title": desc,
            "subtitle": "分析服务暂时不可用",
            "metrics": [{"label": "状态", "value": "服务降级", "cls": ""}],
            "analysis": (
                f"**{desc}服务暂时不可用**\n"
                "• 可能原因：网络受限、搜索服务未配置、或分析引擎异常\n"
                "• 建议稍后重试，或先使用轻量分析功能\n"
                "• 如需启用实时搜索，请配置 SERPAPI_API_KEY 或 BING_SEARCH_API_KEY"
            ),
            "rating": "hold",
            "ratingLabel": "观望",
            "reply": f"{desc}服务暂时不可用，建议稍后重试或先使用轻量分析功能。",
            "data": {"skill_name": skill_name, "params": params, "status": "fallback"},
            "attachments": [],
        }

    # === 工具方法 ===

    def _build_search_query(self, skill_name: str, params: Dict[str, Any]) -> str:
        """根据 Skill 和参数构建搜索关键词"""
        if skill_name == "stock_screening":
            criteria = params.get("criteria", {})
            sectors = criteria.get("sectors", [])
            query = "A股选股策略"
            if sectors:
                query = f"{' '.join(sectors)} 股票 选股"
            return query
        elif skill_name == "industry_analysis":
            industry = params.get("industry_name", "")
            return f"{industry}行业分析 趋势" if industry else "行业深度研究"
        elif skill_name == "announcement_analysis":
            codes = params.get("stock_codes", [])
            ann_type = params.get("announcement_type", "")
            base = "上市公司公告解读"
            if codes:
                base = f"{' '.join(codes)} 公告"
            if ann_type:
                base += f" {ann_type}"
            return base
        elif skill_name == "earnings_review":
            codes = params.get("stock_codes", [])
            period = params.get("period", "")
            base = "财报分析 业绩"
            if codes:
                base = f"{' '.join(codes)} 财报"
            if period:
                base += f" {period}"
            return base
        elif skill_name == "market_review_l2":
            focus = params.get("focus", "")
            return f"A股 港股 美股 联动分析 {focus}".strip()
        elif skill_name == "market_review_l3":
            focus = params.get("focus", "")
            return f"宏观经济 策略研究 {focus}".strip()
        else:
            return params.get("query", "")

    def _dedupe_results(self, results: List[Any]) -> List[Any]:
        """去重搜索结果"""
        seen = set()
        unique = []
        for r in results:
            key = r.title + r.url
            if key not in seen:
                seen.add(key)
                unique.append(r)
        return unique

    async def get_task_status(self, task_id: str) -> Dict[str, Any]:
        """查询委托任务状态（同步执行，立即返回 completed）"""
        return {"task_id": task_id, "status": "completed", "progress": 100}


# 全局单例
delegation_service = AgentDelegationService()
