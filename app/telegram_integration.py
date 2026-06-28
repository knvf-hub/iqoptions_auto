from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

from app.config import AppConfig, ROOT_DIR
from app.db import Database, utc_now
from app.engine import TradingEngine


CUSTOM_MAP = {
    "ARBITRUM": "ARBUSD-OTC",
    "ARB": "ARBUSD-OTC",
    "BITCOIN": "BTCUSD-op",
    "BITCOINUSD": "BTCUSD-op",
    "BITCOINUSD-OTC": "BTCUSD-OTC-op",
    "BAIDUINCADR": "BIDU-OTC",
    "BONK": "BONKUSD-OTC",
    "CARDANO": "CARDANO-OTC",
    "CELESTIA": "TIAUSD-OTC",
    "CHAINLINK": "LINKUSD-OTC",
    "COSMOS": "ATOMUSD-OTC",
    "DECENTRALAND": "MANAUSD-OTC",
    "DOGECOIN": "DOGECOIN-OTC",
    "DOGWIFHAT": "WIFUSD-OTC",
    "ETHEREUM": "ETHUSD-op",
    "ETHEREUMUSD": "ETHUSD-op",
    "FARTCOIN": "FARTCOINUSD-OTC",
    "ICP": "ICPUSD-OTC",
    "INJECTIVE": "INJUSD-OTC",
    "IOTA": "IOTAUSD-OTC",
    "LITECOIN": "LTCUSD-OTC",
    "META": "FB-OTC",
    "POLKADOT": "DOTUSD-OTC",
    "POLYGON": "MATICUSD-OTC",
    "RIPPLE": "XRPUSD-OTC",
    "SHIBAINU": "SHIBUSD-OTC",
    "SHIBAINUUSDT": "SHIBUSD-OTC",
    "SOLANA": "SOLUSD-OTC",
    "TRON": "TRON-OTC",
    "WORLDCOIN": "WLDUSD-OTC",
    "AMZN": "AMAZON-OTC",
    "AMAZON": "AMAZON-OTC",
    "APPLE": "APPLE-OTC",
    "GOOGLE": "GOOGLE-OTC",
    "MICROSOFT": "MSFT-OTC",
    "MSFT": "MSFT-OTC",
    "TESLA": "TESLA-OTC",
    "BRENT": "UKOUSD-OTC",
    "CRUDEOILBRENT": "UKOUSD-OTC",
    "CRUDEOILWTI": "USOUSD-OTC",
    "SILVER": "XAGUSD-OTC",
    "WTI": "USOUSD-OTC",
    "US30": "US30-OTC",
    "US500": "US500-OTC",
    "AMZNALIBABA-OTC": "AMZN/ALIBABA-OTC",
    "AMZNEBAY-OTC": "AMZN/EBAY-OTC",
    "GER30UK100-OTC": "GER30/UK100-OTC",
    "GOOGLEMSFT-OTC": "GOOGLE/MSFT-OTC",
    "INTELIBM-OTC": "INTEL/IBM-OTC",
    "METAGOOGLE-OTC": "META/GOOGLE-OTC",
    "MSFTAAPL-OTC": "MSFT/AAPL-OTC",
    "NFLXAMZN-OTC": "NFLX/AMZN-OTC",
    "NVDAAMD-OTC": "NVDA/AMD-OTC",
    "OPENAI": "OpenAI-OTC",
    "OPENAI-OTC": "OpenAI-OTC",
    "TESLAFORD-OTC": "TESLA/FORD-OTC",
    "US100JP225-OTC": "US100/JP225-OTC",
    "US30JP225-OTC": "US30/JP225-OTC",
    "US500JP225-OTC": "US500/JP225-OTC",
    "XAUXAG-OTC": "XAU/XAG-OTC",
}

FOREX_RE = re.compile(r"^[A-Z]{6}$")


@dataclass
class ParsedTelegramSignal:
    active_raw: str
    expiration: str
    direction: str
    signal_time: str
    raw_text: str


def parse_signal(text: str) -> Optional[ParsedTelegramSignal]:
    active = re.search(r"Active:\s*(.+)", text, re.IGNORECASE)
    expiration = re.search(r"Expiration:\s*(M\d+)", text, re.IGNORECASE)
    direction = re.search(r"Direction:.*?(COMPRA|VENDA|CALL|PUT)", text, re.IGNORECASE)
    trade_time = re.search(r"Time:\s*(\d{2}:\d{2})", text, re.IGNORECASE)
    if not active or not direction or not trade_time:
        return None
    raw_direction = direction.group(1).upper()
    return ParsedTelegramSignal(
        active_raw=active.group(1).strip(),
        expiration=expiration.group(1).strip().upper() if expiration else "M1",
        direction="call" if raw_direction in {"COMPRA", "CALL"} else "put",
        signal_time=trade_time.group(1).strip(),
        raw_text=text,
    )


def normalize_active(active: str) -> str:
    value = active.upper().strip()
    value = value.replace(" ", "")
    value = value.replace("(OTC)", "-OTC")
    value = value.replace("_", "")
    value = value.replace("/", "")
    value = value.replace(".", "")
    return value.replace("--", "-")


def map_active_to_symbol(active: str) -> str:
    candidates = candidate_symbols_for_active(active)
    return candidates[0] if candidates else normalize_active(active)


def candidate_symbols_for_active(active: str) -> list[str]:
    raw = str(active or "").upper()
    is_otc = "(OTC)" in raw or raw.strip().endswith("-OTC")
    key = normalize_active(active)
    candidates: list[str] = []

    def add(symbol: str) -> None:
        symbol = str(symbol or "").strip()
        if symbol and symbol not in candidates:
            candidates.append(symbol)

    if key in CUSTOM_MAP:
        add(CUSTOM_MAP[key])
    if key.endswith("-OTC"):
        base = key[:-4]
        add(CUSTOM_MAP.get(base, key))
        add(key)
    if FOREX_RE.fullmatch(key):
        if is_otc:
            add(f"{key}-OTC")
            add(f"{key}-op")
        else:
            add(f"{key}-op")
            add(f"{key}-OTC")
    crypto_key = f"{key}USD"
    if crypto_key in CUSTOM_MAP:
        add(CUSTOM_MAP[crypto_key])
    add(key)
    return candidates


class TelegramSignalManager:
    def __init__(self, config: AppConfig, db: Database, engine: TradingEngine) -> None:
        self.config = config
        self.db = db
        self.engine = engine
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._last_error: Optional[str] = None
        self._latest_signal: dict[str, Any] = {}
        self._imported = 0
        self._mapped = 0
        self._signal_tasks: set[asyncio.Task] = set()
        self._broker_assets_cache: list[dict[str, Any]] = []
        self._broker_assets_cache_at = 0.0
        self._client: Any = None
        self._prime_on_connect = False
        self._scheduled_signal_keys: set[str] = set()

    async def startup(self) -> None:
        self.import_history()
        if self.config.telegram.enabled:
            await self.start()

    async def shutdown(self) -> None:
        await self.stop()

    def status(self, *, include_summary: bool = False) -> dict[str, Any]:
        data = {
            "enabled": self.config.telegram.enabled,
            "follow_signals": self.config.telegram.follow_signals,
            "running": self._running,
            "channel": self.config.telegram.channel,
            "latest_signal": self._latest_signal,
            "last_error": self._last_error,
            "imported": self._imported,
            "mapped": self._mapped,
            "min_history_signals": self.config.telegram.min_history_signals,
        }
        if include_summary:
            data["summary"] = self.db.telegram_asset_stats(min_signals=self.config.telegram.min_history_signals)
        return data

    async def update_controls(self, *, enabled: bool, follow_signals: bool) -> dict[str, Any]:
        was_enabled = self.config.telegram.enabled
        was_following = self.config.telegram.follow_signals
        self.config.telegram.enabled = bool(enabled)
        self.config.telegram.follow_signals = bool(follow_signals)
        if self.config.telegram.enabled:
            await self.start()
        else:
            await self.stop()
        if self.config.telegram.enabled and self.config.telegram.follow_signals and (not was_enabled or not was_following):
            self.schedule_prime_latest_pending_signal()
        self.db.add_event(
            "info",
            "telegram",
            "Telegram controls updated",
            {"enabled": self.config.telegram.enabled, "follow_signals": self.config.telegram.follow_signals},
        )
        return self.status()

    async def start(self) -> None:
        if self._task and not self._task.done():
            self._running = True
            return
        self._running = True
        self._prime_on_connect = True
        self._task = asyncio.create_task(self._listen_loop())

    async def stop(self) -> None:
        self._running = False
        task = self._task
        self._task = None
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self.cancel_pending_orders()

    async def prime_latest_pending_signal(self) -> dict[str, Any]:
        self._prime_on_connect = True
        if self._client is not None:
            await self._safe_prime_latest_pending_signal(self._client)
        return self.status()

    def schedule_prime_latest_pending_signal(self) -> None:
        self._prime_on_connect = True
        if self._client is None:
            return
        task = asyncio.create_task(self._safe_prime_latest_pending_signal(self._client))
        self._signal_tasks.add(task)
        task.add_done_callback(self._signal_tasks.discard)

    def cancel_pending_orders(self) -> None:
        for signal_task in list(self._signal_tasks):
            signal_task.cancel()
        self._signal_tasks.clear()
        self._scheduled_signal_keys.clear()

    def import_history(self) -> dict[str, int]:
        allowed = self._iq_symbols_from_runtime()
        imported = 0
        mapped = 0
        for path in self._history_files()[-self.config.telegram.import_history_limit :]:
            try:
                rows = path.read_text(encoding="utf-8").splitlines()
            except OSError:
                continue
            for line in rows:
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                signal = payload.get("signal") or {}
                active_raw = str(signal.get("active_raw") or signal.get("active") or "")
                raw_symbol = str(signal.get("symbol") or map_active_to_symbol(active_raw))
                symbol = self._choose_allowed_symbol(
                    candidate_symbols_for_active(active_raw) if active_raw else [raw_symbol],
                    allowed,
                ) or raw_symbol
                direction = str(signal.get("direction") or "").lower()
                if direction not in {"call", "put"} or not symbol:
                    continue
                is_mapped = symbol in allowed
                self.db.upsert_telegram_signal(
                    source_id=str(payload.get("id") or f"{path.name}:{imported}"),
                    received_at=str(signal.get("received_at") or payload.get("created_at") or utc_now()),
                    provider=str(payload.get("provider") or signal.get("channel") or self.config.telegram.channel),
                    active_raw=active_raw,
                    symbol=symbol,
                    direction=direction,
                    expiration=str(signal.get("expiration") or "M1"),
                    signal_time=str(signal.get("signal_time") or ""),
                    entry_time=str(signal.get("entry_time") or ""),
                    raw_text=str(signal.get("raw_text") or ""),
                    mapped=is_mapped,
                    source="history",
                    status="mapped" if is_mapped else "unmapped",
                    payload=payload,
                )
                imported += 1
                if is_mapped:
                    mapped += 1
        self._imported = imported
        self._mapped = mapped
        self.db.add_event("info", "telegram", "Telegram history imported", {"imported": imported, "mapped": mapped})
        return {"imported": imported, "mapped": mapped}

    def _history_files(self) -> list[Path]:
        base = self._resolve_path(self.config.telegram.source_logs_path)
        if not base.exists():
            return []
        return sorted(base.glob("*/*.jsonl"))

    def _iq_symbols_from_runtime(self) -> set[str]:
        symbols = set(self.config.trading.assets)
        symbols.add(self.config.trading.asset)
        runtime_path = self._resolve_path(self.config.telegram.runtime_state_path)
        try:
            runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
            symbols.update(str(item) for item in runtime.get("open_symbols", []) if item)
        except (OSError, json.JSONDecodeError):
            pass
        return symbols

    def _resolve_path(self, value: str) -> Path:
        path = Path(value)
        if path.is_absolute():
            return path
        return ROOT_DIR / path

    async def _listen_loop(self) -> None:
        try:
            from telethon import TelegramClient, events
        except Exception as exc:
            self._last_error = f"telethon_import_failed:{exc}"
            self.db.add_event("error", "telegram", "Telethon import failed", {"error": str(exc)})
            self._running = False
            return

        try:
            api_id = int(self.config.telegram.api_id)
            api_hash = str(self.config.telegram.api_hash)
            session = str(self._resolve_path(self.config.telegram.session_path))
            channel_filter = str(self.config.telegram.channel or "")
            client = TelegramClient(session, api_id, api_hash)
            await client.connect()
            self._client = client
            if not await client.is_user_authorized():
                self._last_error = "telegram_session_not_authorized"
                self.db.add_event("error", "telegram", "Telegram session is not authorized", {})
                self._running = False
                await client.disconnect()
                return

            @client.on(events.NewMessage)
            async def on_message(event: Any) -> None:
                chat = await event.get_chat()
                title = str(getattr(chat, "title", "") or "")
                if channel_filter and channel_filter.lower() not in title.lower():
                    return
                parsed = parse_signal(str(event.raw_text or ""))
                if not parsed:
                    return
                await self._handle_live_signal(parsed, title)

            self._last_error = None
            self.db.add_event("info", "telegram", "Telegram listener started", {"channel": channel_filter})
            if self.config.telegram.follow_signals or self._prime_on_connect:
                self.schedule_prime_latest_pending_signal()
            await client.run_until_disconnected()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._last_error = str(exc)
            self.db.add_event("error", "telegram", "Telegram listener failed", {"error": str(exc)})
        finally:
            self._client = None
            self._running = False

    async def _safe_prime_latest_pending_signal(self, client: Any) -> None:
        try:
            await asyncio.wait_for(self._prime_latest_pending_signal(client), timeout=8)
        except asyncio.TimeoutError:
            self._last_error = "telegram_latest_signal_prime_timeout"
            self.db.add_event("warning", "telegram", "Telegram latest signal prime timed out", {})
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._last_error = str(exc)
            self.db.add_event("warning", "telegram", "Telegram latest signal prime failed", {"error": str(exc)})

    async def _prime_latest_pending_signal(self, client: Any) -> None:
        self._prime_on_connect = False
        channel_filter = str(self.config.telegram.channel or "")
        try:
            entity = await self._find_channel_entity(client, channel_filter)
            if entity is None:
                self.db.add_event("warning", "telegram", "Telegram latest signal prime skipped", {"reason": "channel_not_found"})
                return
            messages = await client.get_messages(entity, limit=20)
        except Exception as exc:
            self.db.add_event("warning", "telegram", "Telegram latest signal prime failed", {"error": str(exc)})
            return

        latest_parsed: Optional[tuple[ParsedTelegramSignal, Any]] = None
        for message in messages:
            parsed = parse_signal(str(getattr(message, "raw_text", "") or ""))
            if parsed:
                latest_parsed = (parsed, message)
                break
        if latest_parsed is None:
            self.db.add_event("info", "telegram", "Telegram latest signal prime skipped", {"reason": "no_signal_in_recent_messages"})
            return

        parsed, message = latest_parsed
        seconds_until_entry = self._seconds_until_entry(parsed.signal_time)
        if seconds_until_entry < 0:
            self._latest_signal = {
                "received_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "channel": channel_filter,
                "active_raw": parsed.active_raw,
                "symbol": map_active_to_symbol(parsed.active_raw),
                "direction": parsed.direction,
                "expiration": parsed.expiration,
                "signal_time": parsed.signal_time,
                "entry_time": self._entry_time_text(parsed.signal_time),
                "raw_text": parsed.raw_text,
                "mapped": False,
                "order_status": "skipped",
                "order_message": "latest_signal_entry_time_passed",
            }
            self.db.add_event(
                "info",
                "telegram",
                "Telegram latest signal ignored because entry time passed",
                self._latest_signal,
            )
            return

        source_id = f"prime:{getattr(message, 'id', '')}:{parsed.signal_time}:{parsed.active_raw}:{parsed.direction}"
        self.db.add_event(
            "info",
            "telegram",
            "Telegram latest pending signal found",
            {"active": parsed.active_raw, "direction": parsed.direction, "signal_time": parsed.signal_time},
        )
        await self._handle_live_signal(
            parsed,
            channel_filter,
            source="prime",
            source_id=source_id,
            received_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )

    async def _find_channel_entity(self, client: Any, channel_filter: str) -> Any:
        if not channel_filter:
            return None
        async for dialog in client.iter_dialogs(limit=100):
            title = str(getattr(dialog, "name", "") or "")
            if channel_filter.lower() in title.lower():
                return dialog.entity
        try:
            return await client.get_entity(channel_filter)
        except Exception:
            return None

    async def _handle_live_signal(
        self,
        parsed: ParsedTelegramSignal,
        channel: str,
        *,
        source: str = "live",
        source_id: Optional[str] = None,
        received_at: Optional[str] = None,
    ) -> None:
        resolved = await self._resolve_live_symbol(parsed.active_raw)
        symbol = resolved["symbol"]
        mapped = bool(resolved["mapped"])
        received_at = received_at or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        source_id = source_id or f"live:{channel}:{parsed.signal_time}:{parsed.active_raw}:{parsed.direction}"
        signal = {
            "received_at": received_at,
            "channel": channel,
            "active_raw": parsed.active_raw,
            "symbol": symbol,
            "direction": parsed.direction,
            "expiration": parsed.expiration,
            "signal_time": parsed.signal_time,
            "entry_time": self._entry_time_text(parsed.signal_time),
            "raw_text": parsed.raw_text,
            "mapped": mapped,
            "mapped_reason": resolved["reason"],
            "candidates": resolved["candidates"],
            "order_status": "mapped" if mapped else "skipped",
            "order_message": resolved["reason"] if mapped else f"asset_not_open_or_mapped:{resolved['reason']}",
            "source": source,
            "source_id": source_id,
        }
        self._latest_signal = signal
        self.db.upsert_telegram_signal(
            source_id=source_id,
            received_at=signal["received_at"],
            provider=channel,
            active_raw=parsed.active_raw,
            symbol=symbol,
            direction=parsed.direction,
            expiration=parsed.expiration,
            signal_time=parsed.signal_time,
            entry_time=signal["entry_time"],
            raw_text=parsed.raw_text,
            mapped=mapped,
            source=source,
            status="mapped" if mapped else "unmapped",
            payload=signal,
        )
        self.db.add_event("info", "telegram", "Telegram signal received", signal)
        if not mapped:
            self.db.add_event(
                "warning",
                "telegram",
                "Telegram signal skipped because asset is not open/mapped",
                signal,
            )
            return
        if not self.config.telegram.follow_signals:
            self._latest_signal = {
                **signal,
                "order_status": "listen_only",
                "order_message": "follow_signals_disabled",
            }
            return
        signal_key = self._signal_key(signal)
        if signal_key in self._scheduled_signal_keys:
            self._latest_signal = {**signal, "order_status": "skipped", "order_message": "duplicate_signal_already_scheduled"}
            self.db.add_event("info", "telegram", "Telegram signal skipped because it is already scheduled", self._latest_signal)
            return
        self._scheduled_signal_keys.add(signal_key)
        self._latest_signal = {**signal, "order_status": "waiting", "order_message": "waiting_for_entry_time"}
        task = asyncio.create_task(self._place_at_entry(signal))
        self._signal_tasks.add(task)
        task.add_done_callback(self._signal_tasks.discard)

    def _signal_key(self, signal: dict[str, Any]) -> str:
        return "|".join(
            [
                str(signal.get("source_id") or ""),
                str(signal.get("channel") or ""),
                str(signal.get("signal_time") or ""),
                str(signal.get("active_raw") or signal.get("symbol") or ""),
                str(signal.get("direction") or ""),
            ]
        )

    async def _resolve_live_symbol(self, active_raw: str) -> dict[str, Any]:
        candidates = candidate_symbols_for_active(active_raw)
        instrument = self.config.trading.instrument.lower().strip()
        broker_items = await self._broker_assets()
        for candidate in candidates:
            for item in broker_items:
                if (
                    str(item.get("name")) == candidate
                    and str(item.get("type", "")).lower() == instrument
                    and bool(item.get("open"))
                ):
                    return {
                        "symbol": candidate,
                        "mapped": True,
                        "reason": f"broker_open_{instrument}",
                        "candidates": candidates,
                    }

        allowed = self._iq_symbols_from_runtime()
        runtime_symbol = self._choose_allowed_symbol(candidates, allowed)
        if runtime_symbol:
            return {
                "symbol": runtime_symbol,
                "mapped": True,
                "reason": "runtime_open_symbols",
                "candidates": candidates,
            }

        return {
            "symbol": candidates[0] if candidates else normalize_active(active_raw),
            "mapped": False,
            "reason": f"not_open_for_{instrument}",
            "candidates": candidates,
        }

    async def _broker_assets(self) -> list[dict[str, Any]]:
        now = time.monotonic()
        if self._broker_assets_cache and now - self._broker_assets_cache_at < 30:
            return self._broker_assets_cache
        try:
            data = await self.engine.list_broker_assets()
            items = data.get("items", []) if isinstance(data, dict) else []
            self._broker_assets_cache = [item for item in items if isinstance(item, dict)]
            self._broker_assets_cache_at = now
        except Exception as exc:
            self.db.add_event("warning", "telegram", "Broker asset lookup failed for Telegram mapping", {"error": str(exc)})
        return self._broker_assets_cache

    def _choose_allowed_symbol(self, candidates: list[str], allowed: set[str]) -> str:
        for candidate in candidates:
            if candidate in allowed:
                return candidate
        return ""

    async def _place_at_entry(self, signal: dict[str, Any]) -> None:
        if not self.config.telegram.enabled or not self.config.telegram.follow_signals:
            payload = {**signal, "order_status": "cancelled", "order_message": "telegram_disabled_before_wait"}
            self._latest_signal = payload
            self.db.add_event("info", "telegram", "Telegram signal cancelled before wait", payload)
            return
        wait_seconds = self._seconds_until_entry(signal.get("signal_time", ""))
        if wait_seconds < 0:
            payload = {**signal, "order_status": "skipped", "order_message": "entry_time_already_passed"}
            self._latest_signal = payload
            self.db.add_event("info", "telegram", "Telegram signal skipped because entry time already passed", payload)
            return
        if wait_seconds > 0:
            await asyncio.sleep(wait_seconds)
        if not self.config.telegram.enabled or not self.config.telegram.follow_signals:
            payload = {**signal, "order_status": "cancelled", "order_message": "telegram_disabled_before_order"}
            self._latest_signal = payload
            self.db.add_event("info", "telegram", "Telegram signal cancelled before order", payload)
            return
        if not self.engine.status(include_broker=False).get("running"):
            payload = {**signal, "order_status": "skipped", "order_message": "bot_is_stopped"}
            self._latest_signal = payload
            self.db.add_event("info", "telegram", "Telegram signal skipped because bot is stopped", payload)
            return
        self._latest_signal = {**signal, "order_status": "opening", "order_message": "sending_order"}
        result = await self.engine.external_signal_trade(
            asset=signal["symbol"],
            direction=signal["direction"],
            duration_minutes=self._expiry_minutes(signal.get("expiration", "M1")),
            reason="telegram_signal",
            raw_signal=signal,
        )
        placed = bool(result.get("placed"))
        payload = {
            **signal,
            **result,
            "order_status": "ordered" if placed else "skipped",
            "order_message": "order_sent" if placed else str(result.get("reason") or "order_not_placed"),
        }
        self._latest_signal = payload
        self.db.add_event("info" if placed else "warning", "telegram", "Telegram signal order processed", payload)

    def _seconds_until_entry(self, signal_time: str) -> float:
        try:
            hour, minute = [int(part) for part in signal_time.split(":", 1)]
        except ValueError:
            return 0.0
        now = datetime.now(ZoneInfo("Asia/Bangkok"))
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        target -= timedelta(seconds=self.config.telegram.entry_lead_seconds)
        if target < now - timedelta(seconds=20):
            return -1.0
        return max(0.0, (target - now).total_seconds())

    def _entry_time_text(self, signal_time: str) -> str:
        try:
            hour, minute = [int(part) for part in signal_time.split(":", 1)]
            target = datetime.now(ZoneInfo("Asia/Bangkok")).replace(
                hour=hour,
                minute=minute,
                second=0,
                microsecond=0,
            )
            target -= timedelta(seconds=self.config.telegram.entry_lead_seconds)
            return target.strftime("%H:%M:%S.%f")[:-3]
        except ValueError:
            return ""

    def _expiry_minutes(self, expiration: str) -> int:
        match = re.search(r"M(\d+)", str(expiration or ""), re.IGNORECASE)
        if not match:
            return self.config.telegram.default_expiry_minutes
        return max(1, min(int(match.group(1)), 60))
