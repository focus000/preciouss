"""Tests for clearing account routing (replacing cross-platform resolution)."""

from __future__ import annotations

from preciouss.importers.clearing import (
    detect_merchant_clearing,
    is_clearing_account,
    resolve_payment_to_clearing,
)


class TestResolvePaymentToClearing:
    """resolve_payment_to_clearing: payment method → clearing account."""

    def test_internal_wallet_wechat(self):
        assert resolve_payment_to_clearing("零钱", "WX") == "Assets:WeChat"

    def test_internal_wallet_wechat_lingqiantong(self):
        assert resolve_payment_to_clearing("零钱通", "WX") == "Assets:WeChat"

    def test_internal_wallet_alipay(self):
        assert resolve_payment_to_clearing("余额", "Alipay") == "Assets:Alipay"

    def test_internal_wallet_alipay_yuebao(self):
        assert resolve_payment_to_clearing("余额宝", "Alipay") == "Assets:Alipay"

    def test_internal_wallet_jd_baitiao(self):
        assert resolve_payment_to_clearing("京东白条", "JD") == "Liabilities:JD:BaiTiao"

    def test_internal_wallet_jd_xiaojinku(self):
        assert resolve_payment_to_clearing("京东小金库", "JD") == "Assets:JD:XiaoJinKu"

    def test_credit_card_wechat(self):
        result = resolve_payment_to_clearing("招商银行信用卡(0913)", "WX")
        assert result == "Assets:Clearing:WX:CC:CMB"

    def test_debit_card_wechat(self):
        result = resolve_payment_to_clearing("招商银行储蓄卡(5678)", "WX")
        assert result == "Assets:Clearing:WX:Bank:CMB"

    def test_credit_card_alipay(self):
        result = resolve_payment_to_clearing("招商银行信用卡(尾号1234)", "Alipay")
        assert result == "Assets:Clearing:Alipay:CC:CMB"

    def test_credit_card_jd(self):
        result = resolve_payment_to_clearing("招商银行信用卡", "JD")
        assert result == "Assets:Clearing:JD:CC:CMB"

    def test_debit_card_jd(self):
        result = resolve_payment_to_clearing("招商银行储蓄卡", "JD")
        assert result == "Assets:Clearing:JD:Bank:CMB"

    def test_icbc_credit(self):
        result = resolve_payment_to_clearing("工商银行信用卡(1234)", "WX")
        assert result == "Assets:Clearing:WX:CC:ICBC"

    def test_platform_wechat_from_jd(self):
        """JD sees '微信支付' → route to JD:WX clearing."""
        result = resolve_payment_to_clearing("微信支付", "JD")
        assert result == "Assets:Clearing:JD:WX"

    def test_platform_alipay_from_jd(self):
        result = resolve_payment_to_clearing("支付宝", "JD")
        assert result == "Assets:Clearing:JD:Alipay"

    def test_composite_wechat_bank(self):
        """'微信-招商银行信用卡' → extract 微信 → JD:WX clearing."""
        result = resolve_payment_to_clearing("微信-招商银行信用卡", "JD")
        assert result == "Assets:Clearing:JD:WX"

    def test_unknown_fallback(self):
        result = resolve_payment_to_clearing("某某未知方式", "WX")
        assert result == "Assets:Clearing:WX:Unknown"

    def test_empty_payment(self):
        result = resolve_payment_to_clearing("", "WX")
        assert result == "Assets:Clearing:WX:Unknown"

    def test_slash_payment(self):
        result = resolve_payment_to_clearing("/", "JD")
        assert result == "Assets:Clearing:JD:Unknown"


class TestDetectMerchantClearing:
    """detect_merchant_clearing: payee/narration → clearing account."""

    def test_costco_in_payee(self):
        result = detect_merchant_clearing("WX", "Costco", "开心购物")
        assert result == "Assets:Clearing:Costco"

    def test_costco_keyword_kaishike(self):
        result = detect_merchant_clearing("WX", "开市客", "购物")
        assert result == "Assets:Clearing:Costco"

    def test_aldi_in_payee(self):
        result = detect_merchant_clearing("WX", "ALDI奥乐齐", "线下门店")
        assert result == "Assets:Clearing:ALDI"

    def test_jd_in_payee(self):
        """JD has sub-clearing, so includes platform suffix."""
        result = detect_merchant_clearing("WX", "京东", "京东购物")
        assert result == "Assets:Clearing:JD:WX"

    def test_jd_from_alipay(self):
        result = detect_merchant_clearing("Alipay", "京东", "购物")
        assert result == "Assets:Clearing:JD:Alipay"

    def test_no_match_returns_none(self):
        result = detect_merchant_clearing("WX", "星巴克", "拿铁咖啡")
        assert result is None

    def test_costco_case_insensitive(self):
        result = detect_merchant_clearing("WX", "costco", "购物")
        assert result == "Assets:Clearing:Costco"


class TestIsClearingAccount:
    def test_clearing(self):
        assert is_clearing_account("Assets:Clearing:Costco")
        assert is_clearing_account("Assets:Clearing:WX:CC:CMB")

    def test_not_clearing(self):
        assert not is_clearing_account("Assets:WeChat")
        assert not is_clearing_account("Liabilities:CreditCard:CMB")
