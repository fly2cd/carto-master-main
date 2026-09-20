from __future__ import annotations

import os
import platform
import shutil
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..canonical import sha256_digest
from .controlled_renderer import (
    FRONTEND_BUILD,
    MAPLIBRE_VERSION,
    OVERLAY_ENGINE_VERSION,
    RENDERER_VERSION,
    BrowserLimits,
    ControlledBrowserRenderer,
    browser_version,
    discover_browser,
)


class RendererCapabilityProbe:
    """Perform a real local Chromium/MapLibre capability handshake."""

    DEFAULT_RENDERER = "maplibre-web"

    def __init__(self, timeout_seconds: float = 10.0) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.timeout_seconds = timeout_seconds
        self._webgl_error: str | None = None

    def run(self) -> dict[str, Any]:
        tools = self._probe_helper_tools()
        fonts = self._font_probe()
        webgl = self._probe_webgl(tools)
        profile = self._detect_profile(tools, fonts, webgl)
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
            "chinese_fonts": fonts,
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
            detail = f"; WebGL probe failed: {self._webgl_error}" if self._webgl_error else ""
            body["error"] = {
                "code": "CAPABILITY_NOT_AVAILABLE",
                "message": "Controlled browser, WebGL, offline export, and a pinned Chinese font are required" + detail,
            }
        return body

    @classmethod
    def _detect_profile(cls, tools: dict[str, Any], fonts: list[str], webgl: bool) -> dict[str, Any]:
        browser = tools["browser"]
        return {
            "renderer_id": cls.DEFAULT_RENDERER,
            "frontend_build": FRONTEND_BUILD,
            "renderer_version": RENDERER_VERSION,
            "maplibre_version": MAPLIBRE_VERSION,
            "overlay_engine_version": OVERLAY_ENGINE_VERSION,
            "browser_engine": browser.get("version") or "unavailable",
            "webgl_available": webgl,
            "supported_export_formats": ["svg", "pdf", "png"] if webgl else ["svg"],
            "max_canvas_width": 16384,
            "max_canvas_height": 16384,
            "device_pixel_ratio": 2.0,
            "available_fonts": fonts,
            "offline_rendering": webgl,
        }

    @staticmethod
    def _derive_capabilities(profile: dict[str, Any]) -> dict[str, Any]:
        has_chinese = bool(profile.get("available_fonts"))
        headless = bool(profile.get("webgl_available") and profile.get("offline_rendering"))
        return {
            "webgl_available": bool(profile.get("webgl_available")),
            "offline_rendering": bool(profile.get("offline_rendering")),
            "svg_composition": True,
            "headless_export": headless,
            "chinese_font": has_chinese,
            "max_canvas_width": int(profile.get("max_canvas_width", 0)),
            "max_canvas_height": int(profile.get("max_canvas_height", 0)),
            "supported_export_formats": list(profile.get("supported_export_formats", [])),
        }

    def _probe_helper_tools(self) -> dict[str, Any]:
        browser = discover_browser()
        browser_result = self._unavailable_result()
        browser_result["command"] = None
        if browser is not None:
            browser_result = {
                "available": True,
                "command": browser.name,
                "executable": str(browser),
                "version": browser_version(browser),
                "exit_code": 0,
            }
        return {"browser": browser_result, "node": self._probe("node", ["--version"])}

    def _probe_webgl(self, tools: dict[str, Any]) -> bool:
        executable = tools["browser"].get("executable")
        if not executable:
            self._webgl_error = "RENDER_BROWSER_UNAVAILABLE"
            return False
        timeout = max(0.05, self.timeout_seconds)
        try:
            with tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                renderer = ControlledBrowserRenderer(
                    allowed_roots=[root], output_root=root,
                    attestation_key=b"renderer-probe-key-material-32-bytes",
                    limits=BrowserLimits(timeout_seconds=timeout, cpu_seconds=max(1, int(timeout) + 1)),
                    browser=executable,
                )
                available = renderer.probe_webgl()
                self._webgl_error = None if available else "RENDER_WEBGL_UNAVAILABLE"
                return available
        except Exception as exc:
            self._webgl_error = str(getattr(exc, "code", type(exc).__name__))[:128]
            return False

    def _probe(self, command: str, arguments: list[str]) -> dict[str, Any]:
        executable = shutil.which(command)
        if not executable:
            return self._unavailable_result()
        try:
            completed = subprocess.run(
                [executable, *arguments], capture_output=True, text=True,
                check=False, timeout=self.timeout_seconds,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {
                "available": False, "executable": str(Path(executable).resolve()),
                "version": None, "exit_code": None, "error": type(exc).__name__,
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
        candidates.extend([Path("/usr/share/fonts/opentype/noto"), Path("/usr/share/fonts/truetype/noto")])
        aliases = (
            ("notosanssc", "Noto Sans SC"),
            ("notosanscjk", "Noto Sans CJK SC"),
            ("sourcehansans", "Source Han Sans SC"),
            ("msyh", "Microsoft YaHei"),
            ("simhei", "SimHei"),
            ("simsun", "SimSun"),
        )
        found: set[str] = set()
        for root in candidates:
            if not root.is_dir():
                continue
            for path in root.iterdir():
                if not path.is_file() or not RendererCapabilityProbe._supported_font_file(path):
                    continue
                folded = path.name.casefold().replace("-", "").replace("_", "")
                for marker, family in aliases:
                    if marker in folded:
                        found.add(family)
        return sorted(found)

    @staticmethod
    def _supported_font_file(path: Path) -> bool:
        try:
            signature = path.read_bytes()[:4]
        except OSError:
            return False
        return signature in {b"wOF2", b"\x00\x01\x00\x00", b"true", b"OTTO"}
