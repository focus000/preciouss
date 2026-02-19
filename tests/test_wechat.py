"""Tests for WeChat Pay importer (CSV and XLSX)."""

from decimal import Decimal
from pathlib import Path

import pytest

from preciouss.importers.wechat import WechatImporter, _accept_status

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
        """CSV should extract 7 transactions (1 closed tx is skipped)."""
        importer = WechatImporter()
        txns = importer.extract(FIXTURES / "wechat_sample.csv")
        # 8 data rows, 1 has status "交易关闭" → 7 valid
        assert len(txns) == 7

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
        assert tx0.source_account == "Assets:Clearing:WX:CC:CMB"

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


class TestMerchantClearing:
    """Test that known merchant payees route to clearing accounts."""

    def _make_row(self, payee: str, narration: str = "购物") -> dict[str, str]:
        return {
            "交易时间": "2024-01-15 10:30:00",
            "交易类型": "商户消费",
            "交易对方": payee,
            "商品": narration,
            "收/支": "支出",
            "金额(元)": "¥149.00",
            "支付方式": "招商银行(0913)",
            "当前状态": "支付成功",
            "交易单号": "W001",
            "商户单号": "/",
            "备注": "/",
        }

    def test_jd_payee_routes_to_clearing(self):
        """WeChat seeing '京东' payee -> counter_account = Assets:Clearing:JD:WX."""
        importer = WechatImporter()
        tx = importer._parse_row(self._make_row("京东", "京东购物"))
        assert tx.counter_account == "Assets:Clearing:JD:WX"

    def test_costco_payee_routes_to_clearing(self):
        """WeChat seeing 'Costco' -> counter_account = Assets:Clearing:Costco."""
        importer = WechatImporter()
        tx = importer._parse_row(self._make_row("Costco开市客"))
        assert tx.counter_account == "Assets:Clearing:Costco"

    def test_aldi_payee_routes_to_clearing(self):
        """WeChat seeing 'ALDI奥乐齐' -> counter_account = Assets:Clearing:ALDI."""
        importer = WechatImporter()
        tx = importer._parse_row(self._make_row("ALDI奥乐齐"))
        assert tx.counter_account == "Assets:Clearing:ALDI"

    def test_normal_merchant_no_clearing(self):
        """Normal merchant (星巴克) -> counter_account is None."""
        importer = WechatImporter()
        tx = importer._parse_row(self._make_row("星巴克", "拿铁咖啡"))
        assert tx.counter_account is None


class TestRefundStatus:
    """Test refund-related statuses are accepted and parsed correctly."""

    def _make_row(self, status: str, direction: str = "支出", amount: str = "¥35.00") -> dict:
        return {
            "交易时间": "2024-01-19 10:00:00",
            "交易类型": "商户消费",
            "交易对方": "某商铺",
            "商品": "日用品",
            "收/支": direction,
            "金额(元)": amount,
            "支付方式": "零钱",
            "当前状态": status,
            "交易单号": "W2024011900001",
            "商户单号": "M20240119001",
            "备注": "/",
        }

    def test_status_fully_refunded_accepted(self):
        """'已全额退款' rows should produce a Transaction (not None)."""
        importer = WechatImporter()
        tx = importer._parse_row(self._make_row("已全额退款"))
        assert tx is not None
        assert tx.metadata["wechat_status"] == "已全额退款"

    def test_status_partial_refund_accepted(self):
        """'已退款(￥0.66)' produces a Transaction with wechat_refund_amount metadata."""
        importer = WechatImporter()
        tx = importer._parse_row(self._make_row("已退款(￥0.66)"))
        assert tx is not None
        assert tx.metadata.get("wechat_refund_amount") == "0.66"

    def test_status_refund_credit_accepted(self):
        """'已退款￥7.43' income entry should be accepted (starts with '已退款')."""
        importer = WechatImporter()
        tx = importer._parse_row(self._make_row("已退款￥7.43", direction="收入", amount="¥7.43"))
        assert tx is not None
        assert tx.amount == Decimal("7.43")
        # No parentheses → no refund_amount metadata
        assert "wechat_refund_amount" not in tx.metadata

    def test_accept_status_helper(self):
        assert _accept_status("支付成功")
        assert _accept_status("已全额退款")
        assert _accept_status("已退款(￥5.00)")
        assert _accept_status("已退款￥7.43")
        assert _accept_status("对方已收钱")
        assert _accept_status("对方已退还")
        assert _accept_status("充值成功")
        assert _accept_status("已到账")
        assert not _accept_status("充值完成")   # neutral, not accepted
        assert not _accept_status("交易关闭")
        assert not _accept_status("待付款")

    def test_fixture_includes_refund_rows(self):
        """Fixture now has 7 extracted rows including refund rows."""
        importer = WechatImporter()
        txns = importer.extract(FIXTURES / "wechat_sample.csv")
        statuses = [tx.metadata["wechat_status"] for tx in txns]
        assert "已全额退款" in statuses
        assert any(s.startswith("已退款") for s in statuses)


class TestHeaderValidation:
    """Test header total validation."""

    def test_header_validation_pass(self):
        """Fixture has totals matching extracted transactions → no exception."""
        importer = WechatImporter()
        importer.extract(FIXTURES / "wechat_sample.csv")  # must not raise

    def test_header_validation_fail(self, tmp_path):
        """Wrong income total → ValueError raised."""
        csv_content = (
            "微信支付账单明细\n"
            "微信昵称：[测试用户]\n"
            "起始时间：[2024-01-01 00:00:00] 终止时间：[2024-01-31 23:59:59]\n"
            "导出类型：[全部]\n"
            "导出时间：[2024-02-01 10:00:00]\n"
            "\n"
            "共1笔记录\n"
            "收入：1笔 999.00元\n"
            "支出：0笔 0.00元\n"
            "\n"
            "----------------------微信支付账单明细列表--------------------\n"
            "交易时间,交易类型,交易对方,商品,收/支,金额(元),支付方式,当前状态,交易单号,商户单号,备注\n"
            "2024-01-16 09:00:00,转账,张三,转账,收入,¥200.00,/,已收钱,W2024011600001,/,/\n"
        )
        f = tmp_path / "wechat_wrong_totals.csv"
        f.write_text(csv_content, encoding="utf-8")
        importer = WechatImporter()
        with pytest.raises(ValueError, match="income"):
            importer.extract(f)


class TestAccountName:
    def test_default_account(self):
        importer = WechatImporter()
        assert importer.account_name() == "Assets:WeChat"

    def test_custom_account(self):
        importer = WechatImporter(account="Assets:MyWeChat")
        assert importer.account_name() == "Assets:MyWeChat"
