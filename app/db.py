from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def bangkok_day_range_utc(now: Optional[datetime] = None) -> tuple[str, str, str]:
    bangkok_tz = ZoneInfo("Asia/Bangkok")
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    bangkok_now = current.astimezone(bangkok_tz)
    day_start = datetime.combine(bangkok_now.date(), time.min, tzinfo=bangkok_tz)
    day_end = day_start + timedelta(days=1)
    return (
        day_start.astimezone(timezone.utc).isoformat(timespec="seconds"),
        day_end.astimezone(timezone.utc).isoformat(timespec="seconds"),
        bangkok_now.date().isoformat(),
    )


def bangkok_month_range_utc(month: str) -> tuple[str, str]:
    bangkok_tz = ZoneInfo("Asia/Bangkok")
    year_text, month_text = month.split("-", 1)
    year = int(year_text)
    month_number = int(month_text)
    if month_number < 1 or month_number > 12:
        raise ValueError("month must be in YYYY-MM format")
    month_start = datetime(year, month_number, 1, tzinfo=bangkok_tz)
    if month_number == 12:
        month_end = datetime(year + 1, 1, 1, tzinfo=bangkok_tz)
    else:
        month_end = datetime(year, month_number + 1, 1, tzinfo=bangkok_tz)
    return (
        month_start.astimezone(timezone.utc).isoformat(timespec="seconds"),
        month_end.astimezone(timezone.utc).isoformat(timespec="seconds"),
    )


def _parse_utc_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def init(self) -> None:
        with self._lock, self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    expires_at TEXT,
                    closed_at TEXT,
                    mode TEXT NOT NULL,
                    account_type TEXT NOT NULL,
                    asset TEXT NOT NULL,
                    instrument TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    amount REAL NOT NULL,
                    duration_minutes INTEGER NOT NULL,
                    strategy TEXT NOT NULL,
                    status TEXT NOT NULL,
                    order_id TEXT UNIQUE,
                    entry_price REAL,
                    exit_price REAL,
                    payout REAL,
                    profit REAL,
                    confidence REAL,
                    reason TEXT,
                    error TEXT,
                    raw_response TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_trades_created_at ON trades(created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status);
                CREATE INDEX IF NOT EXISTS idx_trades_order_id ON trades(order_id);

                CREATE TABLE IF NOT EXISTS signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    asset TEXT NOT NULL,
                    action TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    reason TEXT NOT NULL,
                    close_price REAL,
                    metrics TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_signals_created_at ON signals(created_at DESC);

                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    level TEXT NOT NULL,
                    category TEXT NOT NULL,
                    message TEXT NOT NULL,
                    payload TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_events_created_at ON events(created_at DESC);

                CREATE TABLE IF NOT EXISTS telegram_signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_id TEXT UNIQUE,
                    received_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    active_raw TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    expiration TEXT NOT NULL,
                    signal_time TEXT NOT NULL,
                    entry_time TEXT,
                    raw_text TEXT,
                    mapped INTEGER NOT NULL DEFAULT 0,
                    source TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_telegram_signals_symbol ON telegram_signals(symbol, direction);
                CREATE INDEX IF NOT EXISTS idx_telegram_signals_received ON telegram_signals(received_at DESC);

                CREATE TABLE IF NOT EXISTS telegram_paper_signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_id TEXT UNIQUE,
                    received_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    message_id TEXT,
                    active_raw TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    expiration TEXT NOT NULL,
                    signal_time TEXT NOT NULL,
                    entry_time TEXT,
                    raw_text TEXT,
                    mapped INTEGER NOT NULL DEFAULT 0,
                    filtered INTEGER NOT NULL DEFAULT 0,
                    filter_reason TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL,
                    result_at TEXT,
                    result_message_id TEXT,
                    result_text TEXT,
                    payload TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_telegram_paper_signals_received ON telegram_paper_signals(received_at DESC);
                CREATE INDEX IF NOT EXISTS idx_telegram_paper_signals_symbol ON telegram_paper_signals(symbol, direction, status);

                CREATE TABLE IF NOT EXISTS runtime_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )

    def get_state(self, key: str) -> Optional[str]:
        with self._lock, self._connect() as db:
            row = db.execute("SELECT value FROM runtime_state WHERE key = ?", (key,)).fetchone()
        return str(row["value"]) if row else None

    def set_state(self, key: str, value: str) -> None:
        now = utc_now()
        with self._lock, self._connect() as db:
            db.execute(
                """
                INSERT INTO runtime_state (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at
                """,
                (key, value, now),
            )

    def delete_state(self, key: str) -> None:
        with self._lock, self._connect() as db:
            db.execute("DELETE FROM runtime_state WHERE key = ?", (key,))

    def add_event(
        self,
        level: str,
        category: str,
        message: str,
        payload: Optional[dict[str, Any]] = None,
    ) -> None:
        with self._lock, self._connect() as db:
            db.execute(
                """
                INSERT INTO events (created_at, level, category, message, payload)
                VALUES (?, ?, ?, ?, ?)
                """,
                (utc_now(), level, category, message, json.dumps(payload or {})),
            )

    def add_signal(
        self,
        asset: str,
        action: str,
        confidence: float,
        reason: str,
        close_price: Optional[float],
        metrics: dict[str, Any],
    ) -> int:
        with self._lock, self._connect() as db:
            cursor = db.execute(
                """
                INSERT INTO signals
                    (created_at, asset, action, confidence, reason, close_price, metrics)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    utc_now(),
                    asset,
                    action,
                    confidence,
                    reason,
                    close_price,
                    json.dumps(metrics, default=str),
                ),
            )
            return int(cursor.lastrowid)

    def create_trade(
        self,
        *,
        mode: str,
        account_type: str,
        asset: str,
        instrument: str,
        direction: str,
        amount: float,
        duration_minutes: int,
        strategy: str,
        status: str,
        order_id: str,
        expires_at: str,
        entry_price: Optional[float],
        confidence: Optional[float],
        reason: str,
        raw_response: Optional[dict[str, Any]],
    ) -> int:
        now = utc_now()
        with self._lock, self._connect() as db:
            cursor = db.execute(
                """
                INSERT INTO trades (
                    created_at, updated_at, expires_at, mode, account_type, asset,
                    instrument, direction, amount, duration_minutes, strategy, status,
                    order_id, entry_price, confidence, reason, raw_response
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    now,
                    now,
                    expires_at,
                    mode,
                    account_type,
                    asset,
                    instrument,
                    direction,
                    amount,
                    duration_minutes,
                    strategy,
                    status,
                    order_id,
                    entry_price,
                    confidence,
                    reason,
                    json.dumps(raw_response or {}, default=str),
                ),
            )
            return int(cursor.lastrowid)

    def close_trade(
        self,
        trade_id: int,
        *,
        profit: float,
        exit_price: Optional[float],
        payout: Optional[float],
        raw_response: Optional[dict[str, Any]],
    ) -> None:
        now = utc_now()
        status = "won" if profit > 0 else "draw" if profit == 0 else "lost"
        with self._lock, self._connect() as db:
            db.execute(
                """
                UPDATE trades
                SET updated_at = ?, closed_at = ?, status = ?, profit = ?, exit_price = ?,
                    payout = ?, raw_response = ?
                WHERE id = ?
                """,
                (
                    now,
                    now,
                    status,
                    profit,
                    exit_price,
                    payout,
                    json.dumps(raw_response or {}, default=str),
                    trade_id,
                ),
            )

    def fail_trade(self, trade_id: int, error: str, raw_response: Optional[dict[str, Any]] = None) -> None:
        now = utc_now()
        with self._lock, self._connect() as db:
            db.execute(
                """
                UPDATE trades
                SET updated_at = ?, closed_at = ?, status = 'failed', error = ?, raw_response = ?
                WHERE id = ?
                """,
                (now, now, error, json.dumps(raw_response or {}, default=str), trade_id),
            )

    def list_due_open_trades(self, now: Optional[str] = None) -> list[dict[str, Any]]:
        now = now or utc_now()
        with self._lock, self._connect() as db:
            rows = db.execute(
                """
                SELECT * FROM trades
                WHERE status = 'open' AND expires_at IS NOT NULL AND expires_at <= ?
                ORDER BY expires_at ASC
                """,
                (now,),
            ).fetchall()
        return [self._decode_row(row) for row in rows]

    def count_open_trades(self) -> int:
        with self._lock, self._connect() as db:
            row = db.execute("SELECT COUNT(*) AS count FROM trades WHERE status = 'open'").fetchone()
        return int(row["count"] or 0)

    def next_open_trade_expires_at(self) -> Optional[str]:
        with self._lock, self._connect() as db:
            row = db.execute(
                """
                SELECT expires_at
                FROM trades
                WHERE status = 'open' AND expires_at IS NOT NULL
                ORDER BY expires_at ASC
                LIMIT 1
                """
            ).fetchone()
        return str(row["expires_at"]) if row and row["expires_at"] else None

    def clear_history(self, *, include_events: bool = True) -> dict[str, int]:
        with self._lock, self._connect() as db:
            counts = {
                "trades": int(db.execute("SELECT COUNT(*) AS count FROM trades").fetchone()["count"] or 0),
                "signals": int(db.execute("SELECT COUNT(*) AS count FROM signals").fetchone()["count"] or 0),
                "telegram_signals": int(
                    db.execute("SELECT COUNT(*) AS count FROM telegram_signals").fetchone()["count"] or 0
                ),
                "events": int(db.execute("SELECT COUNT(*) AS count FROM events").fetchone()["count"] or 0)
                if include_events
                else 0,
            }
            db.execute("DELETE FROM trades")
            db.execute("DELETE FROM signals")
            db.execute("DELETE FROM telegram_signals")
            if include_events:
                db.execute("DELETE FROM events")

            tables = ["trades", "signals", "telegram_signals"]
            if include_events:
                tables.append("events")
            placeholders = ", ".join("?" for _ in tables)
            db.execute(f"DELETE FROM sqlite_sequence WHERE name IN ({placeholders})", tables)
        return counts

    def list_trades(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        status: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 200))
        offset = max(0, offset)
        params: list[Any] = []
        where = ""
        if status:
            where = "WHERE status = ?"
            params.append(status)
        params.extend([limit, offset])
        with self._lock, self._connect() as db:
            rows = db.execute(
                f"""
                SELECT * FROM trades
                {where}
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
                """,
                params,
            ).fetchall()
        return [self._decode_row(row) for row in rows]

    def list_events(self, limit: int = 80, offset: int = 0) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 200))
        offset = max(0, offset)
        with self._lock, self._connect() as db:
            rows = db.execute(
                "SELECT * FROM events ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        return [self._decode_row(row) for row in rows]

    def list_signals(self, limit: int = 80) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 200))
        with self._lock, self._connect() as db:
            rows = db.execute(
                "SELECT * FROM signals ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._decode_row(row) for row in rows]

    def upsert_telegram_signal(
        self,
        *,
        source_id: str,
        received_at: str,
        provider: str,
        active_raw: str,
        symbol: str,
        direction: str,
        expiration: str,
        signal_time: str,
        entry_time: str,
        raw_text: str,
        mapped: bool,
        source: str,
        status: str,
        payload: dict[str, Any],
    ) -> None:
        with self._lock, self._connect() as db:
            db.execute(
                """
                INSERT INTO telegram_signals (
                    source_id, received_at, created_at, provider, active_raw, symbol,
                    direction, expiration, signal_time, entry_time, raw_text, mapped,
                    source, status, payload
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_id) DO UPDATE SET
                    received_at = excluded.received_at,
                    provider = excluded.provider,
                    active_raw = excluded.active_raw,
                    symbol = excluded.symbol,
                    direction = excluded.direction,
                    expiration = excluded.expiration,
                    signal_time = excluded.signal_time,
                    entry_time = excluded.entry_time,
                    raw_text = excluded.raw_text,
                    mapped = excluded.mapped,
                    status = excluded.status,
                    payload = excluded.payload
                """,
                (
                    source_id,
                    received_at,
                    utc_now(),
                    provider,
                    active_raw,
                    symbol,
                    direction,
                    expiration,
                    signal_time,
                    entry_time,
                    raw_text,
                    1 if mapped else 0,
                    source,
                    status,
                    json.dumps(payload or {}, default=str),
                ),
            )

    def telegram_signal_exists(
        self,
        *,
        provider: str,
        active_raw: str,
        direction: str,
        signal_time: str,
    ) -> bool:
        with self._lock, self._connect() as db:
            row = db.execute(
                """
                SELECT 1
                FROM telegram_signals
                WHERE provider = ?
                  AND active_raw = ?
                  AND direction = ?
                  AND signal_time = ?
                LIMIT 1
                """,
                (provider, active_raw, direction, signal_time),
            ).fetchone()
        return row is not None

    def list_telegram_signals(self, limit: int = 50, *, mapped_only: bool = False) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 200))
        where = "WHERE mapped = 1" if mapped_only else ""
        with self._lock, self._connect() as db:
            rows = db.execute(
                f"""
                SELECT * FROM telegram_signals
                {where}
                ORDER BY received_at DESC, id DESC
                LIMIT ?
                """,
                (min(limit * 5, 500),),
            ).fetchall()
        items: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str, str]] = set()
        for row in rows:
            item = self._decode_row(row)
            key = (
                str(item.get("provider") or ""),
                str(item.get("active_raw") or ""),
                str(item.get("direction") or ""),
                str(item.get("signal_time") or ""),
            )
            if key in seen:
                continue
            seen.add(key)
            items.append(item)
            if len(items) >= limit:
                break
        return items

    def upsert_telegram_paper_signal(
        self,
        *,
        source_id: str,
        received_at: str,
        provider: str,
        message_id: str,
        active_raw: str,
        symbol: str,
        direction: str,
        expiration: str,
        signal_time: str,
        entry_time: str,
        raw_text: str,
        mapped: bool,
        filtered: bool,
        filter_reason: str,
        status: str,
        payload: dict[str, Any],
    ) -> None:
        with self._lock, self._connect() as db:
            db.execute(
                """
                INSERT INTO telegram_paper_signals (
                    source_id, received_at, created_at, provider, message_id, active_raw,
                    symbol, direction, expiration, signal_time, entry_time, raw_text,
                    mapped, filtered, filter_reason, status, payload
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_id) DO UPDATE SET
                    received_at = excluded.received_at,
                    provider = excluded.provider,
                    message_id = excluded.message_id,
                    active_raw = excluded.active_raw,
                    symbol = excluded.symbol,
                    direction = excluded.direction,
                    expiration = excluded.expiration,
                    signal_time = excluded.signal_time,
                    entry_time = excluded.entry_time,
                    raw_text = excluded.raw_text,
                    mapped = excluded.mapped,
                    filtered = excluded.filtered,
                    filter_reason = excluded.filter_reason,
                    status = CASE
                        WHEN telegram_paper_signals.status IN ('won', 'lost', 'draw') THEN telegram_paper_signals.status
                        ELSE excluded.status
                    END,
                    payload = excluded.payload
                """,
                (
                    source_id,
                    received_at,
                    received_at,
                    provider,
                    message_id,
                    active_raw,
                    symbol,
                    direction,
                    expiration,
                    signal_time,
                    entry_time,
                    raw_text,
                    1 if mapped else 0,
                    1 if filtered else 0,
                    filter_reason,
                    status,
                    json.dumps(payload or {}, default=str),
                ),
            )

    def close_next_telegram_paper_signal(
        self,
        *,
        symbol: str,
        status: str,
        result_at: str,
        result_message_id: str,
        result_text: str,
    ) -> Optional[dict[str, Any]]:
        if status not in {"won", "lost", "draw"}:
            return None
        with self._lock, self._connect() as db:
            row = db.execute(
                """
                SELECT *
                FROM telegram_paper_signals
                WHERE symbol = ? AND status = 'pending' AND received_at <= ?
                ORDER BY received_at ASC, id ASC
                LIMIT 1
                """,
                (symbol, result_at),
            ).fetchone()
            if not row:
                return None
            db.execute(
                """
                UPDATE telegram_paper_signals
                SET status = ?, result_at = ?, result_message_id = ?, result_text = ?
                WHERE id = ?
                """,
                (status, result_at, result_message_id, result_text, row["id"]),
            )
            updated = db.execute("SELECT * FROM telegram_paper_signals WHERE id = ?", (row["id"],)).fetchone()
        return self._decode_row(updated) if updated else None

    def clear_telegram_paper_since(self, *, hours: int = 24) -> int:
        hours = max(1, min(hours, 168))
        since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat(timespec="seconds")
        with self._lock, self._connect() as db:
            cursor = db.execute("DELETE FROM telegram_paper_signals WHERE received_at >= ?", (since,))
            return int(cursor.rowcount or 0)

    def list_telegram_paper_signals(
        self,
        *,
        limit: int = 100,
        hours: int = 24,
        status: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 500))
        hours = max(1, min(hours, 168))
        since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat(timespec="seconds")
        params: list[Any] = [since]
        where = "received_at >= ?"
        if status:
            where += " AND status = ?"
            params.append(status)
        params.append(limit)
        with self._lock, self._connect() as db:
            rows = db.execute(
                f"""
                SELECT *
                FROM telegram_paper_signals
                WHERE {where}
                ORDER BY received_at DESC, id DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [self._decode_row(row) for row in rows]

    def telegram_paper_stats(self, *, hours: int = 24) -> dict[str, Any]:
        hours = max(1, min(hours, 168))
        since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat(timespec="seconds")
        with self._lock, self._connect() as db:
            total = db.execute(
                """
                SELECT
                    COUNT(*) AS signals,
                    SUM(CASE WHEN status = 'won' THEN 1 ELSE 0 END) AS wins,
                    SUM(CASE WHEN status = 'lost' THEN 1 ELSE 0 END) AS losses,
                    SUM(CASE WHEN status = 'draw' THEN 1 ELSE 0 END) AS draws,
                    SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) AS pending,
                    SUM(CASE WHEN mapped = 1 THEN 1 ELSE 0 END) AS mapped,
                    SUM(CASE WHEN filtered = 1 THEN 1 ELSE 0 END) AS filtered
                FROM telegram_paper_signals
                WHERE received_at >= ?
                """,
                (since,),
            ).fetchone()
            by_asset = db.execute(
                """
                SELECT
                    symbol,
                    direction,
                    COUNT(*) AS signals,
                    SUM(CASE WHEN status = 'won' THEN 1 ELSE 0 END) AS wins,
                    SUM(CASE WHEN status = 'lost' THEN 1 ELSE 0 END) AS losses,
                    SUM(CASE WHEN status = 'draw' THEN 1 ELSE 0 END) AS draws,
                    SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) AS pending,
                    SUM(CASE WHEN mapped = 1 THEN 1 ELSE 0 END) AS mapped,
                    MAX(received_at) AS latest_signal_at
                FROM telegram_paper_signals
                WHERE received_at >= ?
                GROUP BY symbol, direction
                ORDER BY symbol ASC, direction ASC
                """,
                (since,),
            ).fetchall()

        wins = int(total["wins"] or 0) if total else 0
        losses = int(total["losses"] or 0) if total else 0
        draws = int(total["draws"] or 0) if total else 0
        closed = wins + losses + draws
        return {
            "hours": hours,
            "since": since,
            "signals": int(total["signals"] or 0) if total else 0,
            "wins": wins,
            "losses": losses,
            "draws": draws,
            "pending": int(total["pending"] or 0) if total else 0,
            "mapped": int(total["mapped"] or 0) if total else 0,
            "filtered": int(total["filtered"] or 0) if total else 0,
            "win_rate": round((wins / closed * 100), 2) if closed else 0.0,
            "by_asset": [
                {
                    "symbol": row["symbol"],
                    "direction": row["direction"],
                    "signals": int(row["signals"] or 0),
                    "wins": int(row["wins"] or 0),
                    "losses": int(row["losses"] or 0),
                    "draws": int(row["draws"] or 0),
                    "pending": int(row["pending"] or 0),
                    "mapped": int(row["mapped"] or 0),
                    "latest_signal_at": row["latest_signal_at"],
                    "win_rate": round(
                        (int(row["wins"] or 0) / max(1, int(row["wins"] or 0) + int(row["losses"] or 0) + int(row["draws"] or 0))) * 100,
                        2,
                    )
                    if (int(row["wins"] or 0) + int(row["losses"] or 0) + int(row["draws"] or 0))
                    else 0.0,
                }
                for row in by_asset
            ],
        }

    def telegram_asset_stats(self, *, min_signals: int = 3, date: Optional[str] = None) -> list[dict[str, Any]]:
        trade_stats = {
            f"{item['asset']}:{item['direction']}": item
            for item in self.asset_stats(date=date)
        }
        with self._lock, self._connect() as db:
            rows = db.execute(
                """
                SELECT
                    symbol AS asset,
                    direction,
                    COUNT(*) AS signal_count,
                    MAX(received_at) AS latest_signal_at
                FROM telegram_signals
                WHERE mapped = 1
                GROUP BY symbol, direction
                HAVING COUNT(*) >= ?
                ORDER BY symbol ASC, direction ASC
                """,
                (max(1, min_signals),),
            ).fetchall()

        items: list[dict[str, Any]] = []
        for row in rows:
            key = f"{row['asset']}:{row['direction']}"
            base = dict(trade_stats.get(key) or {})
            items.append(
                {
                    "date": date or utc_now()[:10],
                    "asset": row["asset"],
                    "direction": row["direction"],
                    "trades": int(row["signal_count"] or 0),
                    "wins": int(base.get("wins", 0) or 0),
                    "losses": int(base.get("losses", 0) or 0),
                    "draws": int(base.get("draws", 0) or 0),
                    "open_trades": int(base.get("open_trades", 0) or 0),
                    "profit": round(float(base.get("profit", 0) or 0), 2),
                    "win_rate": float(base.get("win_rate", 0) or 0),
                    "avg_confidence": float(base.get("avg_confidence", 0) or 0),
                    "telegram_signals": int(row["signal_count"] or 0),
                    "latest_signal_at": row["latest_signal_at"],
                }
            )
        return items

    def asset_stats(self, *, date: Optional[str] = None, since: Optional[str] = None) -> list[dict[str, Any]]:
        target_date = date or utc_now()[:10]
        where_clause = "created_at >= ?" if since else "substr(created_at, 1, 10) = ?"
        where_value = since or target_date
        with self._lock, self._connect() as db:
            rows = db.execute(
                f"""
                SELECT
                    asset,
                    direction,
                    COUNT(*) AS trades,
                    SUM(CASE WHEN status = 'won' THEN 1 ELSE 0 END) AS wins,
                    SUM(CASE WHEN status = 'lost' THEN 1 ELSE 0 END) AS losses,
                    SUM(CASE WHEN status = 'draw' THEN 1 ELSE 0 END) AS draws,
                    SUM(CASE WHEN status = 'open' THEN 1 ELSE 0 END) AS open_trades,
                    COALESCE(SUM(CASE WHEN status IN ('won', 'lost', 'draw') THEN profit ELSE 0 END), 0) AS profit,
                    AVG(CASE WHEN confidence IS NOT NULL THEN confidence ELSE NULL END) AS avg_confidence
                FROM trades
                WHERE {where_clause}
                GROUP BY asset, direction
                ORDER BY profit ASC, trades DESC
                """,
                (where_value,),
            ).fetchall()

        items: list[dict[str, Any]] = []
        for row in rows:
            wins = int(row["wins"] or 0)
            losses = int(row["losses"] or 0)
            closed = wins + losses
            items.append(
                {
                    "date": target_date,
                    "since": since,
                    "asset": row["asset"],
                    "direction": row["direction"],
                    "trades": int(row["trades"] or 0),
                    "wins": wins,
                    "losses": losses,
                    "draws": int(row["draws"] or 0),
                    "open_trades": int(row["open_trades"] or 0),
                    "profit": round(float(row["profit"] or 0), 2),
                    "win_rate": round((wins / closed) * 100, 2) if closed else 0.0,
                    "avg_confidence": round(float(row["avg_confidence"] or 0), 3),
                }
            )
        return items

    def asset_direction_loss_blocks(self, *, loss_limit: int, cooldown_sec: int) -> dict[str, dict[str, Any]]:
        if loss_limit <= 0 or cooldown_sec <= 0:
            return {}

        with self._lock, self._connect() as db:
            rows = db.execute(
                """
                SELECT asset, direction, status, closed_at
                FROM trades
                WHERE status IN ('won', 'lost', 'draw') AND closed_at IS NOT NULL
                ORDER BY closed_at DESC, id DESC
                LIMIT 300
                """
            ).fetchall()

        grouped: dict[tuple[str, str], list[sqlite3.Row]] = {}
        for row in rows:
            key = (str(row["asset"]), str(row["direction"]))
            grouped.setdefault(key, []).append(row)

        now = datetime.now(timezone.utc)
        blocks: dict[str, dict[str, Any]] = {}
        for (asset, direction), items in grouped.items():
            latest_closed_at = str(items[0]["closed_at"])
            try:
                latest_closed = datetime.fromisoformat(latest_closed_at)
            except ValueError:
                continue
            cooldown_until = latest_closed + timedelta(seconds=cooldown_sec)
            if cooldown_until <= now:
                continue

            losses = 0
            for item in items:
                if str(item["status"]) != "lost":
                    break
                losses += 1
            if losses >= loss_limit:
                blocks[f"{asset}:{direction}"] = {
                    "losses": losses,
                    "last_closed_at": latest_closed_at,
                    "cooldown_until": cooldown_until.isoformat(timespec="seconds"),
                }
        return blocks

    def asset_loss_cooldowns(self, *, cooldown_candles: int, candle_interval_sec: int) -> dict[str, dict[str, Any]]:
        if cooldown_candles <= 0 or candle_interval_sec <= 0:
            return {}

        with self._lock, self._connect() as db:
            rows = db.execute(
                """
                SELECT asset, status, closed_at
                FROM trades
                WHERE status IN ('won', 'lost', 'draw') AND closed_at IS NOT NULL
                ORDER BY closed_at DESC, id DESC
                LIMIT 100
                """
            ).fetchall()

        now = datetime.now(timezone.utc)
        latest_by_asset: dict[str, sqlite3.Row] = {}
        for row in rows:
            asset = str(row["asset"])
            if asset not in latest_by_asset:
                latest_by_asset[asset] = row

        cooldowns: dict[str, dict[str, Any]] = {}
        cooldown_seconds = cooldown_candles * candle_interval_sec
        for asset, row in latest_by_asset.items():
            if str(row["status"]) != "lost":
                continue
            last_closed_at = str(row["closed_at"])
            try:
                last_closed = datetime.fromisoformat(last_closed_at)
            except ValueError:
                continue
            cooldown_until = last_closed + timedelta(seconds=cooldown_seconds)
            if cooldown_until > now:
                cooldowns[asset] = {
                    "last_closed_at": last_closed_at,
                    "cooldown_until": cooldown_until.isoformat(timespec="seconds"),
                    "cooldown_candles": cooldown_candles,
                }
        return cooldowns

    def daily_stats(self, *, since: Optional[str] = None) -> dict[str, Any]:
        if since:
            today = bangkok_day_range_utc()[2]
            where_clause = "created_at >= ?"
            where_params: tuple[Any, ...] = (since,)
        else:
            start_utc, end_utc, today = bangkok_day_range_utc()
            where_clause = "created_at >= ? AND created_at < ?"
            where_params = (start_utc, end_utc)
        with self._lock, self._connect() as db:
            row = db.execute(
                f"""
                SELECT
                    COUNT(*) AS trades,
                    COALESCE(SUM(CASE WHEN status IN ('won', 'lost', 'draw') THEN profit ELSE 0 END), 0) AS profit,
                    SUM(CASE WHEN status = 'won' THEN 1 ELSE 0 END) AS wins,
                    SUM(CASE WHEN status = 'lost' THEN 1 ELSE 0 END) AS losses,
                    SUM(CASE WHEN status = 'open' THEN 1 ELSE 0 END) AS open_trades
                FROM trades
                WHERE {where_clause}
                """,
                where_params,
            ).fetchone()
            last = db.execute(
                f"""
                SELECT created_at
                FROM trades
                WHERE {where_clause}
                ORDER BY created_at DESC
                LIMIT 1
                """,
                where_params,
            ).fetchone()
            recent_closed = db.execute(
                f"""
                SELECT profit
                FROM trades
                WHERE status IN ('won', 'lost', 'draw')
                    AND {where_clause}
                ORDER BY closed_at DESC, id DESC
                LIMIT 20
                """,
                where_params,
            ).fetchall()
        consecutive_losses = 0
        for closed in recent_closed:
            profit = float(closed["profit"] or 0)
            if profit < 0:
                consecutive_losses += 1
            elif profit > 0:
                break
            # Draw keeps the current martingale level: it neither adds a step nor resets.
        trades = int(row["trades"] or 0)
        wins = int(row["wins"] or 0)
        losses = int(row["losses"] or 0)
        closed_count = wins + losses
        profit = round(float(row["profit"] or 0), 2)
        return {
            "date": today,
            "scope": "session" if since else "daily",
            "since": since,
            "trades": trades,
            "profit": profit,
            "daily_loss": round(abs(min(profit, 0)), 2),
            "wins": wins,
            "losses": losses,
            "win_rate": round((wins / closed_count) * 100, 2) if closed_count else 0.0,
            "open_trades": int(row["open_trades"] or 0),
            "consecutive_losses": consecutive_losses,
            "last_trade_at": last["created_at"] if last else None,
        }

    def pnl_calendar(self, *, month: str) -> dict[str, Any]:
        start_utc, end_utc = bangkok_month_range_utc(month)
        bangkok_tz = ZoneInfo("Asia/Bangkok")
        with self._lock, self._connect() as db:
            rows = db.execute(
                """
                SELECT closed_at, asset, direction, amount, status, profit
                FROM trades
                WHERE status IN ('won', 'lost', 'draw')
                    AND closed_at IS NOT NULL
                    AND closed_at >= ?
                    AND closed_at < ?
                ORDER BY closed_at ASC, id ASC
                """,
                (start_utc, end_utc),
            ).fetchall()

        days: dict[str, dict[str, Any]] = {}
        ranking: dict[tuple[str, str], dict[str, Any]] = {}
        summary = {
            "profit": 0.0,
            "volume": 0.0,
            "positions": 0,
            "wins": 0,
            "losses": 0,
            "draws": 0,
        }

        for row in rows:
            closed_local = _parse_utc_timestamp(str(row["closed_at"])).astimezone(bangkok_tz)
            day_key = closed_local.date().isoformat()
            profit = float(row["profit"] or 0)
            amount = float(row["amount"] or 0)
            status = str(row["status"])
            direction = str(row["direction"]).upper()
            asset = str(row["asset"])

            day = days.setdefault(
                day_key,
                {
                    "date": day_key,
                    "day": closed_local.day,
                    "weekday": int(closed_local.strftime("%w")),
                    "profit": 0.0,
                    "volume": 0.0,
                    "positions": 0,
                    "wins": 0,
                    "losses": 0,
                    "draws": 0,
                },
            )
            item = ranking.setdefault(
                (asset, direction),
                {
                    "asset": asset,
                    "direction": direction,
                    "label": f"{asset} {direction}",
                    "profit": 0.0,
                    "volume": 0.0,
                    "positions": 0,
                    "wins": 0,
                    "losses": 0,
                    "draws": 0,
                },
            )

            for target in (summary, day, item):
                target["profit"] += profit
                target["volume"] += amount
                target["positions"] += 1
                if status == "won":
                    target["wins"] += 1
                elif status == "lost":
                    target["losses"] += 1
                elif status == "draw":
                    target["draws"] += 1

        def finalize(item: dict[str, Any]) -> dict[str, Any]:
            closed = int(item["wins"] or 0) + int(item["losses"] or 0)
            volume = float(item["volume"] or 0)
            item["profit"] = round(float(item["profit"] or 0), 2)
            item["volume"] = round(volume, 2)
            item["roi"] = round((item["profit"] / volume) * 100, 2) if volume else 0.0
            item["win_rate"] = round((float(item["wins"] or 0) / closed) * 100, 2) if closed else 0.0
            return item

        finalized_days = [finalize(day) for day in days.values()]
        finalized_days.sort(key=lambda item: str(item["date"]))
        finalized_ranking = [finalize(item) for item in ranking.values()]
        finalized_ranking.sort(key=lambda item: (str(item["asset"]), str(item["direction"])))
        return {
            "month": month,
            "summary": finalize(summary),
            "days": finalized_days,
            "ranking": finalized_ranking,
        }

    def consecutive_losses(
        self,
        *,
        since: Optional[str] = None,
        strategy: Optional[str] = None,
        limit: int = 100,
    ) -> int:
        params: list[Any] = []
        since_clause = ""
        if since:
            since_clause = "AND closed_at >= ?"
            params.append(since)
        strategy_clause = ""
        if strategy:
            strategy_clause = "AND strategy = ?"
            params.append(strategy)
        params.append(max(1, min(limit, 500)))

        with self._lock, self._connect() as db:
            rows = db.execute(
                f"""
                SELECT profit
                FROM trades
                WHERE status IN ('won', 'lost', 'draw')
                    AND closed_at IS NOT NULL
                    {since_clause}
                    {strategy_clause}
                ORDER BY closed_at DESC, id DESC
                LIMIT ?
                """,
                params,
            ).fetchall()

        losses = 0
        for row in rows:
            profit = float(row["profit"] or 0)
            if profit < 0:
                losses += 1
            elif profit > 0:
                break
            # Draw keeps the current martingale level: it neither adds a step nor resets.
        return losses

    def equity_curve(self, limit: int = 120, *, since: Optional[str] = None) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 500))
        today = utc_now()[:10]
        where_clause = "created_at >= ?" if since else "substr(created_at, 1, 10) = ?"
        where_value = since or today
        with self._lock, self._connect() as db:
            rows = db.execute(
                f"""
                SELECT closed_at, profit
                FROM trades
                WHERE status IN ('won', 'lost', 'draw')
                    AND closed_at IS NOT NULL
                    AND {where_clause}
                ORDER BY closed_at ASC
                """,
                (where_value,),
            ).fetchall()

        if since:
            carry = 0.0
            rows = rows[-limit:] if len(rows) > limit else rows
        elif len(rows) > limit:
            carry = sum(float(row["profit"] or 0) for row in rows[: -limit])
            rows = rows[-limit:]
        else:
            carry = 0.0

        running = 0.0
        points = []
        if carry and rows:
            points.append({"time": rows[0]["closed_at"], "equity": round(carry, 2)})
            running = carry
        for row in rows:
            running += float(row["profit"] or 0)
            points.append({"time": row["closed_at"], "equity": round(running, 2)})
        return points

    @staticmethod
    def _decode_row(row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        for key in ("payload", "metrics", "raw_response"):
            if key in data and isinstance(data[key], str):
                try:
                    data[key] = json.loads(data[key])
                except json.JSONDecodeError:
                    data[key] = {}
        return data
