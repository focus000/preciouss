"""Payment account resolver — parse payment method strings into beancount accounts."""

from __future__ import annotations

# Bank name → short code mapping
BANK_PATTERNS: dict[str, str] = {
    "招商银行": "CMB",
    "工商银行": "ICBC",
    "建设银行": "CCB",
    "中国银行": "BOC",
    "中信银行": "CITIC",
    "农业银行": "ABC",
    "交通银行": "COMM",
    "浦发银行": "SPDB",
    "兴业银行": "CIB",
    "民生银行": "CMBC",
    "光大银行": "CEB",
    "平安银行": "PAB",
    "广发银行": "GDB",
    "邮储银行": "PSBC",
    "汇丰": "HSBC",
}

# Platform wallet exact matches
WALLET_ACCOUNTS: dict[str, str] = {
    "零钱": "Assets:WeChat",
    "零钱通": "Assets:WeChat",
    "余额": "Assets:Alipay",
    "余额宝": "Assets:Alipay",
    "京东白条": "Liabilities:JD:BaiTiao",
    "京东小金库": "Assets:JD:XiaoJinKu",
    # Cross-platform payment method names (not wallets, but platform routing)
    "微信支付": "Assets:WeChat",
    "财付通": "Assets:WeChat",
    "支付宝": "Assets:Alipay",
    "支付宝支付": "Assets:Alipay",
    "京东支付": "Assets:JD",
}

# Platform accounts that may need cross-platform resolution
PLATFORM_ACCOUNT_PREFIXES: set[str] = {
    "Assets:WeChat",
    "Assets:Alipay",
    "Assets:JD",
}

# Keywords used to identify platform transactions in other platforms' data
PLATFORM_KEYWORDS: dict[str, list[str]] = {
    "Assets:JD": ["京东", "JD", "jd.com"],
    "Assets:Alipay": ["支付宝", "Alipay"],
    "Assets:WeChat": ["微信", "财付通", "WeChat", "Tenpay"],
}


def is_platform_account(account: str) -> bool:
    """Check if an account is a platform account (not a terminal bank account)."""
    return account in PLATFORM_ACCOUNT_PREFIXES


def resolve_payment_account(
    payment_method: str,
    fallback_account: str,
    default_card_type: str = "Liabilities:CreditCard",
) -> str:
    """Resolve a payment method string into a beancount account name.

    Args:
        payment_method: Raw payment method string from CSV (e.g. "招商银行信用卡(0913)")
        fallback_account: Account to use when resolution fails
        default_card_type: Default card type prefix when ambiguous (no 信用卡/储蓄卡 keyword)

    Returns:
        Resolved beancount account string.
    """
    method = payment_method.strip()
    if not method:
        return fallback_account

    # 1. Platform wallet prefix match (longest first, handles "微信支付信用卡" → "微信支付")
    for keyword, account in sorted(WALLET_ACCOUNTS.items(), key=lambda x: -len(x[0])):
        if method.startswith(keyword):
            return account

    # 2. Composite format: "微信-招商银行储蓄卡" → take part after "-"
    if "-" in method:
        parts = method.split("-", 1)
        return resolve_payment_account(parts[1], fallback_account, default_card_type)

    # 3. Detect card type
    if "储蓄卡" in method:
        card_prefix = "Assets:Bank"
    elif "信用卡" in method:
        card_prefix = "Liabilities:CreditCard"
    else:
        card_prefix = default_card_type

    # 4. Extract bank name
    for bank_name, bank_code in BANK_PATTERNS.items():
        if bank_name in method:
            return f"{card_prefix}:{bank_code}"

    return fallback_account
