"""Alipay (支付宝) CSV importer."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation

from preciouss.importers.base import CsvImporter, Transaction
from preciouss.importers.clearing import detect_merchant_clearing, resolve_payment_to_clearing


class AlipayImporter(CsvImporter):
    """Import transactions from Alipay CSV exports.

    Alipay CSV format (after header lines):
    - 交易号, 商家订单号, 交易创建时间, 付款时间, 最近修改时间, 交易来源地,
      类型, 交易对方, 商品名称, 金额（元）, 收/支, 交易状态, 服务费（元）,
      成功退款（元）, 备注, 资金状态

    The CSV typically has several metadata lines before the actual header.
    """

    skip_lines = 3  # Alipay adds 3 metadata lines before the CSV header row
    expected_headers = ["支付宝交易记录"]
    tab_delimited = True

    def __init__(self, account: str = "Assets:Alipay", currency: str = "CNY"):
        self._account = account
        self._currency = currency

    def account_name(self) -> str:
        return self._account

    def identify(self, filepath) -> bool:
        """Alipay CSVs have '支付宝交易记录' in the first line."""
        from pathlib import Path

        filepath = Path(filepath)
        if filepath.suffix.lower() != ".csv":
            return False
        try:
            content = self._read_file(filepath)
            # Only match header area (first 3 lines), not data rows
            first_lines = "\n".join(content.split("\n")[:3])
            return "支付宝交易记录" in first_lines
        except Exception:
            return False

    def _parse_row(self, row: dict[str, str]) -> Transaction | None:
        """Parse a single Alipay CSV row."""
        # Skip empty rows or rows without essential fields
        trade_no = row.get("交易号", "").strip()
        if not trade_no or trade_no == "交易号":
            return None

        # Parse transaction status - skip non-completed transactions
        status = row.get("交易状态", "").strip()
        if status not in ("交易成功", "退款成功", "还款成功"):
            return None

        # Parse amount
        amount_str = row.get("金额（元）", row.get("金额(元)", "0")).strip()
        try:
            amount = Decimal(amount_str)
        except InvalidOperation:
            return None

        # Determine direction (income/expense)
        direction = row.get("收/支", "").strip()
        if direction == "支出":
            amount = -abs(amount)
            tx_type = "expense"
        elif direction == "收入":
            amount = abs(amount)
            tx_type = "income"
        elif direction == "不计收支":
            tx_type = "transfer"
        else:
            tx_type = "other"

        # Parse date
        date_str = row.get("付款时间", row.get("交易创建时间", "")).strip()
        try:
            date = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
        except (ValueError, TypeError):
            try:
                date = datetime.strptime(date_str, "%Y/%m/%d %H:%M:%S")
            except (ValueError, TypeError):
                return None

        payee = row.get("交易对方", "").strip()
        narration = row.get("商品名称", "").strip()
        merchant_order = row.get("商家订单号", "").strip()

        # Extract payment method from 资金状态 or other fields
        payment_method = row.get("资金状态", "").strip()
        if not payment_method:
            payment_method = row.get("交易来源地", "").strip()

        # Resolve payment account via clearing
        if payment_method and payment_method not in ("", "/"):
            resolved_account = resolve_payment_to_clearing(payment_method, "Alipay")
        else:
            resolved_account = "Assets:Clearing:Alipay:Unknown"

        # Detect known merchants → counter_account (clearing)
        counter_account = detect_merchant_clearing("Alipay", payee, narration)

        return Transaction(
            date=date,
            amount=amount,
            currency=self._currency,
            payee=payee,
            narration=narration,
            source_account=resolved_account,
            payment_method=payment_method if payment_method else None,
            reference_id=trade_no.strip(),
            counterpart_ref=merchant_order if merchant_order else None,
            raw_category=row.get("类型", "").strip() or None,
            tx_type=tx_type,
            counter_account=counter_account,
            metadata={
                "alipay_status": status,
                "source": row.get("交易来源地", "").strip(),
            },
        )
