"""Transaction matching engine - matches cross-platform transactions."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta

from rapidfuzz import fuzz

from preciouss.importers.base import Transaction


@dataclass
class MatchResult:
    """Result of matching two transactions."""

    tx_a: Transaction
    tx_b: Transaction
    match_type: str  # "reference", "intermediary", "fuzzy"
    confidence: float  # 0.0 to 1.0


@dataclass
class MatchingOutput:
    """Output of the matching engine."""

    matched: list[MatchResult] = field(default_factory=list)
    unmatched: list[Transaction] = field(default_factory=list)


class MatchingEngine:
    """Three-phase transaction matching engine.

    Phase 1: Reference ID exact matching
    Phase 2: Intermediary pattern matching (e.g. Alipay -> credit card)
    Phase 3: Fuzzy matching (amount + date + payee similarity)
    """

    def __init__(
        self,
        date_tolerance_days: int = 3,
        fuzzy_payee_threshold: float = 0.7,
    ):
        self.date_tolerance = timedelta(days=date_tolerance_days)
        self.fuzzy_threshold = fuzzy_payee_threshold

    def match(self, transactions: list[Transaction]) -> MatchingOutput:
        """Run all matching phases on a list of transactions.

        Args:
            transactions: All transactions from all sources to match against each other.

        Returns:
            MatchingOutput with matched pairs and unmatched transactions.
        """
        remaining = list(transactions)
        all_matches: list[MatchResult] = []

        # Phase 1: Reference ID matching
        matches, remaining = self._phase_reference(remaining)
        all_matches.extend(matches)

        # Phase 2: Intermediary pattern matching
        matches, remaining = self._phase_intermediary(remaining)
        all_matches.extend(matches)

        # Phase 3: Fuzzy matching
        matches, remaining = self._phase_fuzzy(remaining)
        all_matches.extend(matches)

        return MatchingOutput(matched=all_matches, unmatched=remaining)

    def _phase_reference(
        self, transactions: list[Transaction]
    ) -> tuple[list[MatchResult], list[Transaction]]:
        """Phase 1: Match transactions by reference ID / counterpart ref."""
        matches = []
        matched_indices: set[int] = set()

        # Build index of reference IDs
        ref_index: dict[str, list[int]] = {}
        for i, tx in enumerate(transactions):
            if tx.reference_id:
                ref_index.setdefault(tx.reference_id, []).append(i)
            if tx.counterpart_ref:
                ref_index.setdefault(tx.counterpart_ref, []).append(i)

        # Find transactions that share a reference
        for ref_id, indices in ref_index.items():
            if len(indices) < 2:
                continue
            for j in range(1, len(indices)):
                i_a, i_b = indices[0], indices[j]
                if i_a in matched_indices or i_b in matched_indices:
                    continue
                if transactions[i_a].source_account == transactions[i_b].source_account:
                    continue  # Same source, not a cross-platform match
                matches.append(
                    MatchResult(
                        tx_a=transactions[i_a],
                        tx_b=transactions[i_b],
                        match_type="reference",
                        confidence=1.0,
                    )
                )
                matched_indices.add(i_a)
                matched_indices.add(i_b)

        remaining = [tx for i, tx in enumerate(transactions) if i not in matched_indices]
        return matches, remaining

    def _phase_intermediary(
        self, transactions: list[Transaction]
    ) -> tuple[list[MatchResult], list[Transaction]]:
        """Phase 2: Match intermediary patterns (e.g. Alipay via credit card)."""
        matches = []
        matched_indices: set[int] = set()

        # Identify payment platform transactions with payment_method set
        platform_txs = []
        bank_txs = []
        for i, tx in enumerate(transactions):
            if tx.payment_method:
                platform_txs.append((i, tx))
            else:
                bank_txs.append((i, tx))

        for pi, ptx in platform_txs:
            if pi in matched_indices:
                continue
            for bi, btx in bank_txs:
                if bi in matched_indices:
                    continue
                # Check: same amount (absolute), close dates, payee contains platform name
                if abs(ptx.amount) != abs(btx.amount):
                    continue
                if ptx.currency != btx.currency:
                    continue
                date_diff = abs(ptx.date - btx.date)
                if date_diff > self.date_tolerance:
                    continue
                # Check if the bank transaction mentions the platform
                btx_text = f"{btx.payee} {btx.narration}".lower()
                platform_keywords = ["支付宝", "财付通", "微信", "alipay", "wechat", "tenpay"]
                if any(kw in btx_text for kw in platform_keywords):
                    matches.append(
                        MatchResult(
                            tx_a=ptx,
                            tx_b=btx,
                            match_type="intermediary",
                            confidence=0.9,
                        )
                    )
                    matched_indices.add(pi)
                    matched_indices.add(bi)
                    break

        remaining = [tx for i, tx in enumerate(transactions) if i not in matched_indices]
        return matches, remaining

    def _phase_fuzzy(
        self, transactions: list[Transaction]
    ) -> tuple[list[MatchResult], list[Transaction]]:
        """Phase 3: Fuzzy matching by amount + date + payee similarity."""
        matches = []
        matched_indices: set[int] = set()
        n = len(transactions)

        for i in range(n):
            if i in matched_indices:
                continue
            for j in range(i + 1, n):
                if j in matched_indices:
                    continue
                tx_a, tx_b = transactions[i], transactions[j]

                # Must be from different sources
                if tx_a.source_account == tx_b.source_account:
                    continue

                # Amount must match exactly (absolute value)
                if abs(tx_a.amount) != abs(tx_b.amount):
                    continue
                if tx_a.currency != tx_b.currency:
                    continue

                # Date within tolerance
                date_diff = abs(tx_a.date - tx_b.date)
                if date_diff > self.date_tolerance:
                    continue

                # Payee similarity
                payee_a = f"{tx_a.payee} {tx_a.narration}"
                payee_b = f"{tx_b.payee} {tx_b.narration}"
                similarity = fuzz.token_sort_ratio(payee_a, payee_b) / 100.0

                if similarity >= self.fuzzy_threshold:
                    matches.append(
                        MatchResult(
                            tx_a=tx_a,
                            tx_b=tx_b,
                            match_type="fuzzy",
                            confidence=similarity,
                        )
                    )
                    matched_indices.add(i)
                    matched_indices.add(j)
                    break

        remaining = [tx for i, tx in enumerate(transactions) if i not in matched_indices]
        return matches, remaining
