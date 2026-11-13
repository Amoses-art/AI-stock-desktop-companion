"""
SQLite 数据库初始化与管理

MVP 阶段使用标准 sqlite3（SQLCipher 在完整 Tauri 环境中启用）
所有持仓/配置/提醒数据本地持久化，不上传云端
"""

from __future__ import annotations

import asyncio
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator, Optional

import aiosqlite
import sys


def _get_data_dir() -> Path:
    """获取数据目录 — 统一使用系统标准用户数据目录，开发与打包一致。

    历史：开发环境曾用 backend/data/，与打包环境 AppData 双轨，
    导致打包后数据丢失（Gudashi v1.3 联调修复 2026-09-03）。
    """
    if sys.platform == "win32":
        base = Path.home() / "AppData" / "Local" / "Gudashi"
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / "Gudashi"
    else:
        base = Path.home() / ".local" / "share" / "gudashi"
    base.mkdir(parents=True, exist_ok=True)
    return base


DATA_DIR = _get_data_dir()
DB_PATH = DATA_DIR / "gudashi.db"

# === DDL ===
INIT_SQL = """
-- 持仓表（支持股票 + 基金）
CREATE TABLE IF NOT EXISTS portfolio (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,           -- 代码，如 600519
    name TEXT NOT NULL,             -- 名称，如 贵州茅台
    market TEXT NOT NULL DEFAULT 'cn',
    asset_type TEXT NOT NULL,       -- "stock" | "fund_open" | "fund_etf" | "fund_lof" | "fund_money"
    quantity REAL NOT NULL,         -- 持仓数量
    cost_price REAL NOT NULL,       -- 成本价
    currency TEXT DEFAULT 'CNY',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(symbol, market, asset_type)
);

-- 提醒规则表
CREATE TABLE IF NOT EXISTS alert_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    portfolio_id INTEGER NOT NULL,
    threshold_percent REAL NOT NULL, -- 阈值百分比，如 3.0 表示 ±3%
    direction TEXT DEFAULT 'both',   -- "up" | "down" | "both"
    is_active INTEGER DEFAULT 1,
    last_triggered_at TIMESTAMP,
    cooldown_minutes INTEGER DEFAULT 5,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (portfolio_id) REFERENCES portfolio(id) ON DELETE CASCADE
);

-- 行情缓存表（离线回退用）
CREATE TABLE IF NOT EXISTS quote_cache (
    symbol TEXT PRIMARY KEY,
    market TEXT DEFAULT 'cn',
    name TEXT DEFAULT '',
    current_price REAL,
    pre_close REAL,
    open_price REAL,
    high_price REAL,
    low_price REAL,
    change_amount REAL,
    change_percent REAL,
    volume REAL,
    turnover REAL,
    currency TEXT DEFAULT 'CNY',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 用户配置表
CREATE TABLE IF NOT EXISTS user_config (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 皮肤配置表
CREATE TABLE IF NOT EXISTS skin_config (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    skin_name TEXT NOT NULL DEFAULT 'tech_bull',
    is_active INTEGER DEFAULT 1,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 对话历史表（上下文存储）
CREATE TABLE IF NOT EXISTS conversation_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    intent TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_conv_session ON conversation_history(session_id, created_at);

-- 交易时间配置表
CREATE TABLE IF NOT EXISTS trading_hours_config (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    is_enabled INTEGER DEFAULT 1,
    start_time TEXT DEFAULT '09:20',
    end_time TEXT DEFAULT '15:00',
    always_show INTEGER DEFAULT 0,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 预算使用表（每日持久化，支持跨天自动重置）
CREATE TABLE IF NOT EXISTS budget_usage (
    date TEXT PRIMARY KEY,           -- YYYY-MM-DD
    spent REAL NOT NULL DEFAULT 0.0, -- 当日已用额度
    "limit" REAL NOT NULL DEFAULT 50.0, -- 当日额度上限（SQLite保留关键字，需引号）
    updated_at INTEGER NOT NULL      -- 更新时间戳（unix epoch）
);

-- 初始化默认配置
INSERT OR IGNORE INTO user_config (key, value) VALUES
    ('default_alert_threshold_stock', '5.0'),
    ('default_alert_threshold_fund', '3.0'),
    ('quote_polling_interval_cn', '5'),
    ('quote_polling_interval_fund', '60'),
    ('data_source_retry_times', '3'),
    ('data_source_retry_delay', '2'),
    ('llm_tier_preference', 'local_first'),
    ('local_model_name', 'qwen2.5:7b');

INSERT OR IGNORE INTO skin_config (skin_name, is_active) VALUES ('tech_bull', 1);

INSERT OR IGNORE INTO trading_hours_config (is_enabled, start_time, end_time, always_show)
    VALUES (1, '09:20', '15:00', 0);
"""


# --- Schema migration (兼容旧版本 DB) ---
_QUOTE_CACHE_EXPECTED_COLS = {
    "symbol": "TEXT PRIMARY KEY",
    "market": "TEXT DEFAULT 'cn'",
    "name": "TEXT DEFAULT ''",
    "current_price": "REAL",
    "pre_close": "REAL",
    "open_price": "REAL",
    "high_price": "REAL",
    "low_price": "REAL",
    "change_amount": "REAL",
    "change_percent": "REAL",
    "volume": "REAL",
    "turnover": "REAL",
    "currency": "TEXT DEFAULT 'CNY'",
    "updated_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
}

_USER_CONFIG_DEFAULTS = {
    "ai_enabled": "False",
    "first_run_done": "False",
    "ollama_host": "http://127.0.0.1:11434",
    "ollama_timeout": "60",
}


async def _migrate_schema(db):
    """检测并补齐缺失列 — 兼容历史版本 DB"""
    cur = await db.execute("PRAGMA table_info(quote_cache)")
    existing = {row[1] for row in (await cur.fetchall())}
    for col, defn in _QUOTE_CACHE_EXPECTED_COLS.items():
        if col not in existing:
            await db.execute(f"ALTER TABLE quote_cache ADD COLUMN {col} {defn}")
            print(f"  [migration] quote_cache +{col}")
    for k, v in _USER_CONFIG_DEFAULTS.items():
        await db.execute(
            "INSERT OR IGNORE INTO user_config (key, value) VALUES (?, ?)",
            (k, v),
        )
    await db.commit()


class Database:
    """异步 SQLite 数据库管理器"""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or DB_PATH

    async def init(self) -> None:
        """初始化数据库：建表 + 默认数据 + schema migration"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.executescript(INIT_SQL)
            await _migrate_schema(db)
            await db.commit()

    @asynccontextmanager
    async def connection(self) -> AsyncGenerator[aiosqlite.Connection, None]:
        """获取数据库连接上下文（WAL 模式 + busy_timeout，避免读写锁冲突）"""
        db = await aiosqlite.connect(self.db_path)
        db.row_factory = aiosqlite.Row
        try:
            # WAL 模式：读写并发不互斥，解决行情轮询写 quote_cache 时
            # config.set / portfolio.add 等用户写操作 "database is locked" 的问题
            await db.execute("PRAGMA journal_mode=WAL")
            # 遇到锁时等待最多 5s，而非立即抛 "database is locked"
            await db.execute("PRAGMA busy_timeout=5000")
            yield db
        finally:
            await db.close()

    async def execute(self, sql: str, params: tuple = ()) -> int:
        """执行 INSERT/UPDATE/DELETE，返回受影响行数"""
        async with self.connection() as db:
            cursor = await db.execute(sql, params)
            await db.commit()
            return cursor.rowcount

    async def execute_insert(self, sql: str, params: tuple = ()) -> int:
        """执行 INSERT，返回新行的自增主键（lastrowid）

        注意与 execute 的区别：execute 返回受影响行数（单行 INSERT 恒为 1），
        不能当作新行 id 使用——需要取回自增 id 的场景必须用本方法。
        """
        async with self.connection() as db:
            cursor = await db.execute(sql, params)
            await db.commit()
            return cursor.lastrowid or 0

    async def fetchone(self, sql: str, params: tuple = ()) -> Optional[dict]:
        """查询单条记录"""
        async with self.connection() as db:
            cursor = await db.execute(sql, params)
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def fetchall(self, sql: str, params: tuple = ()) -> list[dict]:
        """查询多条记录"""
        async with self.connection() as db:
            cursor = await db.execute(sql, params)
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]


# 全局单例
db = Database()


async def init_database() -> None:
    """启动时调用：初始化数据库"""
    await db.init()
