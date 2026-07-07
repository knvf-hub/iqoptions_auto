from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.db import Database


class HistoryClearTest(unittest.TestCase):
    def test_clear_history_keeps_saved_trades(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "trading.db")
            db.init()
            with db._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO trades (
                        created_at, updated_at, expires_at, closed_at, mode, account_type,
                        asset, instrument, direction, amount, duration_minutes, strategy,
                        status, profit
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "2026-07-07T01:00:00+00:00",
                        "2026-07-07T01:01:00+00:00",
                        "2026-07-07T01:01:00+00:00",
                        "2026-07-07T01:01:00+00:00",
                        "iqoption",
                        "PRACTICE",
                        "EURUSD-OTC",
                        "binary",
                        "call",
                        100.0,
                        1,
                        "telegram",
                        "won",
                        87.0,
                    ),
                )

            counts = db.clear_history()
            remaining = db.list_trades()

        self.assertEqual(counts["trades"], 1)
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0]["asset"], "EURUSD-OTC")


if __name__ == "__main__":
    unittest.main()
