"""Tests for the categorization system."""

from datetime import datetime
from decimal import Decimal

from preciouss.categorize.rules import RuleCategorizer
from preciouss.importers.base import Transaction


def _make_tx(payee: str, narration: str = "") -> Transaction:
    return Transaction(
        date=datetime(2024, 1, 15),
        amount=Decimal("-35.00"),
        currency="CNY",
        payee=payee,
        narration=narration,
        source_account="Assets:Alipay",
    )


def test_keyword_categorization():
    """Keywords match against payee and narration."""
    categorizer = RuleCategorizer()

    assert categorizer.categorize(_make_tx("星巴克")) == "Expenses:Food:Coffee"
    assert categorizer.categorize(_make_tx("滴滴出行")) == "Expenses:Transport:Taxi"
    assert categorizer.categorize(_make_tx("美团外卖")) == "Expenses:Food:Delivery"


def test_regex_categorization():
    """Regex rules match complex patterns."""
    categorizer = RuleCategorizer()

    tx = _make_tx("某公司", "工资发放")
    assert categorizer.categorize(tx) == "Income:Salary"

    tx = _make_tx("某商户", "退款-商品退货")
    assert categorizer.categorize(tx) == "Income:Refund"


def test_custom_rules_override():
    """User-provided rules take priority."""
    custom = {"测试商户": "Expenses:Test"}
    categorizer = RuleCategorizer(keyword_rules=custom)

    assert categorizer.categorize(_make_tx("测试商户")) == "Expenses:Test"


def test_no_match_returns_none():
    """Unknown merchants return None."""
    categorizer = RuleCategorizer()
    assert categorizer.categorize(_make_tx("完全未知的商户")) is None
