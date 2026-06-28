from __future__ import annotations

import threading
import time
from typing import Any, Optional

from app.broker.base import BrokerError, BrokerOrder, BrokerStatus, Candle
from app.config import AppConfig


class IQOptionBroker:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self._client: Optional[Any] = None
        self._connected = False
        self._last_balance: Optional[float] = None
        self._last_message = ""

        self._assets_cache: list[dict[str, Any]] = []
        self._assets_cache_at = 0.0
        self._active_id_cache: dict[str, dict[str, int]] = {}

    def _load_client_class(self) -> Any:
        try:
            from iqoptionapi.stable_api import IQ_Option
        except Exception as exc:
            raise BrokerError(
                "Cannot import iqoptionapi.stable_api. Install requirements first."
            ) from exc
        return IQ_Option

    def connect(self) -> BrokerStatus:
        if not self.config.broker.email or not self.config.broker.password:
            raise BrokerError("IQ Option email/password are empty in config.yaml")

        IQ_Option = self._load_client_class()
        self._client = IQ_Option(self.config.broker.email, self.config.broker.password)

        check, reason = self._client.connect()

        if check is False and reason == "2FA" and self.config.broker.two_factor_code:
            check, reason = self._client.connect_2fa(self.config.broker.two_factor_code)

        if not check:
            self._connected = False
            self._last_message = str(reason)
            raise BrokerError(f"IQ Option connect failed: {reason}")

        self._client.change_balance(self.config.broker.account_type)

        self._connected = True
        self._last_message = "IQ Option connected"

        return BrokerStatus(
            connected=True,
            mode="iqoption",
            account_type=self.config.broker.account_type,
            balance=self._last_balance,
            message=self._last_message,
        )

    def _refresh_active_codes(self) -> None:
        if self._client is None:
            return
        update = getattr(self._client, "update_ACTIVES_OPCODE", None)
        if callable(update):
            update()

    def status(self) -> BrokerStatus:
        return BrokerStatus(
            connected=self._connected,
            mode="iqoption",
            account_type=self.config.broker.account_type,
            balance=self._last_balance,
            message=self._last_message,
        )

    def refresh_balance(self) -> BrokerStatus:
        if self._client is None or not self._connected:
            return self.status()
        self._last_balance = float(self._client.get_balance())
        return self.status()

    def change_account_type(self, account_type: str) -> BrokerStatus:
        account_type = account_type.upper().strip()
        if account_type not in {"PRACTICE", "REAL", "TOURNAMENT"}:
            raise BrokerError("account_type must be PRACTICE, REAL, or TOURNAMENT")
        client = self._ensure_connected()
        client.change_balance(account_type)
        self.config.broker.account_type = account_type
        self._last_message = f"Switched to {account_type}"
        return self.refresh_balance()

    def disconnect(self) -> BrokerStatus:
        client = self._client
        for target in (client, getattr(client, "api", None)):
            if target is None:
                continue
            for method_name in ("close", "disconnect", "logout"):
                method = getattr(target, method_name, None)
                if callable(method):
                    try:
                        method()
                    except Exception:
                        pass
                    break
        self._client = None
        self._connected = False
        self._last_message = "IQ Option disconnected"
        return self.status()

    def _ensure_connected(self) -> Any:
        if self._client is None or not self._connected:
            self.connect()
        if self._client is None:
            raise BrokerError("IQ Option client is not available")
        return self._client

    def get_candles(self, asset: str, interval_sec: int, count: int) -> list[Candle]:
        return self.get_candles_until(asset, interval_sec, count, time.time())

    def get_candles_until(self, asset: str, interval_sec: int, count: int, endtime: float) -> list[Candle]:
        client = self._ensure_connected()
        raw_candles = client.get_candles(asset, interval_sec, count, endtime)
        return self._parse_candles(raw_candles)

    def _parse_candles(self, raw_candles: Any) -> list[Candle]:
        candles: list[Candle] = []
        for item in raw_candles or []:
            candles.append(
                Candle(
                    timestamp=int(item.get("from") or item.get("at") or time.time()),
                    open=float(item.get("open", item.get("close", 0))),
                    high=float(item.get("max", item.get("high", item.get("close", 0)))),
                    low=float(item.get("min", item.get("low", item.get("close", 0)))),
                    close=float(item.get("close", 0)),
                    volume=float(item.get("volume", 0) or 0),
                )
            )
        return candles

    def _call_with_timeout(self, label: str, fn: Any, timeout_sec: float = 8.0) -> tuple[bool, Any]:
        box: dict[str, Any] = {
            "value": None,
            "error": None,
        }

        def worker() -> None:
            try:
                box["value"] = fn()
            except Exception as exc:
                box["error"] = exc

        thread = threading.Thread(target=worker, daemon=True)
        started = time.perf_counter()
        thread.start()
        thread.join(timeout=timeout_sec)
        elapsed = time.perf_counter() - started

        if thread.is_alive():
            print(f"[IQ ASSET] {label} timeout after {elapsed:.3f}s", flush=True)
            return False, "timeout"

        if box["error"] is not None:
            print(f"[IQ ASSET] {label} error: {box['error']}", flush=True)
            return False, box["error"]

        return True, box["value"]


    def _items_from_init_v2(self, raw: Any) -> list[dict[str, Any]]:
        if not isinstance(raw, dict):
            return []

        by_name: dict[str, dict[str, Any]] = {}
        next_active_cache: dict[str, dict[str, int]] = {}

        for option_type in ("binary", "turbo"):
            actives = raw.get(option_type, {}).get("actives", {})
            if not isinstance(actives, dict):
                continue

            for active_key, active in actives.items():
                if not isinstance(active, dict):
                    continue

                raw_name = str(active.get("name") or "")
                if "." in raw_name:
                    name = raw_name.split(".", 1)[1]
                else:
                    name = raw_name

                name = name.strip()
                if not name:
                    continue

                enabled = bool(active.get("enabled"))
                suspended = bool(active.get("is_suspended"))
                is_open = enabled and not suspended

                active_id = self._parse_active_id(
                    active_key,
                    active.get("id"),
                    active.get("active_id"),
                    active.get("activeId"),
                )

                item = by_name.setdefault(
                    name,
                    {
                        "name": name,
                        "type": "binary",
                        "open": False,
                        "raw_types": [],
                        "active_ids": {},
                    },
                )

                item["open"] = bool(item["open"] or is_open)

                if option_type not in item["raw_types"]:
                    item["raw_types"].append(option_type)

                if active_id is not None:
                    item["active_ids"][option_type] = active_id
                    next_active_cache.setdefault(name, {})[option_type] = active_id

        if next_active_cache:
            self._active_id_cache.update(next_active_cache)

        items = list(by_name.values())
        items.sort(key=lambda item: (not item["open"], item["name"]))
        return items


    def list_assets(self) -> dict:
        client = self._ensure_connected()
        now = time.monotonic()

        # cache สั้น ๆ กัน Telegram เรียกถี่แล้วไปยิง IQOption รัว
        # แต่ถ้า cache เก่ามาจากช่วงที่ยัง parse active_ids ไม่ได้ ให้บังคับ refresh ใหม่
        cache_has_active_ids = any(
            bool(item.get("active_ids"))
            for item in self._assets_cache
            if isinstance(item, dict)
        )
        if self._assets_cache and cache_has_active_ids and now - self._assets_cache_at < 30:
            return {
                "broker": "iqoption",
                "items": self._assets_cache,
                "source": "cache_get_all_init_v2",
            }

        ok, raw = self._call_with_timeout(
            "get_all_init_v2",
            client.get_all_init_v2,
            timeout_sec=8.0,
        )

        items = self._items_from_init_v2(raw) if ok else []

        if items:
            self._assets_cache = items
            self._assets_cache_at = now

            open_count = sum(1 for item in items if item.get("open"))
            active_id_count = sum(
                len(item.get("active_ids") or {})
                for item in items
                if isinstance(item, dict)
            )
            print(
                f"[IQ ASSET] get_all_init_v2 items={len(items)} open={open_count} active_ids={active_id_count}",
                flush=True,
            )

            return {
                "broker": "iqoption",
                "items": items,
                "source": "get_all_init_v2",
            }

        # ถ้ารอบนี้ดึงไม่ได้ แต่เคยมี cache ให้คืน cache เดิม
        if self._assets_cache:
            print(
                f"[IQ ASSET] fallback stale cache items={len(self._assets_cache)}",
                flush=True,
            )
            return {
                "broker": "iqoption",
                "items": self._assets_cache,
                "source": "stale_cache_get_all_init_v2",
            }

        print("[IQ ASSET] get_all_init_v2 returned no assets", flush=True)
        return {
            "broker": "iqoption",
            "items": [],
            "source": "empty_get_all_init_v2",
        }

    def place_order(
        self,
        asset: str,
        instrument: str,
        direction: str,
        amount: float,
        duration_minutes: int,
    ) -> BrokerOrder:
        client = self._ensure_connected()

        direction = direction.lower().strip()
        if direction not in {"call", "put"}:
            raise BrokerError("direction must be call or put")

        ok = False
        order_id: Optional[str] = None
        first_error: Optional[str] = None

        # ต้องเลือก active_id ตาม duration ก่อน
        # 1-5 นาทีควรใช้ turbo active id
        active_id = self._get_active_id_for_asset(
            asset,
            instrument,
            duration_minutes,
        )

        if active_id is not None:
            print(
                f"[IQ ORDER] buyv3 asset={asset} active_id={active_id} "
                f"direction={direction} amount={amount} duration={duration_minutes}",
                flush=True,
            )

            ok, order_id = self._buy_binary_by_active_id(
                asset=asset,
                active_id=active_id,
                amount=amount,
                direction=direction,
                duration_minutes=duration_minutes,
            )

            if not ok:
                first_error = str(order_id or "buyv3 rejected")
                print(
                    f"[IQ ORDER] buyv3 failed asset={asset} active_id={active_id}: {first_error}",
                    flush=True,
                )

        # fallback เฉพาะกรณีไม่มี active_id หรือ buyv3 fail
        # บาง symbol ที่อยู่ใน OP_code.ACTIVES อาจยังซื้อผ่าน client.buy ได้
        if not ok:
            try:
                print(
                    f"[IQ ORDER] fallback client.buy asset={asset} "
                    f"direction={direction} amount={amount} duration={duration_minutes}",
                    flush=True,
                )

                result = client.buy(amount, asset, direction, duration_minutes)

                if isinstance(result, tuple) and len(result) == 2:
                    ok, raw_order_id = result
                    order_id = str(raw_order_id) if raw_order_id is not None else None
                else:
                    first_error = f"invalid buy result: {result!r}"

            except KeyError as exc:
                first_error = f"missing static active code: {exc}"
                print(
                    f"[IQ ORDER] client.buy KeyError asset={asset}: {exc}",
                    flush=True,
                )

            except Exception as exc:
                first_error = str(exc)
                print(
                    f"[IQ ORDER] client.buy failed asset={asset}: {exc}",
                    flush=True,
                )

        if not ok:
            raise BrokerError(
                f"IQ Option order rejected: {order_id or first_error or 'unknown'}"
            )

        try:
            candles = self.get_candles(asset, self.config.trading.candle_interval_sec, 1)
            entry_price = candles[-1].close if candles else None
        except Exception as exc:
            print(f"[IQ ORDER] entry price lookup skipped asset={asset}: {exc}", flush=True)
            entry_price = None

        actual_instrument = "turbo-option" if duration_minutes <= 5 else "binary-option"

        return BrokerOrder(
            order_id=str(order_id),
            asset=asset,
            instrument=instrument,
            direction=direction,
            amount=amount,
            duration_minutes=duration_minutes,
            entry_price=entry_price,
            raw={
                "broker": "iqoption",
                "raw_order_id": order_id,
                "instrument_type": actual_instrument,
                "active_id": active_id,
            },
        )

    def resolve_order(
        self,
        order_id: str,
        instrument: str,
        duration_minutes: Optional[int] = None,
    ) -> tuple[Optional[float], dict]:
        client = self._ensure_connected()
        close_event_result = self._resolve_from_option_close_cache(client, order_id)
        if close_event_result is not None:
            return close_event_result

        history_result = self._resolve_from_history(client, order_id, instrument, duration_minutes)
        if history_result is not None:
            return history_result

        betinfo_result = self._resolve_from_betinfo(client, order_id)
        if betinfo_result is not None:
            return betinfo_result

        close_event_result = self._resolve_from_option_close_cache(client, order_id)
        if close_event_result is not None:
            return close_event_result

        return None, {
            "broker": "iqoption",
            "status": "pending",
            "message": "order result is not available from IQ Option yet",
        }

    def _resolve_from_option_close_cache(self, client: Any, order_id: str) -> Optional[tuple[float, dict]]:
        api = getattr(client, "api", None)
        if api is None:
            return None
        order_key = self._order_key(order_id)

        order_binary = getattr(api, "order_binary", {}) or {}
        payload = order_binary.get(order_key) or order_binary.get(str(order_key))
        result = self._profit_from_binary_payload(payload)
        if result is not None:
            profit, response = result
            response.update({"broker": "iqoption", "status": "closed", "source": "order_binary"})
            return profit, response

        socket_closed = getattr(api, "socket_option_closed", {}) or {}
        payload = socket_closed.get(order_key) or socket_closed.get(str(order_key))
        if isinstance(payload, dict) and isinstance(payload.get("msg"), dict):
            result = self._profit_from_binary_payload(payload["msg"])
            if result is not None:
                profit, response = result
                response.update({"broker": "iqoption", "status": "closed", "source": "socket_option_closed"})
                return profit, response

        order_async = getattr(api, "order_async", {}) or {}
        async_payload = order_async.get(order_key) or order_async.get(str(order_key))
        if isinstance(async_payload, dict):
            closed = async_payload.get("option-closed")
            if isinstance(closed, dict) and isinstance(closed.get("msg"), dict):
                result = self._profit_from_binary_payload(closed["msg"])
                if result is not None:
                    profit, response = result
                    response.update({"broker": "iqoption", "status": "closed", "source": "option_closed"})
                    return profit, response
        return None

    def _resolve_from_history(
        self,
        client: Any,
        order_id: str,
        instrument: str,
        duration_minutes: Optional[int] = None,
    ) -> Optional[tuple[float, dict]]:
        end = int(time.time())
        start = end - 24 * 60 * 60
        for instrument_type in self._history_instrument_types(instrument, duration_minutes):
            check, data = self._get_position_history_v2(client, instrument_type, 100, 0, start, end, timeout=4)
            if not check or not data:
                continue

            for position in data.get("positions", []):
                if not self._payload_contains_order_id(position, order_id):
                    continue
                if position.get("status") != "closed":
                    return None
                profit = self._profit_from_position(position)
                if profit is None:
                    return None
                response = {
                    "broker": "iqoption",
                    "status": "closed",
                    "source": "position_history_v2",
                    "instrument_type": instrument_type,
                    "external_id": position.get("external_id"),
                    "close_reason": position.get("close_reason"),
                    "entry_price": position.get("open_quote"),
                    "exit_price": position.get("close_quote"),
                    "invest": position.get("invest"),
                    "close_profit": position.get("close_profit"),
                    "pnl": profit,
                }
                return float(profit), response
        return None

    def _resolve_from_betinfo(self, client: Any, order_id: str, timeout: float = 4.0) -> Optional[tuple[float, dict]]:
        api = getattr(client, "api", None)
        if api is None:
            return None
        try:
            api.game_betinfo.isSuccessful = None
            api.get_betinfo(self._order_key(order_id))
            deadline = time.time() + timeout
            while api.game_betinfo.isSuccessful is None and time.time() < deadline:
                time.sleep(0.05)
            if api.game_betinfo.isSuccessful is not True:
                return None
            data = api.game_betinfo.dict
        except Exception:
            return None

        try:
            bet = data["result"]["data"][str(self._order_key(order_id))]
        except Exception:
            return None
        win = str(bet.get("win", "")).lower()
        if not win:
            return None
        profit = float(bet.get("profit", 0)) - float(bet.get("deposit", 0))
        return profit, {
            "broker": "iqoption",
            "status": "closed",
            "source": "api_game_betinfo",
            "win": win,
            "profit": bet.get("profit"),
            "deposit": bet.get("deposit"),
            "raw": bet,
        }

    def _get_position_history_v2(
        self,
        client: Any,
        instrument_type: str,
        limit: int,
        offset: int,
        start: int,
        end: int,
        *,
        timeout: float,
    ) -> tuple[bool, Optional[dict]]:
        api = getattr(client, "api", None)
        if api is None:
            return False, None
        try:
            api.position_history_v2 = None
            api.get_position_history_v2(instrument_type, limit, offset, start, end)
            deadline = time.time() + timeout
            while api.position_history_v2 is None and time.time() < deadline:
                time.sleep(0.05)
            if api.position_history_v2 is None:
                return False, None
            if api.position_history_v2.get("status") == 2000:
                return True, api.position_history_v2.get("msg")
        except Exception:
            return False, None
        return False, None

    def _history_instrument_types(self, instrument: str, duration_minutes: Optional[int]) -> list[str]:
        preferred = "turbo-option" if duration_minutes is not None and duration_minutes <= 5 else {
            "turbo": "turbo-option",
            "binary": "binary-option",
        }.get(instrument, "turbo-option")
        types = [preferred, "turbo-option", "binary-option"]
        ordered: list[str] = []
        for item in types:
            if item not in ordered:
                ordered.append(item)
        return ordered

    def _profit_from_position(self, position: dict[str, Any]) -> Optional[float]:
        for key in ("pnl", "pnl_realized"):
            if position.get(key) is not None:
                return float(position[key])
        if position.get("close_profit") is not None and position.get("invest") is not None:
            return float(position["close_profit"]) - float(position["invest"])
        return None

    def _profit_from_binary_payload(self, payload: Any) -> Optional[tuple[float, dict]]:
        if not isinstance(payload, dict):
            return None
        win = str(payload.get("win", "")).lower()
        amount = self._first_number(payload, "sum", "amount", "deposit", "invest")
        win_amount = self._first_number(payload, "win_amount", "profit", "close_profit")
        if not win and win_amount is None:
            return None
        if win in {"equal", "draw"}:
            profit = 0.0
        elif win in {"loose", "lose", "loss", "lost"}:
            profit = -abs(float(amount or 0))
        elif win == "win" and win_amount is not None and amount is not None:
            profit = float(win_amount) - float(amount)
        elif win_amount is not None and amount is not None:
            profit = float(win_amount) - float(amount)
        else:
            return None
        return profit, {
            "win": win,
            "sum": amount,
            "win_amount": win_amount,
            "raw": payload,
        }

    def _first_number(self, payload: dict[str, Any], *keys: str) -> Optional[float]:
        for key in keys:
            value = payload.get(key)
            if value is not None:
                try:
                    return float(value)
                except (TypeError, ValueError):
                    continue
        return None

    def _payload_contains_order_id(self, payload: Any, order_id: str) -> bool:
        target = str(self._order_key(order_id))
        for value in self._id_values(payload):
            if str(value) == target:
                return True
        return False

    def _id_values(self, payload: Any) -> list[Any]:
        values: list[Any] = []
        if isinstance(payload, dict):
            for key, value in payload.items():
                if "id" in str(key).lower() and not isinstance(value, (dict, list)):
                    values.append(value)
                values.extend(self._id_values(value))
        elif isinstance(payload, list):
            for item in payload:
                values.extend(self._id_values(item))
        return values

    def _order_key(self, order_id: str) -> Any:
        try:
            return int(order_id)
        except (TypeError, ValueError):
            return str(order_id)
        
    def _get_static_active_id(self, asset: str) -> Optional[int]:
        try:
            import iqoptionapi.constants as OP_code

            active_id = OP_code.ACTIVES.get(asset)
            return int(active_id) if active_id is not None else None
        except Exception:
            return None


    def _get_active_id_for_asset(
        self,
        asset: str,
        instrument: str,
        duration_minutes: int,
    ) -> Optional[int]:
        asset = str(asset or "").strip()
        if not asset:
            return None

        # IQ Option 1-5 นาทีมักต้องใช้ turbo active id
        preferred_type = "turbo" if int(duration_minutes or 1) <= 5 else "binary"

        type_map = self._active_id_cache.get(asset) or {}

        active_id = type_map.get(preferred_type)
        if active_id is not None:
            return int(active_id)

        # fallback: ถ้า preferred ไม่มี ให้ลองอีก type
        for fallback_type in ("turbo", "binary"):
            active_id = type_map.get(fallback_type)
            if active_id is not None:
                return int(active_id)

        # force refresh list_assets เพื่อเติม active id cache
        try:
            self._assets_cache = []
            self._assets_cache_at = 0.0
            self.list_assets()
        except Exception as exc:
            print(f"[IQ ORDER] active id refresh failed for {asset}: {exc}", flush=True)

        type_map = self._active_id_cache.get(asset) or {}

        active_id = type_map.get(preferred_type)
        if active_id is not None:
            return int(active_id)

        for fallback_type in ("turbo", "binary"):
            active_id = type_map.get(fallback_type)
            if active_id is not None:
                return int(active_id)

        return None


    def _buy_binary_by_active_id(
        self,
        asset: str,
        active_id: int,
        amount: float,
        direction: str,
        duration_minutes: int,
    ) -> tuple[bool, Optional[str]]:
        client = self._ensure_connected()
        req_id = f"buy_dynamic_{int(time.time() * 1000)}_{threading.get_ident()}"
        api = client.api

        try:
            api.buy_multi_option = {}
            api.buy_successful = None
            api.result = None

            api.buyv3(
                float(amount),
                int(active_id),
                str(direction).lower(),
                int(duration_minutes),
                req_id,
            )

            started = time.time()
            order_id = None

            while api.result is None or order_id is None:
                payload = api.buy_multi_option.get(req_id, {}) if isinstance(api.buy_multi_option, dict) else {}

                if isinstance(payload, dict) and "message" in payload:
                    return False, str(payload.get("message") or "rejected without message")

                if isinstance(payload, dict):
                    order_id = payload.get("id")

                if time.time() - started >= 5.0:
                    return False, "dynamic buy timeout"

                time.sleep(0.01)

            return bool(api.result), str(order_id) if api.result else None

        except Exception as exc:
            return False, str(exc)
        
    def _parse_active_id(self, *values: Any) -> Optional[int]:
        for value in values:
            if value is None:
                continue
            try:
                return int(value)
            except (TypeError, ValueError):
                continue
        return None
