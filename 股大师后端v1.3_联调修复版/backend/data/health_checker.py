"""
数据源健康检查器 — 生产环境降级策略

架构决策(ADR-022): 三态自动切换 NORMAL → DEGRADED → OFFLINE，
HealthChecker 每 60 秒探测，连续 3 次失败才切换，避免网络抖动误切。
"""

from __future__ import annotations

import asyncio
import sys
from concurrent.futures import ThreadPoolExecutor
from enum import Enum
from typing import Literal, Optional


class HealthStatus(Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


class DataSourceHealthChecker:
    """数据源健康检查器 — 每 60 秒探测一次"""

    PROBE_INTERVAL_SECONDS = 60
    FAILURE_THRESHOLD = 3
    PROBE_TIMEOUT = 3.0

    _executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="health_probe")

    def __init__(self) -> None:
        self._consecutive_failures = 0
        self._consecutive_successes = 0
        self._mode: Literal["normal", "degraded", "offline"] = "normal"
        self._last_check: Optional[float] = None
        self._running = False
        self._task: Optional[asyncio.Task] = None

    @property
    def current_mode(self) -> Literal["normal", "degraded", "offline"]:
        """返回当前运行模式"""
        return self._mode

    async def check_akshare(self) -> HealthStatus:
        """探测 A股数据源（与适配器一致）：东财快照优先，失败回退新浪单股日线"""
        try:
            import akshare as ak

            loop = asyncio.get_event_loop()
            # 1) 腾讯日线（更稳定，不受东方财富风控）
            try:
                import datetime as _dt
                _end = _dt.date.today().strftime('%Y%m%d')
                _start = (_dt.date.today() - _dt.timedelta(days=30)).strftime('%Y%m%d')
                df = await asyncio.wait_for(
                    loop.run_in_executor(
                        self._executor,
                        lambda: ak.stock_zh_index_daily_tx(symbol="sh000001", start_date=_start, end_date=_end),
                    ),
                    timeout=self.PROBE_TIMEOUT,
                )
                if df is not None and not df.empty:
                    return HealthStatus.HEALTHY
            except Exception:
                pass

            # 2) 新浪备源（单股日线，约 5-10s）：探测与适配器回退行为保持一致，
            #    避免东财被网络环境封锁时误判 UNHEALTHY → offline
            try:
                df = await asyncio.wait_for(
                    loop.run_in_executor(
                        self._executor,
                        lambda: ak.stock_zh_a_daily(
                            symbol="sz000001", start_date="20260801", end_date="20260831"
                        ),
                    ),
                    timeout=10.0,
                )
                if df is not None and not df.empty:
                    return HealthStatus.HEALTHY
                return HealthStatus.DEGRADED
            except Exception:
                return HealthStatus.DEGRADED
        except Exception:
            return HealthStatus.UNHEALTHY

    async def check_yfinance(self) -> HealthStatus:
        """尝试获取一只已知美股行情，3 秒超时（ADR-026）"""
        try:
            import yfinance as yf

            loop = asyncio.get_event_loop()
            ticker = await asyncio.wait_for(
                loop.run_in_executor(
                    self._executor,
                    lambda: yf.Ticker("AAPL"),
                ),
                timeout=self.PROBE_TIMEOUT,
            )
            hist = await asyncio.wait_for(
                loop.run_in_executor(
                    self._executor,
                    lambda: ticker.history(period="1d"),
                ),
                timeout=self.PROBE_TIMEOUT,
            )
            if hist is not None and not hist.empty:
                return HealthStatus.HEALTHY
            return HealthStatus.DEGRADED
        except Exception:
            return HealthStatus.UNHEALTHY

    async def start(self) -> None:
        """启动健康检查后台任务"""
        self._running = True

        async def probe_loop() -> None:
            while self._running:
                try:
                    # 同时探测 A股和美股数据源
                    ak_status = await self.check_akshare()
                    yf_status = await self.check_yfinance()
                    # PRD 4.3.2 降级策略：仅两路数据源均不可用才 UNHEALTHY（offline）；
                    # 单路失败 → DEGRADED（部分可用：A股实时 / 港美股走缓存），两路正常 → HEALTHY
                    if (
                        ak_status == HealthStatus.UNHEALTHY
                        and yf_status == HealthStatus.UNHEALTHY
                    ):
                        overall = HealthStatus.UNHEALTHY
                    elif (
                        ak_status == HealthStatus.HEALTHY
                        and yf_status == HealthStatus.HEALTHY
                    ):
                        overall = HealthStatus.HEALTHY
                    else:
                        overall = HealthStatus.DEGRADED

                    # 同步感知 YFinanceClient 降级状态
                    from data.yfinance_client import yfinance_client
                    yf_degraded = yfinance_client.is_degraded
                    if yf_degraded and overall == HealthStatus.HEALTHY:
                        # yfinance 已降级但 akshare 正常 -> 整体降级
                        overall = HealthStatus.DEGRADED

                    self._update_mode(overall)
                except Exception as e:
                    print(f"[HealthChecker] probe error: {e}", file=sys.stderr, flush=True)
                await asyncio.sleep(self.PROBE_INTERVAL_SECONDS)

        self._task = asyncio.create_task(probe_loop())

    async def stop(self) -> None:
        """停止健康检查"""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    def _update_mode(self, status: HealthStatus) -> None:
        """根据探测结果更新运行模式"""
        if status == HealthStatus.HEALTHY:
            self._consecutive_successes += 1
            self._consecutive_failures = 0
            # 连续 1 次成功即从 OFFLINE/DEGRADED 恢复
            if self._mode in ("offline", "degraded") and self._consecutive_successes >= 1:
                print(f"[HealthChecker] 模式切换: {self._mode} -> normal", file=sys.stderr, flush=True)
                self._mode = "normal"
        elif status == HealthStatus.DEGRADED:
            self._consecutive_failures += 1
            self._consecutive_successes = 0
            if self._mode == "normal" and self._consecutive_failures >= self.FAILURE_THRESHOLD:
                print(f"[HealthChecker] 模式切换: normal -> degraded", file=sys.stderr, flush=True)
                self._mode = "degraded"
        else:  # UNHEALTHY
            self._consecutive_failures += 1
            self._consecutive_successes = 0
            if self._consecutive_failures >= self.FAILURE_THRESHOLD:
                if self._mode != "offline":
                    print(f"[HealthChecker] 模式切换: {self._mode} -> offline", file=sys.stderr, flush=True)
                    self._mode = "offline"

    def get_mode_display(self) -> str:
        """获取当前模式的中文显示"""
        return {
            "normal": "正常",
            "degraded": "降级",
            "offline": "离线",
        }.get(self._mode, "未知")


# 全局单例
health_checker = DataSourceHealthChecker()
