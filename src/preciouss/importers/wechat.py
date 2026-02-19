"""WeChat Pay (微信支付) CSV/XLSX importer."""

from __future__ import annotations

import csv
import io
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from preciouss.importers.base import CsvImporter, Transaction
from preciouss.importers.resolve import resolve_payment_account


class WechatImporter(CsvImporter):
    """Import transactions from WeChat Pay CSV or XLSX exports.

    WeChat Pay format (after metadata lines):
    交易时间, 交易类型, 交易对方, 商品, 收/支, 金额(元), 支付方式, 当前状态,
    交易单号, 商户单号, 备注

    Notes:
    - Amounts have ¥ prefix
    - 交易单号 and 商户单号 may have trailing tabs
    - 支付方式 contains bank card info like "招商银行(0913)"
    - Supports both .csv and .xlsx files (same column structure)
    """

    expected_headers = ["微信支付账单明细"]

    def __init__(self, account: str = "Assets:WeChat", currency: str = "CNY"):
        self._account = account
        self._currency = currency

    def account_name(self) -> str:
        return self._account

    def identify(self, filepath) -> bool:
        filepath = Path(filepath)
        suffix = filepath.suffix.lower()
        if suffix == ".csv":
            return self._identify_csv(filepath)
        elif suffix == ".xlsx":
            return self._identify_xlsx(filepath)
        return False

    def extract(self, filepath) -> list[Transaction]:
        filepath = Path(filepath)
        suffix = filepath.suffix.lower()
        if suffix == ".csv":
            return self._extract_csv(filepath)
        elif suffix == ".xlsx":
            return self._extract_xlsx(filepath)
        return []

    # --- CSV methods ---

    def _identify_csv(self, filepath: Path) -> bool:
        try:
            content = self._read_file(filepath)
            first_line = content.split("\n")[0]
            return "微信支付账单明细" in first_line
        except Exception:
            return False

    def _extract_csv(self, filepath: Path) -> list[Transaction]:
        """Extract transactions from CSV, finding header dynamically."""
        content = self._read_file(filepath)
        lines = content.split("\n")

        # Find the header line containing "交易时间"
        header_idx = None
        for i, line in enumerate(lines):
            if line.startswith("交易时间,"):
                header_idx = i
                break

        if header_idx is None:
            return []

        csv_lines = lines[header_idx:]
        csv_content = "\n".join(csv_lines)

        reader = csv.DictReader(io.StringIO(csv_content))
        transactions = []
        for row in reader:
            row = {k.strip(): v.strip() if v else "" for k, v in row.items() if k}
            tx = self._parse_row(row)
            if tx is not None:
                transactions.append(tx)

        return transactions

    # --- XLSX methods ---

    def _identify_xlsx(self, filepath: Path) -> bool:
        try:
            from openpyxl import load_workbook
        except ImportError:
            return False

        try:
            wb = load_workbook(filepath, read_only=True, data_only=True)
            ws = wb.active
            # Check first row first cell for "微信支付"
            for row in ws.iter_rows(max_row=1, max_col=1, values_only=True):
                val = str(row[0]) if row[0] is not None else ""
                wb.close()
                return "微信支付" in val
            wb.close()
            return False
        except Exception:
            return False

    def _extract_xlsx(self, filepath: Path) -> list[Transaction]:
        try:
            from openpyxl import load_workbook
        except ImportError as e:
            raise ImportError(
                "openpyxl is required for xlsx support. Install it with: uv add openpyxl"
            ) from e

        wb = load_workbook(filepath, read_only=True, data_only=True)
        ws = wb.active

        headers = None
        transactions = []

        for row in ws.iter_rows(values_only=True):
            # Convert all cells to strings
            cells = [str(c).strip() if c is not None else "" for c in row]

            # Find header row
            if headers is None:
                if cells and cells[0] == "交易时间":
                    headers = cells
                continue

            # Build dict from row using headers
            if len(cells) < len(headers):
                continue
            row_dict = {headers[i]: cells[i] for i in range(len(headers))}
            tx = self._parse_row(row_dict)
            if tx is not None:
                transactions.append(tx)

        wb.close()
        return transactions

    # --- Shared parsing ---

    def _parse_row(self, row: dict[str, str]) -> Transaction | None:
        # Parse date
        date_str = row.get("交易时间", "").strip()
        if not date_str:
            return None

        try:
            date = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None

        # Parse status - skip non-completed transactions
        status = row.get("当前状态", "").strip()
        if status not in ("支付成功", "已转账", "已存入零钱", "已收钱", "已退款", "朋友已收钱"):
            return None

        # Parse amount - remove ¥ prefix
        amount_str = row.get("金额(元)", "").strip()
        amount_str = amount_str.replace("¥", "").replace(",", "").strip()
        try:
            amount = Decimal(amount_str)
        except (InvalidOperation, ValueError):
            return None

        # Direction
        direction = row.get("收/支", "").strip()
        if direction == "支出":
            amount = -abs(amount)
            tx_type = "expense"
        elif direction == "收入":
            amount = abs(amount)
            tx_type = "income"
        elif direction == "/":
            tx_type = "transfer"
        else:
            tx_type = "other"

        payee = row.get("交易对方", "").strip()
        narration = row.get("商品", "").strip().strip('"')
        payment_method = row.get("支付方式", "").strip()
        trade_no = row.get("交易单号", "").strip().strip("\t")
        merchant_no = row.get("商户单号", "").strip().strip("\t")
        tx_type_raw = row.get("交易类型", "").strip()

        # Resolve payment account
        if payment_method and payment_method != "/":
            resolved_account = resolve_payment_account(payment_method, f"{self._account}:Unknown")
        else:
            resolved_account = self._account

        return Transaction(
            date=date,
            amount=amount,
            currency=self._currency,
            payee=payee,
            narration=narration,
            source_account=resolved_account,
            payment_method=payment_method if payment_method and payment_method != "/" else None,
            reference_id=trade_no if trade_no and trade_no != "/" else None,
            counterpart_ref=merchant_no if merchant_no and merchant_no != "/" else None,
            raw_category=tx_type_raw or None,
            tx_type=tx_type,
            metadata={
                "wechat_status": status,
                "wechat_type": tx_type_raw,
            },
        )
