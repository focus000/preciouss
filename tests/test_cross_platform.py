"""Tests for cross-platform payment resolution."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from preciouss.cli import _resolve_cross_platform
from preciouss.importers.alipay import AlipayImporter
from preciouss.importers.base import Transaction
from preciouss.importers.jd import JdImporter
from preciouss.importers.wechat import WechatImporter


def _make_tx(
    *,
    amount: str = "-38.68",
    date: str = "2025-01-15 10:00:00",
    payee: str = "商户",
    narration: str = "",
    source_account: str = "Assets:Unknown",
    payment_method: str | None = None,
    reference_id: str | None = None,
    currency: str = "CNY",
) -> Transaction:
    return Transaction(
        date=datetime.strptime(date, "%Y-%m-%d %H:%M:%S"),
        amount=Decimal(amount),
        currency=currency,
        payee=payee,
        narration=narration,
        source_account=source_account,
        payment_method=payment_method,
        reference_id=reference_id,
    )


class TestJdViaWechat:
    """JD transaction paid via WeChat → should inherit WeChat's actual payment."""

    def test_basic_resolution(self):
        jd_imp = JdImporter()
        wechat_imp = WechatImporter()

        jd_tx = _make_tx(
            amount="-38.68",
            payee="京东商城",
            narration="购物",
            source_account="Assets:WeChat",
            reference_id="JD001",
        )
        wechat_shadow = _make_tx(
            amount="-38.68",
            payee="京东",
            narration="京东购物",
            source_account="Liabilities:CreditCard:CMB",
            payment_method="招商银行信用卡(0913)",
            reference_id="WX001",
        )

        jd_id, wechat_id = id(jd_imp), id(wechat_imp)
        all_txns = {jd_id: [jd_tx], wechat_id: [wechat_shadow]}
        imp_map = {jd_id: jd_imp, wechat_id: wechat_imp}

        _resolve_cross_platform(all_txns, imp_map)

        assert jd_tx.source_account == "Liabilities:CreditCard:CMB"
        assert jd_tx.payment_method == "招商银行信用卡(0913)"


class TestShadowTxRemoved:
    """Matched shadow transaction should be removed from the target pool."""

    def test_shadow_removed_after_match(self):
        jd_imp = JdImporter()
        wechat_imp = WechatImporter()

        jd_tx = _make_tx(
            amount="-50.00",
            payee="京东",
            source_account="Assets:WeChat",
        )
        wechat_shadow = _make_tx(
            amount="-50.00",
            payee="京东购物",
            source_account="Liabilities:CreditCard:CMB",
        )
        wechat_other = _make_tx(
            amount="-100.00",
            payee="美团",
            source_account="Liabilities:CreditCard:CMB",
        )

        jd_id, wechat_id = id(jd_imp), id(wechat_imp)
        all_txns = {jd_id: [jd_tx], wechat_id: [wechat_shadow, wechat_other]}
        imp_map = {jd_id: jd_imp, wechat_id: wechat_imp}

        _resolve_cross_platform(all_txns, imp_map)

        # Shadow tx should be removed, other tx should remain
        assert len(all_txns[wechat_id]) == 1
        assert all_txns[wechat_id][0].payee == "美团"


class TestNoMatchingFallback:
    """When no matching shadow tx is found, fallback to Unknown."""

    def test_no_match_becomes_unknown(self):
        jd_imp = JdImporter()
        wechat_imp = WechatImporter()

        jd_tx = _make_tx(
            amount="-38.68",
            payee="京东",
            source_account="Assets:WeChat",
        )
        # WeChat pool has no matching transaction
        wechat_unrelated = _make_tx(
            amount="-999.00",
            payee="美团",
            source_account="Liabilities:CreditCard:CMB",
        )

        jd_id, wechat_id = id(jd_imp), id(wechat_imp)
        all_txns = {jd_id: [jd_tx], wechat_id: [wechat_unrelated]}
        imp_map = {jd_id: jd_imp, wechat_id: wechat_imp}

        _resolve_cross_platform(all_txns, imp_map)

        assert jd_tx.source_account == "Assets:WeChat:Unknown"


class TestPlatformImporterNotPresent:
    """When the target platform importer doesn't exist, fallback to Unknown."""

    def test_missing_wechat_importer(self):
        jd_imp = JdImporter()

        jd_tx = _make_tx(
            amount="-38.68",
            payee="京东",
            source_account="Assets:WeChat",
        )

        jd_id = id(jd_imp)
        all_txns = {jd_id: [jd_tx]}
        imp_map = {jd_id: jd_imp}

        _resolve_cross_platform(all_txns, imp_map)

        assert jd_tx.source_account == "Assets:WeChat:Unknown"


class TestTerminalAccountNotResolved:
    """Transactions with terminal bank accounts should not be touched."""

    def test_bank_account_unchanged(self):
        jd_imp = JdImporter()
        wechat_imp = WechatImporter()

        jd_tx = _make_tx(
            amount="-38.68",
            payee="京东",
            source_account="Liabilities:CreditCard:CMB",
        )

        jd_id, wechat_id = id(jd_imp), id(wechat_imp)
        all_txns = {jd_id: [jd_tx], wechat_id: []}
        imp_map = {jd_id: jd_imp, wechat_id: wechat_imp}

        _resolve_cross_platform(all_txns, imp_map)

        assert jd_tx.source_account == "Liabilities:CreditCard:CMB"


class TestRequiresPlatformKeyword:
    """Shadow tx must contain keywords identifying the source platform."""

    def test_no_keyword_no_match(self):
        jd_imp = JdImporter()
        wechat_imp = WechatImporter()

        jd_tx = _make_tx(
            amount="-38.68",
            payee="京东",
            source_account="Assets:WeChat",
        )
        # Same amount, same date, but no JD keyword in payee/narration
        wechat_shadow = _make_tx(
            amount="-38.68",
            payee="美团外卖",
            narration="午餐",
            source_account="Liabilities:CreditCard:CMB",
        )

        jd_id, wechat_id = id(jd_imp), id(wechat_imp)
        all_txns = {jd_id: [jd_tx], wechat_id: [wechat_shadow]}
        imp_map = {jd_id: jd_imp, wechat_id: wechat_imp}

        _resolve_cross_platform(all_txns, imp_map)

        # Not matched because shadow doesn't mention "京东"
        assert jd_tx.source_account == "Assets:WeChat:Unknown"


class TestDateTolerance:
    """Date must be within 1 day for matching."""

    def test_date_within_one_day(self):
        jd_imp = JdImporter()
        wechat_imp = WechatImporter()

        jd_tx = _make_tx(
            amount="-38.68",
            date="2025-01-15 10:00:00",
            payee="京东",
            source_account="Assets:WeChat",
        )
        wechat_shadow = _make_tx(
            amount="-38.68",
            date="2025-01-16 08:00:00",
            payee="京东购物",
            source_account="Liabilities:CreditCard:CMB",
        )

        jd_id, wechat_id = id(jd_imp), id(wechat_imp)
        all_txns = {jd_id: [jd_tx], wechat_id: [wechat_shadow]}
        imp_map = {jd_id: jd_imp, wechat_id: wechat_imp}

        _resolve_cross_platform(all_txns, imp_map)

        assert jd_tx.source_account == "Liabilities:CreditCard:CMB"

    def test_date_beyond_one_day(self):
        jd_imp = JdImporter()
        wechat_imp = WechatImporter()

        jd_tx = _make_tx(
            amount="-38.68",
            date="2025-01-15 10:00:00",
            payee="京东",
            source_account="Assets:WeChat",
        )
        wechat_shadow = _make_tx(
            amount="-38.68",
            date="2025-01-17 10:00:00",
            payee="京东购物",
            source_account="Liabilities:CreditCard:CMB",
        )

        jd_id, wechat_id = id(jd_imp), id(wechat_imp)
        all_txns = {jd_id: [jd_tx], wechat_id: [wechat_shadow]}
        imp_map = {jd_id: jd_imp, wechat_id: wechat_imp}

        _resolve_cross_platform(all_txns, imp_map)

        # Date diff = 2 days, should not match
        assert jd_tx.source_account == "Assets:WeChat:Unknown"


class TestRecursiveChain:
    """JD → WeChat → Alipay → bank card should resolve recursively."""

    def test_three_level_chain(self):
        jd_imp = JdImporter()
        wechat_imp = WechatImporter()
        alipay_imp = AlipayImporter()

        jd_tx = _make_tx(
            amount="-100.00",
            payee="京东商城",
            source_account="Assets:WeChat",
        )
        # WeChat shadow: paid via Alipay, mentions JD
        wechat_shadow = _make_tx(
            amount="-100.00",
            payee="京东",
            narration="京东购物",
            source_account="Assets:Alipay",
            payment_method="支付宝",
        )
        # Alipay shadow: paid via bank card, mentions WeChat/财付通
        alipay_shadow = _make_tx(
            amount="-100.00",
            payee="财付通",
            narration="微信转账",
            source_account="Liabilities:CreditCard:CMB",
            payment_method="招商银行信用卡",
        )

        jd_id, wechat_id, alipay_id = id(jd_imp), id(wechat_imp), id(alipay_imp)
        all_txns = {
            jd_id: [jd_tx],
            wechat_id: [wechat_shadow],
            alipay_id: [alipay_shadow],
        }
        imp_map = {jd_id: jd_imp, wechat_id: wechat_imp, alipay_id: alipay_imp}

        _resolve_cross_platform(all_txns, imp_map)

        assert jd_tx.source_account == "Liabilities:CreditCard:CMB"


class TestCycleDetection:
    """A → B → A cycle should not loop forever."""

    def test_cycle_falls_back_to_unknown(self):
        jd_imp = JdImporter()
        wechat_imp = WechatImporter()

        jd_tx = _make_tx(
            amount="-50.00",
            payee="京东",
            source_account="Assets:WeChat",
        )
        # WeChat shadow points back to JD (cycle)
        wechat_shadow = _make_tx(
            amount="-50.00",
            payee="京东",
            source_account="Assets:JD",
            payment_method="京东支付",
        )

        jd_id, wechat_id = id(jd_imp), id(wechat_imp)
        all_txns = {jd_id: [jd_tx], wechat_id: [wechat_shadow]}
        imp_map = {jd_id: jd_imp, wechat_id: wechat_imp}

        # Should not raise, should handle gracefully with fallback
        warnings = _resolve_cross_platform(all_txns, imp_map)

        # After resolving, the tx inherits Assets:JD from wechat shadow,
        # but Assets:JD is the own platform → cycle detected.
        # The result should be Unknown fallback.
        assert jd_tx.source_account == "Assets:JD:Unknown" or "Cycle" in str(warnings)
