"""Tiered runner for the carto-agent regression suite.

Why this exists
---------------
The full regression measures ~974s (16.2 min) for 470 cases, but the cost is
extremely concentrated: 32 cases that perform real A4@300dpi rendering account
for ~89.8% of the wall time, while the other 438 cases finish in ~100s. Paying
16 minutes for every inner-loop edit is what makes changes feel expensive.

Tiers are therefore derived from a MEASURED baseline (``regression-baseline.json``)
rather than a hand-maintained list, so the split cannot silently drift away from
reality. Re-measure with ``--measure`` whenever the suite changes shape.

Tiers
-----
fast  per-case measured time <= threshold (default 5s). Protocol, schema, unit and
      component level. No real page rendering.
slow  per-case measured time >  threshold. End-to-end workflows that render for
      real (template validate/publish across the six parameter combinations,
      preview -> G2 -> render -> check -> G3 -> deliver).
full  everything; identical coverage to ``python -m unittest discover``.

``full`` remains the merge/release gate. ``fast`` is an inner-loop accelerator and
is NOT a substitute for it: ADR-001 §8.3 records that a static migration checklist
missed three ``encoding['kind']`` accesses which only the end-to-end tests caught.

Unknown cases (present in the repo but absent from the baseline, e.g. newly added
tests) are included in EVERY tier and reported, so a new test can never be skipped
by accident. Refresh the baseline to classify it.

Usage
-----
    python tests/run_tests.py --tier fast
    python tests/run_tests.py --tier slow
    python tests/run_tests.py --tier full
    python tests/run_tests.py --module test_encoding_ir --module test_backend_registry
    python tests/run_tests.py --test tests.test_schemas.SchemaTests.test_x
    python tests/run_tests.py --list --tier slow
    python tests/run_tests.py --measure          # re-time everything, rewrite baseline
    python tests/run_tests.py --tier fast --strict-skips

Exit codes: 0 pass; 1 failures/errors; 2 runner or configuration error;
3 skips present while --strict-skips was given; 5 nothing was collected.

This is development tooling under ``scripts/tests/`` (SKILL.md: that tree is for
development and acceptance only, never a runtime protocol). The single
cartography CLI remains ``scripts/carto.py``; this runner never touches map
workflows, approvals or project data.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import sys
import time
import unittest
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TESTS_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = TESTS_DIR.parent
BASELINE_PATH = TESTS_DIR / "regression-baseline.json"
DEFAULT_THRESHOLD = 5.0
DISCOVER_PATTERN = "test_*.py"

EXIT_OK = 0
EXIT_TESTS_FAILED = 1
EXIT_RUNNER_ERROR = 2
EXIT_SKIPS_PRESENT = 3
EXIT_NOTHING_COLLECTED = 5


# ---------------------------------------------------------------------------
# baseline
# ---------------------------------------------------------------------------

def load_baseline(path: Path) -> dict[str, Any]:
    """Return the measured baseline, or an empty one when it is unusable.

    A missing or corrupt baseline must not crash the runner: it degrades to
    "everything is unknown", which is conservative because unknown cases run in
    every tier.
    """
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    timings = data.get("timings")
    if not isinstance(timings, dict):
        return {}
    return data


def save_baseline(path: Path, timings: dict[str, float], *, threshold: float,
                  wall_seconds: float, tests_run: int, skipped: list[str]) -> None:
    payload = {
        "schema_version": 1,
        "purpose": "Measured per-case durations used to split the regression into "
                   "fast/slow tiers. Regenerate with run_tests.py --measure.",
        "measured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "python": platform.python_version(),
        "platform": f"{platform.system()} {platform.release()}",
        "threshold_seconds": threshold,
        "wall_seconds": round(wall_seconds, 2),
        "tests_run": tests_run,
        "timings": {name: round(seconds, 4) for name, seconds in sorted(timings.items())},
        "skipped": sorted(skipped),
        "caveat": "Durations are machine-specific. Re-measure on a materially "
                  "different host, or pass --threshold to retune the split.",
    }
    path.write_text(json.dumps(payload, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# discovery
# ---------------------------------------------------------------------------

def discover() -> unittest.TestSuite:
    """Discover with scripts/ as top level so ids read ``tests.test_x.Class.test_y``.

    Keeping the fully qualified id stable matters: it is the key used in the
    baseline, in --test selectors and in reported failures.
    """
    if str(SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPTS_DIR))
    loader = unittest.TestLoader()
    return loader.discover(start_dir=str(TESTS_DIR), pattern=DISCOVER_PATTERN,
                           top_level_dir=str(SCRIPTS_DIR))


def iter_cases(suite: unittest.TestSuite) -> Iterator[unittest.TestCase]:
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from iter_cases(item)
        else:
            yield item


def build_suite(cases: list[unittest.TestCase]) -> unittest.TestSuite:
    suite = unittest.TestSuite()
    for case in cases:
        suite.addTest(case)
    return suite


def module_of(test_id: str) -> str:
    """``tests.test_foo.Bar.test_baz`` -> ``test_foo``."""
    for part in test_id.split("."):
        if part.startswith("test_"):
            return part
    return test_id.split(".")[0]


# ---------------------------------------------------------------------------
# tiering
# ---------------------------------------------------------------------------

def tier_of(test_id: str, timings: dict[str, float], threshold: float) -> str:
    seconds = timings.get(test_id)
    if seconds is None:
        return "unknown"
    return "slow" if seconds > threshold else "fast"


def select_cases(cases: list[unittest.TestCase], *, tier: str, modules: list[str],
                 explicit: list[str], timings: dict[str, float],
                 threshold: float) -> tuple[list[unittest.TestCase], list[str]]:
    """Apply tier/module/id filters. Returns (selected, unknown_ids)."""
    unknown: list[str] = []
    selected: list[unittest.TestCase] = []
    for case in cases:
        test_id = case.id()
        if modules and module_of(test_id) not in modules:
            continue
        if explicit and test_id not in explicit:
            continue
        case_tier = tier_of(test_id, timings, threshold)
        if case_tier == "unknown":
            unknown.append(test_id)
            # Conservative: an unmeasured case always runs, in every tier.
        elif tier != "full" and case_tier != tier:
            continue
        selected.append(case)
    return selected, unknown


# ---------------------------------------------------------------------------
# execution
# ---------------------------------------------------------------------------

class TimingResult(unittest.TextTestResult):
    """TextTestResult that also records per-case wall time for --measure."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.timings: dict[str, float] = {}
        self.statuses: dict[str, str] = {}
        self._started: dict[str, float] = {}

    def startTest(self, test: unittest.TestCase) -> None:
        self._started[test.id()] = time.perf_counter()
        super().startTest(test)

    def stopTest(self, test: unittest.TestCase) -> None:
        super().stopTest(test)
        started = self._started.pop(test.id(), None)
        if started is not None:
            self.timings[test.id()] = time.perf_counter() - started

    def _record(self, test: unittest.TestCase, state: str) -> None:
        self.timings.setdefault(test.id(), 0.0)
        self.statuses[test.id()] = state

    def addSuccess(self, test: unittest.TestCase) -> None:
        super().addSuccess(test)
        self._record(test, "ok")

    def addFailure(self, test: unittest.TestCase, err: Any) -> None:
        super().addFailure(test, err)
        self._record(test, "FAIL")

    def addError(self, test: unittest.TestCase, err: Any) -> None:
        super().addError(test, err)
        self._record(test, "ERROR")

    def addSkip(self, test: unittest.TestCase, reason: str) -> None:
        super().addSkip(test, reason)
        self._record(test, "skip")

    def addExpectedFailure(self, test: unittest.TestCase, err: Any) -> None:
        super().addExpectedFailure(test, err)
        self._record(test, "expected-failure")

    def addUnexpectedSuccess(self, test: unittest.TestCase) -> None:
        super().addUnexpectedSuccess(test)
        self._record(test, "unexpected-success")


class TimingRunner(unittest.TextTestRunner):
    resultclass = TimingResult


def report_skips(result: unittest.TestResult) -> None:
    """Print every skip reason: a skipped case is not a passed case."""
    if not result.skipped:
        return
    print(f"\nSKIPPED {len(result.skipped)} (external-environment dependent; "
          f"NOT equivalent to passing):")
    for test, reason in result.skipped:
        print(f"  {test.id()}\n      {reason}")


def summarise_tiers(timings: dict[str, float], threshold: float) -> None:
    fast = [s for s in timings.values() if s <= threshold]
    slow = [s for s in timings.values() if s > threshold]
    total = sum(timings.values()) or 1.0
    print("\n=== tier split (from this measurement) ===")
    for label, group in (("fast", fast), ("slow", slow)):
        if not group:
            continue
        seconds = sum(group)
        print(f"  {label:<5} {len(group):>4} cases  {seconds:>8.1f}s = {seconds/60:>5.2f} min"
              f"  ({100*seconds/total:>5.1f}% of measured time)")
    print(f"  total {len(timings):>4} cases  {total:>8.1f}s = {total/60:>5.2f} min")


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="run_tests.py",
        description="Tiered runner for the carto-agent regression suite "
                    "(development tooling, not a cartography entry point).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Tiers come from a measured baseline; --tier full is the merge gate.",
    )
    parser.add_argument("--tier", choices=("fast", "slow", "full"), default="full",
                        help="which tier to run (default: full, i.e. unchanged behaviour)")
    parser.add_argument("--module", action="append", default=[], metavar="NAME",
                        help="restrict to a test module, e.g. test_encoding_ir (repeatable)")
    parser.add_argument("--test", action="append", default=[], metavar="ID",
                        help="restrict to an exact test id (repeatable)")
    parser.add_argument("--threshold", type=float, default=None, metavar="SECONDS",
                        help=f"fast/slow boundary (default: baseline value, else {DEFAULT_THRESHOLD})")
    parser.add_argument("--measure", action="store_true",
                        help="run everything with timing and rewrite regression-baseline.json")
    parser.add_argument("--list", action="store_true", dest="list_only",
                        help="print the selected test ids and exit without running them")
    parser.add_argument("--baseline", type=Path, default=BASELINE_PATH,
                        help="baseline file to read or write")
    parser.add_argument("--quiet", action="store_true", help="less verbose test output")
    parser.add_argument("--strict-skips", action="store_true",
                        help="exit 3 when any case was skipped")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    os.environ.setdefault("PYTHONUTF8", "1")
    args = parse_args(argv)

    try:
        suite = discover()
    except Exception as exc:  # discovery errors must be reported, not raised raw
        print(f"discovery failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return EXIT_RUNNER_ERROR

    cases = list(iter_cases(suite))
    if not cases:
        print(f"no tests discovered under {TESTS_DIR}", file=sys.stderr)
        return EXIT_NOTHING_COLLECTED

    baseline = load_baseline(args.baseline)
    timings: dict[str, float] = baseline.get("timings", {}) if isinstance(baseline.get("timings"), dict) else {}
    threshold = args.threshold
    if threshold is None:
        threshold = float(baseline.get("threshold_seconds") or DEFAULT_THRESHOLD)

    if args.measure:
        return measure(cases, threshold=threshold, baseline_path=args.baseline,
                       quiet=args.quiet, strict_skips=args.strict_skips)

    if not timings:
        print(f"WARNING: no usable baseline at {args.baseline}; every case is treated "
              f"as unknown and will run in all tiers. Run --measure to create it.\n",
              file=sys.stderr)

    selected, unknown = select_cases(cases, tier=args.tier, modules=args.module,
                                     explicit=args.test, timings=timings,
                                     threshold=threshold)

    if args.list_only:
        print(f"tier={args.tier}  threshold={threshold}s  selected={len(selected)}/{len(cases)}")
        for case in selected:
            seconds = timings.get(case.id())
            suffix = f"{seconds:8.2f}s" if seconds is not None else "  unknown"
            print(f"  {suffix}  {case.id()}")
        if unknown:
            print(f"\nunknown (absent from baseline, always selected): {len(unknown)}")
            for test_id in unknown:
                print(f"  {test_id}")
        if not selected:
            # An empty listing almost always means a misspelled --module/--test.
            print("nothing selected; check --tier/--module/--test", file=sys.stderr)
            return EXIT_NOTHING_COLLECTED
        return EXIT_OK

    if not selected:
        print("nothing selected; check --tier/--module/--test", file=sys.stderr)
        return EXIT_NOTHING_COLLECTED

    if unknown:
        print(f"WARNING: {len(unknown)} case(s) are absent from the baseline and are "
              f"being run in every tier. Refresh with --measure:", file=sys.stderr)
        for test_id in unknown[:20]:
            print(f"    {test_id}", file=sys.stderr)
        if len(unknown) > 20:
            print(f"    ... and {len(unknown) - 20} more", file=sys.stderr)
        print(file=sys.stderr)

    measured = sum(timings[c.id()] for c in selected if c.id() in timings)
    print(f"tier={args.tier}  threshold={threshold}s  selected={len(selected)}/{len(cases)}"
          f"  expected≈{measured:.0f}s ({measured/60:.2f} min, from baseline)")

    started = time.perf_counter()
    runner = TimingRunner(verbosity=1 if args.quiet else 2, stream=sys.stdout)
    result = runner.run(build_suite(selected))
    wall = time.perf_counter() - started

    report_skips(result)
    print(f"\nran {result.testsRun}/{len(cases)} cases in {wall:.1f}s ({wall/60:.2f} min) "
          f"| baseline expected {measured:.1f}s | failures={len(result.failures)} "
          f"errors={len(result.errors)} skipped={len(result.skipped)}")
    if args.tier != "full":
        print(f"NOTE: --tier {args.tier} is an inner-loop accelerator. Run --tier full "
              f"before merging or releasing.")

    if result.failures or result.errors:
        return EXIT_TESTS_FAILED
    if args.strict_skips and result.skipped:
        return EXIT_SKIPS_PRESENT
    return EXIT_OK


def measure(cases: list[unittest.TestCase], *, threshold: float, baseline_path: Path,
            quiet: bool, strict_skips: bool) -> int:
    """Time every case and rewrite the baseline."""
    print(f"measuring {len(cases)} cases (this runs the whole regression once)...")
    started = time.perf_counter()
    runner = TimingRunner(verbosity=1 if quiet else 2, stream=sys.stdout)
    result = runner.run(build_suite(cases))
    wall = time.perf_counter() - started

    report_skips(result)
    timings = result.timings
    save_baseline(baseline_path, timings, threshold=threshold, wall_seconds=wall,
                  tests_run=result.testsRun,
                  skipped=[test.id() for test, _ in result.skipped])
    summarise_tiers(timings, threshold)
    print(f"\nbaseline written: {baseline_path}")
    print(f"wall {wall:.1f}s ({wall/60:.2f} min) | failures={len(result.failures)} "
          f"errors={len(result.errors)} skipped={len(result.skipped)}")

    if result.failures or result.errors:
        return EXIT_TESTS_FAILED
    if strict_skips and result.skipped:
        return EXIT_SKIPS_PRESENT
    return EXIT_OK


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
