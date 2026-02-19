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
    assert tx0.source_account == "Assets:Clearing:Alipay:Unknown"

    # Check second transaction (expense with payment method resolved)
    tx1 = txns[1]
    assert tx1.payee == "美团外卖"
    assert tx1.amount == Decimal("-45.50")
    assert tx1.payment_method == "招商银行信用卡(尾号1234)"
    assert tx1.source_account == "Assets:Clearing:Alipay:CC:CMB"

    # Check third transaction (income, 资金状态="已收入" → fallback)
    tx2 = txns[2]
    assert tx2.payee == "张三"
    assert tx2.amount == Decimal("200.00")
    assert tx2.tx_type == "income"
    assert tx2.source_account == "Assets:Clearing:Alipay:Unknown"


def test_account_name():
    importer = AlipayImporter(account="Assets:MyAlipay")
    assert importer.account_name() == "Assets:MyAlipay"


class TestMerchantClearing:
    """Test that known merchant payees route to clearing accounts."""

    def _make_row(self, payee: str, narration: str = "购物") -> dict[str, str]:
        return {
            "交易号": "2024011500099",
            "商家订单号": "M001",
            "交易创建时间": "2024-01-15 10:30:00",
            "付款时间": "2024-01-15 10:30:00",
            "最近修改时间": "2024-01-15 10:30:00",
            "交易来源地": "",
            "类型": "商户消费",
            "交易对方": payee,
            "商品名称": narration,
            "金额（元）": "149.00",
            "收/支": "支出",
            "交易状态": "交易成功",
            "服务费（元）": "0",
            "成功退款（元）": "0",
            "备注": "",
            "资金状态": "招商银行信用卡(尾号1234)",
        }

    def test_jd_payee_routes_to_clearing(self):
        """Alipay seeing '京东' -> counter_account = Assets:Clearing:JD:Alipay."""
        importer = AlipayImporter()
        tx = importer._parse_row(self._make_row("京东", "京东购物"))
        assert tx.counter_account == "Assets:Clearing:JD:Alipay"

    def test_costco_payee_routes_to_clearing(self):
        """Alipay seeing 'Costco' -> counter_account = Assets:Clearing:Costco."""
        importer = AlipayImporter()
        tx = importer._parse_row(self._make_row("Costco开市客"))
        assert tx.counter_account == "Assets:Clearing:Costco"
