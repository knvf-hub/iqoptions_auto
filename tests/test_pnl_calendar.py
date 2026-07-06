from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.db import Database


class PnlCalendarTest(unittest.TestCase):
    def test_monthly_pnl_uses_closed_trade_bangkok_date(self) -> None:
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
                        "2026-06-30T16:59:00+00:00",
                        "2026-06-30T18:00:00+00:00",
                        "2026-06-30T18:00:00+00:00",
                        "2026-06-30T18:00:00+00:00",
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
                connection.execute(
                    """
                    INSERT INTO trades (
                        created_at, updated_at, expires_at, closed_at, mode, account_type,
                        asset, instrument, direction, amount, duration_minutes, strategy,
                        status, profit
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "2026-07-31T16:59:00+00:00",
                        "2026-07-31T17:30:00+00:00",
                        "2026-07-31T17:30:00+00:00",
                        "2026-07-31T17:30:00+00:00",
                        "iqoption",
                        "PRACTICE",
                        "EURUSD-OTC",
                        "binary",
                        "put",
                        100.0,
                        1,
                        "telegram",
                        "lost",
                        -100.0,
                    ),
                )

            result = db.pnl_calendar(month="2026-07")

        self.assertEqual(result["summary"]["positions"], 1)
        self.assertEqual(result["summary"]["profit"], 87.0)
        self.assertEqual(result["summary"]["win_rate"], 100.0)
        self.assertEqual(result["summary"]["roi"], 87.0)
        self.assertEqual(result["days"][0]["date"], "2026-07-01")
        self.assertEqual(result["ranking"][0]["label"], "EURUSD-OTC CALL")


if __name__ == "__main__":
    unittest.main()
