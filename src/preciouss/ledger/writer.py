"""Beancount file writer - converts intermediate Transactions to .bean files."""

from __future__ import annotations

import datetime
from pathlib import Path

from beancount.core.data import (
    Amount,
    Posting,
    new_metadata,
)
from beancount.core.data import (
    Transaction as BeanTransaction,
)
from beancount.parser import printer

from preciouss.importers.base import Transaction
from preciouss.ledger.accounts import (
    DEFAULT_ACCOUNTS,
    DEFAULT_CURRENCIES,
    get_expense_account_for_type,
)


def transaction_to_bean(tx: Transaction, counter_account: str | None = None) -> BeanTransaction:
    """Convert an intermediate Transaction to a beancount Transaction.

    Args:
        tx: Our intermediate Transaction object.
        counter_account: The counter-account for double-entry. If None,
                        auto-determined based on tx_type.

    Returns:
        A beancount Transaction directive.
    """
    if counter_account is None:
        counter_account = get_expense_account_for_type(tx.tx_type)

    meta = new_metadata("<preciouss>", 0)
    if tx.reference_id:
        meta["ref"] = tx.reference_id
    if tx.counterpart_ref:
        meta["counterpart_ref"] = tx.counterpart_ref
    if tx.payment_method:
        meta["payment_method"] = tx.payment_method
    if tx.raw_category:
        meta["raw_category"] = tx.raw_category

    tags = frozenset()
    links = frozenset()

    # Build postings
    postings = []

    # Source account posting (the account where money comes from/goes to)
    postings.append(
        Posting(
            tx.source_account,
            Amount(tx.amount, tx.currency),
            None,
            None,
            None,
            None,
        )
    )

    # Counter account posting (expense/income category)
    postings.append(
        Posting(
            counter_account,
            Amount(-tx.amount, tx.currency),
            None,
            None,
            None,
            None,
        )
    )

    return BeanTransaction(
        meta=meta,
        date=tx.date.date() if isinstance(tx.date, datetime.datetime) else tx.date,
        flag="*",
        payee=tx.payee or None,
        narration=tx.narration or "",
        tags=tags,
        links=links,
        postings=postings,
    )


def write_transactions(
    transactions: list[Transaction],
    output_path: str | Path,
    counter_account: str | None = None,
    categorizer: "RuleCategorizer | None" = None,
) -> Path:
    """Write a list of intermediate Transactions to a .bean file.

    Args:
        transactions: List of Transaction objects to write.
        output_path: Path for the output .bean file.
        counter_account: Default counter-account. If None, auto-determined per tx.
        categorizer: Optional RuleCategorizer to auto-categorize transactions.

    Returns:
        Path to the written file.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    bean_entries = []
    for tx in transactions:
        # Try auto-categorization first
        cat_account = None
        if categorizer is not None:
            cat_account = categorizer.categorize(tx)
        effective_account = cat_account or counter_account
        bean_tx = transaction_to_bean(tx, effective_account)
        bean_entries.append(bean_tx)

    # Sort by date
    bean_entries.sort(key=lambda e: e.date)

    with open(output_path, "w", encoding="utf-8") as f:
        for entry in bean_entries:
            f.write(printer.format_entry(entry))
            f.write("\n")

    return output_path


def init_ledger(ledger_dir: str | Path, default_currency: str = "CNY") -> None:
    """Initialize a new ledger directory with default files.

    Creates:
    - main.bean (includes other files)
    - accounts.bean (account definitions)
    - commodities.bean (currency definitions)
    """
    ledger_dir = Path(ledger_dir)
    ledger_dir.mkdir(parents=True, exist_ok=True)
    (ledger_dir / "importers").mkdir(exist_ok=True)
    (ledger_dir / "prices").mkdir(exist_ok=True)

    today = datetime.date.today()
    # Use an early date for account open directives so they precede all transactions
    open_date = datetime.date(1970, 1, 1)

    # Write main.bean
    main_path = ledger_dir / "main.bean"
    if not main_path.exists():
        main_content = f"""\
;; Preciouss Ledger - Main File
;; Generated on {today}

option "title" "Personal Finance"
option "operating_currency" "{default_currency}"

include "commodities.bean"
include "accounts.bean"
include "importers/*.bean"
"""
        main_path.write_text(main_content, encoding="utf-8")

    # Write commodities.bean
    commodities_path = ledger_dir / "commodities.bean"
    if not commodities_path.exists():
        lines = [f";; Currency definitions\n;; Generated on {today}\n"]
        for curr in DEFAULT_CURRENCIES:
            lines.append(f"{open_date} commodity {curr}")
        commodities_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # Write accounts.bean
    accounts_path = ledger_dir / "accounts.bean"
    if not accounts_path.exists():
        lines = [f";; Account definitions\n;; Generated on {today}\n"]
        for account, description in DEFAULT_ACCOUNTS.items():
            currencies = f"{default_currency}"
            if "HK" in account:
                currencies = "HKD"
            elif "PayPal" in account or "IBKR" in account:
                currencies = "USD"

            lines.append(f"{open_date} open {account} {currencies} ; {description}")
        accounts_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
