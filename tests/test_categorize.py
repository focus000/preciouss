"""Tests for the categorization system."""

from datetime import datetime
from decimal import Decimal

from preciouss.categorize.rules import RuleCategorizer
from preciouss.importers.base import Transaction


def _make_tx(
    payee: str, narration: str = "", raw_category: str = "", tx_type: str | None = None
) -> Transaction:
    return Transaction(
        date=datetime(2024, 1, 15),
        amount=Decimal("-35.00"),
        currency="CNY",
        payee=payee,
        narration=narration,
        source_account="Assets:Alipay",
        raw_category=raw_category,
        tx_type=tx_type,
    )


def test_keyword_categorization():
    """Keywords match against payee and narration."""
    categorizer = RuleCategorizer()

    assert categorizer.categorize(_make_tx("星巴克")) == "Expenses:Food:Coffee"
    assert categorizer.categorize(_make_tx("滴滴出行")) == "Expenses:Transport:Taxi"
    assert categorizer.categorize(_make_tx("美团外卖")) == "Expenses:Food:Delivery"


def test_regex_categorization():
    """Regex rules match complex patterns."""
    categorizer = RuleCategorizer()

    tx = _make_tx("某公司", "工资发放")
    assert categorizer.categorize(tx) == "Income:Salary"

    tx = _make_tx("某商户", "退款-商品退货")
    assert categorizer.categorize(tx) == "Income:Refund"


def test_custom_rules_override():
    """User-provided rules take priority."""
    custom = {"测试商户": "Expenses:Test"}
    categorizer = RuleCategorizer(keyword_rules=custom)

    assert categorizer.categorize(_make_tx("测试商户")) == "Expenses:Test"


def test_no_match_returns_none():
    """Unknown merchants return None."""
    categorizer = RuleCategorizer()
    assert categorizer.categorize(_make_tx("完全未知的商户")) is None


# --- Huawei campus specifics ---


def test_huawei_campus_food():
    """华为一卡通 should be Food:Restaurant, not Electronics."""
    categorizer = RuleCategorizer()
    assert categorizer.categorize(_make_tx("华为一卡通充值")) == "Expenses:Food:Restaurant"


def test_huawei_campus_restaurant():
    """Huawei campus restaurants should match Food:Restaurant."""
    categorizer = RuleCategorizer()
    assert categorizer.categorize(_make_tx("三牦记华为店")) == "Expenses:Food:Restaurant"
    assert categorizer.categorize(_make_tx("农耕记华为食堂")) == "Expenses:Food:Restaurant"


def test_huawei_medical():
    """Huawei campus clinic should match Health:Medical."""
    categorizer = RuleCategorizer()
    assert (
        categorizer.categorize(_make_tx("北京大学深圳医院华为门诊部")) == "Expenses:Health:Medical"
    )


def test_huawei_swimming():
    """Swimming pool should match Health:Fitness."""
    categorizer = RuleCategorizer()
    assert categorizer.categorize(_make_tx("游泳池店")) == "Expenses:Health:Fitness"


def test_huawei_wifi():
    """华为 WiFi subscription should match Housing:Utilities."""
    categorizer = RuleCategorizer()
    assert categorizer.categorize(_make_tx("华为支付 尊享年包套餐")) == "Expenses:Housing:Utilities"


def test_xiaomi_still_electronics():
    """小米 should still match Electronics."""
    categorizer = RuleCategorizer()
    assert categorizer.categorize(_make_tx("小米之家")) == "Expenses:Shopping:Electronics"


# --- Charging order fix ---


def test_powerbank_not_gas():
    """Power bank brands should match DailyGoods, not Transport:Gas."""
    categorizer = RuleCategorizer()
    assert (
        categorizer.categorize(_make_tx("来电科技 来电共享充电宝"))
        == "Expenses:Shopping:DailyGoods"
    )
    assert categorizer.categorize(_make_tx("怪兽充电")) == "Expenses:Shopping:DailyGoods"


# --- Mobile keyword fix ---


def test_china_mobile_telecom():
    """中国移动 should match Utilities."""
    categorizer = RuleCategorizer()
    assert categorizer.categorize(_make_tx("中国移动")) == "Expenses:Housing:Utilities"


def test_mobile_payment_not_telecom():
    """中国银行移动支付平台 should NOT match Utilities."""
    categorizer = RuleCategorizer()
    result = categorizer.categorize(_make_tx("中国银行移动支付平台"))
    assert result != "Expenses:Housing:Utilities"


# --- Transfer direction ---


def test_transfer_expense():
    """转账 expense goes to Expenses:Transfer."""
    categorizer = RuleCategorizer()
    tx = _make_tx("张三", "转账", "转账", tx_type="expense")
    assert categorizer.categorize(tx) == "Expenses:Transfer"


def test_transfer_income():
    """转账 income goes to Income:Transfer."""
    categorizer = RuleCategorizer()
    tx = _make_tx("张三", "转账", "转账", tx_type="income")
    assert categorizer.categorize(tx) == "Income:Transfer"


def test_group_collection_expense():
    """群收款 expense goes to Expenses:Transfer."""
    categorizer = RuleCategorizer()
    tx = _make_tx("李四", "群收款", "群收款", tx_type="expense")
    assert categorizer.categorize(tx) == "Expenses:Transfer"


def test_group_collection_income():
    """群收款 income goes to Income:Transfer."""
    categorizer = RuleCategorizer()
    tx = _make_tx("李四", "群收款", "群收款", tx_type="income")
    assert categorizer.categorize(tx) == "Income:Transfer"
