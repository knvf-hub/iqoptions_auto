from __future__ import annotations

import argparse
import json
import logging
import signal
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.broker.iqoption import IQOptionBroker
from app.config import load_config, resolve_storage_path
from app.db import Database, utc_now
from app.indicators import TradeSignal
from app.selector import CandidateSignal, scan_and_select


class OperationTimeout(RuntimeError):
    pass


def _alarm_handler(signum: int, frame: Any) -> None:
    raise OperationTimeout("operation timed out")


def with_timeout(seconds: int, fn: Any, *args: Any, **kwargs: Any) -> Any:
    signal.signal(signal.SIGALRM, _alarm_handler)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        return fn(*args, **kwargs)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)


def setup_logger(log_dir: Path) -> tuple[logging.Logger, Path]:
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / f"practice-session-{datetime.now().strftime('%Y%m%d-%H%M%S')}.log"
    logger = logging.getLogger("practice-session")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    file_handler = logging.FileHandler(path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    return logger, path


def choose_signal(
    broker: IQOptionBroker,
    *,
    primary_asset: str,
    assets: list[str],
    auto_select: bool,
    duration_minutes: int,
    lookback: int,
    min_confidence: float,
) -> dict[str, Any]:
    return scan_and_select(
        broker,
        primary_asset=primary_asset,
        assets=assets,
        auto_select=auto_select,
        duration_minutes=duration_minutes,
        lookback_candles=lookback,
        min_confidence=min_confidence,
    )


def record_signals(db: Database, candidates: list[CandidateSignal], prefix: str) -> None:
    for item in candidates:
        signal_value = item.signal
        db.add_signal(
            item.asset,
            signal_value.action,
            signal_value.confidence,
            f"{prefix}_{item.label}:{signal_value.reason}",
            signal_value.close_price,
            signal_value.metrics,
        )


def open_trade(
    *,
    db: Database,
    broker: IQOptionBroker,
    mode: str,
    account_type: str,
    instrument: str,
    amount: float,
    selected: CandidateSignal,
    sequence: int,
) -> dict[str, Any]:
    signal_value = selected.signal
    order = broker.place_order(
        selected.asset,
        instrument,
        signal_value.action,
        amount,
        selected.duration_minutes,
    )
    expires_at = (
        datetime.now(timezone.utc) + timedelta(minutes=selected.duration_minutes)
    ).isoformat(timespec="seconds")
    trade_id = db.create_trade(
        mode=mode,
        account_type=account_type,
        asset=selected.asset,
        instrument=instrument,
        direction=signal_value.action,
        amount=amount,
        duration_minutes=selected.duration_minutes,
        strategy=f"practice_session_{selected.label}",
        status="open",
        order_id=order.order_id,
        expires_at=expires_at,
        entry_price=order.entry_price,
        confidence=signal_value.confidence,
        reason=f"session_order_{sequence}_{selected.label}:{signal_value.reason}",
        raw_response=order.raw,
    )
    payload = {
        "trade_id": trade_id,
        "order_id": order.order_id,
        "asset": selected.asset,
        "label": selected.label,
        "duration_minutes": selected.duration_minutes,
        "direction": signal_value.action,
        "amount": amount,
        "entry_price": order.entry_price,
        "confidence": signal_value.confidence,
        "reason": signal_value.reason,
        "expires_at": expires_at,
    }
    db.add_event("info", "trade", "Practice session trade opened", payload)
    return payload


def settle_due_trades(
    *,
    db: Database,
    broker: IQOptionBroker,
    timeout_sec: int,
    logger: logging.Logger,
) -> int:
    settled = 0
    for trade in db.list_due_open_trades():
        try:
            profit, raw = with_timeout(
                timeout_sec,
                broker.resolve_order,
                str(trade["order_id"]),
                str(trade["instrument"]),
            )
        except OperationTimeout:
            db.add_event(
                "warning",
                "trade",
                "Practice session settlement timed out",
                {"id": trade["id"], "order_id": trade["order_id"]},
            )
            logger.warning("settle timeout trade_id=%s order_id=%s", trade["id"], trade["order_id"])
            try:
                broker.connect()
            except Exception as exc:
                logger.warning("reconnect after timeout failed: %s", exc)
            continue
        except Exception as exc:
            db.add_event(
                "error",
                "trade",
                "Practice session settlement failed",
                {"id": trade["id"], "order_id": trade["order_id"], "error": str(exc)},
            )
            logger.warning("settle error trade_id=%s order_id=%s error=%s", trade["id"], trade["order_id"], exc)
            continue

        if profit is None:
            logger.info("settle pending trade_id=%s order_id=%s raw=%s", trade["id"], trade["order_id"], raw)
            continue

        raw = raw if isinstance(raw, dict) else {}
        db.close_trade(
            int(trade["id"]),
            profit=round(float(profit), 2),
            exit_price=raw.get("exit_price"),
            payout=raw.get("close_profit") or raw.get("payout_rate"),
            raw_response=raw,
        )
        db.add_event(
            "info",
            "trade",
            "Practice session trade closed",
            {"id": trade["id"], "order_id": trade["order_id"], "profit": round(float(profit), 2)},
        )
        logger.info(
            "closed trade_id=%s order_id=%s profit=%.2f raw=%s",
            trade["id"],
            trade["order_id"],
            float(profit),
            json.dumps(raw, default=str),
        )
        settled += 1
    return settled


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a bounded IQ Option PRACTICE test session.")
    parser.add_argument("--max-orders", type=int, default=15)
    parser.add_argument("--max-minutes", type=int, default=60)
    parser.add_argument("--poll-sec", type=int, default=5)
    parser.add_argument("--settle-timeout-sec", type=int, default=20)
    parser.add_argument("--force-on-hold", action="store_true", help="Place fallback direction even when strategy says hold.")
    args = parser.parse_args()

    logger, log_path = setup_logger(ROOT / "logs")
    cfg = load_config()
    db = Database(resolve_storage_path(cfg))
    db.init()

    if cfg.broker.mode != "iqoption":
        raise SystemExit("broker.mode must be iqoption for this practice session")
    if cfg.broker.account_type != "PRACTICE":
        raise SystemExit("Refusing to run: broker.account_type must be PRACTICE")
    if cfg.trading.amount > cfg.risk.max_trade_amount:
        raise SystemExit("Refusing to run: trading.amount exceeds risk.max_trade_amount")

    session = {
        "started_at": utc_now(),
        "max_orders": args.max_orders,
        "max_minutes": args.max_minutes,
        "poll_sec": args.poll_sec,
        "asset": cfg.trading.asset,
        "auto_select_asset": cfg.trading.auto_select_asset,
        "assets": cfg.trading.assets,
        "instrument": cfg.trading.instrument,
        "amount": cfg.trading.amount,
        "min_confidence": cfg.trading.min_confidence,
        "force_on_hold": args.force_on_hold,
        "log_path": str(log_path),
    }
    db.add_event("info", "session", "Practice session started", session)
    logger.info("session started %s", json.dumps(session, default=str))

    broker = IQOptionBroker(cfg)
    status = broker.connect()
    logger.info("broker connected balance=%s mode=%s account=%s", status.balance, status.mode, status.account_type)

    deadline = time.time() + args.max_minutes * 60
    opened = 0
    settled = 0
    skipped = 0

    while time.time() < deadline:
        settled += settle_due_trades(db=db, broker=broker, timeout_sec=args.settle_timeout_sec, logger=logger)

        stats = db.daily_stats()
        if opened >= args.max_orders:
            if db.count_open_trades() == 0:
                break
            logger.info("max orders opened, waiting for remaining open trades")
            time.sleep(args.poll_sec)
            continue
        if stats["daily_loss"] >= cfg.risk.max_daily_loss:
            logger.warning("daily loss limit reached daily_loss=%s", stats["daily_loss"])
            break
        if stats["consecutive_losses"] >= cfg.risk.stop_after_consecutive_losses:
            logger.warning("consecutive loss limit reached count=%s", stats["consecutive_losses"])
            break
        if db.count_open_trades() > 0:
            time.sleep(args.poll_sec)
            continue

        try:
            decision = choose_signal(
                broker,
                primary_asset=cfg.trading.asset,
                assets=cfg.trading.assets,
                auto_select=cfg.trading.auto_select_asset,
                duration_minutes=cfg.trading.duration_minutes,
                lookback=cfg.trading.lookback_candles,
                min_confidence=cfg.trading.min_confidence,
            )
        except Exception as exc:
            logger.warning("signal read failed: %s", exc)
            db.add_event("error", "session", "Practice session signal read failed", {"error": str(exc)})
            try:
                broker.connect()
            except Exception as reconnect_exc:
                logger.warning("reconnect after signal failure failed: %s", reconnect_exc)
            time.sleep(args.poll_sec)
            continue

        record_signals(db, decision["candidates"], "practice_session")
        best = decision["best"]
        signal_value = best.signal
        logger.info(
            "decision asset=%s best=%s action=%s confidence=%.3f reason=%s metrics=%s",
            best.asset,
            best.label,
            signal_value.action,
            signal_value.confidence,
            signal_value.reason,
            json.dumps(signal_value.metrics, default=str),
        )

        selected = best
        if not decision["tradable"]:
            skipped += 1
            if not args.force_on_hold:
                time.sleep(args.poll_sec)
                continue
            direction = "call" if (signal_value.metrics.get("momentum") or 0) >= 0 else "put"
            selected = CandidateSignal(
                asset=best.asset,
                label=best.label,
                interval_sec=best.interval_sec,
                duration_minutes=best.duration_minutes,
                signal=TradeSignal(
                    action=direction,
                    confidence=0.0,
                    reason=f"force_on_hold:{signal_value.reason}",
                    close_price=signal_value.close_price,
                    metrics=signal_value.metrics,
                ),
                score=0.0,
            )

        try:
            opened += 1
            trade = open_trade(
                db=db,
                broker=broker,
                mode=cfg.broker.mode,
                account_type=cfg.broker.account_type,
                instrument=cfg.trading.instrument,
                amount=cfg.trading.amount,
                selected=selected,
                sequence=opened,
            )
            logger.info("opened %s", json.dumps(trade, default=str))
        except Exception as exc:
            opened -= 1
            logger.warning("open trade failed: %s", exc)
            db.add_event("error", "session", "Practice session open trade failed", {"error": str(exc)})
            try:
                broker.connect()
            except Exception as reconnect_exc:
                logger.warning("reconnect after open failure failed: %s", reconnect_exc)

        time.sleep(args.poll_sec)

    end_wait = time.time() + 10 * 60
    while db.count_open_trades() > 0 and time.time() < end_wait:
        settled += settle_due_trades(db=db, broker=broker, timeout_sec=args.settle_timeout_sec, logger=logger)
        time.sleep(args.poll_sec)

    final_stats = db.daily_stats()
    summary = {
        "finished_at": utc_now(),
        "opened": opened,
        "settled_calls": settled,
        "skipped_hold_cycles": skipped,
        "open_trades": db.count_open_trades(),
        "stats": final_stats,
        "log_path": str(log_path),
    }
    db.add_event("info", "session", "Practice session finished", summary)
    logger.info("session finished %s", json.dumps(summary, default=str))
    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
