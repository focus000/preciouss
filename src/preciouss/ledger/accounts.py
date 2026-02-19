"""Account hierarchy definitions and helpers."""

from __future__ import annotations

# Default account hierarchy for Chinese personal finance
DEFAULT_ACCOUNTS = {
    # Assets
    "Assets:Bank:CMB": "招商银行储蓄卡",
    "Assets:Bank:ICBC": "工商银行储蓄卡",
    "Assets:Bank:CCB": "建设银行储蓄卡",
    "Assets:Bank:BOC": "中国银行储蓄卡",
    "Assets:Bank:ABC": "农业银行储蓄卡",
    "Assets:Bank:COMM": "交通银行储蓄卡",
    "Assets:Bank:CITIC": "中信银行储蓄卡",
    "Assets:Bank:SPDB": "浦发银行储蓄卡",
    "Assets:Bank:CIB": "兴业银行储蓄卡",
    "Assets:Bank:CMBC": "民生银行储蓄卡",
    "Assets:Bank:CEB": "光大银行储蓄卡",
    "Assets:Bank:PAB": "平安银行储蓄卡",
    "Assets:Bank:GDB": "广发银行储蓄卡",
    "Assets:Bank:PSBC": "邮储银行储蓄卡",
    "Assets:Bank:HSBC": "汇丰银行储蓄卡",
    "Assets:Bank:HSBC:HK": "汇丰香港储蓄账户",
    "Assets:Bank:BOC:HK": "中银香港储蓄账户",
    "Assets:Alipay": "支付宝余额",
    "Assets:WeChat": "微信钱包",
    "Assets:AlipayHK": "AlipayHK",
    "Assets:WeChatHK": "WeChatHK",
    "Assets:UnionPay": "云闪付",
    "Assets:PayPal": "PayPal",
    "Assets:Investment:IBKR": "Interactive Brokers",
    "Assets:JD": "京东",
    "Assets:JD:GiftCard": "京东购物卡",
    "Assets:JD:XiaoJinKu": "京东小金库",
    "Assets:Unknown": "未知支付账户",
    "Assets:WeChat:Unknown": "微信未识别付款方式",
    "Assets:Alipay:Unknown": "支付宝未识别付款方式",
    "Assets:JD:Unknown": "京东未识别付款方式",
    # Clearing accounts (cross-platform bridges)
    "Assets:Clearing:Costco": "Costco清算",
    "Assets:Clearing:ALDI": "ALDI清算",
    "Assets:Clearing:JD": "京东清算",
    "Assets:Clearing:JD:WX": "京东清算-微信",
    "Assets:Clearing:JD:Alipay": "京东清算-支付宝",
    "Assets:Clearing:JD:ApplePay": "京东清算-ApplePay",
    "Assets:Clearing:JD:Unknown": "京东清算-未知",
    "Assets:Clearing:WX:Unknown": "微信清算-未知",
    "Assets:Clearing:Alipay:Unknown": "支付宝清算-未知",
    # Liabilities
    "Liabilities:CreditCard:CMB": "招商银行信用卡",
    "Liabilities:CreditCard:ICBC": "工商银行信用卡",
    "Liabilities:CreditCard:CCB": "建设银行信用卡",
    "Liabilities:CreditCard:BOC": "中国银行信用卡",
    "Liabilities:CreditCard:ABC": "农业银行信用卡",
    "Liabilities:CreditCard:COMM": "交通银行信用卡",
    "Liabilities:CreditCard:CITIC": "中信银行信用卡",
    "Liabilities:CreditCard:SPDB": "浦发银行信用卡",
    "Liabilities:CreditCard:CIB": "兴业银行信用卡",
    "Liabilities:CreditCard:CMBC": "民生银行信用卡",
    "Liabilities:CreditCard:CEB": "光大银行信用卡",
    "Liabilities:CreditCard:PAB": "平安银行信用卡",
    "Liabilities:CreditCard:GDB": "广发银行信用卡",
    "Liabilities:CreditCard:PSBC": "邮储银行信用卡",
    "Liabilities:CreditCard:HSBC": "汇丰银行信用卡",
    "Liabilities:CreditCard:HSBC:HK": "汇丰香港信用卡",
    "Liabilities:CreditCard:BOC:HK": "中银香港信用卡",
    "Liabilities:JD:BaiTiao": "京东白条",
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
    "Expenses:Transfer": "转账支出",
    # Income
    "Income:Uncategorized": "未分类收入",
    "Income:Transfer": "转账收入",
    "Income:Salary": "工资",
    "Income:Bonus": "奖金",
    "Income:Investment": "投资收益",
    "Income:Interest": "利息收入",
    "Income:Refund": "退款",
    # Equity
    "Equity:Opening-Balances": "期初余额",
}

# Bank-specific clearing accounts are generated dynamically
# for each platform × card type × bank combination
_CLEARING_PLATFORMS = ["WX", "Alipay", "JD"]
_CLEARING_CARD_TYPES = {"CC": "信用卡", "Bank": "储蓄卡"}
_CLEARING_BANKS = [
    "CMB", "ICBC", "CCB", "BOC", "CITIC", "ABC", "COMM",
    "SPDB", "CIB", "CMBC", "CEB", "PAB", "GDB", "PSBC", "HSBC",
]

for _platform in _CLEARING_PLATFORMS:
    for _card_type, _card_desc in _CLEARING_CARD_TYPES.items():
        for _bank in _CLEARING_BANKS:
            _acct = f"Assets:Clearing:{_platform}:{_card_type}:{_bank}"
            DEFAULT_ACCOUNTS[_acct] = f"{_platform}清算-{_card_desc}-{_bank}"

# Default currencies
DEFAULT_CURRENCIES = ["CNY", "HKD", "USD", "EUR", "GBP", "JPY"]


def get_expense_account_for_type(tx_type: str | None) -> str:
    """Get a default expense account based on transaction type."""
    if tx_type == "income":
        return "Income:Uncategorized"
    return "Expenses:Uncategorized"
