from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol


@dataclass
class Candle:
    timestamp: int
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


@dataclass
class BrokerStatus:
    connected: bool
    mode: str
    account_type: str
    balance: Optional[float]
    message: str = ""


@dataclass
class BrokerOrder:
    order_id: str
    asset: str
    instrument: str
    direction: str
    amount: float
    duration_minutes: int
    entry_price: Optional[float] = None
    raw: Optional[dict] = None


class BrokerError(RuntimeError):
    pass


class Broker(Protocol):
    def connect(self) -> BrokerStatus:
        ...

    def status(self) -> BrokerStatus:
        ...

    def get_candles(self, asset: str, interval_sec: int, count: int) -> list[Candle]:
        ...

    def get_candles_until(self, asset: str, interval_sec: int, count: int, endtime: float) -> list[Candle]:
        ...

    def list_assets(self) -> dict:
        ...

    def place_order(
        self,
        asset: str,
        instrument: str,
        direction: str,
        amount: float,
        duration_minutes: int,
    ) -> BrokerOrder:
        ...

    def resolve_order(
        self,
        order_id: str,
        instrument: str,
        duration_minutes: Optional[int] = None,
    ) -> tuple[Optional[float], dict]:
        ...
