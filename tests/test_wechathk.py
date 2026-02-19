"""Tests for WeChat Pay HK JSON importer."""

from datetime import datetime
from decimal import Decimal
from pathlib import Path

from preciouss.importers.wechathk import WechatHKImporter

FIXTURES = Path(__file__).parent / "fixtures"


class TestIdentify:
    def test_identify_json(self):
        importer = WechatHKImporter()
        assert importer.identify(FIXTURES / "wechathk_sample.json")

    def test_identify_rejects_csv(self):
        importer = WechatHKImporter()
        assert not importer.identify(FIXTURES / "wechat_sample.csv")

    def test_identify_rejects_non_wechathk_json(self, tmp_path):
        f = tmp_path / "other.json"
        f.write_text('[{"foo": "bar"}]', encoding="utf-8")
        importer = WechatHKImporter()
        assert not importer.identify(f)

    def test_identify_rejects_empty_json(self, tmp_path):
        f = tmp_path / "empty.json"
        f.write_text("[]", encoding="utf-8")
        importer = WechatHKImporter()
        assert not importer.identify(f)


class TestExtract:
    def test_extract_count(self):
        """Should extract 4 records: 3 pay_state=0 + 1 pay_state=9, skip pay_state=7."""
        importer = WechatHKImporter()
        txns = importer.extract(FIXTURES / "wechathk_sample.json")
        assert len(txns) == 4

    def test_extract_cny_payment(self):
        """CNY payment settled in HKD (Manner Coffee)."""
        importer = WechatHKImporter()
        txns = importer.extract(FIXTURES / "wechathk_sample.json")
        tx = txns[0]
        assert tx.payee == "Manner Coffee"
        assert tx.narration == "点餐-深圳天安云谷店"
        assert tx.amount == Decimal("-27.18")
        assert tx.currency == "HKD"
        assert tx.tx_type == "expense"
        assert tx.reference_id == "4200002700202505129525209429"
        assert tx.payment_method == "Mastercard(1863)"
        assert tx.metadata["wechathk_foreign_amount"] == "25.00"
        assert tx.metadata["wechathk_foreign_currency"] == "CNY"
        assert tx.metadata["foreign_rate"] == "1CNY=1.08719HKD"

    def test_extract_native_hkd_payment(self):
        """Native HKD payment (Hutchison Telephone)."""
        importer = WechatHKImporter()
        txns = importer.extract(FIXTURES / "wechathk_sample.json")
        tx = txns[1]
        assert tx.payee == "Hutchison Telephone Company Limited"
        assert tx.amount == Decimal("-48.00")
        assert tx.currency == "HKD"
        assert tx.tx_type == "expense"
        # Native HKD has no foreign currency metadata
        assert "wechathk_foreign_amount" not in tx.metadata
        assert "foreign_rate" not in tx.metadata

    def test_extract_refund(self):
        """Refund (pay_state=9) should have positive amount."""
        importer = WechatHKImporter()
        txns = importer.extract(FIXTURES / "wechathk_sample.json")
        tx = txns[2]
        assert tx.payee == "WeChat利是"
        assert tx.amount == Decimal("99.00")
        assert tx.tx_type == "income"
        assert tx.metadata.get("wechathk_refund") == "true"

    def test_extract_skips_pending(self):
        """pay_state=7 should be skipped."""
        importer = WechatHKImporter()
        txns = importer.extract(FIXTURES / "wechathk_sample.json")
        # pay_state=7 record (WeChat利是 with pay_state=7) should NOT appear
        payees = [tx.payee for tx in txns]
        # WeChat利是 appears once (the refund), not twice
        assert payees.count("WeChat利是") == 1

    def test_extract_large_amount(self):
        """Costco payment with large amount."""
        importer = WechatHKImporter()
        txns = importer.extract(FIXTURES / "wechathk_sample.json")
        tx = txns[3]
        assert tx.payee == "Costco开市客"
        assert tx.amount == Decimal("-618.26")
        assert tx.counterpart_ref == "1016661903"

    def test_costco_merchant_clearing(self):
        """Costco payee should route to Costco clearing account."""
        importer = WechatHKImporter()
        txns = importer.extract(FIXTURES / "wechathk_sample.json")
        tx = txns[3]  # Costco开市客
        assert tx.counter_account == "Assets:Clearing:Costco"

    def test_non_merchant_no_clearing(self):
        """Non-merchant payee should have no counter_account."""
        importer = WechatHKImporter()
        txns = importer.extract(FIXTURES / "wechathk_sample.json")
        tx = txns[0]  # Manner Coffee
        assert tx.counter_account is None


class TestAccountName:
    def test_default_account(self):
        importer = WechatHKImporter()
        assert importer.account_name() == "Assets:WeChatHK"

    def test_custom_account(self):
        importer = WechatHKImporter(account="Assets:WeChatHK", currency="HKD")
        assert importer.account_name() == "Assets:WeChatHK"


class TestBeancountValidation:
    def test_cross_currency_validates(self, tmp_path):
        """Cross-currency WechatHK transaction passes beancount validation."""
        from beancount.loader import load_string

        from preciouss.importers.base import Transaction
        from preciouss.ledger.writer import init_ledger, write_transactions

        ledger_dir = tmp_path / "ledger"
        init_ledger(ledger_dir)

        tx = Transaction(
            date=datetime(2026, 5, 12, 0, 0, 0),
            amount=Decimal("-27.18"),
            currency="HKD",
            payee="Manner Coffee",
            narration="点餐-深圳天安云谷店",
            source_account="Assets:WeChatHK",
            reference_id="4200002700202505129525209429",
            payment_method="Mastercard(1863)",
            tx_type="expense",
            metadata={
                "wechathk_foreign_amount": "25.00",
                "wechathk_foreign_currency": "CNY",
                "foreign_rate": "1CNY=1.08719HKD",
            },
        )

        write_transactions([tx], ledger_dir / "importers" / "wechathk.bean")

        parts = []
        for name in ["main.bean", "commodities.bean", "accounts.bean"]:
            parts.append((ledger_dir / name).read_text(encoding="utf-8"))
        parts.append((ledger_dir / "importers" / "wechathk.bean").read_text(encoding="utf-8"))

        combined = "\n".join(parts)
        combined = "\n".join(
            line for line in combined.splitlines() if not line.startswith("include ")
        )

        _, errors, _ = load_string(combined)
        assert errors == [], f"Beancount validation errors: {errors}"

    def test_cross_currency_refund_validates(self, tmp_path):
        """Cross-currency refund (positive amount) passes beancount validation."""
        from beancount.loader import load_string

        from preciouss.importers.base import Transaction
        from preciouss.ledger.writer import init_ledger, write_transactions

        ledger_dir = tmp_path / "ledger"
        init_ledger(ledger_dir)

        tx = Transaction(
            date=datetime(2024, 5, 19, 0, 0, 0),
            amount=Decimal("84.74"),
            currency="HKD",
            payee="中铁网络",
            narration="12306消费",
            source_account="Assets:WeChatHK",
            reference_id="1020023200020110202405195800188745330",
            payment_method="Mastercard(1863)",
            tx_type="income",
            metadata={
                "wechathk_foreign_amount": "78.00",
                "wechathk_foreign_currency": "CNY",
                "wechathk_refund": "true",
            },
        )

        write_transactions([tx], ledger_dir / "importers" / "wechathk.bean")

        parts = []
        for name in ["main.bean", "commodities.bean", "accounts.bean"]:
            parts.append((ledger_dir / name).read_text(encoding="utf-8"))
        parts.append((ledger_dir / "importers" / "wechathk.bean").read_text(encoding="utf-8"))

        combined = "\n".join(parts)
        combined = "\n".join(
            line for line in combined.splitlines() if not line.startswith("include ")
        )

        _, errors, _ = load_string(combined)
        assert errors == [], f"Beancount validation errors: {errors}"
