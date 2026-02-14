"""Matching rule definitions for cross-platform transaction matching."""

from __future__ import annotations

# Platform keywords that appear in bank statements when a payment goes through a platform
PLATFORM_KEYWORDS: dict[str, list[str]] = {
    "alipay": ["支付宝", "alipay", "蚂蚁金服"],
    "wechat": ["财付通", "微信支付", "tenpay", "wechat"],
    "unionpay": ["云闪付", "银联在线", "unionpay"],
}

# Keywords in payment_method field that map to bank accounts
# e.g. "招商银行信用卡(尾号1234)" -> identifier pattern
PAYMENT_METHOD_PATTERNS: dict[str, str] = {
    "招商银行": "cmb",
    "工商银行": "icbc",
    "建设银行": "ccb",
    "中国银行": "boc",
    "交通银行": "comm",
    "农业银行": "abc",
    "花呗": "huabei",
    "余额宝": "yuebao",
    "余额": "alipay_balance",
}
