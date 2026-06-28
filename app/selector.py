from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Optional

from app.broker.base import Broker
from app.indicators import TradeSignal
from app.strategies import get_signal, is_asset_specific_signal


@dataclass
class CandidateSignal:
    asset: str
    label: str
    interval_sec: int
    duration_minutes: int
    signal: TradeSignal
    score: float
    error: str = ""
    filter_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "asset": self.asset,
            "label": self.label,
            "interval_sec": self.interval_sec,
            "duration_minutes": self.duration_minutes,
            "action": self.signal.action,
            "confidence": self.signal.confidence,
            "reason": self.signal.reason,
            "close_price": self.signal.close_price,
            "metrics": self.signal.metrics,
            "score": self.score,
            "error": self.error,
            "filter_reason": self.filter_reason,
        }


TIMEFRAMES: tuple[tuple[str, int, int], ...] = (
    ("1m", 60, 1),
    ("5m", 300, 5),
)


def timeframes_for_duration(duration_minutes: int) -> list[tuple[str, int, int]]:
    matching = [timeframe for timeframe in TIMEFRAMES if timeframe[2] == duration_minutes]
    if matching:
        return matching
    return [(f"{duration_minutes}m", duration_minutes * 60, duration_minutes)]


def candidate_assets(primary_asset: str, assets: list[str], auto_select: bool) -> list[str]:
    if not auto_select:
        return [primary_asset]

    seen: set[str] = set()
    result: list[str] = []
    for asset in [primary_asset] + list(assets):
        cleaned = asset.strip()
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            result.append(cleaned)
    return result or [primary_asset]


def closed_candles(candles: list[Any], interval_sec: int, now: Optional[float] = None) -> list[Any]:
    now = time.time() if now is None else now
    return [candle for candle in candles if candle.timestamp + interval_sec <= now]


def scan_candidates(
    broker: Broker,
    *,
    primary_asset: str,
    assets: list[str],
    auto_select: bool,
    duration_minutes: int,
    lookback_candles: int,
    default_strategy: Optional[str],
) -> list[CandidateSignal]:
    candidates: list[CandidateSignal] = []
    timeframes = timeframes_for_duration(duration_minutes)
    for asset in candidate_assets(primary_asset, assets, auto_select):
        for label, interval_sec, candidate_duration_minutes in timeframes:
            try:
                candles = closed_candles(broker.get_candles(asset, interval_sec, lookback_candles), interval_sec)
                signal = get_signal(
                    asset,
                    candles,
                    len(candles) - 1,
                    default_strategy=default_strategy,
                )
                score = signal.confidence if signal.action in {"call", "put"} else 0.0
                candidates.append(
                    CandidateSignal(
                        asset=asset,
                        label=label,
                        interval_sec=interval_sec,
                        duration_minutes=candidate_duration_minutes,
                        signal=signal,
                        score=score,
                    )
                )
            except Exception as exc:
                candidates.append(
                    CandidateSignal(
                        asset=asset,
                        label=label,
                        interval_sec=interval_sec,
                        duration_minutes=candidate_duration_minutes,
                        signal=TradeSignal(
                            action="hold",
                            confidence=0.0,
                            reason="asset_scan_error",
                            close_price=None,
                            metrics={"error": str(exc)},
                        ),
                        score=0.0,
                        error=str(exc),
                    )
                )
    return candidates


def _metric_float(candidate: CandidateSignal, name: str) -> Optional[float]:
    value = candidate.signal.metrics.get(name)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _blocked_pairs(items: list[str]) -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    for item in items:
        if ":" not in item:
            continue
        asset, direction = item.rsplit(":", 1)
        asset = asset.strip()
        direction = direction.lower().strip()
        if asset and direction in {"call", "put"}:
            pairs.add((asset, direction))
    return pairs


def _rule_value(rule: Any, name: str, default: Any = None) -> Any:
    if rule is None:
        return default
    if isinstance(rule, dict):
        return rule.get(name, default)
    return getattr(rule, name, default)


def _threshold(rule: Any, name: str, fallback: float) -> float:
    value = _rule_value(rule, name)
    return fallback if value is None else float(value)


def candidate_filter_reason(
    candidate: CandidateSignal,
    *,
    min_abs_momentum: float,
    max_atr_ratio: float,
    max_rsi: float,
    blocked_asset_directions: list[str],
    asset_rules: dict[str, Any],
    asset_direction_loss_blocks: dict[str, Any],
    asset_loss_cooldowns: dict[str, Any],
) -> str:
    action = candidate.signal.action
    if action not in {"call", "put"}:
        return ""

    if is_asset_specific_signal(candidate.signal) and asset_loss_cooldowns.get(candidate.asset):
        return "strategy_loss_cooldown"

    if asset_direction_loss_blocks.get(f"{candidate.asset}:{action}"):
        return "asset_direction_loss_cooldown"

    rule = asset_rules.get(candidate.asset) if asset_rules else None
    if rule is not None:
        if not bool(_rule_value(rule, "enabled", True)):
            return "asset_rule_disabled"
        allow_directions = _rule_value(rule, "allow_directions", []) or []
        if allow_directions and action not in allow_directions:
            return "direction_not_allowed_for_asset"
        min_confidence = _rule_value(rule, "min_confidence")
        if min_confidence is not None and candidate.score < float(min_confidence):
            return "confidence_below_asset_rule"
    elif (candidate.asset, action) in _blocked_pairs(blocked_asset_directions):
        return "blocked_asset_direction"

    if is_asset_specific_signal(candidate.signal):
        return ""

    momentum = _metric_float(candidate, "momentum")
    momentum_floor = _threshold(rule, "min_abs_momentum", min_abs_momentum)
    if momentum_floor > 0 and (momentum is None or abs(momentum) < momentum_floor):
        return "momentum_below_filter"

    atr_ratio = _metric_float(candidate, "atr_ratio")
    atr_ceiling = _threshold(rule, "max_atr_ratio", max_atr_ratio)
    if atr_ceiling > 0 and (atr_ratio is None or atr_ratio > atr_ceiling):
        return "atr_ratio_above_filter"

    rsi = _metric_float(candidate, "rsi")
    min_rsi = _rule_value(rule, "min_rsi")
    if min_rsi is not None and (rsi is None or rsi < float(min_rsi)):
        return "rsi_below_filter"
    rsi_ceiling = _threshold(rule, "max_rsi", max_rsi)
    if rsi_ceiling > 0 and rsi is not None and rsi > rsi_ceiling:
        return "rsi_above_filter"

    return ""


def select_best_candidate(
    candidates: list[CandidateSignal],
    min_confidence: float,
    min_abs_momentum: float,
    max_atr_ratio: float,
    max_rsi: float,
    blocked_asset_directions: list[str],
    asset_rules: dict[str, Any],
    asset_direction_loss_blocks: dict[str, Any] | None = None,
    asset_loss_cooldowns: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not candidates:
        raise ValueError("no candidate signals were scanned")

    asset_direction_loss_blocks = asset_direction_loss_blocks or {}
    asset_loss_cooldowns = asset_loss_cooldowns or {}
    for candidate in candidates:
        candidate.filter_reason = candidate_filter_reason(
            candidate,
            min_abs_momentum=min_abs_momentum,
            max_atr_ratio=max_atr_ratio,
            max_rsi=max_rsi,
            blocked_asset_directions=blocked_asset_directions,
            asset_rules=asset_rules,
            asset_direction_loss_blocks=asset_direction_loss_blocks,
            asset_loss_cooldowns=asset_loss_cooldowns,
        )

    best_raw = max(candidates, key=lambda item: item.score)
    eligible = [
        candidate
        for candidate in candidates
        if candidate.signal.action in {"call", "put"}
        and candidate.score >= min_confidence
        and not candidate.filter_reason
    ]
    best = max(eligible, key=lambda item: item.score) if eligible else best_raw
    tradable = bool(eligible)
    rejections: list[dict[str, Any]] = []
    for candidate in sorted(candidates, key=lambda item: item.score, reverse=True):
        reason = ""
        if candidate.signal.action not in {"call", "put"}:
            reason = candidate.signal.reason
        elif candidate.score < min_confidence:
            reason = "confidence_below_minimum"
        else:
            reason = candidate.filter_reason
        if reason:
            loss_block = asset_direction_loss_blocks.get(f"{candidate.asset}:{candidate.signal.action}") or {}
            rejections.append(
                {
                    "asset": candidate.asset,
                    "label": candidate.label,
                    "action": candidate.signal.action,
                    "confidence": round(float(candidate.signal.confidence), 3),
                    "reason": reason,
                    "signal_reason": candidate.signal.reason,
                    "losses": loss_block.get("losses"),
                    "cooldown_until": loss_block.get("cooldown_until"),
                }
            )
            asset_loss_block = asset_loss_cooldowns.get(candidate.asset) or {}
            if asset_loss_block:
                rejections[-1]["last_loss_closed_at"] = asset_loss_block.get("last_closed_at")
                rejections[-1]["strategy_cooldown_until"] = asset_loss_block.get("cooldown_until")

    reject_reason = ""
    if not tradable:
        reject_reason = "no_eligible_candidate"
    return {
        "best": best,
        "candidates": candidates,
        "tradable": tradable,
        "eligible_count": len(eligible),
        "reject_reason": reject_reason,
        "rejections": rejections,
    }


def scan_and_select(
    broker: Broker,
    *,
    primary_asset: str,
    assets: list[str],
    auto_select: bool,
    duration_minutes: int,
    lookback_candles: int,
    min_confidence: float,
    min_abs_momentum: float,
    max_atr_ratio: float,
    max_rsi: float,
    blocked_asset_directions: list[str],
    asset_rules: dict[str, Any],
    asset_direction_loss_blocks: dict[str, Any] | None = None,
    asset_loss_cooldowns: dict[str, Any] | None = None,
    default_strategy: Optional[str] = None,
) -> dict[str, Any]:
    candidates = scan_candidates(
        broker,
        primary_asset=primary_asset,
        assets=assets,
        auto_select=auto_select,
        duration_minutes=duration_minutes,
        lookback_candles=lookback_candles,
        default_strategy=default_strategy,
    )
    return select_best_candidate(
        candidates,
        min_confidence,
        min_abs_momentum,
        max_atr_ratio,
        max_rsi,
        blocked_asset_directions,
        asset_rules,
        asset_direction_loss_blocks,
        asset_loss_cooldowns,
    )
