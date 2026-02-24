"""Management of overrides.toml — persistent transaction override configuration."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from preciouss.categorize.bql import MatchedTransaction

OVERRIDES_FILENAME = "overrides.toml"
EDITABLE_FIELDS = ("category", "payee", "narration")


@dataclass
class OverrideEntry:
    """A single override entry keyed by ref (txid)."""

    ref: str
    category: str = ""  # "" = no override
    payee: str = ""
    narration: str = ""

    def has_overrides(self) -> bool:
        """Return True if any field has a non-empty override."""
        return any(getattr(self, f) for f in EDITABLE_FIELDS)


def get_overrides_path(ledger_dir: str) -> Path:
    """Return the path to <ledger_dir>/overrides.toml."""
    return Path(ledger_dir) / OVERRIDES_FILENAME


def load_overrides(path: Path) -> dict[str, OverrideEntry]:
    """Read overrides.toml → {ref: OverrideEntry}.

    Returns an empty dict if the file does not exist.
    """
    if not path.exists():
        return {}

    with open(path, "rb") as f:
        data = tomllib.load(f)

    entries: dict[str, OverrideEntry] = {}
    for ref, fields in data.items():
        if not isinstance(fields, dict):
            continue
        entries[ref] = OverrideEntry(
            ref=ref,
            category=str(fields.get("category", "")),
            payee=str(fields.get("payee", "")),
            narration=str(fields.get("narration", "")),
        )
    return entries


def _format_entry(
    entry: OverrideEntry,
    match: MatchedTransaction | None = None,
) -> str:
    """Format a single override entry as TOML text with comment annotations."""
    lines: list[str] = []
    lines.append(f'["{entry.ref}"]')

    # Comment line with transaction summary
    if match:
        lines.append(
            f"# {match.date} "
            f'"{match.payee}" "{match.narration}" '
            f"{match.amount} {match.currency}"
        )

    # Editable fields with current-value comments
    for field_name in EDITABLE_FIELDS:
        value = getattr(entry, field_name)
        if match:
            if field_name == "category":
                current = match.current_account
            else:
                current = getattr(match, field_name, "")
            lines.append(f'{field_name} = "{value}"          # current: {current}')
        else:
            lines.append(f'{field_name} = "{value}"')

    return "\n".join(lines)


def save_overrides(
    path: Path,
    entries: dict[str, OverrideEntry],
    match_info: dict[str, MatchedTransaction] | None = None,
) -> None:
    """Write overrides.toml with comment annotations.

    match_info is used to generate helpful comments (transaction summary, current values).
    """
    if match_info is None:
        match_info = {}

    lines: list[str] = [
        "# preciouss overrides — managed by `preciouss override`",
        "# Edit with `preciouss override -i`, then `preciouss import --reinit` to apply.",
        "",
    ]

    for ref, entry in entries.items():
        match = match_info.get(ref)
        lines.append(_format_entry(entry, match))
        lines.append("")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def add_entries(
    path: Path,
    new_refs: list[str],
    match_info: dict[str, MatchedTransaction],
    defaults: dict[str, str] | None = None,
) -> int:
    """Add or update entries in overrides.toml.

    - New refs are added with default field values from `defaults`.
    - Existing refs are updated: only non-empty defaults overwrite existing values.

    Returns the number of newly added entries.
    """
    existing = load_overrides(path)
    added = 0

    for ref in new_refs:
        if ref in existing:
            # Update only non-empty defaults
            if defaults:
                entry = existing[ref]
                for key, value in defaults.items():
                    if key in EDITABLE_FIELDS and value:
                        setattr(entry, key, value)
        else:
            # Create new entry
            entry = OverrideEntry(ref=ref)
            if defaults:
                for key, value in defaults.items():
                    if key in EDITABLE_FIELDS:
                        setattr(entry, key, value)
            existing[ref] = entry
            added += 1

    save_overrides(path, existing, match_info)
    return added


def open_editor(path: Path) -> None:
    """Open the file in $EDITOR (default: vim), blocking until closed."""
    import os
    import subprocess

    editor = os.environ.get("EDITOR", "vim")
    subprocess.run([editor, str(path)], check=True)
