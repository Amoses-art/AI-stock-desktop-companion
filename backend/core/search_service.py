"""
搜索服务封装层 — 统一入口，支持多搜索后端

架构决策(ADR-023 评估项 #3):
- Python 后端无法直接调用 aily web_search，需接入第三方搜索 API
- 支持 SerpAPI / Bing Search API，优先级 fallback
- 未配置 API Key 时保持 Mock 降级行为
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import httpx


@dataclass
class SearchResult:
    """搜索结果"""
    title: str = ""
    url: str = ""
    snippet: str = ""
    source: str = ""


class SearchService:
    """搜索服务 — 统一封装层

    支持后端:
    1. SerpAPI (Google Search)
    2. Bing Search API
    3. Mock 降级（沙箱/无网络环境）

    API Key 优先级:
    1. 环境变量 SERPAPI_API_KEY / BING_SEARCH_API_KEY
    2. configure() 显式调用
    3. 无 Key 时走 Mock 降级
    """

    # 预置的财经/行业 Mock 搜索语料池（沙箱环境无网络时提供结构化信息）
    MOCK_CORPUS: Dict[str, List[SearchResult]] = {
        "半导体": [
            SearchResult(
                title="半导体行业深度报告：国产替代进入加速期",
                url="https://mock.example.com/semiconductor-report",
                snippet="2026年半导体设备国产化率预计突破35%，晶圆厂扩产带动上游材料需求，"
                        "先进封装成为新增长极。建议关注设备、材料、封测三大主线。",
                source="mock",
            ),
            SearchResult(
                title="中微公司：刻蚀设备龙头，业绩持续高增",
                url="https://mock.example.com/amc",
                snippet="中微公司2026年Q2营收同比+45%，新签订单饱满，"
                        "5nm以下刻蚀设备进入验证阶段，国产替代逻辑清晰。",
                source="mock",
            ),
        ],
        "新能源": [
            SearchResult(
                title="新能源产业链跟踪：光伏装机超预期",
                url="https://mock.example.com/new-energy",
                snippet="2026年上半年光伏新增装机同比+38%，组件价格触底回升，"
                        "储能配套政策密集出台，产业链景气度持续上行。",
                source="mock",
            ),
            SearchResult(
                title="锂电池：产能出清接近尾声，龙头盈利修复",
                url="https://mock.example.com/lithium",
                snippet="电池级碳酸锂价格稳定在8万元/吨，下游需求回暖，"
                        "头部电池厂开工率回升至75%以上，单位盈利有望修复。",
                source="mock",
            ),
        ],
        "白酒": [
            SearchResult(
                title="白酒行业：中秋旺季动销跟踪",
                url="https://mock.example.com/baijiu",
                snippet="中秋备货启动，高端白酒批价企稳，茅台1935放量增长，"
                        "区域酒企分化加剧，建议关注头部品牌确定性。",
                source="mock",
            ),
        ],
        "医药": [
            SearchResult(
                title="创新药：医保谈判规则优化，支付环境改善",
                url="https://mock.example.com/pharma",
                snippet="2026年医保谈判续约规则明确，创新药支付天花板提升，"
                        "ADC、CAR-T等前沿疗法纳入速度加快，行业迎来拐点。",
                source="mock",
            ),
        ],
        "人工智能": [
            SearchResult(
                title="AI算力：国产芯片迭代加速",
                url="https://mock.example.com/ai",
                snippet="国内大模型训练需求爆发，算力芯片国产化率提升，"
                        "寒武纪、海光信息等产品迭代加速，生态建设成关键。",
                source="mock",
            ),
        ],
        "选股": [
            SearchResult(
                title="量化选股策略：低估值+高成长组合",
                url="https://mock.example.com/stock-screening",
                snippet="当前市场环境下，低估值（PE<20）+高成长（营收增速>20%）"
                        "策略超额收益显著，科技制造与消费复苏为两大主线。",
                source="mock",
            ),
            SearchResult(
                title="A股半年报前瞻：业绩超预期方向",
                url="https://mock.example.com/earnings",
                snippet="半导体设备、新能源车零部件、创新药等方向业绩超预期概率较高，"
                        "传统周期品受制于价格下行，业绩承压。",
                source="mock",
            ),
        ],
        "公告": [
            SearchResult(
                title="上市公司公告解读要点：如何识别关键信息",
                url="https://mock.example.com/announcement",
                snippet="公告类型优先级：业绩预告>重大合同>并购重组>增减持>分红。"
                        "重点关注业绩指引、订单金额、交易对价等量化指标。",
                source="mock",
            ),
        ],
        "财报": [
            SearchResult(
                title="财报分析框架：五维评价体系",
                url="https://mock.example.com/earnings-review",
                snippet="盈利能力（ROE/毛利率）、成长能力（营收/利润增速）、"
                        "营运能力（周转率）、偿债能力（资产负债率）、现金流质量。",
                source="mock",
            ),
            SearchResult(
                title="A股2026年中报：整体业绩增速放缓",
                url="https://mock.example.com/mid-report",
                snippet="全部A股2026H1净利润同比+3.2%，较Q1放缓1.8pct，"
                        "上游资源品业绩下滑，中下游制造业盈利改善。",
                source="mock",
            ),
        ],
        "大盘": [
            SearchResult(
                title="A股市场策略：震荡中寻找结构性机会",
                url="https://mock.example.com/market-strategy",
                snippet="当前市场处于估值修复期，指数区间震荡，"
                        "建议关注高股息防御板块与科技成长赛道的轮动节奏。",
                source="mock",
            ),
            SearchResult(
                title="跨市场比较：A股估值处于全球洼地",
                url="https://mock.example.com/cross-market",
                snippet="沪深300 PE(TTM)约11.5倍，低于标普500的22倍和日经225的18倍，"
                        "北向资金连续净流入，外资配置意愿回升。",
                source="mock",
            ),
        ],
    }

    def __init__(self) -> None:
        self._backend: Optional[str] = None
        self._config: Dict[str, Any] = {}
        self._httpx_client: Optional[httpx.AsyncClient] = None
        self._load_from_env()

    def _load_from_env(self) -> None:
        """从环境变量加载 API Key"""
        serpapi_key = os.environ.get("SERPAPI_API_KEY")
        bing_key = os.environ.get("BING_SEARCH_API_KEY")
        if serpapi_key:
            self.configure("serpapi", serpapi_key)
        elif bing_key:
            self.configure("bing", bing_key)

    def configure(self, backend: str, api_key: str, **kwargs: Any) -> None:
        """配置搜索后端"""
        self._backend = backend
        self._config = {"api_key": api_key, **kwargs}

    def _get_client(self) -> httpx.AsyncClient:
        if self._httpx_client is None or self._httpx_client.is_closed:
            self._httpx_client = httpx.AsyncClient(timeout=15.0)
        return self._httpx_client

    async def search(self, query: str, limit: int = 5) -> List[SearchResult]:
        """执行通用搜索

        Args:
            query: 搜索关键词
            limit: 返回结果数量上限

        Returns:
            搜索结果列表（永不抛异常，降级时返回 Mock 数据）
        """
        if not self._backend or not self._config.get("api_key"):
            return self._mock_search(query, limit)

        try:
            if self._backend == "serpapi":
                return await self._search_serpapi(query, limit)
            elif self._backend == "bing":
                return await self._search_bing(query, limit)
            else:
                return self._mock_search(query, limit)
        except Exception:
            # 任何异常都降级到 Mock
            return self._mock_search(query, limit)

    async def search_news(self, query: str, limit: int = 5) -> List[SearchResult]:
        """搜索新闻"""
        if not self._backend or not self._config.get("api_key"):
            return self._mock_search(f"{query} 新闻", limit)

        try:
            if self._backend == "serpapi":
                return await self._search_serpapi(query, limit, engine="google_news")
            elif self._backend == "bing":
                return await self._search_bing(query, limit, news_only=True)
            else:
                return self._mock_search(f"{query} 新闻", limit)
        except Exception:
            return self._mock_search(f"{query} 新闻", limit)

    async def search_finance(self, query: str, limit: int = 5) -> List[SearchResult]:
        """搜索财经信息"""
        finance_query = f"{query} 财经 股票 分析"
        if not self._backend or not self._config.get("api_key"):
            return self._mock_search(finance_query, limit)

        try:
            if self._backend == "serpapi":
                return await self._search_serpapi(finance_query, limit)
            elif self._backend == "bing":
                return await self._search_bing(finance_query, limit)
            else:
                return self._mock_search(finance_query, limit)
        except Exception:
            return self._mock_search(finance_query, limit)

    async def _search_serpapi(
        self, query: str, limit: int = 5, engine: str = "google"
    ) -> List[SearchResult]:
        """调用 SerpAPI"""
        api_key = self._config.get("api_key")
        params = {
            "engine": engine,
            "q": query,
            "api_key": api_key,
            "num": limit,
        }
        client = self._get_client()
        resp = await client.get("https://serpapi.com/search", params=params)
        resp.raise_for_status()
        data = resp.json()

        results: List[SearchResult] = []
        if engine == "google_news":
            items = data.get("news_results", [])
        else:
            items = data.get("organic_results", [])

        for r in items[:limit]:
            results.append(
                SearchResult(
                    title=r.get("title", ""),
                    url=r.get("link", r.get("url", "")),
                    snippet=r.get("snippet", r.get("description", "")),
                    source="serpapi",
                )
            )
        return results

    async def _search_bing(
        self, query: str, limit: int = 5, news_only: bool = False
    ) -> List[SearchResult]:
        """调用 Bing Search API"""
        api_key = self._config.get("api_key")
        headers = {"Ocp-Apim-Subscription-Key": api_key}
        params: Dict[str, Any] = {"q": query, "count": limit}
        if news_only:
            endpoint = "https://api.bing.microsoft.com/v7.0/news/search"
        else:
            endpoint = "https://api.bing.microsoft.com/v7.0/search"

        client = self._get_client()
        resp = await client.get(endpoint, headers=headers, params=params)
        resp.raise_for_status()
        data = resp.json()

        results: List[SearchResult] = []
        if news_only:
            items = data.get("value", [])
            for r in items[:limit]:
                results.append(
                    SearchResult(
                        title=r.get("name", ""),
                        url=r.get("url", ""),
                        snippet=r.get("description", ""),
                        source="bing",
                    )
                )
        else:
            items = data.get("webPages", {}).get("value", [])
            for r in items[:limit]:
                results.append(
                    SearchResult(
                        title=r.get("name", ""),
                        url=r.get("url", ""),
                        snippet=r.get("snippet", ""),
                        source="bing",
                    )
                )
        return results

    def _mock_search(self, query: str, limit: int = 5) -> List[SearchResult]:
        """Mock 搜索 — 基于关键词匹配预置语料池

        沙箱环境/无 API Key 时提供结构化信息，
        确保深度研究 Skill 仍能获得可分析的内容。
        """
        lowered = query.lower()
        matched: List[SearchResult] = []

        # 按关键词匹配语料池
        for keyword, corpus in self.MOCK_CORPUS.items():
            if keyword in lowered or any(kw in lowered for kw in keyword):
                matched.extend(corpus)

        # 去重并限制数量
        seen = set()
        unique: List[SearchResult] = []
        for r in matched:
            key = r.title + r.url
            if key not in seen:
                seen.add(key)
                unique.append(r)

        if unique:
            return unique[:limit]

        # 无匹配时返回通用 Mock 结果
        return [
            SearchResult(
                title="实时搜索服务未配置",
                url="",
                snippet=(
                    f"当前未配置搜索 API Key，无法获取'{query}'的实时网络信息。"
                    "以下为基于历史模式的推演提示："
                    "建议结合实时行情数据、公司基本面与行业趋势进行综合判断。"
                    "如需启用实时搜索，请配置 SERPAPI_API_KEY 或 BING_SEARCH_API_KEY 环境变量。"
                ),
                source="mock",
            )
        ]

    async def close(self) -> None:
        """关闭 HTTP 客户端"""
        if self._httpx_client and not self._httpx_client.is_closed:
            await self._httpx_client.aclose()


# 全局单例
search_service = SearchService()
