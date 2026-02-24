"""BQL query layer for filtering and locating transactions in the ledger."""

from __future__ import annotations

import datetime
import re
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import beanquery

DEFAULT_WHERE = (
    "account = 'Expenses:Uncategorized' OR account = 'Income:Uncategorized'"
)

# Account prefixes that represent the "category" side of a transaction
_CATEGORY_PREFIXES = ("Expenses:", "Income:")


@dataclass
class MatchedTransaction:
    """A transaction matched by BQL query, with enough info for display and override."""

    ref: str  # meta['ref'] — used as txid
    filename: str  # .bean file absolute path
    lineno: int  # transaction header line number
    date: datetime.date
    payee: str
    narration: str
    amount: Decimal  # category posting amount
    currency: str
    current_account: str  # current category account (Expenses:*/Income:*)


def connect(ledger_dir: str, main_file: str) -> beanquery.Connection:
    """Create a beanquery connection to the ledger.

    Uses the beancount:// URI scheme required by beanquery.
    """
    main_path = Path(ledger_dir).resolve() / main_file
    return beanquery.connect(f"beancount://{main_path}")


def _extract_from_entry(entry, posting_account: str, posting_number, posting_currency: str):
    """Extract MatchedTransaction fields from a beancount entry + posting info."""
    ref = entry.meta.get("ref")
    if ref is None:
        return None

    return MatchedTransaction(
        ref=str(ref),
        filename=entry.meta.get("filename", ""),
        lineno=entry.meta.get("lineno", 0),
        date=entry.date,
        payee=entry.payee or "",
        narration=entry.narration or "",
        amount=posting_number,
        currency=posting_currency,
        current_account=posting_account,
    )


def query_transactions(
    conn: beanquery.Connection,
    where_clause: str | None = None,
) -> list[MatchedTransaction]:
    """Query postings table and return deduplicated MatchedTransaction list.

    Groups by transaction id to deduplicate multiple postings per transaction.
    For each transaction, finds the Expenses:/Income: posting as the categorizable one.
    Skips transactions without ref or without a category posting.
    """
    where = where_clause or DEFAULT_WHERE
    sql = (
        "SELECT id, entry, account, number, currency "
        f"FROM postings WHERE {where} "
        "ORDER BY date, filename, lineno"
    )
    curs = conn.execute(sql)
    rows = curs.fetchall()

    # Group by transaction id to get unique transactions
    # Each row: (id, entry, account, number, currency)
    tx_groups: dict[str, list[tuple]] = {}
    for row in rows:
        tx_id = row[0]
        tx_groups.setdefault(tx_id, []).append(row)

    results: list[MatchedTransaction] = []
    for _tx_id, postings in tx_groups.items():
        category_posting = None
        entry = postings[0][1]  # entry is same for all postings in a tx

        for p in postings:
            p_account = p[2]
            if any(p_account.startswith(prefix) for prefix in _CATEGORY_PREFIXES):
                category_posting = p
                break

        if category_posting is None:
            continue

        matched = _extract_from_entry(
            entry,
            posting_account=category_posting[2],
            posting_number=category_posting[3],
            posting_currency=category_posting[4],
        )
        if matched is not None:
            results.append(matched)

    return results


def find_by_refs(
    conn: beanquery.Connection,
    refs: list[str],
) -> list[MatchedTransaction]:
    """Find transactions by ref values (txids).

    Uses ANY_META('ref') which searches both posting and transaction metadata.
    """
    if not refs:
        return []

    # Build WHERE clause using ANY_META which searches transaction-level meta
    conditions = " OR ".join(f"ANY_META('ref') = '{ref}'" for ref in refs)
    return query_transactions(conn, conditions)


def read_bean_entry(filename: str, lineno: int) -> str:
    """Read a transaction block from a .bean file starting at lineno.

    Reads from lineno until the next blank line or next transaction header.
    Returns the raw text of the transaction.
    """
    path = Path(filename)
    if not path.exists():
        return ""

    lines = path.read_text(encoding="utf-8").splitlines()
    start = lineno - 1  # Convert to 0-indexed

    if start < 0 or start >= len(lines):
        return ""

    result: list[str] = [lines[start]]
    tx_header_re = re.compile(r"^\d{4}-\d{2}-\d{2}\s")

    for i in range(start + 1, len(lines)):
        line = lines[i]
        # Stop at blank line or next transaction header
        if line.strip() == "" or (tx_header_re.match(line) and i > start):
            break
        result.append(line)

    return "\n".join(result)
