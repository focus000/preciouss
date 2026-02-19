"""CLI interface for Preciouss."""

from __future__ import annotations

import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import click

from preciouss import __version__
from preciouss.config import Config, load_config
from preciouss.importers.aldi import AldiImporter
from preciouss.importers.alipay import AlipayImporter
from preciouss.importers.base import PrecioussImporter, Transaction
from preciouss.importers.cmb import CmbCreditImporter, CmbDebitImporter
from preciouss.importers.costco import CostcoImporter
from preciouss.importers.jd import JdImporter, JdOrdersImporter
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
            case "costco":
                importers.append(
                    CostcoImporter(account=acct.beancount_account, currency=acct.currency)
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
            CostcoImporter(),
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


def _validate_ledger(ledger_dir: Path, main_file: str) -> None:
    """Validate the generated beancount ledger and report errors."""
    from beancount.loader import load_file

    main_bean = ledger_dir / main_file
    if not main_bean.exists():
        return

    _, errors, _ = load_file(str(main_bean))
    if not errors:
        click.echo(click.style("\nBeancount validation: OK", fg="green"))
        return

    click.echo(click.style(f"\n{len(errors)} beancount validation error(s):", fg="red"), err=True)
    for err in errors:
        source = err.source
        fname = Path(source.get("filename", "")).name if source else "?"
        lineno = source.get("lineno", "?") if source else "?"
        click.echo(click.style(f"  {fname}:{lineno}  {err.message}", fg="red"), err=True)


def _parse_year_range(year_str: str) -> tuple[datetime, datetime]:
    """Parse 'START:END' year range string into a half-open [from, until) datetime interval.

    '2020:2026' → (datetime(2020,1,1), datetime(2026,1,1))
    Transactions are kept if: date_from <= tx.date < date_until.
    """
    parts = year_str.split(":")
    if len(parts) != 2:
        raise click.BadParameter(f"Expected 'START:END', got '{year_str}'", param_hint="'--year'")
    try:
        start, end = int(parts[0]), int(parts[1])
    except ValueError:
        raise click.BadParameter(f"Years must be integers, got '{year_str}'", param_hint="'--year'")
    if start >= end:
        raise click.BadParameter(
            f"Start year must be less than end year, got '{year_str}'", param_hint="'--year'"
        )
    return datetime(start, 1, 1), datetime(end, 1, 1)


@main.command(name="import")
@click.argument("files", nargs=-1, type=click.Path(exists=True))
@click.option("--source", "-s", default=None, help="Force a specific importer (e.g. alipay, cmb)")
@click.option(
    "--reinit", is_flag=True, default=False, help="Delete and reinitialize ledger before importing"
)
@click.option(
    "--year",
    "year_range",
    default=None,
    help="Only import transactions in this year range, e.g. '2020:2026' keeps 2020–2025.",
)
@click.pass_context
def import_cmd(
    ctx: click.Context,
    files: tuple[str, ...],
    source: str | None,
    reinit: bool,
    year_range: str | None,
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

    date_filter: tuple[datetime, datetime] | None = None
    if year_range:
        date_filter = _parse_year_range(year_range)
        date_from, date_until = date_filter
        click.echo(
            f"Date filter: {date_from.year}-01-01 to {date_until.year - 1}-12-31 (inclusive)"
        )

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
    total_filtered = 0
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

        if date_filter is not None:
            date_from, date_until = date_filter
            before = len(all_txns)
            all_txns = [tx for tx in all_txns if date_from <= tx.date < date_until]
            n_filtered = before - len(all_txns)
            total_filtered += n_filtered
            if n_filtered > 0:
                click.echo(f"  Date filter: removed {n_filtered} out-of-range transactions")

        all_txns_by_importer[imp_id] = all_txns

    # Phase 2.5: Clearing link assignment (DFS from terminal expenses)
    from preciouss.matching.clearing import assign_clearing_links

    all_flat: list[Transaction] = []
    tx_importer_map: dict[int, PrecioussImporter] = {}
    for imp_id, txns in all_txns_by_importer.items():
        for tx in txns:
            tx_importer_map[len(all_flat)] = importer_map[imp_id]
            all_flat.append(tx)

    if all_flat:
        clr_stats = assign_clearing_links(all_flat, tx_importer_map)
        if clr_stats.total_chains > 0:
            click.echo(
                f"\nClearing: {clr_stats.total_chains} chains, "
                f"{clr_stats.total_linked} linked, "
                f"{clr_stats.unmatched_terminal} unmatched"
            )

    # Phase 3: Write per importer (each importer is independent, no cross-source mutations)
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
    if total_filtered > 0:
        click.echo(f"  Filtered (out of date range): {total_filtered}")
    click.echo(f"  Categorized: {total_categorized}")
    click.echo(f"  Uncategorized: {n_uncat}")

    if warnings:
        click.echo(click.style(f"\n{len(warnings)} warning(s):", fg="yellow"), err=True)
        for w in warnings:
            click.echo(click.style(f"  - {w}", fg="yellow"), err=True)

    # Phase 4: Validate generated beancount ledger
    if total_imported > 0:
        _validate_ledger(ledger_dir, config.general.main_file)


@main.command()
@click.option("--dry-run", is_flag=True, help="Show matches without modifying files")
@click.pass_context
def match(ctx: click.Context, dry_run: bool) -> None:
    """DFS match clearing account chains, propagate ^link."""
    config: Config = ctx.obj["config"]

    # Load all imported transactions
    ledger_dir = Path(config.general.ledger_dir)
    import_dir = ledger_dir / "importers"

    if not import_dir.exists():
        click.echo("No imported files found. Run 'preciouss import' first.", err=True)
        sys.exit(1)

    click.echo("Clearing account matching engine")
    click.echo("This feature will be fully implemented in Phase 7.")
    if dry_run:
        click.echo("(dry-run mode)")


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
