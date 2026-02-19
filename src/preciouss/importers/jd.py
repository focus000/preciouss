"""JD (京东) CSV importer."""

from __future__ import annotations

import json
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from preciouss.importers.base import CsvImporter, PrecioussImporter, Transaction
from preciouss.importers.resolve import resolve_payment_account

_AMOUNT_RE = re.compile(r"^([\d.]+)(?:[（(]已(?:全额)?退款([\d.]*)[）)])?$")

# Keyword patterns → expense account mapping for JD items
JD_ITEM_CATEGORIES: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(r"电脑|笔记本|手机|平板|耳机|音箱|相机|路由|充电|数据线|键盘|鼠标|显示器|剃须"),
        "Expenses:Shopping:Electronics",
    ),
    (
        re.compile(r"书|图书|文具|教材|课本"),
        "Expenses:Education:Books",
    ),
    (
        re.compile(r"衣|裤|裙|袜|鞋|包|帽|外套|夹克|T恤|毛衣|羽绒"),
        "Expenses:Shopping:Clothing",
    ),
    (
        re.compile(r"食品|零食|饮料|米|面|油|奶|茶|咖啡|饼干|糖|巧克力|坚果"),
        "Expenses:Food:Grocery",
    ),
    (
        re.compile(r"洗发|沐浴|牙膏|护肤|化妆|卫生|洗衣|清洁|湿巾|毛球"),
        "Expenses:Shopping:DailyGoods",
    ),
    (
        re.compile(r"家具|收纳|床|枕|被|毯|灯|窗帘|厨具|餐具|不锈钢|烘焙"),
        "Expenses:Shopping:HomeGoods",
    ),
]

DEFAULT_JD_CATEGORY = "Expenses:Uncategorized"


class JdItemCategorizer:
    """Categorize individual JD product items by keyword matching."""

    def categorize(self, name: str) -> str:
        for pattern, category in JD_ITEM_CATEGORIES:
            if pattern.search(name):
                return category
        return DEFAULT_JD_CATEGORY


def _parse_amount(raw: str) -> tuple[Decimal, Decimal | None]:
    """Parse JD amount string, returning (original_amount, refund_amount | None).

    Examples:
        "38.68"                → (38.68, None)
        "44.28(已全额退款)"      → (44.28, 44.28)
        "392.98(已退款203.98)"  → (392.98, 203.98)
    """
    raw = raw.strip()
    m = _AMOUNT_RE.match(raw)
    if not m:
        raise ValueError(f"Cannot parse JD amount: {raw!r}")

    original = Decimal(m.group(1))
    refund_part = m.group(2)

    if refund_part is None:
        # No parenthetical at all
        return original, None
    elif refund_part == "":
        # "(已全额退款)" — no explicit number means full refund
        return original, original
    else:
        return original, Decimal(refund_part)


def _load_jd_orders(orders_file: str | Path) -> dict[str, list[dict]]:
    """Load JD orders JSON and build a lookup dict keyed by merchant order number.

    Key = parent_order_id if set, else order_id.
    Only completed orders are included.
    """
    with open(orders_file, encoding="utf-8") as f:
        data = json.load(f)
    lookup: dict[str, list[dict]] = {}
    for order in data.get("orders", []):
        if order.get("status") != "已完成":
            continue
        key = order.get("parent_order_id") or order.get("order_id")
        if key:
            lookup.setdefault(str(key), []).append(order)
    return lookup


def _enrich_with_orders(tx: Transaction, lookup: dict[str, list[dict]]) -> None:
    """Enrich a transaction with item details from the JD orders lookup.

    Writes jd_items (and optionally jd_gift_card) into tx.metadata in-place.
    Fully gift-card orders (amount==0) are excluded from CSV enrichment.
    """
    key = tx.counterpart_ref
    if not key or key not in lookup:
        return

    categorizer = JdItemCategorizer()
    jd_items: list[dict] = []
    gift_card_total = Decimal(0)

    for order in lookup[key]:
        goods_total = order.get("goods_total", {})
        order_amount = Decimal(str(order.get("amount", 0)))
        gift_card = abs(Decimal(str(goods_total.get("礼品卡和领货码", 0))))

        # Skip fully gift-card orders (not in CSV, handled by JdOrdersImporter)
        if order_amount == 0 and gift_card > 0:
            continue

        if gift_card > 0:
            gift_card_total += gift_card

        for item in order.get("items", []):
            price = Decimal(str(item.get("price", 0)))
            if price == 0:
                continue
            jd_items.append(
                {
                    "name": item["name"],
                    "num": item["quantity"],
                    "price": str(price),
                    "category": categorizer.categorize(item["name"]),
                }
            )

    if jd_items:
        tx.metadata["jd_items"] = jd_items
    if gift_card_total > 0:
        tx.metadata["jd_gift_card"] = str(gift_card_total)


class JdImporter(CsvImporter):
    """Import transactions from JD (京东) CSV exports.

    JD CSV format:
    - 21 metadata lines before the header
    - Identification: line 2 contains "京东账号名"
    """

    skip_lines = 21
    expected_headers = ["京东账号名"]
    tab_delimited = True

    def __init__(
        self,
        account: str = "Assets:JD",
        currency: str = "CNY",
        orders_file: str | Path | None = None,
    ):
        self._account = account
        self._currency = currency
        self._orders = _load_jd_orders(orders_file) if orders_file else None

    def account_name(self) -> str:
        return self._account

    def identify(self, filepath) -> bool:
        filepath = Path(filepath)
        if filepath.suffix.lower() != ".csv":
            return False
        try:
            content = self._read_file(filepath)
            # Check first few lines for "京东账号名"
            first_lines = "\n".join(content.split("\n")[:5])
            return "京东账号名" in first_lines
        except Exception:
            return False

    def extract(self, filepath) -> list[Transaction]:
        transactions = super().extract(filepath)
        if self._orders:
            for tx in transactions:
                if tx.tx_type != "transfer":
                    _enrich_with_orders(tx, self._orders)
        return transactions

    def _parse_row(self, row: dict[str, str]) -> Transaction | None:
        # Parse status — skip non-completed
        status = row.get("交易状态", "").strip()
        if status not in ("交易成功", "还款成功"):
            return None

        # Parse date
        date_str = row.get("交易时间", "").strip()
        if not date_str:
            return None
        try:
            date = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None

        # Parse amount
        amount_str = row.get("金额", "").strip()
        try:
            original, refund = _parse_amount(amount_str)
        except (ValueError, InvalidOperation):
            return None

        direction = row.get("收/支", "").strip()
        payment_method = row.get("收/付款方式", "").strip()
        narration = row.get("交易说明", "").strip()
        payee = row.get("商户名称", "").strip()
        trade_no = row.get("交易订单号", "").strip()
        merchant_no = row.get("商家订单号", "").strip()
        raw_category = row.get("交易分类", "").strip()

        # Resolve payment account
        source_account = self._resolve_payment(payment_method)

        if direction == "支出":
            if refund is not None:
                if refund == original:
                    # Full refund — skip
                    return None
                # Partial refund: net amount
                amount = -(original - refund)
                metadata = {"jd_refund": str(refund), "jd_original": str(original)}
            else:
                amount = -original
                metadata = {}
            tx_type = "expense"

        elif direction == "收入":
            amount = original
            tx_type = "income"
            metadata = {}

        elif direction == "不计收支":
            amount = -original
            tx_type = "transfer"
            if "还款" in narration:
                # BaiTiao repayment: money flows from bank to BaiTiao
                metadata = {"transfer_account": "Liabilities:JD:BaiTiao"}
            elif "小金库" in narration or "小金库" in payee:
                if "取出" in narration:
                    # XiaoJinKu → bank: force source = XiaoJinKu, target = payment method
                    source_account = "Assets:JD:XiaoJinKu"
                    target = (
                        resolve_payment_account(payment_method, "Assets:Unknown")
                        if payment_method and payment_method != "/"
                        else "Assets:Unknown"
                    )
                    # Prevent source == target (if payment_method also resolves to XiaoJinKu)
                    if target == "Assets:JD:XiaoJinKu":
                        target = "Assets:Unknown"
                    metadata = {"transfer_account": target}
                else:
                    # Bank → XiaoJinKu: source_account already resolved from payment_method
                    metadata = {"transfer_account": "Assets:JD:XiaoJinKu"}
            else:
                # Other non-counted: full refunds, etc.
                return None
        else:
            return None

        return Transaction(
            date=date,
            amount=amount,
            currency=self._currency,
            payee=payee,
            narration=narration,
            source_account=source_account,
            payment_method=payment_method if payment_method and payment_method != "/" else None,
            reference_id=trade_no if trade_no else None,
            counterpart_ref=merchant_no if merchant_no else None,
            raw_category=raw_category or None,
            tx_type=tx_type,
            metadata=metadata,
        )


class JdOrdersImporter(PrecioussImporter):
    """Import fully gift-card-paid JD orders from the orders JSON export.

    These orders have amount==0 and are not present in the CSV statement.
    """

    def __init__(self, account: str = "Assets:JD:GiftCard", currency: str = "CNY"):
        self._account = account
        self._currency = currency

    def account_name(self) -> str:
        return self._account

    def identify(self, filepath: str | Path) -> bool:
        filepath = Path(filepath)
        if filepath.suffix.lower() != ".json":
            return False
        try:
            with open(filepath, encoding="utf-8") as f:
                data = json.load(f)
            orders = data.get("orders", [])
            if not orders or not isinstance(orders[0], dict):
                return False
            first = orders[0]
            return "order_id" in first and "goods_total" in first
        except Exception:
            return False

    def extract(self, filepath: str | Path) -> list[Transaction]:
        filepath = Path(filepath)
        with open(filepath, encoding="utf-8") as f:
            data = json.load(f)

        categorizer = JdItemCategorizer()
        transactions = []

        for order in data.get("orders", []):
            if order.get("status") != "已完成":
                continue
            goods_total = order.get("goods_total", {})
            amount = Decimal(str(order.get("amount", 0)))
            gift_card = abs(Decimal(str(goods_total.get("礼品卡和领货码", 0))))

            # Only process fully gift-card-paid orders
            if amount != 0 or gift_card == 0:
                continue

            jd_items: list[dict] = []
            for item in order.get("items", []):
                price = Decimal(str(item.get("price", 0)))
                if price == 0:
                    continue
                jd_items.append(
                    {
                        "name": item["name"],
                        "num": item["quantity"],
                        "price": str(price),
                        "category": categorizer.categorize(item["name"]),
                    }
                )

            if not jd_items:
                continue

            time_str = order.get("pay_time") or order.get("order_time")
            date = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")

            if len(jd_items) == 1:
                narration = jd_items[0]["name"]
            else:
                narration = f"{jd_items[0]['name']}等{len(jd_items)}件"

            transactions.append(
                Transaction(
                    date=date,
                    amount=-gift_card,
                    currency=self._currency,
                    payee="京东平台商户",
                    narration=narration,
                    source_account=self._account,
                    reference_id=order.get("order_id"),
                    tx_type="expense",
                    metadata={"jd_items": jd_items},
                )
            )

        return transactions
