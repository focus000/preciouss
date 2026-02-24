"""Apply overrides to intermediate Transaction objects during import."""

from __future__ import annotations

from preciouss.categorize.overrides import OverrideEntry
from preciouss.importers.base import Transaction


def apply_overrides(
    transactions: list[Transaction],
    overrides: dict[str, OverrideEntry],
) -> int:
    """Apply override entries to transactions, matched by reference_id.

    Override logic:
    - category (non-empty) → sets tx.counter_account (skips auto-categorizer)
    - payee (non-empty) → sets tx.payee
    - narration (non-empty) → sets tx.narration

    Returns the number of transactions that were overridden.
    """
    if not overrides:
        return 0

    count = 0
    for tx in transactions:
        if tx.reference_id is None:
            continue
        entry = overrides.get(tx.reference_id)
        if entry is None:
            continue

        applied = False
        if entry.category:
            tx.counter_account = entry.category
            applied = True
        if entry.payee:
            tx.payee = entry.payee
            applied = True
        if entry.narration:
            tx.narration = entry.narration
            applied = True

        if applied:
            count += 1

    return count
