"""Account hierarchy definitions and helpers."""

from __future__ import annotations

# Default account hierarchy for Chinese personal finance
DEFAULT_ACCOUNTS = {
    # Assets
    "Assets:Bank:CMB": "招商银行储蓄卡",
    "Assets:Bank:ICBC": "工商银行储蓄卡",
    "Assets:Bank:CCB": "建设银行储蓄卡",
    "Assets:Bank:BOC": "中国银行储蓄卡",
    "Assets:Bank:HSBC:HK": "汇丰香港储蓄账户",
    "Assets:Bank:BOC:HK": "中银香港储蓄账户",
    "Assets:Alipay": "支付宝余额",
    "Assets:WeChat": "微信钱包",
    "Assets:AlipayHK": "AlipayHK",
    "Assets:WeChatHK": "WeChatHK",
    "Assets:UnionPay": "云闪付",
    "Assets:PayPal": "PayPal",
    "Assets:Investment:IBKR": "Interactive Brokers",
    # Liabilities
    "Liabilities:CreditCard:CMB": "招商银行信用卡",
    "Liabilities:CreditCard:ICBC": "工商银行信用卡",
    "Liabilities:CreditCard:CCB": "建设银行信用卡",
    "Liabilities:CreditCard:BOC": "中国银行信用卡",
    "Liabilities:CreditCard:HSBC:HK": "汇丰香港信用卡",
    "Liabilities:CreditCard:BOC:HK": "中银香港信用卡",
    # Expenses
    "Expenses:Food:Restaurant": "餐饮",
    "Expenses:Food:Coffee": "咖啡",
    "Expenses:Food:Delivery": "外卖",
    "Expenses:Food:Grocery": "超市",
    "Expenses:Transport:Taxi": "打车",
    "Expenses:Transport:PublicTransit": "公交地铁",
    "Expenses:Transport:Parking": "停车",
    "Expenses:Transport:Gas": "加油",
    "Expenses:Housing:Rent": "房租",
    "Expenses:Housing:PropertyFee": "物业",
    "Expenses:Housing:Utilities": "水电燃气",
    "Expenses:Shopping:Clothing": "服饰",
    "Expenses:Shopping:Electronics": "数码",
    "Expenses:Shopping:DailyGoods": "日用品",
    "Expenses:Shopping:HomeGoods": "家居",
    "Expenses:Entertainment:Movie": "电影",
    "Expenses:Entertainment:Games": "游戏",
    "Expenses:Entertainment:Subscription": "订阅",
    "Expenses:Entertainment:Travel": "旅行",
    "Expenses:Health:Medical": "医疗",
    "Expenses:Health:Medicine": "药品",
    "Expenses:Health:Fitness": "运动健身",
    "Expenses:Education:Books": "书籍",
    "Expenses:Education:Courses": "课程",
    "Expenses:Education:Training": "培训",
    "Expenses:Finance:Fees": "手续费",
    "Expenses:Finance:Interest": "利息支出",
    "Expenses:Finance:Insurance": "保险",
    "Expenses:Uncategorized": "未分类支出",
    # Income
    "Income:Uncategorized": "未分类收入",
    "Income:Salary": "工资",
    "Income:Bonus": "奖金",
    "Income:Investment": "投资收益",
    "Income:Interest": "利息收入",
    "Income:Refund": "退款",
    # Equity
    "Equity:Opening-Balances": "期初余额",
}

# Default currencies
DEFAULT_CURRENCIES = ["CNY", "HKD", "USD", "EUR", "GBP", "JPY"]


def get_expense_account_for_type(tx_type: str | None) -> str:
    """Get a default expense account based on transaction type."""
    if tx_type == "income":
        return "Income:Uncategorized"
    return "Expenses:Uncategorized"
