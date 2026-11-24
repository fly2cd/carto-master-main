"""Carto Agent controlled CLI — command-group assembly shell.

The monolithic ``cli.py`` was split into per-command-group modules (``schema_cmd``,
``security_cmd``, ``intent_cmd``, ``environment_cmd``, ``data_cmd``, ``template_cmd``,
``generate_cmd``). Each module exposes ``register(sub)`` (argparse definition) and
``handle(args) -> payload dict`` (execution). This shell assembles the parser in the
original order, dispatches by command name, and owns the single JSON error path.

Public surface is unchanged: ``carto_core.cli:main`` and ``carto_core.cli:build_parser``
remain importable, so ``carto.py``, the ``carto`` console script, and existing tests need
no edits.
"""
from __future__ import annotations

import argparse
import json
import sys

from ..errors import CartoError
from . import (
    schema_cmd, security_cmd, intent_cmd, environment_cmd, data_cmd, match_cmd, template_cmd, generate_cmd,
)
from ._shared import success

# Registration order preserves the original --help output order. security_cmd registers
# both the ``security`` and ``approval`` top-level commands.
_REGISTER_ORDER = (
    schema_cmd, security_cmd, intent_cmd, environment_cmd, data_cmd, match_cmd, template_cmd, generate_cmd,
)

# Command name -> handling module. ``approval`` shares security_cmd.
_DISPATCH = {
    "schema": schema_cmd,
    "security": security_cmd,
    "approval": security_cmd,
    "intent": intent_cmd,
    "environment": environment_cmd,
    "data": data_cmd,
    "template": match_cmd,
    "create-template": template_cmd,
    "generate-map": generate_cmd,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="carto", description="Carto Agent controlled CLI")
    sub = parser.add_subparsers(dest="command", required=True)
    for module in _REGISTER_ORDER:
        module.register(sub)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        module = _DISPATCH.get(args.command)
        if module is not None:
            return success(module.handle(args))
    except (CartoError, OSError, ValueError) as exc:
        code = exc.code if isinstance(exc, CartoError) else "UNEXPECTED_ERROR"
        print(json.dumps({"ok": False, "code": code, "message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    return 2


__all__ = ["main", "build_parser"]