"""China Merchants Bank (招商银行) CSV importer.

Supports both credit card and debit card CSV exports.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation

from preciouss.importers.base import CsvImporter, Transaction


class CmbCreditImporter(CsvImporter):
    """Import transactions from CMB credit card CSV exports.

    CMB credit card CSV format:
    - 交易日, 记账日, 交易摘要, 人民币金额, 卡号后四位, ...

    Or newer format:
    - 交易日期, 记账日期, 交易描述, 交易金额, ...
    """

    skip_lines = 1  # Skip title line "招商银行信用卡交易明细"
    expected_headers = ["交易日"]

    def __init__(
        self,
        account: str = "Liabilities:CreditCard:CMB",
        currency: str = "CNY",
        card_suffix: str | None = None,
    ):
        self._account = account
        self._currency = currency
        self._card_suffix = card_suffix  # e.g. "1234"

    def account_name(self) -> str:
        return self._account

    def identify(self, filepath) -> bool:
        """CMB credit card CSVs contain '交易日' and credit card related headers."""
        from pathlib import Path

        filepath = Path(filepath)
        if filepath.suffix.lower() != ".csv":
            return False
        try:
            content = self._read_file(filepath)
            first_lines = content[:500]
            has_trade_date = "交易日" in first_lines
            has_cmb_marker = "招商银行" in first_lines or "记账日" in first_lines
            return has_trade_date and has_cmb_marker
        except Exception:
            return False

    def _parse_row(self, row: dict[str, str]) -> Transaction | None:
        """Parse a single CMB credit card CSV row."""
        # Try different date column names
        date_str = (row.get("交易日", "") or row.get("交易日期", "")).strip()
        if not date_str:
            return None

        # Parse date
        for fmt in ("%Y%m%d", "%Y-%m-%d", "%Y/%m/%d"):
            try:
                date = datetime.strptime(date_str, fmt)
                break
            except ValueError:
                continue
        else:
            return None

        # Parse amount - credit card amounts: positive = expense, negative = refund/payment
        amount_str = (
            row.get("人民币金额", "") or row.get("交易金额", "") or row.get("金额", "")
        ).strip()
        # Remove currency symbols and commas
        amount_str = amount_str.replace("¥", "").replace(",", "").replace("￥", "").strip()
        try:
            amount = Decimal(amount_str)
        except (InvalidOperation, ValueError):
            return None

        # For credit cards, positive amount = you spent money (liability increases)
        # We negate because from the account perspective, spending decreases the balance
        tx_type = "expense" if amount > 0 else "income"

        narration = (
            row.get("交易摘要", "") or row.get("交易描述", "") or row.get("摘要", "")
        ).strip()

        # Try to extract payee from narration
        payee = narration

        # Card suffix for matching
        card_no = row.get("卡号后四位", row.get("卡号", "")).strip()

        return Transaction(
            date=date,
            amount=-amount,  # Negate: expense on credit card = negative posting
            currency=self._currency,
            payee=payee,
            narration=narration,
            source_account=self._account,
            tx_type=tx_type,
            metadata={
                "card_suffix": card_no or self._card_suffix or "",
                "posting_date": row.get("记账日", row.get("记账日期", "")).strip(),
            },
        )


class CmbDebitImporter(CsvImporter):
    """Import transactions from CMB debit card (储蓄卡) CSV exports.

    CMB debit card CSV format:
    - 交易日期, 摘要, 交易金额, 余额, ...
    """

    expected_headers = ["交易日期"]

    def __init__(
        self,
        account: str = "Assets:Bank:CMB",
        currency: str = "CNY",
    ):
        self._account = account
        self._currency = currency

    def account_name(self) -> str:
        return self._account

    def identify(self, filepath) -> bool:
        from pathlib import Path

        filepath = Path(filepath)
        if filepath.suffix.lower() != ".csv":
            return False
        try:
            content = self._read_file(filepath)
            first_lines = content[:500]
            # Debit card has 余额 (balance) column, credit card doesn't
            return "交易日期" in first_lines and "余额" in first_lines
        except Exception:
            return False

    def _parse_row(self, row: dict[str, str]) -> Transaction | None:
        date_str = row.get("交易日期", "").strip()
        if not date_str:
            return None

        for fmt in ("%Y%m%d", "%Y-%m-%d", "%Y/%m/%d"):
            try:
                date = datetime.strptime(date_str, fmt)
                break
            except ValueError:
                continue
        else:
            return None

        amount_str = row.get("交易金额", row.get("金额", "")).strip()
        amount_str = amount_str.replace(",", "").replace("¥", "").replace("￥", "").strip()
        try:
            amount = Decimal(amount_str)
        except (InvalidOperation, ValueError):
            return None

        tx_type = "income" if amount > 0 else "expense"
        narration = row.get("摘要", row.get("交易摘要", "")).strip()

        return Transaction(
            date=date,
            amount=amount,
            currency=self._currency,
            payee=narration,
            narration=narration,
            source_account=self._account,
            tx_type=tx_type,
            metadata={
                "balance": row.get("余额", "").strip(),
            },
        )
