"""CLI interface for Preciouss."""

from __future__ import annotations

import sys
from pathlib import Path

import click

from preciouss import __version__
from preciouss.config import Config, load_config
from preciouss.importers.alipay import AlipayImporter
from preciouss.importers.base import PrecioussImporter
from preciouss.importers.cmb import CmbCreditImporter, CmbDebitImporter
from preciouss.importers.wechat import WechatImporter
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
            case _:
                click.echo(f"Warning: unknown importer '{acct.importer}' for account '{name}'")

    # Always include default importers if no config
    if not importers:
        importers = [
            AlipayImporter(),
            WechatImporter(),
            CmbCreditImporter(),
            CmbDebitImporter(),
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


@main.command(name="import")
@click.argument("files", nargs=-1, type=click.Path(exists=True))
@click.option("--source", "-s", default=None, help="Force a specific importer (e.g. alipay, cmb)")
@click.pass_context
def import_cmd(ctx: click.Context, files: tuple[str, ...], source: str | None) -> None:
    """Import transaction files (auto-detects platform)."""
    from preciouss.categorize.rules import RuleCategorizer

    config: Config = ctx.obj["config"]
    importers = _get_importers(config)

    if not files:
        click.echo("Error: no files specified. Usage: preciouss import <file>...", err=True)
        sys.exit(1)

    # Build categorizer with user rules from config
    user_rules = config.get_categorize_rules()
    categorizer = RuleCategorizer(keyword_rules=user_rules if user_rules else None)

    ledger_dir = Path(config.general.ledger_dir)
    import_dir = ledger_dir / "importers"
    import_dir.mkdir(parents=True, exist_ok=True)

    total_imported = 0
    total_categorized = 0

    for filepath in files:
        filepath = str(filepath)
        click.echo(f"\nProcessing: {filepath}")

        # Find matching importer
        matched_importer: PrecioussImporter | None = None

        if source:
            # Force specific importer
            for imp in importers:
                if source.lower() in type(imp).__name__.lower():
                    matched_importer = imp
                    break
            if not matched_importer:
                click.echo(f"  Error: no importer found for source '{source}'", err=True)
                continue
        else:
            # Auto-detect
            for imp in importers:
                if imp.identify(filepath):
                    matched_importer = imp
                    break

        if not matched_importer:
            click.echo(
                "  Error: could not identify file format. Use --source to specify.",
                err=True,
            )
            continue

        importer_name = type(matched_importer).__name__
        click.echo(f"  Identified as: {importer_name}")

        # Extract transactions
        transactions = matched_importer.extract(filepath)
        if not transactions:
            click.echo("  No transactions found.")
            continue

        # Count how many can be categorized
        n_cat = sum(1 for tx in transactions if categorizer.categorize(tx) is not None)
        click.echo(f"  Extracted {len(transactions)} transactions ({n_cat} categorized)")
        total_categorized += n_cat

        # Write to .bean file with auto-categorization
        source_name = Path(filepath).stem
        output_path = import_dir / f"{source_name}.bean"
        write_transactions(transactions, output_path, categorizer=categorizer)
        click.echo(f"  Written to: {output_path}")
        total_imported += len(transactions)

    n_uncat = total_imported - total_categorized
    click.echo(f"\nTotal: {total_imported} transactions imported.")
    click.echo(f"  Categorized: {total_categorized}")
    click.echo(f"  Uncategorized: {n_uncat}")


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
