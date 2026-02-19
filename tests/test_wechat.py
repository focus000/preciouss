"""Tests for WeChat Pay importer (CSV and XLSX)."""

from decimal import Decimal
from pathlib import Path

from preciouss.importers.wechat import WechatImporter

FIXTURES = Path(__file__).parent / "fixtures"


class TestIdentify:
    def test_identify_csv(self):
        importer = WechatImporter()
        assert importer.identify(FIXTURES / "wechat_sample.csv")

    def test_identify_xlsx(self):
        importer = WechatImporter()
        assert importer.identify(FIXTURES / "wechat_sample.xlsx")

    def test_identify_rejects_other_csv(self):
        importer = WechatImporter()
        assert not importer.identify(FIXTURES / "alipay_sample.csv")
        assert not importer.identify(FIXTURES / "cmb_credit_sample.csv")

    def test_identify_rejects_unknown_suffix(self, tmp_path):
        f = tmp_path / "data.txt"
        f.write_text("微信支付账单明细\n", encoding="utf-8")
        importer = WechatImporter()
        assert not importer.identify(f)


class TestExtractCSV:
    def test_extract_csv_count(self):
        """CSV should extract 4 transactions (1 closed tx is skipped)."""
        importer = WechatImporter()
        txns = importer.extract(FIXTURES / "wechat_sample.csv")
        # 5 data rows, 1 has status "交易关闭" → 4 valid
        assert len(txns) == 4

    def test_extract_csv_expense(self):
        importer = WechatImporter()
        txns = importer.extract(FIXTURES / "wechat_sample.csv")
        tx0 = txns[0]
        assert tx0.payee == "星巴克"
        assert tx0.narration == "拿铁咖啡"
        assert tx0.amount == Decimal("-35.00")
        assert tx0.currency == "CNY"
        assert tx0.reference_id == "W2024011500001"
        assert tx0.tx_type == "expense"
        assert tx0.payment_method == "招商银行(0913)"
        assert tx0.source_account == "Liabilities:CreditCard:CMB"

    def test_extract_csv_expense_wallet(self):
        """零钱 payment → Assets:WeChat."""
        importer = WechatImporter()
        txns = importer.extract(FIXTURES / "wechat_sample.csv")
        tx1 = txns[1]
        assert tx1.payee == "美团外卖"
        assert tx1.source_account == "Assets:WeChat"

    def test_extract_csv_income(self):
        importer = WechatImporter()
        txns = importer.extract(FIXTURES / "wechat_sample.csv")
        tx2 = txns[2]
        assert tx2.payee == "张三"
        assert tx2.amount == Decimal("200.00")
        assert tx2.tx_type == "income"
        assert tx2.payment_method is None


class TestExtractXLSX:
    def test_extract_xlsx_count(self):
        """XLSX should extract 4 transactions (all valid)."""
        importer = WechatImporter()
        txns = importer.extract(FIXTURES / "wechat_sample.xlsx")
        assert len(txns) == 4

    def test_extract_xlsx_expense(self):
        importer = WechatImporter()
        txns = importer.extract(FIXTURES / "wechat_sample.xlsx")
        tx0 = txns[0]
        assert tx0.payee == "美团外卖"
        assert tx0.narration == "午餐外卖"
        assert tx0.amount == Decimal("-45.50")
        assert tx0.reference_id == "W2024011500002"
        assert tx0.tx_type == "expense"

    def test_extract_xlsx_income(self):
        importer = WechatImporter()
        txns = importer.extract(FIXTURES / "wechat_sample.xlsx")
        tx3 = txns[3]
        assert tx3.payee == "李四"
        assert tx3.amount == Decimal("500.00")
        assert tx3.tx_type == "income"
        assert tx3.reference_id == "W2024020500001"

    def test_extract_xlsx_fields_match_csv_format(self):
        """Verify that XLSX parsing produces same field types as CSV."""
        importer = WechatImporter()
        txns = importer.extract(FIXTURES / "wechat_sample.xlsx")
        for tx in txns:
            assert isinstance(tx.amount, Decimal)
            assert tx.currency == "CNY"
            assert tx.source_account  # non-empty, may be resolved account
            assert tx.metadata.get("wechat_status") is not None


class TestParseRow:
    def test_parse_row_expense(self):
        importer = WechatImporter()
        row = {
            "交易时间": "2024-01-15 10:30:00",
            "交易类型": "商户消费",
            "交易对方": "星巴克",
            "商品": "拿铁咖啡",
            "收/支": "支出",
            "金额(元)": "¥35.00",
            "支付方式": "招商银行(0913)",
            "当前状态": "支付成功",
            "交易单号": "W2024011500001",
            "商户单号": "M20240115001",
            "备注": "/",
        }
        tx = importer._parse_row(row)
        assert tx is not None
        assert tx.amount == Decimal("-35.00")
        assert tx.tx_type == "expense"

    def test_parse_row_income(self):
        importer = WechatImporter()
        row = {
            "交易时间": "2024-02-05 11:00:00",
            "交易类型": "转账",
            "交易对方": "李四",
            "商品": "转账",
            "收/支": "收入",
            "金额(元)": "¥500.00",
            "支付方式": "/",
            "当前状态": "已收钱",
            "交易单号": "W2024020500001",
            "商户单号": "/",
            "备注": "/",
        }
        tx = importer._parse_row(row)
        assert tx is not None
        assert tx.amount == Decimal("500.00")
        assert tx.tx_type == "income"
        assert tx.payment_method is None

    def test_parse_row_skip_closed_status(self):
        importer = WechatImporter()
        row = {
            "交易时间": "2024-01-17 14:00:00",
            "交易类型": "商户消费",
            "交易对方": "某商铺",
            "商品": "日用品",
            "收/支": "/",
            "金额(元)": "¥88.00",
            "支付方式": "零钱",
            "当前状态": "交易关闭",
            "交易单号": "W2024011700001",
            "商户单号": "/",
            "备注": "/",
        }
        tx = importer._parse_row(row)
        assert tx is None


class TestAccountName:
    def test_default_account(self):
        importer = WechatImporter()
        assert importer.account_name() == "Assets:WeChat"

    def test_custom_account(self):
        importer = WechatImporter(account="Assets:MyWeChat")
        assert importer.account_name() == "Assets:MyWeChat"
