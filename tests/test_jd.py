"""Tests for JD (京东) importer."""

from decimal import Decimal
from pathlib import Path

from beancount.loader import load_string

from preciouss.importers.base import Transaction
from preciouss.importers.jd import (
    JdImporter,
    JdItemCategorizer,
    JdOrdersImporter,
    _enrich_with_orders,
    _load_jd_orders,
    _parse_amount,
)
from preciouss.ledger.writer import (
    group_items_by_category,
    init_ledger,
    multiposting_transaction_to_bean,
    write_transactions,
)

FIXTURES = Path(__file__).parent / "fixtures"


class TestIdentify:
    def test_identify_jd_csv(self):
        importer = JdImporter()
        assert importer.identify(FIXTURES / "jd_sample.csv")

    def test_identify_rejects_other_csv(self):
        importer = JdImporter()
        assert not importer.identify(FIXTURES / "alipay_sample.csv")
        assert not importer.identify(FIXTURES / "wechat_sample.csv")

    def test_identify_rejects_non_csv(self, tmp_path):
        f = tmp_path / "data.txt"
        f.write_text("京东账号名\n", encoding="utf-8")
        importer = JdImporter()
        assert not importer.identify(f)


class TestParseAmount:
    def test_simple_amount(self):
        original, refund = _parse_amount("38.68")
        assert original == Decimal("38.68")
        assert refund is None

    def test_full_refund(self):
        original, refund = _parse_amount("44.28(已全额退款)")
        assert original == Decimal("44.28")
        assert refund == Decimal("44.28")

    def test_partial_refund(self):
        original, refund = _parse_amount("392.98(已退款203.98)")
        assert original == Decimal("392.98")
        assert refund == Decimal("203.98")

    def test_full_refund_chinese_parens(self):
        original, refund = _parse_amount("100.00（已全额退款）")
        assert original == Decimal("100.00")
        assert refund == Decimal("100.00")

    def test_partial_refund_chinese_parens(self):
        original, refund = _parse_amount("200.00（已退款50.00）")
        assert original == Decimal("200.00")
        assert refund == Decimal("50.00")


class TestExtract:
    def test_extract_count(self):
        """Should extract 6 transactions (full refund skipped).

        expense + transfer + partial refund + income + 2 XiaoJinKu transfers.
        """
        importer = JdImporter()
        txns = importer.extract(FIXTURES / "jd_sample.csv")
        # Row 1: expense (normal) → kept
        # Row 2: BaiTiao repayment (transfer) → kept
        # Row 3: full refund → skipped
        # Row 4: partial refund → kept
        # Row 5: income → kept
        # Row 6: XiaoJinKu deposit → kept
        # Row 7: XiaoJinKu withdrawal → kept
        assert len(txns) == 6  # 新增两条小金库转账

    def test_expense_resolved_account(self):
        importer = JdImporter()
        txns = importer.extract(FIXTURES / "jd_sample.csv")
        tx0 = txns[0]
        assert tx0.payee == "京东平台商户"
        assert tx0.narration == "小米空气净化器滤芯"
        assert tx0.amount == Decimal("-38.68")
        assert tx0.source_account == "Liabilities:CreditCard:CMB"
        assert tx0.tx_type == "expense"
        assert tx0.raw_category == "数码电器"
        assert tx0.reference_id == "JD202401100001"

    def test_baitiao_repayment_transfer(self):
        importer = JdImporter()
        txns = importer.extract(FIXTURES / "jd_sample.csv")
        tx1 = txns[1]
        assert tx1.narration == "白条还款-1月"
        assert tx1.amount == Decimal("-500.00")
        assert tx1.tx_type == "transfer"
        assert tx1.source_account == "Assets:Bank:CMB"
        assert tx1.metadata["transfer_account"] == "Liabilities:JD:BaiTiao"

    def test_full_refund_skipped(self):
        """Full refund (44.28 已全额退款) should be skipped."""
        importer = JdImporter()
        txns = importer.extract(FIXTURES / "jd_sample.csv")
        # None of the transactions should have amount -44.28 or reference JD202401180001
        refs = [tx.reference_id for tx in txns]
        assert "JD202401180001" not in refs

    def test_partial_refund_net_amount(self):
        """Partial refund: net = -(392.98 - 203.98) = -189.00."""
        importer = JdImporter()
        txns = importer.extract(FIXTURES / "jd_sample.csv")
        tx2 = txns[2]
        assert tx2.amount == Decimal("-189.00")
        assert tx2.metadata["jd_refund"] == "203.98"
        assert tx2.metadata["jd_original"] == "392.98"
        assert tx2.source_account == "Liabilities:JD:BaiTiao"
        assert tx2.raw_category == "鞋服箱包"

    def test_income(self):
        importer = JdImporter()
        txns = importer.extract(FIXTURES / "jd_sample.csv")
        tx3 = txns[3]
        assert tx3.amount == Decimal("50.00")
        assert tx3.tx_type == "income"
        assert tx3.source_account == "Assets:JD"


class TestXiaoJinKuTransfers:
    def _get_txns(self):
        return JdImporter().extract(FIXTURES / "jd_sample.csv")

    def test_deposit_to_xiaojinku(self):
        """小金库转入：银行 → Assets:JD:XiaoJinKu"""
        txns = self._get_txns()
        tx = txns[4]  # Row 6 (0-indexed 4)
        assert tx.narration == "京东小金库-转入"
        assert tx.amount == Decimal("-200.00")
        assert tx.source_account == "Assets:Bank:CMB"
        assert tx.metadata["transfer_account"] == "Assets:JD:XiaoJinKu"

    def test_deposit_tx_type(self):
        txns = self._get_txns()
        assert txns[4].tx_type == "transfer"

    def test_withdraw_from_xiaojinku(self):
        """小金库取出：Assets:JD:XiaoJinKu → Assets:Unknown"""
        txns = self._get_txns()
        tx = txns[5]  # Row 7 (0-indexed 5)
        assert tx.narration == "京东小金库-取出"
        assert tx.amount == Decimal("-100.00")
        assert tx.source_account == "Assets:JD:XiaoJinKu"
        assert tx.metadata["transfer_account"] == "Assets:Unknown"

    def test_withdraw_tx_type(self):
        txns = self._get_txns()
        assert txns[5].tx_type == "transfer"

    def test_xiaojinku_not_enriched(self):
        """小金库 tx 有 orders_file 时也不应被 order enrichment 处理"""
        importer = JdImporter(orders_file=FIXTURES / "jd_orders_sample.json")
        txns = importer.extract(FIXTURES / "jd_sample.csv")
        deposit_tx = txns[4]
        withdraw_tx = txns[5]
        assert "jd_items" not in deposit_tx.metadata
        assert "jd_items" not in withdraw_tx.metadata


class TestAccountName:
    def test_default_account(self):
        importer = JdImporter()
        assert importer.account_name() == "Assets:JD"

    def test_custom_account(self):
        importer = JdImporter(account="Assets:MyJD")
        assert importer.account_name() == "Assets:MyJD"


class TestBeancountValidation:
    def test_beancount_validates(self, tmp_path):
        """Generated ledger with JD transactions passes beancount validation."""
        importer = JdImporter()
        txns = importer.extract(FIXTURES / "jd_sample.csv")

        ledger_dir = tmp_path / "ledger"
        init_ledger(ledger_dir)
        write_transactions(txns, ledger_dir / "importers" / "jd.bean")

        # Combine all files
        parts = []
        for name in ["main.bean", "commodities.bean", "accounts.bean"]:
            parts.append((ledger_dir / name).read_text(encoding="utf-8"))
        parts.append((ledger_dir / "importers" / "jd.bean").read_text(encoding="utf-8"))

        combined = "\n".join(parts)
        combined = "\n".join(
            line for line in combined.splitlines() if not line.startswith("include ")
        )
        _, errors, _ = load_string(combined)
        assert errors == [], f"Beancount validation errors: {errors}"


# --- Order Enrichment ---


class TestOrderEnrichment:
    def _make_tx(self, counterpart_ref: str, amount: Decimal = Decimal("-38.68")) -> Transaction:
        from datetime import datetime

        return Transaction(
            date=datetime(2024, 1, 10, 9, 30),
            amount=amount,
            currency="CNY",
            payee="京东平台商户",
            narration="test",
            source_account="Liabilities:CreditCard:CMB",
            reference_id="JD202401100001",
            counterpart_ref=counterpart_ref,
            tx_type="expense",
        )

    def test_load_jd_orders_builds_lookup(self):
        lookup = _load_jd_orders(FIXTURES / "jd_orders_sample.json")
        assert "M20240110001" in lookup
        assert "M20240120001" in lookup
        # Cancelled order is excluded
        assert "CANCELLED001" not in lookup
        # parent_order_id grouping: CHILD001 and CHILD002 both map to PARENT001
        assert "PARENT001" in lookup
        assert len(lookup["PARENT001"]) == 2

    def test_enrich_adds_jd_items(self):
        lookup = _load_jd_orders(FIXTURES / "jd_orders_sample.json")
        tx = self._make_tx("M20240110001")
        _enrich_with_orders(tx, lookup)
        assert "jd_items" in tx.metadata
        items = tx.metadata["jd_items"]
        assert len(items) == 1
        assert items[0]["name"] == "小米空气净化器滤芯"
        assert items[0]["num"] == 1
        assert items[0]["price"] == "38.68"

    def test_enrich_with_refund_tx(self):
        """jd_refund transactions should also be enriched (not skipped)."""
        from datetime import datetime

        lookup = _load_jd_orders(FIXTURES / "jd_orders_sample.json")
        tx = Transaction(
            date=datetime(2024, 1, 20, 16, 30),
            amount=Decimal("-189.00"),
            currency="CNY",
            payee="京东平台商户",
            narration="运动T恤两件装",
            source_account="Liabilities:JD:BaiTiao",
            reference_id="JD202401200001",
            counterpart_ref="M20240120001",
            tx_type="expense",
            metadata={"jd_refund": "203.98", "jd_original": "392.98"},
        )
        _enrich_with_orders(tx, lookup)
        assert "jd_items" in tx.metadata

    def test_zero_price_item_skipped(self):
        """Items with price=0 (gifts) should not appear in jd_items."""
        import json

        fixture = FIXTURES / "jd_orders_sample.json"
        with open(fixture, encoding="utf-8") as f:
            data = json.load(f)
        # Inject a zero-price item into M20240110001
        for order in data["orders"]:
            if order["order_id"] == "M20240110001":
                order["items"].append({"name": "赠品", "quantity": 1, "price": 0})
                break
        # Build lookup from modified data
        synthetic_lookup: dict[str, list[dict]] = {}
        for order in data["orders"]:
            if order.get("status") != "已完成":
                continue
            key = order.get("parent_order_id") or order.get("order_id")
            if key:
                synthetic_lookup.setdefault(str(key), []).append(order)

        tx = self._make_tx("M20240110001")
        _enrich_with_orders(tx, synthetic_lookup)
        names = [it["name"] for it in tx.metadata["jd_items"]]
        assert "赠品" not in names
        assert "小米空气净化器滤芯" in names

    def test_cancelled_order_skipped(self):
        """Cancelled orders should not contribute items."""
        lookup = _load_jd_orders(FIXTURES / "jd_orders_sample.json")
        # CANCELLED001 is not in the lookup at all
        assert "CANCELLED001" not in lookup

    def test_fully_gift_card_order_excluded_from_enrichment(self):
        """amount==0 + gift_card>0 orders should be excluded from CSV enrichment."""
        lookup = _load_jd_orders(FIXTURES / "jd_orders_sample.json")
        # GC20240201001 is in the lookup (status=已完成, not cancelled)
        assert "GC20240201001" in lookup
        # But _enrich_with_orders skips it because amount==0 and gift_card>0
        tx = self._make_tx("GC20240201001")
        _enrich_with_orders(tx, lookup)
        # No items should have been written (the fully-GC order is excluded)
        assert "jd_items" not in tx.metadata

    def test_gift_card_amount_in_metadata(self):
        """Partial gift card payment should write jd_gift_card metadata."""
        lookup = _load_jd_orders(FIXTURES / "jd_orders_sample.json")
        tx = self._make_tx("M20240120001", Decimal("-189.00"))
        _enrich_with_orders(tx, lookup)
        assert "jd_gift_card" in tx.metadata
        assert tx.metadata["jd_gift_card"] == "110.0"

    def test_no_match_falls_back_to_standard(self, tmp_path):
        """TX with no matching order should not get jd_items."""
        lookup = _load_jd_orders(FIXTURES / "jd_orders_sample.json")
        tx = self._make_tx("NONEXISTENT999")
        _enrich_with_orders(tx, lookup)
        assert "jd_items" not in tx.metadata

    def test_parent_order_id_grouping(self):
        """Multiple sub-orders with same parent_order_id all map to parent key."""
        lookup = _load_jd_orders(FIXTURES / "jd_orders_sample.json")
        tx = self._make_tx("PARENT001", Decimal("-50.00"))
        _enrich_with_orders(tx, lookup)
        assert "jd_items" in tx.metadata
        items = tx.metadata["jd_items"]
        names = [it["name"] for it in items]
        assert "子订单商品A" in names
        assert "子订单商品B" in names

    def test_extract_with_orders_file_enriches(self):
        """JdImporter with orders_file should enrich extracted transactions."""
        importer = JdImporter(orders_file=FIXTURES / "jd_orders_sample.json")
        txns = importer.extract(FIXTURES / "jd_sample.csv")
        # tx0 (M20240110001) should have jd_items
        tx0 = txns[0]
        assert "jd_items" in tx0.metadata
        # transfer tx (BaiTiao repayment) should NOT be enriched
        tx1 = txns[1]
        assert "jd_items" not in tx1.metadata

    def test_extract_without_orders_file_no_enrichment(self):
        """JdImporter without orders_file should NOT enrich transactions."""
        importer = JdImporter()
        txns = importer.extract(FIXTURES / "jd_sample.csv")
        for tx in txns:
            assert "jd_items" not in tx.metadata


# --- JdOrdersImporter ---


class TestJdOrdersImporter:
    def test_identify_jd_orders_json(self):
        importer = JdOrdersImporter()
        assert importer.identify(FIXTURES / "jd_orders_sample.json")

    def test_identify_rejects_aldi_json(self):
        importer = JdOrdersImporter()
        assert not importer.identify(FIXTURES / "aldi_sample.json")

    def test_identify_rejects_csv(self):
        importer = JdOrdersImporter()
        assert not importer.identify(FIXTURES / "jd_sample.csv")

    def test_extract_gift_card_orders_only(self):
        """Should extract only the fully gift-card-paid order."""
        importer = JdOrdersImporter()
        txns = importer.extract(FIXTURES / "jd_orders_sample.json")
        assert len(txns) == 1
        tx = txns[0]
        assert tx.amount == Decimal("-53.10")
        assert tx.source_account == "Assets:JD:GiftCard"
        assert tx.reference_id == "GC20240201001"

    def test_cash_orders_not_extracted(self):
        """Orders with cash payment should NOT be extracted."""
        importer = JdOrdersImporter()
        txns = importer.extract(FIXTURES / "jd_orders_sample.json")
        for tx in txns:
            # No cash-paid order IDs should appear
            assert tx.reference_id not in ("M20240110001", "M20240120001")

    def test_zero_price_items_skipped(self):
        """Gift items (price=0) should not appear in jd_items."""
        importer = JdOrdersImporter()
        txns = importer.extract(FIXTURES / "jd_orders_sample.json")
        assert len(txns) == 1
        items = txns[0].metadata["jd_items"]
        names = [it["name"] for it in items]
        assert "赠品贴纸" not in names
        assert "松下毛球修剪器" in names

    def test_narration_single_item(self):
        """Single item → narration is the item name."""
        importer = JdOrdersImporter()
        txns = importer.extract(FIXTURES / "jd_orders_sample.json")
        assert txns[0].narration == "松下毛球修剪器"

    def test_cancelled_orders_not_extracted(self):
        """Cancelled orders should not be extracted."""
        importer = JdOrdersImporter()
        txns = importer.extract(FIXTURES / "jd_orders_sample.json")
        refs = [tx.reference_id for tx in txns]
        assert "CANCELLED001" not in refs

    def test_account_name(self):
        importer = JdOrdersImporter()
        assert importer.account_name() == "Assets:JD:GiftCard"


# --- JD Writer Tests ---


class TestJdWriter:
    def _make_jd_tx(
        self,
        amount: Decimal = Decimal("-38.68"),
        items: list[dict] | None = None,
        gift_card: str | None = None,
    ) -> Transaction:
        from datetime import datetime

        metadata: dict = {}
        if items is not None:
            metadata["jd_items"] = items
        if gift_card is not None:
            metadata["jd_gift_card"] = gift_card

        return Transaction(
            date=datetime(2024, 1, 10, 9, 30),
            amount=amount,
            currency="CNY",
            payee="京东平台商户",
            narration="test order",
            source_account="Liabilities:CreditCard:CMB",
            reference_id="JD202401100001",
            tx_type="expense",
            metadata=metadata,
        )

    def test_proportional_discount_single_category(self):
        """Single category: effective amount equals total_payment exactly."""
        items = [
            {"name": "滤芯", "num": 1, "price": "50.0", "category": "Expenses:Shopping:Electronics"}
        ]
        total_payment = Decimal("38.68")
        result = group_items_by_category(items, total_payment)
        assert len(result) == 1
        assert result[0][0] == "Expenses:Shopping:Electronics"
        assert result[0][1] == total_payment

    def test_proportional_discount_multi_category(self):
        """Multiple categories scaled proportionally, sum equals total_payment."""
        items = [
            {
                "name": "滤芯",
                "num": 1,
                "price": "100.0",
                "category": "Expenses:Shopping:Electronics",
            },
            {"name": "T恤", "num": 2, "price": "50.0", "category": "Expenses:Shopping:Clothing"},
        ]
        total_payment = Decimal("150.0")
        result = group_items_by_category(items, total_payment)
        assert len(result) == 2
        total = sum(amt for _, amt, _ in result)
        assert total == total_payment

    def test_multiposting_with_gift_card(self):
        """Gift card posting should appear between source and expense postings."""
        items = [
            {
                "name": "运动T恤",
                "num": 2,
                "price": "149.50",
                "category": "Expenses:Shopping:Clothing",
            }
        ]
        gift_card = Decimal("110.00")
        total_payment = Decimal("189.00") + gift_card  # 299.00
        by_category = group_items_by_category(items, total_payment)
        tx = self._make_jd_tx(amount=Decimal("-189.00"), items=items, gift_card="110.00")
        bean_tx = multiposting_transaction_to_bean(tx, by_category, gift_card_amount=gift_card)

        accounts = [p.account for p in bean_tx.postings]
        assert "Liabilities:CreditCard:CMB" in accounts
        assert "Assets:JD:GiftCard" in accounts
        assert "Expenses:Shopping:Clothing" in accounts
        assert len(bean_tx.postings) == 3

    def test_gift_card_balance_correct(self):
        """Sum of all postings must be zero."""
        items = [
            {
                "name": "运动T恤",
                "num": 2,
                "price": "149.50",
                "category": "Expenses:Shopping:Clothing",
            }
        ]
        gift_card = Decimal("110.00")
        total_payment = Decimal("189.00") + gift_card
        by_category = group_items_by_category(items, total_payment)
        tx = self._make_jd_tx(amount=Decimal("-189.00"), items=items, gift_card="110.00")
        bean_tx = multiposting_transaction_to_bean(tx, by_category, gift_card_amount=gift_card)

        total = sum(p.units.number for p in bean_tx.postings)
        assert total == Decimal("0")

    def test_items_metadata_shows_original_price(self):
        """items metadata string should show original listed price, not effective price."""
        items = [
            {
                "name": "毛球修剪器",
                "num": 1,
                "price": "59.0",
                "category": "Expenses:Shopping:DailyGoods",
            }
        ]
        total_payment = Decimal("53.10")
        by_category = group_items_by_category(items, total_payment)
        tx = self._make_jd_tx(amount=Decimal("-53.10"), items=items)
        bean_tx = multiposting_transaction_to_bean(tx, by_category)

        expense_posting = next(p for p in bean_tx.postings if p.account.startswith("Expenses:"))
        assert "毛球修剪器 x1 ¥59.0" in expense_posting.meta["items"]

    def test_rounding_correction(self):
        """Proportional amounts must sum exactly to total_payment after rounding correction."""
        items = [
            {"name": "A", "num": 1, "price": "33.33", "category": "Expenses:Uncategorized"},
            {"name": "B", "num": 1, "price": "33.33", "category": "Expenses:Uncategorized"},
            {"name": "C", "num": 1, "price": "33.34", "category": "Expenses:Uncategorized"},
        ]
        total_payment = Decimal("90.00")
        result = group_items_by_category(items, total_payment)
        total = sum(amt for _, amt, _ in result)
        assert total == total_payment

    def test_write_transactions_jd_items(self, tmp_path):
        """write_transactions dispatches JD items to multiposting path."""
        items = [
            {
                "name": "空气净化器滤芯",
                "num": 1,
                "price": "38.68",
                "category": "Expenses:Shopping:Electronics",
            }
        ]
        tx = self._make_jd_tx(items=items)
        output = tmp_path / "jd.bean"
        write_transactions([tx], output)

        content = output.read_text(encoding="utf-8")
        assert "京东平台商户" in content
        assert "Liabilities:CreditCard:CMB" in content
        assert "Expenses:Shopping:Electronics" in content
        assert "空气净化器滤芯 x1" in content

    def test_beancount_validates_jd_with_gift_card(self, tmp_path):
        """JD multi-posting with gift card passes beancount validation."""
        ledger_dir = tmp_path / "ledger"
        init_ledger(ledger_dir)

        items = [
            {
                "name": "运动T恤",
                "num": 2,
                "price": "149.50",
                "category": "Expenses:Shopping:Clothing",
            }
        ]
        tx = self._make_jd_tx(amount=Decimal("-189.00"), items=items, gift_card="110.00")
        write_transactions([tx], ledger_dir / "importers" / "jd.bean")

        parts = []
        for name in ["main.bean", "commodities.bean", "accounts.bean"]:
            parts.append((ledger_dir / name).read_text(encoding="utf-8"))
        parts.append((ledger_dir / "importers" / "jd.bean").read_text(encoding="utf-8"))

        combined = "\n".join(parts)
        combined = "\n".join(
            line for line in combined.splitlines() if not line.startswith("include ")
        )
        _, errors, _ = load_string(combined)
        assert errors == [], f"Beancount validation errors: {errors}"


# --- JdItemCategorizer ---


class TestJdItemCategorizer:
    def test_electronics(self):
        cat = JdItemCategorizer()
        assert cat.categorize("蓝牙耳机") == "Expenses:Shopping:Electronics"
        assert cat.categorize("机械键盘") == "Expenses:Shopping:Electronics"
        assert cat.categorize("空气净化器HEPA滤芯") == "Expenses:Uncategorized"

    def test_clothing(self):
        cat = JdItemCategorizer()
        assert cat.categorize("运动T恤两件装") == "Expenses:Shopping:Clothing"
        assert cat.categorize("羽绒服") == "Expenses:Shopping:Clothing"

    def test_daily_goods(self):
        cat = JdItemCategorizer()
        assert cat.categorize("松下毛球修剪器") == "Expenses:Shopping:DailyGoods"
        assert cat.categorize("洗发水") == "Expenses:Shopping:DailyGoods"

    def test_grocery(self):
        cat = JdItemCategorizer()
        assert cat.categorize("进口坚果礼盒") == "Expenses:Food:Grocery"

    def test_default(self):
        cat = JdItemCategorizer()
        assert cat.categorize("某种未知商品XYZ") == "Expenses:Uncategorized"
