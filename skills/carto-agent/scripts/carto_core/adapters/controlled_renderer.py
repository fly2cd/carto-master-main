from __future__ import annotations

import base64
import ctypes
import hashlib
import html
import json
import os
import platform
import shutil
import socket
import struct
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from ..canonical import sha256_digest
from ..errors import ConfigurationError, ProtocolError, SecurityError
from ..security.paths import PathGuard
from .svg_compositor import SvgCompositor

FRONTEND_BUILD = "2026.09.18"
RENDERER_VERSION = "1.0.0"
MAPLIBRE_VERSION = "3.6.0"
OVERLAY_ENGINE_VERSION = "1.0.0"
RANDOM_SEED = 20260918
_ASSET_ROOT = Path(__file__).with_name("web_assets")
_MAPLIBRE_JS = _ASSET_ROOT / f"maplibre-gl-{MAPLIBRE_VERSION}.js"
_MAPLIBRE_CSS = _ASSET_ROOT / f"maplibre-gl-{MAPLIBRE_VERSION}.css"
_BROWSER_CANDIDATES = (
    "chromium",
    "chromium-browser",
    "google-chrome",
    "chrome",
    "msedge",
)
_WINDOWS_BROWSER_PATHS = (
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
)
_BROWSER_LAUNCH_POLICY_VERSION = "1"
_BROWSER_FIXED_FLAGS = (
    "--headless=new",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-background-networking",
    "--disable-component-update",
    "--disable-default-apps",
    "--disable-domain-reliability",
    "--disable-extensions",
    "--disable-sync",
    "--metrics-recording-only",
    "--mute-audio",
    "--hide-scrollbars",
    "--enable-webgl",
    "--use-angle=swiftshader",
    "--enable-unsafe-swiftshader",
    "--disable-features=OptimizationHints,MediaRouter",
    "--host-resolver-rules=MAP * 0.0.0.0, EXCLUDE 127.0.0.1",
)
_WINDOWS_BROWSER_FLAGS = (
    # Headless Chromium renderer/GPU subprocesses cannot initialize inside some
    # Windows service/CI tokens. This runner only opens generated local HTML and
    # pinned assets; the Job Object, deny-all network policy, CSP, path guard,
    # resource digests, and process-tree cleanup remain mandatory controls.
    "--no-sandbox",
)


class _VS_FIXEDFILEINFO(ctypes.Structure):
    _fields_ = [
        ("dwSignature", ctypes.c_uint32),
        ("dwStrucVersion", ctypes.c_uint32),
        ("dwFileVersionMS", ctypes.c_uint32),
        ("dwFileVersionLS", ctypes.c_uint32),
        ("dwProductVersionMS", ctypes.c_uint32),
        ("dwProductVersionLS", ctypes.c_uint32),
        ("dwFileFlagsMask", ctypes.c_uint32),
        ("dwFileFlags", ctypes.c_uint32),
        ("dwFileOS", ctypes.c_uint32),
        ("dwFileType", ctypes.c_uint32),
        ("dwFileSubtype", ctypes.c_uint32),
        ("dwFileDateMS", ctypes.c_uint32),
        ("dwFileDateLS", ctypes.c_uint32),
    ]


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def discover_browser() -> Path | None:
    for command in _BROWSER_CANDIDATES:
        executable = shutil.which(command)
        if executable:
            return Path(executable).resolve()
    if os.name == "nt":
        for candidate in _WINDOWS_BROWSER_PATHS:
            if candidate.is_file():
                return candidate.resolve()
    return None


def browser_version(executable: Path) -> str:
    if os.name == "nt":
        try:
            size = ctypes.windll.version.GetFileVersionInfoSizeW(str(executable), None)
            if size:
                buffer = ctypes.create_string_buffer(size)
                ctypes.windll.version.GetFileVersionInfoW(str(executable), 0, size, buffer)
                value = ctypes.c_void_p()
                length = ctypes.c_uint()
                if ctypes.windll.version.VerQueryValueW(buffer, "\\", ctypes.byref(value), ctypes.byref(length)):
                    if length.value >= ctypes.sizeof(_VS_FIXEDFILEINFO):
                        info = ctypes.cast(value, ctypes.POINTER(_VS_FIXEDFILEINFO)).contents
                        if info.dwSignature == 0xFEEF04BD:
                            major = (info.dwFileVersionMS >> 16) & 0xFFFF
                            minor = info.dwFileVersionMS & 0xFFFF
                            build = (info.dwFileVersionLS >> 16) & 0xFFFF
                            patch = info.dwFileVersionLS & 0xFFFF
                            return f"Chromium {major}.{minor}.{build}.{patch}"
        except (AttributeError, OSError, ValueError):
            pass
    try:
        completed = subprocess.run(
            [str(executable), "--version"], capture_output=True, text=True,
            check=False, timeout=5,
        )
        output = (completed.stdout or completed.stderr).strip().splitlines()
        if completed.returncode == 0 and output:
            return output[0][:128]
    except (OSError, subprocess.TimeoutExpired):
        pass
    return f"Chromium unknown ({executable.name})"


@dataclass(frozen=True, slots=True)
class BrowserLimits:
    timeout_seconds: float = 30.0
    cpu_seconds: int = 25
    memory_bytes: int = 1024 * 1024 * 1024
    temporary_disk_bytes: int = 256 * 1024 * 1024

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0 or self.cpu_seconds <= 0:
            raise ValueError("browser time limits must be positive")
        if self.memory_bytes < 128 * 1024 * 1024:
            raise ValueError("browser memory limit is too small")
        if self.temporary_disk_bytes < 16 * 1024 * 1024:
            raise ValueError("temporary disk limit is too small")


class _WindowsJob:
    """Best-effort Windows Job Object enforcing CPU, memory and tree cleanup."""

    JOB_OBJECT_LIMIT_JOB_TIME = 0x00000004
    JOB_OBJECT_LIMIT_JOB_MEMORY = 0x00000200
    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
    JobObjectExtendedLimitInformation = 9

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_ulonglong),
            ("WriteOperationCount", ctypes.c_ulonglong),
            ("OtherOperationCount", ctypes.c_ulonglong),
            ("ReadTransferCount", ctypes.c_ulonglong),
            ("WriteTransferCount", ctypes.c_ulonglong),
            ("OtherTransferCount", ctypes.c_ulonglong),
        ]

    class BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_longlong),
            ("PerJobUserTimeLimit", ctypes.c_longlong),
            ("LimitFlags", ctypes.c_ulong),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", ctypes.c_ulong),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", ctypes.c_ulong),
            ("SchedulingClass", ctypes.c_ulong),
        ]

    class EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        pass

    EXTENDED_LIMIT_INFORMATION._fields_ = [
        ("BasicLimitInformation", BASIC_LIMIT_INFORMATION),
        ("IoInfo", IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]

    def __init__(self, limits: BrowserLimits) -> None:
        self.handle: int | None = None
        if os.name != "nt":
            return
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.CreateJobObjectW(None, None)
        if not handle:
            raise ConfigurationError("BROWSER_LIMIT_SETUP_FAILED", "CreateJobObjectW failed")
        info = self.EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.PerJobUserTimeLimit = limits.cpu_seconds * 10_000_000
        info.BasicLimitInformation.LimitFlags = (
            self.JOB_OBJECT_LIMIT_JOB_TIME
            | self.JOB_OBJECT_LIMIT_JOB_MEMORY
            | self.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        )
        info.JobMemoryLimit = limits.memory_bytes
        if not kernel32.SetInformationJobObject(
            handle, self.JobObjectExtendedLimitInformation,
            ctypes.byref(info), ctypes.sizeof(info),
        ):
            kernel32.CloseHandle(handle)
            raise ConfigurationError("BROWSER_LIMIT_SETUP_FAILED", "SetInformationJobObject failed")
        self.handle = handle

    def assign(self, process: subprocess.Popen[str]) -> None:
        if self.handle is None:
            return
        if not ctypes.windll.kernel32.AssignProcessToJobObject(self.handle, int(process._handle)):  # type: ignore[attr-defined]
            self.close()
            raise ConfigurationError("BROWSER_LIMIT_SETUP_FAILED", "AssignProcessToJobObject failed")

    def close(self) -> None:
        if self.handle is not None:
            ctypes.windll.kernel32.CloseHandle(self.handle)
            self.handle = None


class ControlledBrowserRenderer:
    """Offline, bounded Chromium runner for deterministic MapLibre previews."""

    def __init__(
        self,
        *,
        allowed_roots: list[str | os.PathLike[str]],
        output_root: str | os.PathLike[str],
        attestation_key: bytes,
        limits: BrowserLimits | None = None,
        browser: str | os.PathLike[str] | None = None,
    ) -> None:
        if len(attestation_key) < 32:
            raise SecurityError("RENDER_ATTESTATION_KEY_WEAK", "Attestation key must be at least 32 bytes")
        self.path_guard = PathGuard(allowed_roots)
        self.output_root = self.path_guard.resolve(output_root, must_exist=True)
        self.attestation_key = attestation_key
        self.limits = limits or BrowserLimits()
        selected = Path(browser).resolve() if browser else discover_browser()
        if selected is None or not selected.is_file():
            raise ConfigurationError("RENDER_BROWSER_UNAVAILABLE", "A supported Chromium browser was not found")
        self.browser = selected
        for asset in (_MAPLIBRE_JS, _MAPLIBRE_CSS):
            if not asset.is_file():
                raise ConfigurationError("RENDER_FRONTEND_ASSET_MISSING", str(asset))
        self.browser_engine = browser_version(self.browser)
        self.environment_fingerprint = sha256_digest({
            "browser": self.browser_engine,
            "browser_binary": sha256_file(self.browser),
            "frontend_build": FRONTEND_BUILD,
            "maplibre": sha256_file(_MAPLIBRE_JS),
            "maplibre_css": sha256_file(_MAPLIBRE_CSS),
            "platform": platform.platform(),
            "limits": asdict(self.limits),
            "browser_launch_policy": {
                "version": _BROWSER_LAUNCH_POLICY_VERSION,
                "flags": list(_BROWSER_FIXED_FLAGS + (_WINDOWS_BROWSER_FLAGS if os.name == "nt" else ())),
            },
        })

    def receipt_controls(self) -> dict[str, Any]:
        return {
            "network_policy": "deny-all",
            "timeout_seconds": self.limits.timeout_seconds,
            "cpu_seconds": self.limits.cpu_seconds,
            "memory_bytes": self.limits.memory_bytes,
            "temporary_disk_bytes": self.limits.temporary_disk_bytes,
        }

    def probe_webgl(self) -> bool:
        scene = {
            "viewport": {"width_px": 64, "height_px": 64, "device_pixel_ratio": 1, "background": "#FFFFFF"},
            "camera": {"bounds": [-1, -1, 1, 1], "bearing": 0, "pitch": 0, "padding": {"top": 0, "right": 0, "bottom": 0, "left": 0}},
            "map": {"sources": [], "layers": []},
            "random_seed": RANDOM_SEED,
        }
        work_root = Path(tempfile.mkdtemp(prefix="probe-", dir=self.output_root))
        try:
            html_path = work_root / "probe.html"
            html_path.write_text(self._build_html(scene, {}), encoding="utf-8", newline="\n")
            with self._open_browser(work_root, scene) as browser_session:
                browser_session.navigate(self._file_url(html_path))
                browser_session.wait_for_map_ready()
            return True
        finally:
            shutil.rmtree(work_root, ignore_errors=True)

    def render(self, session: dict[str, Any], profile: Any) -> dict[str, Any]:
        scene = session["scene"]
        started_at = _utc_now()
        session_root = self.path_guard.resolve(self.output_root / session["session_id"])
        if session_root.exists():
            raise SecurityError("RENDER_OUTPUT_EXISTS", str(session_root))
        session_root.mkdir(parents=False)
        resources, evidence = self._load_resources(scene)
        resource_set_digest = sha256_digest([
            {"resource_id": item["resource_id"], "digest": item["digest"], "status": item["status"]}
            for item in evidence
        ])
        execution_digest = sha256_digest({
            "scene_digest": session["scene_digest"],
            "resource_set_digest": resource_set_digest,
            "renderer_profile_digest": profile.profile_digest(),
            "environment_fingerprint": self.environment_fingerprint,
            "random_seed": RANDOM_SEED,
        })
        work_root = Path(tempfile.mkdtemp(prefix="work-", dir=session_root))
        try:
            html_path = work_root / "scene.html"
            html_path.write_text(self._build_html(scene, resources), encoding="utf-8", newline="\n")
            map_png = work_root / "map.png"
            with self._open_browser(work_root, scene) as browser_session:
                browser_session.navigate(self._file_url(html_path))
                browser_session.wait_for_map_ready()
                map_png.write_bytes(browser_session.capture_png())
                self._assert_png(map_png, scene)

                svg_path = session_root / "map.svg"
                inline_fonts = [
                    (item["font_family"], item["bytes"])
                    for item in resources.values() if item["kind"] == "font"
                ]
                SvgCompositor(
                    scene["viewport"]["width_px"], scene["viewport"]["height_px"],
                    self.path_guard, scene["viewport"]["background"],
                ).compose(map_png, scene["overlays"], svg_path, inline_fonts=inline_fonts)

                requested = set(scene["export"]["targets"])
                artifacts: list[dict[str, Any]] = []
                if "svg" in requested:
                    artifacts.append(self._artifact("svg", svg_path, "image/svg+xml", "mixed"))
                if "png" in requested or "pdf" in requested:
                    browser_session.navigate(self._file_url(svg_path))
                    browser_session.wait_for_document_ready()
                if "png" in requested:
                    png_path = session_root / "map.png"
                    png_path.write_bytes(browser_session.capture_png())
                    self._assert_png(png_path, scene)
                    artifacts.append(self._artifact("png", png_path, "image/png", "raster"))
                if "pdf" in requested:
                    pdf_path = session_root / "map.pdf"
                    pdf_path.write_bytes(browser_session.print_pdf())
                    self._assert_pdf(pdf_path)
                    artifacts.append(self._artifact("pdf", pdf_path, "application/pdf", "mixed"))

            completed_at = _utc_now()
            receipt: dict[str, Any] = {
                "schema_version": 1,
                "receipt_id": f"render-{execution_digest[7:31]}",
                "session_id": session["session_id"],
                "scene_id": session["scene_id"],
                "scene_revision": session["scene_revision"],
                "scene_digest": session["scene_digest"],
                "execution_digest": execution_digest,
                "resource_set_digest": resource_set_digest,
                "environment_fingerprint": self.environment_fingerprint,
                "random_seed": RANDOM_SEED,
                "renderer_id": profile.renderer_id,
                "renderer_profile_digest": profile.profile_digest(),
                "frontend_build_version": profile.frontend_build,
                "renderer_version": profile.renderer_version,
                "maplibre_version": profile.maplibre_version,
                "overlay_engine_version": profile.overlay_engine_version,
                "browser_version": profile.browser_engine,
                "status": "succeeded",
                "viewport": {key: scene["viewport"][key] for key in ("width_px", "height_px", "device_pixel_ratio")},
                "resource_evidence": evidence,
                "output_artifacts": artifacts,
                "composition": {
                    "map_body": "maplibre-webgl-raster",
                    "overlays": "svg-vector",
                    "svg": "raster-map-with-vector-overlays",
                    "png": "rasterized-composite",
                    "pdf": "engineering-preview-mixed" if "pdf" in requested else "not-requested",
                },
                "controls": self.receipt_controls(),
                "warnings": ["PDF is an engineering preview and is not claimed to be fully vector." ] if "pdf" in requested else [],
                "render_started_at": started_at,
                "render_completed_at": completed_at,
                "attestation_algorithm": "hmac-sha256",
                "renderer_attestation": "",
            }
            from .webmap_renderer import compute_renderer_attestation
            receipt["renderer_attestation"] = compute_renderer_attestation(receipt, self.attestation_key)
            return receipt
        finally:
            shutil.rmtree(work_root, ignore_errors=True)

    def _load_resources(self, scene: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
        loaded: dict[str, dict[str, Any]] = {}
        evidence: list[dict[str, Any]] = []
        required_fonts = iter(scene["renderer_requirements"]["required_fonts"])
        for resource in sorted(scene["resources"], key=lambda item: item["id"]):
            ref = resource["ref"]
            uri = ref.get("uri")
            if not uri:
                raise ProtocolError("RENDER_RESOURCE_URI_MISSING", resource["id"])
            parsed = urlparse(uri)
            if parsed.scheme and not Path(uri).is_absolute():
                raise SecurityError("RENDER_NETWORK_ACCESS_DENIED", uri)
            try:
                path = self.path_guard.resolve(uri, base_root=self.output_root, must_exist=True)
            except SecurityError as exc:
                if resource["kind"] == "font" and exc.code == "PATH_NOT_FOUND":
                    raise ProtocolError(
                        "RENDER_FONT_UNAVAILABLE", resource.get("font_family", resource["id"])
                    ) from exc
                raise
            actual_digest = sha256_file(path)
            if actual_digest != ref["digest"]:
                raise SecurityError("RENDER_RESOURCE_DIGEST_MISMATCH", resource["id"])
            data = path.read_bytes()
            item: dict[str, Any] = {"kind": resource["kind"], "path": path, "bytes": data}
            if resource["kind"] == "geojson":
                try:
                    item["json"] = json.loads(data.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise ProtocolError("RENDER_GEOJSON_INVALID", resource["id"]) from exc
                if item["json"].get("type") != "FeatureCollection":
                    raise ProtocolError("RENDER_GEOJSON_INVALID", resource["id"])
            if resource["kind"] == "font":
                item["font_family"] = resource.get("font_family") or next(required_fonts, "Noto Sans SC")
            loaded[resource["id"]] = item
            evidence.append({"resource_id": resource["id"], "digest": actual_digest, "status": "loaded"})
        return loaded, evidence

    def _build_html(self, scene: dict[str, Any], resources: dict[str, dict[str, Any]]) -> str:
        sources: dict[str, Any] = {}
        for source in scene["map"]["sources"]:
            if source["type"] != "geojson":
                raise ProtocolError("RENDER_SOURCE_TYPE_UNSUPPORTED", source["type"])
            sources[source["id"]] = {"type": "geojson", "data": resources[source["resource_id"]]["json"]}
        layers = []
        for layer in sorted(scene["map"]["layers"], key=lambda item: (item["z_index"], item["id"])):
            if layer["type"] not in {"fill", "circle"}:
                raise ProtocolError("RENDER_LAYER_TYPE_UNSUPPORTED", layer["type"])
            rendered = {"id": layer["id"], "source": layer["source_id"], "type": layer["type"]}
            for name in ("paint", "layout", "filter", "minzoom", "maxzoom"):
                if name in layer:
                    rendered[name] = layer[name]
            layers.append(rendered)
        style = {"version": 8, "sources": sources, "layers": layers}
        payload = json.dumps({
            "style": style,
            "bounds": scene["camera"]["bounds"],
            "padding": scene["camera"].get("padding", {"top": 0, "right": 0, "bottom": 0, "left": 0}),
            "bearing": scene["camera"]["bearing"],
            "pitch": scene["camera"]["pitch"],
            "background": scene["viewport"]["background"],
            "randomSeed": scene["random_seed"],
        }, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
        css = _MAPLIBRE_CSS.read_text(encoding="utf-8")
        script = _MAPLIBRE_JS.read_text(encoding="utf-8").replace("</script", "<\\/script")
        return f'''<!doctype html><html data-carto-status="starting"><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline' blob:; style-src 'unsafe-inline'; img-src data: blob:; font-src data:; worker-src blob:; connect-src 'none'">
<style>html,body,#map{{margin:0;width:100%;height:100%;overflow:hidden;background:{html.escape(scene['viewport']['background'])}}}{css}</style></head>
<body><div id="map"></div><script>{script}</script><script>
(()=>{{'use strict';const input={payload};let networkViolation='';
const rejectNetwork=(value)=>{{const url=String(value||'');if(url.startsWith('blob:')||url.startsWith('data:')||url.startsWith('file:'))return;networkViolation=url;document.documentElement.dataset.networkViolation=url;throw new Error('NETWORK_ACCESS_DENIED:'+url)}};
const originalFetch=window.fetch;window.fetch=(input,init)=>{{rejectNetwork(input&&input.url?input.url:input);return originalFetch(input,init)}};
const originalOpen=XMLHttpRequest.prototype.open;XMLHttpRequest.prototype.open=function(method,url){{rejectNetwork(url);return originalOpen.apply(this,arguments)}};
Math.random=(()=>{{let seed=input.randomSeed>>>0;return()=>{{seed=(1664525*seed+1013904223)>>>0;return seed/4294967296}}}})();
try{{if(!window.maplibregl)throw new Error('MAPLIBRE_NOT_LOADED');const map=new maplibregl.Map({{container:'map',style:input.style,bounds:input.bounds,fitBoundsOptions:{{padding:input.padding,duration:0}},bearing:input.bearing,pitch:input.pitch,interactive:false,attributionControl:false,preserveDrawingBuffer:true,fadeDuration:0,localIdeographFontFamily:'Noto Sans SC'}});
let failed=false;map.on('error',event=>{{failed=true;document.documentElement.dataset.cartoError=String(event.error||event)}});
map.once('idle',()=>{{if(failed||networkViolation){{document.documentElement.dataset.cartoStatus='error';return}}const canvas=map.getCanvas();const gl=canvas.getContext('webgl2')||canvas.getContext('webgl');document.documentElement.dataset.webgl=gl?'available':'unavailable';document.documentElement.dataset.maplibre=maplibregl.version;document.documentElement.dataset.cartoStatus=gl?'ready':'error';map.triggerRepaint()}});
setTimeout(()=>{{if(document.documentElement.dataset.cartoStatus==='starting')document.documentElement.dataset.cartoStatus='timeout'}},4000);
}}catch(error){{document.documentElement.dataset.cartoError=String(error);document.documentElement.dataset.cartoStatus='error'}}}})();
</script></body></html>'''

    def _open_browser(self, work_root: Path, scene: dict[str, Any]) -> "_ChromeCdpSession":
        return _ChromeCdpSession(self, work_root, scene)

    @staticmethod
    def _file_url(path: Path) -> str:
        return path.resolve().as_uri()

    @staticmethod
    def _directory_size(root: Path) -> int:
        total = 0
        for path in root.rglob("*"):
            try:
                if path.is_file():
                    total += path.stat().st_size
            except OSError:
                continue
        return total

    @staticmethod
    def _assert_png(path: Path, scene: dict[str, Any]) -> None:
        if not path.is_file():
            raise ProtocolError("RENDER_PNG_INVALID", str(path))
        header = path.read_bytes()[:24]
        if len(header) < 24 or header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
            raise ProtocolError("RENDER_PNG_INVALID", str(path))
        actual = struct.unpack("!II", header[16:24])
        expected = (scene["viewport"]["width_px"], scene["viewport"]["height_px"])
        if actual != expected:
            raise ProtocolError("RENDER_VIEWPORT_MISMATCH", f"{actual} != {expected}")

    @staticmethod
    def _assert_pdf(path: Path) -> None:
        if not path.is_file() or path.stat().st_size <= 8 or path.read_bytes()[:5] != b"%PDF-":
            raise ProtocolError("RENDER_PDF_INVALID", str(path))

    @staticmethod
    def _artifact(target: str, path: Path, media_type: str, composition: str) -> dict[str, Any]:
        return {
            "target": target,
            "media_type": media_type,
            "size_bytes": path.stat().st_size,
            "composition": composition,
            "artifact_ref": {
                "id": f"render-{target}", "version": "1.0.0",
                "digest": sha256_file(path), "uri": str(path),
            },
        }


class _WebSocketClient:
    def __init__(self, url: str, timeout: float) -> None:
        parsed = urlparse(url)
        if parsed.scheme != "ws" or parsed.hostname not in {"127.0.0.1", "localhost"}:
            raise SecurityError("RENDER_DEBUG_ENDPOINT_INVALID", url)
        self.socket = socket.create_connection((parsed.hostname, parsed.port or 80), timeout=timeout)
        try:
            self.socket.settimeout(timeout)
            self._buffer = bytearray()
            key = base64.b64encode(os.urandom(16)).decode("ascii")
            request = (
                f"GET {parsed.path or '/'}{('?' + parsed.query) if parsed.query else ''} HTTP/1.1\r\n"
                f"Host: {parsed.hostname}:{parsed.port or 80}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
            )
            self.socket.sendall(request.encode("ascii"))
            response = b""
            while b"\r\n\r\n" not in response:
                response += self.socket.recv(4096)
                if len(response) > 65536:
                    raise ProtocolError("RENDER_DEBUG_HANDSHAKE_FAILED", "oversized response")
            header_bytes, remainder = response.split(b"\r\n\r\n", 1)
            if not header_bytes.startswith(b"HTTP/1.1 101"):
                raise ProtocolError("RENDER_DEBUG_HANDSHAKE_FAILED", header_bytes[:256].decode("latin1", "replace"))
            headers: dict[str, str] = {}
            for line in header_bytes.decode("latin1").split("\r\n")[1:]:
                if ":" in line:
                    name, value = line.split(":", 1)
                    headers[name.strip().casefold()] = value.strip()
            expected_accept = base64.b64encode(
                hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")).digest()
            ).decode("ascii")
            if headers.get("sec-websocket-accept") != expected_accept:
                raise ProtocolError("RENDER_DEBUG_HANDSHAKE_FAILED", "invalid Sec-WebSocket-Accept")
            self._buffer.extend(remainder)
        except Exception:
            self.close()
            raise

    def close(self) -> None:
        try:
            self.socket.close()
        except OSError:
            pass

    def send_json(self, value: dict[str, Any]) -> None:
        payload = json.dumps(value, separators=(",", ":")).encode("utf-8")
        mask = os.urandom(4)
        length = len(payload)
        header = bytearray([0x81])
        if length < 126:
            header.append(0x80 | length)
        elif length <= 0xFFFF:
            header.append(0x80 | 126)
            header.extend(struct.pack("!H", length))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack("!Q", length))
        header.extend(mask)
        header.extend(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        self.socket.sendall(header)

    def receive_json(self) -> dict[str, Any]:
        fragments = bytearray()
        message_opcode: int | None = None
        while True:
            first, second = self._read_exact(2)
            final = bool(first & 0x80)
            opcode = first & 0x0F
            length = second & 0x7F
            if length == 126:
                length = struct.unpack("!H", self._read_exact(2))[0]
            elif length == 127:
                length = struct.unpack("!Q", self._read_exact(8))[0]
            masked = bool(second & 0x80)
            mask = self._read_exact(4) if masked else b""
            payload = self._read_exact(length)
            if masked:
                payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
            if opcode == 0x8:
                raise ProtocolError("RENDER_DEBUG_CONNECTION_CLOSED", "browser closed DevTools connection")
            if opcode == 0x9:
                self._send_control(0xA, payload)
                continue
            if opcode == 0xA:
                continue
            if opcode == 0x1:
                if message_opcode is not None:
                    raise ProtocolError("RENDER_DEBUG_FRAME_INVALID", "new message before fragmented message completed")
                message_opcode = opcode
                fragments.extend(payload)
            elif opcode == 0x0:
                if message_opcode is None:
                    raise ProtocolError("RENDER_DEBUG_FRAME_INVALID", "unexpected continuation frame")
                fragments.extend(payload)
            else:
                raise ProtocolError("RENDER_DEBUG_FRAME_INVALID", f"unsupported opcode {opcode}")
            if final:
                if message_opcode != 0x1:
                    raise ProtocolError("RENDER_DEBUG_FRAME_INVALID", "DevTools response is not text")
                try:
                    return json.loads(bytes(fragments).decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise ProtocolError("RENDER_DEBUG_MESSAGE_INVALID", "invalid DevTools JSON") from exc

    def _send_control(self, opcode: int, payload: bytes) -> None:
        mask = os.urandom(4)
        frame = bytearray([0x80 | opcode, 0x80 | len(payload)])
        frame.extend(mask)
        frame.extend(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        self.socket.sendall(frame)

    def _read_exact(self, size: int) -> bytes:
        chunks = bytearray()
        if self._buffer:
            take = min(size, len(self._buffer))
            chunks.extend(self._buffer[:take])
            del self._buffer[:take]
        while len(chunks) < size:
            chunk = self.socket.recv(size - len(chunks))
            if not chunk:
                raise ProtocolError("RENDER_DEBUG_CONNECTION_CLOSED", "unexpected EOF")
            chunks.extend(chunk)
        return bytes(chunks)


class _ChromeCdpSession:
    def __init__(self, renderer: ControlledBrowserRenderer, work_root: Path, scene: dict[str, Any]) -> None:
        self.renderer = renderer
        self.work_root = work_root
        self.scene = scene
        self.started = time.monotonic()
        self.process: subprocess.Popen[bytes] | None = None
        self.job: _WindowsJob | None = None
        self.ws: _WebSocketClient | None = None
        self.next_id = 1
        self.network_violation: str | None = None

    def __enter__(self) -> "_ChromeCdpSession":
        port = self._free_port()
        command = [
            str(self.renderer.browser),
            *_BROWSER_FIXED_FLAGS,
            *(_WINDOWS_BROWSER_FLAGS if os.name == "nt" else ()),
            f"--user-data-dir={self.work_root / 'profile'}", f"--remote-debugging-port={port}",
            "--remote-debugging-address=127.0.0.1", "--remote-allow-origins=http://127.0.0.1",
            "about:blank",
        ]
        try:
            self.job = _WindowsJob(self.renderer.limits)
            self.process = subprocess.Popen(command, cwd=self.work_root, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.job.assign(self.process)
            endpoint = self._wait_for_endpoint(port)
            self.ws = _WebSocketClient(endpoint, self._remaining())
            self.call("Page.enable")
            self.call("Runtime.enable")
            self.call("Network.enable")
            self.call("Network.setBlockedURLs", {"urls": ["http://*", "https://*", "ws://*", "wss://*", "ftp://*"]})
            self.call("Emulation.setDeviceMetricsOverride", {
                "width": self.scene["viewport"]["width_px"],
                "height": self.scene["viewport"]["height_px"],
                "deviceScaleFactor": 1,
                "mobile": False,
            })
            return self
        except Exception:
            self.__exit__(None, None, None)
            raise

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        try:
            if self.ws is not None:
                try:
                    try:
                        self.call("Browser.close")
                    except (OSError, ProtocolError, SecurityError, socket.timeout):
                        pass
                finally:
                    self.ws.close()
                    self.ws = None
        finally:
            if self.process is not None:
                try:
                    self.process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=3)
            if self.job is not None:
                self.job.close()

    @staticmethod
    def _free_port() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            return int(sock.getsockname()[1])

    def _wait_for_endpoint(self, port: int) -> str:
        endpoint = f"http://127.0.0.1:{port}/json/list"
        last_error: Exception | None = None
        while self._remaining() > 0:
            self._check_limits()
            try:
                with urllib.request.urlopen(endpoint, timeout=min(1.0, self._remaining())) as response:
                    targets = json.loads(response.read().decode("utf-8"))
                pages = [item for item in targets if item.get("type") == "page"]
                if pages:
                    return str(pages[0]["webSocketDebuggerUrl"])
            except (OSError, urllib.error.URLError, json.JSONDecodeError, KeyError) as exc:
                last_error = exc
            time.sleep(0.05)
        raise ProtocolError("RENDER_BROWSER_START_TIMEOUT", type(last_error).__name__ if last_error else "timeout")

    def _remaining(self) -> float:
        return max(0.01, self.renderer.limits.timeout_seconds - (time.monotonic() - self.started))

    def _check_limits(self) -> None:
        if time.monotonic() - self.started > self.renderer.limits.timeout_seconds:
            if self.job is not None:
                self.job.close()
            raise ProtocolError("RENDER_TIMEOUT", f"browser exceeded {self.renderer.limits.timeout_seconds:g}s")
        if self.renderer._directory_size(self.work_root) > self.renderer.limits.temporary_disk_bytes:
            if self.job is not None:
                self.job.close()
            raise SecurityError("RENDER_TEMP_DISK_LIMIT", str(self.renderer.limits.temporary_disk_bytes))
        if self.process is not None and self.process.poll() is not None:
            raise ProtocolError("RENDER_BROWSER_FAILED", f"browser exited with {self.process.returncode}")

    def call(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self._check_limits()
        if self.ws is None:
            raise ProtocolError("RENDER_DEBUG_CONNECTION_CLOSED", "session is not connected")
        request_id = self.next_id
        self.next_id += 1
        self.ws.socket.settimeout(self._remaining())
        self.ws.send_json({"id": request_id, "method": method, "params": params or {}})
        while True:
            self._check_limits()
            try:
                message = self.ws.receive_json()
            except socket.timeout as exc:
                raise ProtocolError("RENDER_TIMEOUT", method) from exc
            if message.get("method") == "Network.loadingFailed":
                parameters = message.get("params", {})
                if parameters.get("blockedReason"):
                    self.network_violation = str(parameters.get("errorText") or parameters.get("blockedReason"))
            if message.get("id") != request_id:
                continue
            if "error" in message:
                raise ProtocolError("RENDER_BROWSER_COMMAND_FAILED", f"{method}: {message['error']}")
            return message.get("result", {})

    def navigate(self, url: str) -> None:
        self.network_violation = None
        self.call("Page.navigate", {"url": url})
        self.wait_for_document_ready()

    def evaluate(self, expression: str) -> Any:
        result = self.call("Runtime.evaluate", {"expression": expression, "returnByValue": True})
        return result.get("result", {}).get("value")

    def wait_for_document_ready(self) -> None:
        while self._remaining() > 0:
            if self.evaluate("document.readyState") == "complete":
                if self.network_violation:
                    raise SecurityError("RENDER_NETWORK_ACCESS_DENIED", self.network_violation)
                return
            time.sleep(0.05)
        raise ProtocolError("RENDER_TIMEOUT", "document readiness")

    def wait_for_map_ready(self) -> None:
        while self._remaining() > 0:
            status = self.evaluate("document.documentElement.dataset.cartoStatus")
            if self.network_violation or self.evaluate("document.documentElement.dataset.networkViolation || ''"):
                raise SecurityError("RENDER_NETWORK_ACCESS_DENIED", self.network_violation or "page request")
            if status == "ready":
                version = self.evaluate("document.documentElement.dataset.maplibre")
                if version != MAPLIBRE_VERSION:
                    raise ProtocolError("RENDER_MAPLIBRE_VERSION_MISMATCH", str(version))
                return
            if status in {"error", "timeout"}:
                detail = self.evaluate("document.documentElement.dataset.cartoError || document.documentElement.dataset.networkViolation || ''")
                raise ProtocolError("RENDER_BROWSER_NOT_READY", str(detail))
            time.sleep(0.05)
        raise ProtocolError("RENDER_TIMEOUT", "MapLibre readiness")

    def capture_png(self) -> bytes:
        result = self.call("Page.captureScreenshot", {"format": "png", "fromSurface": True, "captureBeyondViewport": False})
        return base64.b64decode(result["data"], validate=True)

    def print_pdf(self) -> bytes:
        result = self.call("Page.printToPDF", {
            "printBackground": True,
            "preferCSSPageSize": True,
            "displayHeaderFooter": False,
            "paperWidth": 16.5354,
            "paperHeight": 11.6929,
            "marginTop": 0,
            "marginBottom": 0,
            "marginLeft": 0,
            "marginRight": 0,
        })
        return base64.b64decode(result["data"], validate=True)
