"""Costco JSON receipt importer."""

from __future__ import annotations

import json
import re
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from preciouss.importers.base import PrecioussImporter, Transaction

# Keyword patterns → expense account mapping for individual items
COSTCO_ITEM_CATEGORIES: list[tuple[re.Pattern[str], str]] = [
    # 个护/日用
    (
        re.compile(r"洗发|沐浴|牙膏|纸巾|卫生|洗衣|清洁|厨房纸|保鲜"),
        "Expenses:Shopping:DailyGoods",
    ),
    # 服饰
    (
        re.compile(r"服装|衣|裤|鞋|袜|内衣|外套|帽"),
        "Expenses:Shopping:Clothing",
    ),
    # 电子
    (
        re.compile(r"电子|耳机|充电|数码|电器|手表"),
        "Expenses:Shopping:Electronics",
    ),
    # 家居
    (
        re.compile(r"家具|床|椅|桌|收纳|家居"),
        "Expenses:Shopping:Household",
    ),
    # 食品 — meat/seafood/produce/snacks/dairy (default fallthrough also handles these)
    (
        re.compile(
            r"牛肉|猪肉|鸡肉|羊肉|排骨|五花"
            r"|三文鱼|海鲜|虾|鱼"
            r"|蔬菜|水果|沙拉"
            r"|坚果|零食|饼干|巧克力|糖|果汁|饮料|牛奶|奶酪|酸奶|鸡蛋|面包|米|面"
        ),
        "Expenses:Food:Grocery",
    ),
]

DEFAULT_COSTCO_CATEGORY = "Expenses:Food:Grocery"


class CostcoItemCategorizer:
    """Categorize individual Costco product items by keyword matching."""

    def categorize(self, item_name: str) -> str:
        for pattern, account in COSTCO_ITEM_CATEGORIES:
            if pattern.search(item_name):
                return account
        return DEFAULT_COSTCO_CATEGORY


class CostcoImporter(PrecioussImporter):
    """Import transactions from Costco JSON receipt exports.

    Costco exports receipt data as JSON with a top-level structure:
    - code: "000000"
    - success: true
    - data:
      - barcode: store code + 10-digit merchant order + register + datetime
      - itemList: list of purchased items
      - actualPayment: amount actually paid
      - totalPrice: sum of listed prices
      - cashDiscount: discount amount (negative)
      - transTime: "YYYY-MM-DD HH:MM:SS"
      - warehouseName: store name

    The barcode[4:14] extracts the 10-digit merchant order number used to
    match against Alipay/WeChat counterpart_ref for payment resolution.
    """

    def __init__(self, account: str = "Assets:Clearing:Costco", currency: str = "CNY"):
        self._account = account
        self._currency = currency
        self._categorizer = CostcoItemCategorizer()

    def account_name(self) -> str:
        return self._account

    def identify(self, filepath: str | Path) -> bool:
        filepath = Path(filepath)
        if filepath.suffix.lower() != ".json":
            return False
        try:
            with open(filepath, encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return False
            if not all(k in data for k in ("code", "data", "success")):
                return False
            inner = data["data"]
            if not isinstance(inner, dict):
                return False
            return all(k in inner for k in ("barcode", "itemList", "actualPayment"))
        except Exception:
            return False

    def extract(self, filepath: str | Path) -> list[Transaction]:
        filepath = Path(filepath)
        with open(filepath, encoding="utf-8") as f:
            data = json.load(f)
        if not data.get("success"):
            return []
        return [self._data_to_transaction(data["data"])]

    def _data_to_transaction(self, data: dict) -> Transaction:
        barcode = data["barcode"]
        merchant_order = barcode[4:14]  # 10-digit merchant order number

        items = [
            {
                "name": item["itemName"],
                "num": int(item["amount"]),
                "price": str(item["unitPrice"]),
                "category": self._categorizer.categorize(item["itemName"]),
            }
            for item in data["itemList"]
        ]

        meta: dict = {"costco_items": items}
        cash_discount = data.get("cashDiscount")
        if cash_discount:
            meta["costco_discount"] = str(abs(Decimal(str(cash_discount))))

        return Transaction(
            date=datetime.strptime(data["transTime"], "%Y-%m-%d %H:%M:%S"),
            amount=-Decimal(str(data["actualPayment"])),
            currency=self._currency,
            payee="Costco",
            narration=data["warehouseName"],
            source_account=self._account,
            reference_id=barcode,
            counterpart_ref=merchant_order,
            tx_type="expense",
            metadata=meta,
        )
