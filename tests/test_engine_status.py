from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from app.broker.base import BrokerStatus
from app.config import AppConfig
from app.db import Database
from app.engine import TradingEngine


class NullBalanceBroker:
    def status(self) -> BrokerStatus:
        return BrokerStatus(
            connected=True,
            mode="iqoption",
            account_type="PRACTICE",
            balance=None,
            message="IQ Option connected",
        )


class FailingStatusBroker:
    def status(self) -> BrokerStatus:
        raise RuntimeError("connection stale")


class EngineStatusTest(unittest.TestCase):
    def test_stopped_status_keeps_last_known_balance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "trading.db")
            db.init()
            engine = TradingEngine(AppConfig(), db)
            engine._last_broker_status = {
                "connected": True,
                "mode": "iqoption",
                "account_type": "PRACTICE",
                "balance": 4818.41,
                "message": "connected",
            }

            status = engine.status(include_broker=False)

        self.assertFalse(status["broker"]["connected"])
        self.assertEqual(status["broker"]["balance"], 4818.41)
        self.assertEqual(status["broker"]["account_type"], "PRACTICE")

    def test_last_known_balance_is_loaded_from_runtime_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "trading.db")
            db.init()
            engine = TradingEngine(AppConfig(), db)
            engine._set_last_broker_status(
                {
                    "connected": True,
                    "mode": "iqoption",
                    "account_type": "PRACTICE",
                    "balance": 5123.45,
                    "message": "connected",
                }
            )

            restored = TradingEngine(AppConfig(), db)
            status = restored.status(include_broker=False)

        self.assertFalse(status["broker"]["connected"])
        self.assertEqual(status["broker"]["balance"], 5123.45)

    def test_connected_status_uses_persisted_balance_when_broker_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "trading.db")
            db.init()
            engine = TradingEngine(AppConfig(), db)
            engine._set_last_broker_status(
                {
                    "connected": True,
                    "mode": "iqoption",
                    "account_type": "PRACTICE",
                    "balance": 2573.16,
                    "message": "connected",
                }
            )

            restored = TradingEngine(AppConfig(), db)
            restored._broker = NullBalanceBroker()
            status = restored.status()

        self.assertTrue(status["broker"]["connected"])
        self.assertEqual(status["broker"]["balance"], 2573.16)

    def test_status_error_uses_persisted_balance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "trading.db")
            db.init()
            engine = TradingEngine(AppConfig(), db)
            engine._set_last_broker_status(
                {
                    "connected": True,
                    "mode": "iqoption",
                    "account_type": "PRACTICE",
                    "balance": 4818.41,
                    "message": "connected",
                }
            )

            restored = TradingEngine(AppConfig(), db)
            restored._broker = FailingStatusBroker()
            status = restored.status()

        self.assertFalse(status["broker"]["connected"])
        self.assertEqual(status["broker"]["balance"], 4818.41)
        self.assertEqual(status["broker"]["message"], "connection stale")

    def test_logout_clears_persisted_balance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "trading.db")
            db.init()
            config = AppConfig()
            config.broker.mode = "iqoption"
            engine = TradingEngine(config, db)
            engine._set_last_broker_status(
                {
                    "connected": True,
                    "mode": "iqoption",
                    "account_type": "PRACTICE",
                    "balance": 2573.16,
                    "message": "connected",
                }
            )

            try:
                previous_loop = asyncio.get_event_loop()
            except RuntimeError:
                previous_loop = None
            loop = asyncio.new_event_loop()
            try:
                asyncio.set_event_loop(loop)
                status = loop.run_until_complete(engine.logout())
            finally:
                loop.close()
                asyncio.set_event_loop(previous_loop)

            self.assertIsNone(status["broker"]["balance"])
            self.assertIsNone(db.get_state("last_broker_status"))


if __name__ == "__main__":
    unittest.main()
