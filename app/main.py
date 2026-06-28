from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from app.broker import BrokerError
from app.config import ROOT_DIR, load_config, resolve_storage_path
from app.db import Database
from app.engine import TradingEngine
from app.market_export import MarketExportManager
from app.telegram_integration import TelegramSignalManager


class ManualTradeRequest(BaseModel):
    asset: str = Field(default="EURUSD-OTC", min_length=3, max_length=32)
    instrument: str = "binary"
    direction: str
    amount: float = Field(gt=0)
    duration_minutes: int = Field(default=1, ge=1, le=60)

    @field_validator("instrument")
    @classmethod
    def validate_instrument(cls, value: str) -> str:
        value = value.lower().strip()
        if value not in {"binary", "turbo"}:
            raise ValueError("instrument must be binary or turbo")
        return value

    @field_validator("direction")
    @classmethod
    def validate_direction(cls, value: str) -> str:
        value = value.lower().strip()
        if value not in {"call", "put"}:
            raise ValueError("direction must be call or put")
        return value


class TradingControlsRequest(BaseModel):
    asset: str = Field(default="EURUSD-OTC", min_length=3, max_length=32)
    instrument: str = "binary"
    amount: float = Field(gt=0)
    duration_minutes: int = Field(default=1, ge=1, le=60)
    take_profit: float = Field(default=0.0, ge=0)
    max_daily_loss: float = Field(default=1000.0, gt=0)
    martingale_enabled: bool = False
    martingale_3step_enabled: bool = False

    @field_validator("asset")
    @classmethod
    def validate_asset(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("asset must not be empty")
        return value

    @field_validator("instrument")
    @classmethod
    def validate_instrument(cls, value: str) -> str:
        value = value.lower().strip()
        if value not in {"binary", "turbo"}:
            raise ValueError("instrument must be binary or turbo")
        return value


class AssetRuleRequest(BaseModel):
    asset: str = Field(min_length=3, max_length=64)
    enabled: bool
    direction: Optional[str] = None

    @field_validator("asset")
    @classmethod
    def validate_asset(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("asset must not be empty")
        return value

    @field_validator("direction")
    @classmethod
    def validate_direction(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        direction = value.lower().strip()
        if direction not in {"call", "put"}:
            raise ValueError("direction must be call or put")
        return direction


class MarketExportRequest(BaseModel):
    asset: str = Field(min_length=3, max_length=64)
    timeframe_sec: int = Field(default=60)
    records: int = Field(default=1000, ge=1, le=50000)

    @field_validator("asset")
    @classmethod
    def validate_asset(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("asset must not be empty")
        return value

    @field_validator("timeframe_sec")
    @classmethod
    def validate_timeframe_sec(cls, value: int) -> int:
        if value not in {60, 300}:
            raise ValueError("timeframe_sec must be 60 or 300")
        return value


class TelegramControlsRequest(BaseModel):
    enabled: bool = False
    follow_signals: bool = False


def create_app() -> FastAPI:
    config = load_config()
    db = Database(resolve_storage_path(config))
    db.init()
    engine = TradingEngine(config, db)
    export_manager = MarketExportManager()
    telegram_manager = TelegramSignalManager(config, db, engine)

    app = FastAPI(title="IQ Auto Trader", version="0.1.0")
    app.state.config = config
    app.state.db = db
    app.state.engine = engine
    app.state.export_manager = export_manager
    app.state.telegram_manager = telegram_manager

    static_dir = ROOT_DIR / "static"

    @app.on_event("startup")
    async def startup() -> None:
        db.add_event("info", "system", "Server started", {"mode": config.broker.mode})
        await telegram_manager.startup()
        if config.trading.enabled_on_start:
            try:
                await engine.start()
            except BrokerError as exc:
                db.add_event("error", "bot", "Autostart failed", {"error": str(exc)})

    @app.on_event("shutdown")
    async def shutdown() -> None:
        await telegram_manager.shutdown()

    @app.get("/api/status")
    async def status() -> dict:
        data = engine.status()
        data["telegram"] = telegram_manager.status()
        return data

    @app.post("/api/bot/start")
    async def start_bot() -> dict:
        try:
            result = await engine.start()
            if config.telegram.enabled and config.telegram.follow_signals:
                telegram_manager.schedule_prime_latest_pending_signal()
            return result
        except BrokerError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/bot/stop")
    async def stop_bot() -> dict:
        telegram_manager.cancel_pending_orders()
        return await engine.stop()

    @app.post("/api/bot/tick")
    async def tick_bot() -> dict:
        try:
            return await engine.tick()
        except BrokerError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/config/reload")
    async def reload_config() -> dict:
        return await engine.reload_config()

    @app.post("/api/config/trading")
    async def update_trading_controls(payload: TradingControlsRequest) -> dict:
        return await engine.update_trading_controls(**payload.model_dump())

    @app.post("/api/config/asset-rule")
    async def update_asset_rule(payload: AssetRuleRequest) -> dict:
        try:
            return await engine.update_asset_enabled(**payload.model_dump())
        except BrokerError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/trades/manual")
    async def manual_trade(payload: ManualTradeRequest) -> dict:
        try:
            return await engine.manual_trade(**payload.model_dump())
        except BrokerError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/trades/settle")
    async def settle_trades() -> dict:
        try:
            return await engine.settle_due_trades()
        except BrokerError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/history/clear")
    async def clear_history() -> dict:
        try:
            return await engine.clear_history()
        except BrokerError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/stats/reset")
    async def reset_stats() -> dict:
        try:
            return await engine.reset_stats()
        except BrokerError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/trades")
    async def trades(
        limit: int = Query(default=50, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
        status: Optional[str] = None,
    ) -> dict:
        return {"items": db.list_trades(limit=limit, offset=offset, status=status)}

    @app.get("/api/stats/assets")
    async def asset_stats(
        date: Optional[str] = None,
        source: Optional[str] = None,
        scope: str = "session",
    ) -> dict:
        if source == "telegram":
            return {
                "items": db.telegram_asset_stats(
                    date=date,
                    min_signals=engine.config.telegram.min_history_signals,
                )
            }
        since = engine.stats_since_at() if scope == "session" and not date else None
        return {"items": db.asset_stats(date=date, since=since)}

    @app.get("/api/telegram/status")
    async def telegram_status() -> dict:
        return telegram_manager.status(include_summary=True)

    @app.post("/api/telegram/controls")
    async def update_telegram_controls(payload: TelegramControlsRequest) -> dict:
        return await telegram_manager.update_controls(**payload.model_dump())

    @app.post("/api/telegram/import-history")
    async def import_telegram_history() -> dict:
        return telegram_manager.import_history()

    @app.get("/api/telegram/signals")
    async def telegram_signals(
        limit: int = Query(default=30, ge=1, le=200),
        mapped_only: bool = False,
    ) -> dict:
        return {"items": db.list_telegram_signals(limit=limit, mapped_only=mapped_only)}

    @app.get("/api/broker/assets")
    async def broker_assets() -> dict:
        try:
            return await engine.list_broker_assets()
        except BrokerError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/exports/market")
    async def create_market_export(payload: MarketExportRequest) -> dict:
        return export_manager.create_job(
            config=engine.config,
            asset=payload.asset,
            timeframe_sec=payload.timeframe_sec,
            records=payload.records,
        )

    @app.get("/api/exports/market/history")
    async def market_export_history(limit: int = Query(default=50, ge=1, le=200)) -> dict:
        return {"items": export_manager.list_jobs(limit=limit)}

    @app.get("/api/exports/market/{job_id}")
    async def market_export_status(job_id: str) -> dict:
        try:
            return export_manager.get_job(job_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="export job not found") from exc

    @app.get("/api/exports/market/{job_id}/download")
    async def market_export_download(job_id: str) -> FileResponse:
        try:
            path = export_manager.file_for_job(job_id)
        except (KeyError, FileNotFoundError) as exc:
            raise HTTPException(status_code=404, detail="export file not ready") from exc
        return FileResponse(path, media_type="text/csv", filename=path.name)

    @app.get("/api/events")
    async def events(
        limit: int = Query(default=20, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
    ) -> dict:
        return {"items": db.list_events(limit=limit, offset=offset)}

    @app.get("/api/signals")
    async def signals(limit: int = Query(default=80, ge=1, le=200)) -> dict:
        return {"items": db.list_signals(limit=limit)}

    @app.get("/api/equity")
    async def equity(
        limit: int = Query(default=120, ge=1, le=500),
        scope: str = "session",
    ) -> dict:
        since = engine.stats_since_at() if scope == "session" else None
        return {"items": db.equity_curve(limit=limit, since=since)}

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(static_dir / "index.html", headers={"Cache-Control": "no-store"})

    @app.get("/export")
    async def export_page() -> FileResponse:
        return FileResponse(static_dir / "export.html", headers={"Cache-Control": "no-store"})

    app.mount("/static", StaticFiles(directory=static_dir), name="static")
    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    cfg = load_config()
    uvicorn.run(
        "app.main:app",
        host=cfg.server.host,
        port=cfg.server.port,
        reload=True,
    )
