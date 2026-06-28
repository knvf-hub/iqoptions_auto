from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Union

from app.broker.base import Candle


@dataclass
class TradeSignal:
    action: str
    confidence: float
    reason: str
    close_price: Optional[float]
    metrics: dict[str, Optional[Union[float, str]]]


def _ema(values: list[float], period: int) -> list[float]:
    if not values:
        return []
    multiplier = 2 / (period + 1)
    series = [values[0]]
    for value in values[1:]:
        series.append((value - series[-1]) * multiplier + series[-1])
    return series


def _rsi(values: list[float], period: int = 14) -> Optional[float]:
    if len(values) <= period:
        return None
    gains: list[float] = []
    losses: list[float] = []
    for idx in range(1, period + 1):
        change = values[idx] - values[idx - 1]
        gains.append(max(change, 0))
        losses.append(abs(min(change, 0)))

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    for idx in range(period + 1, len(values)):
        change = values[idx] - values[idx - 1]
        avg_gain = ((avg_gain * (period - 1)) + max(change, 0)) / period
        avg_loss = ((avg_loss * (period - 1)) + abs(min(change, 0))) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _atr(candles: list[Candle], period: int = 14) -> Optional[float]:
    if len(candles) <= period:
        return None
    ranges: list[float] = []
    previous_close = candles[-period - 1].close
    for candle in candles[-period:]:
        ranges.append(max(candle.high - candle.low, abs(candle.high - previous_close), abs(candle.low - previous_close)))
        previous_close = candle.close
    return sum(ranges) / period


def evaluate_signal(candles: list[Candle]) -> TradeSignal:
    if len(candles) < 35:
        return TradeSignal("hold", 0.0, "not_enough_candles", None, {})

    closes = [candle.close for candle in candles]
    ema_fast = _ema(closes, 9)
    ema_slow = _ema(closes, 21)
    rsi_value = _rsi(closes, 14)
    atr_value = _atr(candles, 14)
    close = closes[-1]
    previous = closes[-4] if len(closes) >= 4 else closes[-2]
    momentum = (close - previous) / previous if previous else 0.0
    slope_fast = ema_fast[-1] - ema_fast[-4]
    slope_slow = ema_slow[-1] - ema_slow[-4]
    trend_gap = (ema_fast[-1] - ema_slow[-1]) / close if close else 0.0
    atr_ratio = (atr_value / close) if atr_value and close else 0.0

    metrics: dict[str, Optional[Union[float, str]]] = {
        "ema_fast": round(ema_fast[-1], 6),
        "ema_slow": round(ema_slow[-1], 6),
        "rsi": round(rsi_value, 2) if rsi_value is not None else None,
        "momentum": round(momentum, 6),
        "trend_gap": round(trend_gap, 6),
        "atr_ratio": round(atr_ratio, 6),
        "close": round(close, 6),
    }

    if rsi_value is None:
        return TradeSignal("hold", 0.0, "rsi_unavailable", close, metrics)

    trend_up = ema_fast[-1] > ema_slow[-1] and slope_fast > 0 and slope_slow >= 0
    trend_down = ema_fast[-1] < ema_slow[-1] and slope_fast < 0 and slope_slow <= 0
    calm_enough = atr_ratio < 0.006

    if trend_up and momentum > 0 and 45 <= rsi_value <= 72 and calm_enough:
        confidence = 0.58 + min(abs(trend_gap) * 300, 0.12) + min(abs(momentum) * 200, 0.12)
        return TradeSignal("call", round(min(confidence, 0.9), 3), "ema_up_momentum_confirmed", close, metrics)

    if trend_down and momentum < 0 and 28 <= rsi_value <= 55 and calm_enough:
        confidence = 0.58 + min(abs(trend_gap) * 300, 0.12) + min(abs(momentum) * 200, 0.12)
        return TradeSignal("put", round(min(confidence, 0.9), 3), "ema_down_momentum_confirmed", close, metrics)

    if rsi_value <= 25 and momentum > -0.0004 and calm_enough:
        confidence = 0.6 + min((25 - rsi_value) / 100, 0.1)
        return TradeSignal("call", round(min(confidence, 0.82), 3), "rsi_oversold_reversion", close, metrics)

    if rsi_value >= 75 and momentum < 0.0004 and calm_enough:
        confidence = 0.6 + min((rsi_value - 75) / 100, 0.1)
        return TradeSignal("put", round(min(confidence, 0.82), 3), "rsi_overbought_reversion", close, metrics)

    return TradeSignal("hold", 0.0, "no_trade_edge", close, metrics)
