"""Tests for CMB (招商银行) importers."""

from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

from preciouss.importers.cmb import CmbCreditImporter, CmbDebitImporter, CmbDebitPdfImporter

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


# ---------------------------------------------------------------------------
# CmbDebitPdfImporter tests
# ---------------------------------------------------------------------------

SAMPLE_ROWS = [
    ["记账日期", "货币", "交易金额", "联机余额", "交易摘要", "对手信息", "客户摘要"],  # header
    ["2020-01-26", "CNY", "1,000.00", "1,000.41", "银联渠道转入", "李蕴方", "银联卡转入"],
    ["2020-01-26", "CNY", "-452.78", "547.63", "快捷支付", "", "支付宝-还款"],
]


class TestCmbDebitPdf:
    def test_parse_income_row(self):
        result = CmbDebitPdfImporter._parse_row(
            SAMPLE_ROWS[1], "Assets:Bank:CMB", "CNY"
        )
        assert result is not None
        tx, balance = result
        assert tx.amount == Decimal("1000.00")
        assert tx.tx_type == "income"
        assert tx.payee == "李蕴方"
        assert tx.source_account == "Assets:Bank:CMB"
        assert tx.counter_account is None
        assert balance == Decimal("1000.41")

    def test_parse_expense_row(self):
        result = CmbDebitPdfImporter._parse_row(
            SAMPLE_ROWS[2], "Assets:Bank:CMB", "CNY"
        )
        assert result is not None
        tx, balance = result
        assert tx.amount == Decimal("-452.78")
        assert tx.tx_type == "expense"
        assert balance == Decimal("547.63")

    def test_parse_skips_header(self):
        result = CmbDebitPdfImporter._parse_row(SAMPLE_ROWS[0], "Assets:Bank:CMB", "CNY")
        assert result is None

    def test_parse_narration_combined(self):
        """交易摘要 and 客户摘要 are combined when different."""
        result = CmbDebitPdfImporter._parse_row(
            SAMPLE_ROWS[2], "Assets:Bank:CMB", "CNY"
        )
        assert result is not None
        tx, _ = result
        assert "快捷支付" in tx.narration
        assert "支付宝-还款" in tx.narration

    def test_balance_validation_pass(self, caplog):
        """No warning when balances are sequentially consistent."""
        import logging

        # Row 1 sets prev_balance = 1000.41; Row 2: 1000.41 + (-452.78) = 547.63 ✓
        with caplog.at_level(logging.WARNING, logger="preciouss.importers.cmb"):
            txns = CmbDebitPdfImporter._parse(SAMPLE_ROWS, "Assets:Bank:CMB", "CNY")

        assert len(txns) == 2
        assert "mismatch" not in caplog.text.lower()

    def test_balance_validation_fail(self, caplog):
        """Warning logged when balance jumps unexpectedly for same-currency rows."""
        import logging

        rows = [
            ["2020-01-26", "CNY", "1,000.00", "1,000.41", "转入", "来源", "转入"],
            # Correct expected balance would be 1000.41 + (-100) = 900.41, but we put 999.99
            ["2020-01-27", "CNY", "-100.00", "999.99", "支出", "", "支出"],
        ]
        with caplog.at_level(logging.WARNING, logger="preciouss.importers.cmb"):
            CmbDebitPdfImporter._parse(rows, "Assets:Bank:CMB", "CNY")

        assert "mismatch" in caplog.text.lower()

    def test_balance_validation_skips_cross_currency(self, caplog):
        """No warning when consecutive rows are different currencies (multi-currency account)."""
        import logging

        rows = [
            ["2022-04-26", "CNY", "70.40", "49,222.66", "快捷支付", "支付宝", ""],
            # JPY transaction — balance is in JPY, not comparable to CNY balance
            ["2022-04-26", "JPY", "600,000.00", "600,000.00", "结售汇即时售汇", "李蕴方", ""],
            ["2022-04-26", "CNY", "-30,849.60", "18,373.06", "结售汇即时售汇", "李蕴方", ""],
        ]
        with caplog.at_level(logging.WARNING, logger="preciouss.importers.cmb"):
            txns = CmbDebitPdfImporter._parse(rows, "Assets:Bank:CMB", "CNY")

        assert len(txns) == 3
        assert "mismatch" not in caplog.text.lower()

    def test_identify_cmb_debit_pdf(self, tmp_path):
        pdf_path = tmp_path / "cmb_debit.pdf"
        pdf_path.touch()

        mock_page = MagicMock()
        mock_page.extract_text.return_value = "招商银行交易流水 联机余额 记账日期"
        mock_ctx = MagicMock()
        mock_ctx.__enter__.return_value.pages = [mock_page]

        with patch("pdfplumber.open", return_value=mock_ctx):
            importer = CmbDebitPdfImporter()
            assert importer.identify(pdf_path)

    def test_identify_rejects_citic_pdf(self, tmp_path):
        pdf_path = tmp_path / "citic.pdf"
        pdf_path.touch()

        mock_page = MagicMock()
        mock_page.extract_text.return_value = "中信银行 信用卡账单 2026-01-08"
        mock_ctx = MagicMock()
        mock_ctx.__enter__.return_value.pages = [mock_page]

        with patch("pdfplumber.open", return_value=mock_ctx):
            importer = CmbDebitPdfImporter()
            assert not importer.identify(pdf_path)

    def test_identify_rejects_non_pdf(self, tmp_path):
        csv_path = tmp_path / "data.csv"
        csv_path.touch()
        importer = CmbDebitPdfImporter()
        assert not importer.identify(csv_path)

    def test_parse_totals_found(self):
        text = (
            "合并统计 合并收入(+) 合并支出(-)\n币种\n"
            "JPY 640,000.00 -640,000.00\n"
            "CNY 2,183,210.75 -2,123,020.01\n"
        )
        result = CmbDebitPdfImporter._parse_totals(text)
        assert result == {
            "JPY": (Decimal("640000.00"), Decimal("640000.00")),
            "CNY": (Decimal("2183210.75"), Decimal("2123020.01")),
        }

    def test_parse_totals_missing(self):
        assert CmbDebitPdfImporter._parse_totals("some other text") is None

    def test_totals_validation_passes(self, caplog):
        """No warning when computed sums match stated totals."""
        import logging

        # SAMPLE_ROWS: income=1000.00, expense=452.78
        totals = {"CNY": (Decimal("1000.00"), Decimal("452.78"))}
        with caplog.at_level(logging.WARNING, logger="preciouss.importers.cmb"):
            CmbDebitPdfImporter._parse(SAMPLE_ROWS, "Assets:Bank:CMB", "CNY", totals)

        assert "mismatch" not in caplog.text.lower()

    def test_totals_validation_warns(self, caplog):
        """Warning logged when computed income doesn't match stated totals."""
        import logging

        totals = {"CNY": (Decimal("9999.00"), Decimal("452.78"))}
        with caplog.at_level(logging.WARNING, logger="preciouss.importers.cmb"):
            CmbDebitPdfImporter._parse(SAMPLE_ROWS, "Assets:Bank:CMB", "CNY", totals)

        assert "mismatch" in caplog.text.lower()
