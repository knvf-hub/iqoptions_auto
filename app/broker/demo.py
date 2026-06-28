from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass
from typing import Optional

from app.broker.base import BrokerError, BrokerOrder, BrokerStatus, Candle
from app.config import AppConfig


@dataclass
class _DemoPosition:
    order: BrokerOrder
    opened_at: float
    expires_at: float


class DemoBroker:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self._connected = True
        self._balance = 10000.0
        self._price = 1.084
        self._positions: dict[str, _DemoPosition] = {}
        self._rng = random.Random(42)

    def connect(self) -> BrokerStatus:
        self._connected = True
        return self.status("Demo broker connected")

    def status(self, message: str = "") -> BrokerStatus:
        return BrokerStatus(
            connected=self._connected,
            mode="demo",
            account_type="PRACTICE",
            balance=round(self._balance, 2),
            message=message,
        )

    def get_candles(self, asset: str, interval_sec: int, count: int) -> list[Candle]:
        return self.get_candles_until(asset, interval_sec, count, time.time())

    def get_candles_until(self, asset: str, interval_sec: int, count: int, endtime: float) -> list[Candle]:
        if not self._connected:
            self.connect()

        now = int(endtime)
        candles: list[Candle] = []
        base = self._price
        start = now - (count * interval_sec)
        for idx in range(count):
            t = start + idx * interval_sec
            drift = math.sin((t / 3600.0) + len(asset)) * 0.00025
            noise = self._rng.uniform(-0.00018, 0.00018)
            open_price = base
            close_price = max(0.0001, open_price + drift + noise)
            high = max(open_price, close_price) + abs(self._rng.uniform(0.0, 0.00016))
            low = min(open_price, close_price) - abs(self._rng.uniform(0.0, 0.00016))
            volume = 100 + abs(self._rng.gauss(0, 35))
            candles.append(
                Candle(
                    timestamp=t,
                    open=round(open_price, 6),
                    high=round(high, 6),
                    low=round(low, 6),
                    close=round(close_price, 6),
                    volume=round(volume, 2),
                )
            )
            base = close_price
        self._price = candles[-1].close if candles else self._price
        return candles

    def list_assets(self) -> dict:
        assets = [
            "EURUSD-OTC",
            "GBPUSD-OTC",
            "EURJPY-OTC",
            "AUDCAD-OTC",
            "US500-OTC",
            "OPENAI-OTC",
        ]
        return {
            "broker": "demo",
            "items": [{"name": asset, "type": "binary", "open": True} for asset in assets],
        }

    def place_order(
        self,
        asset: str,
        instrument: str,
        direction: str,
        amount: float,
        duration_minutes: int,
    ) -> BrokerOrder:
        if direction not in {"call", "put"}:
            raise BrokerError("direction must be call or put")
        if amount <= 0:
            raise BrokerError("amount must be greater than zero")
        if amount > self._balance:
            raise BrokerError("demo balance is not enough")

        candles = self.get_candles(asset, self.config.trading.candle_interval_sec, 2)
        entry_price = candles[-1].close
        order_id = f"demo-{int(time.time() * 1000)}-{self._rng.randint(1000, 9999)}"
        order = BrokerOrder(
            order_id=order_id,
            asset=asset,
            instrument=instrument,
            direction=direction,
            amount=amount,
            duration_minutes=duration_minutes,
            entry_price=entry_price,
            raw={"broker": "demo"},
        )
        self._balance -= amount
        self._positions[order_id] = _DemoPosition(
            order=order,
            opened_at=time.time(),
            expires_at=time.time() + duration_minutes * 60,
        )
        return order

    def resolve_order(
        self,
        order_id: str,
        instrument: str,
        duration_minutes: Optional[int] = None,
    ) -> tuple[Optional[float], dict]:
        position = self._positions.get(order_id)
        if position is None:
            return None, {"status": "unknown", "message": "demo order not found"}
        if time.time() < position.expires_at:
            return None, {"status": "open"}

        candles = self.get_candles(position.order.asset, self.config.trading.candle_interval_sec, 3)
        exit_price = candles[-1].close
        direction = position.order.direction
        won = exit_price > (position.order.entry_price or exit_price) if direction == "call" else exit_price < (position.order.entry_price or exit_price)
        payout_rate = 0.82
        profit = round(position.order.amount * payout_rate, 2) if won else round(-position.order.amount, 2)
        if won:
            self._balance += position.order.amount + profit
        raw = {
            "status": "closed",
            "exit_price": exit_price,
            "won": won,
            "payout_rate": payout_rate,
            "balance": round(self._balance, 2),
        }
        del self._positions[order_id]
        return profit, raw
