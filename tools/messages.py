"""
Find every message ServeSync shows, so the Spanish catalog can be checked.

    python tools/messages.py            # how many messages, how many still need Spanish
    python tools/messages.py --missing  # print the untranslated ones as JSON, ready to fill in

A *message* is the English text passed to ``tr()``, ``tr_n()``, ``tr_for()`` or ``mark()``,
plus each enum's display label and each report date preset. The tests use
the same scan (tests/test_i18n.py), so a new message without a translation
fails the build instead of showing up in English on a Spanish screen.
"""

from __future__ import annotations

import ast
import json
import string
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "servesync"
CATALOG = PACKAGE / "locale" / "es.json"

_TRANSLATING_CALLS = {"tr": 1, "mark": 1, "tr_n": 2}  # how many leading arguments are messages


def _call_name(node: ast.Call) -> str:
    func = node.func
    return func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")


def scan_source(source: str) -> set[str]:
    """Messages in one module's source code."""
    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call) and _call_name(node) == "tr_for" and len(node.args) >= 2:
            context, message = node.args[:2]
            if isinstance(context, ast.Constant) and isinstance(message, ast.Constant):
                found |= {str(message.value), f"{context.value}|{message.value}"}
        elif isinstance(node, ast.Call) and (count := _TRANSLATING_CALLS.get(_call_name(node))):
            for argument in node.args[:count]:
                if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                    found.add(argument.value)
    return found


def runtime_messages() -> set[str]:
    """Messages built from code rather than written out: enum labels and date presets."""
    sys.path.insert(0, str(ROOT))
    from servesync.models import enums
    from servesync.services.reports.model import DatePreset

    found: set[str] = set()
    for value in vars(enums).values():
        if isinstance(value, type) and issubclass(value, enums.DisplayEnum) and value is not enums.DisplayEnum:
            found.update(member.english_label for member in value)
    found.update(preset.value for preset in DatePreset)
    return found


def all_messages() -> set[str]:
    found: set[str] = set()
    for path in sorted(PACKAGE.rglob("*.py")):
        if path.name == "i18n.py":
            continue  # the translation functions themselves
        found |= scan_source(path.read_text(encoding="utf-8"))
    return found | runtime_messages()


def load_catalog() -> dict[str, str]:
    data = json.loads(CATALOG.read_text(encoding="utf-8"))
    return {key: value for key, value in data.items() if not key.startswith("//")}


def placeholders(text: str) -> set[str]:
    """Field names in a format string: 'Saved {name}.' -> {'name'}."""
    return {field.split(".")[0].split("[")[0] for _, field, _, _ in string.Formatter().parse(text) if field}


def main() -> int:
    messages = all_messages()
    catalog = load_catalog() if CATALOG.exists() else {}
    missing = sorted(m for m in messages if m not in catalog)
    if "--missing" in sys.argv:
        print(json.dumps(dict.fromkeys(missing, ""), ensure_ascii=False, indent=2))
        return 0
    print(f"{len(messages)} messages; {len(missing)} without Spanish; {len(set(catalog) - messages)} unused")
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
