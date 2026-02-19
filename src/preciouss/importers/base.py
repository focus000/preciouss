"""Base classes for all importers."""

from __future__ import annotations

import csv
import io
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

import chardet


@dataclass
class Transaction:
    """Intermediate transaction model used across all importers.

    This is NOT a beancount Transaction - it's our internal representation
    that gets converted to beancount entries by the ledger writer.
    """

    date: datetime
    amount: Decimal
    currency: str
    payee: str  # merchant / counterparty
    narration: str  # transaction description
    source_account: str  # beancount account name for this source
    payment_method: str | None = None  # e.g. "招商银行信用卡(尾号1234)"
    reference_id: str | None = None  # platform transaction ID
    counterpart_ref: str | None = None  # counterparty transaction ID
    raw_category: str | None = None  # platform's original category
    tx_type: str | None = None  # income/expense/transfer
    counter_account: str | None = None  # explicit counter-account (skips categorizer)
    metadata: dict = field(default_factory=dict)


def _amounts_match(a: Transaction, b: Transaction) -> bool:
    """Check if amounts match, including cross-currency via foreign_amount metadata."""
    # Same currency: direct comparison
    if a.currency == b.currency and abs(a.amount) == abs(b.amount):
        return True
    # Cross-currency: check wechathk_foreign_amount on either side
    for tx1, tx2 in [(a, b), (b, a)]:
        fa = tx1.metadata.get("wechathk_foreign_amount")
        fc = tx1.metadata.get("wechathk_foreign_currency")
        if fa and fc and fc == tx2.currency and Decimal(fa) == abs(tx2.amount):
            return True
    return False


class PrecioussImporter(ABC):
    """Abstract base class for all importers."""

    @abstractmethod
    def identify(self, filepath: str | Path) -> bool:
        """Return True if this importer can handle the given file."""
        raise NotImplementedError

    @abstractmethod
    def extract(self, filepath: str | Path) -> list[Transaction]:
        """Parse the file and return a list of Transaction objects."""
        raise NotImplementedError

    @abstractmethod
    def account_name(self) -> str:
        """Return the beancount account name for this importer."""
        raise NotImplementedError

    def match_clearing(
        self, seed_tx: Transaction, candidates: list[Transaction]
    ) -> Transaction | None:
        """Default clearing matcher: cross-ref match, then amount+date fallback.

        Override in subclasses for custom matching logic.
        """
        # Phase 1: reference_id / counterpart_ref cross-match
        seed_refs = {r for r in [seed_tx.reference_id, seed_tx.counterpart_ref] if r}
        for c in candidates:
            cand_refs = {r for r in [c.reference_id, c.counterpart_ref] if r}
            if seed_refs & cand_refs:
                return c
        # Phase 2: amount + date (±3 days), closest date first
        for c in sorted(candidates, key=lambda c: abs((seed_tx.date - c.date).total_seconds())):
            if abs(seed_tx.date - c.date) <= timedelta(days=3) and _amounts_match(seed_tx, c):
                return c
        return None


class CsvImporter(PrecioussImporter):
    """Base class for CSV-based importers.

    Handles encoding detection (GB18030/UTF-8) and CSV reading.
    Subclasses must implement _identify_header, _parse_row, and account_name.
    """

    # Number of lines to skip before the CSV header (platform-specific)
    skip_lines: int = 0

    # Expected header keywords for identification
    expected_headers: list[str] = []

    # CSV delimiter
    delimiter: str = ","

    # Whether to strip tab characters (\t, and \t) before parsing
    tab_delimited: bool = False

    def identify(self, filepath: str | Path) -> bool:
        """Identify by checking for expected header keywords."""
        filepath = Path(filepath)
        if filepath.suffix.lower() != ".csv":
            return False

        try:
            content = self._read_file(filepath)
            # Check first few lines for expected headers
            lines = content.split("\n")[: self.skip_lines + 5]
            header_area = "\n".join(lines)
            return all(kw in header_area for kw in self.expected_headers)
        except Exception:
            return False

    def extract(self, filepath: str | Path) -> list[Transaction]:
        """Read CSV and parse each row into Transaction objects."""
        filepath = Path(filepath)
        content = self._read_file(filepath)

        # Skip leading lines (some platforms add metadata before the header)
        lines = content.split("\n")
        csv_lines = lines[self.skip_lines :]

        if self.tab_delimited:
            csv_lines = [line.replace("\t,", ",").replace("\t", "") for line in csv_lines]

        csv_content = "\n".join(csv_lines)

        reader = csv.DictReader(io.StringIO(csv_content), delimiter=self.delimiter)
        transactions = []
        for row in reader:
            # Strip whitespace from keys and values
            row = {k.strip(): v.strip() if v else "" for k, v in row.items() if k}
            tx = self._parse_row(row)
            if tx is not None:
                transactions.append(tx)

        return transactions

    @abstractmethod
    def _parse_row(self, row: dict[str, str]) -> Transaction | None:
        """Parse a single CSV row into a Transaction, or None to skip."""
        raise NotImplementedError

    def _resolve_payment(self, payment_method: str) -> str:
        """Resolve payment method string to a beancount account."""
        if payment_method and payment_method not in ("", "/"):
            from preciouss.importers.resolve import resolve_payment_account

            return resolve_payment_account(payment_method, f"{self.account_name()}:Unknown")
        return self.account_name()

    def _read_file(self, filepath: Path) -> str:
        """Read file with automatic encoding detection."""
        raw = filepath.read_bytes()
        detected = chardet.detect(raw)
        encoding = detected.get("encoding", "utf-8")

        # Common Chinese CSV encodings
        for enc in [encoding, "utf-8-sig", "gb18030", "gbk", "utf-8"]:
            try:
                return raw.decode(enc)
            except (UnicodeDecodeError, LookupError):
                continue

        return raw.decode("utf-8", errors="replace")
