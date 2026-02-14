"""Tests for configuration loading."""

from pathlib import Path
from textwrap import dedent

from preciouss.config.schema import Config, load_config


def test_default_config():
    """Loading with no config file returns defaults."""
    config = load_config(Path("/nonexistent/config.toml"))
    assert config.general.default_currency == "CNY"
    assert config.general.ledger_dir == "./ledger"
    assert config.matching.date_tolerance_days == 3


def test_load_config_from_toml(tmp_path):
    """Load a valid config file."""
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        dedent("""\
        [general]
        ledger_dir = "./my_ledger"
        default_currency = "HKD"

        [accounts.alipay]
        type = "payment_platform"
        importer = "alipay"
        beancount_account = "Assets:Alipay"
        currency = "CNY"

        [matching]
        date_tolerance_days = 5
        fuzzy_payee_threshold = 0.8

        [categorize.rules]
        "星巴克" = "Expenses:Food:Coffee"
    """)
    )

    config = load_config(config_file)
    assert config.general.ledger_dir == "./my_ledger"
    assert config.general.default_currency == "HKD"
    assert "alipay" in config.accounts
    assert config.accounts["alipay"].beancount_account == "Assets:Alipay"
    assert config.matching.date_tolerance_days == 5
    assert config.get_categorize_rules()["星巴克"] == "Expenses:Food:Coffee"


def test_config_model_properties():
    """Test Config model computed properties."""
    config = Config()
    assert config.ledger_path == Path("./ledger")
    assert config.main_bean_path == Path("./ledger/main.bean")
