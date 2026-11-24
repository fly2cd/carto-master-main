"""carto CLI entry: the single entry point for all map capabilities.

stdout/stderr are pinned to UTF-8 at entry: the JSON machine output of the
CLI must be byte-stable regardless of the host's console codepage (Chinese
Windows pipes default to cp936/GBK, which corrupts UTF-8 JSON re-encoding).
Human-facing terminals can display UTF-8 via ``chcp 65001`` or Windows
Terminal; hosts read the bytes as UTF-8 unconditionally. Belt-and-braces:
hosts may also invoke with ``python -X utf8``.
"""
import sys

from carto_core.cli import main


def _pin_utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        if stream is not None:
            try:
                stream.reconfigure(encoding="utf-8")
            except (AttributeError, ValueError):
                # Non-reconfigurable stream (e.g. replaced by a test harness):
                # leave it as-is rather than fail entry.
                pass


if __name__ == "__main__":
    _pin_utf8()
    raise SystemExit(main())
