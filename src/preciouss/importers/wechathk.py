"""WeChat Pay HK (微信支付香港) JSON importer."""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from preciouss.importers.base import PrecioussImporter, Transaction
from preciouss.importers.clearing import detect_merchant_clearing


def _parse_foreign_price(foreign_price: str) -> tuple[Decimal, str] | None:
    """Parse '￥25.00' → (Decimal('25.00'), 'CNY'). Returns None if unrecognized."""
    s = foreign_price.strip()
    if s.startswith("￥") or s.startswith("¥"):
        try:
            return Decimal(s[1:]), "CNY"
        except Exception:
            return None
    return None


class WechatHKImporter(PrecioussImporter):
    """Import transactions from WeChat Pay HK JSON exports.

    WeChat Pay HK exports transaction data as a JSON array. Each record contains:
    - amount_in_cent: Amount in HKD cents
    - currency_code: Always "HK$"
    - datetime: Unix timestamp
    - merchant: Merchant name
    - description / product_desc: Transaction description
    - payrecord_id: Unique payment record ID
    - out_trade_no: Merchant order number
    - foreign_price / foreign_rate: Original currency info (mostly CNY)
    - pay_state: 0=success, 9=refund, 7=pending
    """

    def __init__(self, account: str = "Assets:WeChatHK", currency: str = "HKD"):
        self._account = account
        self._currency = currency

    def account_name(self) -> str:
        return self._account

    def identify(self, filepath) -> bool:
        filepath = Path(filepath)
        if filepath.suffix.lower() != ".json":
            return False
        try:
            with open(filepath, encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, list) or not data:
                return False
            first = data[0]
            return isinstance(first, dict) and "currency_code" in first and "payrecord_id" in first
        except Exception:
            return False

    def extract(self, filepath) -> list[Transaction]:
        filepath = Path(filepath)
        with open(filepath, encoding="utf-8") as f:
            data = json.load(f)

        transactions = []
        for record in data:
            tx = self._parse_record(record)
            if tx is not None:
                transactions.append(tx)
        return transactions

    def _parse_record(self, record: dict) -> Transaction | None:
        # Only process successful payments and refunds
        pay_state = record.get("pay_state", "")
        if pay_state not in ("0", "9"):
            return None

        # Parse date from unix timestamp
        ts = record.get("datetime", "")
        if not ts:
            return None
        try:
            date = datetime.fromtimestamp(int(ts))
        except (ValueError, OSError):
            return None

        # Parse amount (stored in cents)
        amount_str = record.get("amount_in_cent", "0")
        try:
            amount = Decimal(amount_str) / 100
        except Exception:
            return None

        # Determine direction
        is_refund = pay_state == "9"
        if is_refund:
            tx_type = "income"
            # Refund: money comes back, positive amount
        else:
            tx_type = "expense"
            amount = -amount

        # Merchant and description
        merchant = record.get("merchant", "").strip()
        description = record.get("description", "").strip()
        product_desc = record.get("product_desc", "").strip()
        # Prefer description, fall back to product_desc
        narration = description if description else product_desc

        # Payment method
        instrument = record.get("instrument", "")
        card_tail = record.get("card_tail", "")
        bank_name_raw = record.get("bank_name", "")
        # Extract card brand from bank_name (e.g., "Mastercard|1863|")
        card_brand = bank_name_raw.split("|")[0] if bank_name_raw else ""
        payment_method = f"{card_brand}({card_tail})" if card_brand and card_tail else instrument

        # Reference IDs
        payrecord_id = record.get("payrecord_id", "").strip()
        out_trade_no = record.get("out_trade_no", "").strip()

        # Foreign currency info
        foreign_price = record.get("foreign_price", "").strip()
        foreign_rate = record.get("foreign_rate", "").strip()

        metadata: dict = {}
        parsed = _parse_foreign_price(foreign_price) if foreign_price else None
        if parsed:
            foreign_amount, foreign_currency = parsed
            metadata["wechathk_foreign_amount"] = str(foreign_amount)
            metadata["wechathk_foreign_currency"] = foreign_currency
        if foreign_rate:
            metadata["foreign_rate"] = foreign_rate
        if is_refund:
            metadata["wechathk_refund"] = "true"

        # Detect known merchants → counter_account (clearing)
        counter_account = detect_merchant_clearing("WeChatHK", merchant, narration)

        return Transaction(
            date=date,
            amount=amount,
            currency=self._currency,
            payee=merchant,
            narration=narration,
            source_account=self._account,
            payment_method=payment_method if payment_method else None,
            reference_id=payrecord_id if payrecord_id else None,
            counterpart_ref=out_trade_no if out_trade_no else None,
            tx_type=tx_type,
            counter_account=counter_account,
            metadata=metadata,
        )
