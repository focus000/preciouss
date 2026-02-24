"""Tests for overrides.toml management."""

from __future__ import annotations

import datetime
from decimal import Decimal
from pathlib import Path

import pytest

from preciouss.categorize.bql import MatchedTransaction
from preciouss.categorize.overrides import (
    OverrideEntry,
    add_entries,
    load_overrides,
    save_overrides,
)


def _make_match(ref: str, **kwargs) -> MatchedTransaction:
    defaults = {
        "ref": ref,
        "filename": "/tmp/test.bean",
        "lineno": 1,
        "date": datetime.date(2024, 1, 15),
        "payee": "美团外卖",
        "narration": "午餐",
        "amount": Decimal("-35.00"),
        "currency": "CNY",
        "current_account": "Expenses:Uncategorized",
    }
    defaults.update(kwargs)
    return MatchedTransaction(**defaults)


class TestOverrideEntry:
    def test_has_overrides_empty(self):
        entry = OverrideEntry(ref="abc")
        assert not entry.has_overrides()

    def test_has_overrides_category(self):
        entry = OverrideEntry(ref="abc", category="Expenses:Food:Restaurant")
        assert entry.has_overrides()

    def test_has_overrides_payee(self):
        entry = OverrideEntry(ref="abc", payee="星巴克")
        assert entry.has_overrides()


class TestLoadSaveRoundTrip:
    def test_save_and_load(self, tmp_path: Path):
        path = tmp_path / "overrides.toml"
        entries = {
            "ref001": OverrideEntry(ref="ref001", category="Expenses:Food:Restaurant"),
            "ref002": OverrideEntry(ref="ref002", payee="星巴克"),
        }
        save_overrides(path, entries)

        loaded = load_overrides(path)
        assert "ref001" in loaded
        assert loaded["ref001"].category == "Expenses:Food:Restaurant"
        assert loaded["ref001"].payee == ""
        assert "ref002" in loaded
        assert loaded["ref002"].payee == "星巴克"
        assert loaded["ref002"].category == ""

    def test_save_with_match_info(self, tmp_path: Path):
        path = tmp_path / "overrides.toml"
        entries = {"ref001": OverrideEntry(ref="ref001")}
        match_info = {"ref001": _make_match("ref001")}

        save_overrides(path, entries, match_info)

        content = path.read_text()
        assert '["ref001"]' in content
        assert "美团外卖" in content
        assert "current: Expenses:Uncategorized" in content

    def test_load_nonexistent(self, tmp_path: Path):
        path = tmp_path / "nonexistent.toml"
        assert load_overrides(path) == {}


class TestAddEntries:
    def test_add_new_entries(self, tmp_path: Path):
        path = tmp_path / "overrides.toml"
        match_info = {
            "ref001": _make_match("ref001"),
            "ref002": _make_match("ref002"),
        }

        added = add_entries(path, ["ref001", "ref002"], match_info)
        assert added == 2

        loaded = load_overrides(path)
        assert len(loaded) == 2

    def test_add_with_defaults(self, tmp_path: Path):
        path = tmp_path / "overrides.toml"
        match_info = {"ref001": _make_match("ref001")}

        add_entries(
            path,
            ["ref001"],
            match_info,
            defaults={"category": "Expenses:Food:Coffee"},
        )

        loaded = load_overrides(path)
        assert loaded["ref001"].category == "Expenses:Food:Coffee"

    def test_update_existing_with_defaults(self, tmp_path: Path):
        path = tmp_path / "overrides.toml"
        match_info = {"ref001": _make_match("ref001")}

        # First add with category
        add_entries(
            path, ["ref001"], match_info, defaults={"category": "Expenses:Food:Coffee"}
        )
        # Then update with payee
        added = add_entries(
            path, ["ref001"], match_info, defaults={"payee": "新payee"}
        )

        assert added == 0  # not new
        loaded = load_overrides(path)
        assert loaded["ref001"].category == "Expenses:Food:Coffee"  # preserved
        assert loaded["ref001"].payee == "新payee"  # updated

    def test_update_existing_empty_default_preserves(self, tmp_path: Path):
        path = tmp_path / "overrides.toml"
        match_info = {"ref001": _make_match("ref001")}

        add_entries(
            path, ["ref001"], match_info, defaults={"category": "Expenses:Food:Coffee"}
        )
        # Update with empty category → should NOT overwrite
        add_entries(path, ["ref001"], match_info, defaults={"category": ""})

        loaded = load_overrides(path)
        assert loaded["ref001"].category == "Expenses:Food:Coffee"

    def test_add_mixed_new_and_existing(self, tmp_path: Path):
        path = tmp_path / "overrides.toml"
        match_info = {
            "ref001": _make_match("ref001"),
            "ref002": _make_match("ref002"),
        }

        add_entries(path, ["ref001"], match_info)
        added = add_entries(path, ["ref001", "ref002"], match_info)

        assert added == 1  # only ref002 is new
        loaded = load_overrides(path)
        assert len(loaded) == 2
