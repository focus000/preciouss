"""Tests for clearing link generation (DFS matching)."""

from datetime import datetime
from decimal import Decimal

from beancount.loader import load_string

from preciouss.importers.base import PrecioussImporter, Transaction, _amounts_match
from preciouss.ledger.writer import init_ledger, write_transactions
from preciouss.matching.clearing import assign_clearing_links


class _StubImporter(PrecioussImporter):
    """Minimal importer for tests — only match_clearing is used."""

    def identify(self, filepath):
        return False

    def extract(self, filepath):
        return []

    def account_name(self):
        return "Assets:Stub"


def _make_tx(**kwargs) -> Transaction:
    """Helper to build a Transaction with sensible defaults."""
    defaults = {
        "date": datetime(2024, 1, 15),
        "amount": Decimal("-100.00"),
        "currency": "CNY",
        "payee": "Test",
        "narration": "test",
        "source_account": "Assets:Clearing:JD",
        "tx_type": "expense",
        "metadata": {},
    }
    defaults.update(kwargs)
    # Ensure metadata is always a fresh dict (not shared)
    if "metadata" not in kwargs:
        defaults["metadata"] = {}
    return Transaction(**defaults)


def _run_clearing(transactions: list[Transaction], importers=None):
    """Helper: run assign_clearing_links with a stub importer for all txns."""
    imp = _StubImporter()
    if importers is None:
        importers = {i: imp for i in range(len(transactions))}
    return assign_clearing_links(transactions, importers)


# ─── Unit tests: terminal detection & amounts ───────────────────────


def test_terminal_expense_gets_link():
    """A clearing→Expenses terminal expense gets a link."""
    tx = _make_tx(source_account="Assets:Clearing:JD", tx_type="expense")
    stats = _run_clearing([tx])
    assert tx.metadata.get("link") is not None
    assert tx.metadata["link"].startswith("clr-")
    assert stats.total_chains == 1
    assert stats.total_linked == 1


def test_non_terminal_no_link():
    """A bridge (clearing→clearing) does NOT generate its own link."""
    tx = _make_tx(
        source_account="Assets:Clearing:JD:WX",
        counter_account="Assets:Clearing:JD",
        tx_type="expense",
    )
    stats = _run_clearing([tx])
    assert tx.metadata.get("link") is None
    assert stats.total_chains == 0


def test_income_no_link():
    """Income transactions don't generate links."""
    tx = _make_tx(source_account="Assets:Clearing:JD", tx_type="income")
    stats = _run_clearing([tx])
    assert tx.metadata.get("link") is None
    assert stats.total_chains == 0


def test_non_clearing_source_no_link():
    """Non-clearing source (e.g. Assets:WeChat) → Expenses doesn't generate link."""
    tx = _make_tx(source_account="Assets:WeChat", tx_type="expense")
    stats = _run_clearing([tx])
    assert tx.metadata.get("link") is None
    assert stats.total_chains == 0


def test_amounts_match_same_currency():
    """Same currency amount matching works."""
    a = _make_tx(amount=Decimal("-100.00"), currency="CNY")
    b = _make_tx(amount=Decimal("100.00"), currency="CNY")
    assert _amounts_match(a, b) is True


def test_amounts_match_cross_currency():
    """Cross-currency matching via wechathk_foreign_amount."""
    a = _make_tx(
        amount=Decimal("-618.26"),
        currency="HKD",
        metadata={"wechathk_foreign_amount": "570.80", "wechathk_foreign_currency": "CNY"},
    )
    b = _make_tx(amount=Decimal("-570.80"), currency="CNY")
    assert _amounts_match(a, b) is True


def test_amounts_no_match_different():
    """Different amounts don't match."""
    a = _make_tx(amount=Decimal("-100.00"), currency="CNY")
    b = _make_tx(amount=Decimal("-99.00"), currency="CNY")
    assert _amounts_match(a, b) is False


# ─── DFS chain tests ────────────────────────────────────────────────


def test_2leg_chain():
    """ALDI: terminal(Clearing:ALDI→Expenses) + payment(WX→Clearing:ALDI) share link."""
    terminal = _make_tx(
        source_account="Assets:Clearing:ALDI",
        tx_type="expense",
        reference_id="ALDI001",
        metadata={},
    )
    payment = _make_tx(
        source_account="Assets:Clearing:WX:CC:CMB",
        counter_account="Assets:Clearing:ALDI",
        tx_type="expense",
        counterpart_ref="ALDI001",
        metadata={},
    )
    stats = _run_clearing([terminal, payment])
    assert stats.total_chains == 1
    assert stats.total_linked == 2
    assert terminal.metadata["link"] == payment.metadata["link"]


def test_3leg_chain():
    """JD: terminal(Clearing:JD→Expenses) + bridge(Clearing:JD:WX→Clearing:JD)
    + payment(WX:CC:CMB→Clearing:JD:WX) share link."""
    terminal = _make_tx(
        source_account="Assets:Clearing:JD",
        tx_type="expense",
        reference_id="ORDER001",
        metadata={},
    )
    bridge = _make_tx(
        source_account="Assets:Clearing:JD:WX",
        counter_account="Assets:Clearing:JD",
        tx_type="expense",
        counterpart_ref="ORDER001",
        reference_id="JD_TRADE001",
        metadata={},
    )
    payment = _make_tx(
        source_account="Assets:Clearing:WX:CC:CMB",
        counter_account="Assets:Clearing:JD:WX",
        tx_type="expense",
        counterpart_ref="JD_TRADE001",
        metadata={},
    )
    stats = _run_clearing([terminal, bridge, payment])
    assert stats.total_chains == 1
    assert stats.total_linked == 3
    link = terminal.metadata["link"]
    assert bridge.metadata["link"] == link
    assert payment.metadata["link"] == link


def test_cross_currency_chain():
    """Costco(CNY) + WechatHK(HKD) share link via foreign_amount matching."""
    terminal = _make_tx(
        source_account="Assets:Clearing:Costco",
        amount=Decimal("-570.80"),
        currency="CNY",
        tx_type="expense",
        counterpart_ref="COSTCO_ORDER",
        metadata={},
    )
    payment = _make_tx(
        source_account="Assets:WeChatHK",
        counter_account="Assets:Clearing:Costco",
        amount=Decimal("-618.26"),
        currency="HKD",
        tx_type="expense",
        counterpart_ref="COSTCO_ORDER",
        metadata={"wechathk_foreign_amount": "570.80", "wechathk_foreign_currency": "CNY"},
    )
    stats = _run_clearing([terminal, payment])
    assert stats.total_chains == 1
    assert stats.total_linked == 2
    assert terminal.metadata["link"] == payment.metadata["link"]


def test_independent_chains():
    """Two independent chains get different links."""
    t1 = _make_tx(
        source_account="Assets:Clearing:JD",
        tx_type="expense",
        reference_id="A001",
        metadata={},
    )
    p1 = _make_tx(
        source_account="Assets:Clearing:WX:CC:CMB",
        counter_account="Assets:Clearing:JD",
        tx_type="expense",
        counterpart_ref="A001",
        metadata={},
    )
    t2 = _make_tx(
        source_account="Assets:Clearing:ALDI",
        tx_type="expense",
        reference_id="B001",
        metadata={},
    )
    p2 = _make_tx(
        source_account="Assets:Clearing:WX:CC:CMB",
        counter_account="Assets:Clearing:ALDI",
        tx_type="expense",
        counterpart_ref="B001",
        metadata={},
    )
    stats = _run_clearing([t1, p1, t2, p2])
    assert stats.total_chains == 2
    assert stats.total_linked == 4
    assert t1.metadata["link"] == p1.metadata["link"]
    assert t2.metadata["link"] == p2.metadata["link"]
    assert t1.metadata["link"] != t2.metadata["link"]


def test_dfs_stops_at_non_clearing():
    """DFS stops when source is not a clearing account (e.g. Assets:WeChatHK)."""
    terminal = _make_tx(
        source_account="Assets:Clearing:Costco",
        tx_type="expense",
        counterpart_ref="C001",
        metadata={},
    )
    payment = _make_tx(
        source_account="Assets:WeChatHK",  # NOT clearing → DFS stops after linking this
        counter_account="Assets:Clearing:Costco",
        tx_type="expense",
        counterpart_ref="C001",
        metadata={},
    )
    stats = _run_clearing([terminal, payment])
    assert stats.total_linked == 2
    # Payment is linked but DFS doesn't continue past it
    assert terminal.metadata["link"] == payment.metadata["link"]


def test_dfs_stops_no_candidates():
    """DFS stops when there are no upstream candidates."""
    terminal = _make_tx(
        source_account="Assets:Clearing:JD",
        tx_type="expense",
        reference_id="LONELY",
        metadata={},
    )
    stats = _run_clearing([terminal])
    assert stats.total_chains == 1
    assert stats.total_linked == 1
    assert stats.unmatched_terminal == 1


# ─── Beancount validation tests ─────────────────────────────────────


def _init_and_write(tmp_path, transactions):
    """Helper: init ledger, write transactions, return combined bean string."""
    ledger_dir = tmp_path / "ledger"
    init_ledger(ledger_dir)
    write_transactions(transactions, ledger_dir / "importers" / "test.bean")

    parts = []
    for name in ["main.bean", "commodities.bean", "accounts.bean"]:
        parts.append((ledger_dir / name).read_text(encoding="utf-8"))
    parts.append((ledger_dir / "importers" / "test.bean").read_text(encoding="utf-8"))

    combined = "\n".join(parts)
    combined = "\n".join(line for line in combined.splitlines() if not line.startswith("include "))
    return combined


def test_links_in_bean_output(tmp_path):
    """Linked transactions should produce ^clr-NNNNNN in .bean output."""
    terminal = _make_tx(
        source_account="Assets:Clearing:ALDI",
        tx_type="expense",
        reference_id="ALDI999",
        metadata={},
    )
    payment = _make_tx(
        source_account="Assets:Clearing:WX:CC:CMB",
        counter_account="Assets:Clearing:ALDI",
        tx_type="expense",
        counterpart_ref="ALDI999",
        metadata={},
    )
    _run_clearing([terminal, payment])

    combined = _init_and_write(tmp_path, [terminal, payment])
    assert "^clr-000000" in combined
    # Both transactions should have the same link
    assert combined.count("^clr-000000") == 2


def test_beancount_validates_with_links(tmp_path):
    """Ledger with clearing links passes beancount validation."""
    terminal = _make_tx(
        source_account="Assets:Clearing:JD",
        tx_type="expense",
        reference_id="JD_ORD",
        metadata={
            "jd_items": [
                {
                    "name": "蓝牙耳机",
                    "num": 1,
                    "price": "100.00",
                    "category": "Expenses:Shopping:Electronics",
                },
            ],
        },
    )
    bridge = _make_tx(
        source_account="Assets:Clearing:JD:WX",
        counter_account="Assets:Clearing:JD",
        tx_type="expense",
        counterpart_ref="JD_ORD",
        reference_id="JD_TRADE",
        metadata={},
    )
    payment = _make_tx(
        source_account="Assets:Clearing:WX:CC:CMB",
        counter_account="Assets:Clearing:JD:WX",
        tx_type="expense",
        counterpart_ref="JD_TRADE",
        metadata={},
    )
    _run_clearing([terminal, bridge, payment])

    combined = _init_and_write(tmp_path, [terminal, bridge, payment])
    _, errors, _ = load_string(combined)
    assert errors == [], f"Beancount validation errors: {errors}"
    # All three should share the same link
    assert combined.count("^clr-000000") == 3
