"""Tests for ALDI JSON importer."""

from datetime import datetime
from decimal import Decimal
from pathlib import Path

from beancount.loader import load_string

from preciouss.importers.aldi import AldiImporter, AldiItemCategorizer
from preciouss.importers.base import Transaction
from preciouss.ledger.writer import (
    group_items_by_category,
    init_ledger,
    multiposting_transaction_to_bean,
    write_transactions,
)

FIXTURES = Path(__file__).parent / "fixtures"


# --- Identify ---


class TestIdentify:
    def test_identify_aldi_json(self):
        importer = AldiImporter()
        assert importer.identify(FIXTURES / "aldi_sample.json")

    def test_identify_rejects_csv(self):
        importer = AldiImporter()
        # Any CSV file should be rejected
        csv_files = list(FIXTURES.glob("*.csv"))
        if csv_files:
            assert not importer.identify(csv_files[0])

    def test_identify_rejects_non_aldi_json(self, tmp_path):
        f = tmp_path / "other.json"
        f.write_text('[{"foo": "bar"}]', encoding="utf-8")
        importer = AldiImporter()
        assert not importer.identify(f)

    def test_identify_rejects_wechathk_json(self):
        """Should not match WeChat HK JSON format."""
        importer = AldiImporter()
        wechathk = FIXTURES / "wechathk_sample.json"
        if wechathk.exists():
            assert not importer.identify(wechathk)

    def test_identify_rejects_empty_json(self, tmp_path):
        f = tmp_path / "empty.json"
        f.write_text('{"orders": []}', encoding="utf-8")
        importer = AldiImporter()
        assert not importer.identify(f)

    def test_identify_rejects_non_aldi_store(self, tmp_path):
        """Orders JSON with non-ALDI store should be rejected."""
        f = tmp_path / "other_store.json"
        f.write_text(
            '{"orders": [{"orderCode": "123", "store": "Walmart"}]}',
            encoding="utf-8",
        )
        importer = AldiImporter()
        assert not importer.identify(f)


# --- Extract ---


class TestExtract:
    def test_extract_order_count(self):
        importer = AldiImporter()
        txns = importer.extract(FIXTURES / "aldi_sample.json")
        assert len(txns) == 3

    def test_extract_items(self):
        """First order should have correct item details."""
        importer = AldiImporter()
        txns = importer.extract(FIXTURES / "aldi_sample.json")
        tx = txns[0]  # Order 260118463558598993
        items = tx.metadata["aldi_items"]
        assert len(items) == 8
        assert items[0]["name"] == "有机开口大板栗 一份"
        assert items[0]["num"] == 1
        assert items[0]["price"] == "17.9"

    def test_extract_amount(self):
        """Amount should be negative paymentAmount."""
        importer = AldiImporter()
        txns = importer.extract(FIXTURES / "aldi_sample.json")
        assert txns[0].amount == Decimal("-85.7")
        assert txns[1].amount == Decimal("-46.1")
        assert txns[2].amount == Decimal("-48.3")

    def test_extract_payee_and_narration(self):
        importer = AldiImporter()
        txns = importer.extract(FIXTURES / "aldi_sample.json")
        assert txns[0].payee == "ALDI奥乐齐"
        assert txns[0].narration == "ALDI奥乐齐(苏州环宇荟店)"

    def test_source_account_is_clearing(self):
        """Initial source_account should be Assets:Clearing:ALDI."""
        importer = AldiImporter()
        txns = importer.extract(FIXTURES / "aldi_sample.json")
        for tx in txns:
            assert tx.source_account == "Assets:Clearing:ALDI"

    def test_reference_id(self):
        importer = AldiImporter()
        txns = importer.extract(FIXTURES / "aldi_sample.json")
        assert txns[0].reference_id == "260118463558598993"

    def test_discount_metadata(self):
        """Order with promotion should have discount in metadata."""
        importer = AldiImporter()
        txns = importer.extract(FIXTURES / "aldi_sample.json")
        # Third order (251208871732177993) has promotionAmount=9.9
        tx = txns[2]
        assert tx.metadata["aldi_discount"] == "9.9"

    def test_no_discount_metadata_when_zero(self):
        """Order without promotion should not have discount in metadata."""
        importer = AldiImporter()
        txns = importer.extract(FIXTURES / "aldi_sample.json")
        assert "aldi_discount" not in txns[0].metadata

    def test_channel_metadata(self):
        importer = AldiImporter()
        txns = importer.extract(FIXTURES / "aldi_sample.json")
        assert txns[0].metadata["aldi_channel"] == "线上"
        assert txns[1].metadata["aldi_channel"] == "门店"

    def test_skips_incomplete_orders(self, tmp_path):
        """Orders with non-completed status should be skipped."""
        f = tmp_path / "incomplete.json"
        f.write_text(
            '{"orders": [{"orderCode": "123", "store": "ALDI奥乐齐(test)",'
            '"date": "2026-01-01", "time": "10:00", "paymentAmount": 10.0,'
            '"productAmount": 10.0, "promotionAmount": 0, "channel": "门店",'
            '"products": [{"name": "test", "num": 1, "price": 10.0}],'
            '"orderStatusName": "已取消"}]}',
            encoding="utf-8",
        )
        importer = AldiImporter()
        txns = importer.extract(f)
        assert len(txns) == 0

    def test_total_verification(self):
        """sum(item prices) should match productAmount for no-discount orders."""
        importer = AldiImporter()
        txns = importer.extract(FIXTURES / "aldi_sample.json")
        # Second order: no discount, productAmount == paymentAmount == 46.1
        tx = txns[1]
        items = tx.metadata["aldi_items"]
        item_total = sum(Decimal(item["price"]) * item["num"] for item in items)
        assert item_total == Decimal("46.1")


# --- Item Categorizer ---


class TestItemCategorizer:
    def test_grocery_items(self):
        cat = AldiItemCategorizer()
        assert cat.categorize("有机开口大板栗 一份") == "Expenses:Food:Grocery"
        assert cat.categorize("悠白零乳糖牛奶450毫升*2") == "Expenses:Food:Grocery"
        assert cat.categorize("超值 秘鲁蓝莓(果径18mm) 500g") == "Expenses:Food:Grocery"
        assert cat.categorize("传统乡村法棍") == "Expenses:Food:Grocery"
        assert cat.categorize("野生鲅鱼水饺480g") == "Expenses:Food:Grocery"

    def test_daily_goods(self):
        cat = AldiItemCategorizer()
        assert cat.categorize("超值 清新护齿牙膏 150g") == "Expenses:Shopping:DailyGoods"
        assert cat.categorize("LACURA 檀香木护手霜 75g") == "Expenses:Shopping:DailyGoods"
        assert cat.categorize("ALDI HOME 75%酒精卫生湿巾 80片") == "Expenses:Shopping:DailyGoods"
        assert cat.categorize("ALDI HOME 蒸笼纸 30张") == "Expenses:Shopping:DailyGoods"
        assert cat.categorize("超值 夜安裤L 2片") == "Expenses:Shopping:DailyGoods"

    def test_restaurant(self):
        cat = AldiItemCategorizer()
        assert cat.categorize("奥小辣烤鸡腿") == "Expenses:Food:Restaurant"
        assert cat.categorize("安格斯芝士牛肉卷") == "Expenses:Food:Restaurant"
        assert cat.categorize("关东煮串串组合 370g") == "Expenses:Food:Restaurant"

    def test_clothing(self):
        cat = AldiItemCategorizer()
        assert cat.categorize("ALDI男士棉拖鞋") == "Expenses:Shopping:Clothing"

    def test_default_category(self):
        """Unknown items should default to Grocery."""
        cat = AldiItemCategorizer()
        assert cat.categorize("某种未知商品XYZ") == "Expenses:Food:Grocery"


# --- Multiposting Writer ---


class TestMultiposting:
    def _make_aldi_tx(self):
        return Transaction(
            date=datetime(2026, 1, 18, 11, 10),
            amount=Decimal("-85.70"),
            currency="CNY",
            payee="ALDI奥乐齐",
            narration="ALDI奥乐齐(苏州环宇荟店)",
            source_account="Assets:WeChat",
            reference_id="260118463558598993",
            tx_type="expense",
            metadata={
                "aldi_items": [
                    {
                        "name": "板栗",
                        "num": 1,
                        "price": "17.9",
                        "category": "Expenses:Food:Grocery",
                    },
                    {
                        "name": "牛奶",
                        "num": 1,
                        "price": "14.9",
                        "category": "Expenses:Food:Grocery",
                    },
                    {
                        "name": "湿巾",
                        "num": 1,
                        "price": "16.8",
                        "category": "Expenses:Shopping:DailyGoods",
                    },
                    {
                        "name": "烤鸡腿",
                        "num": 1,
                        "price": "9.9",
                        "category": "Expenses:Food:Restaurant",
                    },
                    {
                        "name": "纯净水",
                        "num": 1,
                        "price": "5.9",
                        "category": "Expenses:Food:Grocery",
                    },
                ],
                "aldi_channel": "线上",
            },
        )

    def test_group_items_by_category(self):
        items = [
            {"name": "a", "num": 1, "price": "10.0", "category": "Expenses:Food:Grocery"},
            {"name": "b", "num": 1, "price": "5.0", "category": "Expenses:Shopping:DailyGoods"},
            {"name": "c", "num": 2, "price": "3.0", "category": "Expenses:Food:Grocery"},
        ]
        # listed_total = 21.0; total_payment = 21.0 → scale = 1.0, amounts unchanged
        result = group_items_by_category(items, Decimal("21.0"))
        assert len(result) == 2
        # Sorted by account name; each entry is (account, total, items_list)
        assert result[0][0] == "Expenses:Food:Grocery"
        assert result[0][1] == Decimal("16.0")
        assert len(result[0][2]) == 2  # items a and c
        assert result[1][0] == "Expenses:Shopping:DailyGoods"
        assert result[1][1] == Decimal("5.0")
        assert len(result[1][2]) == 1  # item b

    def test_multiposting_output(self):
        tx = self._make_aldi_tx()
        by_category = group_items_by_category(tx.metadata["aldi_items"], Decimal("85.70"))
        bean_tx = multiposting_transaction_to_bean(tx, by_category)

        assert bean_tx.payee == "ALDI奥乐齐"
        # 1 source + 3 categories
        assert len(bean_tx.postings) == 4
        # Source posting
        assert bean_tx.postings[0].account == "Assets:WeChat"
        assert bean_tx.postings[0].units.number == Decimal("-85.70")
        # Expense postings (sorted by account)
        accounts = [p.account for p in bean_tx.postings[1:]]
        assert "Expenses:Food:Grocery" in accounts
        assert "Expenses:Food:Restaurant" in accounts
        assert "Expenses:Shopping:DailyGoods" in accounts

    def test_multiposting_balances(self):
        """Sum of all postings should be zero."""
        tx = self._make_aldi_tx()
        by_category = group_items_by_category(tx.metadata["aldi_items"], Decimal("85.70"))
        bean_tx = multiposting_transaction_to_bean(tx, by_category)

        total = sum(p.units.number for p in bean_tx.postings)
        assert total == Decimal("0")

    def test_multiposting_with_discount_adjustment(self):
        """When paymentAmount != sum(items), adjustment keeps balance."""
        tx = Transaction(
            date=datetime(2025, 12, 8, 19, 0),
            amount=Decimal("-48.3"),
            currency="CNY",
            payee="ALDI奥乐齐",
            narration="ALDI奥乐齐(长宁缤谷店)",
            source_account="Assets:Unknown",
            reference_id="251208871732177993",
            tx_type="expense",
            metadata={
                "aldi_items": [
                    {
                        "name": "护手霜",
                        "num": 1,
                        "price": "14.9",
                        "category": "Expenses:Shopping:DailyGoods",
                    },
                    {
                        "name": "护唇膏",
                        "num": 1,
                        "price": "12.9",
                        "category": "Expenses:Shopping:DailyGoods",
                    },
                    {
                        "name": "洗手液",
                        "num": 1,
                        "price": "9.9",
                        "category": "Expenses:Shopping:DailyGoods",
                    },
                    {"name": "酸奶", "num": 1, "price": "5.9", "category": "Expenses:Food:Grocery"},
                    {"name": "香菇", "num": 1, "price": "4.7", "category": "Expenses:Food:Grocery"},
                ],
                "aldi_channel": "门店",
                "aldi_discount": "9.9",
            },
        )
        # item_total = 48.3, but paymentAmount = 48.3 and productAmount = 58.2
        # In this case items sum to 48.3 which equals paymentAmount
        # The real test: when items sum != paymentAmount
        tx.metadata["aldi_items"][0]["price"] = "20.0"  # make items sum to 53.4
        by_category = group_items_by_category(tx.metadata["aldi_items"], Decimal("48.3"))
        bean_tx = multiposting_transaction_to_bean(tx, by_category)

        total = sum(p.units.number for p in bean_tx.postings)
        assert total == Decimal("0")

    def test_write_transactions_multiposting(self, tmp_path):
        """write_transactions() correctly dispatches ALDI transactions."""
        tx = self._make_aldi_tx()
        output = tmp_path / "aldi.bean"
        write_transactions([tx], output)

        content = output.read_text(encoding="utf-8")
        assert "ALDI奥乐齐" in content
        assert "Assets:WeChat" in content
        assert "Expenses:Food:Grocery" in content
        assert "-85.70 CNY" in content

    def test_posting_items_metadata(self):
        """Expense postings should have items metadata with formatted item details."""
        tx = self._make_aldi_tx()
        by_category = group_items_by_category(tx.metadata["aldi_items"], Decimal("85.70"))
        bean_tx = multiposting_transaction_to_bean(tx, by_category)

        # Check expense postings (skip source posting at index 0)
        for posting in bean_tx.postings[1:]:
            assert "items" in posting.meta
            assert isinstance(posting.meta["items"], str)

        # Find the Grocery posting and verify item names
        grocery_posting = next(p for p in bean_tx.postings if p.account == "Expenses:Food:Grocery")
        items_str = grocery_posting.meta["items"]
        assert "板栗 x1" in items_str
        assert "牛奶 x1" in items_str
        assert "纯净水 x1" in items_str

        # Restaurant posting
        restaurant_posting = next(
            p for p in bean_tx.postings if p.account == "Expenses:Food:Restaurant"
        )
        assert "烤鸡腿 x1 ¥9.9" in restaurant_posting.meta["items"]

    def test_items_metadata_in_bean_output(self, tmp_path):
        """Generated .bean file should contain items metadata lines."""
        tx = self._make_aldi_tx()
        output = tmp_path / "aldi.bean"
        write_transactions([tx], output)

        content = output.read_text(encoding="utf-8")
        assert 'items: "' in content
        assert "板栗 x1" in content
        assert "湿巾 x1" in content


# --- Beancount Validation ---


class TestBeancountValidation:
    def test_beancount_validates(self, tmp_path):
        """Generated multiposting ledger passes beancount validation."""
        ledger_dir = tmp_path / "ledger"
        init_ledger(ledger_dir)

        tx = Transaction(
            date=datetime(2026, 1, 18, 11, 10),
            amount=Decimal("-85.70"),
            currency="CNY",
            payee="ALDI奥乐齐",
            narration="ALDI奥乐齐(苏州环宇荟店)",
            source_account="Assets:Clearing:ALDI",
            reference_id="260118463558598993",
            tx_type="expense",
            metadata={
                "aldi_items": [
                    {
                        "name": "板栗",
                        "num": 1,
                        "price": "17.9",
                        "category": "Expenses:Food:Grocery",
                    },
                    {
                        "name": "牛奶",
                        "num": 1,
                        "price": "14.9",
                        "category": "Expenses:Food:Grocery",
                    },
                    {
                        "name": "湿巾",
                        "num": 1,
                        "price": "16.8",
                        "category": "Expenses:Shopping:DailyGoods",
                    },
                    {
                        "name": "烤鸡腿",
                        "num": 1,
                        "price": "9.9",
                        "category": "Expenses:Food:Restaurant",
                    },
                    {
                        "name": "纯净水",
                        "num": 1,
                        "price": "5.9",
                        "category": "Expenses:Food:Grocery",
                    },
                ],
                "aldi_channel": "线上",
            },
        )

        write_transactions([tx], ledger_dir / "importers" / "aldi.bean")

        # Combine all files like beancount would
        parts = []
        for name in ["main.bean", "commodities.bean", "accounts.bean"]:
            parts.append((ledger_dir / name).read_text(encoding="utf-8"))
        parts.append((ledger_dir / "importers" / "aldi.bean").read_text(encoding="utf-8"))

        combined = "\n".join(parts)
        combined = "\n".join(
            line for line in combined.splitlines() if not line.startswith("include ")
        )

        _, errors, _ = load_string(combined)
        assert errors == [], f"Beancount validation errors: {errors}"


# --- Account Name ---


class TestAccountName:
    def test_default_account(self):
        importer = AldiImporter()
        assert importer.account_name() == "Assets:Clearing:ALDI"

    def test_custom_account(self):
        importer = AldiImporter(account="Assets:Alipay", currency="CNY")
        assert importer.account_name() == "Assets:Alipay"
