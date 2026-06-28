from __future__ import annotations

import csv
import glob
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

from app.broker.base import Candle
from app.strategies import backtest_asset, print_backtest_report


EXPORT_DIR = ROOT_DIR / "data" / "market_exports"
WEB_EXPORT_DIR = EXPORT_DIR / "web"
ASSETS = (
    "GBPUSD-OTC",
    "EURJPY-OTC",
    "USDJPY-OTC",
    "AUDJPY-OTC",
    "ALIBABA-OTC",
    "CASINOS-OTC",
    "ETHUSD-OTC",
    "ONDOUSD-OTC",
    "OpenAI-OTC",
    "SP500-OTC",
)


def latest_export_path(asset: str) -> Path:
    candidates = sorted(glob.glob(str(WEB_EXPORT_DIR / f"{asset}_1m_*.csv")))
    if candidates:
        return Path(candidates[-1])
    return EXPORT_DIR / f"{asset}_1m_1000.csv"


def load_exported_candles(asset: str) -> tuple[Path, list[Candle]]:
    path = latest_export_path(asset)
    candles: list[Candle] = []
    with path.open("r", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            candles.append(
                Candle(
                    timestamp=int(row["timestamp"]),
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=float(row.get("volume") or 0),
                )
            )
    return path, candles


def main() -> None:
    for asset in ASSETS:
        path, candles = load_exported_candles(asset)
        print(f"Source: {path.relative_to(ROOT_DIR)}")
        result = backtest_asset(asset, candles)
        print_backtest_report(result)
        print()


if __name__ == "__main__":
    main()
