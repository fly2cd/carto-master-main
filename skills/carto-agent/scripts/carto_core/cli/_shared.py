"""Shared CLI helpers (command-group modules import from here)."""
from __future__ import annotations

import json
import os
from pathlib import Path


def policy_path(name: str) -> Path:
    # cli/_shared.py -> parents[3] == skills/carto-agent (was parents[2] in the old cli.py).
    return Path(__file__).resolve().parents[3] / "policies" / name


def success(payload: dict[str, object]) -> int:
    print(json.dumps({"ok": True, **payload}, ensure_ascii=False, sort_keys=True))
    return 0


def approval_key(args) -> bytes:
    return os.environ.get(args.key_env, "").encode("utf-8")


def attestation_key(args) -> bytes:
    return os.environ.get(args.attestation_key_env, "").encode("utf-8")