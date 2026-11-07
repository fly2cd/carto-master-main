from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..errors import CartoError, ProtocolError
from ..schema_registry import SchemaRegistry, load_document
from ..security.paths import PathGuard

MAX_CONFIG_BYTES = 512 * 1024
CAPABILITIES = ("file_read", "gis_read", "spatial_analysis", "map_render", "map_export")


def _is_link(path: Path) -> bool:
    return path.is_symlink() or bool(
        getattr(path.lstat(), "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    )


def _local_result(status: str, code: str) -> dict[str, Any]:
    return {
        "status": status, "scope": "isolated-skill-resource-read",
        "skill_document_read": False, "resource_read": False,
        "tool_names": [], "code": code,
    }


class HermesHostProbe:
    """Read-only installation inspection; never authorizes a map or a tool binding.

    The optional child calls installed Hermes skill_view, not an LLM or an MCP
    server. It is deliberately NOT evidence about the user's running session.
    """

    def __init__(self, *, allowed_roots: list[str], project_root: str, host_home: str) -> None:
        self.guard = PathGuard(allowed_roots)
        self.project = self.guard.resolve(project_root, must_exist=True)
        self.home = self.guard.resolve(host_home, must_exist=True)
        if not self.project.is_dir() or not self.home.is_dir():
            raise ProtocolError("HOST_PROBE_ROOT_NOT_DIRECTORY", "Project and host roots must be directories")
        self.skill = self.guard.resolve(self.project / "skills/carto-agent", must_exist=True)
        self.skill_file = self.guard.resolve(self.skill / "SKILL.md", must_exist=True)
        self.resource = self.guard.resolve(self.skill / "schemas/layout.schema.json", must_exist=True)

    def _configuration(self) -> dict[str, Any]:
        summary: dict[str, Any] = {"state": "missing", "terminal_backend": "unspecified", "mcp_servers": []}
        try:
            path = self.guard.resolve(self.home / "config.yaml")
            if not path.exists():
                return summary
            if path.stat().st_size > MAX_CONFIG_BYTES:
                summary["state"] = "invalid"
                return summary
            config = load_document(path)
            if not isinstance(config, dict):
                summary["state"] = "invalid"
                return summary
            terminal = config.get("terminal", {})
            if not isinstance(terminal, dict):
                summary["state"] = "invalid"
                return summary
            backend = terminal.get("backend")
            summary["terminal_backend"] = backend if backend in ("local", "ssh", "docker", "wsl") else ("other" if backend else "unspecified")
            servers = config.get("mcp_servers", {})
            if not isinstance(servers, dict) or len(servers) > 128:
                summary["state"] = "invalid"
                return summary
            summary["state"] = "read"
            for index, server in enumerate(servers.values(), 1):
                if not isinstance(server, dict):
                    summary["state"] = "invalid"
                    summary["mcp_servers"] = []
                    return summary
                # Even names can carry secrets. Do not export names, URLs, args,
                # env, arbitrary config fields, or parser exception messages.
                transport = "stdio" if server.get("command") else "remote" if server.get("url") else "unspecified"
                summary["mcp_servers"].append({"ordinal": index, "transport": transport, "verification": "not-connected"})
        except (CartoError, OSError, ValueError, TypeError):
            summary["state"] = "unreadable"
        return summary

    def _registrations(self) -> list[dict[str, Any]]:
        records = []
        # Inspect only known global locations; no recursive traversal of skills.
        # A registration junction is inspected as metadata, never used to read
        # arbitrary targets. All content reads use the approved canonical Skill.
        for root in (self.home / "skills", self.project / ".hermes/skills"):
            try:
                root = self.guard.resolve(root)
                if not root.is_dir():
                    continue
                candidates = [root / "carto-agent"]
                children = sorted(root.iterdir(), key=lambda item: item.name)[:128]
                for child in children:
                    if child.is_dir() and not _is_link(child):
                        candidates.append(child / "carto-agent")
                for candidate in candidates:
                    if not os.path.lexists(candidate):
                        continue
                    self.guard.resolve(candidate.parent, must_exist=True)
                    target = candidate.resolve(strict=False)
                    matches = target == self.skill
                    records.append({
                        "path": str(candidate), "kind": "link" if _is_link(candidate) else "directory",
                        "matches_workspace": matches,
                    })
            except (CartoError, OSError):
                continue
        return records

    def _version(self) -> str | None:
        try:
            path = self.guard.resolve(self.home / "hermes-agent/pyproject.toml", must_exist=True)
            if path.stat().st_size > MAX_CONFIG_BYTES:
                return None
            value = tomllib.loads(path.read_text(encoding="utf-8"))["project"]["version"]
            if isinstance(value, str) and re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:[a-zA-Z0-9.+-]*)", value):
                return value
        except (CartoError, OSError, ValueError, KeyError, TypeError):
            pass
        return None

    def _verify_local_tools(self, host_python: str, timeout: float) -> dict[str, Any]:
        if not 1 <= timeout <= 120:
            raise ProtocolError("HOST_PROBE_TIMEOUT_INVALID", "Timeout must be between 1 and 120 seconds")
        interpreter = self.guard.resolve(host_python, must_exist=True)
        source = self.guard.resolve(self.home / "hermes-agent", must_exist=True)
        if not interpreter.is_file() or not source.is_dir():
            raise ProtocolError("HOST_PROBE_RUNTIME_INVALID", "Hermes interpreter and source are required")
        worker = Path(__file__).with_name("hermes_probe_worker.py")
        # Do not pass API keys, provider config overrides, or another terminal backend.
        env = {key: value for key, value in os.environ.items() if key.upper() in {
            "SYSTEMROOT", "WINDIR", "PATH", "PATHEXT", "COMSPEC", "USERPROFILE", "HOME", "LOCALAPPDATA", "APPDATA",
        }}
        env.update(HERMES_HOME=str(self.home), PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8", TERMINAL_ENV="local")
        try:
            completed = subprocess.run(
                [str(interpreter), "-I", "-B", str(worker), str(source), str(self.home), str(self.skill)],
                cwd=self.project, env=env, capture_output=True, encoding="utf-8", errors="replace",
                timeout=timeout, check=False, stdin=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except subprocess.TimeoutExpired:
            return _local_result("timeout", "HOST_PROBE_TIMEOUT")
        except OSError:
            return _local_result("failed", "HOST_RUNTIME_START_FAILED")
        if completed.returncode != 0:
            return _local_result("failed", "HOST_RUNTIME_FAILED")
        try:
            value = json.loads(completed.stdout)
            SchemaRegistry().validate("host-preflight", {**self._report, "local_probe": value})
            return value
        except (CartoError, ValueError, TypeError):
            return _local_result("failed", "HOST_RUNTIME_OUTPUT_INVALID")

    def run(self, *, verify_local_tools: bool = False, host_python: str | None = None, timeout: float = 30) -> dict[str, Any]:
        if verify_local_tools and not host_python:
            raise ProtocolError("HOST_PYTHON_REQUIRED", "Use --host-python with --verify-local-tools")
        if host_python and not verify_local_tools:
            raise ProtocolError("HOST_PROBE_OPT_IN_REQUIRED", "Use --verify-local-tools to run installed Hermes code")
        executable = self.guard.resolve(self.home / "bin" / ("hermes.exe" if os.name == "nt" else "hermes"))
        registrations = self._registrations()
        self._report: dict[str, Any] = {
            "schema_version": 1, "host": "hermes",
            "probed_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "status": "needs-session-verification",
            "project_root": str(self.project), "host_home": str(self.home),
            "installation": {"executable_present": executable.is_file(), "source_version": self._version()},
            "skill": {
                "path": str(self.skill), "document_digest": "sha256:" + hashlib.sha256(self.skill_file.read_bytes()).hexdigest(),
                "registrations": registrations,
            },
            "configuration": self._configuration(),
            "local_probe": _local_result("not-run", "LOCAL_PROBE_NOT_REQUESTED"),
            "resource": {"path": str(self.resource), "digest": "sha256:" + hashlib.sha256(self.resource.read_bytes()).hexdigest()},
            "capabilities": {name: "unverified" for name in CAPABILITIES},
            "active_session_verified": False, "stage_passed": False, "production_ready": False,
            "next_actions": ["VERIFY_ACTIVE_SESSION", "TEST_FILE_READ", "TEST_GIS_READ", "TEST_SPATIAL_ANALYSIS", "TEST_RENDER_EXPORT"],
        }
        if verify_local_tools:
            self._report["local_probe"] = self._verify_local_tools(str(host_python), timeout)
            for path, expected in ((self.skill_file, self._report["skill"]["document_digest"]),
                                   (self.resource, self._report["resource"]["digest"])):
                checked = self.guard.resolve(path, must_exist=True)
                if "sha256:" + hashlib.sha256(checked.read_bytes()).hexdigest() != expected:
                    self._report["local_probe"] = _local_result("failed", "HOST_PROBE_INPUT_CHANGED")
        if (not executable.is_file() or not any(item["matches_workspace"] for item in registrations)
                or self._report["configuration"]["state"] != "read"
                or self._report["local_probe"]["status"] in {"failed", "timeout"}):
            self._report["status"] = "attention-required"
        SchemaRegistry().validate("host-preflight", self._report)
        return self._report

    def save(self, report: dict[str, Any], output: str) -> Path:
        SchemaRegistry().validate("host-preflight", report)
        # Read permission for Hermes home must not turn into report write permission.
        path = PathGuard([self.project]).resolve(output, base_root=self.project)
        if path.suffix.lower() != ".json":
            raise ProtocolError("HOST_REPORT_FORMAT_INVALID", "Host reports must be JSON")
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(report, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        return path
