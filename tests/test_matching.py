"""Tests for the matching engine."""

from datetime import datetime
from decimal import Decimal

from preciouss.importers.base import Transaction
from preciouss.matching.engine import MatchingEngine


def _make_tx(**kwargs) -> Transaction:
    """Helper to create test transactions."""
    defaults = {
        "date": datetime(2024, 1, 15),
        "amount": Decimal("-35.00"),
        "currency": "CNY",
        "payee": "星巴克",
        "narration": "咖啡",
        "source_account": "Assets:Alipay",
        "tx_type": "expense",
    }
    defaults.update(kwargs)
    return Transaction(**defaults)


def test_reference_matching():
    """Phase 1: Match by reference ID."""
    engine = MatchingEngine()

    tx_alipay = _make_tx(
        reference_id="REF001",
        source_account="Assets:Alipay",
    )
    tx_bank = _make_tx(
        counterpart_ref="REF001",
        source_account="Liabilities:CreditCard:CMB",
    )
    tx_unrelated = _make_tx(
        reference_id="REF999",
        source_account="Assets:WeChat",
    )

    result = engine.match([tx_alipay, tx_bank, tx_unrelated])

    assert len(result.matched) == 1
    assert result.matched[0].match_type == "reference"
    assert result.matched[0].confidence == 1.0
    assert len(result.unmatched) == 1


def test_intermediary_matching():
    """Phase 2: Match payment platform -> credit card pattern."""
    engine = MatchingEngine()

    # Alipay transaction paid with CMB credit card
    tx_alipay = _make_tx(
        amount=Decimal("-45.50"),
        payment_method="招商银行信用卡(尾号1234)",
        source_account="Assets:Alipay",
    )
    # Bank statement showing the same amount from 支付宝
    tx_bank = _make_tx(
        amount=Decimal("-45.50"),
        payee="支付宝-美团外卖",
        narration="支付宝消费",
        source_account="Liabilities:CreditCard:CMB",
    )

    result = engine.match([tx_alipay, tx_bank])

    assert len(result.matched) == 1
    assert result.matched[0].match_type == "intermediary"
    assert len(result.unmatched) == 0


def test_no_self_matching():
    """Transactions from the same source should not match."""
    engine = MatchingEngine()

    tx1 = _make_tx(reference_id="REF001", source_account="Assets:Alipay")
    tx2 = _make_tx(reference_id="REF001", source_account="Assets:Alipay")

    result = engine.match([tx1, tx2])
    assert len(result.matched) == 0
    assert len(result.unmatched) == 2


def test_unmatched_transactions():
    """Transactions with no match remain unmatched."""
    engine = MatchingEngine()

    tx1 = _make_tx(amount=Decimal("-35.00"), source_account="Assets:Alipay")
    tx2 = _make_tx(amount=Decimal("-100.00"), source_account="Liabilities:CreditCard:CMB")

    result = engine.match([tx1, tx2])
    assert len(result.matched) == 0
    assert len(result.unmatched) == 2
