from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Literal, Optional

from app.broker.base import Candle
from app.indicators import TradeSignal, evaluate_signal


Direction = Literal["call", "put"]
TieHandling = Literal["loss", "skip"]


@dataclass(frozen=True)
class OpenAIStrategyConfig:
    bullish_streak: int = 2
    call_min_body_ratio: float = 0.70
    call_min_atr_ratio: float = 0.001
    call_max_atr_ratio: float = 0.0012
    bearish_streak: int = 4
    put_min_body_ratio: float = 0.45
    put_min_atr_ratio: float = 0.001
    put_max_atr_ratio: float = 0.003
    atr_period: int = 14
    ema_fast_period: int = 9
    ema_slow_period: int = 21


@dataclass(frozen=True)
class ONDOStrategyConfig:
    min_wick_ratio: float = 0.55
    call_close_pos: float = 0.75
    put_close_pos: float = 0.25
    call_close_pos_min: float = 0.75
    put_close_pos_max: float = 0.25
    min_body_ratio: float = 0.0


@dataclass(frozen=True)
class GBPUSDStrategyConfig:
    support_lookback: int = 50
    resistance_lookback: int = 100
    atr_period: int = 14
    tolerance_atr_multiplier: float = 0.25
    call_tolerance_atr_multiplier: float = 0.2
    min_wick_ratio: float = 0.35
    call_min_wick_ratio: float = 0.30
    call_close_pos_min: float = 0.65
    put_close_pos_max: float = 0.35
    block_opposite_img_score: float = 80.0
    block_opposite_lookback: int = 5


@dataclass(frozen=True)
class EURJPYStrategyConfig:
    atr_period: int = 14
    max_atr_ratio: float = 0.0004
    call_bearish_streak: int = 5
    call_min_body_ratio: float = 0.45
    put_bullish_streak: int = 4
    put_min_body_ratio: float = 0.65


@dataclass(frozen=True)
class USDJPYStrategyConfig:
    strategy: str = "streak_exhaustion_reversal"
    mode: str = "balanced"
    call_bearish_streak: int = 7
    call_min_body_ratio: float = 0.0
    put_bullish_streak: int = 6
    put_min_body_ratio: float = 0.45


@dataclass(frozen=True)
class AUDJPYStrategyConfig:
    call_bullish_streak: int = 6
    call_min_body_ratio: float = 0.55
    call_min_atr_ratio: float = 0.000731
    atr_period: int = 14
    ema_fast_period: int = 9
    ema_slow_period: int = 21
    resistance_lookback: int = 100
    tolerance_atr_multiplier: float = 0.2
    put_min_upper_wick_ratio: float = 0.30
    put_max_close_pos: float = 0.35
    block_if_img_call_score_gte: float = 80.0


@dataclass(frozen=True)
class AlibabaStrategyConfig:
    support_lookback: int = 100
    resistance_lookback: int = 20
    atr_period: int = 14
    call_tolerance_atr_multiplier: float = 0.2
    put_tolerance_atr_multiplier: float = 0.5
    call_min_lower_wick_ratio: float = 0.25
    call_min_close_pos: float = 0.60
    put_min_upper_wick_ratio: float = 0.50
    put_max_close_pos: float = 0.25
    block_if_img_call_score_gte: float = 80.0


@dataclass(frozen=True)
class CasinosStrategyConfig:
    strategy: str = "put_resistance_wick_rejection"
    mode: str = "balanced"
    call_enabled: bool = False
    resistance_lookback: int = 20
    atr_period: int = 14
    tolerance_atr_multiplier: float = 0.5
    min_upper_wick_ratio: float = 0.60
    max_close_pos: float = 0.35


@dataclass(frozen=True)
class ETHUSDStrategyConfig:
    strategy: str = "eth_sr_wick_rejection"
    mode: str = "balanced"
    call_support_lookback: int = 100
    call_atr_period: int = 14
    call_tolerance_atr_multiplier: float = 0.3
    call_min_lower_wick_ratio: float = 0.25
    call_min_close_pos: float = 0.75
    put_resistance_lookback: int = 150
    put_atr_period: int = 14
    put_tolerance_atr_multiplier: float = 1.0
    put_min_upper_wick_ratio: float = 0.30
    put_max_close_pos: float = 0.30
    accurate_put_bb_period: int = 20
    accurate_put_bb_deviation: float = 2.0
    accurate_put_bullish_streak: int = 6
    accurate_put_min_body_ratio: float = 0.25


@dataclass(frozen=True)
class SP500StrategyConfig:
    strategy: str = "sp500_sr_bb_exhaustion"
    mode: str = "balanced"
    call_enabled: bool = True
    call_support_lookback: int = 30
    call_atr_period: int = 14
    call_tolerance_atr_multiplier: float = 0.1
    call_min_lower_wick_ratio: float = 0.50
    call_min_close_pos: float = 0.75
    put_bb_period: int = 10
    put_bb_deviation: float = 2.0
    put_min_bbpct: float = 0.95
    put_bullish_streak: int = 5
    put_min_body_ratio: float = 0.25
    accurate_put_bullish_streak: int = 7


@dataclass(frozen=True)
class AdaptiveFXStrategyConfig:
    strategy: str = "adaptive_fx_sr_momentum"
    support_lookback: int = 80
    resistance_lookback: int = 80
    atr_period: int = 14
    ema_fast_period: int = 9
    ema_slow_period: int = 21
    tolerance_atr_multiplier: float = 0.10
    min_wick_ratio: float = 0.55
    call_close_pos_min: float = 0.78
    put_close_pos_max: float = 0.22
    enable_exhaustion: bool = False
    exhaustion_streak: int = 4
    exhaustion_min_body_ratio: float = 0.42
    enable_momentum: bool = False
    momentum_streak: int = 3
    momentum_min_body_ratio: float = 0.55
    min_atr_ratio: float = 0.0
    max_atr_ratio: float = 0.006


@dataclass(frozen=True)
class StrategyConfig:
    timeframe_sec: int = 60
    expiry_candles: int = 1
    cooldown_after_loss: int = 1
    tie_handling: TieHandling = "loss"
    openai: OpenAIStrategyConfig = field(default_factory=OpenAIStrategyConfig)
    ondo: ONDOStrategyConfig = field(default_factory=ONDOStrategyConfig)
    gbpusd: GBPUSDStrategyConfig = field(default_factory=GBPUSDStrategyConfig)
    eurjpy: EURJPYStrategyConfig = field(default_factory=EURJPYStrategyConfig)
    usdjpy: USDJPYStrategyConfig = field(default_factory=USDJPYStrategyConfig)
    audjpy: AUDJPYStrategyConfig = field(default_factory=AUDJPYStrategyConfig)
    alibaba: AlibabaStrategyConfig = field(default_factory=AlibabaStrategyConfig)
    casinos: CasinosStrategyConfig = field(default_factory=CasinosStrategyConfig)
    ethusd: ETHUSDStrategyConfig = field(default_factory=ETHUSDStrategyConfig)
    sp500: SP500StrategyConfig = field(default_factory=SP500StrategyConfig)
    adaptive_fx: AdaptiveFXStrategyConfig = field(default_factory=AdaptiveFXStrategyConfig)


DEFAULT_STRATEGY_CONFIG = StrategyConfig()
ADAPTIVE_FX_ASSETS = (
    "AUDCHF-OTC",
    "AUDNZD-OTC",
    "AUDUSD-OTC",
    "CADJPY-OTC",
    "EURGBP-OTC",
    "EURNZD-OTC",
    "GBPJPY-OTC",
    "GBPNZD-OTC",
    "NZDCAD-OTC",
    "NZDCHF-OTC",
    "NZDJPY-OTC",
    "NZDUSD-OTC",
    "USDCHF-OTC",
    "USDHKD-OTC",
    "USDSGD-OTC",
)
ASSET_STRATEGIES = {
    "GBPUSD-OTC": "gbpusd_sr_wick_rejection_side_tuned",
    "EURJPY-OTC": "eurjpy_streak_exhaustion",
    "USDJPY-OTC": "streak_exhaustion_reversal",
    "OpenAI-OTC": "openai_selective_momentum",
    "ONDOUSD-OTC": "ondo_opposite_body_rejection",
    "AUDJPY-OTC": "audjpy_hybrid_momentum_sr_put",
    "ALIBABA-OTC": "alibaba_split_sr_wick",
    "CASINOS-OTC": "put_resistance_wick_rejection",
    "ETHUSD-OTC": "eth_sr_wick_rejection",
    "SP500-OTC": "sp500_sr_bb_exhaustion",
    **{asset: "adaptive_fx_sr_momentum" for asset in ADAPTIVE_FX_ASSETS},
}


def calculate_rsi(series: Iterable[float], period: int = 20) -> Optional[float]:
    values = list(series)
    if len(values) <= period:
        return None

    gains: list[float] = []
    losses: list[float] = []
    for idx in range(1, period + 1):
        change = values[idx] - values[idx - 1]
        gains.append(max(change, 0.0))
        losses.append(abs(min(change, 0.0)))

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    for idx in range(period + 1, len(values)):
        change = values[idx] - values[idx - 1]
        avg_gain = ((avg_gain * (period - 1)) + max(change, 0.0)) / period
        avg_loss = ((avg_loss * (period - 1)) + abs(min(change, 0.0))) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def calculate_atr(candles: list[Candle], period: int = 14) -> Optional[float]:
    if len(candles) <= period:
        return None

    ranges: list[float] = []
    previous_close = candles[-period - 1].close
    for candle in candles[-period:]:
        ranges.append(
            max(
                candle.high - candle.low,
                abs(candle.high - previous_close),
                abs(candle.low - previous_close),
            )
        )
        previous_close = candle.close
    return sum(ranges) / period


def calculate_ema(series: Iterable[float], period: int) -> Optional[float]:
    values = list(series)
    if len(values) < period:
        return None
    multiplier = 2 / (period + 1)
    ema_value = values[0]
    for value in values[1:]:
        ema_value = ((value - ema_value) * multiplier) + ema_value
    return ema_value


def calculate_bollinger_bands(
    candles: list[Candle],
    index: int,
    period: int,
    deviation: float,
) -> Optional[tuple[float, float, float]]:
    if period <= 0 or index < 0 or index >= len(candles) or index + 1 < period:
        return None
    closes = [candle.close for candle in candles[index - period + 1 : index + 1]]
    middle = sum(closes) / period
    variance = sum((value - middle) ** 2 for value in closes) / period
    width = (variance**0.5) * deviation
    return middle - width, middle, middle + width


def candle_body_ratio(candle: Candle) -> Optional[float]:
    candle_range = candle.high - candle.low
    if candle_range <= 0:
        return None
    return abs(candle.close - candle.open) / candle_range


def candle_close_position(candle: Candle) -> Optional[float]:
    candle_range = candle.high - candle.low
    if candle_range <= 0:
        return None
    return (candle.close - candle.low) / candle_range


def candle_wick_ratios(candle: Candle) -> Optional[tuple[float, float]]:
    candle_range = candle.high - candle.low
    if candle_range <= 0:
        return None
    upper = (candle.high - max(candle.open, candle.close)) / candle_range
    lower = (min(candle.open, candle.close) - candle.low) / candle_range
    return upper, lower


def is_bullish(candle: Candle) -> bool:
    return candle.close > candle.open


def is_bearish(candle: Candle) -> bool:
    return candle.close < candle.open


def count_latest_bullish_candles(candles: list[Candle], index: int, length: int) -> int:
    if length <= 0 or index < 0 or index >= len(candles):
        return 0
    count = 0
    for candle in reversed(candles[max(0, index - length + 1) : index + 1]):
        if not is_bullish(candle):
            break
        count += 1
    return count


def count_latest_bearish_candles(candles: list[Candle], index: int, length: int) -> int:
    if length <= 0 or index < 0 or index >= len(candles):
        return 0
    count = 0
    for candle in reversed(candles[max(0, index - length + 1) : index + 1]):
        if not is_bearish(candle):
            break
        count += 1
    return count


def highest_high_before_index(candles: list[Candle], index: int, lookback: int) -> Optional[float]:
    if lookback <= 0 or index <= 0 or index > len(candles):
        return None
    window = candles[max(0, index - lookback) : index]
    if len(window) < lookback:
        return None
    return max(candle.high for candle in window)


def lowest_low_before_index(candles: list[Candle], index: int, lookback: int) -> Optional[float]:
    if lookback <= 0 or index <= 0 or index > len(candles):
        return None
    window = candles[max(0, index - lookback) : index]
    if len(window) < lookback:
        return None
    return min(candle.low for candle in window)


def streak_matches(candles: list[Candle], index: int, length: int, direction: Direction) -> bool:
    if length <= 0 or index + 1 < length:
        return False
    window = candles[index - length + 1 : index + 1]
    if direction == "call":
        return all(is_bullish(candle) for candle in window)
    return all(is_bearish(candle) for candle in window)


def image_call_score(candle: Candle) -> float:
    body_ratio = candle_body_ratio(candle) or 0.0
    close_pos = candle_close_position(candle) or 0.5
    wick_ratios = candle_wick_ratios(candle)
    lower_wick_ratio = wick_ratios[1] if wick_ratios else 0.0
    directional_bonus = 1.0 if is_bullish(candle) else 0.0
    return min(
        100.0,
        (
            (body_ratio * 0.45)
            + (close_pos * 0.30)
            + (lower_wick_ratio * 0.15)
            + (directional_bonus * 0.10)
        )
        * 100,
    )


def opposite_block_score(candles: list[Candle], index: int, direction: Direction, lookback: int) -> float:
    best = 0.0
    for candle in candles[max(0, index - lookback) : index]:
        body_ratio = candle_body_ratio(candle) or 0.0
        close_pos = candle_close_position(candle) or 0.5
        if direction == "call" and is_bearish(candle):
            best = max(best, (0.75 * body_ratio + 0.25 * (1 - close_pos)) * 100)
        elif direction == "put" and is_bullish(candle):
            best = max(best, (0.75 * body_ratio + 0.25 * close_pos) * 100)
    return best


def legacy_rsi_ema_momentum(candles: list[Candle], index: int) -> TradeSignal:
    signal = evaluate_signal(candles[: index + 1])
    signal.metrics["legacy_strategy"] = "legacy_rsi_ema_momentum"
    return signal


def strategy_gbpusd_sr_wick_rejection(
    candles: list[Candle],
    index: int,
    config: StrategyConfig = DEFAULT_STRATEGY_CONFIG,
) -> TradeSignal:
    strategy_name = ASSET_STRATEGIES["GBPUSD-OTC"]
    if index < 0 or index >= len(candles):
        return TradeSignal("hold", 0.0, "not_enough_candles", None, {"strategy": strategy_name})

    rule = config.gbpusd
    required = max(rule.support_lookback, rule.resistance_lookback, rule.atr_period + 1)
    candle = candles[index]
    metrics: dict[str, Any] = {"strategy": strategy_name, "close": round(candle.close, 6)}
    if index < required:
        metrics["required_closed_candles"] = required + 1
        return TradeSignal("hold", 0.0, "not_enough_candles", candle.close, metrics)

    candle_range = candle.high - candle.low
    if candle_range <= 0:
        metrics["range"] = round(candle_range, 8)
        return TradeSignal("hold", 0.0, "zero_range_candle", candle.close, metrics)

    atr_value = calculate_atr(candles[: index + 1], rule.atr_period)
    if atr_value is None:
        return TradeSignal("hold", 0.0, "atr_unavailable", candle.close, metrics)

    support_window = candles[index - rule.support_lookback : index]
    resistance_window = candles[index - rule.resistance_lookback : index]
    support = min(item.low for item in support_window)
    resistance = max(item.high for item in resistance_window)
    call_tolerance = atr_value * rule.call_tolerance_atr_multiplier
    put_tolerance = atr_value * rule.tolerance_atr_multiplier
    wick_ratios = candle_wick_ratios(candle)
    close_pos = candle_close_position(candle)
    if wick_ratios is None or close_pos is None:
        return TradeSignal("hold", 0.0, "zero_range_candle", candle.close, metrics)

    upper_wick_ratio, lower_wick_ratio = wick_ratios
    touched_support = candle.low <= support + call_tolerance
    touched_resistance = candle.high >= resistance - put_tolerance
    metrics.update(
        {
            "support": round(support, 6),
            "resistance": round(resistance, 6),
            "call_tolerance": round(call_tolerance, 8),
            "put_tolerance": round(put_tolerance, 8),
            "atr": round(atr_value, 8),
            "upper_wick_ratio": round(upper_wick_ratio, 4),
            "lower_wick_ratio": round(lower_wick_ratio, 4),
            "close_pos": round(close_pos, 4),
            "touched_support": touched_support,
            "touched_resistance": touched_resistance,
        }
    )

    if (
        metrics["touched_support"]
        and lower_wick_ratio >= rule.call_min_wick_ratio
        and close_pos >= rule.call_close_pos_min
    ):
        block_score = opposite_block_score(candles, index, "call", rule.block_opposite_lookback)
        metrics["opposite_block_img_score"] = round(block_score, 2)
        metrics["block_opposite_img_score_min"] = rule.block_opposite_img_score
        if block_score < rule.block_opposite_img_score:
            return TradeSignal(
                "hold",
                0.0,
                "gbpusd_call_opposite_block_score_below_min",
                candle.close,
                metrics,
            )
        strength = (lower_wick_ratio - rule.call_min_wick_ratio) + (close_pos - rule.call_close_pos_min)
        confidence = (
            0.70
            + min(max(strength, 0.0) * 0.22, 0.16)
            + min((block_score - rule.block_opposite_img_score) / 1000, 0.02)
        )
        return TradeSignal(
            "call",
            round(min(confidence, 0.88), 3),
            "gbpusd_call_support_wick_rejection_with_opposite_block",
            candle.close,
            metrics,
        )

    if metrics["touched_resistance"] and upper_wick_ratio >= rule.min_wick_ratio and close_pos <= rule.put_close_pos_max:
        strength = (upper_wick_ratio - rule.min_wick_ratio) + (rule.put_close_pos_max - close_pos)
        confidence = 0.70 + min(max(strength, 0.0) * 0.25, 0.18)
        return TradeSignal(
            "put",
            round(min(confidence, 0.88), 3),
            "gbpusd_put_resistance_wick_rejection",
            candle.close,
            metrics,
        )

    return TradeSignal("hold", 0.0, "gbpusd_no_support_resistance_rejection", candle.close, metrics)


def strategy_eurjpy_streak_exhaustion(
    candles: list[Candle],
    index: int,
    config: StrategyConfig = DEFAULT_STRATEGY_CONFIG,
) -> TradeSignal:
    strategy_name = ASSET_STRATEGIES["EURJPY-OTC"]
    if index < 0 or index >= len(candles):
        return TradeSignal("hold", 0.0, "not_enough_candles", None, {"strategy": strategy_name})

    rule = config.eurjpy
    required = max(rule.atr_period + 1, rule.call_bearish_streak, rule.put_bullish_streak)
    candle = candles[index]
    metrics: dict[str, Any] = {"strategy": strategy_name, "close": round(candle.close, 6)}
    if index + 1 < required:
        metrics["required_closed_candles"] = required
        return TradeSignal("hold", 0.0, "not_enough_candles", candle.close, metrics)

    body_ratio = candle_body_ratio(candle)
    if body_ratio is None:
        return TradeSignal("hold", 0.0, "zero_range_candle", candle.close, metrics)

    atr_value = calculate_atr(candles[: index + 1], rule.atr_period)
    if atr_value is None or candle.close == 0:
        return TradeSignal("hold", 0.0, "atr_unavailable", candle.close, metrics)

    atr_ratio = atr_value / candle.close
    latest_for_call = candles[index - rule.call_bearish_streak + 1 : index + 1]
    latest_for_put = candles[index - rule.put_bullish_streak + 1 : index + 1]
    bearish_streak = len(latest_for_call) == rule.call_bearish_streak and all(is_bearish(item) for item in latest_for_call)
    bullish_streak = len(latest_for_put) == rule.put_bullish_streak and all(is_bullish(item) for item in latest_for_put)
    metrics.update(
        {
            "body_ratio": round(body_ratio, 4),
            "atr": round(atr_value, 8),
            "atr_ratio": round(atr_ratio, 6),
            "bearish_streak": bearish_streak,
            "bullish_streak": bullish_streak,
            "call_bearish_streak": rule.call_bearish_streak,
            "put_bullish_streak": rule.put_bullish_streak,
        }
    )

    if bearish_streak and body_ratio >= rule.call_min_body_ratio and atr_ratio <= rule.max_atr_ratio:
        strength = body_ratio - rule.call_min_body_ratio
        confidence = 0.70 + min(max(strength, 0.0) * 0.25, 0.15)
        return TradeSignal(
            "call",
            round(min(confidence, 0.85), 3),
            "eurjpy_bearish_streak_exhaustion_call",
            candle.close,
            metrics,
        )

    if bullish_streak and body_ratio >= rule.put_min_body_ratio and atr_ratio <= rule.max_atr_ratio:
        strength = body_ratio - rule.put_min_body_ratio
        confidence = 0.70 + min(max(strength, 0.0) * 0.25, 0.15)
        return TradeSignal(
            "put",
            round(min(confidence, 0.85), 3),
            "eurjpy_bullish_streak_exhaustion_put",
            candle.close,
            metrics,
        )

    return TradeSignal("hold", 0.0, "eurjpy_streak_condition_not_met", candle.close, metrics)


def strategy_usdjpy_streak_exhaustion_reversal(
    candles: list[Candle],
    index: int,
    config: StrategyConfig = DEFAULT_STRATEGY_CONFIG,
) -> TradeSignal:
    strategy_name = ASSET_STRATEGIES["USDJPY-OTC"]
    if index < 0 or index >= len(candles):
        return TradeSignal("hold", 0.0, "not_enough_candles", None, {"strategy": strategy_name})

    rule = config.usdjpy
    required = max(rule.call_bearish_streak, rule.put_bullish_streak)
    candle = candles[index]
    metrics: dict[str, Any] = {
        "strategy": strategy_name,
        "mode": rule.mode,
        "close": round(candle.close, 6),
    }
    if index + 1 < required:
        metrics["required_closed_candles"] = required
        return TradeSignal("hold", 0.0, "not_enough_candles", candle.close, metrics)

    body_ratio = candle_body_ratio(candle)
    if body_ratio is None:
        return TradeSignal("hold", 0.0, "zero_range_candle", candle.close, metrics)

    bearish_count = count_latest_bearish_candles(candles, index, rule.call_bearish_streak)
    bullish_count = count_latest_bullish_candles(candles, index, rule.put_bullish_streak)
    bearish_streak = bearish_count >= rule.call_bearish_streak
    bullish_streak = bullish_count >= rule.put_bullish_streak
    metrics.update(
        {
            "body_ratio": round(body_ratio, 4),
            "bearish_streak_count": bearish_count,
            "bullish_streak_count": bullish_count,
            "call_bearish_streak": rule.call_bearish_streak,
            "put_bullish_streak": rule.put_bullish_streak,
            "call_min_body_ratio": rule.call_min_body_ratio,
            "put_min_body_ratio": rule.put_min_body_ratio,
        }
    )

    if bearish_streak and body_ratio >= rule.call_min_body_ratio:
        strength = (bearish_count - rule.call_bearish_streak) * 0.02 + max(body_ratio - rule.call_min_body_ratio, 0.0) * 0.12
        confidence = 0.70 + min(strength, 0.16)
        return TradeSignal(
            "call",
            round(min(confidence, 0.86), 3),
            "usdjpy_call_bearish_streak_exhaustion",
            candle.close,
            metrics,
        )

    if bullish_streak and body_ratio >= rule.put_min_body_ratio:
        strength = (bullish_count - rule.put_bullish_streak) * 0.02 + max(body_ratio - rule.put_min_body_ratio, 0.0) * 0.20
        confidence = 0.70 + min(strength, 0.16)
        return TradeSignal(
            "put",
            round(min(confidence, 0.86), 3),
            "usdjpy_put_bullish_streak_body_exhaustion",
            candle.close,
            metrics,
        )

    return TradeSignal("hold", 0.0, "usdjpy_streak_exhaustion_not_met", candle.close, metrics)


def signal_openai_otc(
    candles: list[Candle],
    index: int,
    config: StrategyConfig = DEFAULT_STRATEGY_CONFIG,
) -> TradeSignal:
    rule = config.openai
    required = max(rule.atr_period + 1, rule.ema_slow_period, rule.bearish_streak, rule.bullish_streak)
    if index < 0 or index >= len(candles):
        return TradeSignal("hold", 0.0, "not_enough_candles", None, {})

    candle = candles[index]
    metrics: dict[str, Any] = {
        "strategy": ASSET_STRATEGIES["OpenAI-OTC"],
        "close": round(candle.close, 6),
    }
    if index + 1 < required:
        metrics["required_closed_candles"] = required
        return TradeSignal("hold", 0.0, "not_enough_candles", candle.close, metrics)

    body_ratio = candle_body_ratio(candle)
    atr_value = calculate_atr(candles[: index + 1], rule.atr_period)
    closes = [item.close for item in candles[: index + 1]]
    ema_fast = calculate_ema(closes, rule.ema_fast_period)
    ema_slow = calculate_ema(closes, rule.ema_slow_period)
    if body_ratio is None:
        return TradeSignal("hold", 0.0, "zero_range_candle", candle.close, metrics)
    if atr_value is None or ema_fast is None or ema_slow is None or candle.close == 0:
        return TradeSignal("hold", 0.0, "indicator_unavailable", candle.close, metrics)

    atr_ratio = atr_value / candle.close
    bullish_streak = streak_matches(candles, index, rule.bullish_streak, "call")
    bearish_streak = streak_matches(candles, index, rule.bearish_streak, "put")
    metrics.update(
        {
            "body_ratio": round(body_ratio, 4),
            "atr": round(atr_value, 8),
            "atr_ratio": round(atr_ratio, 6),
            "ema_fast": round(ema_fast, 6),
            "ema_slow": round(ema_slow, 6),
            "bullish_streak": bullish_streak,
            "bearish_streak": bearish_streak,
            "call_atr_window": f"{rule.call_min_atr_ratio}-{rule.call_max_atr_ratio}",
            "put_atr_window": f"{rule.put_min_atr_ratio}-{rule.put_max_atr_ratio}",
        }
    )

    if (
        bullish_streak
        and body_ratio >= rule.call_min_body_ratio
        and rule.call_min_atr_ratio <= atr_ratio <= rule.call_max_atr_ratio
        and ema_fast > ema_slow
    ):
        strength = (body_ratio - rule.call_min_body_ratio) + ((atr_ratio - rule.call_min_atr_ratio) * 100)
        confidence = 0.70 + min(max(strength, 0.0) * 0.18, 0.18)
        return TradeSignal(
            "call",
            round(min(confidence, 0.88), 3),
            "openai_call_selective_momentum",
            candle.close,
            metrics,
        )

    if (
        bearish_streak
        and body_ratio >= rule.put_min_body_ratio
        and rule.put_min_atr_ratio <= atr_ratio <= rule.put_max_atr_ratio
        and ema_fast < ema_slow
    ):
        strength = (body_ratio - rule.put_min_body_ratio) + ((atr_ratio - rule.put_min_atr_ratio) * 60)
        confidence = 0.70 + min(max(strength, 0.0) * 0.18, 0.18)
        return TradeSignal(
            "put",
            round(min(confidence, 0.88), 3),
            "openai_put_selective_momentum",
            candle.close,
            metrics,
        )

    return TradeSignal("hold", 0.0, "openai_selective_momentum_not_met", candle.close, metrics)


def signal_audjpy_otc(
    candles: list[Candle],
    index: int,
    config: StrategyConfig = DEFAULT_STRATEGY_CONFIG,
) -> TradeSignal:
    rule = config.audjpy
    strategy_name = ASSET_STRATEGIES["AUDJPY-OTC"]
    required = max(rule.resistance_lookback, rule.atr_period + 1, rule.ema_slow_period, rule.call_bullish_streak)
    if index < 0 or index >= len(candles):
        return TradeSignal("hold", 0.0, "not_enough_candles", None, {"strategy": strategy_name})

    candle = candles[index]
    metrics: dict[str, Any] = {"strategy": strategy_name, "close": round(candle.close, 6)}
    if index + 1 < required:
        metrics["required_closed_candles"] = required
        return TradeSignal("hold", 0.0, "not_enough_candles", candle.close, metrics)

    body_ratio = candle_body_ratio(candle)
    close_pos = candle_close_position(candle)
    wick_ratios = candle_wick_ratios(candle)
    atr_value = calculate_atr(candles[: index + 1], rule.atr_period)
    closes = [item.close for item in candles[: index + 1]]
    ema_fast = calculate_ema(closes, rule.ema_fast_period)
    ema_slow = calculate_ema(closes, rule.ema_slow_period)
    if body_ratio is None or close_pos is None or wick_ratios is None:
        return TradeSignal("hold", 0.0, "zero_range_candle", candle.close, metrics)
    if atr_value is None or ema_fast is None or ema_slow is None or candle.close == 0:
        return TradeSignal("hold", 0.0, "indicator_unavailable", candle.close, metrics)

    upper_wick_ratio, lower_wick_ratio = wick_ratios
    atr_ratio = atr_value / candle.close
    resistance_window = candles[index - rule.resistance_lookback : index]
    resistance = max(item.high for item in resistance_window)
    tolerance = atr_value * rule.tolerance_atr_multiplier
    touched_resistance = candle.high >= resistance - tolerance
    call_score = image_call_score(candle)
    bullish_streak = streak_matches(candles, index, rule.call_bullish_streak, "call")
    metrics.update(
        {
            "body_ratio": round(body_ratio, 4),
            "close_pos": round(close_pos, 4),
            "upper_wick_ratio": round(upper_wick_ratio, 4),
            "lower_wick_ratio": round(lower_wick_ratio, 4),
            "atr": round(atr_value, 8),
            "atr_ratio": round(atr_ratio, 6),
            "ema_fast": round(ema_fast, 6),
            "ema_slow": round(ema_slow, 6),
            "resistance": round(resistance, 6),
            "tolerance": round(tolerance, 8),
            "touched_resistance": touched_resistance,
            "img_call_score": round(call_score, 2),
            "bullish_streak": bullish_streak,
        }
    )

    if bullish_streak and body_ratio >= rule.call_min_body_ratio and atr_ratio >= rule.call_min_atr_ratio and ema_fast > ema_slow:
        strength = (body_ratio - rule.call_min_body_ratio) + ((atr_ratio - rule.call_min_atr_ratio) * 100)
        confidence = 0.70 + min(max(strength, 0.0) * 0.18, 0.18)
        return TradeSignal(
            "call",
            round(min(confidence, 0.88), 3),
            "audjpy_call_momentum_continuation",
            candle.close,
            metrics,
        )

    if (
        touched_resistance
        and upper_wick_ratio >= rule.put_min_upper_wick_ratio
        and close_pos <= rule.put_max_close_pos
        and call_score < rule.block_if_img_call_score_gte
    ):
        strength = (upper_wick_ratio - rule.put_min_upper_wick_ratio) + (rule.put_max_close_pos - close_pos)
        confidence = 0.70 + min(max(strength, 0.0) * 0.24, 0.18)
        return TradeSignal(
            "put",
            round(min(confidence, 0.88), 3),
            "audjpy_put_resistance_wick_rejection",
            candle.close,
            metrics,
        )

    return TradeSignal("hold", 0.0, "audjpy_hybrid_condition_not_met", candle.close, metrics)


def signal_alibaba_otc(
    candles: list[Candle],
    index: int,
    config: StrategyConfig = DEFAULT_STRATEGY_CONFIG,
) -> TradeSignal:
    rule = config.alibaba
    strategy_name = ASSET_STRATEGIES["ALIBABA-OTC"]
    required = max(rule.support_lookback, rule.resistance_lookback, rule.atr_period + 1)
    if index < 0 or index >= len(candles):
        return TradeSignal("hold", 0.0, "not_enough_candles", None, {"strategy": strategy_name})

    candle = candles[index]
    metrics: dict[str, Any] = {"strategy": strategy_name, "close": round(candle.close, 6)}
    if index + 1 < required:
        metrics["required_closed_candles"] = required
        return TradeSignal("hold", 0.0, "not_enough_candles", candle.close, metrics)

    close_pos = candle_close_position(candle)
    wick_ratios = candle_wick_ratios(candle)
    atr_value = calculate_atr(candles[: index + 1], rule.atr_period)
    if close_pos is None or wick_ratios is None:
        return TradeSignal("hold", 0.0, "zero_range_candle", candle.close, metrics)
    if atr_value is None:
        return TradeSignal("hold", 0.0, "atr_unavailable", candle.close, metrics)

    upper_wick_ratio, lower_wick_ratio = wick_ratios
    support_window = candles[index - rule.support_lookback : index]
    resistance_window = candles[index - rule.resistance_lookback : index]
    support = min(item.low for item in support_window)
    resistance = max(item.high for item in resistance_window)
    call_tolerance = atr_value * rule.call_tolerance_atr_multiplier
    put_tolerance = atr_value * rule.put_tolerance_atr_multiplier
    touched_support = candle.low <= support + call_tolerance
    touched_resistance = candle.high >= resistance - put_tolerance
    call_score = image_call_score(candle)
    metrics.update(
        {
            "close_pos": round(close_pos, 4),
            "upper_wick_ratio": round(upper_wick_ratio, 4),
            "lower_wick_ratio": round(lower_wick_ratio, 4),
            "atr": round(atr_value, 8),
            "support": round(support, 6),
            "resistance": round(resistance, 6),
            "call_tolerance": round(call_tolerance, 8),
            "put_tolerance": round(put_tolerance, 8),
            "touched_support": touched_support,
            "touched_resistance": touched_resistance,
            "img_call_score": round(call_score, 2),
        }
    )

    if touched_support and lower_wick_ratio >= rule.call_min_lower_wick_ratio and close_pos >= rule.call_min_close_pos:
        strength = (lower_wick_ratio - rule.call_min_lower_wick_ratio) + (close_pos - rule.call_min_close_pos)
        confidence = 0.70 + min(max(strength, 0.0) * 0.24, 0.18)
        return TradeSignal(
            "call",
            round(min(confidence, 0.88), 3),
            "alibaba_call_support_wick_rejection",
            candle.close,
            metrics,
        )

    if (
        touched_resistance
        and upper_wick_ratio >= rule.put_min_upper_wick_ratio
        and close_pos <= rule.put_max_close_pos
        and call_score < rule.block_if_img_call_score_gte
    ):
        strength = (upper_wick_ratio - rule.put_min_upper_wick_ratio) + (rule.put_max_close_pos - close_pos)
        confidence = 0.70 + min(max(strength, 0.0) * 0.24, 0.18)
        return TradeSignal(
            "put",
            round(min(confidence, 0.88), 3),
            "alibaba_put_resistance_wick_rejection",
            candle.close,
            metrics,
        )

    return TradeSignal("hold", 0.0, "alibaba_sr_wick_condition_not_met", candle.close, metrics)


def strategy_casinos_put_resistance_wick_rejection(
    candles: list[Candle],
    index: int,
    config: StrategyConfig = DEFAULT_STRATEGY_CONFIG,
) -> TradeSignal:
    rule = config.casinos
    strategy_name = ASSET_STRATEGIES["CASINOS-OTC"]
    required = max(rule.resistance_lookback, rule.atr_period + 1)
    if index < 0 or index >= len(candles):
        return TradeSignal("hold", 0.0, "not_enough_candles", None, {"strategy": strategy_name})

    candle = candles[index]
    metrics: dict[str, Any] = {
        "strategy": strategy_name,
        "mode": rule.mode,
        "close": round(candle.close, 6),
        "call_enabled": rule.call_enabled,
    }
    if index + 1 < required:
        metrics["required_closed_candles"] = required
        return TradeSignal("hold", 0.0, "not_enough_candles", candle.close, metrics)

    close_pos = candle_close_position(candle)
    wick_ratios = candle_wick_ratios(candle)
    atr_value = calculate_atr(candles[: index + 1], rule.atr_period)
    resistance = highest_high_before_index(candles, index, rule.resistance_lookback)
    if close_pos is None or wick_ratios is None:
        return TradeSignal("hold", 0.0, "zero_range_candle", candle.close, metrics)
    if atr_value is None or resistance is None:
        return TradeSignal("hold", 0.0, "indicator_unavailable", candle.close, metrics)

    upper_wick_ratio, lower_wick_ratio = wick_ratios
    tolerance = atr_value * rule.tolerance_atr_multiplier
    touched_resistance = candle.high >= resistance - tolerance
    metrics.update(
        {
            "close_pos": round(close_pos, 4),
            "upper_wick_ratio": round(upper_wick_ratio, 4),
            "lower_wick_ratio": round(lower_wick_ratio, 4),
            "atr": round(atr_value, 8),
            "resistance": round(resistance, 6),
            "tolerance": round(tolerance, 8),
            "touched_resistance": touched_resistance,
            "resistance_lookback": rule.resistance_lookback,
            "min_upper_wick_ratio": rule.min_upper_wick_ratio,
            "max_close_pos": rule.max_close_pos,
        }
    )

    if touched_resistance and upper_wick_ratio >= rule.min_upper_wick_ratio and close_pos <= rule.max_close_pos:
        strength = (upper_wick_ratio - rule.min_upper_wick_ratio) + (rule.max_close_pos - close_pos)
        confidence = 0.70 + min(max(strength, 0.0) * 0.24, 0.18)
        return TradeSignal(
            "put",
            round(min(confidence, 0.88), 3),
            "casinos_put_resistance_wick_rejection",
            candle.close,
            metrics,
        )

    if not rule.call_enabled:
        metrics["call_disabled"] = True
    return TradeSignal("hold", 0.0, "casinos_put_rejection_not_met", candle.close, metrics)


def strategy_eth_sr_wick_rejection(
    candles: list[Candle],
    index: int,
    config: StrategyConfig = DEFAULT_STRATEGY_CONFIG,
) -> TradeSignal:
    rule = config.ethusd
    strategy_name = ASSET_STRATEGIES["ETHUSD-OTC"]
    required = max(rule.call_support_lookback, rule.put_resistance_lookback, rule.call_atr_period + 1, rule.put_atr_period + 1)
    if index < 0 or index >= len(candles):
        return TradeSignal("hold", 0.0, "not_enough_candles", None, {"strategy": strategy_name})

    candle = candles[index]
    metrics: dict[str, Any] = {"strategy": strategy_name, "mode": rule.mode, "close": round(candle.close, 6)}
    if index + 1 < required:
        metrics["required_closed_candles"] = required
        return TradeSignal("hold", 0.0, "not_enough_candles", candle.close, metrics)

    close_pos = candle_close_position(candle)
    wick_ratios = candle_wick_ratios(candle)
    if close_pos is None or wick_ratios is None:
        return TradeSignal("hold", 0.0, "zero_range_candle", candle.close, metrics)

    call_atr = calculate_atr(candles[: index + 1], rule.call_atr_period)
    put_atr = calculate_atr(candles[: index + 1], rule.put_atr_period)
    support = lowest_low_before_index(candles, index, rule.call_support_lookback)
    resistance = highest_high_before_index(candles, index, rule.put_resistance_lookback)
    if call_atr is None or put_atr is None or support is None or resistance is None:
        return TradeSignal("hold", 0.0, "indicator_unavailable", candle.close, metrics)

    upper_wick_ratio, lower_wick_ratio = wick_ratios
    call_tolerance = call_atr * rule.call_tolerance_atr_multiplier
    put_tolerance = put_atr * rule.put_tolerance_atr_multiplier
    touched_support = candle.low <= support + call_tolerance
    touched_resistance = candle.high >= resistance - put_tolerance
    metrics.update(
        {
            "close_pos": round(close_pos, 4),
            "upper_wick_ratio": round(upper_wick_ratio, 4),
            "lower_wick_ratio": round(lower_wick_ratio, 4),
            "support": round(support, 6),
            "resistance": round(resistance, 6),
            "call_atr": round(call_atr, 8),
            "put_atr": round(put_atr, 8),
            "call_tolerance": round(call_tolerance, 8),
            "put_tolerance": round(put_tolerance, 8),
            "touched_support": touched_support,
            "touched_resistance": touched_resistance,
        }
    )

    if touched_support and lower_wick_ratio >= rule.call_min_lower_wick_ratio and close_pos >= rule.call_min_close_pos:
        strength = (lower_wick_ratio - rule.call_min_lower_wick_ratio) + (close_pos - rule.call_min_close_pos)
        confidence = 0.70 + min(max(strength, 0.0) * 0.22, 0.18)
        return TradeSignal(
            "call",
            round(min(confidence, 0.88), 3),
            "eth_call_support_wick_rejection",
            candle.close,
            metrics,
        )

    if touched_resistance and upper_wick_ratio >= rule.put_min_upper_wick_ratio and close_pos <= rule.put_max_close_pos:
        strength = (upper_wick_ratio - rule.put_min_upper_wick_ratio) + (rule.put_max_close_pos - close_pos)
        confidence = 0.70 + min(max(strength, 0.0) * 0.22, 0.18)
        return TradeSignal(
            "put",
            round(min(confidence, 0.88), 3),
            "eth_put_resistance_wick_rejection",
            candle.close,
            metrics,
        )

    return TradeSignal("hold", 0.0, "eth_sr_wick_rejection_not_met", candle.close, metrics)


def strategy_eth_accurate_mode(
    candles: list[Candle],
    index: int,
    config: StrategyConfig = DEFAULT_STRATEGY_CONFIG,
) -> TradeSignal:
    rule = config.ethusd
    balanced = strategy_eth_sr_wick_rejection(candles, index, config)
    if balanced.action == "call":
        min_lower = 0.40
        if float(balanced.metrics.get("lower_wick_ratio", 0.0)) >= min_lower:
            balanced.metrics["strategy"] = "eth_accurate_mode"
            balanced.metrics["mode"] = "accurate"
            return TradeSignal(balanced.action, balanced.confidence, balanced.reason, balanced.close_price, balanced.metrics)

    strategy_name = "eth_accurate_mode"
    if index < 0 or index >= len(candles):
        return TradeSignal("hold", 0.0, "not_enough_candles", None, {"strategy": strategy_name, "mode": "accurate"})
    candle = candles[index]
    required = max(rule.accurate_put_bb_period, rule.accurate_put_bullish_streak)
    metrics: dict[str, Any] = {"strategy": strategy_name, "mode": "accurate", "close": round(candle.close, 6)}
    if index + 1 < required:
        metrics["required_closed_candles"] = required
        return TradeSignal("hold", 0.0, "not_enough_candles", candle.close, metrics)

    bands = calculate_bollinger_bands(candles, index, rule.accurate_put_bb_period, rule.accurate_put_bb_deviation)
    body_ratio = candle_body_ratio(candle)
    bullish_count = count_latest_bullish_candles(candles, index, rule.accurate_put_bullish_streak)
    if bands is None or body_ratio is None:
        return TradeSignal("hold", 0.0, "indicator_unavailable", candle.close, metrics)
    bb_lower, bb_middle, bb_upper = bands
    metrics.update(
        {
            "body_ratio": round(body_ratio, 4),
            "bb_lower": round(bb_lower, 6),
            "bb_middle": round(bb_middle, 6),
            "bb_upper": round(bb_upper, 6),
            "bullish_streak_count": bullish_count,
        }
    )
    if candle.close >= bb_upper and bullish_count >= rule.accurate_put_bullish_streak and body_ratio >= rule.accurate_put_min_body_ratio:
        confidence = 0.72 + min(max(body_ratio - rule.accurate_put_min_body_ratio, 0.0) * 0.20, 0.14)
        return TradeSignal("put", round(min(confidence, 0.88), 3), "eth_put_bb_bullish_exhaustion", candle.close, metrics)
    return TradeSignal("hold", 0.0, "eth_accurate_condition_not_met", candle.close, metrics)


def strategy_sp500_sr_bb_exhaustion(
    candles: list[Candle],
    index: int,
    config: StrategyConfig = DEFAULT_STRATEGY_CONFIG,
) -> TradeSignal:
    rule = config.sp500
    strategy_name = ASSET_STRATEGIES["SP500-OTC"]
    required = max(rule.call_support_lookback, rule.call_atr_period + 1, rule.put_bb_period, rule.put_bullish_streak)
    if index < 0 or index >= len(candles):
        return TradeSignal("hold", 0.0, "not_enough_candles", None, {"strategy": strategy_name})

    candle = candles[index]
    metrics: dict[str, Any] = {"strategy": strategy_name, "mode": rule.mode, "close": round(candle.close, 6)}
    if index + 1 < required:
        metrics["required_closed_candles"] = required
        return TradeSignal("hold", 0.0, "not_enough_candles", candle.close, metrics)

    close_pos = candle_close_position(candle)
    body_ratio = candle_body_ratio(candle)
    wick_ratios = candle_wick_ratios(candle)
    atr_value = calculate_atr(candles[: index + 1], rule.call_atr_period)
    support = lowest_low_before_index(candles, index, rule.call_support_lookback)
    bands = calculate_bollinger_bands(candles, index, rule.put_bb_period, rule.put_bb_deviation)
    if close_pos is None or body_ratio is None or wick_ratios is None:
        return TradeSignal("hold", 0.0, "zero_range_candle", candle.close, metrics)
    if atr_value is None or support is None or bands is None:
        return TradeSignal("hold", 0.0, "indicator_unavailable", candle.close, metrics)

    upper_wick_ratio, lower_wick_ratio = wick_ratios
    bb_lower, bb_middle, bb_upper = bands
    bb_range = bb_upper - bb_lower
    bb_percent = 0.5 if bb_range <= 0 else (candle.close - bb_lower) / bb_range
    call_tolerance = atr_value * rule.call_tolerance_atr_multiplier
    touched_support = candle.low <= support + call_tolerance
    bullish_count = count_latest_bullish_candles(candles, index, rule.put_bullish_streak)
    metrics.update(
        {
            "close_pos": round(close_pos, 4),
            "body_ratio": round(body_ratio, 4),
            "upper_wick_ratio": round(upper_wick_ratio, 4),
            "lower_wick_ratio": round(lower_wick_ratio, 4),
            "atr": round(atr_value, 8),
            "support": round(support, 6),
            "call_tolerance": round(call_tolerance, 8),
            "touched_support": touched_support,
            "bb_lower": round(bb_lower, 6),
            "bb_middle": round(bb_middle, 6),
            "bb_upper": round(bb_upper, 6),
            "bb_percent": round(bb_percent, 4),
            "bullish_streak_count": bullish_count,
        }
    )

    if rule.call_enabled and touched_support and lower_wick_ratio >= rule.call_min_lower_wick_ratio and close_pos >= rule.call_min_close_pos:
        strength = (lower_wick_ratio - rule.call_min_lower_wick_ratio) + (close_pos - rule.call_min_close_pos)
        confidence = 0.70 + min(max(strength, 0.0) * 0.22, 0.18)
        return TradeSignal("call", round(min(confidence, 0.88), 3), "sp500_call_support_wick_rejection", candle.close, metrics)

    if (
        (bb_percent >= rule.put_min_bbpct or candle.close >= bb_upper)
        and bullish_count >= rule.put_bullish_streak
        and body_ratio >= rule.put_min_body_ratio
    ):
        strength = max(bb_percent - rule.put_min_bbpct, 0.0) + max(body_ratio - rule.put_min_body_ratio, 0.0)
        confidence = 0.70 + min(strength * 0.20, 0.18)
        return TradeSignal("put", round(min(confidence, 0.88), 3), "sp500_put_bb_bullish_exhaustion", candle.close, metrics)

    return TradeSignal("hold", 0.0, "sp500_sr_bb_condition_not_met", candle.close, metrics)


def strategy_sp500_accurate_put_only(
    candles: list[Candle],
    index: int,
    config: StrategyConfig = DEFAULT_STRATEGY_CONFIG,
) -> TradeSignal:
    rule = config.sp500
    strategy_name = "sp500_accurate_put_only"
    if index < 0 or index >= len(candles):
        return TradeSignal("hold", 0.0, "not_enough_candles", None, {"strategy": strategy_name, "mode": "accurate"})
    candle = candles[index]
    if index + 1 < rule.accurate_put_bullish_streak:
        return TradeSignal(
            "hold",
            0.0,
            "not_enough_candles",
            candle.close,
            {"strategy": strategy_name, "mode": "accurate", "required_closed_candles": rule.accurate_put_bullish_streak},
        )
    bullish_count = count_latest_bullish_candles(candles, index, rule.accurate_put_bullish_streak)
    metrics = {
        "strategy": strategy_name,
        "mode": "accurate",
        "close": round(candle.close, 6),
        "bullish_streak_count": bullish_count,
    }
    if bullish_count >= rule.accurate_put_bullish_streak:
        return TradeSignal("put", 0.74, "sp500_accurate_put_bullish_streak", candle.close, metrics)
    return TradeSignal("hold", 0.0, "sp500_accurate_condition_not_met", candle.close, metrics)


def strategy_adaptive_fx_sr_momentum(
    asset: str,
    candles: list[Candle],
    index: int,
    config: StrategyConfig = DEFAULT_STRATEGY_CONFIG,
) -> TradeSignal:
    rule = config.adaptive_fx
    strategy_name = ASSET_STRATEGIES[asset]
    required = max(
        rule.support_lookback,
        rule.resistance_lookback,
        rule.atr_period + 1,
        rule.ema_slow_period,
        rule.exhaustion_streak if rule.enable_exhaustion else 0,
        rule.momentum_streak if rule.enable_momentum else 0,
    )
    if index < 0 or index >= len(candles):
        return TradeSignal("hold", 0.0, "not_enough_candles", None, {"strategy": strategy_name})

    candle = candles[index]
    metrics: dict[str, Any] = {
        "strategy": strategy_name,
        "asset": asset,
        "close": round(candle.close, 6),
    }
    if index + 1 < required:
        metrics["required_closed_candles"] = required
        return TradeSignal("hold", 0.0, "not_enough_candles", candle.close, metrics)

    close_pos = candle_close_position(candle)
    body_ratio = candle_body_ratio(candle)
    wick_ratios = candle_wick_ratios(candle)
    atr_value = calculate_atr(candles[: index + 1], rule.atr_period)
    support = lowest_low_before_index(candles, index, rule.support_lookback)
    resistance = highest_high_before_index(candles, index, rule.resistance_lookback)
    closes = [item.close for item in candles[: index + 1]]
    ema_fast = calculate_ema(closes, rule.ema_fast_period)
    ema_slow = calculate_ema(closes, rule.ema_slow_period)
    if close_pos is None or body_ratio is None or wick_ratios is None:
        return TradeSignal("hold", 0.0, "zero_range_candle", candle.close, metrics)
    if atr_value is None or support is None or resistance is None or ema_fast is None or ema_slow is None:
        return TradeSignal("hold", 0.0, "indicator_unavailable", candle.close, metrics)

    atr_ratio = atr_value / candle.close if candle.close else 0.0
    upper_wick_ratio, lower_wick_ratio = wick_ratios
    tolerance = atr_value * rule.tolerance_atr_multiplier
    touched_support = candle.low <= support + tolerance
    touched_resistance = candle.high >= resistance - tolerance
    bullish_count = count_latest_bullish_candles(candles, index, max(rule.exhaustion_streak, rule.momentum_streak))
    bearish_count = count_latest_bearish_candles(candles, index, max(rule.exhaustion_streak, rule.momentum_streak))
    ema_trend = "up" if ema_fast > ema_slow else "down" if ema_fast < ema_slow else "flat"
    metrics.update(
        {
            "close_pos": round(close_pos, 4),
            "body_ratio": round(body_ratio, 4),
            "upper_wick_ratio": round(upper_wick_ratio, 4),
            "lower_wick_ratio": round(lower_wick_ratio, 4),
            "atr": round(atr_value, 8),
            "atr_ratio": round(atr_ratio, 8),
            "support": round(support, 6),
            "resistance": round(resistance, 6),
            "tolerance": round(tolerance, 8),
            "touched_support": touched_support,
            "touched_resistance": touched_resistance,
            "bullish_streak_count": bullish_count,
            "bearish_streak_count": bearish_count,
            "ema_fast": round(ema_fast, 6),
            "ema_slow": round(ema_slow, 6),
            "ema_trend": ema_trend,
        }
    )

    if rule.max_atr_ratio > 0 and atr_ratio > rule.max_atr_ratio:
        return TradeSignal("hold", 0.0, "adaptive_fx_atr_too_hot", candle.close, metrics)
    if rule.min_atr_ratio > 0 and atr_ratio < rule.min_atr_ratio:
        return TradeSignal("hold", 0.0, "adaptive_fx_atr_too_quiet", candle.close, metrics)

    if touched_support and lower_wick_ratio >= rule.min_wick_ratio and close_pos >= rule.call_close_pos_min:
        strength = (lower_wick_ratio - rule.min_wick_ratio) + (close_pos - rule.call_close_pos_min)
        confidence = 0.70 + min(max(strength, 0.0) * 0.20, 0.17)
        return TradeSignal(
            "call",
            round(min(confidence, 0.87), 3),
            "adaptive_fx_call_support_wick_rejection",
            candle.close,
            metrics,
        )

    if touched_resistance and upper_wick_ratio >= rule.min_wick_ratio and close_pos <= rule.put_close_pos_max:
        strength = (upper_wick_ratio - rule.min_wick_ratio) + (rule.put_close_pos_max - close_pos)
        confidence = 0.70 + min(max(strength, 0.0) * 0.20, 0.17)
        return TradeSignal(
            "put",
            round(min(confidence, 0.87), 3),
            "adaptive_fx_put_resistance_wick_rejection",
            candle.close,
            metrics,
        )

    if (
        rule.enable_exhaustion
        and bearish_count >= rule.exhaustion_streak
        and body_ratio >= rule.exhaustion_min_body_ratio
        and close_pos <= rule.put_close_pos_max
    ):
        strength = (bearish_count - rule.exhaustion_streak) * 0.03 + body_ratio - rule.exhaustion_min_body_ratio
        confidence = 0.69 + min(max(strength, 0.0) * 0.18, 0.15)
        return TradeSignal(
            "call",
            round(min(confidence, 0.84), 3),
            "adaptive_fx_call_bearish_streak_exhaustion",
            candle.close,
            metrics,
        )

    if (
        rule.enable_exhaustion
        and bullish_count >= rule.exhaustion_streak
        and body_ratio >= rule.exhaustion_min_body_ratio
        and close_pos >= rule.call_close_pos_min
    ):
        strength = (bullish_count - rule.exhaustion_streak) * 0.03 + body_ratio - rule.exhaustion_min_body_ratio
        confidence = 0.69 + min(max(strength, 0.0) * 0.18, 0.15)
        return TradeSignal(
            "put",
            round(min(confidence, 0.84), 3),
            "adaptive_fx_put_bullish_streak_exhaustion",
            candle.close,
            metrics,
        )

    if (
        rule.enable_momentum
        and bullish_count >= rule.momentum_streak
        and body_ratio >= rule.momentum_min_body_ratio
        and close_pos >= rule.call_close_pos_min
        and ema_fast > ema_slow
    ):
        strength = (bullish_count - rule.momentum_streak) * 0.02 + body_ratio - rule.momentum_min_body_ratio
        confidence = 0.70 + min(max(strength, 0.0) * 0.16, 0.14)
        return TradeSignal(
            "call",
            round(min(confidence, 0.84), 3),
            "adaptive_fx_call_ema_momentum",
            candle.close,
            metrics,
        )

    if (
        rule.enable_momentum
        and bearish_count >= rule.momentum_streak
        and body_ratio >= rule.momentum_min_body_ratio
        and close_pos <= rule.put_close_pos_max
        and ema_fast < ema_slow
    ):
        strength = (bearish_count - rule.momentum_streak) * 0.02 + body_ratio - rule.momentum_min_body_ratio
        confidence = 0.70 + min(max(strength, 0.0) * 0.16, 0.14)
        return TradeSignal(
            "put",
            round(min(confidence, 0.84), 3),
            "adaptive_fx_put_ema_momentum",
            candle.close,
            metrics,
        )

    return TradeSignal("hold", 0.0, "adaptive_fx_condition_not_met", candle.close, metrics)


def signal_ondousd_otc(
    candles: list[Candle],
    index: int,
    config: StrategyConfig = DEFAULT_STRATEGY_CONFIG,
) -> TradeSignal:
    if index < 0 or index >= len(candles):
        return TradeSignal("hold", 0.0, "not_enough_candles", None, {})

    candle = candles[index]
    candle_range = candle.high - candle.low
    metrics: dict[str, Any] = {
        "strategy": ASSET_STRATEGIES["ONDOUSD-OTC"],
        "range": round(candle_range, 8),
        "close": round(candle.close, 6),
    }
    if candle_range <= 0:
        return TradeSignal("hold", 0.0, "zero_range_candle", candle.close, metrics)

    close_pos = candle_close_position(candle)
    body_ratio = candle_body_ratio(candle)
    if close_pos is None or body_ratio is None:
        return TradeSignal("hold", 0.0, "zero_range_candle", candle.close, metrics)
    metrics.update(
        {
            "close_pos": round(close_pos, 4),
            "body_ratio": round(body_ratio, 4),
            "call_close_pos_min": config.ondo.call_close_pos_min,
            "put_close_pos_max": config.ondo.put_close_pos_max,
            "min_body_ratio": config.ondo.min_body_ratio,
        }
    )

    if is_bearish(candle) and close_pos >= config.ondo.call_close_pos_min and body_ratio >= config.ondo.min_body_ratio:
        strength = (close_pos - config.ondo.call_close_pos_min) + body_ratio
        confidence = 0.70 + min(strength * 0.20, 0.20)
        return TradeSignal(
            "call",
            round(min(confidence, 0.90), 3),
            "ondo_bearish_body_high_close_rejection_call",
            candle.close,
            metrics,
        )

    if is_bullish(candle) and close_pos <= config.ondo.put_close_pos_max and body_ratio >= config.ondo.min_body_ratio:
        strength = (config.ondo.put_close_pos_max - close_pos) + body_ratio
        confidence = 0.70 + min(strength * 0.20, 0.20)
        return TradeSignal(
            "put",
            round(min(confidence, 0.90), 3),
            "ondo_bullish_body_low_close_rejection_put",
            candle.close,
            metrics,
        )

    return TradeSignal("hold", 0.0, "ondo_opposite_body_rejection_not_met", candle.close, metrics)


def get_signal(
    asset: str,
    candles: list[Candle],
    index: Optional[int] = None,
    *,
    config: StrategyConfig = DEFAULT_STRATEGY_CONFIG,
    default_strategy: Optional[str] = None,
) -> TradeSignal:
    if not candles:
        return TradeSignal("hold", 0.0, "not_enough_candles", None, {})

    signal_index = len(candles) - 1 if index is None else index
    if signal_index < 0 or signal_index >= len(candles):
        return TradeSignal("hold", 0.0, "not_enough_candles", None, {})

    if asset == "GBPUSD-OTC":
        return strategy_gbpusd_sr_wick_rejection(candles, signal_index, config)
    if asset == "EURJPY-OTC":
        return strategy_eurjpy_streak_exhaustion(candles, signal_index, config)
    if asset == "USDJPY-OTC":
        return strategy_usdjpy_streak_exhaustion_reversal(candles, signal_index, config)
    if asset == "OpenAI-OTC":
        return signal_openai_otc(candles, signal_index, config)
    if asset == "ONDOUSD-OTC":
        return signal_ondousd_otc(candles, signal_index, config)
    if asset == "AUDJPY-OTC":
        return signal_audjpy_otc(candles, signal_index, config)
    if asset == "ALIBABA-OTC":
        return signal_alibaba_otc(candles, signal_index, config)
    if asset == "CASINOS-OTC":
        return strategy_casinos_put_resistance_wick_rejection(candles, signal_index, config)
    if asset == "ETHUSD-OTC":
        if config.ethusd.mode == "accurate":
            return strategy_eth_accurate_mode(candles, signal_index, config)
        return strategy_eth_sr_wick_rejection(candles, signal_index, config)
    if asset == "SP500-OTC":
        if config.sp500.mode == "accurate":
            return strategy_sp500_accurate_put_only(candles, signal_index, config)
        return strategy_sp500_sr_bb_exhaustion(candles, signal_index, config)
    if asset in ADAPTIVE_FX_ASSETS:
        return strategy_adaptive_fx_sr_momentum(asset, candles, signal_index, config)

    if default_strategy == "legacy_rsi_ema_momentum":
        return legacy_rsi_ema_momentum(candles, signal_index)

    return TradeSignal("hold", 0.0, "asset_strategy_not_configured", candles[signal_index].close, {})


def is_asset_specific_signal(signal: TradeSignal) -> bool:
    return str(signal.metrics.get("strategy") or "") in set(ASSET_STRATEGIES.values())


def strategy_name_for_asset(asset: str, default_strategy: Optional[str] = None) -> str:
    if asset in ASSET_STRATEGIES:
        return ASSET_STRATEGIES[asset]
    if default_strategy == "legacy_rsi_ema_momentum":
        return "legacy_rsi_ema_momentum"
    return "no_trade"


def _trade_result(direction: Direction, next_candle: Candle, tie_handling: TieHandling) -> Optional[str]:
    if next_candle.close == next_candle.open:
        return None if tie_handling == "skip" else "loss"
    if direction == "call":
        return "win" if next_candle.close > next_candle.open else "loss"
    return "win" if next_candle.close < next_candle.open else "loss"


def _empty_summary(label: str, total_candles: int) -> dict[str, Any]:
    return {
        "label": label,
        "total_candles_tested": total_candles,
        "total_trades": 0,
        "wins": 0,
        "losses": 0,
        "ties": 0,
        "win_rate": 0.0,
        "trade_frequency_pct": 0.0,
        "call_count": 0,
        "put_count": 0,
        "call_win_rate": 0.0,
        "put_win_rate": 0.0,
        "max_losing_streak": 0,
        "max_winning_streak": 0,
    }


def _summarize_trades(label: str, total_candles: int, trades: list[dict[str, Any]]) -> dict[str, Any]:
    if not trades:
        return _empty_summary(label, total_candles)

    wins = sum(1 for trade in trades if trade["result"] == "win")
    losses = sum(1 for trade in trades if trade["result"] == "loss")
    ties = sum(1 for trade in trades if trade.get("tie"))
    calls = [trade for trade in trades if trade["direction"] == "call"]
    puts = [trade for trade in trades if trade["direction"] == "put"]
    call_wins = sum(1 for trade in calls if trade["result"] == "win")
    put_wins = sum(1 for trade in puts if trade["result"] == "win")

    max_winning_streak = 0
    max_losing_streak = 0
    current_wins = 0
    current_losses = 0
    for trade in trades:
        if trade["result"] == "win":
            current_wins += 1
            current_losses = 0
        else:
            current_losses += 1
            current_wins = 0
        max_winning_streak = max(max_winning_streak, current_wins)
        max_losing_streak = max(max_losing_streak, current_losses)

    return {
        "label": label,
        "total_candles_tested": total_candles,
        "total_trades": len(trades),
        "wins": wins,
        "losses": losses,
        "ties": ties,
        "win_rate": round((wins / len(trades)) * 100, 2),
        "trade_frequency_pct": round((len(trades) / total_candles) * 100, 2) if total_candles else 0.0,
        "call_count": len(calls),
        "put_count": len(puts),
        "call_win_rate": round((call_wins / len(calls)) * 100, 2) if calls else 0.0,
        "put_win_rate": round((put_wins / len(puts)) * 100, 2) if puts else 0.0,
        "max_losing_streak": max_losing_streak,
        "max_winning_streak": max_winning_streak,
    }


def backtest_asset(
    asset: str,
    candles: list[Candle],
    config: StrategyConfig = DEFAULT_STRATEGY_CONFIG,
    *,
    start_index: int = 0,
    end_index: Optional[int] = None,
    default_strategy: Optional[str] = None,
) -> dict[str, Any]:
    end = min(len(candles) - config.expiry_candles, end_index if end_index is not None else len(candles))
    start = max(0, start_index)
    trades: list[dict[str, Any]] = []
    cooldown_left = 0

    for index in range(start, end):
        if cooldown_left > 0:
            cooldown_left -= 1
            continue

        signal = get_signal(asset, candles, index, config=config, default_strategy=default_strategy)
        if signal.action not in {"call", "put"}:
            continue

        next_candle = candles[index + config.expiry_candles]
        tie = next_candle.close == next_candle.open
        result = _trade_result(signal.action, next_candle, config.tie_handling)
        if result is None:
            continue

        trades.append(
            {
                "asset": asset,
                "signal_index": index,
                "signal_time": candles[index].timestamp,
                "entry_index": index + config.expiry_candles,
                "entry_time": next_candle.timestamp,
                "direction": signal.action,
                "result": result,
                "tie": tie,
                "confidence": signal.confidence,
                "reason": signal.reason,
            }
        )
        if result == "loss":
            cooldown_left = config.cooldown_after_loss

    total = max(0, end - start)
    train_end = start + int(total * 0.60)
    validation_end = start + int(total * 0.80)

    def segment(label: str, left: int, right: int) -> dict[str, Any]:
        scoped = [trade for trade in trades if left <= int(trade["signal_index"]) < right]
        return _summarize_trades(label, max(0, right - left), scoped)

    result = {
        "asset": asset,
        "strategy_name": strategy_name_for_asset(asset, default_strategy),
        "mode": getattr(config, asset.split("-")[0].lower(), None).mode
        if hasattr(getattr(config, asset.split("-")[0].lower(), None), "mode")
        else None,
        "start_index": start,
        "end_index": end,
        "overall": _summarize_trades("overall", total, trades),
        "segments": {
            "train": segment("train_first_60pct", start, train_end),
            "validation": segment("validation_next_20pct", train_end, validation_end),
            "test": segment("test_last_20pct", validation_end, end),
            "last_300": segment("last_300_candles", max(start, end - 300), end),
        },
        "warnings": [],
    }
    if result["overall"]["total_trades"] < 30:
        result["warnings"].append("TOTAL_TRADES_LOW")
    if result["segments"]["validation"]["total_trades"] and result["segments"]["validation"]["win_rate"] < 55:
        result["warnings"].append("VALIDATION_WIN_RATE_BELOW_55")
    if result["segments"]["test"]["win_rate"] < 55:
        result["warnings"].append("TEST_WIN_RATE_BELOW_55")
    if result["segments"]["train"]["win_rate"] >= 60 and result["segments"]["test"]["win_rate"] < 55:
        result["warnings"].append("TRAIN_GOOD_TEST_WEAK_POSSIBLE_OVERFIT")
    if result["segments"]["last_300"]["total_trades"] < 10:
        result["warnings"].append("LAST_300_TRADES_LOW")
    return result


def backtest_all_assets(
    asset_to_candles: dict[str, list[Candle]],
    config: StrategyConfig = DEFAULT_STRATEGY_CONFIG,
    *,
    default_strategy: Optional[str] = None,
) -> dict[str, dict[str, Any]]:
    return {
        asset: backtest_asset(asset, candles, config=config, default_strategy=default_strategy)
        for asset, candles in asset_to_candles.items()
    }


def print_backtest_report(result: dict[str, Any]) -> None:
    print(f"Asset: {result['asset']}")
    print(f"Strategy: {result.get('strategy_name', 'unknown')}")
    if result.get("mode"):
        print(f"Mode: {result['mode']}")
    for name in ("overall", "train", "validation", "test", "last_300"):
        summary = result["overall"] if name == "overall" else result["segments"][name]
        print(
            f"{name:10s} trades={summary['total_trades']:4d} "
            f"wins={summary['wins']:4d} losses={summary['losses']:4d} ties={summary['ties']:3d} "
            f"wr={summary['win_rate']:6.2f}% freq={summary['trade_frequency_pct']:6.2f}% "
            f"call={summary['call_count']:4d}/{summary['call_win_rate']:5.2f}% "
            f"put={summary['put_count']:4d}/{summary['put_win_rate']:5.2f}% "
            f"maxL={summary['max_losing_streak']} maxW={summary['max_winning_streak']}"
        )
    if result["warnings"]:
        print("Warnings:", ", ".join(result["warnings"]))
