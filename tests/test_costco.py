"""Tests for Costco JSON receipt importer."""

from datetime import datetime
from decimal import Decimal
from pathlib import Path

from beancount.loader import load_string

from preciouss.importers.base import Transaction
from preciouss.importers.costco import CostcoImporter, CostcoItemCategorizer
from preciouss.ledger.writer import (
    group_items_by_category,
    init_ledger,
    multiposting_transaction_to_bean,
    write_transactions,
)

FIXTURES = Path(__file__).parent / "fixtures"


# --- Identify ---


class TestIdentify:
    def test_identify_costco_json(self):
        importer = CostcoImporter()
        assert importer.identify(FIXTURES / "costco_sample.json")

    def test_identify_rejects_csv(self):
        importer = CostcoImporter()
        csv_files = list(FIXTURES.glob("*.csv"))
        if csv_files:
            assert not importer.identify(csv_files[0])

    def test_identify_rejects_aldi_json(self):
        importer = CostcoImporter()
        aldi = FIXTURES / "aldi_sample.json"
        if aldi.exists():
            assert not importer.identify(aldi)

    def test_identify_rejects_wechathk_json(self):
        importer = CostcoImporter()
        wechathk = FIXTURES / "wechathk_sample.json"
        if wechathk.exists():
            assert not importer.identify(wechathk)

    def test_identify_rejects_missing_keys(self, tmp_path):
        f = tmp_path / "other.json"
        f.write_text('{"code": "000000", "success": true}', encoding="utf-8")
        importer = CostcoImporter()
        assert not importer.identify(f)

    def test_identify_rejects_non_json(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("not json", encoding="utf-8")
        importer = CostcoImporter()
        assert not importer.identify(f)


# --- Extract ---


class TestExtract:
    def test_extract_count(self):
        importer = CostcoImporter()
        txns = importer.extract(FIXTURES / "costco_sample.json")
        assert len(txns) == 1

    def test_extract_amount(self):
        importer = CostcoImporter()
        txns = importer.extract(FIXTURES / "costco_sample.json")
        assert txns[0].amount == Decimal("-141.8")

    def test_extract_date(self):
        importer = CostcoImporter()
        txns = importer.extract(FIXTURES / "costco_sample.json")
        assert txns[0].date == datetime(2026, 1, 17, 20, 23, 33)

    def test_extract_payee(self):
        importer = CostcoImporter()
        txns = importer.extract(FIXTURES / "costco_sample.json")
        assert txns[0].payee == "Costco"

    def test_extract_narration(self):
        importer = CostcoImporter()
        txns = importer.extract(FIXTURES / "costco_sample.json")
        assert txns[0].narration == "上海闵行"

    def test_extract_reference_id(self):
        importer = CostcoImporter()
        txns = importer.extract(FIXTURES / "costco_sample.json")
        assert txns[0].reference_id == "555710202360070001202601172024"

    def test_extract_counterpart_ref(self):
        """counterpart_ref should be barcode[4:14] (10-digit merchant order)."""
        importer = CostcoImporter()
        txns = importer.extract(FIXTURES / "costco_sample.json")
        assert txns[0].counterpart_ref == "1020236007"

    def test_extract_items_count(self):
        importer = CostcoImporter()
        txns = importer.extract(FIXTURES / "costco_sample.json")
        items = txns[0].metadata["costco_items"]
        assert len(items) == 2

    def test_extract_item_details(self):
        importer = CostcoImporter()
        txns = importer.extract(FIXTURES / "costco_sample.json")
        items = txns[0].metadata["costco_items"]
        assert items[0]["name"] == "袋装综合坚果"
        assert items[0]["num"] == 1
        assert items[0]["price"] == "115.9"
        assert items[1]["name"] == "纸巾家庭装"
        assert items[1]["price"] == "33.9"

    def test_extract_discount_metadata(self):
        importer = CostcoImporter()
        txns = importer.extract(FIXTURES / "costco_sample.json")
        assert txns[0].metadata["costco_discount"] == "7.0"

    def test_source_account_is_clearing(self):
        importer = CostcoImporter()
        txns = importer.extract(FIXTURES / "costco_sample.json")
        assert txns[0].source_account == "Assets:Clearing:Costco"

    def test_tx_type(self):
        importer = CostcoImporter()
        txns = importer.extract(FIXTURES / "costco_sample.json")
        assert txns[0].tx_type == "expense"

    def test_extract_success_false_returns_empty(self, tmp_path):
        import json

        f = tmp_path / "failed.json"
        f.write_text(
            json.dumps(
                {
                    "code": "999999",
                    "data": {
                        "barcode": "555710202360070001202601172024",
                        "itemList": [],
                        "actualPayment": 0,
                        "transTime": "2026-01-17 20:23:33",
                        "warehouseName": "test",
                    },
                    "success": False,
                }
            ),
            encoding="utf-8",
        )
        importer = CostcoImporter()
        assert importer.extract(f) == []

    def test_no_discount_when_zero(self, tmp_path):
        import json

        f = tmp_path / "no_discount.json"
        f.write_text(
            json.dumps(
                {
                    "code": "000000",
                    "data": {
                        "barcode": "555710202360070001202601172024",
                        "itemList": [
                            {
                                "amount": 1.0,
                                "itemCode": "123",
                                "itemName": "坚果",
                                "taxAmount": 0,
                                "taxRate": "13%",
                                "totalDiscount": 0.0,
                                "totalNetPrice": 50.0,
                                "totalPrice": 50.0,
                                "unitNetPrice": 50.0,
                                "unitPrice": 50.0,
                                "weightItem": "",
                            }
                        ],
                        "actualPayment": 50.0,
                        "totalPrice": 50.0,
                        "transTime": "2026-01-17 20:23:33",
                        "warehouseName": "上海闵行",
                        "cashDiscount": 0,
                    },
                    "success": True,
                }
            ),
            encoding="utf-8",
        )
        importer = CostcoImporter()
        txns = importer.extract(f)
        assert len(txns) == 1
        # cashDiscount is 0 (falsy), so no costco_discount in metadata
        assert "costco_discount" not in txns[0].metadata


# --- Item Categorizer ---


class TestItemCategorizer:
    def test_grocery_nuts(self):
        cat = CostcoItemCategorizer()
        assert cat.categorize("袋装综合坚果") == "Expenses:Food:Grocery"

    def test_grocery_milk(self):
        cat = CostcoItemCategorizer()
        assert cat.categorize("有机全脂牛奶") == "Expenses:Food:Grocery"

    def test_grocery_salmon(self):
        cat = CostcoItemCategorizer()
        assert cat.categorize("挪威三文鱼") == "Expenses:Food:Grocery"

    def test_grocery_beef(self):
        cat = CostcoItemCategorizer()
        assert cat.categorize("澳洲牛肉") == "Expenses:Food:Grocery"

    def test_daily_goods_tissue(self):
        cat = CostcoItemCategorizer()
        assert cat.categorize("纸巾家庭装") == "Expenses:Shopping:DailyGoods"

    def test_daily_goods_shampoo(self):
        cat = CostcoItemCategorizer()
        assert cat.categorize("洗发水大瓶装") == "Expenses:Shopping:DailyGoods"

    def test_clothing(self):
        cat = CostcoItemCategorizer()
        assert cat.categorize("男士外套") == "Expenses:Shopping:Clothing"

    def test_electronics(self):
        cat = CostcoItemCategorizer()
        assert cat.categorize("无线耳机") == "Expenses:Shopping:Electronics"

    def test_household(self):
        cat = CostcoItemCategorizer()
        assert cat.categorize("收纳箱") == "Expenses:Shopping:Household"

    def test_default_category(self):
        cat = CostcoItemCategorizer()
        assert cat.categorize("某种未知商品XYZ") == "Expenses:Food:Grocery"


# --- Multiposting Writer ---


class TestMultiposting:
    def _make_costco_tx(self) -> Transaction:
        return Transaction(
            date=datetime(2026, 1, 17, 20, 23, 33),
            amount=Decimal("-141.8"),
            currency="CNY",
            payee="Costco",
            narration="上海闵行",
            source_account="Assets:Alipay",
            reference_id="555710202360070001202601172024",
            counterpart_ref="1020236007",
            tx_type="expense",
            metadata={
                "costco_items": [
                    {
                        "name": "袋装综合坚果",
                        "num": 1,
                        "price": "115.9",
                        "category": "Expenses:Food:Grocery",
                    },
                    {
                        "name": "纸巾家庭装",
                        "num": 1,
                        "price": "33.9",
                        "category": "Expenses:Shopping:DailyGoods",
                    },
                ],
                "costco_discount": "7.0",
            },
        )

    def test_multiposting_posting_count(self):
        tx = self._make_costco_tx()
        by_category = group_items_by_category(tx.metadata["costco_items"], Decimal("141.8"))
        bean_tx = multiposting_transaction_to_bean(tx, by_category)
        # 1 source + 2 expense categories
        assert len(bean_tx.postings) == 3

    def test_multiposting_source_posting(self):
        tx = self._make_costco_tx()
        by_category = group_items_by_category(tx.metadata["costco_items"], Decimal("141.8"))
        bean_tx = multiposting_transaction_to_bean(tx, by_category)
        assert bean_tx.postings[0].account == "Assets:Alipay"
        assert bean_tx.postings[0].units.number == Decimal("-141.8")

    def test_multiposting_expense_accounts(self):
        tx = self._make_costco_tx()
        by_category = group_items_by_category(tx.metadata["costco_items"], Decimal("141.8"))
        bean_tx = multiposting_transaction_to_bean(tx, by_category)
        accounts = [p.account for p in bean_tx.postings[1:]]
        assert "Expenses:Food:Grocery" in accounts
        assert "Expenses:Shopping:DailyGoods" in accounts

    def test_multiposting_balances(self):
        """Sum of all postings should be zero."""
        tx = self._make_costco_tx()
        by_category = group_items_by_category(tx.metadata["costco_items"], Decimal("141.8"))
        bean_tx = multiposting_transaction_to_bean(tx, by_category)
        total = sum(p.units.number for p in bean_tx.postings)
        assert total == Decimal("0")

    def test_write_transactions_dispatches_costco(self, tmp_path):
        """write_transactions() correctly dispatches Costco transactions."""
        tx = self._make_costco_tx()
        output = tmp_path / "costco.bean"
        write_transactions([tx], output)

        content = output.read_text(encoding="utf-8")
        assert "Costco" in content
        assert "Assets:Alipay" in content
        assert "Expenses:Food:Grocery" in content
        assert "-141.8 CNY" in content

    def test_posting_items_metadata(self):
        """Expense postings should have items metadata."""
        tx = self._make_costco_tx()
        by_category = group_items_by_category(tx.metadata["costco_items"], Decimal("141.8"))
        bean_tx = multiposting_transaction_to_bean(tx, by_category)
        for posting in bean_tx.postings[1:]:
            assert "items" in posting.meta
            assert isinstance(posting.meta["items"], str)



# --- Beancount Validation ---


class TestBeancountValidation:
    def test_beancount_validates(self, tmp_path):
        """Generated multiposting Costco ledger passes beancount validation."""
        ledger_dir = tmp_path / "ledger"
        init_ledger(ledger_dir)

        tx = Transaction(
            date=datetime(2026, 1, 17, 20, 23, 33),
            amount=Decimal("-141.8"),
            currency="CNY",
            payee="Costco",
            narration="上海闵行",
            source_account="Assets:Clearing:Costco",
            reference_id="555710202360070001202601172024",
            counterpart_ref="1020236007",
            tx_type="expense",
            metadata={
                "costco_items": [
                    {
                        "name": "袋装综合坚果",
                        "num": 1,
                        "price": "115.9",
                        "category": "Expenses:Food:Grocery",
                    },
                    {
                        "name": "纸巾家庭装",
                        "num": 1,
                        "price": "33.9",
                        "category": "Expenses:Shopping:DailyGoods",
                    },
                ],
            },
        )

        write_transactions([tx], ledger_dir / "importers" / "costco.bean")

        parts = []
        for name in ["main.bean", "commodities.bean", "accounts.bean"]:
            parts.append((ledger_dir / name).read_text(encoding="utf-8"))
        parts.append((ledger_dir / "importers" / "costco.bean").read_text(encoding="utf-8"))

        combined = "\n".join(parts)
        combined = "\n".join(
            line for line in combined.splitlines() if not line.startswith("include ")
        )

        _, errors, _ = load_string(combined)
        assert errors == [], f"Beancount validation errors: {errors}"


# --- Account Name ---


class TestAccountName:
    def test_default_account(self):
        importer = CostcoImporter()
        assert importer.account_name() == "Assets:Clearing:Costco"

    def test_custom_account(self):
        importer = CostcoImporter(account="Assets:Alipay", currency="CNY")
        assert importer.account_name() == "Assets:Alipay"
