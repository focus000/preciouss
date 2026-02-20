"""Tests for CITIC (中信银行) credit card PDF importer."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock, patch

from preciouss.importers.citic import CiticCreditPdfImporter

# ---------------------------------------------------------------------------
# Sample data (mirrors a real billing cycle page)
# ---------------------------------------------------------------------------

# The real CITIC PDF page text has the billing date on its own line and the
# 本期新增金额 embedded in the CNY card balance summary row format:
#   "CNY {上期应还款额} {上期已还款额} {本期新增金额} {账户账单金额} {最低还款额}"
# The transaction table header also contains "银行记账日" (used for identification).
SAMPLE_PAGES = [
    {
        "text": (
            "账单日\n2026-01-08\nStatement Date\n"
            "卡号 上期应还款额 - 上期已还款额 + 本期新增金额 = 账户账单金额 最低还款额\n"
            "CNY 0.00 0.00 106.19 1119.40 55.97\n"
            "交易日 银行记账日 卡号后四位 交易描述 交易货币/金额 记账货币/金额\n"
        ),
        "table": [
            ["交易日", "银行记账日", "卡号后四位", "交易描述", "交易货币/金额", "记账货币/金额"],
            ["20251209", "20251209", "4709", "财付通－美团平台商户", "CNY 106.19", "CNY 106.19"],
            ["20251229", "20251229", "4709", "财付通还款", "CNY -47.00", "CNY -47.00"],
        ],
    }
]


# ---------------------------------------------------------------------------
# _parse_row tests
# ---------------------------------------------------------------------------


def test_parse_expense_row():
    """Positive amount → expense, negated."""
    row = ["20251209", "20251209", "4709", "财付通－美团平台商户", "CNY 106.19", "CNY 106.19"]
    tx = CiticCreditPdfImporter._parse_row(row, "Liabilities:CreditCard:CITIC", "CNY", None)
    assert tx is not None
    assert tx.amount == Decimal("-106.19")
    assert tx.tx_type == "expense"
    assert tx.payee == "财付通－美团平台商户"
    assert tx.source_account == "Liabilities:CreditCard:CITIC"
    assert tx.counter_account is None


def test_parse_repayment_row():
    """Negative amount in PDF → income (repayment), positive amount."""
    row = ["20251229", "20251229", "4709", "财付通还款", "CNY -47.00", "CNY -47.00"]
    tx = CiticCreditPdfImporter._parse_row(row, "Liabilities:CreditCard:CITIC", "CNY", None)
    assert tx is not None
    assert tx.amount == Decimal("47.00")
    assert tx.tx_type == "income"


def test_parse_row_skips_header():
    """Header row (first cell == '交易日') is skipped."""
    row = ["交易日", "银行记账日", "卡号后四位", "交易描述", "交易货币/金额", "记账货币/金额"]
    result = CiticCreditPdfImporter._parse_row(row, "Liabilities:CreditCard:CITIC", "CNY", None)
    assert result is None


def test_parse_row_skips_empty():
    """Rows with no date value are skipped."""
    row = ["", "", "", "", "", ""]
    result = CiticCreditPdfImporter._parse_row(row, "Liabilities:CreditCard:CITIC", "CNY", None)
    assert result is None


def test_parse_row_too_short():
    """Rows shorter than 5 cells are skipped."""
    result = CiticCreditPdfImporter._parse_row(["20251209", "20251209"], "Acct", "CNY", None)
    assert result is None


def test_parse_row_metadata():
    """card_last4, post_date, and statement_date are stored in metadata."""
    from datetime import date

    stmt = date(2026, 1, 8)
    row = ["20251209", "20251210", "4709", "Some merchant", "CNY 50.00", "CNY 50.00"]
    tx = CiticCreditPdfImporter._parse_row(row, "Liabilities:CreditCard:CITIC", "CNY", stmt)
    assert tx is not None
    assert tx.metadata["card_last4"] == "4709"
    assert tx.metadata["post_date"] == "2025-12-10"
    assert tx.metadata["statement_date"] == "2026-01-08"


# ---------------------------------------------------------------------------
# _parse tests
# ---------------------------------------------------------------------------


def test_parse_returns_transactions():
    """_parse() produces the expected transactions from sample pages."""
    txns = CiticCreditPdfImporter._parse(
        SAMPLE_PAGES, "Liabilities:CreditCard:CITIC", "CNY"
    )
    assert len(txns) == 2
    assert txns[0].amount == Decimal("-106.19")
    assert txns[1].amount == Decimal("47.00")


def test_cycle_total_validation_passes(caplog):
    """No warning logged when cycle total matches 本期新增金额."""
    import logging

    with caplog.at_level(logging.WARNING, logger="preciouss.importers.citic"):
        CiticCreditPdfImporter._parse(SAMPLE_PAGES, "Liabilities:CreditCard:CITIC", "CNY")

    # 106.19 ≈ 106.19: no mismatch warning
    assert "mismatch" not in caplog.text.lower()


def test_cycle_total_validation_warns(caplog):
    """Warning logged when cycle total differs from 本期新增金额 by > 1.00."""
    import logging

    pages = [
        {
            "text": (
                "账单日\n2026-01-08\nStatement Date\n"
                "卡号 上期应还款额 - 上期已还款额 + 本期新增金额 = 账户账单金额 最低还款额\n"
                # Claims 500.00 new charges (group 3) but table only has 106.19
                "CNY 0.00 0.00 500.00 500.00 50.00\n"
                "交易日 银行记账日 卡号后四位 交易描述 交易货币/金额 记账货币/金额\n"
            ),
            "table": [
                ["交易日", "银行记账日", "卡号后四位", "交易描述", "交易货币/金额", "记账货币/金额"],  # noqa: E501
                ["20251209", "20251209", "4709", "商户A", "CNY 106.19", "CNY 106.19"],
            ],
        }
    ]
    with caplog.at_level(logging.WARNING, logger="preciouss.importers.citic"):
        CiticCreditPdfImporter._parse(pages, "Liabilities:CreditCard:CITIC", "CNY")

    assert "mismatch" in caplog.text.lower()


# ---------------------------------------------------------------------------
# _extract_new_charge tests
# ---------------------------------------------------------------------------


def test_extract_new_charge_found():
    # Real format: CNY balance row has 5 values; 本期新增金额 is the 3rd
    text = (
        "卡号 上期应还款额 - 上期已还款额 + 本期新增金额 = 账户账单金额 最低还款额\n"
        "CNY 0.00 0.00 106.19 1119.40 55.97\n"
    )
    result = CiticCreditPdfImporter._extract_new_charge(text)
    assert result == Decimal("106.19")


def test_extract_new_charge_missing():
    result = CiticCreditPdfImporter._extract_new_charge("some other text")
    assert result is None


# ---------------------------------------------------------------------------
# identify() tests (mock pdfplumber.open)
# ---------------------------------------------------------------------------


def _make_mock_pdf(text: str):
    """Build a mock pdfplumber PDF context manager with given page text."""
    mock_page = MagicMock()
    mock_page.extract_text.return_value = text
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value.pages = [mock_page]
    return mock_ctx


def test_identify_citic(tmp_path):
    """identify() returns True for CITIC credit card PDF."""
    pdf_path = tmp_path / "citic.pdf"
    pdf_path.touch()

    mock_pdf = _make_mock_pdf("账单日\n2026-01-08\n交易日 银行记账日 卡号后四位 交易描述")
    with patch("pdfplumber.open", return_value=mock_pdf):
        importer = CiticCreditPdfImporter()
        assert importer.identify(pdf_path)


def test_identify_rejects_cmb_pdf(tmp_path):
    """identify() returns False for CMB debit PDF (different keywords)."""
    pdf_path = tmp_path / "cmb.pdf"
    pdf_path.touch()

    mock_pdf = _make_mock_pdf("招商银行交易流水 联机余额 2020-01-01")
    with patch("pdfplumber.open", return_value=mock_pdf):
        importer = CiticCreditPdfImporter()
        assert not importer.identify(pdf_path)


def test_identify_rejects_non_pdf(tmp_path):
    """identify() returns False for non-PDF files."""
    csv_path = tmp_path / "data.csv"
    csv_path.touch()
    importer = CiticCreditPdfImporter()
    assert not importer.identify(csv_path)


def test_identify_rejects_wrong_bank(tmp_path):
    """identify() returns False when bank name doesn't match."""
    pdf_path = tmp_path / "other.pdf"
    pdf_path.touch()

    mock_pdf = _make_mock_pdf("招商银行 信用卡账单 2026-01-08")
    with patch("pdfplumber.open", return_value=mock_pdf):
        importer = CiticCreditPdfImporter()
        assert not importer.identify(pdf_path)
