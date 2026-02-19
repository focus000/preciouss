"""Tests for Alipay importer."""

from decimal import Decimal
from pathlib import Path

from preciouss.importers.alipay import AlipayImporter

FIXTURES = Path(__file__).parent / "fixtures"


def test_identify_alipay_csv():
    """AlipayImporter identifies Alipay CSV files."""
    importer = AlipayImporter()
    assert importer.identify(FIXTURES / "alipay_sample.csv")
    assert not importer.identify(FIXTURES / "cmb_credit_sample.csv")


def test_extract_alipay_transactions():
    """AlipayImporter extracts transactions from CSV."""
    importer = AlipayImporter()
    txns = importer.extract(FIXTURES / "alipay_sample.csv")

    # Should skip closed transactions (交易关闭)
    assert len(txns) == 3

    # Check first transaction (expense, 资金状态="已支出" → fallback)
    tx0 = txns[0]
    assert tx0.payee == "星巴克"
    assert tx0.narration == "拿铁咖啡"
    assert tx0.amount == Decimal("-35.00")
    assert tx0.currency == "CNY"
    assert tx0.reference_id == "2024011500001"
    assert tx0.tx_type == "expense"
    assert tx0.source_account == "Assets:Alipay:Unknown"

    # Check second transaction (expense with payment method resolved)
    tx1 = txns[1]
    assert tx1.payee == "美团外卖"
    assert tx1.amount == Decimal("-45.50")
    assert tx1.payment_method == "招商银行信用卡(尾号1234)"
    assert tx1.source_account == "Liabilities:CreditCard:CMB"

    # Check third transaction (income, 资金状态="已收入" → fallback)
    tx2 = txns[2]
    assert tx2.payee == "张三"
    assert tx2.amount == Decimal("200.00")
    assert tx2.tx_type == "income"
    assert tx2.source_account == "Assets:Alipay:Unknown"


def test_account_name():
    importer = AlipayImporter(account="Assets:MyAlipay")
    assert importer.account_name() == "Assets:MyAlipay"
