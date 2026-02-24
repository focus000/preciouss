"""Tests for apply_overrides — override application to Transaction objects."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from preciouss.categorize.apply import apply_overrides
from preciouss.categorize.overrides import OverrideEntry
from preciouss.importers.base import Transaction


def _make_tx(ref: str | None = None, **kwargs) -> Transaction:
    defaults = {
        "date": datetime(2024, 1, 15),
        "amount": Decimal("-35.00"),
        "currency": "CNY",
        "payee": "美团外卖",
        "narration": "午餐",
        "source_account": "Assets:Alipay",
        "reference_id": ref,
    }
    defaults.update(kwargs)
    return Transaction(**defaults)


class TestApplyOverrides:
    def test_category_override(self):
        txns = [_make_tx(ref="ref001")]
        overrides = {
            "ref001": OverrideEntry(ref="ref001", category="Expenses:Food:Restaurant")
        }

        count = apply_overrides(txns, overrides)
        assert count == 1
        assert txns[0].counter_account == "Expenses:Food:Restaurant"

    def test_payee_override(self):
        txns = [_make_tx(ref="ref001")]
        overrides = {"ref001": OverrideEntry(ref="ref001", payee="新商户")}

        count = apply_overrides(txns, overrides)
        assert count == 1
        assert txns[0].payee == "新商户"

    def test_narration_override(self):
        txns = [_make_tx(ref="ref001")]
        overrides = {"ref001": OverrideEntry(ref="ref001", narration="晚餐")}

        count = apply_overrides(txns, overrides)
        assert count == 1
        assert txns[0].narration == "晚餐"

    def test_multiple_fields(self):
        txns = [_make_tx(ref="ref001")]
        overrides = {
            "ref001": OverrideEntry(
                ref="ref001",
                category="Expenses:Food:Coffee",
                payee="星巴克",
                narration="拿铁",
            )
        }

        count = apply_overrides(txns, overrides)
        assert count == 1
        assert txns[0].counter_account == "Expenses:Food:Coffee"
        assert txns[0].payee == "星巴克"
        assert txns[0].narration == "拿铁"

    def test_empty_fields_not_applied(self):
        txns = [_make_tx(ref="ref001")]
        overrides = {"ref001": OverrideEntry(ref="ref001")}  # all empty

        count = apply_overrides(txns, overrides)
        assert count == 0
        assert txns[0].counter_account is None  # unchanged
        assert txns[0].payee == "美团外卖"  # unchanged

    def test_no_matching_ref(self):
        txns = [_make_tx(ref="ref001")]
        overrides = {"ref999": OverrideEntry(ref="ref999", category="Expenses:Food")}

        count = apply_overrides(txns, overrides)
        assert count == 0

    def test_tx_without_ref_skipped(self):
        txns = [_make_tx(ref=None)]
        overrides = {"ref001": OverrideEntry(ref="ref001", category="Expenses:Food")}

        count = apply_overrides(txns, overrides)
        assert count == 0

    def test_multiple_transactions(self):
        txns = [
            _make_tx(ref="ref001"),
            _make_tx(ref="ref002"),
            _make_tx(ref="ref003"),
        ]
        overrides = {
            "ref001": OverrideEntry(ref="ref001", category="Expenses:Food:Restaurant"),
            "ref003": OverrideEntry(ref="ref003", payee="新商户"),
        }

        count = apply_overrides(txns, overrides)
        assert count == 2
        assert txns[0].counter_account == "Expenses:Food:Restaurant"
        assert txns[1].counter_account is None  # not overridden
        assert txns[2].payee == "新商户"

    def test_empty_overrides_dict(self):
        txns = [_make_tx(ref="ref001")]
        count = apply_overrides(txns, {})
        assert count == 0

    def test_empty_transactions(self):
        overrides = {"ref001": OverrideEntry(ref="ref001", category="Expenses:Food")}
        count = apply_overrides([], overrides)
        assert count == 0
