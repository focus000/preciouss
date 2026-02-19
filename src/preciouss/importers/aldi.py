"""ALDI (奥乐齐) JSON order importer."""

from __future__ import annotations

import json
import re
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from preciouss.importers.base import PrecioussImporter, Transaction

# Keyword patterns → expense account mapping for individual items
ALDI_ITEM_CATEGORIES: list[tuple[re.Pattern[str], str]] = [
    # 即食熟食 (must be checked before generic meat/fish)
    (
        re.compile(r"烤鸡腿|烤猪肘|炸鱼|关东煮|芝士牛肉卷"),
        "Expenses:Food:Restaurant",
    ),
    # 个护/日用
    (
        re.compile(r"牙膏|漱口水|护手霜|唇膏|洗手液|洁面乳|蓬松喷雾|卫生巾|夜安裤|迷你卫生巾"),
        "Expenses:Shopping:DailyGoods",
    ),
    # 清洁/家居
    (
        re.compile(r"湿巾|蒸笼纸|酒精"),
        "Expenses:Shopping:DailyGoods",
    ),
    # 服饰
    (
        re.compile(r"拖鞋"),
        "Expenses:Shopping:Clothing",
    ),
    # Everything else → grocery (default, but explicit patterns for clarity)
    (
        re.compile(
            r"蓝莓|草莓|番茄|香蕉|芒果|柠檬|菠菜|白菜|香菇|金针菇|蘑菇|蒜头|小米椒"
            r"|香菜|玉米|牛心菜|娃娃菜|鸡枞菌|蟹味菇|白玉菇"
        ),
        "Expenses:Food:Grocery",
    ),
    (
        re.compile(r"牛奶|酸奶|豆浆|干酪|鸡蛋|椰汁"),
        "Expenses:Food:Grocery",
    ),
    (
        re.compile(r"鸡腿|鸡胸|鸡大胸|牛肉|猪肘|鱼|水饺|黑鱼"),
        "Expenses:Food:Grocery",
    ),
    (
        re.compile(r"面包|法棍|贝果|吐司|乳酪包|六谷面包"),
        "Expenses:Food:Grocery",
    ),
    (
        re.compile(r"板栗|瓜子|锅巴|枣|糖葫芦|汤圆|酸辣粉|火锅底料|芝麻香油|椰子水|纯净水"),
        "Expenses:Food:Grocery",
    ),
]

DEFAULT_ALDI_CATEGORY = "Expenses:Food:Grocery"


class AldiItemCategorizer:
    """Categorize individual ALDI product items by keyword matching."""

    def categorize(self, item_name: str) -> str:
        for pattern, account in ALDI_ITEM_CATEGORIES:
            if pattern.search(item_name):
                return account
        return DEFAULT_ALDI_CATEGORY


class AldiImporter(PrecioussImporter):
    """Import transactions from ALDI (奥乐齐) JSON order exports.

    ALDI exports order data as JSON with an "orders" array. Each order contains:
    - orderCode: Unique order ID
    - date/time: Order date and time
    - store: Store name
    - channel: "线上" (online) or "门店" (in-store)
    - paymentAmount: Actual payment amount
    - productAmount: Sum of product prices
    - promotionAmount: Promotion discount
    - products: List of items with name, num, price
    - orderStatusName: "已完成" for completed orders
    """

    def __init__(self, account: str = "Assets:Clearing:ALDI", currency: str = "CNY"):
        self._account = account
        self._currency = currency
        self._item_categorizer = AldiItemCategorizer()

    def account_name(self) -> str:
        return self._account

    def identify(self, filepath: str | Path) -> bool:
        filepath = Path(filepath)
        if filepath.suffix.lower() != ".json":
            return False
        try:
            with open(filepath, encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict) or "orders" not in data:
                return False
            orders = data["orders"]
            if not isinstance(orders, list) or not orders:
                return False
            first = orders[0]
            if not isinstance(first, dict):
                return False
            if "orderCode" not in first or "store" not in first:
                return False
            store = first["store"]
            return "ALDI" in store or "奥乐齐" in store
        except Exception:
            return False

    def extract(self, filepath: str | Path) -> list[Transaction]:
        filepath = Path(filepath)
        with open(filepath, encoding="utf-8") as f:
            data = json.load(f)

        transactions = []
        for order in data["orders"]:
            if order.get("orderStatusName") != "已完成":
                continue
            tx = self._order_to_transaction(order)
            transactions.append(tx)
        return transactions

    def _order_to_transaction(self, order: dict) -> Transaction:
        # Categorize each product item
        categorized_items = []
        for p in order["products"]:
            category = self._item_categorizer.categorize(p["name"])
            categorized_items.append(
                {
                    "name": p["name"],
                    "num": p["num"],
                    "price": str(p["price"]),
                    "category": category,
                }
            )

        metadata: dict = {"aldi_items": categorized_items}
        if order.get("channel"):
            metadata["aldi_channel"] = order["channel"]
        promotion = Decimal(str(order.get("promotionAmount", 0)))
        if promotion:
            metadata["aldi_discount"] = str(promotion)

        dt = datetime.strptime(f"{order['date']} {order['time']}", "%Y-%m-%d %H:%M")
        payment_amount = Decimal(str(order["paymentAmount"]))

        return Transaction(
            date=dt,
            amount=-payment_amount,
            currency=self._currency,
            payee="ALDI奥乐齐",
            narration=order["store"],
            source_account=self._account,
            reference_id=order["orderCode"],
            tx_type="expense",
            metadata=metadata,
        )
