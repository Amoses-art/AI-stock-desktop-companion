"""
全局配置管理器 — 兼容用户 Skill 库的 GLOBAL_CONFIG

设计原则：
1. 用户原有 GLOBAL_CONFIG 中的参数全部保留
2. 新增桌面应用相关参数
3. 支持运行时热更新
4. 配置从 SQLite user_config 表加载，覆盖默认值
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any, Optional

from local.db import db

# === 用户 Skill 库原有参数 + 新增参数 ===
DEFAULT_GLOBAL_CONFIG: dict[str, Any] = {
    # === 用户 Skill 库原有参数（全部保留）===
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

    # === 数据源参数 ===
    "quote_polling_interval_cn": 5,
    "quote_polling_interval_hk": 10,
    "quote_polling_interval_us": 10,
    "quote_polling_interval_fund": 60,
    "data_source_retry_times": 3,
    "data_source_retry_delay": 2,

    # === 提醒参数 ===
    "alert_default_threshold_stock": 5.0,
    "alert_default_threshold_fund": 3.0,
    "alert_cooldown_minutes": 5,

    # === UI 参数 ===
    "default_skin": "tech_bull",
    "edge_snap_threshold": 50,
    "edge_snap_offset": 5,
    "trading_hours_default_start": "09:00",
    "trading_hours_default_end": "15:00",

    # === AI 参数 ===
    "llm_tier_preference": "local_first",
    "local_model_name": "qwen2.5:1.5b",
    "ollama_host": "http://127.0.0.1:11434",
    "ollama_timeout": 60,

    # ---------- M2：产品功能开关 ----------
    "ai_enabled": True,       # AI 对话能力（M2 门控 / M3 Ollama 链路）
    "first_run_done": False,   # 首启向导完成标记（M2-3）

    # === 搜索服务参数 ===
    "search_backend": "",  # serpapi | bing | mock
    "serpapi_api_key": "",
    "bing_search_api_key": "",
}


class ConfigManager:
    """配置管理器 — 运行时热更新"""

    def __init__(self) -> None:
        self._config = DEFAULT_GLOBAL_CONFIG.copy()
        # 安装器标记优先级最高：由 NSIS 安装器写入 installer_flags.json
        self._apply_installer_flags()

    @staticmethod
    def _backend_root() -> str:
        """获取后端根目录（PyInstaller 打包后为 exe 所在目录；开发模式为 backend/）"""
        if getattr(sys, "frozen", False):
            return os.path.dirname(sys.executable)
        # global_config.py 位于 backend/config/，向上一级即 backend 根
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def _apply_installer_flags(self) -> None:
        """读取安装器写入的 installer_flags.json，覆盖 ai_enabled 默认值

        优先级：installer_flags.json > SQLite user_config > 默认值
        若文件不存在或解析失败则保持默认值不变。
        """
        flags_path = os.path.join(self._backend_root(), "installer_flags.json")
        try:
            if os.path.isfile(flags_path):
                with open(flags_path, "r", encoding="utf-8") as f:
                    flags = json.load(f)
                if isinstance(flags, dict) and "ai_enabled" in flags:
                    self._config["ai_enabled"] = bool(flags["ai_enabled"])
        except Exception:
            # 任何异常都不影响后端启动
            pass

    async def load_from_db(self) -> None:
        """从 SQLite 加载用户自定义配置覆盖默认值"""
        rows = await db.fetchall("SELECT key, value FROM user_config")
        for row in rows:
            key = row["key"]
            raw = row["value"]
            if key in DEFAULT_GLOBAL_CONFIG:
                default_val = DEFAULT_GLOBAL_CONFIG[key]
                # 类型保持与默认值一致（bool 必须在 int 之前判断：bool 是 int 子类）
                if isinstance(default_val, bool):
                    self._config[key] = str(raw).lower() == "true"
                elif isinstance(default_val, int):
                    self._config[key] = int(float(raw))
                elif isinstance(default_val, float):
                    self._config[key] = float(raw)
                else:
                    self._config[key] = raw
        # 安装器标记优先级最高，DB 加载后再次应用以确保不被覆盖
        self._apply_installer_flags()

    def get(self, key: str, default: Any = None) -> Any:
        return self._config.get(key, default)

    def get_float(self, key: str, default: float = 0.0) -> float:
        return float(self._config.get(key, default))

    def get_int(self, key: str, default: int = 0) -> int:
        return int(self._config.get(key, default))

    async def set(self, key: str, value: Any) -> None:
        self._config[key] = value
        await db.execute(
            "INSERT INTO user_config (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=CURRENT_TIMESTAMP",
            (key, str(value)),
        )

    def get_all(self) -> dict[str, Any]:
        return self._config.copy()


# 全局单例
config_manager = ConfigManager()
