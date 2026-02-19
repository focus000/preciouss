"""Tests for payment account resolver."""

from preciouss.importers.resolve import is_platform_account, resolve_payment_account


class TestResolveCreditCard:
    def test_explicit_credit_card(self):
        result = resolve_payment_account("招商银行信用卡(0913)", "Assets:Unknown")
        assert result == "Liabilities:CreditCard:CMB"

    def test_alipay_format_credit_card(self):
        result = resolve_payment_account("招商银行信用卡(尾号1234)", "Assets:Unknown")
        assert result == "Liabilities:CreditCard:CMB"

    def test_citic_credit_card(self):
        result = resolve_payment_account("中信银行信用卡(1234)", "Assets:Unknown")
        assert result == "Liabilities:CreditCard:CITIC"


class TestResolveDebitCard:
    def test_explicit_debit_card(self):
        result = resolve_payment_account("招商银行储蓄卡(4455)", "Assets:Unknown")
        assert result == "Assets:Bank:CMB"

    def test_icbc_debit_card(self):
        result = resolve_payment_account("工商银行储蓄卡(7890)", "Assets:Unknown")
        assert result == "Assets:Bank:ICBC"


class TestResolveAmbiguous:
    def test_defaults_to_credit_card(self):
        """No card type keyword → uses default_card_type (credit card)."""
        result = resolve_payment_account("招商银行(0913)", "Assets:Unknown")
        assert result == "Liabilities:CreditCard:CMB"

    def test_override_default_to_debit(self):
        result = resolve_payment_account(
            "招商银行(0913)", "Assets:Unknown", default_card_type="Assets:Bank"
        )
        assert result == "Assets:Bank:CMB"


class TestResolvePlatformWallet:
    def test_wechat_wallet(self):
        result = resolve_payment_account("零钱", "Assets:Unknown")
        assert result == "Assets:WeChat"

    def test_alipay_balance(self):
        result = resolve_payment_account("余额", "Assets:Unknown")
        assert result == "Assets:Alipay"

    def test_jd_baitiao(self):
        result = resolve_payment_account("京东白条", "Assets:Unknown")
        assert result == "Liabilities:JD:BaiTiao"

    def test_jd_xiaojinku(self):
        result = resolve_payment_account("京东小金库", "Assets:Unknown")
        assert result == "Assets:JD:XiaoJinKu"


class TestResolveComposite:
    def test_wechat_composite_debit(self):
        result = resolve_payment_account("微信-招商银行储蓄卡", "Assets:Unknown")
        assert result == "Assets:Bank:CMB"

    def test_wechat_composite_credit(self):
        result = resolve_payment_account("微信-工商银行信用卡", "Assets:Unknown")
        assert result == "Liabilities:CreditCard:ICBC"


class TestResolveFallback:
    def test_unknown_string(self):
        result = resolve_payment_account("某未知支付", "Assets:WeChat:Unknown")
        assert result == "Assets:WeChat:Unknown"

    def test_empty_string(self):
        result = resolve_payment_account("", "Assets:Alipay")
        assert result == "Assets:Alipay"

    def test_alipay_status_not_payment(self):
        """Alipay 资金状态 like '已支出' is not a payment method."""
        result = resolve_payment_account("已支出", "Assets:Alipay:Unknown")
        assert result == "Assets:Alipay:Unknown"

    def test_alipay_status_income(self):
        result = resolve_payment_account("已收入", "Assets:Alipay:Unknown")
        assert result == "Assets:Alipay:Unknown"


class TestResolvePlatformPayment:
    def test_wechat_pay(self):
        result = resolve_payment_account("微信支付", "Assets:Unknown")
        assert result == "Assets:WeChat"

    def test_alipay_pay(self):
        result = resolve_payment_account("支付宝", "Assets:Unknown")
        assert result == "Assets:Alipay"

    def test_alipay_pay_full(self):
        result = resolve_payment_account("支付宝支付", "Assets:Unknown")
        assert result == "Assets:Alipay"

    def test_caifu_tong(self):
        result = resolve_payment_account("财付通", "Assets:Unknown")
        assert result == "Assets:WeChat"

    def test_jd_pay(self):
        result = resolve_payment_account("京东支付", "Assets:Unknown")
        assert result == "Assets:JD"


class TestPlatformAccountHelpers:
    def test_is_platform_account_wechat(self):
        assert is_platform_account("Assets:WeChat") is True

    def test_is_platform_account_alipay(self):
        assert is_platform_account("Assets:Alipay") is True

    def test_is_platform_account_jd(self):
        assert is_platform_account("Assets:JD") is True

    def test_not_platform_account_bank(self):
        assert is_platform_account("Liabilities:CreditCard:CMB") is False

    def test_not_platform_account_subaccount(self):
        assert is_platform_account("Assets:WeChat:Unknown") is False
