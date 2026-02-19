"""Pydantic configuration models and TOML loading."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class AccountConfig(BaseModel):
    """Configuration for a single financial account."""

    type: str  # credit_card, debit_card, payment_platform, brokerage, bank
    importer: str  # alipay, wechat, cmb, icbc, etc.
    beancount_account: str  # e.g. Liabilities:CreditCard:CMB
    currency: str = "CNY"
    identifier: str | None = None  # e.g. 尾号1234, used for matching payment methods

    # Supplementary data files (optional)
    orders_file: str | None = None  # order detail JSON (used by JD)

    # API credentials (optional, for API-based importers)
    flex_token: str | None = None
    flex_query_id: str | None = None
    client_id: str | None = None
    client_secret: str | None = None


class MatchingConfig(BaseModel):
    """Configuration for the transaction matching engine."""

    date_tolerance_days: int = 3
    fuzzy_payee_threshold: float = 0.7


class GeneralConfig(BaseModel):
    """General project configuration."""

    ledger_dir: str = "./ledger"
    main_file: str = "main.bean"
    default_currency: str = "CNY"


class Config(BaseModel):
    """Root configuration model."""

    general: GeneralConfig = Field(default_factory=GeneralConfig)
    accounts: dict[str, AccountConfig] = Field(default_factory=dict)
    matching: MatchingConfig = Field(default_factory=MatchingConfig)
    categorize: dict[str, Any] = Field(default_factory=dict)

    @property
    def ledger_path(self) -> Path:
        return Path(self.general.ledger_dir)

    @property
    def main_bean_path(self) -> Path:
        return self.ledger_path / self.general.main_file

    def get_categorize_rules(self) -> dict[str, str]:
        """Get keyword-to-category mapping from config."""
        return self.categorize.get("rules", {})


def _resolve_env_vars(data: dict) -> dict:
    """Recursively resolve ${ENV_VAR} references in string values."""
    resolved = {}
    for key, value in data.items():
        if isinstance(value, dict):
            resolved[key] = _resolve_env_vars(value)
        elif isinstance(value, str) and value.startswith("${") and value.endswith("}"):
            env_var = value[2:-1]
            resolved[key] = os.environ.get(env_var, value)
        else:
            resolved[key] = value
    return resolved


def load_config(config_path: str | Path | None = None) -> Config:
    """Load configuration from a TOML file.

    Args:
        config_path: Path to config.toml. If None, looks for config.toml
                     in the current directory.

    Returns:
        Parsed Config object.
    """
    if config_path is None:
        config_path = Path("config.toml")
    else:
        config_path = Path(config_path)

    if not config_path.exists():
        return Config()

    with open(config_path, "rb") as f:
        raw = tomllib.load(f)

    raw = _resolve_env_vars(raw)
    return Config.model_validate(raw)
