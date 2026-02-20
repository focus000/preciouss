"""China Merchants Bank (招商银行) importers.

Supports credit card CSV, debit card CSV, and debit card PDF exports.
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from preciouss.importers.base import CsvImporter, PrecioussImporter, Transaction

# CMB debit PDF column x-boundaries (measured from actual PDFs)
# Columns: 记账日期 | 货币 | 交易金额 | 联机余额 | 交易摘要 | 对手信息 | 客户摘要
_CMB_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_CMB_COLS = [
    ("date",      0,    85),
    ("currency",  85,   130),
    ("amount",    130,  212),
    ("balance",   212,  290),
    ("narration", 290,  372),
    ("counter",   372,  478),
    ("note",      478,  9999),
]
_CMB_OVERFLOW_THRESHOLD = 15  # max pt distance for overflow → nearest date row

# Matches one currency row in 合并统计 section: "CNY 2,183,210.75 -2,123,020.01"
_CMB_TOTALS_RE = re.compile(r"([A-Z]{3})\s+([\d,]+\.\d{2})\s+-([\d,]+\.\d{2})")


def _cmb_col_of(x0: float) -> str | None:
    for name, lo, hi in _CMB_COLS:
        if lo <= x0 < hi:
            return name
    return None

logger = logging.getLogger(__name__)


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


class CmbDebitPdfImporter(PrecioussImporter):
    """Import transactions from CMB debit card (储蓄卡) PDF statement exports.

    CMB debit PDF columns (7):
      记账日期 | 货币 | 交易金额 | 联机余额 | 交易摘要 | 对手信息 | 客户摘要

    The 联机余额 column provides a running balance used for sequential validation.
    """

    def __init__(
        self,
        account: str = "Assets:Bank:CMB",
        currency: str = "CNY",
    ):
        self._account = account
        self._currency = currency

    def account_name(self) -> str:
        return self._account

    def identify(self, filepath: str | Path) -> bool:
        filepath = Path(filepath)
        if filepath.suffix.lower() != ".pdf":
            return False
        try:
            import pdfplumber

            with pdfplumber.open(filepath) as pdf:
                if not pdf.pages:
                    return False
                text = pdf.pages[0].extract_text() or ""
            return "招商银行交易流水" in text and "联机余额" in text
        except Exception:
            return False

    def extract(self, filepath: str | Path) -> list[Transaction]:
        rows = self._read_pdf(filepath)
        totals = self._read_totals(filepath)
        return self._parse(rows, self._account, self._currency, totals)

    @staticmethod
    def _parse_totals(text: str) -> dict[str, tuple[Decimal, Decimal]] | None:
        """Parse 合并统计 section. Returns {ccy: (income, expense)} or None if absent."""
        if "合并统计" not in text:
            return None
        result = {}
        for m in _CMB_TOTALS_RE.finditer(text):
            ccy = m.group(1)
            income = Decimal(m.group(2).replace(",", ""))
            expense = Decimal(m.group(3).replace(",", ""))
            result[ccy] = (income, expense)
        return result or None

    @staticmethod
    def _read_totals(filepath: str | Path) -> dict[str, tuple[Decimal, Decimal]] | None:
        """Read 合并统计 totals from the last page of the PDF."""
        import pdfplumber

        try:
            with pdfplumber.open(filepath) as pdf:
                if not pdf.pages:
                    return None
                text = pdf.pages[-1].extract_text() or ""
            return CmbDebitPdfImporter._parse_totals(text)
        except Exception:
            return None

    @staticmethod
    def _read_pdf(filepath: str | Path) -> list[list[str | None]]:
        """Extract all table rows from all PDF pages using coordinate-based word parsing.

        The CMB debit PDF has no visible table borders, so pdfplumber's
        extract_table() returns None.  Words are grouped by Y position into
        rows and assigned to columns by X position.

        Counterparty and customer-note fields can wrap to adjacent lines.
        Overflow fragments are joined (without separator) to their nearest
        date row, handling both pre- and post-date overflow positions.
        """
        import pdfplumber

        all_rows: list[list[str | None]] = []

        with pdfplumber.open(filepath) as pdf:
            for page in pdf.pages:
                words = page.extract_words()

                # Group words by approximate row (round top to nearest 4 pts)
                row_groups: dict = defaultdict(lambda: defaultdict(list))
                for w in words:
                    key = round(w["top"] / 4) * 4
                    col = _cmb_col_of(w["x0"])
                    if col:
                        row_groups[key][col].append(w["text"])

                sorted_keys = sorted(row_groups.keys())

                # Identify date rows vs overflow rows
                date_row_keys = [
                    k for k in sorted_keys
                    if any(_CMB_DATE_RE.match(t) for t in row_groups[k].get("date", []))
                ]
                if not date_row_keys:
                    continue

                # For counter/note fields, collect (top, text) fragments per date row
                counter_parts: dict[int, list[tuple[int, str]]] = {
                    k: [(k, " ".join(row_groups[k].get("counter", [])))]
                    for k in date_row_keys
                }
                note_parts: dict[int, list[tuple[int, str]]] = {
                    k: [(k, " ".join(row_groups[k].get("note", [])))]
                    for k in date_row_keys
                }

                # Assign overflow rows to nearest date row within threshold
                for key in sorted_keys:
                    row = row_groups[key]
                    if any(_CMB_DATE_RE.match(t) for t in row.get("date", [])):
                        continue
                    if "counter" not in row and "note" not in row:
                        continue
                    nearest = min(date_row_keys, key=lambda dk: abs(dk - key))
                    if abs(nearest - key) > _CMB_OVERFLOW_THRESHOLD:
                        continue
                    if "counter" in row:
                        counter_parts[nearest].append((key, " ".join(row["counter"])))
                    if "note" in row:
                        note_parts[nearest].append((key, " ".join(row["note"])))

                # Build output rows
                for k in date_row_keys:
                    row = row_groups[k]
                    counter = "".join(
                        text for _, text in sorted(counter_parts[k], key=lambda x: x[0])
                    )
                    note = "".join(
                        text for _, text in sorted(note_parts[k], key=lambda x: x[0])
                    )
                    all_rows.append([
                        " ".join(row.get("date", [])),
                        " ".join(row.get("currency", [])),
                        " ".join(row.get("amount", [])),
                        " ".join(row.get("balance", [])),
                        " ".join(row.get("narration", [])),
                        counter,
                        note,
                    ])

        return all_rows

    @classmethod
    def _parse(
        cls,
        rows: list[list[str | None]],
        account: str,
        currency: str,
        totals: dict[str, tuple[Decimal, Decimal]] | None = None,
    ) -> list[Transaction]:
        """Parse all table rows into transactions with per-currency balance validation.

        The CMB 全币种 (all-currency) account holds separate balances per currency.
        The 联机余额 column shows the balance in the transaction's own currency,
        so sequential validation is only meaningful between consecutive same-currency rows.
        """
        transactions: list[Transaction] = []
        # Track last-seen balance per currency code
        prev_balance_by_ccy: dict[str, Decimal] = {}

        for row in rows:
            result = cls._parse_row(row, account, currency)
            if result is None:
                continue
            tx, balance = result

            ccy = tx.currency
            if ccy in prev_balance_by_ccy:
                expected = prev_balance_by_ccy[ccy] + tx.amount
                if abs(expected - balance) > Decimal("0.01"):
                    logger.warning(
                        "CMB debit PDF balance mismatch at %s (%s): "
                        "prev=%.2f + amount=%.2f = expected=%.2f, got=%.2f",
                        tx.date.strftime("%Y-%m-%d"),
                        ccy,
                        prev_balance_by_ccy[ccy],
                        tx.amount,
                        expected,
                        balance,
                    )

            prev_balance_by_ccy[ccy] = balance
            transactions.append(tx)

        # Validate against 合并统计 totals
        if totals:
            for ccy, (expected_income, expected_expense) in totals.items():
                actual_income = sum(
                    tx.amount for tx in transactions if tx.currency == ccy and tx.amount > 0
                )
                actual_expense = sum(
                    -tx.amount for tx in transactions if tx.currency == ccy and tx.amount < 0
                )
                if abs(actual_income - expected_income) > Decimal("1.00"):
                    logger.warning(
                        "CMB totals mismatch (%s) income: computed=%.2f, stated=%.2f",
                        ccy,
                        actual_income,
                        expected_income,
                    )
                if abs(actual_expense - expected_expense) > Decimal("1.00"):
                    logger.warning(
                        "CMB totals mismatch (%s) expense: computed=%.2f, stated=%.2f",
                        ccy,
                        actual_expense,
                        expected_expense,
                    )

        return transactions

    @staticmethod
    def _parse_row(
        row: list[str | None], account: str, currency: str
    ) -> tuple[Transaction, Decimal] | None:
        """Parse a single table row. Returns (tx, balance) or None to skip.

        Expected columns (7):
          0: 记账日期 (YYYY-MM-DD)
          1: 货币
          2: 交易金额 (signed, comma-separated)
          3: 联机余额 (running balance after transaction)
          4: 交易摘要
          5: 对手信息 (counterparty)
          6: 客户摘要
        """
        if not row or len(row) < 4:
            return None

        cells = [str(c).strip() if c else "" for c in row]

        # Skip header rows (date column doesn't look like YYYY-MM-DD)
        date_str = cells[0]
        if not date_str or not date_str[:4].isdigit() or "-" not in date_str:
            return None

        try:
            tx_date = datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            return None

        # Currency from col 1 (may be empty for continuation rows)
        row_currency = cells[1] if len(cells) > 1 and cells[1] else currency

        # Parse transaction amount (col 2)
        amount_str = cells[2].replace(",", "").strip() if len(cells) > 2 else ""
        try:
            amount = Decimal(amount_str)
        except InvalidOperation:
            return None

        # Parse running balance (col 3)
        balance_str = cells[3].replace(",", "").strip() if len(cells) > 3 else ""
        try:
            balance = Decimal(balance_str)
        except InvalidOperation:
            return None

        narration = cells[4] if len(cells) > 4 else ""
        counterparty = cells[5] if len(cells) > 5 else ""
        customer_note = cells[6] if len(cells) > 6 else ""

        # Combine narration fields
        full_narration = narration
        if customer_note and customer_note != narration:
            full_narration = f"{narration}-{customer_note}" if narration else customer_note

        tx_type = "income" if amount > 0 else "expense"

        metadata: dict = {
            "balance": str(balance),
        }
        if row_currency != currency:
            metadata["currency"] = row_currency

        return (
            Transaction(
                date=tx_date,
                amount=amount,
                currency=row_currency,
                payee=counterparty,
                narration=full_narration,
                source_account=account,
                tx_type=tx_type,
                counter_account=None,  # top-of-chain: categorizer assigns
                metadata=metadata,
            ),
            balance,
        )
