"""CITIC Bank (中信银行) credit card PDF importer.

Supports annual PDF files covering multiple billing cycles.
Each billing cycle spans ~2 pages:
  - Page 1: header (账单日, 到期还款日) + card summary + transaction table
  - Page 2: disclaimer text (skipped automatically)
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from preciouss.importers.base import PrecioussImporter, Transaction

logger = logging.getLogger(__name__)

# Regex to extract 本期新增金额 from the CNY card balance summary row.
# The row format is: "CNY {上期应还款额} {上期已还款额} {本期新增金额} ..."
# 本期新增金额 is the third decimal value after the "CNY" prefix.
_CNY_BALANCE_RE = re.compile(
    r"CNY\s+([\d,]+\.\d{2})\s+([\d,]+\.\d{2})\s+([\d,]+\.\d{2})\b"
)

# Statement date line: "账单日\n2025-01-08\nStatement Date" (pdfplumber flattens newlines)
# Also handles inline: "账单日 Statement Date  2026-01-08"
_STATEMENT_DATE_RE = re.compile(r"账单日\D{0,30}?(\d{4}-\d{2}-\d{2})")

# Transaction date: 8-digit YYYYMMDD (new format) or YYYY-MM-DD (old format pre-2023)
_DATE_TX_RE = re.compile(r"^\d{8}$|^\d{4}-\d{2}-\d{2}$")

# CITIC PDF column x-boundaries — unified across both PDF generations:
#   New (2024+): YYYYMMDD, tx_date~8, post_date~74, card4~159, desc~214, tx_amt~370, setl~482
#   Old (2020-22): YYYY-MM-DD, tx_date~33, post_date~89, card4~152, desc~181, tx_amt~411, setl~490
# Boundaries chosen so both generations land in the correct column.
_CITIC_COLS = [
    ("tx_date",   0,    72),
    ("post_date", 72,   143),
    ("card4",     143,  178),
    ("desc",      178,  368),
    ("tx_amt",    368,  480),
    ("setl_amt",  480,  9999),
]


def _citic_col_of(x0: float) -> str | None:
    for name, lo, hi in _CITIC_COLS:
        if lo <= x0 < hi:
            return name
    return None


def _parse_amount(s: str) -> Decimal | None:
    """Parse 'CNY 106.19', 'RMB 10.00', or 'CNY -47.00' → Decimal."""
    s = s.strip()
    # Strip currency prefix (RMB used in older CITIC PDFs pre-2023)
    for prefix in ("CNY ", "RMB ", "HKD ", "USD ", "EUR "):
        if s.startswith(prefix):
            s = s[len(prefix) :]
            break
    s = s.replace(",", "").strip()
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def _parse_date(s: str) -> datetime | None:
    """Parse 'YYYYMMDD' or 'YYYY-MM-DD' → datetime."""
    s = s.strip()
    for fmt in ("%Y%m%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


class CiticCreditPdfImporter(PrecioussImporter):
    """Import transactions from CITIC credit card annual PDF statements.

    Sign convention (same as CmbCreditImporter):
    - Positive in PDF (charge/expense) → amount = -value, tx_type = "expense"
    - Negative in PDF (repayment/refund) → amount = +value, tx_type = "income"
    """

    def __init__(
        self,
        account: str = "Liabilities:CreditCard:CITIC",
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
            # CITIC credit card PDFs contain "账单日" (billing date) and
            # "银行记账日" (bank posting date column header).
            # Neither keyword appears in CMB debit PDFs.
            return "账单日" in text and "银行记账日" in text
        except Exception:
            return False

    def extract(self, filepath: str | Path) -> list[Transaction]:
        pages = self._read_pdf(filepath)
        return self._parse(pages, self._account, self._currency)

    @staticmethod
    def _read_pdf(filepath: str | Path) -> list[dict]:
        """Return list of {text, table} per page. Pure I/O layer.

        Uses coordinate-based word extraction because the CITIC transaction
        table has no visible borders that pdfplumber can detect.  Words are
        grouped by row (Y position) and assigned to columns by X position.
        """
        import pdfplumber

        pages = []
        with pdfplumber.open(filepath) as pdf:
            for page in pdf.pages:
                text = page.extract_text() or ""
                words = page.extract_words()

                # Group words by approximate row (round top to nearest 4 pts)
                row_groups: dict = defaultdict(lambda: defaultdict(list))
                for w in words:
                    key = round(w["top"] / 4) * 4
                    col = _citic_col_of(w["x0"])
                    if col:
                        row_groups[key][col].append(w["text"])

                # Extract transaction rows: rows that have a transaction date in tx_date col
                table_rows: list[list[str]] = []
                for key in sorted(row_groups.keys()):
                    row = row_groups[key]
                    if any(_DATE_TX_RE.match(t) for t in row.get("tx_date", [])):
                        table_rows.append([
                            " ".join(row.get("tx_date", [])),
                            " ".join(row.get("post_date", [])),
                            " ".join(row.get("card4", [])),
                            " ".join(row.get("desc", [])),
                            " ".join(row.get("tx_amt", [])),
                            " ".join(row.get("setl_amt", [])),
                        ])

                pages.append({"text": text, "table": table_rows})

        return pages

    @classmethod
    def _parse(
        cls, pages: list[dict], account: str, currency: str
    ) -> list[Transaction]:
        """Parse all pages into transactions. Pure logic layer (no I/O)."""
        transactions: list[Transaction] = []
        current_statement_date: date | None = None
        current_new_charge: Decimal | None = None

        for page in pages:
            text = page["text"]
            table = page["table"]

            # Try to find billing cycle statement date on this page
            m = _STATEMENT_DATE_RE.search(text)
            if m:
                try:
                    current_statement_date = datetime.strptime(m.group(1), "%Y-%m-%d").date()
                except ValueError:
                    pass

            # Try to extract 本期新增金额 from this page.
            # Only look on pages that have the card balance summary section.
            if "本期新增金额" in text:
                m2 = _CNY_BALANCE_RE.search(text)
                if m2:
                    try:
                        current_new_charge = Decimal(m2.group(3).replace(",", ""))
                    except InvalidOperation:
                        current_new_charge = None

            # Parse transaction rows from the table
            cycle_expenses = []
            for row in table:
                if row is None:
                    continue
                tx = cls._parse_row(row, account, currency, current_statement_date)
                if tx is not None:
                    transactions.append(tx)
                    if tx.tx_type == "expense":
                        cycle_expenses.append(tx)

            # Validate per-cycle total if we have a new_charge value
            if current_new_charge is not None and cycle_expenses:
                total = sum(-tx.amount for tx in cycle_expenses)
                if abs(total - current_new_charge) > Decimal("1.00"):
                    logger.warning(
                        "CITIC cycle total mismatch: computed=%.2f, stated=%.2f "
                        "(statement_date=%s)",
                        total,
                        current_new_charge,
                        current_statement_date,
                    )
                else:
                    logger.debug(
                        "CITIC cycle total OK: %.2f (statement_date=%s)",
                        total,
                        current_statement_date,
                    )
                # Reset for next cycle
                current_new_charge = None

        return transactions

    @staticmethod
    def _parse_row(
        row: list[str | None],
        account: str,
        currency: str,
        statement_date: date | None,
    ) -> Transaction | None:
        """Parse a single table row into a Transaction, or None to skip.

        Expected columns (6):
          0: 交易日 (YYYYMMDD new format, or YYYY-MM-DD old format)
          1: 银行记账日 (same format as col 0)
          2: 卡号后四位
          3: 交易描述
          4: 交易货币/金额 (e.g. "CNY 106.19" or "RMB 10.00")
          5: 记账货币/金额 (e.g. "CNY 106.19" or "RMB 10.00")
        """
        if not row or len(row) < 5:
            return None

        # Normalize cells
        cells = [str(c).strip() if c else "" for c in row]

        # Skip header rows
        if cells[0] in ("交易日", "交易日期") or cells[0] == "":
            return None

        # Parse transaction date
        tx_date = _parse_date(cells[0])
        if tx_date is None:
            return None

        # Parse posting date (col 1)
        post_date_str = cells[1] if len(cells) > 1 else ""
        post_date = _parse_date(post_date_str)

        card_last4 = cells[2] if len(cells) > 2 else ""
        description = cells[3] if len(cells) > 3 else ""

        # Amount from col 4 (交易货币/金额) — prefer col 5 (记账货币/金额, CNY)
        amount_str = cells[5] if len(cells) > 5 and cells[5] else cells[4] if len(cells) > 4 else ""
        if not amount_str:
            return None

        amount_raw = _parse_amount(amount_str)
        if amount_raw is None:
            return None

        # Sign convention: positive PDF value = expense, negative = income/refund
        if amount_raw >= 0:
            tx_type = "expense"
            amount = -amount_raw
        else:
            tx_type = "income"
            amount = -amount_raw  # -(-|value|) = positive

        metadata: dict = {}
        if card_last4:
            metadata["card_last4"] = card_last4
        if post_date:
            metadata["post_date"] = post_date.strftime("%Y-%m-%d")
        if statement_date:
            metadata["statement_date"] = statement_date.strftime("%Y-%m-%d")

        return Transaction(
            date=tx_date,
            amount=amount,
            currency=currency,
            payee=description,
            narration=description,
            source_account=account,
            tx_type=tx_type,
            counter_account=None,  # top-of-chain: categorizer assigns expense
            metadata=metadata,
        )

    @staticmethod
    def _extract_new_charge(page_text: str) -> Decimal | None:
        """Extract 本期新增金额 (CNY) from billing cycle summary page text.

        The CNY card balance summary row has the format:
          "CNY {上期应还款额} {上期已还款额} {本期新增金额} {账户账单金额} {最低还款额}"
        so 本期新增金额 is group(3) of _CNY_BALANCE_RE.
        Only present on pages that contain the "本期新增金额" header label.
        """
        if "本期新增金额" not in page_text:
            return None
        m = _CNY_BALANCE_RE.search(page_text)
        if m:
            try:
                return Decimal(m.group(3).replace(",", ""))
            except InvalidOperation:
                return None
        return None
