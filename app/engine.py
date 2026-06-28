from __future__ import annotations

import asyncio
import json
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

from app.broker import BrokerError, DemoBroker, IQOptionBroker
from app.config import AppConfig, load_config
from app.db import Database, utc_now
from app.indicators import TradeSignal
from app.selector import CandidateSignal, scan_and_select


STRATEGY_MARTINGALE_STATE_KEY = "strategy_martingale_pending"
STRATEGY_MARTINGALE_MULTIPLIERS = (1.0, 1.5, 4.0)


class TradingEngine:
    def __init__(self, config: AppConfig, db: Database) -> None:
        self.config = config
        self.db = db
        self._broker = self._build_broker(config)
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._started_at: Optional[str] = None
        self._stats_since_at: Optional[str] = self.db.get_state("stats_since_at")
        self._last_tick_at: Optional[str] = None
        self._next_tick_at: Optional[str] = None
        self._last_error: Optional[str] = None
        self._last_signal: Optional[dict[str, Any]] = None
        self._last_broker_status: Optional[dict[str, Any]] = None
        self._last_skip_reason: Optional[str] = None
        self._martingale_enabled_at: Optional[str] = (
            self._tracking_timestamp()
            if config.trading.martingale_enabled or config.trading.martingale_3step_enabled
            else None
        )
        self._strategy_martingale_pending: Optional[dict[str, Any]] = self._load_strategy_martingale_pending()
        self._lock = asyncio.Lock()

    def _build_broker(self, config: AppConfig) -> Any:
        if config.broker.mode == "iqoption":
            return IQOptionBroker(config)
        return DemoBroker(config)

    async def reload_config(self) -> dict[str, Any]:
        async with self._lock:
            old_mode = self.config.broker.mode
            old_martingale_enabled = self.config.trading.martingale_enabled
            old_martingale_3step_enabled = self.config.trading.martingale_3step_enabled
            self.config = load_config()
            if self.config.trading.martingale_3step_enabled:
                self.config.trading.martingale_enabled = False
            if self.config.broker.mode != old_mode:
                self._broker = self._build_broker(self.config)
            else:
                self._broker.config = self.config
            self._sync_martingale_tracking(old_martingale_enabled, old_martingale_3step_enabled)
            self.db.add_event("info", "config", "Config reloaded", self.config.safe_dict())
        return self.status()

    async def update_trading_controls(
        self,
        *,
        asset: str,
        instrument: str,
        amount: float,
        duration_minutes: int,
        take_profit: float = 0.0,
        max_daily_loss: float = 1000.0,
        martingale_enabled: bool = False,
        martingale_3step_enabled: bool = False,
    ) -> dict[str, Any]:
        async with self._lock:
            old_martingale_enabled = self.config.trading.martingale_enabled
            old_martingale_3step_enabled = self.config.trading.martingale_3step_enabled
            self.config.trading.asset = asset.strip()
            self.config.trading.instrument = instrument.lower().strip()
            self.config.trading.amount = amount
            self.config.trading.duration_minutes = duration_minutes
            self.config.trading.martingale_3step_enabled = bool(martingale_3step_enabled)
            self.config.trading.martingale_enabled = bool(martingale_enabled) and not self.config.trading.martingale_3step_enabled
            self._sync_martingale_tracking(old_martingale_enabled, old_martingale_3step_enabled)
            self.config.risk.take_profit = take_profit
            self.config.risk.max_daily_loss = max_daily_loss
            self._broker.config = self.config
            self.db.add_event(
                "info",
                "config",
                "Trading controls updated",
                {
                    "asset": self.config.trading.asset,
                    "instrument": self.config.trading.instrument,
                    "amount": self.config.trading.amount,
                    "duration_minutes": self.config.trading.duration_minutes,
                    "martingale_enabled": self.config.trading.martingale_enabled,
                    "martingale_3step_enabled": self.config.trading.martingale_3step_enabled,
                    "take_profit": self.config.risk.take_profit,
                    "max_daily_loss": self.config.risk.max_daily_loss,
                },
            )
        return self.status()

    async def update_asset_enabled(
        self,
        *,
        asset: str,
        enabled: bool,
        direction: Optional[str] = None,
    ) -> dict[str, Any]:
        asset = asset.strip()
        if not asset:
            raise BrokerError("asset_required")
        direction = direction.lower().strip() if direction else None
        if direction and direction not in {"call", "put"}:
            raise BrokerError("invalid_direction")
        async with self._lock:
            rule = self.config.trading.asset_rules.get(asset)
            if rule is None:
                from app.config import AssetRuleConfig

                rule = AssetRuleConfig(enabled=True, allow_directions=["call", "put"])
            if direction:
                current = set(rule.allow_directions or ["call", "put"]) if rule.enabled else set()
                if enabled:
                    current.add(direction)
                else:
                    current.discard(direction)
                if current:
                    next_rule = rule.model_copy(
                        update={
                            "enabled": True,
                            "allow_directions": [item for item in ["call", "put"] if item in current],
                        }
                    )
                else:
                    next_rule = rule.model_copy(update={"enabled": False, "allow_directions": ["call", "put"]})
            else:
                next_rule = rule.model_copy(update={"enabled": enabled})
            self.config.trading.asset_rules[asset] = next_rule
            self._broker.config = self.config
            self.db.add_event(
                "info",
                "config",
                "Asset rule updated",
                {
                    "asset": asset,
                    "enabled": enabled,
                    "direction": direction,
                    "allow_directions": self.config.trading.asset_rules[asset].allow_directions,
                },
            )
        return self.status()

    async def clear_history(self) -> dict[str, Any]:
        if self._running:
            raise BrokerError("stop_bot_before_clearing_history")
        if self.db.count_open_trades() > 0:
            raise BrokerError("cannot_clear_history_with_open_trades")

        counts = self.db.clear_history(include_events=True)
        self._last_signal = None
        self._last_error = None
        self._last_tick_at = None
        self._next_tick_at = None
        self._stats_since_at = utc_now()
        self.db.set_state("stats_since_at", self._stats_since_at)
        self.db.add_event("info", "system", "History cleared", counts)
        return {"cleared": counts, "status": self.status(include_broker=False)}

    async def reset_stats(self) -> dict[str, Any]:
        if self.db.count_open_trades() > 0:
            raise BrokerError("cannot_reset_stats_with_open_trades")
        async with self._lock:
            self._stats_since_at = utc_now()
            self.db.set_state("stats_since_at", self._stats_since_at)
            self.db.add_event("info", "system", "Stats reset", {"since": self._stats_since_at})
        return self.status(include_broker=False)

    def _telegram_follow_mode_active(self) -> bool:
        return bool(self.config.telegram.enabled and self.config.telegram.follow_signals)

    async def settle_due_trades(self) -> dict[str, Any]:
        async with self._lock:
            self._last_tick_at = utc_now()
            await self._settle_due_trades()

            # MTG 3-step: ถ้า settle ผ่าน API แล้วเกิด pending ให้ยิงต่อทันที
            # ไม่ต้องรอรอบ tick / ไม่ต้องรอวินาที 59-00
            if self._running and not self._telegram_follow_mode_active():
                strategy_martingale = self._active_strategy_martingale_pending()
                if strategy_martingale:
                    await self._place_strategy_martingale_trade(strategy_martingale)

        return self.status()

    async def list_broker_assets(self) -> dict[str, Any]:
        async with self._lock:
            assets = await asyncio.to_thread(self._broker.list_assets)
            configured = set(self.config.trading.assets)
            configured.add(self.config.trading.asset)
            for item in assets.get("items", []):
                item["configured"] = item.get("name") in configured
            return assets

    async def start(self) -> dict[str, Any]:
        async with self._lock:
            if self._running:
                return self.status()
            
            await self._safe_reset_broker(reason="before_start")

            try:
                broker_status = await asyncio.wait_for(
                    asyncio.to_thread(self._broker.connect),
                    timeout=self.config.broker.connect_timeout_sec,
                )
            except asyncio.TimeoutError as exc:
                self._last_error = f"broker_connect_timeout_after_{self.config.broker.connect_timeout_sec}s"
                self._broker = self._build_broker(self.config)
                self._last_broker_status = self.broker_status()
                self.db.add_event(
                    "error",
                    "broker",
                    "Broker connect timed out",
                    {"timeout_sec": self.config.broker.connect_timeout_sec},
                )
                raise BrokerError(self._last_error) from exc
            except Exception as exc:
                self._last_error = str(exc)
                self.db.add_event("error", "broker", "Broker connect failed", {"error": str(exc)})
                raise BrokerError(str(exc)) from exc
            self._last_broker_status = await self._refresh_connected_broker_status(broker_status)
            self._running = True
            self._started_at = utc_now()
            self._stats_since_at = self._started_at
            self.db.set_state("stats_since_at", self._stats_since_at)
            self._last_error = None
            self.db.add_event("info", "bot", "Bot started", {"mode": self.config.broker.mode})
            self._task = asyncio.create_task(self._run_loop())
        return self.status()

    async def stop(self) -> dict[str, Any]:
        if not self._running:
            return self.status(include_broker=False)

        self._running = False
        task = self._task
        self._task = None
        self._next_tick_at = None
        self.db.add_event("info", "bot", "Bot stopped", {})

        if task and not task.done():
            task.cancel()
            try:
                await asyncio.wait_for(task, timeout=2)
            except asyncio.CancelledError:
                pass
            except asyncio.TimeoutError:
                self.db.add_event("warning", "bot", "Stop returned before tick cancellation finished", {})

        await self._safe_reset_broker(reason="after_stop")
        
        return self.status(include_broker=False)

    async def _run_loop(self) -> None:
        while self._running:
            started = datetime.now(timezone.utc)
            try:
                await self.tick()
            except Exception as exc:
                self._last_error = str(exc)
                self.db.add_event("error", "bot", "Tick failed", {"error": str(exc)})
            if not self._running:
                self._next_tick_at = None
                break
            interval = self._next_loop_sleep_seconds()
            next_tick = started + timedelta(seconds=interval)
            self._next_tick_at = next_tick.isoformat(timespec="seconds")
            await asyncio.sleep(interval)

    async def tick(self) -> dict[str, Any]:
        async with self._lock:
            self._last_tick_at = utc_now()

            await self._settle_due_trades()

            strategy_martingale = self._active_strategy_martingale_pending()

            if self._telegram_follow_mode_active():
                self._last_signal = {
                    "asset": "",
                    "label": "telegram",
                    "action": "wait",
                    "confidence": 0.0,
                    "reason": "telegram_follow_mode",
                    "tradable": False,
                    "reject_reason": "telegram_follow_mode",
                    "eligible_count": 0,
                    "rejections": [],
                    "close_price": None,
                    "metrics": {"source": "telegram"},
                    "top_candidate": None,
                    "auto_select_asset": False,
                    "candidates": [],
                    "created_at": self._last_tick_at,
                }
                self._last_error = "telegram_follow_mode"
                return {"placed": False, "reason": "telegram_follow_mode", "signal": self._last_signal}

            # สำคัญ:
            # MTG 3-step ต้องเข้า order ต่อทันทีหลังรู้ผล
            # ห้ามปล่อยให้ไปติด entry window 59-00
            if strategy_martingale:
                return await self._place_strategy_martingale_trade(strategy_martingale)

            # ตั้งแต่ตรงนี้ลงไปคือ strategy ปกติเท่านั้น
            # strategy ปกติยังคงรอ entry window 59-00 เหมือนเดิม
            if not self._is_entry_scan_window():
                wait_reason = "entry_window_wait"
                self._last_signal = {
                    "asset": "",
                    "label": "",
                    "action": "wait",
                    "confidence": 0.0,
                    "reason": wait_reason,
                    "tradable": False,
                    "reject_reason": wait_reason,
                    "eligible_count": 0,
                    "rejections": [],
                    "close_price": None,
                    "metrics": {},
                    "top_candidate": None,
                    "auto_select_asset": self.config.trading.auto_select_asset,
                    "candidates": [],
                    "created_at": self._last_tick_at,
                    "entry_window_seconds": sorted(self._entry_seconds()),
                    "seconds_until_entry": self._seconds_until_entry(),
                }
                self._last_error = wait_reason
                return {"placed": False, "reason": wait_reason, "signal": self._last_signal}

            decision = await self._select_signal()
            selected: CandidateSignal = decision["best"]
            signal = selected.signal
            tradable = bool(decision["tradable"])
            reject_reason = decision.get("reject_reason") or "no_candidate_above_threshold"

            self._last_signal = {
                "asset": selected.asset if tradable else "",
                "label": selected.label if tradable else "",
                "action": signal.action if tradable else "skip",
                "confidence": signal.confidence if tradable else 0.0,
                "reason": signal.reason if tradable else reject_reason,
                "tradable": tradable,
                "reject_reason": reject_reason if not tradable else "",
                "eligible_count": decision.get("eligible_count", 0),
                "rejections": decision.get("rejections", []),
                "close_price": signal.close_price if tradable else None,
                "metrics": signal.metrics if tradable else {},
                "top_candidate": selected.to_dict(),
                "auto_select_asset": self.config.trading.auto_select_asset,
                "candidates": [candidate.to_dict() for candidate in decision["candidates"]],
                "created_at": self._last_tick_at,
            }

            for candidate in decision["candidates"]:
                candidate_signal = candidate.signal
                self.db.add_signal(
                    candidate.asset,
                    candidate_signal.action,
                    candidate_signal.confidence,
                    f"{candidate.label}:{candidate_signal.reason}",
                    candidate_signal.close_price,
                    candidate_signal.metrics,
                )

            if not tradable:
                self._record_skip(reject_reason, selected, decision.get("rejections", []))
                return {"placed": False, "reason": reject_reason, "signal": self._last_signal}

            martingale = self._martingale_state()
            trade_amount = float(martingale["next_amount"])

            allowed, reason = self._risk_guard(signal, amount=trade_amount)
            if not allowed:
                self._record_skip(reason, selected)
                return {"placed": False, "reason": reason, "signal": self._last_signal}

            if not await self._wait_for_entry_second():
                self._record_skip("entry_window_missed", selected)
                return {"placed": False, "reason": "entry_window_missed", "signal": self._last_signal}

            self._last_skip_reason = None
            self._last_error = None

            trade = await self._place_trade(
                asset=selected.asset,
                instrument=self.config.trading.instrument,
                direction=signal.action,
                amount=trade_amount,
                duration_minutes=selected.duration_minutes,
                confidence=signal.confidence,
                reason=f"{selected.label}:{signal.reason}",
                strategy=f"{self.config.trading.strategy}_{selected.label}",
                martingale=martingale,
            )

            return {"placed": True, "trade": trade, "signal": self._last_signal}

    async def manual_trade(
        self,
        *,
        asset: str,
        instrument: str,
        direction: str,
        amount: float,
        duration_minutes: int,
    ) -> dict[str, Any]:
        async with self._lock:
            synthetic_signal = TradeSignal(
                action=direction,
                confidence=1.0,
                reason="manual",
                close_price=None,
                metrics={"source": "manual"},
            )
            allowed, reason = self._risk_guard(synthetic_signal, manual=True, amount=amount)
            if not allowed:
                raise BrokerError(reason)
            trade = await self._place_trade(
                asset=asset,
                instrument=instrument,
                direction=direction,
                amount=amount,
                duration_minutes=duration_minutes,
                confidence=1.0,
                reason="manual",
                strategy="manual",
            )
            return trade

    async def external_signal_trade(
        self,
        *,
        asset: str,
        direction: str,
        duration_minutes: int,
        reason: str,
        raw_signal: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        async with self._lock:
            signal = TradeSignal(
                action=direction,
                confidence=1.0,
                reason=reason,
                close_price=None,
                metrics={"source": "telegram", "raw_signal": raw_signal or {}},
            )
            rule_allowed, rule_reason = self._asset_direction_allowed(asset, direction)
            if not rule_allowed:
                self.db.add_event(
                    "info",
                    "telegram",
                    "Telegram trade skipped",
                    {
                        "asset": asset,
                        "direction": direction,
                        "reason": rule_reason,
                        "signal": raw_signal or {},
                    },
                )
                return {"placed": False, "reason": rule_reason}
            martingale = self._telegram_martingale_state(level=0)
            amount = float(martingale["next_amount"])
            allowed, risk_reason = self._risk_guard(signal, amount=amount)
            if not allowed:
                self.db.add_event(
                    "info",
                    "telegram",
                    "Telegram trade skipped",
                    {
                        "asset": asset,
                        "direction": direction,
                        "reason": risk_reason,
                        "signal": raw_signal or {},
                    },
                )
                return {"placed": False, "reason": risk_reason}
            trade = await self._place_trade(
                asset=asset,
                instrument=self.config.trading.instrument,
                direction=direction,
                amount=amount,
                duration_minutes=duration_minutes,
                confidence=1.0,
                reason=reason,
                strategy="telegram_signal",
                martingale=martingale,
                expires_at_override=self._telegram_signal_expires_at(raw_signal or {}),
                raw_extra={"telegram_signal": raw_signal or {}},
            )
            return {"placed": True, "trade": trade}

    async def _select_signal(self) -> dict[str, Any]:
        timeout_sec = self.config.trading.signal_scan_timeout_sec
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(
                    scan_and_select,
                    self._broker,
                    primary_asset=self.config.trading.asset,
                    assets=self.config.trading.assets,
                    auto_select=self.config.trading.auto_select_asset,
                    duration_minutes=self.config.trading.duration_minutes,
                    lookback_candles=self.config.trading.lookback_candles,
                    min_confidence=self.config.trading.min_confidence,
                    min_abs_momentum=self.config.trading.min_abs_momentum,
                    max_atr_ratio=self.config.trading.max_atr_ratio,
                    max_rsi=self.config.trading.max_rsi,
                    blocked_asset_directions=self.config.trading.blocked_asset_directions,
                    asset_rules=self.config.trading.asset_rules,
                    asset_direction_loss_blocks=self.db.asset_direction_loss_blocks(
                        loss_limit=self.config.risk.asset_direction_loss_limit,
                        cooldown_sec=self.config.risk.asset_direction_cooldown_sec,
                    ),
                    asset_loss_cooldowns=self.db.asset_loss_cooldowns(
                        cooldown_candles=self.config.trading.strategy_cooldown_after_loss_candles,
                        candle_interval_sec=self.config.trading.candle_interval_sec,
                    ),
                    default_strategy=self.config.trading.strategy,
                ),
                timeout=timeout_sec,
            )
        except asyncio.TimeoutError:
            await self._reconnect_broker_after_signal_timeout(timeout_sec)
            return self._timeout_signal_decision(timeout_sec)

    async def _reconnect_broker_after_signal_timeout(self, timeout_sec: int) -> None:
        self._broker = self._build_broker(self.config)
        self._last_broker_status = self.broker_status()
        payload: dict[str, Any] = {
            "timeout_sec": timeout_sec,
            "action": "broker_reset_reconnect",
        }
        try:
            broker_status = await asyncio.wait_for(
                asyncio.to_thread(self._broker.connect),
                timeout=self.config.broker.connect_timeout_sec,
            )
            self._last_broker_status = await self._refresh_connected_broker_status(broker_status)
            payload["reconnected"] = True
            self.db.add_event(
                "warning",
                "broker",
                "Signal scan timed out; broker reconnected",
                payload,
            )
        except asyncio.TimeoutError:
            self._last_broker_status = self.broker_status()
            payload["reconnected"] = False
            payload["reconnect_timeout_sec"] = self.config.broker.connect_timeout_sec
            self.db.add_event(
                "warning",
                "broker",
                "Signal scan timed out; broker reconnect timed out",
                payload,
            )
        except Exception as exc:
            self._last_broker_status = self.broker_status()
            payload["reconnected"] = False
            payload["error"] = str(exc)
            self.db.add_event(
                "warning",
                "broker",
                "Signal scan timed out; broker reconnect failed",
                payload,
            )

    def _timeout_signal_decision(self, timeout_sec: int) -> dict[str, Any]:
        candidate = CandidateSignal(
            asset=self.config.trading.asset,
            label=f"{self.config.trading.duration_minutes}m",
            interval_sec=self.config.trading.candle_interval_sec,
            duration_minutes=self.config.trading.duration_minutes,
            signal=TradeSignal(
                action="hold",
                confidence=0.0,
                reason="signal_scan_timeout",
                close_price=None,
                metrics={"timeout_sec": timeout_sec},
            ),
            score=0.0,
            error="signal_scan_timeout",
        )
        return {
            "best": candidate,
            "candidates": [candidate],
            "tradable": False,
            "eligible_count": 0,
            "reject_reason": "signal_scan_timeout",
            "rejections": [
                {
                    "asset": candidate.asset,
                    "label": candidate.label,
                    "action": candidate.signal.action,
                    "confidence": 0.0,
                    "reason": "signal_scan_timeout",
                    "signal_reason": candidate.signal.reason,
                }
            ],
        }

    async def _place_trade(
        self,
        *,
        asset: str,
        instrument: str,
        direction: str,
        amount: float,
        duration_minutes: int,
        confidence: float,
        reason: str,
        strategy: str,
        martingale: Optional[dict[str, Any]] = None,
        expires_at_override: Optional[str] = None,
        raw_extra: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        request_payload = {
            "asset": asset,
            "instrument": instrument,
            "direction": direction,
            "amount": amount,
            "duration_minutes": duration_minutes,
            "confidence": round(float(confidence), 3),
            "reason": reason,
            "timeout_sec": self.config.trading.order_timeout_sec,
        }
        if martingale:
            request_payload["martingale"] = martingale
        self.db.add_event("info", "trade", "Trade open requested", request_payload)
        try:
            order = await asyncio.wait_for(
                asyncio.to_thread(
                    self._broker.place_order,
                    asset,
                    instrument,
                    direction,
                    amount,
                    duration_minutes,
                ),
                timeout=self.config.trading.order_timeout_sec,
            )
        except asyncio.TimeoutError as exc:
            self._running = False
            self._task = None
            self._next_tick_at = None
            self._last_error = f"trade_open_timeout_after_{self.config.trading.order_timeout_sec}s"
            self.db.add_event(
                "error",
                "trade",
                "Trade open timed out",
                {
                    **request_payload,
                    "warning": "broker call did not return an order id; check IQ Option before restarting",
                },
            )
            raise BrokerError(self._last_error) from exc
        except Exception as exc:
            self.db.add_event(
                "error",
                "trade",
                "Trade open failed",
                {**request_payload, "error": str(exc)},
            )
            raise
        expires_at = expires_at_override or self._broker_expiry_at(duration_minutes)
        raw_response = dict(order.raw or {})
        if martingale:
            raw_response["martingale"] = martingale
        if raw_extra:
            raw_response.update(raw_extra)

        trade_id = self.db.create_trade(
            mode=self.config.broker.mode,
            account_type=self.config.broker.account_type,
            asset=asset,
            instrument=instrument,
            direction=direction,
            amount=amount,
            duration_minutes=duration_minutes,
            strategy=strategy,
            status="open",
            order_id=order.order_id,
            expires_at=expires_at,
            entry_price=order.entry_price,
            confidence=confidence,
            reason=reason,
            raw_response=raw_response,
        )
        payload = {
            "id": trade_id,
            "order_id": order.order_id,
            "asset": asset,
            "direction": direction,
            "amount": amount,
            "expires_at": expires_at,
        }
        if martingale:
            payload["martingale"] = martingale
        self.db.add_event("info", "trade", "Trade opened", payload)
        return payload

    def _entry_seconds(self) -> set[int]:
        return {int(second) % 60 for second in self.config.trading.entry_window_seconds}

    def _seconds_until_entry(self, now: Optional[datetime] = None) -> int:
        now = now or datetime.now(timezone.utc)
        current_second = now.second
        return min((target_second - current_second) % 60 for target_second in self._entry_seconds())

    def _is_entry_second(self, now: Optional[datetime] = None) -> bool:
        now = now or datetime.now(timezone.utc)
        return now.second in self._entry_seconds()

    def _is_entry_scan_window(self, now: Optional[datetime] = None) -> bool:
        now = now or datetime.now(timezone.utc)
        return self._seconds_until_entry(now) <= self.config.trading.entry_scan_lead_sec

    async def _wait_for_entry_second(self) -> bool:
        now = datetime.now(timezone.utc)
        if self._is_entry_second(now):
            return True
        wait_sec = self._seconds_until_entry(now)
        if wait_sec > self.config.trading.entry_scan_lead_sec:
            return False
        await asyncio.sleep(wait_sec)
        return self._is_entry_second()

    async def _settle_due_trades(self) -> None:
        due = self.db.list_due_open_trades()
        for trade in due:
            try:
                profit, raw = await asyncio.wait_for(
                    asyncio.to_thread(
                        self._broker.resolve_order,
                        str(trade["order_id"]),
                        str(trade["instrument"]),
                        int(trade["duration_minutes"]),
                    ),
                    timeout=20,
                )
            except asyncio.TimeoutError:
                self.db.add_event(
                    "warning",
                    "trade",
                    "Trade settlement timed out",
                    {"id": trade["id"], "order_id": trade["order_id"]},
                )
                continue
            except Exception as exc:
                self.db.add_event(
                    "error",
                    "trade",
                    "Trade settlement failed",
                    {"id": trade["id"], "order_id": trade["order_id"], "error": str(exc)},
                )
                continue
            if profit is None:
                if raw.get("status") == "unknown":
                    self.db.fail_trade(int(trade["id"]), raw.get("message", "order not found"), raw)
                    self.db.add_event("warning", "trade", "Trade marked failed", {"id": trade["id"], "raw": raw})
                continue
            exit_price = None
            payout = None
            if isinstance(raw, dict):
                exit_price = raw.get("exit_price")
                payout = raw.get("payout_rate")
            self.db.close_trade(
                int(trade["id"]),
                profit=round(float(profit), 2),
                exit_price=exit_price,
                payout=payout,
                raw_response=raw,
            )
            self.db.add_event(
                "info",
                "trade",
                "Trade closed",
                {"id": trade["id"], "order_id": trade["order_id"], "profit": round(float(profit), 2)},
            )
            await self._refresh_balance_after_settlement(trade, round(float(profit), 2))
            self._update_strategy_martingale_after_close(trade, round(float(profit), 2))
            await self._maybe_place_telegram_martingale(trade, round(float(profit), 2))

    async def _place_strategy_martingale_trade(self, pending: dict[str, Any]) -> dict[str, Any]:
        asset = str(pending.get("asset") or "")
        direction = str(pending.get("direction") or "").lower()
        instrument = str(pending.get("instrument") or self.config.trading.instrument)
        duration_minutes = int(pending.get("duration_minutes") or self.config.trading.duration_minutes)
        level = int(pending.get("level") or 0)

        martingale = self._martingale_state(level=level, pending=pending)
        amount = float(martingale["next_amount"])

        signal = TradeSignal(
            action=direction,
            confidence=1.0,
            reason="strategy_martingale_3step",
            close_price=None,
            metrics={
                "source": "strategy_martingale",
                "pending": pending,
                "immediate_after_settlement": True,
            },
        )

        allowed_direction, direction_reason = self._asset_direction_allowed(asset, direction)
        if not allowed_direction:
            self._record_strategy_martingale_skip(direction_reason, pending)
            return {"placed": False, "reason": direction_reason, "signal": self._last_signal}

        allowed, reason = self._risk_guard(signal, amount=amount, ignore_cooldown=True)
        if not allowed:
            self._record_strategy_martingale_skip(reason, pending)
            return {"placed": False, "reason": reason, "signal": self._last_signal}

        self._last_signal = {
            "asset": asset,
            "label": "martingale",
            "action": direction,
            "confidence": 1.0,
            "reason": "strategy_martingale_3step",
            "tradable": True,
            "reject_reason": "",
            "eligible_count": 1,
            "rejections": [],
            "close_price": None,
            "metrics": {
                "martingale": martingale,
                "pending": pending,
                "immediate_after_settlement": True,
            },
            "top_candidate": None,
            "auto_select_asset": False,
            "candidates": [],
            "created_at": self._last_tick_at or utc_now(),
        }

        self._last_skip_reason = None
        self._last_error = None

        try:
            trade = await self._place_trade(
                asset=asset,
                instrument=instrument,
                direction=direction,
                amount=amount,
                duration_minutes=duration_minutes,
                confidence=1.0,
                reason="martingale:strategy_martingale_3step",
                strategy="strategy_martingale",
                martingale=martingale,
                raw_extra={
                    "strategy_martingale_parent_id": pending.get("parent_trade_id"),
                    "immediate_after_settlement": True,
                },
            )
        except Exception:
            # อย่า clear pending ถ้ายิง order ไม่สำเร็จ
            # เพื่อให้รอบถัดไปยัง retry MTG ได้
            raise

        # clear หลังยิง order สำเร็จเท่านั้น
        self._clear_strategy_martingale_pending()

        return {"placed": True, "trade": trade, "signal": self._last_signal}
    
    def _record_strategy_martingale_skip(self, reason: str, pending: dict[str, Any]) -> None:
        self._last_error = reason
        self._last_signal = {
            "asset": str(pending.get("asset") or ""),
            "label": "martingale",
            "action": str(pending.get("direction") or "skip"),
            "confidence": 1.0,
            "reason": reason,
            "tradable": False,
            "reject_reason": reason,
            "eligible_count": 0,
            "rejections": [],
            "close_price": None,
            "metrics": {"martingale": self._martingale_state(pending=pending), "pending": pending},
            "top_candidate": None,
            "auto_select_asset": False,
            "candidates": [],
            "created_at": self._last_tick_at,
        }
        if reason != self._last_skip_reason:
            self._last_skip_reason = reason
            self.db.add_event(
                "info",
                "trade",
                "Trade skipped",
                {
                    "reason": reason,
                    "asset": pending.get("asset"),
                    "label": "martingale",
                    "action": pending.get("direction"),
                    "confidence": 1.0,
                    "martingale": self._martingale_state(pending=pending),
                },
            )

    async def _maybe_place_telegram_martingale(self, trade: dict[str, Any], profit: float) -> None:
        if str(trade.get("strategy")) != "telegram_signal" or profit > 0:
            return
        raw_response = trade.get("raw_response") if isinstance(trade.get("raw_response"), dict) else {}
        martingale = raw_response.get("martingale") if isinstance(raw_response.get("martingale"), dict) else {}
        current_level = int(martingale.get("level") or 0)
        max_steps = int(martingale.get("max_steps") or 3)
        is_draw = profit == 0
        next_level = current_level if is_draw else current_level + 1
        if not is_draw and next_level >= max_steps:
            self.db.add_event(
                "info",
                "telegram",
                "Telegram martingale sequence finished",
                {"trade_id": trade.get("id"), "level": current_level, "max_steps": max_steps},
            )
            return

        signal = TradeSignal(
            action=str(trade.get("direction")),
            confidence=1.0,
            reason="telegram_martingale_draw_retry" if is_draw else "telegram_martingale",
            close_price=None,
            metrics={"source": "telegram", "previous_trade_id": trade.get("id")},
        )
        next_martingale = self._telegram_martingale_state(level=next_level)
        amount = float(next_martingale["next_amount"])
        allowed, reason = self._risk_guard(signal, amount=amount, ignore_cooldown=True)
        if not allowed:
            self.db.add_event(
                "info",
                "telegram",
                "Telegram martingale skipped",
                {
                    "trade_id": trade.get("id"),
                    "level": next_level,
                    "amount": amount,
                    "reason": reason,
                },
            )
            return

        self.db.add_event(
            "info",
            "telegram",
            "Telegram martingale retry requested",
            {
                "previous_trade_id": trade.get("id"),
                "asset": trade.get("asset"),
                "direction": trade.get("direction"),
                "level": next_level,
                "amount": amount,
                "previous_profit": profit,
                "draw_retry": is_draw,
            },
        )
        await self._place_trade(
            asset=str(trade.get("asset")),
            instrument=str(trade.get("instrument")),
            direction=str(trade.get("direction")),
            amount=amount,
            duration_minutes=int(trade.get("duration_minutes") or self.config.telegram.default_expiry_minutes),
            confidence=1.0,
            reason=signal.reason,
            strategy="telegram_signal",
            martingale=next_martingale,
            expires_at_override=self._next_telegram_expiry_at(
                int(trade.get("duration_minutes") or self.config.telegram.default_expiry_minutes)
            ),
            raw_extra={"telegram_martingale_parent_id": trade.get("id")},
        )

    async def _refresh_balance_after_settlement(self, trade: dict[str, Any], profit: float) -> None:
        refresh_balance = getattr(self._broker, "refresh_balance", None)
        if not callable(refresh_balance):
            return
        try:
            status = await asyncio.wait_for(asyncio.to_thread(refresh_balance), timeout=3)
            self._last_broker_status = asdict(status)
            self.db.add_event(
                "info",
                "broker",
                "Balance refreshed after trade",
                {
                    "trade_id": trade.get("id"),
                    "profit": profit,
                    "balance": self._last_broker_status.get("balance"),
                },
            )
        except Exception as exc:
            self.db.add_event(
                "warning",
                "broker",
                "Balance refresh after trade failed",
                {"trade_id": trade.get("id"), "profit": profit, "error": str(exc)},
            )

    def _update_strategy_martingale_after_close(self, trade: dict[str, Any], profit: float) -> None:
        if str(trade.get("strategy")) == "telegram_signal":
            return
        raw_response = trade.get("raw_response") if isinstance(trade.get("raw_response"), dict) else {}
        martingale = raw_response.get("martingale") if isinstance(raw_response.get("martingale"), dict) else {}
        if martingale.get("source") != "strategy_three_step":
            return

        if not self.config.trading.martingale_3step_enabled:
            self._clear_strategy_martingale_pending()
            return

        current_level = int(martingale.get("level") or 0)
        max_steps = int(martingale.get("max_steps") or len(STRATEGY_MARTINGALE_MULTIPLIERS))
        is_draw = profit == 0
        if profit > 0:
            self._clear_strategy_martingale_pending()
            self.db.add_event(
                "info",
                "trade",
                "Strategy martingale reset after win",
                {"trade_id": trade.get("id"), "level": current_level, "profit": profit},
            )
            return

        next_level = current_level if is_draw else current_level + 1
        if not is_draw and next_level >= max_steps:
            self._clear_strategy_martingale_pending()
            self.db.add_event(
                "info",
                "trade",
                "Strategy martingale sequence finished",
                {"trade_id": trade.get("id"), "level": current_level, "max_steps": max_steps, "profit": profit},
            )
            return

        pending = {
            "source": "strategy_three_step",
            "asset": str(trade.get("asset") or ""),
            "instrument": str(trade.get("instrument") or self.config.trading.instrument),
            "direction": str(trade.get("direction") or ""),
            "duration_minutes": int(trade.get("duration_minutes") or self.config.trading.duration_minutes),
            "level": max(0, min(next_level, max_steps - 1)),
            "max_steps": max_steps,
            "parent_trade_id": trade.get("id"),
            "previous_profit": profit,
            "draw_retry": is_draw,
            "updated_at": utc_now(),
        }
        self._set_strategy_martingale_pending(pending)
        self.db.add_event(
            "info",
            "trade",
            "Strategy martingale pending",
            {
                "trade_id": trade.get("id"),
                "asset": pending["asset"],
                "direction": pending["direction"],
                "level": pending["level"],
                "amount": self._martingale_state(pending=pending)["next_amount"],
                "draw_retry": is_draw,
            },
        )

    def _load_strategy_martingale_pending(self) -> Optional[dict[str, Any]]:
        raw = self.db.get_state(STRATEGY_MARTINGALE_STATE_KEY)
        if not raw:
            return None
        try:
            pending = json.loads(raw)
        except json.JSONDecodeError:
            return None
        return pending if isinstance(pending, dict) else None

    def _set_strategy_martingale_pending(self, pending: dict[str, Any]) -> None:
        self._strategy_martingale_pending = pending
        self.db.set_state(STRATEGY_MARTINGALE_STATE_KEY, json.dumps(pending, default=str))

    def _clear_strategy_martingale_pending(self) -> None:
        self._strategy_martingale_pending = None
        self.db.delete_state(STRATEGY_MARTINGALE_STATE_KEY)

    def _active_strategy_martingale_pending(self) -> Optional[dict[str, Any]]:
        if not self.config.trading.martingale_3step_enabled:
            return None
        pending = self._strategy_martingale_pending
        if not pending:
            return None
        try:
            level = int(pending.get("level") or 0)
        except (TypeError, ValueError):
            self._clear_strategy_martingale_pending()
            return None
        if level <= 0 or level >= len(STRATEGY_MARTINGALE_MULTIPLIERS):
            self._clear_strategy_martingale_pending()
            return None
        if str(pending.get("asset") or "") and str(pending.get("direction") or "").lower() in {"call", "put"}:
            return pending
        self._clear_strategy_martingale_pending()
        return None

    def _strategy_martingale_multiplier(self, level: int) -> float:
        index = max(0, min(int(level), len(STRATEGY_MARTINGALE_MULTIPLIERS) - 1))
        return float(STRATEGY_MARTINGALE_MULTIPLIERS[index])

    def _strategy_martingale_preview(self, base_amount: float) -> list[float]:
        return [round(base_amount * multiplier, 2) for multiplier in STRATEGY_MARTINGALE_MULTIPLIERS]

    def _martingale_multiplier(self, level: int) -> int:
        if level <= 0:
            return 1
        return 2**level

    def _martingale_state(
        self,
        *,
        level: Optional[int] = None,
        pending: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        base_amount = round(float(self.config.trading.amount), 2)
        three_step_enabled = bool(self.config.trading.martingale_3step_enabled)
        classic_enabled = bool(self.config.trading.martingale_enabled) and not three_step_enabled
        enabled = classic_enabled or three_step_enabled
        if enabled and not self._martingale_enabled_at:
            self._martingale_enabled_at = self._tracking_timestamp()

        if classic_enabled:
            loss_streak = self.db.consecutive_losses()
            classic_level = loss_streak if level is None else int(level)
            multiplier = self._martingale_multiplier(classic_level)
            preview = [
                round(base_amount * self._martingale_multiplier(step), 2)
                for step in range(min(max(classic_level + 2, 6), 8))
            ]
            return {
                "enabled": True,
                "source": "strategy_classic",
                "mode": "classic_double",
                "base_amount": base_amount,
                "loss_streak": loss_streak,
                "level": classic_level,
                "multiplier": multiplier,
                "next_amount": round(base_amount * multiplier, 2),
                "will_apply": classic_level > 0,
                "enabled_at": self._martingale_enabled_at,
                "sequence_preview": preview,
                "pending": None,
            }

        active_pending = pending if pending is not None else self._active_strategy_martingale_pending()
        three_step_level = 0
        if three_step_enabled:
            three_step_level = int(active_pending.get("level") or 0) if level is None and active_pending else int(level or 0)
        three_step_level = max(0, min(three_step_level, len(STRATEGY_MARTINGALE_MULTIPLIERS) - 1))
        multiplier = self._strategy_martingale_multiplier(three_step_level)
        return {
            "enabled": three_step_enabled,
            "source": "strategy_three_step",
            "mode": "three_step_1_1_5_4",
            "base_amount": base_amount,
            "loss_streak": three_step_level,
            "level": three_step_level,
            "max_steps": len(STRATEGY_MARTINGALE_MULTIPLIERS),
            "multiplier": multiplier,
            "next_amount": round(base_amount * multiplier, 2),
            "will_apply": three_step_enabled and three_step_level > 0,
            "enabled_at": self._martingale_enabled_at if three_step_enabled else None,
            "sequence_preview": self._strategy_martingale_preview(base_amount),
            "pending": active_pending if three_step_enabled and active_pending else None,
        }

    def _telegram_martingale_state(self, *, level: int = 0) -> dict[str, Any]:
        base_amount = round(float(self.config.trading.amount), 2)
        level = max(0, min(int(level), 2))
        multiplier = self._martingale_multiplier(level)
        next_amount = round(base_amount * multiplier, 2)
        return {
            "enabled": True,
            "source": "telegram_fixed",
            "base_amount": base_amount,
            "loss_streak": level,
            "level": level,
            "max_steps": 3,
            "multiplier": multiplier,
            "next_amount": next_amount,
            "will_apply": level > 0,
            "sequence_preview": [base_amount, round(base_amount * 2, 2), round(base_amount * 4, 2)],
        }

    def _telegram_signal_expires_at(self, raw_signal: dict[str, Any]) -> Optional[str]:
        signal_time = str(raw_signal.get("signal_time") or "")
        if not signal_time:
            return None
        try:
            hour, minute = [int(part) for part in signal_time.split(":", 1)]
        except ValueError:
            return None
        tz = ZoneInfo("Asia/Bangkok")
        now = datetime.now(tz)
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if target < now - timedelta(seconds=20):
            target += timedelta(days=1)
        return target.astimezone(timezone.utc).isoformat(timespec="seconds")

    def _next_telegram_expiry_at(self, duration_minutes: int) -> str:
        return self._broker_expiry_at(duration_minutes)

    def _sync_martingale_tracking(self, old_enabled: bool, old_three_step_enabled: bool) -> None:
        three_step_enabled = bool(self.config.trading.martingale_3step_enabled)
        classic_enabled = bool(self.config.trading.martingale_enabled) and not three_step_enabled
        enabled = classic_enabled or three_step_enabled
        was_enabled = bool(old_enabled) or bool(old_three_step_enabled)
        if three_step_enabled and self.config.trading.martingale_enabled:
            self.config.trading.martingale_enabled = False
        if enabled and not was_enabled:
            self._martingale_enabled_at = self._tracking_timestamp()
        if three_step_enabled and not old_three_step_enabled:
            self._clear_strategy_martingale_pending()
        elif not enabled:
            self._martingale_enabled_at = None
            self._clear_strategy_martingale_pending()

    @staticmethod
    def _tracking_timestamp() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="microseconds")

    def _next_loop_sleep_seconds(self) -> float:
        base_interval = float(self.config.trading.poll_interval_sec)
        expires_at = self.db.next_open_trade_expires_at()
        if not expires_at:
            return base_interval
        try:
            expiry = datetime.fromisoformat(expires_at)
        except ValueError:
            return base_interval
        due_in = (expiry - datetime.now(timezone.utc)).total_seconds()
        if due_in <= 0:
            return 0.2
        if due_in <= 2:
            return min(base_interval, max(0.05, due_in))
        return base_interval

    def _asset_direction_allowed(self, asset: str, direction: str) -> tuple[bool, str]:
        rule = self.config.trading.asset_rules.get(asset)
        if not rule:
            return True, ""
        if not rule.enabled:
            return False, "asset_disabled"
        allow_directions = rule.allow_directions or []
        if allow_directions and direction not in allow_directions:
            return False, "asset_direction_disabled"
        return True, ""

    def _risk_guard(
        self,
        signal: TradeSignal,
        *,
        manual: bool = False,
        amount: Optional[float] = None,
        ignore_cooldown: bool = False,
    ) -> tuple[bool, str]:
        trade_amount = amount if amount is not None else self.config.trading.amount
        stats = self.db.daily_stats()

        if signal.action not in {"call", "put"}:
            return False, signal.reason
        if not manual and signal.confidence < self.config.trading.min_confidence:
            return False, "confidence_below_minimum"
        if self.config.broker.account_type == "REAL" and not self.config.risk.allow_real_balance:
            return False, "real_balance_disabled_by_risk_guard"
        if self.config.risk.max_trade_amount > 0 and trade_amount > self.config.risk.max_trade_amount:
            return False, "amount_exceeds_max_trade_amount"
        if self.config.risk.take_profit > 0 and stats["profit"] >= self.config.risk.take_profit:
            return False, "take_profit_reached"
        if stats["daily_loss"] >= self.config.risk.max_daily_loss:
            return False, "daily_loss_limit_reached"
        projected_loss = abs(min(float(stats["profit"] or 0) - float(trade_amount), 0.0))
        if projected_loss > self.config.risk.max_daily_loss:
            return False, "daily_loss_limit_would_be_exceeded"
        if self.config.risk.max_trades_per_day > 0 and stats["trades"] >= self.config.risk.max_trades_per_day:
            return False, "max_trades_per_day_reached"
        if (
            self.config.risk.stop_after_consecutive_losses > 0
            and stats["consecutive_losses"] >= self.config.risk.stop_after_consecutive_losses
        ):
            return False, "consecutive_loss_limit_reached"
        if self.config.trading.one_open_trade_at_a_time and self.db.count_open_trades() > 0:
            return False, "open_trade_exists"
        if stats["last_trade_at"] and not ignore_cooldown:
            try:
                last = datetime.fromisoformat(stats["last_trade_at"])
                elapsed = (datetime.now(timezone.utc) - last).total_seconds()
                if elapsed < self.config.risk.cooldown_sec:
                    return False, "cooldown_active"
            except ValueError:
                pass
        return True, "ok"

    def _record_skip(
        self,
        reason: str,
        selected: CandidateSignal,
        rejections: Optional[list[dict[str, Any]]] = None,
    ) -> None:
        self._last_error = reason
        if reason == self._last_skip_reason:
            return
        self._last_skip_reason = reason
        payload = {
            "reason": reason,
            "asset": selected.asset,
            "label": selected.label,
            "action": selected.signal.action,
            "confidence": round(float(selected.signal.confidence), 3),
        }
        if rejections:
            payload["rejections"] = rejections[:8]
        is_risk_reason = (
            reason.endswith("_reached")
            or reason.endswith("_limit_reached")
            or reason.endswith("_would_be_exceeded")
        )
        self.db.add_event(
            "info",
            "risk" if is_risk_reason else "trade",
            "Trade skipped",
            payload,
        )

    def broker_status(self) -> dict[str, Any]:
        try:
            status = self._broker.status()
            data = asdict(status)
            self._last_broker_status = data
            return data
        except Exception as exc:
            data = {
                "connected": False,
                "mode": self.config.broker.mode,
                "account_type": self.config.broker.account_type,
                "balance": None,
                "message": str(exc),
            }
            self._last_broker_status = data
            return data

    def stats_since_at(self) -> Optional[str]:
        return self._stats_since_at or self._started_at

    async def _refresh_connected_broker_status(self, broker_status: Any) -> dict[str, Any]:
        data = asdict(broker_status)
        refresh_balance = getattr(self._broker, "refresh_balance", None)
        if not callable(refresh_balance):
            return data
        try:
            refreshed = await asyncio.wait_for(asyncio.to_thread(refresh_balance), timeout=2)
            data = asdict(refreshed)
        except asyncio.TimeoutError:
            data["message"] = f"{data.get('message') or 'connected'}; balance_refresh_timeout"
            self.db.add_event("warning", "broker", "Balance refresh timed out", {"timeout_sec": 2})
        except Exception as exc:
            data["message"] = str(exc)
            self.db.add_event("warning", "broker", "Balance refresh failed", {"error": str(exc)})
        return data

    def status(self, *, include_broker: bool = True) -> dict[str, Any]:
        stats_since = self.stats_since_at()

        session_stats = self.db.daily_stats(since=stats_since)  # หลัง Reset Stats
        today_stats = self.db.daily_stats()                     # ทั้งวัน ไม่โดน Reset

        session_stats["today_profit"] = today_stats["profit"]
        session_stats["today_daily_loss"] = today_stats["daily_loss"]
        session_stats["today_trades"] = today_stats["trades"]
        session_stats["today_wins"] = today_stats["wins"]
        session_stats["today_losses"] = today_stats["losses"]

        return {
            "running": self._running,
            "started_at": self._started_at,
            "stats_since_at": stats_since,
            "last_tick_at": self._last_tick_at,
            "next_tick_at": self._next_tick_at,
            "last_error": self._last_error,
            "last_signal": self._last_signal,
            "config": self.config.safe_dict(),
            "martingale": self._martingale_state(),
            "broker": self.broker_status()
            if include_broker
            else {
                "connected": False,
                "mode": self.config.broker.mode,
                "account_type": self.config.broker.account_type,
                "balance": None,
                "message": "stop requested",
            },
            "stats": session_stats,
        }
    
    async def _safe_reset_broker(self, *, reason: str = "reset_broker") -> None:
        old_broker = self._broker

        for method_name in ("disconnect", "close", "logout"):
            method = getattr(old_broker, method_name, None)
            if not callable(method):
                continue

            try:
                await asyncio.wait_for(asyncio.to_thread(method), timeout=3)
                self.db.add_event(
                    "info",
                    "broker",
                    "Broker disconnected",
                    {"reason": reason, "method": method_name},
                )
                break
            except Exception as exc:
                self.db.add_event(
                    "warning",
                    "broker",
                    "Broker disconnect failed",
                    {"reason": reason, "method": method_name, "error": str(exc)},
                )
                break

        self._broker = self._build_broker(self.config)
        self._last_broker_status = self.broker_status()

    def _broker_expiry_at(self, duration_minutes: int, now: Optional[datetime] = None) -> str:
        now = now or datetime.now(timezone.utc)

        # IQ order ปิดที่วินาที 00 เสมอ
        expiry = now.replace(second=0, microsecond=0) + timedelta(minutes=duration_minutes)

        # ถ้าเข้า order หลัง/เท่ากับ 30 วิ ให้ขยับไป 00 ของนาทีถัดไป
        if now.second >= 30:
            expiry += timedelta(minutes=1)

        return expiry.isoformat(timespec="seconds")
