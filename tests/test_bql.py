"""Tests for BQL query layer."""

from __future__ import annotations

from pathlib import Path

import pytest

from preciouss.categorize.bql import (
    MatchedTransaction,
    connect,
    find_by_refs,
    query_transactions,
    read_bean_entry,
)

# Minimal valid beancount ledger for testing
_LEDGER = """\
option "title" "Test Ledger"
option "operating_currency" "CNY"

1970-01-01 commodity CNY

1970-01-01 open Assets:Alipay CNY
1970-01-01 open Assets:Bank:CMB CNY
1970-01-01 open Expenses:Uncategorized CNY
1970-01-01 open Expenses:Food:Restaurant CNY
1970-01-01 open Income:Uncategorized CNY

2024-01-15 * "美团外卖" "午餐"
  ref: "ref001"
  Assets:Alipay           -35.00 CNY
  Expenses:Uncategorized   35.00 CNY

2024-01-16 * "星巴克" "咖啡"
  ref: "ref002"
  Assets:Alipay           -38.00 CNY
  Expenses:Food:Restaurant 38.00 CNY

2024-01-17 * "公司" "工资"
  ref: "ref003"
  Assets:Bank:CMB         10000.00 CNY
  Income:Uncategorized   -10000.00 CNY

2024-01-18 * "转账" "无ref交易"
  Assets:Alipay           -100.00 CNY
  Assets:Bank:CMB          100.00 CNY
"""


@pytest.fixture()
def ledger_dir(tmp_path: Path) -> Path:
    """Create a temporary ledger directory with test data."""
    main = tmp_path / "main.bean"
    main.write_text(_LEDGER, encoding="utf-8")
    return tmp_path


class TestConnect:
    def test_connect_success(self, ledger_dir: Path):
        conn = connect(str(ledger_dir), "main.bean")
        assert conn is not None


class TestQueryTransactions:
    def test_default_where_uncategorized(self, ledger_dir: Path):
        conn = connect(str(ledger_dir), "main.bean")
        results = query_transactions(conn)

        refs = {m.ref for m in results}
        assert "ref001" in refs  # Expenses:Uncategorized
        assert "ref003" in refs  # Income:Uncategorized
        assert "ref002" not in refs  # already categorized

    def test_custom_where(self, ledger_dir: Path):
        conn = connect(str(ledger_dir), "main.bean")
        results = query_transactions(conn, "narration ~ '咖啡'")

        assert len(results) == 1
        assert results[0].ref == "ref002"
        assert results[0].current_account == "Expenses:Food:Restaurant"

    def test_matched_transaction_fields(self, ledger_dir: Path):
        conn = connect(str(ledger_dir), "main.bean")
        results = query_transactions(conn, "ANY_META('ref') = 'ref001'")

        assert len(results) == 1
        m = results[0]
        assert m.ref == "ref001"
        assert m.payee == "美团外卖"
        assert m.narration == "午餐"
        assert m.current_account == "Expenses:Uncategorized"
        assert m.currency == "CNY"

    def test_skips_no_ref_transactions(self, ledger_dir: Path):
        conn = connect(str(ledger_dir), "main.bean")
        # The transfer has no ref and no Expenses/Income posting
        results = query_transactions(conn, "narration ~ '无ref'")
        assert len(results) == 0

    def test_all_transactions(self, ledger_dir: Path):
        conn = connect(str(ledger_dir), "main.bean")
        results = query_transactions(conn, "1 = 1")

        # ref001, ref002, ref003 have category postings; the transfer has none
        refs = {m.ref for m in results}
        assert refs == {"ref001", "ref002", "ref003"}


class TestFindByRefs:
    def test_find_single(self, ledger_dir: Path):
        conn = connect(str(ledger_dir), "main.bean")
        results = find_by_refs(conn, ["ref001"])

        assert len(results) == 1
        assert results[0].ref == "ref001"

    def test_find_multiple(self, ledger_dir: Path):
        conn = connect(str(ledger_dir), "main.bean")
        results = find_by_refs(conn, ["ref001", "ref002"])

        refs = {m.ref for m in results}
        assert refs == {"ref001", "ref002"}

    def test_find_nonexistent(self, ledger_dir: Path):
        conn = connect(str(ledger_dir), "main.bean")
        results = find_by_refs(conn, ["nonexistent"])

        assert len(results) == 0

    def test_find_empty_list(self, ledger_dir: Path):
        conn = connect(str(ledger_dir), "main.bean")
        results = find_by_refs(conn, [])
        assert len(results) == 0


class TestReadBeanEntry:
    def test_read_entry(self, ledger_dir: Path):
        conn = connect(str(ledger_dir), "main.bean")
        results = query_transactions(conn, "ANY_META('ref') = 'ref001'")
        assert len(results) == 1

        entry = read_bean_entry(results[0].filename, results[0].lineno)
        assert "美团外卖" in entry
        assert "午餐" in entry
        assert "35.00 CNY" in entry

    def test_read_nonexistent_file(self):
        entry = read_bean_entry("/nonexistent/file.bean", 1)
        assert entry == ""

    def test_read_invalid_lineno(self, ledger_dir: Path):
        main = str(ledger_dir / "main.bean")
        entry = read_bean_entry(main, 99999)
        assert entry == ""
