from __future__ import annotations

import os
import platform
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..canonical import sha256_digest


class RendererCapabilityProbe:
    """Performs a renderer capability handshake for the MapLibre + SVG overlay pipeline.

    The values collected here may be submitted by a controlled headless renderer;
    the backend validates them against known ranges and records an environment
    fingerprint.
    """

    DEFAULT_RENDERER = "maplibre-web"
    BROWSER_COMMANDS = ("chromium", "chromium-browser", "google-chrome", "chrome", "msedge")

    def __init__(self, timeout_seconds: float = 10.0) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.timeout_seconds = timeout_seconds

    def run(self) -> dict[str, Any]:
        tools = self._probe_helper_tools()
        profile = self._detect_profile(tools)
        capabilities = self._derive_capabilities(profile)
        required = (
            capabilities["webgl_available"],
            capabilities["offline_rendering"],
            capabilities["headless_export"],
            capabilities["chinese_font"],
        )
        status = "available" if all(required) else "unavailable"
        body = {
            "schema_version": 1,
            "probe_id": "renderer-capability-probe",
            "status": status,
            "platform": platform.platform(),
            "python_version": platform.python_version(),
            "tools": tools,
            "chinese_fonts": profile["available_fonts"],
            "capabilities": capabilities,
            "renderer_profile": profile,
            "probed_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        }
        body["fingerprint"] = sha256_digest({
            "platform": body["platform"],
            "python_version": body["python_version"],
            "tools": body["tools"],
            "chinese_fonts": body["chinese_fonts"],
            "capabilities": body["capabilities"],
            "renderer_profile": body["renderer_profile"],
        })
        if status == "unavailable":
            body["error"] = {
                "code": "CAPABILITY_NOT_AVAILABLE",
                "message": "A controlled browser/WebGL renderer handshake has not established all production capabilities",
            }
        return body

    @classmethod
    def _detect_profile(cls, tools: dict[str, Any]) -> dict[str, Any]:
        browser = tools["browser"]
        return {
            "renderer_id": cls.DEFAULT_RENDERER,
            "frontend_build": "2026.09.15",
            "renderer_version": "1.0.0",
            "maplibre_version": "3.6.0",
            "overlay_engine_version": "1.0.0",
            "browser_engine": browser.get("command") if browser.get("available") else "unavailable",
            "webgl_available": False,
            "supported_export_formats": ["svg"],
            "max_canvas_width": 16384,
            "max_canvas_height": 16384,
            "device_pixel_ratio": 2.0,
            "available_fonts": cls._font_probe(),
            "offline_rendering": False,
        }

    @staticmethod
    def _derive_capabilities(profile: dict[str, Any]) -> dict[str, Any]:
        has_chinese = bool(profile.get("available_fonts"))
        return {
            "webgl_available": bool(profile.get("webgl_available")),
            "offline_rendering": bool(profile.get("offline_rendering")),
            "svg_composition": True,
            "headless_export": False,
            "chinese_font": has_chinese,
            "max_canvas_width": int(profile.get("max_canvas_width", 0)),
            "max_canvas_height": int(profile.get("max_canvas_height", 0)),
            "supported_export_formats": list(profile.get("supported_export_formats", [])),
        }

    def _probe_helper_tools(self) -> dict[str, Any]:
        return {
            "browser": self._probe_first(self.BROWSER_COMMANDS, ["--version"]),
            "node": self._probe("node", ["--version"]),
        }

    def _probe_first(self, commands: tuple[str, ...], arguments: list[str]) -> dict[str, Any]:
        for command in commands:
            if shutil.which(command):
                result = self._probe(command, arguments)
                result["command"] = command
                return result
        result = self._unavailable_result()
        result["command"] = None
        return result

    def _probe(self, command: str, arguments: list[str]) -> dict[str, Any]:
        executable = shutil.which(command)
        if not executable:
            return self._unavailable_result()
        try:
            completed = subprocess.run(
                [executable, *arguments],
                capture_output=True,
                text=True,
                check=False,
                timeout=self.timeout_seconds,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {
                "available": False,
                "executable": str(Path(executable).resolve()),
                "version": None,
                "exit_code": None,
                "error": type(exc).__name__,
            }
        output = (completed.stdout or completed.stderr).strip().splitlines()
        return {
            "available": completed.returncode == 0,
            "executable": str(Path(executable).resolve()),
            "version": output[0][:256] if output else None,
            "exit_code": completed.returncode,
        }

    @staticmethod
    def _unavailable_result() -> dict[str, Any]:
        return {"available": False, "executable": None, "version": None, "exit_code": None}

    @staticmethod
    def _font_probe() -> list[str]:
        candidates: list[Path] = []
        windows = os.environ.get("WINDIR")
        if windows:
            candidates.append(Path(windows) / "Fonts")
        names = ("msyh", "simhei", "simsun", "notosanscjk", "sourcehansans")
        found: list[str] = []
        for root in candidates:
            if root.is_dir():
                found.extend(sorted(path.name for path in root.iterdir() if path.is_file() and any(name in path.name.casefold() for name in names)))
        return found[:32]
