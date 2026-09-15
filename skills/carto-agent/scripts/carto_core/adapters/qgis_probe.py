from __future__ import annotations

import os
import platform
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..canonical import sha256_digest


class QgisEnvironmentProbe:
    def __init__(self, timeout_seconds: float = 10.0) -> None:
        self.timeout_seconds = timeout_seconds

    def run(self) -> dict[str, Any]:
        tools = {name: self._probe(name, args) for name, args in {"qgis_process": ["--version"], "gdalinfo": ["--version"], "projinfo": ["--version"]}.items()}
        fonts = self._font_probe()
        capabilities = {
            "qgis_headless": tools["qgis_process"]["available"],
            "crs_transform": tools["projinfo"]["available"] or tools["gdalinfo"]["available"],
            "a3_pdf_png": tools["qgis_process"]["available"],
            "chinese_font": bool(fonts),
            "isolated_process_exit": all(item.get("exit_code") in {0, None} for item in tools.values()),
        }
        status = "available" if all(capabilities.values()) else "unavailable"
        body = {"schema_version": 1, "probe_id": "qgis-environment-probe", "status": status, "platform": platform.platform(), "python_version": platform.python_version(), "tools": tools, "chinese_fonts": fonts, "capabilities": capabilities, "probed_at": datetime.now(UTC).isoformat().replace("+00:00", "Z")}
        body["fingerprint"] = sha256_digest({key: body[key] for key in ("platform", "python_version", "tools", "chinese_fonts", "capabilities")})
        if status == "unavailable":
            body["error"] = {"code": "CAPABILITY_NOT_AVAILABLE", "message": "Required QGIS production capabilities are not all available"}
        return body

    def _probe(self, command: str, arguments: list[str]) -> dict[str, Any]:
        executable = shutil.which(command)
        if not executable:
            return {"available": False, "executable": None, "version": None, "exit_code": None}
        try:
            completed = subprocess.run([executable, *arguments], capture_output=True, text=True, timeout=self.timeout_seconds, check=False)
            version = (completed.stdout or completed.stderr).strip().splitlines()[:1]
            return {"available": completed.returncode == 0, "executable": str(Path(executable).resolve()), "version": version[0][:256] if version else None, "exit_code": completed.returncode}
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {"available": False, "executable": executable, "version": None, "exit_code": None, "error": type(exc).__name__}

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
