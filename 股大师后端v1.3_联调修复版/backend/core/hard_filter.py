"""
硬规则过滤层 (Layer 1) — 同步执行

职责：在 NLU 解析前拦截明显无效/恶意的输入，减少后续计算浪费。
所有规则均为同步操作（正则、长度检查、字典查找），不涉及 IO。
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import List, Optional, Set


@dataclass(frozen=True)
class HardFilterResult:
    """硬过滤结果"""

    passed: bool
    block_reason: Optional[str] = None
    response_message: Optional[str] = None


class HardFilter:
    """L1 硬规则过滤器 — 同步

    6 项过滤规则：
    1. 空输入 / 纯空白
    2. 输入过长 (>500 字符)
    3. 敏感词过滤
    4. 重复刷屏检测（同文本高频重复）
    5. 无意义字符（纯符号 / 纯数字无上下文）
    6. 编码异常（非法 UTF-8 序列 / 控制字符）

    接口契约：
    - 同步方法（sync），不抛异常，失败时 passed=False + 拦截话术
    - 所有内部错误被捕获并转化为 block_reason
    """

    # 配置常量
    MAX_INPUT_LENGTH: int = 500
    MAX_REPEAT_COUNT: int = 5
    MIN_MEANINGFUL_RATIO: float = 0.1

    # 默认敏感词库（可外置到配置文件热更新）
    DEFAULT_SENSITIVE_WORDS: Set[str] = {
        "傻逼", "sb", "脑残", "他妈的", "草泥马", "cnm",
    }

    @staticmethod
    def _make_hash(text: str) -> str:
        """使用 SHA-256 生成输入指纹，消除 hash() 碰撞风险。"""
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def __init__(self, sensitive_words: Optional[Set[str]] = None) -> None:
        self._sensitive_words = sensitive_words or self.DEFAULT_SENSITIVE_WORDS.copy()
        # 重复刷屏检测：记录最近 N 条输入的 SHA-256 指纹
        self._recent_hashes: List[str] = []
        self._recent_limit: int = 10

    def filter(self, text: str) -> HardFilterResult:
        """执行硬规则过滤，返回结果。同步、不抛异常。"""
        try:
            return self._do_filter(text)
        except Exception as e:
            return HardFilterResult(
                passed=False,
                block_reason=f"filter_internal_error: {e}",
                response_message="输入处理遇到小问题，请稍后再试~",
            )

    def _do_filter(self, text: str) -> HardFilterResult:
        # R1: 空输入 / 纯空白
        if not text or not text.strip():
            return HardFilterResult(
                passed=False,
                block_reason="empty_input",
                response_message="你好像什么都没说呢，请问你想了解什么？",
            )

        stripped = text.strip()

        # R2: 输入过长
        if len(stripped) > self.MAX_INPUT_LENGTH:
            return HardFilterResult(
                passed=False,
                block_reason="input_too_long",
                response_message="输入太长了，能不能简短一点？比如直接说股票代码或问题~",
            )

        # R3: 敏感词过滤
        lower = stripped.lower()
        for word in self._sensitive_words:
            if word in lower:
                return HardFilterResult(
                    passed=False,
                    block_reason="sensitive_word",
                    response_message="请注意文明用语哦~ 股大师期待和你友好交流！",
                )

        # R4: 重复刷屏
        text_hash = self._make_hash(stripped)
        repeat_count = self._recent_hashes.count(text_hash)
        self._recent_hashes.append(text_hash)
        if len(self._recent_hashes) > self._recent_limit:
            self._recent_hashes.pop(0)
        if repeat_count >= self.MAX_REPEAT_COUNT:
            return HardFilterResult(
                passed=False,
                block_reason="spam_repeat",
                response_message="收到收到~ 相同的话重复太多次啦，换个问题问问吧？",
            )

        # R5: 无意义字符
        if self._is_meaningless(stripped):
            return HardFilterResult(
                passed=False,
                block_reason="meaningless_input",
                response_message="这个输入我没看懂，可以重新描述一下你的问题吗？",
            )

        # R6: 编码异常 / 控制字符
        if self._has_control_chars(stripped):
            return HardFilterResult(
                passed=False,
                block_reason="control_chars",
                response_message="输入包含异常字符，请使用正常文字描述~",
            )

        return HardFilterResult(passed=True)

    def _is_meaningless(self, text: str) -> bool:
        """判断是否为无意义输入：纯符号、纯数字无上下文、汉字占比过低"""
        # 纯符号（无汉字、无字母、无数字）
        if re.match(r"^[^\w\u4e00-\u9fff]+$", text):
            return True

        # 纯数字且无股票代码特征（6位数字是合法股票代码，不算无意义）
        if re.match(r"^\d+$", text):
            # 6位数字可能是股票代码，保留
            if len(text) == 6:
                return False
            return True

        # 汉字+字母+数字占比过低（<10% 有意义字符）
        meaningful_chars = len(re.findall(r"[\w\u4e00-\u9fff]", text))
        if len(text) > 0 and meaningful_chars / len(text) < self.MIN_MEANINGFUL_RATIO:
            return True

        return False

    def _has_control_chars(self, text: str) -> bool:
        """检测非法控制字符（除正常换行、制表符外）"""
        for ch in text:
            code = ord(ch)
            # 0x00-0x08, 0x0B-0x0C, 0x0E-0x1F 为控制字符
            if (0x00 <= code <= 0x08) or (0x0B <= code <= 0x0C) or (0x0E <= code <= 0x1F):
                return True
        return False

    def update_sensitive_words(self, words: Set[str]) -> None:
        """热更新敏感词库"""
        self._sensitive_words = words.copy()
