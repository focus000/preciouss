"""Tests for CMB (招商银行) importers."""

from decimal import Decimal
from pathlib import Path

from preciouss.importers.cmb import CmbCreditImporter, CmbDebitImporter

FIXTURES = Path(__file__).parent / "fixtures"


def test_identify_cmb_credit():
    """CmbCreditImporter identifies CMB credit card CSV."""
    importer = CmbCreditImporter()
    assert importer.identify(FIXTURES / "cmb_credit_sample.csv")
    assert not importer.identify(FIXTURES / "alipay_sample.csv")


def test_identify_cmb_debit():
    """CmbDebitImporter identifies CMB debit card CSV."""
    importer = CmbDebitImporter()
    assert importer.identify(FIXTURES / "cmb_debit_sample.csv")
    assert not importer.identify(FIXTURES / "alipay_sample.csv")


def test_extract_cmb_credit():
    """CmbCreditImporter extracts credit card transactions."""
    importer = CmbCreditImporter()
    txns = importer.extract(FIXTURES / "cmb_credit_sample.csv")

    assert len(txns) == 4

    # First transaction: expense
    tx0 = txns[0]
    assert "支付宝" in tx0.payee or "星巴克" in tx0.payee
    assert tx0.amount == Decimal("-35.00")  # Negated for credit card
    assert tx0.currency == "CNY"
    assert tx0.source_account == "Liabilities:CreditCard:CMB"

    # Refund transaction
    tx3 = txns[3]
    assert tx3.amount == Decimal("299.00")  # Refund is positive (reduces liability)


def test_extract_cmb_debit():
    """CmbDebitImporter extracts debit card transactions."""
    importer = CmbDebitImporter()
    txns = importer.extract(FIXTURES / "cmb_debit_sample.csv")

    assert len(txns) == 3

    # Income: salary
    tx0 = txns[0]
    assert tx0.amount == Decimal("15000.00")
    assert tx0.tx_type == "income"

    # Expense: withdrawal
    tx1 = txns[1]
    assert tx1.amount == Decimal("-2000.00")
    assert tx1.tx_type == "expense"
