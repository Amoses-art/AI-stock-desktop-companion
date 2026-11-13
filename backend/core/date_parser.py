"""
日期解析模块 — 同步执行

职责：将用户输入中的相对/绝对日期描述解析为标准化 ISO 8601 日期字符串。
支持中文日期表达、交易日映射。

接口契约：
- 同步方法（sync），不抛异常，解析失败返回 None
- 所有相对日期以 reference_date（默认今天）为基准
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional

try:
    import chinese_calendar as cc
    _CC_AVAILABLE = True
except Exception:
    _CC_AVAILABLE = False

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ParsedDate:
    """解析后的日期结果"""

    iso_date: str          # YYYY-MM-DD
    original_text: str     # 原始日期描述
    is_trading_day: bool   # 是否为交易日
    trading_day_hint: Optional[str] = None  # 交易日调整提示


class DateParser:
    """日期解析器 — 同步

    支持格式：
    - 相对日期：今天、昨天、前天、本周、上周、近N天、N天前
    - 绝对日期：YYYY-MM-DD、MM-DD、YYYY年MM月DD日、M月D日
    - 交易日：T-1、T-2、T+1（自动映射到最近交易日）
    - 特殊：最近一周、最近一个月、今年

    接口契约：
    - parse() 为同步方法，失败返回 None
    - is_trading_day() 为同步方法，当前简化实现（周末判断）
    """

    def __init__(self) -> None:
        self._today_cache: Optional[date] = None

    def parse(
        self,
        text: str,
        reference_date: Optional[date] = None,
    ) -> Optional[ParsedDate]:
        """解析文本中的日期描述，返回标准化结果。同步、不抛异常。"""
        try:
            ref = reference_date or date.today()
            self._today_cache = ref
            return self._do_parse(text, ref)
        except Exception:
            return None

    def _do_parse(self, text: str, ref: date) -> Optional[ParsedDate]:
        stripped = text.strip()

        # 1. 交易日表达式 T-1 / T-2 / T+1
        result = self._parse_trading_day(stripped, ref)
        if result:
            return result

        # 2. 相对日期
        result = self._parse_relative(stripped, ref)
        if result:
            return result

        # 3. 绝对日期
        result = self._parse_absolute(stripped, ref)
        if result:
            return result

        return None

    def _parse_trading_day(self, text: str, ref: date) -> Optional[ParsedDate]:
        """解析交易日表达式：T-1, T-2, T+1"""
        match = re.match(r"^[Tt]([+-]?\d+)$", text)
        if not match:
            return None

        offset = int(match.group(1))
        target = ref + timedelta(days=offset)
        target = self._nearest_trading_day(target, direction="backward" if offset <= 0 else "forward")

        is_td = self.is_trading_day(target)
        hint = None
        if target != ref + timedelta(days=offset):
            hint = f"已自动映射到最近交易日"

        return ParsedDate(
            iso_date=target.isoformat(),
            original_text=text,
            is_trading_day=is_td,
            trading_day_hint=hint,
        )

    def _parse_relative(self, text: str, ref: date) -> Optional[ParsedDate]:
        """解析相对日期表达"""
        mapping = {
            "今天": 0,
            "今": 0,
            "昨天": -1,
            "昨": -1,
            "前天": -2,
            "大前天": -3,
        }

        if text in mapping:
            delta = mapping[text]
            target = ref + timedelta(days=delta)
            return ParsedDate(
                iso_date=target.isoformat(),
                original_text=text,
                is_trading_day=self.is_trading_day(target),
            )

        # 近N天 / N天前
        match = re.match(r"^(?:近|最近)?(\d+)\s*天(?:前|内)?$", text)
        if match:
            n = int(match.group(1))
            target = ref - timedelta(days=n - 1)  # "近3天" = 今天+昨天+前天
            return ParsedDate(
                iso_date=target.isoformat(),
                original_text=text,
                is_trading_day=self.is_trading_day(target),
            )

        # 本周 / 上周
        if text in ("本周", "这週", "这周"):
            # 本周一
            monday = ref - timedelta(days=ref.weekday())
            return ParsedDate(
                iso_date=monday.isoformat(),
                original_text=text,
                is_trading_day=self.is_trading_day(monday),
            )
        if text == "上周":
            monday = ref - timedelta(days=ref.weekday() + 7)
            return ParsedDate(
                iso_date=monday.isoformat(),
                original_text=text,
                is_trading_day=self.is_trading_day(monday),
            )

        # 最近一周
        if text in ("最近一周", "近一周", "这一週", "这一周"):
            target = ref - timedelta(days=6)
            return ParsedDate(
                iso_date=target.isoformat(),
                original_text=text,
                is_trading_day=self.is_trading_day(target),
            )

        # 最近一个月
        if text in ("最近一个月", "近一个月", "本月"):
            target = ref - timedelta(days=29)
            return ParsedDate(
                iso_date=target.isoformat(),
                original_text=text,
                is_trading_day=self.is_trading_day(target),
            )

        # 今年
        if text == "今年":
            target = date(ref.year, 1, 1)
            return ParsedDate(
                iso_date=target.isoformat(),
                original_text=text,
                is_trading_day=self.is_trading_day(target),
            )

        return None

    def _parse_absolute(self, text: str, ref: date) -> Optional[ParsedDate]:
        """解析绝对日期表达"""
        # YYYY-MM-DD
        match = re.match(r"^(\d{4})[-/](\d{1,2})[-/](\d{1,2})$", text)
        if match:
            y, m, d = int(match.group(1)), int(match.group(2)), int(match.group(3))
            try:
                target = date(y, m, d)
                return ParsedDate(
                    iso_date=target.isoformat(),
                    original_text=text,
                    is_trading_day=self.is_trading_day(target),
                )
            except ValueError:
                return None

        # MM-DD（默认今年）
        match = re.match(r"^(\d{1,2})[-/](\d{1,2})$", text)
        if match:
            m, d = int(match.group(1)), int(match.group(2))
            try:
                target = date(ref.year, m, d)
                return ParsedDate(
                    iso_date=target.isoformat(),
                    original_text=text,
                    is_trading_day=self.is_trading_day(target),
                )
            except ValueError:
                return None

        # YYYY年MM月DD日
        match = re.match(r"^(\d{4})年(\d{1,2})月(\d{1,2})日$", text)
        if match:
            y, m, d = int(match.group(1)), int(match.group(2)), int(match.group(3))
            try:
                target = date(y, m, d)
                return ParsedDate(
                    iso_date=target.isoformat(),
                    original_text=text,
                    is_trading_day=self.is_trading_day(target),
                )
            except ValueError:
                return None

        # M月D日（默认今年）
        match = re.match(r"^(\d{1,2})月(\d{1,2})日$", text)
        if match:
            m, d = int(match.group(1)), int(match.group(2))
            try:
                target = date(ref.year, m, d)
                return ParsedDate(
                    iso_date=target.isoformat(),
                    original_text=text,
                    is_trading_day=self.is_trading_day(target),
                )
            except ValueError:
                return None

        return None

    def is_trading_day(self, dt: date) -> bool:
        """判断是否为交易日。优先使用 chinesecalendar 判断节假日/调休，
        库不可用时回退到仅判断周末。
        """
        # 基础判断：周末不是交易日
        if dt.weekday() >= 5:
            return False

        # 接入中国法定节假日（含调休补班）
        if _CC_AVAILABLE:
            try:
                # chinesecalendar.is_holiday 返回 True 表示休息日（含调休假日）
                # is_workday 返回 True 表示工作日（含调休补班日）
                return cc.is_workday(dt)
            except Exception as e:
                logger.debug("chinesecalendar 判断失败: %s", e)

        # 降级：仅判断周末
        return True

    def _nearest_trading_day(self, dt: date, direction: str = "backward") -> date:
        """获取最近的交易日。direction: backward/forward。"""
        if self.is_trading_day(dt):
            return dt
        step = -1 if direction == "backward" else 1
        current = dt + timedelta(days=step)
        # 最多查 10 天，防止无限循环
        for _ in range(10):
            if self.is_trading_day(current):
                return current
            current += timedelta(days=step)
        return dt  # fallback

    def extract_date_from_text(self, text: str, ref: Optional[date] = None) -> Optional[ParsedDate]:
        """从长文本中提取日期子串并解析（优先匹配最具体的日期表达）"""
        ref = ref or date.today()

        # 按优先级尝试各种模式
        patterns = [
            (r"(\d{4}年\d{1,2}月\d{1,2}日)", lambda m: m.group(1)),
            (r"(\d{4}[-/]\d{1,2}[-/]\d{1,2})", lambda m: m.group(1)),
            (r"(\d{1,2}月\d{1,2}日)", lambda m: m.group(1)),
            (r"(\d{1,2}[-/]\d{1,2})", lambda m: m.group(1)),
            (r"(今天|昨天|前天|大前天)", lambda m: m.group(1)),
            (r"(T[+-]?\d+)", lambda m: m.group(1)),
            (r"(本周|上周|最近一周|近一周)", lambda m: m.group(1)),
            (r"(最近\d+天|近\d+天)", lambda m: m.group(1)),
            (r"(最近一个月|近一个月|本月)", lambda m: m.group(1)),
            (r"(今年)", lambda m: m.group(1)),
        ]

        for pat, extractor in patterns:
            match = re.search(pat, text)
            if match:
                date_text = extractor(match)
                result = self.parse(date_text, ref)
                if result:
                    return result
        return None
