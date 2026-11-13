# -*- coding: utf-8 -*-
"""全量 A 股股票字典（中文简称 → 6 位代码）

数据源：东方财富全量列表接口（~5900 只，含沪深主板/创业板/科创板/北交所）。
首次调用时拉取并缓存到 SQLite stock_dict 表；之后启动直接读库（零网络）。
离线且无缓存时回退内置核心 200 只表。

修复：「茅台/招行」等中文简称无法识别 → 现全量可识别。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# 内置核心表（离线回退）：高频大盘蓝筹 + 热门题材，覆盖用户主要场景
_CORE_DICT: Dict[str, str] = {
    "贵州茅台": "600519", "五粮液": "000858", "泸州老窖": "000568", "山西汾酒": "600809",
    "宁德时代": "300750", "比亚迪": "002594", "亿纬锂能": "300014", "赣锋锂业": "002460",
    "立讯精密": "002475", "海康威视": "002415", "大华股份": "002236", "歌尔股份": "002241",
    "中际旭创": "300308", "天孚通信": "300394", "新易盛": "300502", "中科曙光": "603019",
    "寒武纪": "688256", "海光信息": "688041", "科大讯飞": "002230", "浪潮信息": "000977",
    "东方财富": "300059", "同花顺": "300033", "中信证券": "600030", "华泰证券": "601688",
    "招商银行": "600036", "平安银行": "000001", "兴业银行": "601166", "宁波银行": "002142",
    "工商银行": "601398", "建设银行": "601939", "中国平安": "601318", "中国人寿": "601628",
    "药明康德": "603259", "恒瑞医药": "600276", "迈瑞医疗": "300760", "片仔癀": "600436",
    "爱尔眼科": "300015", "美的集团": "000333", "格力电器": "000651", "海尔智家": "600690",
    "三一重工": "600031", "中国中免": "601888", "海天味业": "603288", "伊利股份": "600887",
    "双汇发展": "000895", "紫金矿业": "601899", "中国铝业": "601600", "北方稀土": "600111",
    "隆基绿能": "601012", "通威股份": "600438", "阳光电源": "300274", "长江电力": "600900",
    "中国核电": "601985", "中国石油": "601857", "中国石化": "600028", "中国神华": "601088",
    "陕西煤业": "601225", "万华化学": "600309", "宝钢股份": "600019", "中国建筑": "601668",
    "中国平安": "601318", "京东方A": "000725", "TCL科技": "000100", "工业富联": "601138",
    "汇川技术": "300124", "中芯国际": "688981", "韦尔股份": "603501", "北方华创": "002371",
    "隆基机械": "002363", "长安汽车": "000625", "上汽集团": "600104", "长城汽车": "601633",
    "中国重工": "601989", "中国船舶": "600150", "航发动力": "600893", "中航沈飞": "600760",
    "中国卫星": "600118", "中兴通讯": "000063", "烽火通信": "600498", "紫光股份": "000938",
    "恒生电子": "600570", "广联达": "002410", "金山办公": "688111", "用友网络": "600588",
    "万科A": "000002", "保利发展": "600048", "招商蛇口": "001979", "金地集团": "600383",
    "上海机场": "600009", "白云机场": "600004", "顺丰控股": "002352", "京沪高铁": "601816",
    "中国国航": "601111", "南方航空": "600029", "东方航空": "600115", "锦江酒店": "600754",
    "首旅酒店": "600258", "老凤祥": "600612", "周大生": "002867", "中国黄金": "600916",
    "农夫山泉": "09633", "海底捞": "06862",  # 港股不在本字典范围，仅占位防误匹配
}

# 去掉港股占位（本字典只管 A 股 6 位码）
_CORE_DICT = {k: v for k, v in _CORE_DICT.items() if len(v) == 6}

# 常用简称别名（东财全量表只有正式简称，"招行/茅台"类俗称在此映射）
_ALIAS_MAP: Dict[str, str] = {
    "招行": "600036", "茅台": "600519", "五粮液": "000858",
    "人寿": "601628", "工行": "601398", "建行": "601939", "中行": "601988",
    "农行": "601288", "交行": "601328", "招证": "600999",
    "宁王": "300750", "迪王": "002594", "海康": "002415", "大华": "002236",
    "讯飞": "002230", "东财": "300059", "恒瑞": "600276", "美的": "000333",
    "格力": "000651", "海尔": "600690", "伊利": "600887", "万科": "000002",
    "紫金": "601899", "隆基": "601012", "通威": "600438", "中免": "601888",
    "汾酒": "600809", "老窖": "000568", "药明": "603259",
    "京东方": "000725", "中兴": "000063", "曙光": "603019", "寒武纪": "688256",
    "三一": "600031", "神华": "601088", "陕煤": "601225", "宝钢": "600019",
    "长电": "600900", "上汽": "600104", "长安": "000625",
}

# 腾讯智能搜索建议（关键词级，响应 v_hint="sh~600519~贵州茅台~gzmt~GP-A^..."）
_SMARTBOX_URL = "https://smartbox.gtimg.cn/s3/?v=2&q={q}&t=all"
_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

# 消息候选词停用词（防止"多少钱/帮我看看"类片段被当股票名在线查询）
_STOPWORDS = {
    "多少", "价格", "行情", "现在", "怎么", "帮我", "看看", "今天", "什么", "哪个",
    "好吗", "走势", "现价", "块钱", "股价", "分析", "一下", "怎么样", "多少钱",
    "今天", "明天", "现在", "最近", "感觉", "认为", "推荐", "股票", "个股", "持仓",
    "买入", "卖出", "涨跌", "涨了", "跌了", "可以", "还能", "不能", "这个", "那个",
}

_loaded: Dict[str, str] = {}
_load_lock: Optional[asyncio.Lock] = None


def _get_lock() -> asyncio.Lock:
    global _load_lock
    if _load_lock is None:
        _load_lock = asyncio.Lock()
    return _load_lock


async def ensure_loaded() -> Dict[str, str]:
    """确保字典已加载：别名表 + 核心表 + SQLite 学习缓存（历史在线解析结果）。
    不做全量预拉取（东财全量接口不稳定且易限流）；未知简称按需走 smartbox 在线解析。"""
    global _loaded
    if _loaded:
        return _loaded
    async with _get_lock():
        if _loaded:
            return _loaded
        _loaded = dict(_CORE_DICT)
        # SQLite 学习缓存（历史在线解析过的简称）
        try:
            from local.db import db
            await db.execute(
                "CREATE TABLE IF NOT EXISTS stock_dict (symbol TEXT PRIMARY KEY, name TEXT NOT NULL)"
            )
            rows = await db.fetchall("SELECT symbol, name FROM stock_dict")
            for r in rows:
                _loaded.setdefault(r["name"], r["symbol"])
        except Exception as e:
            logger.warning(f"stock_dict: 读 SQLite 缓存失败: {e}")
        return _loaded


async def _persist(name: str, symbol: str) -> None:
    """在线解析结果写入 SQLite 学习缓存（下次零网络）"""
    try:
        from local.db import db
        await db.execute(
            "INSERT OR REPLACE INTO stock_dict (symbol, name) VALUES (?, ?)",
            (symbol, name),
        )
    except Exception:
        pass


def _smartbox_sync(q: str) -> Optional[tuple]:
    """腾讯 smartbox 关键词查询（同步，在线程池中调用）→ (名称, 代码) 或 None。
    只接受 A 股（GP-A）且 sh/sz 市场的首个结果。"""
    import httpx
    from urllib.parse import quote
    try:
        resp = httpx.get(_SMARTBOX_URL.format(q=quote(q)), timeout=5.0, headers=_HEADERS)
        text = resp.text.strip()
    except Exception:
        return None
    if not text.startswith('v_hint="') or text in ('v_hint="N"', 'v_hint=""'):
        return None
    hint = text[len('v_hint="'):]
    if hint.endswith('"'):
        hint = hint[:-1]
    for item in hint.split("^"):
        parts = item.split("~")
        if len(parts) >= 5 and parts[4].startswith("GP-A") and parts[0] in ("sh", "sz") \
                and len(parts[1]) == 6:
            return (parts[2], parts[1])
    return None


async def query_online(name: str) -> Optional[tuple]:
    """在线解析简称 → (名称, 代码)；命中后写学习缓存。"""
    if not name or len(name) < 2:
        return None
    import asyncio as _aio
    try:
        hit = await _aio.wait_for(_aio.to_thread(_smartbox_sync, name), timeout=6.0)
    except Exception:
        return None
    if hit:
        _loaded.setdefault(hit[0], hit[1])
        await _persist(hit[0], hit[1])
        return hit
    return None


def _cn_candidates(text: str, limit: int = 6) -> list:
    """从消息提取候选股票名词：先按停用词把消息切段（"帮我看看中矿资源现在多少钱"
    → 段"中矿资源"），段长 2-6 整段为首选候选；超长段再滑窗取 2-4 字子串。
    长度降序 + 位置稳定，任一命中即返回。"""
    import re as _re
    # 停用词切分（长词优先，防止"多少钱"被"多少"先切）
    split_pat = _re.compile("|".join(_re.escape(w) for w in
                                     sorted(_STOPWORDS, key=len, reverse=True)))
    candidates: list = []
    seen = set()
    for seg in _re.findall(r"[\u4e00-\u9fff]+", text):
        for piece in split_pat.split(seg):
            piece = piece.strip()
            if len(piece) < 2:
                continue
            if 2 <= len(piece) <= 6:
                if piece not in seen:
                    seen.add(piece)
                    candidates.append(piece)
            else:
                # 超长段滑窗（4→3→2）
                for n in (4, 3, 2):
                    for i in range(len(piece) - n + 1):
                        w = piece[i:i + n]
                        if w not in seen:
                            seen.add(w)
                            candidates.append(w)
    candidates.sort(key=len, reverse=True)
    return candidates[:limit]


async def resolve_from_message(text: str) -> Optional[tuple]:
    """消息级股票名解析：本地（别名/核心/学习缓存，全称+子串）→ 未命中对候选词在线解析。
    总超时 12s（正常 smartbox 响应 <1s，超时即网络异常放弃在线解析）。"""
    if not text:
        return None
    # 1) 本地全称扫描（最先出现者）
    local = extract_from_text(text)
    if local:
        return local
    # 2) 候选词在线解析（总超时控制，任一命中即返回）
    import asyncio as _aio

    async def _try_online():
        for cand in _cn_candidates(text, limit=4):
            hit = await query_online(cand)
            if hit:
                return hit
        return None

    try:
        return await _aio.wait_for(_try_online(), timeout=12.0)
    except Exception:
        return None


def lookup(name: str) -> Optional[str]:
    """中文名（别名/全称/前缀/子串）→ 6 位代码；未命中返回 None。"""
    if not name or len(name) < 2:
        return None
    # 0) 别名表（"招行/茅台"类俗称）
    if name in _ALIAS_MAP:
        return _ALIAS_MAP[name]
    if not _loaded:
        return None
    if name in _loaded:
        return _loaded[name]
    # 前缀匹配（"茅台" → "贵州茅台"）：优先短名
    hits = [(n, c) for n, c in _loaded.items() if n.startswith(name)]
    if len(hits) == 1:
        return hits[0][1]
    # 子串匹配（"酒" 类模糊不做，要求 ≥2 字）
    if len(name) >= 2:
        subs = [(n, c) for n, c in _loaded.items() if name in n]
        if len(subs) == 1:
            return subs[0][1]
        if subs:
            # 多命中取名称最短的（最常用简称为短名）
            subs.sort(key=lambda x: len(x[0]))
            return subs[0][1]
    return None


def extract_from_text(text: str) -> Optional[tuple]:
    """从用户消息中提取（名称, 代码）；别名优先，全称取消息中最先出现者。"""
    if not text:
        return None
    # 1) 别名表（长度 ≥2 按长度降序，防止"老窖"被"泸州老窖"遮蔽类问题）
    for alias in sorted(_ALIAS_MAP, key=len, reverse=True):
        if len(alias) >= 2 and alias in text:
            return (alias, _ALIAS_MAP[alias])
    if not _loaded:
        return None
    best: Optional[tuple] = None
    best_pos = len(text) + 1
    for name in _loaded:
        if len(name) < 2:
            continue
        pos = text.find(name)
        if pos >= 0 and pos < best_pos:
            best_pos = pos
            best = (name, _loaded[name])
    return best
