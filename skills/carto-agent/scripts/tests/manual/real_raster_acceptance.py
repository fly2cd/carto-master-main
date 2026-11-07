"""Read-only real-input preflight plus isolated synthetic regression.

This is a development harness, NOT another map CLI, host attestation, business
approval, or production acceptance. Real inputs are never passed to test fixtures.
"""
from __future__ import annotations

import argparse
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
import hashlib
import importlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import unittest
import uuid

SCRIPTS_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = Path(__file__).resolve().parents[5]
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from carto_core.errors import CartoError
from carto_core.schema_registry import SchemaRegistry, load_document
from carto_core.security.paths import PathGuard

RASTER_MODULES = (
    "test_schemas", "test_geospatial_mcp", "test_geospatial_stdio",
    "test_raster_classification", "test_raster_portrayal", "test_raster_renderer",
    "test_raster_page_renderer", "test_raster_formal",
)
DEPENDENCIES = ("numpy", "rasterio", "matplotlib", "PIL", "fontTools", "mcp", "pypdf", "pypdfium2")
STATUS = {"passed": "通过", "failed": "失败", "blocked": "阻塞", "not_run": "未执行", "skipped": "跳过"}


def now():
    return datetime.now(timezone.utc).isoformat()


class CheckError(Exception):
    def __init__(self, code, evidence=None):
        self.code = code
        self.evidence = evidence or {}


def safe_code(error):
    code = getattr(error, "code", "CHECK_EXCEPTION")
    return code if isinstance(code, str) and re.fullmatch(r"[A-Z][A-Z0-9_]{0,79}", code) else "CHECK_EXCEPTION"


def fingerprint(path, limit):
    if not path.is_file():
        raise CheckError("INPUT_NOT_REGULAR_FILE")
    before = path.stat()
    if not 0 < before.st_size <= limit:
        raise CheckError("INPUT_SIZE_OUT_OF_RANGE")
    digest = hashlib.sha256()
    length = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            length += len(chunk)
            if length > limit:
                raise CheckError("INPUT_SIZE_OUT_OF_RANGE")
            digest.update(chunk)
    after = path.stat()
    if length != before.st_size or (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise CheckError("INPUT_CHANGED_DURING_READ")
    return {"size_bytes": length, "sha256": digest.hexdigest()}


def input_check(path, kind):
    result = fingerprint(path, 256 * 1024 * 1024 if kind == "raster" else 1024 * 1024)
    if kind == "raster":
        with path.open("rb") as stream:
            if stream.read(4) not in (b"II\x2a\x00", b"MM\x00\x2a", b"II\x2b\x00", b"MM\x00\x2b"):
                raise CheckError("TIFF_SIGNATURE_INVALID")
        result["check_depth"] = "size_digest_tiff_signature_only"
    else:
        result["check_depth"] = "size_digest_only_no_column_or_row_interpretation"
    return result


def invoke(command, *, timeout=120):
    started = time.perf_counter()
    # Raw output is intentionally not persisted: an error may contain input values.
    try:
        completed = subprocess.run(command, cwd=REPO_ROOT, capture_output=True,
                                   text=True, encoding="utf-8", errors="replace", timeout=timeout,
                                   env={**os.environ, "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1"})
    except subprocess.TimeoutExpired as exc:
        raise CheckError("SUBPROCESS_TIMEOUT", {"timeout_seconds": timeout, "retried": False}) from exc
    meta = {"exit_code": completed.returncode, "duration_seconds": round(time.perf_counter() - started, 3)}
    for key in ("stdout", "stderr"):
        content = getattr(completed, key).encode("utf-8")
        meta[key + "_bytes"] = len(content)
        meta[key + "_sha256"] = hashlib.sha256(content).hexdigest()
    return completed, meta


def parse_success(completed, meta):
    try:
        value = json.loads(completed.stdout)
    except (ValueError, TypeError) as exc:
        raise CheckError("SUBPROCESS_JSON_INVALID", meta) from exc
    if completed.returncode != 0 or not isinstance(value, dict) or value.get("ok") is not True:
        raise CheckError("SUBPROCESS_NOT_SUCCESSFUL", meta)
    return value


class Report:
    def __init__(self, project, *, guard, mode, host, suite):
        namespace = guard.resolve(project / ".carto/acceptance-tests")
        namespace.mkdir(parents=True, exist_ok=True)
        self.root = guard.resolve(namespace / (datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:12]))
        self.root.mkdir(exist_ok=False)
        self.guard = guard
        self.data = {
            "report_format": "development-acceptance-v1", "started_at": now(), "completed_at": None,
            "mode": mode, "suite": suite if mode == "regression" else None,
            "host_label": host, "host_verification": "not_verified_by_script",
            "requested_map": {"title": "用地分类数据", "paper": "A4", "orientation": "landscape",
                              "width_mm": 297, "height_mm": 210, "is_rendered_output": False},
            "selected_phase_status": "running", "real_map_acceptance": "not_completed",
            "plugin_acceptance": "not_verified", "steps": [],
        }
        self.flush()

    def flush(self):
        rows = ["# 栅格开发测试记录", "", f"- 阶段：`{self.data['mode']}`；状态：`{self.data['selected_phase_status']}`",
                f"- 宿主自报标签：`{self.data['host_label']}`；脚本不能验证插件身份。",
                "- 真实数据仅做只读预检；回归使用合成数据，不代表真实地图或插件端到端验收。", "",
                "| 步骤 | 结果 | 用时(s) | 代码 |", "|---|---|---:|---|"]
        for step in self.data["steps"]:
            rows.append(f"| {step['id']} {step['name']} | {STATUS[step['status']]} | {step['duration_seconds']} | {step['code']} |")
        rows += ["", "详细摘要、时间和退出码见同目录 report.json；逐条回归用例见 regression.json（若执行）。",
                 "不保存输入行、像元、CRS/范围坐标、原始异常文本、密钥或完整环境变量。", ""]
        for name, text in (("report.json", json.dumps(self.data, ensure_ascii=False, indent=2) + "\n"),
                           ("report.md", "\n".join(rows))):
            target = self.guard.resolve(self.root / name)
            temporary = self.guard.resolve(self.root / (name + ".tmp"))
            temporary.write_text(text, encoding="utf-8")
            os.replace(temporary, target)

    def record(self, identifier, name, status, *, code="OK", evidence=None, started=None, duration=0):
        self.data["steps"].append({"id": identifier, "name": name, "status": status, "code": code,
                                   "started_at": started or now(), "completed_at": now(),
                                   "duration_seconds": round(duration, 3), "evidence": evidence or {}})
        self.flush()

    def check(self, identifier, name, action):
        started, timer = now(), time.perf_counter()
        try:
            evidence = action()
        except (CheckError, CartoError, OSError, ValueError, TypeError) as exc:
            self.record(identifier, name, "failed", code=safe_code(exc), evidence=getattr(exc, "evidence", {}),
                        started=started, duration=time.perf_counter() - timer)
            return False
        self.record(identifier, name, "passed", evidence=evidence, started=started, duration=time.perf_counter() - timer)
        return True


class StepResult(unittest.TestResult):
    """Persist identifiers/status only, never test tracebacks or subtest values."""
    def __init__(self):
        super().__init__()
        self.records = []
        self.active = None

    def startTest(self, test):
        super().startTest(test)
        self.timer = time.perf_counter()
        self.active = {"test_id": test.id(), "status": "passed", "code": "OK", "started_at": now()}

    def mark(self, test, status, code):
        if self.active is None:  # setUpClass / module-level errors and skips
            self.records.append({"test_id": test.id(), "status": status, "code": code,
                                 "started_at": now(), "completed_at": now(), "duration_seconds": 0})
        elif self.active["status"] != "failed":
            self.active.update(status=status, code=code)

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self.mark(test, "failed", "TEST_ASSERTION_FAILED")

    def addError(self, test, err):
        super().addError(test, err)
        self.mark(test, "failed", "TEST_EXCEPTION")

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        code = "SYMLINK_PERMISSION_UNAVAILABLE" if "symbolic link creation is not permitted" in reason else "TEST_SKIPPED"
        self.mark(test, "skipped", code)

    def addExpectedFailure(self, test, err):
        super().addExpectedFailure(test, err)
        self.mark(test, "skipped", "EXPECTED_FAILURE")

    def addUnexpectedSuccess(self, test):
        super().addUnexpectedSuccess(test)
        self.mark(test, "failed", "UNEXPECTED_SUCCESS")

    def addSubTest(self, test, subtest, err):
        super().addSubTest(test, subtest, err)
        if err is not None:
            self.mark(test, "failed", "SUBTEST_FAILED")

    def stopTest(self, test):
        self.active.update(completed_at=now(), duration_seconds=round(time.perf_counter() - self.timer, 3))
        self.records.append(self.active)
        self.active = None
        super().stopTest(test)

    def payload(self):
        counts = {key: sum(row["status"] == key for row in self.records) for key in ("passed", "failed", "skipped")}
        return {"ok": self.wasSuccessful(), "tests_run": self.testsRun, "counts": counts,
                "data_kind": "synthetic_only", "records": self.records}


def worker(kind, suite):
    # A fresh child process isolates test mocks, temporary files and runtime state.
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        if kind == "dependencies":
            values = {}
            for module in DEPENDENCIES:
                try:
                    importlib.import_module(module)
                    values[module] = "importable"
                except Exception:
                    values[module] = "unavailable"
            payload = {"ok": True, "dependencies": values}
        else:
            loader = unittest.TestLoader()
            tests = (loader.discover(str(SCRIPTS_ROOT / "tests"), pattern="test_*.py", top_level_dir=str(SCRIPTS_ROOT))
                     if suite == "all" else loader.loadTestsFromNames(["tests." + name for name in RASTER_MODULES]))
            result = StepResult()
            tests.run(result)
            payload = result.payload()
    print(json.dumps(payload, ensure_ascii=False))
    return 0 if payload["ok"] else 2


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("preflight", "regression"), default="preflight")
    parser.add_argument("--suite", choices=("raster", "all"), default="raster")
    parser.add_argument("--project-root", default="projects/landcover-acceptance")
    parser.add_argument("--raster", default="projects/dataset/landCover_reclassified.tif")
    parser.add_argument("--legend", default="projects/dataset/reclass_legend.csv")
    parser.add_argument("--allowed-root", action="append", default=[])
    parser.add_argument("--host", choices=("terminal", "vscode-claude-code"), default="terminal",
                        help="Self-reported label only, never host attestation")
    parser.add_argument("--_worker", choices=("dependencies", "regression"), help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args._worker:
        return worker(args._worker, args.suite)
    try:
        guard = PathGuard([REPO_ROOT, *args.allowed_root])
        project = guard.resolve(args.project_root, base_root=REPO_ROOT)
        # Harness outputs belong in an ignored project, never runtime source or a dataset directory.
        project_namespace = guard.resolve(REPO_ROOT / "projects")
        if not project.is_relative_to(project_namespace) or project == project_namespace or project.is_relative_to(project_namespace / "dataset") or project.is_relative_to(project_namespace / ".carto-dev"):
            raise CheckError("ACCEPTANCE_PROJECT_NAMESPACE_INVALID")
        report = Report(project, guard=guard, mode=args.mode, host=args.host, suite=args.suite)
    except (CartoError, CheckError, OSError) as exc:
        print(json.dumps({"ok": False, "code": safe_code(exc), "report_created": False}))
        return 2

    snapshots = {}
    def snapshot(identifier, raw, kind):
        path = guard.resolve(raw, base_root=REPO_ROOT, must_exist=True)
        result = input_check(path, kind)
        snapshots[identifier] = (path, result, kind)
        return result

    def python_check():
        if sys.version_info < (3, 11):
            raise CheckError("PYTHON_VERSION_UNSUPPORTED")
        return {"version": sys.version.split()[0], "implementation": sys.implementation.name,
                "executable_name": Path(sys.executable).name}

    def help_check():
        completed, meta = invoke([sys.executable, "-B", str(SCRIPTS_ROOT / "carto.py"), "--help"])
        if completed.returncode != 0 or not all(x in completed.stdout for x in ("Carto Agent controlled CLI", "generate-map", "data")):
            raise CheckError("CLI_HELP_NOT_SUCCESSFUL", meta)
        return meta

    def schema_check():
        completed, meta = invoke([sys.executable, "-B", str(SCRIPTS_ROOT / "carto.py"), "schema", "check"])
        value = parse_success(completed, meta)
        expected = {p.name.removesuffix(".schema.json") for p in (SCRIPTS_ROOT.parent / "schemas").glob("*.schema.json")}
        if not expected or value.get("checked") != len(expected) or not isinstance(value.get("schemas"), list) or set(value["schemas"]) != expected or len(value["schemas"]) != len(expected):
            raise CheckError("SCHEMA_CHECK_INCOMPLETE", meta)
        return {**meta, "checked_schemas": value["checked"]}

    def policy_check():
        path = guard.resolve(SCRIPTS_ROOT.parent / "policies/scenario-capabilities.yaml", must_exist=True)
        item = fingerprint(path, 1024 * 1024)
        value = load_document(path)
        SchemaRegistry().validate("scenario-capabilities", value)
        snapshots["policy"] = (path, item, "policy")
        return {**item, "default": value["default"], "profile_count": len(value["profiles"]), "modified_by_harness": False}

    prerequisites = [
        ("01", "实际 Python 版本", python_check),
        ("02", "唯一 CLI 帮助", help_check),
        ("03", "Schema 自检与数量核对", schema_check),
        ("04", "真实 TIFF 只读预检", lambda: snapshot("raster", args.raster, "raster")),
        ("05", "真实 CSV 只读预检", lambda: snapshot("legend", args.legend, "legend")),
        ("06", "业务能力策略只读快照", policy_check),
    ]
    proceed = True
    for identifier, name, action in prerequisites:
        if proceed:
            proceed = report.check(identifier, name, action)
        else:
            report.record(identifier, name, "not_run", code="PREVIOUS_STEP_FAILED")

    deps = {}
    def dependency_check():
        completed, meta = invoke([sys.executable, "-B", str(Path(__file__)), "--_worker", "dependencies"])
        payload = parse_success(completed, meta)
        if set(payload.get("dependencies", {})) != set(DEPENDENCIES):
            raise CheckError("DEPENDENCY_PROBE_INCOMPLETE", meta)
        deps.update(payload["dependencies"])
        return {**meta, "dependencies": deps, "is_renderer_attestation": False}

    if proceed:
        proceed = report.check("07", "可选依赖导入探测（不安装）", dependency_check)
    else:
        report.record("07", "可选依赖导入探测（不安装）", "not_run", code="PREVIOUS_STEP_FAILED")

    def regression_check():
        completed, meta = invoke([sys.executable, "-B", str(Path(__file__)), "--_worker", "regression", "--suite", args.suite], timeout=1200)
        try:
            payload = json.loads(completed.stdout)
        except ValueError as exc:
            raise CheckError("REGRESSION_REPORT_INVALID", meta) from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("records"), list) or not payload.get("tests_run"):
            raise CheckError("REGRESSION_REPORT_INVALID", meta)
        # Worker emits sanitized identifiers/status only; this file contains no raw tracebacks.
        target = guard.resolve(report.root / "regression.json")
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        evidence = {**meta, "artifact": "regression.json", "tests_run": payload["tests_run"], "counts": payload["counts"], "data_kind": "synthetic_only"}
        if completed.returncode != 0 or payload.get("ok") is not True or payload["counts"]["failed"]:
            raise CheckError("REGRESSION_FAILED", evidence)
        return evidence

    if args.mode == "regression" and proceed:
        passed = report.check("08", "隔离进程合成数据回归", regression_check)
        if passed:
            row = report.data["steps"][-1]
            if row["evidence"]["counts"]["skipped"]:
                row.update(status="blocked", code="REGRESSION_HAS_SKIPS")
                report.flush()
    else:
        report.record("08", "隔离进程合成数据回归", "not_run", code="NOT_REQUESTED" if args.mode == "preflight" else "PREVIOUS_STEP_FAILED")

    def integrity_check():
        for path, baseline, kind in snapshots.values():
            checked = guard.resolve(path, must_exist=True)
            current = fingerprint(checked, 256 * 1024 * 1024 if kind == "raster" else 1024 * 1024)
            if any(current[key] != baseline[key] for key in current):
                raise CheckError("INPUT_OR_POLICY_CHANGED")
        return {"verified_objects": sorted(snapshots), "same_bytes": True}
    report.check("09", "输入与策略前后摘要一致", integrity_check)
    selected = [step["status"] for step in report.data["steps"]]
    outcome = "failed" if "failed" in selected else "blocked" if "blocked" in selected else "passed"
    report.record("10", "真实 MCP 分类准备与用户澄清", "blocked", code="EXPLICIT_INPUT_CONTRACT_REQUIRED",
                  evidence={"required": ["trusted_mcp_config", "identities_and_allowed_roots", "source_crs_license_sensitivity",
                                         "csv_column_mapping_and_palette", "class_semantics_if_requested"], "input_pixels_read": False})
    report.record("11", "真实地图 G1/G2、渲染、终检和 G3 交付", "not_run", code="BUSINESS_TEMPLATE_AND_APPROVALS_REQUIRED",
                  evidence={"business_admission_not_bypassed": True, "approval_fabricated": False})
    report.record("12", "VS Code Claude Code 插件内执行验收", "not_run", code="HOST_SESSION_EVIDENCE_REQUIRED",
                  evidence={"label_is_not_proof": True, "needs_plugin_transcript_or_human_observation": True})
    report.data.update(selected_phase_status=outcome, completed_at=now())
    report.flush()
    print(json.dumps({"ok": outcome == "passed", "selected_phase_status": outcome,
                      "real_map_acceptance": "not_completed", "plugin_acceptance": "not_verified",
                      "report_dir": report.root.relative_to(REPO_ROOT).as_posix()}, ensure_ascii=False))
    return {"passed": 0, "failed": 2, "blocked": 3}[outcome]


if __name__ == "__main__":
    raise SystemExit(main())
