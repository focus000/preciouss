"""Beancount file writer - converts intermediate Transactions to .bean files."""

from __future__ import annotations

import datetime
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from preciouss.categorize.rules import RuleCategorizer

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


def _make_posting(
    account: str, number: Decimal, currency: str, meta: dict | None = None
) -> Posting:
    """Create a Posting with standard None fields for cost/price/flag."""
    return Posting(account, Amount(number, currency), None, None, None, meta)


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
    links = frozenset({tx.metadata["link"]}) if tx.metadata.get("link") else frozenset()

    # Build postings
    postings = []

    # Source account posting (the account where money comes from/goes to)
    postings.append(_make_posting(tx.source_account, tx.amount, tx.currency))

    # Counter account posting (expense/income category)
    postings.append(_make_posting(counter_account, -tx.amount, tx.currency))

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


def group_items_by_category(
    items: list[dict],
    total_payment: Decimal,
) -> list[tuple[str, Decimal, list[dict]]]:
    """Group items by category with proportional discount allocation.

    Each item's effective price is scaled from its listed price proportionally:
        effective = listed_price × (total_payment / listed_total)

    Items metadata retains original listed prices; posting amounts use effective prices.
    Rounding residual is applied to the largest category.

    Returns a list of (account, total_amount, items) tuples sorted by account name.
    """
    listed_total = sum(Decimal(item["price"]) * int(item["num"]) for item in items)
    if listed_total == 0:
        return []
    scale = total_payment / listed_total

    by_category: dict[str, tuple[Decimal, list[dict]]] = {}
    for item in items:
        account = item["category"]
        listed = Decimal(item["price"]) * int(item["num"])
        effective = (listed * scale).quantize(Decimal("0.01"))
        if account not in by_category:
            by_category[account] = (Decimal(0), [])
        cur_total, cur_items = by_category[account]
        by_category[account] = (cur_total + effective, cur_items + [item])

    result = sorted((acct, total, its) for acct, (total, its) in by_category.items())

    # Apply rounding correction to the largest category
    rounding_diff = total_payment - sum(t for _, t, _ in result)
    if rounding_diff != Decimal(0) and result:
        max_idx = max(range(len(result)), key=lambda i: result[i][1])
        acct, total, its = result[max_idx]
        result[max_idx] = (acct, total + rounding_diff, its)

    return result


def _format_item(item: dict) -> str:
    """Format a single item: 'name xN ¥price'."""
    num = int(item["num"])
    total = Decimal(item["price"]) * num
    return f"{item['name']} x{num} ¥{total}"


def multiposting_transaction_to_bean(
    tx: Transaction,
    category_amounts: list[tuple[str, Decimal, list[dict]]],
    gift_card_amount: Decimal = Decimal(0),
    source_posting_override: Posting | None = None,
) -> BeanTransaction:
    """Generate a multi-posting beancount entry: source + optional gift card + N expense postings.

    category_amounts must already sum to abs(tx.amount) + gift_card_amount (via
    group_items_by_category with the correct total_payment).

    source_posting_override: if provided, replaces the default source posting. Used for
    cross-currency payments (e.g. Costco CNY receipt paid via WeChat HK in HKD).
    """
    meta = new_metadata("<preciouss>", 0)
    if tx.reference_id:
        meta["ref"] = tx.reference_id
    if tx.payment_method:
        meta["payment_method"] = tx.payment_method
    if tx.metadata.get("aldi_channel"):
        meta["channel"] = tx.metadata["aldi_channel"]

    if source_posting_override is not None:
        postings = [source_posting_override]
    else:
        postings = [_make_posting(tx.source_account, tx.amount, tx.currency)]

    if gift_card_amount > Decimal(0):
        postings.append(_make_posting("Assets:JD:GiftCard", -gift_card_amount, tx.currency))

    for account, amount, its in category_amounts:
        posting_meta = new_metadata("<preciouss>", 0)
        posting_meta["items"] = ", ".join(_format_item(it) for it in its)
        postings.append(_make_posting(account, amount, tx.currency, posting_meta))

    return BeanTransaction(
        meta=meta,
        date=tx.date.date() if isinstance(tx.date, datetime.datetime) else tx.date,
        flag="*",
        payee=tx.payee or None,
        narration=tx.narration or "",
        tags=frozenset(),
        links=frozenset({tx.metadata["link"]}) if tx.metadata.get("link") else frozenset(),
        postings=postings,
    )


def write_transactions(
    transactions: list[Transaction],
    output_path: str | Path,
    counter_account: str | None = None,
    categorizer: RuleCategorizer | None = None,
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
        # Build links from metadata
        links = frozenset({tx.metadata["link"]}) if tx.metadata.get("link") else frozenset()

        if tx.metadata.get("aldi_items"):
            # Multi-posting path: group ALDI items by category (proportional)
            total_payment = -tx.amount
            by_category = group_items_by_category(tx.metadata["aldi_items"], total_payment)
            bean_tx = multiposting_transaction_to_bean(tx, by_category)
        elif tx.metadata.get("costco_items"):
            # Multi-posting path: group Costco items by category (proportional)
            total_payment = -tx.amount
            by_category = group_items_by_category(tx.metadata["costco_items"], total_payment)
            bean_tx = multiposting_transaction_to_bean(tx, by_category)
        elif tx.metadata.get("jd_items"):
            # Multi-posting path: JD items with optional gift card
            gift_card_str = tx.metadata.get("jd_gift_card")
            gift_card = Decimal(gift_card_str) if gift_card_str else Decimal(0)
            total_payment = -tx.amount + gift_card
            by_category = group_items_by_category(tx.metadata["jd_items"], total_payment)
            bean_tx = multiposting_transaction_to_bean(tx, by_category, gift_card_amount=gift_card)
        elif tx.counter_account:
            # Explicit counter_account path (clearing bridges, transfers)
            if tx.metadata.get("wechathk_foreign_amount"):
                # Cross-currency bridge: HKD source → CNY counter
                foreign_amount = Decimal(tx.metadata["wechathk_foreign_amount"])
                foreign_currency = tx.metadata["wechathk_foreign_currency"]
                hkd_amount = abs(tx.amount)
                rate = (foreign_amount / hkd_amount).quantize(Decimal("0.000001"))
                source_posting = Posting(
                    tx.source_account,
                    Amount(tx.amount, tx.currency),
                    None,
                    Amount(rate, foreign_currency),
                    None,
                    None,
                )
                meta = new_metadata("<preciouss>", 0)
                if tx.reference_id:
                    meta["ref"] = tx.reference_id
                if tx.payment_method:
                    meta["payment_method"] = tx.payment_method
                bean_tx = BeanTransaction(
                    meta=meta,
                    date=tx.date.date() if isinstance(tx.date, datetime.datetime) else tx.date,
                    flag="*",
                    payee=tx.payee or None,
                    narration=tx.narration or "",
                    tags=frozenset(),
                    links=links,
                    postings=[
                        source_posting,
                        _make_posting(
                            tx.counter_account,
                            foreign_amount if tx.amount < 0 else -foreign_amount,
                            foreign_currency,
                        ),
                    ],
                )
            else:
                # Simple bridge: source → counter_account
                bean_tx = transaction_to_bean(tx, tx.counter_account)
        elif tx.metadata.get("wechathk_foreign_amount"):
            # Standalone WechatHK cross-currency (no counter_account, e.g. HK local spend)
            foreign_amount = Decimal(tx.metadata["wechathk_foreign_amount"])
            foreign_currency = tx.metadata["wechathk_foreign_currency"]
            hkd_amount = abs(tx.amount)
            rate = (foreign_amount / hkd_amount).quantize(Decimal("0.000001"))
            source_posting = Posting(
                tx.source_account,
                Amount(tx.amount, tx.currency),
                None,
                Amount(rate, foreign_currency),
                None,
                None,
            )
            cat_account = categorizer.categorize(tx) if categorizer else None
            counter = cat_account or counter_account or get_expense_account_for_type(tx.tx_type)
            meta = new_metadata("<preciouss>", 0)
            if tx.reference_id:
                meta["ref"] = tx.reference_id
            if tx.payment_method:
                meta["payment_method"] = tx.payment_method
            bean_tx = BeanTransaction(
                meta=meta,
                date=tx.date.date() if isinstance(tx.date, datetime.datetime) else tx.date,
                flag="*",
                payee=tx.payee or None,
                narration=tx.narration or "",
                tags=frozenset(),
                links=links,
                postings=[
                    source_posting,
                    _make_posting(
                        counter,
                        foreign_amount if tx.amount < 0 else -foreign_amount,
                        foreign_currency,
                    ),
                ],
            )
        else:
            # Standard 2-posting path
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
            if account.startswith(("Expenses:", "Income:", "Equity:")):
                # Expenses/Income/Equity accept any currency
                currencies = ",".join(DEFAULT_CURRENCIES)
            elif account.startswith("Assets:Clearing:"):
                # Clearing accounts may bridge different currencies
                currencies = ",".join(DEFAULT_CURRENCIES)
            elif "HK" in account:
                currencies = "HKD"
            elif "PayPal" in account or "IBKR" in account:
                currencies = "USD"
            else:
                currencies = default_currency

            lines.append(f"{open_date} open {account} {currencies} ; {description}")
        accounts_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
