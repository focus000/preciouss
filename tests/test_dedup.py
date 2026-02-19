"""Tests for transaction deduplication logic."""

from datetime import datetime
from decimal import Decimal

from preciouss.cli import _deduplicate
from preciouss.importers.base import Transaction


def _make_tx(ref_id: str | None, payee: str = "Test", amount: float = -10.0) -> Transaction:
    return Transaction(
        date=datetime(2024, 1, 15, 10, 0, 0),
        amount=Decimal(str(amount)),
        currency="CNY",
        payee=payee,
        narration="test",
        source_account="Assets:Test",
        reference_id=ref_id,
    )


def test_deduplicate_by_reference_id():
    """Transactions with the same reference_id are deduplicated."""
    txns = [
        _make_tx("REF001", payee="A"),
        _make_tx("REF002", payee="B"),
        _make_tx("REF001", payee="A-duplicate"),  # duplicate
        _make_tx("REF003", payee="C"),
    ]
    result = _deduplicate(txns)
    assert len(result) == 3
    assert [tx.payee for tx in result] == ["A", "B", "C"]


def test_deduplicate_keeps_no_ref_id():
    """Transactions without reference_id are always kept."""
    txns = [
        _make_tx(None, payee="NoRef-1"),
        _make_tx(None, payee="NoRef-2"),
        _make_tx("REF001", payee="WithRef"),
    ]
    result = _deduplicate(txns)
    assert len(result) == 3


def test_deduplicate_preserves_order():
    """First occurrence is kept, order is preserved."""
    txns = [
        _make_tx("REF003", payee="Third"),
        _make_tx("REF001", payee="First"),
        _make_tx("REF002", payee="Second"),
        _make_tx("REF001", payee="First-dup"),
        _make_tx("REF003", payee="Third-dup"),
    ]
    result = _deduplicate(txns)
    assert len(result) == 3
    assert [tx.payee for tx in result] == ["Third", "First", "Second"]


def test_deduplicate_empty_list():
    """Empty list returns empty list."""
    assert _deduplicate([]) == []


def test_deduplicate_all_unique():
    """No duplicates means all are kept."""
    txns = [_make_tx(f"REF{i:03d}") for i in range(5)]
    result = _deduplicate(txns)
    assert len(result) == 5


def test_deduplicate_mixed_ref_and_no_ref():
    """Mix of ref_id and None: duplicates removed, None always kept."""
    txns = [
        _make_tx("REF001", payee="A"),
        _make_tx(None, payee="NoRef"),
        _make_tx("REF001", payee="A-dup"),
        _make_tx(None, payee="NoRef-2"),
        _make_tx("REF002", payee="B"),
    ]
    result = _deduplicate(txns)
    assert len(result) == 4
    assert [tx.payee for tx in result] == ["A", "NoRef", "NoRef-2", "B"]
