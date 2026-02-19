"""Clearing account routing for cross-platform transactions.

Core principle: if a payment method doesn't belong to the current platform,
route it through a clearing account. Each data source imports independently;
clearing accounts bridge cross-source transactions.
"""

from __future__ import annotations

from preciouss.importers.resolve import BANK_PATTERNS

# --- Merchant clearing configuration ---

# Known merchants: name → has_sub_clearing (whether to subdivide by payment platform)
CLEARING_MERCHANTS: dict[str, bool] = {
    "Costco": False,  # Receipt only, no payment-side subdivision
    "ALDI": False,  # Receipt only, no payment-side subdivision
    "JD": True,  # Has transaction flow, subdivide by payment channel
}

# Merchant keywords → merchant name
MERCHANT_KEYWORDS: dict[str, list[str]] = {
    "Costco": ["Costco", "开市客"],
    "ALDI": ["ALDI", "奥乐齐"],
    "JD": ["京东", "JD", "jd.com"],
}

# --- Platform/channel configuration ---

# Payment channel identifiers → channel code
PLATFORM_IDENTIFIERS: dict[str, list[str]] = {
    "WX": ["微信", "财付通", "WeChat", "Tenpay"],
    "Alipay": ["支付宝", "Alipay"],
    "ApplePay": ["Apple"],
}

# Platform-internal accounts (do not go through clearing)
PLATFORM_INTERNAL_ACCOUNTS: dict[str, dict[str, str]] = {
    "WX": {"零钱": "Assets:WeChat", "零钱通": "Assets:WeChat"},
    "Alipay": {"余额": "Assets:Alipay", "余额宝": "Assets:Alipay"},
    "JD": {
        "白条": "Liabilities:JD:BaiTiao",
        "京东白条": "Liabilities:JD:BaiTiao",
        "小金库": "Assets:JD:XiaoJinKu",
        "京东小金库": "Assets:JD:XiaoJinKu",
    },
}


def detect_merchant_clearing(my_platform: str, payee: str, narration: str) -> str | None:
    """Detect known merchant → clearing account.

    If the merchant has sub-clearing → Assets:Clearing:<MERCHANT>:<MY_PLATFORM>
    If the merchant has no sub-clearing → Assets:Clearing:<MERCHANT>
    If not a known merchant → None (use categorizer)
    """
    text = f"{payee} {narration}".lower()
    for merchant, keywords in MERCHANT_KEYWORDS.items():
        if any(kw.lower() in text for kw in keywords):
            has_sub = CLEARING_MERCHANTS.get(merchant, False)
            if has_sub:
                return f"Assets:Clearing:{merchant}:{my_platform}"
            return f"Assets:Clearing:{merchant}"
    return None


def resolve_payment_to_clearing(payment_method: str, platform: str) -> str:
    """Resolve payment method string → clearing account. Shared logic for all platforms.

    Resolution order:
    1. Platform-internal accounts (零钱/余额/白条) → direct account
    2. Composite "platform-bank card" format → extract platform → clearing
    3. Known platform keywords → Assets:Clearing:<MY>:<PLATFORM>
    4. Credit card → Assets:Clearing:<MY>:CC:<BANK>
    5. Debit card → Assets:Clearing:<MY>:Bank:<BANK>
    6. Fallback → Assets:Clearing:<MY>:Unknown
    """
    method = payment_method.strip()
    if not method or method == "/":
        return f"Assets:Clearing:{platform}:Unknown"

    # 1. Platform-internal accounts (longest match first)
    internal = PLATFORM_INTERNAL_ACCOUNTS.get(platform, {})
    for keyword, account in sorted(internal.items(), key=lambda x: -len(x[0])):
        if method.startswith(keyword):
            return account

    # 2. Composite format: "微信-招商银行储蓄卡" → extract "微信" → clearing
    if "-" in method:
        parts = method.split("-", 1)
        prefix = parts[0].strip()
        # Check if prefix is a known platform
        for channel_code, keywords in PLATFORM_IDENTIFIERS.items():
            if any(kw in prefix for kw in keywords):
                return f"Assets:Clearing:{platform}:{channel_code}"
        # If prefix is not a platform, try resolving the part after "-"
        return resolve_payment_to_clearing(parts[1], platform)

    # 3. Known platform keywords
    for channel_code, keywords in PLATFORM_IDENTIFIERS.items():
        if any(kw in method for kw in keywords):
            return f"Assets:Clearing:{platform}:{channel_code}"

    # 4/5. Bank card detection
    if "储蓄卡" in method:
        card_prefix = "Bank"
    elif "信用卡" in method:
        card_prefix = "CC"
    else:
        card_prefix = "CC"  # default to credit card

    for bank_name, bank_code in BANK_PATTERNS.items():
        if bank_name in method:
            return f"Assets:Clearing:{platform}:{card_prefix}:{bank_code}"

    # 6. Fallback
    return f"Assets:Clearing:{platform}:Unknown"


def is_clearing_account(account: str) -> bool:
    """Check if an account is a clearing account."""
    return account.startswith("Assets:Clearing:")
