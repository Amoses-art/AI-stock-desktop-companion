"""
数据适配器基类 — 多市场数据源统一接口
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class QuoteData:
    """统一行情数据结构"""

    symbol: str = ""
    name: str = ""
    market: str = "cn"
    asset_type: str = "stock"
    current_price: float = 0.0
    pre_close: float = 0.0
    open_price: float = 0.0
    high_price: float = 0.0
    low_price: float = 0.0
    change_amount: float = 0.0
    change_percent: float = 0.0
    volume: float = 0.0
    turnover: float = 0.0
    timestamp: str = ""
    currency: str = "CNY"

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "name": self.name,
            "market": self.market,
            "asset_type": self.asset_type,
            "current_price": self.current_price,
            "pre_close": self.pre_close,
            "open_price": self.open_price,
            "high_price": self.high_price,
            "low_price": self.low_price,
            "change_amount": self.change_amount,
            "change_percent": self.change_percent,
            "volume": self.volume,
            "turnover": self.turnover,
            "timestamp": self.timestamp,
            "currency": self.currency,
        }


class DataAdapter(ABC):
    """数据适配器抽象基类"""

    name: str = "base"
    priority: int = 0  # 优先级，数字越小越优先
    # 服务的资产类型；None 表示服务所有类型（股票/基金等）
    asset_types: Optional[List[str]] = None

    def serves(self, asset_type: str) -> bool:
        """该适配器是否服务指定资产类型"""
        if self.asset_types is None:
            return True
        return asset_type in self.asset_types

    @abstractmethod
    async def get_quote(self, symbol: str) -> Optional[QuoteData]:
        """获取单只标的实时行情"""
        pass

    @abstractmethod
    async def get_batch_quotes(self, symbols: List[str]) -> List[QuoteData]:
        """批量获取行情"""
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """检查适配器是否可用"""
        pass
