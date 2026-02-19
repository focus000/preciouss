"""CLI interface for Preciouss."""

from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

import click

from preciouss import __version__
from preciouss.config import Config, load_config
from preciouss.importers.aldi import AldiImporter
from preciouss.importers.alipay import AlipayImporter
from preciouss.importers.base import PrecioussImporter, Transaction
from preciouss.importers.cmb import CmbCreditImporter, CmbDebitImporter
from preciouss.importers.jd import JdImporter, JdOrdersImporter
from preciouss.importers.resolve import (
    PLATFORM_ACCOUNT_PREFIXES,
    PLATFORM_KEYWORDS,
    is_platform_account,
)
from preciouss.importers.wechat import WechatImporter
from preciouss.importers.wechathk import WechatHKImporter
from preciouss.ledger.writer import init_ledger, write_transactions


def _get_importers(config: Config) -> list[PrecioussImporter]:
    """Build importer instances from config."""
    importers: list[PrecioussImporter] = []

    for name, acct in config.accounts.items():
        match acct.importer:
            case "alipay":
                importers.append(
                    AlipayImporter(account=acct.beancount_account, currency=acct.currency)
                )
            case "cmb":
                if acct.type == "credit_card":
                    importers.append(
                        CmbCreditImporter(
                            account=acct.beancount_account,
                            currency=acct.currency,
                            card_suffix=acct.identifier,
                        )
                    )
                else:
                    importers.append(
                        CmbDebitImporter(account=acct.beancount_account, currency=acct.currency)
                    )
            case "wechat":
                importers.append(
                    WechatImporter(account=acct.beancount_account, currency=acct.currency)
                )
            case "wechathk":
                importers.append(
                    WechatHKImporter(account=acct.beancount_account, currency=acct.currency)
                )
            case "aldi":
                importers.append(
                    AldiImporter(account=acct.beancount_account, currency=acct.currency)
                )
            case "jd":
                importers.append(
                    JdImporter(
                        account=acct.beancount_account,
                        currency=acct.currency,
                        orders_file=acct.orders_file,
                    )
                )
            case _:
                click.echo(f"Warning: unknown importer '{acct.importer}' for account '{name}'")

    # Always include default importers if no config
    if not importers:
        importers = [
            AlipayImporter(),
            WechatImporter(),
            WechatHKImporter(),
            CmbCreditImporter(),
            CmbDebitImporter(),
            AldiImporter(),
            JdImporter(),
            JdOrdersImporter(),
        ]

    return importers


@click.group()
@click.version_option(version=__version__)
@click.option("--config", "-c", "config_path", default=None, help="Path to config.toml")
@click.pass_context
def main(ctx: click.Context, config_path: str | None) -> None:
    """Preciouss - Cross-platform personal finance accounting system."""
    ctx.ensure_object(dict)
    ctx.obj["config"] = load_config(config_path)


@main.command()
@click.option("--dir", "ledger_dir", default=None, help="Ledger directory path")
@click.pass_context
def init(ctx: click.Context, ledger_dir: str | None) -> None:
    """Initialize a new ledger directory with default files."""
    config: Config = ctx.obj["config"]
    target_dir = ledger_dir or config.general.ledger_dir

    click.echo(f"Initializing ledger in: {target_dir}")
    init_ledger(target_dir, config.general.default_currency)
    click.echo("Created:")
    click.echo(f"  {target_dir}/main.bean")
    click.echo(f"  {target_dir}/accounts.bean")
    click.echo(f"  {target_dir}/commodities.bean")
    click.echo(f"  {target_dir}/importers/")
    click.echo(f"  {target_dir}/prices/")
    click.echo("\nLedger initialized successfully.")


_IMPORT_EXTENSIONS = {".csv", ".xlsx", ".xls", ".json"}


def _resolve_paths(paths: tuple[str, ...]) -> list[Path]:
    """Expand directories recursively into importable files, keep files as-is."""
    result: list[Path] = []
    for p in paths:
        path = Path(p)
        if path.is_dir():
            for child in sorted(path.rglob("*")):
                if child.is_file() and child.suffix.lower() in _IMPORT_EXTENSIONS:
                    result.append(child)
        else:
            result.append(path)
    return result


def _find_importer(
    filepath: str,
    importers: list[PrecioussImporter],
    source: str | None = None,
) -> PrecioussImporter | None:
    """Find the matching importer for a file."""
    if source:
        for imp in importers:
            if source.lower() in type(imp).__name__.lower():
                return imp
        return None
    for imp in importers:
        if imp.identify(filepath):
            return imp
    return None


def _deduplicate(transactions: list[Transaction]) -> list[Transaction]:
    """Deduplicate transactions by reference_id, preserving order.

    Transactions without a reference_id are always kept.
    For duplicates, the first occurrence is kept.
    """
    seen_refs: set[str] = set()
    result: list[Transaction] = []
    for tx in transactions:
        if tx.reference_id is None:
            result.append(tx)
        elif tx.reference_id not in seen_refs:
            seen_refs.add(tx.reference_id)
            result.append(tx)
    return result


def _importer_output_name(importer: PrecioussImporter) -> str:
    """Derive output file name from importer class name.

    WechatImporter → "wechat", AlipayImporter → "alipay",
    CmbCreditImporter → "cmb_credit", CmbDebitImporter → "cmb_debit",
    WechatHKImporter → "wechathk"
    """
    name = type(importer).__name__
    # Remove "Importer" suffix
    name = name.removesuffix("Importer")
    # Convert CamelCase to snake_case, keeping consecutive uppercase together
    # e.g. "WechatHK" → "wechathk", "CmbCredit" → "cmb_credit"
    result = []
    for i, ch in enumerate(name):
        if ch.isupper() and i > 0:
            prev_upper = name[i - 1].isupper()
            next_upper = (i + 1 < len(name)) and name[i + 1].isupper()
            next_end = i + 1 >= len(name)
            # Insert underscore only at boundary: lowercase→upper or end of acronym
            if not prev_upper or (prev_upper and not next_upper and not next_end):
                result.append("_")
        result.append(ch.lower())
    return "".join(result)


def _find_matching_tx(
    tx: Transaction,
    pool: list[Transaction],
    keywords: list[str],
) -> int | None:
    """Find index of a matching transaction in pool.

    Match: exact amount + date within 1 day + keywords in payee/narration.
    """
    tx_amount = abs(tx.amount)
    for i, candidate in enumerate(pool):
        if abs(candidate.amount) != tx_amount:
            continue
        if abs((tx.date.date() - candidate.date.date()).days) > 1:
            continue
        text = f"{candidate.payee or ''} {candidate.narration or ''}"
        if not any(kw in text for kw in keywords):
            continue
        return i
    return None


def _resolve_single_tx(
    tx: Transaction,
    target_platform: str,
    platform_to_imp_id: dict[str, int],
    all_txns_by_importer: dict[int, list[Transaction]],
    importer_map: dict[int, PrecioussImporter],
    source_keywords: list[str],
) -> bool:
    """Try to resolve a single transaction against a target platform's pool.

    Returns True if a matching shadow transaction was found and resolved.
    """
    target_imp_id = platform_to_imp_id.get(target_platform)
    if target_imp_id is None:
        return False

    pool = all_txns_by_importer.get(target_imp_id, [])

    idx = _find_matching_tx(tx, pool, source_keywords)
    if idx is not None:
        shadow = pool[idx]
        tx.source_account = shadow.source_account
        tx.payment_method = shadow.payment_method
        pool.pop(idx)
        return True

    return False


def _get_source_keywords(importer: PrecioussImporter) -> list[str]:
    """Get keywords that identify this importer's platform in other platforms' data."""
    account = importer.account_name()
    for platform, keywords in PLATFORM_KEYWORDS.items():
        if account.startswith(platform) or account == platform:
            return keywords
    # Fallback: use the class name
    return [type(importer).__name__.removesuffix("Importer")]


def _resolve_cross_platform(
    all_txns_by_importer: dict[int, list[Transaction]],
    importer_map: dict[int, PrecioussImporter],
) -> list[str]:
    """Resolve cross-platform payment accounts (in-place).

    When JD says "微信支付", find the matching WeChat transaction and inherit
    its actual payment method (e.g. 招商银行信用卡). Supports recursive chains
    and detects cycles.

    Returns a list of warning messages for unresolvable transactions.
    """
    warnings: list[str] = []

    # Build platform → importer ID mapping
    platform_to_imp_id: dict[str, int] = {}
    imp_id_to_platform: dict[int, str] = {}
    for imp_id, imp in importer_map.items():
        account = imp.account_name()
        for prefix in PLATFORM_ACCOUNT_PREFIXES:
            if account.startswith(prefix) or account == prefix:
                platform_to_imp_id[prefix] = imp_id
                imp_id_to_platform[imp_id] = prefix
                break

    # For each importer, resolve transactions whose source_account is another platform
    for imp_id, txns in all_txns_by_importer.items():
        source_keywords = _get_source_keywords(importer_map[imp_id])

        for tx in txns:
            if not is_platform_account(tx.source_account):
                continue
            # Only resolve if it points to a DIFFERENT platform
            own_platform = imp_id_to_platform.get(imp_id)
            if tx.source_account == own_platform:
                continue

            # Resolve with cycle detection
            visited: set[str] = set()
            if own_platform:
                visited.add(own_platform)

            current_target = tx.source_account
            resolved = False
            # Track which platform's keywords to use for matching
            # Initially, use the source importer's keywords (e.g. JD keywords)
            current_keywords = source_keywords

            while is_platform_account(current_target) and current_target not in visited:
                prev_target = current_target
                visited.add(current_target)

                success = _resolve_single_tx(
                    tx,
                    current_target,
                    platform_to_imp_id,
                    all_txns_by_importer,
                    importer_map,
                    current_keywords,
                )

                if success:
                    # Check if new source_account needs further resolution
                    current_target = tx.source_account
                    if not is_platform_account(current_target):
                        resolved = True
                        break
                    # For the next hop, use the PREVIOUS platform's keywords
                    # e.g. JD→WeChat→Alipay: Alipay pool needs WeChat keywords
                    current_keywords = PLATFORM_KEYWORDS.get(prev_target, [])
                    # Continue resolving (recursive chain)
                else:
                    break

            # Fallback: if still a platform account pointing to another importer
            # This covers: no match, cycle back to own platform, or cycle to visited
            if not resolved and is_platform_account(tx.source_account):
                if tx.source_account != own_platform:
                    tx.source_account = f"{tx.source_account}:Unknown"
                elif tx.source_account == own_platform and len(visited) > 1:
                    # Cycle: resolved back to own platform (e.g. JD→WeChat→JD)
                    tx.source_account = f"{tx.source_account}:Unknown"
                    msg = f"Cycle detected resolving tx {tx.reference_id}: visited {visited}"
                    warnings.append(msg)

    return warnings


def _merge_aldi_with_payments(
    all_txns_by_importer: dict[int, list[Transaction]],
    importer_map: dict[int, PrecioussImporter],
) -> None:
    """Merge ALDI orders with payment transactions (in-place).

    For each ALDI transaction:
    1. Find a matching payment in other importers (amount + date + merchant name)
    2. If matched → inherit source_account + payment_method, remove the payment tx
    3. If unmatched → source_account stays "Assets:Unknown"
    """
    # Find ALDI importer IDs and payment importer IDs
    aldi_imp_ids = []
    payment_imp_ids = []
    for imp_id, imp in importer_map.items():
        if isinstance(imp, AldiImporter):
            aldi_imp_ids.append(imp_id)
        else:
            payment_imp_ids.append(imp_id)

    if not aldi_imp_ids or not payment_imp_ids:
        return

    for aldi_id in aldi_imp_ids:
        aldi_txns = all_txns_by_importer.get(aldi_id, [])
        for aldi_tx in aldi_txns:
            matched = False

            for pay_id in payment_imp_ids:
                if matched:
                    break
                pay_txns = all_txns_by_importer.get(pay_id, [])
                idx = _find_matching_tx(aldi_tx, pay_txns, ["奥乐齐", "ALDI"])
                if idx is not None:
                    pay_tx = pay_txns[idx]
                    aldi_tx.source_account = pay_tx.source_account
                    aldi_tx.payment_method = pay_tx.payment_method
                    pay_txns.pop(idx)
                    matched = True


@main.command(name="import")
@click.argument("files", nargs=-1, type=click.Path(exists=True))
@click.option("--source", "-s", default=None, help="Force a specific importer (e.g. alipay, cmb)")
@click.option(
    "--reinit", is_flag=True, default=False, help="Delete and reinitialize ledger before importing"
)
@click.pass_context
def import_cmd(
    ctx: click.Context, files: tuple[str, ...], source: str | None, reinit: bool
) -> None:
    """Import transaction files (auto-detects platform)."""
    from preciouss.categorize.rules import RuleCategorizer

    config: Config = ctx.obj["config"]
    importers = _get_importers(config)

    if reinit:
        import shutil

        ledger_dir = Path(config.general.ledger_dir)
        if ledger_dir.exists():
            shutil.rmtree(ledger_dir)
            click.echo(f"Deleted ledger directory: {ledger_dir}")
        init_ledger(ledger_dir, config.general.default_currency)
        click.echo(f"Reinitialized ledger in: {ledger_dir}")

    if not files:
        click.echo("Error: no files specified. Usage: preciouss import <file|dir>...", err=True)
        sys.exit(1)

    # Resolve directories into individual files
    resolved = _resolve_paths(files)
    if not resolved:
        click.echo("No importable files found (.csv, .xlsx).", err=True)
        sys.exit(1)

    click.echo(f"Found {len(resolved)} file(s) to process.")

    # Build categorizer with user rules from config
    user_rules = config.get_categorize_rules()
    categorizer = RuleCategorizer(keyword_rules=user_rules if user_rules else None)

    ledger_dir = Path(config.general.ledger_dir)
    import_dir = ledger_dir / "importers"
    import_dir.mkdir(parents=True, exist_ok=True)

    # Phase 1: Identify files and group by importer
    # Use id() as key so different importer instances stay separate
    importer_files: defaultdict[int, list[str]] = defaultdict(list)
    importer_map: dict[int, PrecioussImporter] = {}
    warnings: list[str] = []

    for filepath in resolved:
        filepath_str = str(filepath)
        click.echo(f"\nProcessing: {filepath}")

        matched = _find_importer(filepath_str, importers, source)
        if not matched:
            msg = f"Skipped (unrecognized format): {filepath}"
            warnings.append(msg)
            click.echo(f"  Warning: {msg}", err=True)
            continue

        imp_id = id(matched)
        importer_files[imp_id].append(filepath_str)
        importer_map[imp_id] = matched
        click.echo(f"  Identified as: {type(matched).__name__}")

    # Phase 2: Extract and deduplicate per importer
    total_imported = 0
    total_categorized = 0
    total_deduped = 0
    all_txns_by_importer: dict[int, list[Transaction]] = {}

    for imp_id, file_list in importer_files.items():
        importer = importer_map[imp_id]
        all_txns: list[Transaction] = []

        for filepath in file_list:
            try:
                txns = importer.extract(filepath)
            except Exception as e:
                msg = f"Failed to extract {Path(filepath).name}: {e}"
                warnings.append(msg)
                click.echo(f"\n  Warning: {msg}", err=True)
                continue
            click.echo(f"\n  {Path(filepath).name}: {len(txns)} transactions extracted")
            all_txns.extend(txns)

        # Deduplicate
        before_count = len(all_txns)
        all_txns = _deduplicate(all_txns)
        n_dupes = before_count - len(all_txns)
        total_deduped += n_dupes

        if n_dupes > 0:
            click.echo(f"  Deduplicated: {before_count} → {len(all_txns)} ({n_dupes} duplicates)")

        all_txns_by_importer[imp_id] = all_txns

    # Phase 2.5a: Resolve cross-platform payment accounts
    cross_platform_warnings = _resolve_cross_platform(all_txns_by_importer, importer_map)
    for w in cross_platform_warnings:
        warnings.append(w)
        click.echo(f"  Warning: {w}", err=True)

    # Phase 2.5b: Merge ALDI orders with payment transactions
    _merge_aldi_with_payments(all_txns_by_importer, importer_map)

    # Phase 3: Write per importer
    for imp_id, all_txns in all_txns_by_importer.items():
        importer = importer_map[imp_id]

        if not all_txns:
            click.echo(f"  {type(importer).__name__}: no transactions after deduplication.")
            continue

        # Count categorized
        n_cat = sum(1 for tx in all_txns if categorizer.categorize(tx) is not None)
        total_categorized += n_cat

        # Write to per-importer .bean file
        output_name = _importer_output_name(importer)
        output_path = import_dir / f"{output_name}.bean"
        write_transactions(all_txns, output_path, categorizer=categorizer)
        click.echo(f"  Written {len(all_txns)} transactions to: {output_path}")
        total_imported += len(all_txns)

    n_uncat = total_imported - total_categorized
    click.echo(f"\nTotal: {total_imported} transactions imported.")
    if total_deduped > 0:
        click.echo(f"  Deduplicated: {total_deduped} duplicates removed")
    click.echo(f"  Categorized: {total_categorized}")
    click.echo(f"  Uncategorized: {n_uncat}")

    if warnings:
        click.echo(click.style(f"\n{len(warnings)} warning(s):", fg="yellow"), err=True)
        for w in warnings:
            click.echo(click.style(f"  - {w}", fg="yellow"), err=True)


@main.command()
@click.pass_context
def match(ctx: click.Context) -> None:
    """Run the matching engine on imported transactions."""
    config: Config = ctx.obj["config"]

    # Load all imported transactions
    ledger_dir = Path(config.general.ledger_dir)
    import_dir = ledger_dir / "importers"

    if not import_dir.exists():
        click.echo("No imported files found. Run 'preciouss import' first.", err=True)
        sys.exit(1)

    # For now, just show a message - full implementation in Phase 2
    click.echo("Matching engine: Phase 1 (reference ID), Phase 2 (intermediary), Phase 3 (fuzzy)")
    click.echo("This feature will be fully implemented in Phase 2.")


@main.command()
@click.pass_context
def categorize(ctx: click.Context) -> None:
    """Run the categorization engine on uncategorized transactions."""
    click.echo("Categorization engine: rules-based + ML prediction")
    click.echo("This feature will be fully implemented in Phase 3.")


@main.command()
@click.pass_context
def status(ctx: click.Context) -> None:
    """Show status of imported transactions."""
    config: Config = ctx.obj["config"]
    ledger_dir = Path(config.general.ledger_dir)

    if not ledger_dir.exists():
        click.echo("Ledger directory not found. Run 'preciouss init' first.", err=True)
        sys.exit(1)

    import_dir = ledger_dir / "importers"
    bean_files = list(import_dir.glob("*.bean")) if import_dir.exists() else []

    click.echo(f"Ledger directory: {ledger_dir}")
    click.echo(f"Imported files: {len(bean_files)}")

    total_txns = 0
    for bf in bean_files:
        # Count transactions by counting lines starting with a date pattern
        content = bf.read_text(encoding="utf-8")
        import re

        txn_count = len(re.findall(r"^\d{4}-\d{2}-\d{2} \*", content, re.MULTILINE))
        total_txns += txn_count
        click.echo(f"  {bf.name}: {txn_count} transactions")

    click.echo(f"Total transactions: {total_txns}")


@main.command()
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt")
@click.pass_context
def clear(ctx: click.Context, yes: bool) -> None:
    """Clear all imported ledger data."""
    config: Config = ctx.obj["config"]
    ledger_dir = Path(config.general.ledger_dir)
    import_dir = ledger_dir / "importers"

    if not import_dir.exists():
        click.echo("Nothing to clear — no importers directory found.")
        return

    bean_files = list(import_dir.glob("*.bean"))
    if not bean_files:
        click.echo("Nothing to clear — no .bean files found.")
        return

    click.echo(f"Found {len(bean_files)} .bean file(s) in {import_dir}:")
    for bf in bean_files:
        click.echo(f"  {bf.name}")

    if not yes:
        click.confirm("Delete all imported .bean files?", abort=True)

    for bf in bean_files:
        bf.unlink()

    click.echo(f"Cleared {len(bean_files)} file(s).")


@main.command()
@click.option("--port", "-p", default=5000, help="Port for Fava web UI")
@click.option("--host", "-h", "host", default="localhost", help="Host for Fava web UI")
@click.pass_context
def fava(ctx: click.Context, port: int, host: str) -> None:
    """Start the Fava web UI."""
    config: Config = ctx.obj["config"]
    main_bean = Path(config.general.ledger_dir) / config.general.main_file

    if not main_bean.exists():
        click.echo(
            f"Ledger file not found: {main_bean}\nRun 'preciouss init' first.",
            err=True,
        )
        sys.exit(1)

    click.echo(f"Starting Fava on http://{host}:{port}")
    click.echo(f"Loading: {main_bean}")

    import subprocess

    subprocess.run(
        ["fava", str(main_bean), "--host", host, "--port", str(port)],
        check=True,
    )


if __name__ == "__main__":
    main()
