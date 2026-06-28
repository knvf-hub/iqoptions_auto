from __future__ import annotations

import csv
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Optional

from app.broker import BrokerError, DemoBroker, IQOptionBroker
from app.broker.base import Broker, Candle
from app.config import AppConfig, ROOT_DIR


ExportStatus = Literal["queued", "running", "done", "error"]
MAX_CANDLE_BATCH = 1000
EXPORT_DIR = ROOT_DIR / "data" / "market_exports" / "web"
EXPORT_FILENAME_RE = re.compile(r"^(?P<asset>.+)_(?P<timeframe>\d+[ms])_(?P<rows>\d+)_(?P<id>[a-f0-9]{12})\.csv$")


class MarketExportManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, dict[str, Any]] = {}

    def create_job(
        self,
        *,
        config: AppConfig,
        asset: str,
        timeframe_sec: int,
        records: int,
    ) -> dict[str, Any]:
        job_id = uuid.uuid4().hex[:12]
        now = _utc_now()
        job = {
            "id": job_id,
            "status": "queued",
            "asset": asset,
            "timeframe_sec": timeframe_sec,
            "timeframe_label": _timeframe_label(timeframe_sec),
            "records_requested": records,
            "records_written": 0,
            "created_at": now,
            "updated_at": now,
            "error": "",
            "file_path": "",
            "relative_path": "",
            "download_url": "",
        }
        with self._lock:
            self._jobs[job_id] = job

        thread = threading.Thread(
            target=self._run_export,
            kwargs={"job_id": job_id, "config": config, "asset": asset, "timeframe_sec": timeframe_sec, "records": records},
            daemon=True,
        )
        thread.start()
        return self.get_job(job_id)

    def get_job(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                return dict(job)
        return self._job_from_file(job_id)

    def list_jobs(self, *, limit: int = 50) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 200))
        items: dict[str, dict[str, Any]] = {job["id"]: job for job in self._scan_export_files()}
        with self._lock:
            for job_id, job in self._jobs.items():
                items[job_id] = dict(job)
        return sorted(items.values(), key=lambda job: str(job.get("updated_at") or ""), reverse=True)[:limit]

    def _update_job(self, job_id: str, **updates: Any) -> None:
        with self._lock:
            if job_id not in self._jobs:
                return
            self._jobs[job_id].update(updates)
            self._jobs[job_id]["updated_at"] = _utc_now()

    def _run_export(
        self,
        *,
        job_id: str,
        config: AppConfig,
        asset: str,
        timeframe_sec: int,
        records: int,
    ) -> None:
        self._update_job(job_id, status="running")
        try:
            broker = IQOptionBroker(config) if config.broker.mode == "iqoption" else DemoBroker(config)
            broker.connect()
            candles = self._fetch_candles(
                broker=broker,
                job_id=job_id,
                asset=asset,
                timeframe_sec=timeframe_sec,
                records=records,
            )
            if not candles:
                raise BrokerError(f"No candles returned for {asset}")

            candles = sorted(candles, key=lambda candle: candle.timestamp)
            output_dir = EXPORT_DIR
            output_dir.mkdir(parents=True, exist_ok=True)
            filename = f"{_safe_filename(asset)}_{_timeframe_label(timeframe_sec)}_{len(candles)}_{job_id}.csv"
            output_path = output_dir / filename
            with output_path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=[
                        "asset",
                        "timeframe_sec",
                        "timestamp",
                        "time_utc",
                        "open",
                        "high",
                        "low",
                        "close",
                        "volume",
                    ],
                )
                writer.writeheader()
                for candle in candles:
                    writer.writerow(
                        {
                            "asset": asset,
                            "timeframe_sec": timeframe_sec,
                            "timestamp": int(candle.timestamp),
                            "time_utc": datetime.fromtimestamp(int(candle.timestamp), timezone.utc).isoformat(),
                            "open": candle.open,
                            "high": candle.high,
                            "low": candle.low,
                            "close": candle.close,
                            "volume": candle.volume,
                        }
                    )

            relative_path = output_path.relative_to(ROOT_DIR)
            self._update_job(
                job_id,
                status="done",
                records_written=len(candles),
                file_path=str(output_path),
                relative_path=str(relative_path),
                download_url=f"/api/exports/market/{job_id}/download",
            )
        except Exception as exc:
            self._update_job(job_id, status="error", error=str(exc))

    def _fetch_candles(
        self,
        *,
        broker: Broker,
        job_id: str,
        asset: str,
        timeframe_sec: int,
        records: int,
    ) -> list[Candle]:
        candles_by_timestamp: dict[int, Candle] = {}
        endtime = time.time()
        previous_oldest: Optional[int] = None

        while len(candles_by_timestamp) < records:
            remaining = records - len(candles_by_timestamp)
            batch_size = min(MAX_CANDLE_BATCH, remaining)
            batch = broker.get_candles_until(asset, timeframe_sec, batch_size, endtime)
            if not batch:
                break

            for candle in batch:
                candles_by_timestamp[int(candle.timestamp)] = candle

            oldest = min(int(candle.timestamp) for candle in batch)
            if previous_oldest is not None and oldest >= previous_oldest:
                break
            previous_oldest = oldest
            endtime = oldest - 1
            self._update_job(job_id, records_written=len(candles_by_timestamp))

            if len(batch) < batch_size:
                break

        candles = sorted(candles_by_timestamp.values(), key=lambda candle: candle.timestamp)
        return candles[-records:]

    def file_for_job(self, job_id: str) -> Path:
        job = self.get_job(job_id)
        if job.get("status") != "done" or not job.get("file_path"):
            raise FileNotFoundError(job_id)
        path = Path(str(job["file_path"]))
        if not path.exists():
            raise FileNotFoundError(job_id)
        return path

    def _job_from_file(self, job_id: str) -> dict[str, Any]:
        for path in EXPORT_DIR.glob(f"*_{job_id}.csv"):
            return self._file_job(path)
        raise KeyError(job_id)

    def _scan_export_files(self) -> list[dict[str, Any]]:
        if not EXPORT_DIR.exists():
            return []
        return [self._file_job(path) for path in EXPORT_DIR.glob("*.csv") if path.is_file()]

    def _file_job(self, path: Path) -> dict[str, Any]:
        match = EXPORT_FILENAME_RE.match(path.name)
        stat = path.stat()
        updated_at = datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(timespec="seconds")
        job_id = match.group("id") if match else path.stem[-12:]
        timeframe_label = match.group("timeframe") if match else ""
        records = int(match.group("rows")) if match else 0
        asset = match.group("asset") if match else path.stem
        timeframe_sec = _timeframe_sec(timeframe_label)

        try:
            with path.open("r", encoding="utf-8") as handle:
                first = next(csv.DictReader(handle), None)
            if first:
                asset = first.get("asset") or asset
                timeframe_sec = int(first.get("timeframe_sec") or timeframe_sec)
                timeframe_label = _timeframe_label(timeframe_sec)
        except Exception:
            pass

        relative_path = path.relative_to(ROOT_DIR)
        return {
            "id": job_id,
            "status": "done",
            "asset": asset,
            "timeframe_sec": timeframe_sec,
            "timeframe_label": timeframe_label,
            "records_requested": records,
            "records_written": records,
            "created_at": updated_at,
            "updated_at": updated_at,
            "error": "",
            "file_path": str(path),
            "relative_path": str(relative_path),
            "download_url": f"/api/exports/market/{job_id}/download",
        }


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _safe_filename(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    return cleaned or "asset"


def _timeframe_label(timeframe_sec: int) -> str:
    if timeframe_sec % 60 == 0:
        return f"{timeframe_sec // 60}m"
    return f"{timeframe_sec}s"


def _timeframe_sec(label: str) -> int:
    if label.endswith("m"):
        return int(label[:-1]) * 60
    if label.endswith("s"):
        return int(label[:-1])
    return 0
