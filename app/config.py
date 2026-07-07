from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional, Union

import yaml
from pydantic import BaseModel, Field, field_validator


ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = ROOT_DIR / "config.yaml"


class BrokerConfig(BaseModel):
    mode: str = "demo"
    account_type: str = "PRACTICE"
    email: str = ""
    password: str = ""
    two_factor_code: str = ""
    connect_timeout_sec: int = Field(default=12, ge=3, le=120)

    @field_validator("mode")
    @classmethod
    def validate_mode(cls, value: str) -> str:
        value = value.lower().strip()
        if value not in {"demo", "iqoption"}:
            raise ValueError("broker.mode must be demo or iqoption")
        return value

    @field_validator("account_type")
    @classmethod
    def validate_account_type(cls, value: str) -> str:
        value = value.upper().strip()
        if value not in {"PRACTICE", "REAL", "TOURNAMENT"}:
            raise ValueError("broker.account_type must be PRACTICE, REAL, or TOURNAMENT")
        return value


class AssetRuleConfig(BaseModel):
    enabled: bool = True
    allow_directions: list[str] = Field(default_factory=list)
    min_confidence: Optional[float] = Field(default=None, ge=0.0, le=0.99)
    min_abs_momentum: Optional[float] = Field(default=None, ge=0)
    max_atr_ratio: Optional[float] = Field(default=None, ge=0)
    min_rsi: Optional[float] = Field(default=None, ge=0, le=100)
    max_rsi: Optional[float] = Field(default=None, ge=0, le=100)

    @field_validator("allow_directions")
    @classmethod
    def validate_allow_directions(cls, value: list[str]) -> list[str]:
        cleaned: list[str] = []
        seen: set[str] = set()
        for item in value:
            direction = item.lower().strip()
            if direction in {"call", "put"} and direction not in seen:
                cleaned.append(direction)
                seen.add(direction)
        return cleaned


class TradingConfig(BaseModel):
    enabled_on_start: bool = False
    asset: str = "EURUSD-OTC"
    auto_select_asset: bool = True
    assets: list[str] = Field(
        default_factory=lambda: [
            "EURUSD-OTC",
            "GBPUSD-OTC",
            "USDJPY-OTC",
            "EURJPY-OTC",
            "AUDCAD-OTC",
            "AUDJPY-OTC",
            "ALIBABA-OTC",
            "CASINOS-OTC",
            "ETHUSD-OTC",
            "ONDOUSD-OTC",
            "OpenAI-OTC",
            "SP500-OTC",
            "AUDCHF-OTC",
            "AUDNZD-OTC",
            "AUDUSD-OTC",
            "CADJPY-OTC",
            "EURGBP-OTC",
            "EURNZD-OTC",
            "GBPJPY-OTC",
            "GBPNZD-OTC",
            "NZDCAD-OTC",
            "NZDCHF-OTC",
            "NZDJPY-OTC",
            "NZDUSD-OTC",
            "USDCHF-OTC",
            "USDHKD-OTC",
            "USDSGD-OTC",
        ]
    )
    instrument: str = "binary"
    amount: float = Field(default=1.0, gt=0)
    duration_minutes: int = Field(default=1, ge=1, le=60)
    candle_interval_sec: int = Field(default=60, ge=5)
    lookback_candles: int = Field(default=120, ge=30, le=500)
    poll_interval_sec: int = Field(default=1, ge=1, le=3600)
    entry_window_seconds: list[int] = Field(default_factory=lambda: [59, 0])
    entry_scan_lead_sec: int = Field(default=4, ge=0, le=30)
    signal_scan_timeout_sec: int = Field(default=20, ge=2, le=60)
    strategy_cooldown_after_loss_candles: int = Field(default=1, ge=0, le=20)
    order_timeout_sec: int = Field(default=12, ge=3, le=120)
    martingale_enabled: bool = False
    martingale_3step_enabled: bool = False
    strategy: str = "asset_specific"
    min_confidence: float = Field(default=0.62, ge=0.5, le=0.99)
    min_abs_momentum: float = Field(default=0.0002, ge=0)
    max_atr_ratio: float = Field(default=0.0005, ge=0)
    max_rsi: float = Field(default=65.0, ge=0, le=100)
    blocked_asset_directions: list[str] = Field(
        default_factory=lambda: [
            "EURUSD-OTC:put",
            "GBPUSD-OTC:call",
        ]
    )
    asset_rules: dict[str, AssetRuleConfig] = Field(default_factory=dict)
    one_open_trade_at_a_time: bool = True

    @field_validator("instrument")
    @classmethod
    def validate_instrument(cls, value: str) -> str:
        value = value.lower().strip()
        if value not in {"binary", "turbo"}:
            raise ValueError("trading.instrument must be binary or turbo")
        return value

    @field_validator("asset")
    @classmethod
    def validate_asset(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("trading.asset must not be empty")
        return value

    @field_validator("assets")
    @classmethod
    def validate_assets(cls, value: list[str]) -> list[str]:
        cleaned: list[str] = []
        seen: set[str] = set()
        for item in value:
            asset = item.strip()
            if asset and asset not in seen:
                cleaned.append(asset)
                seen.add(asset)
        if not cleaned:
            raise ValueError("trading.assets must contain at least one asset")
        return cleaned

    @field_validator("entry_window_seconds")
    @classmethod
    def validate_entry_window_seconds(cls, value: list[int]) -> list[int]:
        cleaned: list[int] = []
        seen: set[int] = set()
        for item in value:
            second = int(item)
            if 0 <= second <= 59 and second not in seen:
                cleaned.append(second)
                seen.add(second)
        return cleaned or [59, 0]

    @field_validator("blocked_asset_directions")
    @classmethod
    def validate_blocked_asset_directions(cls, value: list[str]) -> list[str]:
        cleaned: list[str] = []
        seen: set[str] = set()
        for item in value:
            raw = item.strip()
            if not raw or ":" not in raw:
                continue
            asset, direction = raw.rsplit(":", 1)
            direction = direction.lower().strip()
            asset = asset.strip()
            if direction not in {"call", "put"} or not asset:
                continue
            key = f"{asset}:{direction}"
            if key not in seen:
                cleaned.append(key)
                seen.add(key)
        return cleaned


class RiskConfig(BaseModel):
    max_trade_amount: float = Field(default=0.0, ge=0)
    max_daily_loss: float = Field(default=1000.0, gt=0)
    take_profit: float = Field(default=0.0, ge=0)
    max_trades_per_day: int = Field(default=0, ge=0)
    cooldown_sec: int = Field(default=45, ge=0)
    stop_after_consecutive_losses: int = Field(default=0, ge=0)
    asset_direction_loss_limit: int = Field(default=2, ge=0, le=20)
    asset_direction_cooldown_sec: int = Field(default=900, ge=0)
    allow_real_balance: bool = False


class StorageConfig(BaseModel):
    sqlite_path: str = "data/trading.db"


class ServerConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = Field(default=8887, ge=1, le=65535)


class TelegramConfig(BaseModel):
    enabled: bool = False
    follow_signals: bool = False
    follow_latest_pending: bool = True
    signal_source: str = "sala"
    api_id: Union[int, str] = ""
    api_hash: str = ""
    phone: str = ""
    channel: str = ""
    session_path: str = "data/telegram_session"
    source_logs_path: str = "data/telegram_source_logs/signal_dataset"
    runtime_state_path: str = "data/telegram_source_logs/telegram_runtime_state.json"
    entry_lead_seconds: float = Field(default=1.0, ge=0.0, le=10.0)
    min_history_signals: int = Field(default=3, ge=1, le=500)
    import_history_limit: int = Field(default=2500, ge=100, le=20000)
    default_expiry_minutes: int = Field(default=1, ge=1, le=60)
    paper_enabled: bool = True
    paper_channel_keyword: str = "น้องหรั่ง"
    paper_history_hours: int = Field(default=24, ge=1, le=168)
    paper_import_limit: int = Field(default=2000, ge=100, le=20000)

    @field_validator("signal_source")
    @classmethod
    def validate_signal_source(cls, value: str) -> str:
        value = str(value or "sala").lower().strip()
        if value not in {"sala", "nongrang"}:
            raise ValueError("telegram.signal_source must be sala or nongrang")
        return value


class AppConfig(BaseModel):
    broker: BrokerConfig = Field(default_factory=BrokerConfig)
    trading: TradingConfig = Field(default_factory=TradingConfig)
    risk: RiskConfig = Field(default_factory=RiskConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)

    def safe_dict(self) -> dict[str, Any]:
        data = self.model_dump()
        data["broker"]["password"] = "********" if self.broker.password else ""
        data["broker"]["email"] = self._mask_email(self.broker.email)
        data["broker"]["two_factor_code"] = "******" if self.broker.two_factor_code else ""
        data["telegram"]["api_id"] = "******" if self.telegram.api_id else ""
        data["telegram"]["api_hash"] = "********" if self.telegram.api_hash else ""
        data["telegram"]["phone"] = "********" if self.telegram.phone else ""
        return data

    @staticmethod
    def _mask_email(email: str) -> str:
        if not email or "@" not in email:
            return ""
        name, domain = email.split("@", 1)
        if len(name) <= 2:
            masked = name[0] + "*"
        else:
            masked = name[:2] + "***"
        return f"{masked}@{domain}"


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_config(path: Optional[Union[str, Path]] = None) -> AppConfig:
    config_path = Path(path or os.getenv("IQ_AUTO_CONFIG") or DEFAULT_CONFIG_PATH)
    defaults = AppConfig().model_dump()
    if config_path.exists():
        with config_path.open("r", encoding="utf-8") as handle:
            loaded = yaml.safe_load(handle) or {}
        defaults = _deep_merge(defaults, loaded)
    return AppConfig.model_validate(defaults)


def resolve_storage_path(config: AppConfig) -> Path:
    path = Path(config.storage.sqlite_path)
    if not path.is_absolute():
        path = ROOT_DIR / path
    path.parent.mkdir(parents=True, exist_ok=True)
    return path
