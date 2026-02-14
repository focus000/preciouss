"""Category taxonomy definition."""

from __future__ import annotations

# Expense categories with Chinese labels
EXPENSE_TAXONOMY: dict[str, dict[str, str]] = {
    "Expenses:Food": {
        "Restaurant": "餐饮",
        "Coffee": "咖啡",
        "Delivery": "外卖",
        "Grocery": "超市",
    },
    "Expenses:Transport": {
        "Taxi": "打车",
        "PublicTransit": "公交地铁",
        "Parking": "停车",
        "Gas": "加油",
    },
    "Expenses:Housing": {
        "Rent": "房租",
        "PropertyFee": "物业",
        "Utilities": "水电燃气",
    },
    "Expenses:Shopping": {
        "Clothing": "服饰",
        "Electronics": "数码",
        "DailyGoods": "日用品",
        "HomeGoods": "家居",
    },
    "Expenses:Entertainment": {
        "Movie": "电影",
        "Games": "游戏",
        "Subscription": "订阅",
        "Travel": "旅行",
    },
    "Expenses:Health": {
        "Medical": "医疗",
        "Medicine": "药品",
        "Fitness": "运动健身",
    },
    "Expenses:Education": {
        "Books": "书籍",
        "Courses": "课程",
        "Training": "培训",
    },
    "Expenses:Finance": {
        "Fees": "手续费",
        "Interest": "利息支出",
        "Insurance": "保险",
    },
}

INCOME_TAXONOMY: dict[str, str] = {
    "Income:Salary": "工资",
    "Income:Bonus": "奖金",
    "Income:Investment": "投资收益",
    "Income:Interest": "利息收入",
    "Income:Refund": "退款",
}


def get_all_categories() -> list[str]:
    """Return a flat list of all category account names."""
    categories = []
    for parent, children in EXPENSE_TAXONOMY.items():
        for child in children:
            categories.append(f"{parent}:{child}")
    categories.extend(INCOME_TAXONOMY.keys())
    return categories
