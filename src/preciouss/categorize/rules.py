"""Rule-based transaction categorization."""

from __future__ import annotations

import re

from preciouss.importers.base import Transaction

# Default keyword-to-category mapping
# More specific keywords should come before generic ones
DEFAULT_RULES: dict[str, str] = {
    # JD platform categories (raw_category matching)
    "数码电器": "Expenses:Shopping:Electronics",
    "手机通讯": "Expenses:Shopping:Electronics",
    "电脑办公": "Expenses:Shopping:Electronics",
    "家用电器": "Expenses:Shopping:Electronics",
    "美妆个护": "Expenses:Shopping:DailyGoods",
    "清洁纸品": "Expenses:Shopping:DailyGoods",
    "日用百货": "Expenses:Shopping:DailyGoods",
    "鞋服箱包": "Expenses:Shopping:Clothing",
    "食品酒饮": "Expenses:Food:Grocery",
    "家居家装": "Expenses:Shopping:HomeGoods",
    "图书文娱": "Expenses:Education:Books",
    "教育培训": "Expenses:Education:Courses",
    "运动户外": "Expenses:Health:Fitness",
    "医疗保健": "Expenses:Health:Medical",
    "生活服务": "Expenses:Shopping:DailyGoods",
    "12306": "Expenses:Transport:PublicTransit",
    # Huawei campus specific (MUST be before any generic "华为" rule)
    "华为一卡通": "Expenses:Food:Restaurant",
    "捷华餐饮": "Expenses:Food:Restaurant",
    "农耕记": "Expenses:Food:Restaurant",
    "三牦记": "Expenses:Food:Restaurant",
    "食堂": "Expenses:Food:Restaurant",
    # Coffee
    "星巴克": "Expenses:Food:Coffee",
    "starbucks": "Expenses:Food:Coffee",
    "瑞幸": "Expenses:Food:Coffee",
    "luckin": "Expenses:Food:Coffee",
    "costa coffee": "Expenses:Food:Coffee",
    "costa": "Expenses:Food:Coffee",
    "manner coffee": "Expenses:Food:Coffee",
    "manner": "Expenses:Food:Coffee",
    "太平洋咖啡": "Expenses:Food:Coffee",
    "seesaw": "Expenses:Food:Coffee",
    "蓝瓶咖啡": "Expenses:Food:Coffee",
    "arabica": "Expenses:Food:Coffee",
    "阿拉比卡": "Expenses:Food:Coffee",
    "咖啡": "Expenses:Food:Coffee",
    "coffee": "Expenses:Food:Coffee",
    "café": "Expenses:Food:Coffee",
    "cafe": "Expenses:Food:Coffee",
    # Transport - taxi/ride-hailing
    "滴滴出行": "Expenses:Transport:Taxi",
    "滴滴": "Expenses:Transport:Taxi",
    "高德打车": "Expenses:Transport:Taxi",
    "阳光出行": "Expenses:Transport:Taxi",
    "享道出行": "Expenses:Transport:Taxi",
    "灵犀出行": "Expenses:Transport:Taxi",
    "出租车": "Expenses:Transport:Taxi",
    "如祺": "Expenses:Transport:Taxi",
    # Transport - public transit
    "地铁": "Expenses:Transport:PublicTransit",
    "轨道交通": "Expenses:Transport:PublicTransit",
    "公交": "Expenses:Transport:PublicTransit",
    "长安通": "Expenses:Transport:PublicTransit",
    "深圳通": "Expenses:Transport:PublicTransit",
    "机场快线": "Expenses:Transport:PublicTransit",
    # Transport - bike/shared mobility
    "青桔单车": "Expenses:Transport:PublicTransit",
    "哈啰": "Expenses:Transport:PublicTransit",
    "广州骑安": "Expenses:Transport:PublicTransit",
    "小遛共享": "Expenses:Transport:PublicTransit",
    # Transport - moving/freight
    "货拉拉": "Expenses:Transport:Taxi",
    # Food - delivery
    "美团外卖": "Expenses:Food:Delivery",
    "饿了么": "Expenses:Food:Delivery",
    # Food - fast food
    "麦当劳": "Expenses:Food:Restaurant",
    "金拱门": "Expenses:Food:Restaurant",
    "肯德基": "Expenses:Food:Restaurant",
    "kfc": "Expenses:Food:Restaurant",
    "汉堡王": "Expenses:Food:Restaurant",
    "棒约翰": "Expenses:Food:Restaurant",
    "pizzahut": "Expenses:Food:Restaurant",
    "必胜客": "Expenses:Food:Restaurant",
    "老乡鸡": "Expenses:Food:Restaurant",
    "嘉旺": "Expenses:Food:Restaurant",
    # Food - restaurants (from real data)
    "餐饮": "Expenses:Food:Restaurant",
    "餐厅": "Expenses:Food:Restaurant",
    "酒家": "Expenses:Food:Restaurant",
    "饭店": "Expenses:Food:Restaurant",
    "面馆": "Expenses:Food:Restaurant",
    "烤肉": "Expenses:Food:Restaurant",
    "火锅": "Expenses:Food:Restaurant",
    "海底捞": "Expenses:Food:Restaurant",
    "串串": "Expenses:Food:Restaurant",
    "牛肉面": "Expenses:Food:Restaurant",
    "拉面": "Expenses:Food:Restaurant",
    "小面": "Expenses:Food:Restaurant",
    "米线": "Expenses:Food:Restaurant",
    "面点王": "Expenses:Food:Restaurant",
    "魏家凉皮": "Expenses:Food:Restaurant",
    "凉皮": "Expenses:Food:Restaurant",
    "肉夹馍": "Expenses:Food:Restaurant",
    "美团平台商户": "Expenses:Food:Restaurant",
    "美团": "Expenses:Food:Restaurant",
    "大众点评": "Expenses:Food:Restaurant",
    "喜家德": "Expenses:Food:Restaurant",
    "和府捞面": "Expenses:Food:Restaurant",
    "太二": "Expenses:Food:Restaurant",
    "奈雪": "Expenses:Food:Restaurant",
    "1点点": "Expenses:Food:Restaurant",
    "书亦": "Expenses:Food:Restaurant",
    "甜品": "Expenses:Food:Restaurant",
    "烘焙": "Expenses:Food:Restaurant",
    # Food - grocery/supermarket
    "华润万家": "Expenses:Food:Grocery",
    "沃尔玛": "Expenses:Food:Grocery",
    "盒马": "Expenses:Food:Grocery",
    "永辉超市": "Expenses:Food:Grocery",
    "超市": "Expenses:Food:Grocery",
    "便利店": "Expenses:Food:Grocery",
    "7-eleven": "Expenses:Food:Grocery",
    "全家": "Expenses:Food:Grocery",
    "familymart": "Expenses:Food:Grocery",
    "lawson": "Expenses:Food:Grocery",
    "罗森": "Expenses:Food:Grocery",
    "美宜佳": "Expenses:Food:Grocery",
    "百果园": "Expenses:Food:Grocery",
    "水果": "Expenses:Food:Grocery",
    "赛壹便利": "Expenses:Food:Grocery",
    "唐久便利": "Expenses:Food:Grocery",
    "每一天便利": "Expenses:Food:Grocery",
    "苏果超市": "Expenses:Food:Grocery",
    "大润发": "Expenses:Food:Grocery",
    "卜蜂莲花": "Expenses:Food:Grocery",
    "宜家": "Expenses:Shopping:HomeGoods",
    # Shopping - clothing
    "优衣库": "Expenses:Shopping:Clothing",
    "uniqlo": "Expenses:Shopping:Clothing",
    "adidas": "Expenses:Shopping:Clothing",
    "阿迪达斯": "Expenses:Shopping:Clothing",
    "迪卡侬": "Expenses:Shopping:Clothing",
    "lululemon": "Expenses:Shopping:Clothing",
    "露露乐蒙": "Expenses:Shopping:Clothing",
    "名创优品": "Expenses:Shopping:DailyGoods",
    "无印良品": "Expenses:Shopping:DailyGoods",
    "muji": "Expenses:Shopping:DailyGoods",
    # Shopping - electronics
    "小米": "Expenses:Shopping:Electronics",
    # Shopping - online
    "京东": "Expenses:Shopping:DailyGoods",
    "淘宝": "Expenses:Shopping:DailyGoods",
    "拼多多": "Expenses:Shopping:DailyGoods",
    # Entertainment
    "万达电影": "Expenses:Entertainment:Movie",
    "电影": "Expenses:Entertainment:Movie",
    "影院": "Expenses:Entertainment:Movie",
    "影城": "Expenses:Entertainment:Movie",
    "深圳大剧院": "Expenses:Entertainment:Movie",
    "深圳音乐厅": "Expenses:Entertainment:Movie",
    "steam": "Expenses:Entertainment:Games",
    "valve": "Expenses:Entertainment:Games",
    "博物馆": "Expenses:Entertainment:Travel",
    "携程": "Expenses:Entertainment:Travel",
    "艺龙": "Expenses:Entertainment:Travel",
    "同程": "Expenses:Entertainment:Travel",
    "希尔顿": "Expenses:Entertainment:Travel",
    "酒店": "Expenses:Entertainment:Travel",
    "知乎": "Expenses:Entertainment:Subscription",
    "极客时间": "Expenses:Entertainment:Subscription",
    "bilibili": "Expenses:Entertainment:Subscription",
    "上海宽娱": "Expenses:Entertainment:Subscription",
    "奈飞": "Expenses:Entertainment:Subscription",
    "netflix": "Expenses:Entertainment:Subscription",
    "leetcode": "Expenses:Entertainment:Subscription",
    "力扣": "Expenses:Entertainment:Subscription",
    # Housing
    "物业": "Expenses:Housing:PropertyFee",
    "万科物业": "Expenses:Housing:PropertyFee",
    "公寓": "Expenses:Housing:Rent",
    "房租": "Expenses:Housing:Rent",
    "水电": "Expenses:Housing:Utilities",
    "燃气": "Expenses:Housing:Utilities",
    "生活缴费": "Expenses:Housing:Utilities",
    # Health
    "门诊部": "Expenses:Health:Medical",
    "门诊": "Expenses:Health:Medical",
    "诊中支付": "Expenses:Health:Medical",
    "医院": "Expenses:Health:Medical",
    "药房": "Expenses:Health:Medicine",
    "药店": "Expenses:Health:Medicine",
    "宠物医院": "Expenses:Health:Medical",
    "游泳池": "Expenses:Health:Fitness",
    "游泳": "Expenses:Health:Fitness",
    "健身房": "Expenses:Health:Fitness",
    "健身": "Expenses:Health:Fitness",
    "捷安特": "Expenses:Health:Fitness",
    # Education
    "书店": "Expenses:Education:Books",
    "图书": "Expenses:Education:Books",
    "三联生活": "Expenses:Education:Books",
    "课程": "Expenses:Education:Courses",
    "培训": "Expenses:Education:Training",
    "兰州大学": "Expenses:Education:Courses",
    # Finance
    "手续费": "Expenses:Finance:Fees",
    "利息": "Expenses:Finance:Interest",
    "保险": "Expenses:Finance:Insurance",
    # Logistics
    "顺丰": "Expenses:Shopping:DailyGoods",
    "丰巢": "Expenses:Shopping:DailyGoods",
    "中国邮政": "Expenses:Shopping:DailyGoods",
    # Telecom
    "联通": "Expenses:Housing:Utilities",
    "电信": "Expenses:Housing:Utilities",
    "中国移动": "Expenses:Housing:Utilities",
    "手机充值": "Expenses:Housing:Utilities",
    "尊享年包套餐": "Expenses:Housing:Utilities",
    # Charging - power bank (MUST be before generic "充电")
    "来电科技": "Expenses:Shopping:DailyGoods",
    "街电": "Expenses:Shopping:DailyGoods",
    "小电": "Expenses:Shopping:DailyGoods",
    "怪兽充电": "Expenses:Shopping:DailyGoods",
    "充电宝": "Expenses:Shopping:DailyGoods",
    # EV/scooter charging (generic, after brands)
    "充电": "Expenses:Transport:Gas",
    # Government
    "出入境": "Expenses:Finance:Fees",
    "身份证": "Expenses:Finance:Fees",
}

# Regex rules for more complex patterns
DEFAULT_REGEX_RULES: list[tuple[str, str]] = [
    (r"美团.*外卖", "Expenses:Food:Delivery"),
    (r"uber.*eats", "Expenses:Food:Delivery"),
    (r"工资|薪资|salary", "Income:Salary"),
    (r"退款|退货", "Income:Refund"),
    (r"利息.*收入", "Income:Interest"),
    (r"红包", "Income:Uncategorized"),
    (r"信用卡还款", "Expenses:Finance:Fees"),
    (r"转账", "Expenses:Uncategorized"),
]


class RuleCategorizer:
    """Categorize transactions using keyword and regex rules."""

    def __init__(
        self,
        keyword_rules: dict[str, str] | None = None,
        regex_rules: list[tuple[str, str]] | None = None,
    ):
        self.keyword_rules = {**DEFAULT_RULES}
        if keyword_rules:
            # User rules override defaults
            self.keyword_rules.update(keyword_rules)

        self.regex_rules = list(DEFAULT_REGEX_RULES)
        if regex_rules:
            self.regex_rules = regex_rules + self.regex_rules

    def categorize(self, tx: Transaction) -> str | None:
        """Try to categorize a transaction. Returns account name or None."""
        text = f"{tx.payee} {tx.narration}".lower()
        if tx.raw_category:
            text += f" {tx.raw_category}".lower()

        # Try keyword matching first (exact substring)
        for keyword, category in self.keyword_rules.items():
            if keyword.lower() in text:
                return category

        # Try regex matching
        for pattern, category in self.regex_rules:
            if re.search(pattern, text, re.IGNORECASE):
                return category

        return None
