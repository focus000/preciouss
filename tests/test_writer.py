"""Tests for the ledger writer."""

from datetime import datetime
from decimal import Decimal

from preciouss.importers.base import Transaction
from preciouss.ledger.writer import init_ledger, transaction_to_bean, write_transactions


def test_transaction_to_bean():
    """Convert intermediate Transaction to beancount Transaction."""
    tx = Transaction(
        date=datetime(2024, 1, 15, 10, 30),
        amount=Decimal("-35.00"),
        currency="CNY",
        payee="星巴克",
        narration="拿铁咖啡",
        source_account="Assets:Alipay",
        reference_id="2024011500001",
        tx_type="expense",
    )

    bean_tx = transaction_to_bean(tx)

    assert bean_tx.payee == "星巴克"
    assert bean_tx.narration == "拿铁咖啡"
    assert len(bean_tx.postings) == 2
    assert bean_tx.postings[0].account == "Assets:Alipay"
    assert bean_tx.postings[0].units.number == Decimal("-35.00")
    assert bean_tx.postings[1].account == "Expenses:Uncategorized"
    assert bean_tx.postings[1].units.number == Decimal("35.00")
    assert bean_tx.meta["ref"] == "2024011500001"


def test_write_transactions(tmp_path):
    """Write transactions to a .bean file."""
    txns = [
        Transaction(
            date=datetime(2024, 1, 15),
            amount=Decimal("-35.00"),
            currency="CNY",
            payee="星巴克",
            narration="咖啡",
            source_account="Assets:Alipay",
            tx_type="expense",
        ),
        Transaction(
            date=datetime(2024, 1, 16),
            amount=Decimal("200.00"),
            currency="CNY",
            payee="张三",
            narration="转账",
            source_account="Assets:Alipay",
            tx_type="income",
        ),
    ]

    output = tmp_path / "test.bean"
    write_transactions(txns, output)

    assert output.exists()
    content = output.read_text(encoding="utf-8")
    assert "星巴克" in content
    assert "张三" in content
    assert "-35.00 CNY" in content
    assert "200.00 CNY" in content


def test_init_ledger(tmp_path):
    """Initialize a new ledger directory."""
    ledger_dir = tmp_path / "ledger"
    init_ledger(ledger_dir)

    assert (ledger_dir / "main.bean").exists()
    assert (ledger_dir / "accounts.bean").exists()
    assert (ledger_dir / "commodities.bean").exists()
    assert (ledger_dir / "importers").is_dir()
    assert (ledger_dir / "prices").is_dir()

    main_content = (ledger_dir / "main.bean").read_text()
    assert 'option "operating_currency" "CNY"' in main_content
    assert "include" in main_content


def test_init_ledger_idempotent(tmp_path):
    """Initializing twice doesn't overwrite existing files."""
    ledger_dir = tmp_path / "ledger"
    init_ledger(ledger_dir)

    # Modify main.bean
    main_path = ledger_dir / "main.bean"
    original_content = main_path.read_text()
    main_path.write_text(original_content + "\n; custom line\n")

    # Re-init should not overwrite
    init_ledger(ledger_dir)
    assert "; custom line" in main_path.read_text()
