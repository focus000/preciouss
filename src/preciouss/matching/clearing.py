"""Clearing link generation via DFS matching.

Traverses from terminal expenses upward through clearing chains,
assigning shared ^clr-NNNNNN links to related transactions.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from preciouss.importers.base import PrecioussImporter, Transaction
from preciouss.importers.clearing import is_clearing_account


@dataclass
class ClearingStats:
    total_chains: int  # number of links generated
    total_linked: int  # total transactions that received a link
    unmatched_terminal: int  # terminal expenses that couldn't match any upstream


def _is_terminal_expense(tx: Transaction) -> bool:
    """A terminal expense has a clearing source and a non-clearing (or None) counter."""
    if tx.tx_type != "expense":
        return False
    if not is_clearing_account(tx.source_account):
        return False
    if tx.counter_account and is_clearing_account(tx.counter_account):
        return False
    return True


def assign_clearing_links(
    transactions: list[Transaction],
    importer_map: dict[int, PrecioussImporter],
) -> ClearingStats:
    """Assign ^clr-NNNNNN links via DFS from terminal expenses.

    Args:
        transactions: All extracted transactions (flat list across importers).
        importer_map: Mapping from transaction index → importer instance.

    Returns:
        Statistics about the linking process.
    """
    # Build counter_account index: clearing_account → [tx indices]
    counter_index: defaultdict[str, list[int]] = defaultdict(list)
    for i, tx in enumerate(transactions):
        if tx.counter_account and is_clearing_account(tx.counter_account):
            counter_index[tx.counter_account].append(i)

    link_counter = 0
    total_linked = 0
    unmatched_terminal = 0

    # Find all terminal expenses and DFS from each
    for i, tx in enumerate(transactions):
        if not _is_terminal_expense(tx):
            continue
        if tx.metadata.get("link"):
            continue  # already linked

        link_name = f"clr-{link_counter:06d}"
        link_counter += 1
        tx.metadata["link"] = link_name
        total_linked += 1

        matched_any = _dfs_propagate(tx, transactions, importer_map, counter_index)
        if matched_any:
            total_linked += matched_any
        else:
            unmatched_terminal += 1

    return ClearingStats(
        total_chains=link_counter,
        total_linked=total_linked,
        unmatched_terminal=unmatched_terminal,
    )


def _dfs_propagate(
    seed_tx: Transaction,
    transactions: list[Transaction],
    importer_map: dict[int, PrecioussImporter],
    counter_index: defaultdict[str, list[int]],
) -> int:
    """DFS upward through clearing chain, returning count of newly linked transactions."""
    linked_count = 0
    current = seed_tx
    link_name = current.metadata["link"]

    while True:
        # Stop if source is not a clearing account
        if not is_clearing_account(current.source_account):
            break

        # Find candidates: transactions whose counter_account == current.source_account, no link yet
        candidate_indices = [
            idx
            for idx in counter_index.get(current.source_account, [])
            if not transactions[idx].metadata.get("link")
        ]
        if not candidate_indices:
            break

        candidates = [transactions[idx] for idx in candidate_indices]

        # Find the importer for the current tx to use its matcher
        # We need to find current tx's index; look up by identity
        current_idx = None
        for idx, tx in enumerate(transactions):
            if tx is current:
                current_idx = idx
                break

        if current_idx is None:
            break

        importer = importer_map.get(current_idx)
        if importer is None:
            break

        matched = importer.match_clearing(current, candidates)
        if matched is None:
            break

        matched.metadata["link"] = link_name
        linked_count += 1
        current = matched

    return linked_count
