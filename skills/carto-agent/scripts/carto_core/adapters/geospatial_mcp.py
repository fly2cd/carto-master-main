"""Project-scoped raster data access through a pinned, operator-configured GIS service.

No symbology, rendering, scenario registration, implicit reprojection, or business approval.
"""
from __future__ import annotations

import asyncio
import hashlib
import math
import os
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable

from ..canonical import canonical_json_bytes, sha256_digest
from ..errors import ProtocolError, SecurityError
from ..repository.immutable_store import ImmutableArtifactStore
from ..schema_registry import SchemaRegistry, load_document
from ..security.paths import PathGuard
from ..workflow.models import ExecutionContext
from .mcp_stdio import connect_stdio
from .tool_gateway import ToolGateway

CAPABILITIES = {"info": "gis-raster-info", "statistics": "gis-raster-statistics",
                "reproject": "gis-raster-reproject"}
TOOLS = {
    "info": {"geo_raster_info"},
    "statistics": {"geo_raster_statistics"},
    "reproject": {"geo_raster_info", "geo_raster_reproject", "geo_get_task_info", "geo_get_artifact_info"},
}
DTYPE_RANGES = {"uint8": (0, 255), "int8": (-128, 127), "uint16": (0, 65535),
                "int16": (-32768, 32767), "uint32": (0, 4294967295),
                "int32": (-2147483648, 2147483647)}
TIFF_SIGNATURES = (b"II\x2a\x00", b"MM\x00\x2a", b"II\x2b\x00", b"MM\x00\x2b")


def _file_identity(path: Path, limit: int) -> tuple[str, int]:
    if not path.is_file() or not 0 < path.stat().st_size <= limit:
        raise ProtocolError("RASTER_INPUT_SIZE_INVALID", "Input must be a bounded regular file")
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            size += len(chunk)
            if size > limit:
                raise ProtocolError("RASTER_INPUT_TOO_LARGE", "Input exceeds the byte limit")
            digest.update(chunk)
    return "sha256:" + digest.hexdigest(), size


def _publish_bytes(guard: PathGuard, path: Path, data: bytes) -> None:
    """Atomic create-only file publication. Existing content is checked, never overwritten."""
    path = guard.resolve(path)
    guard.resolve(path.parent).mkdir(parents=True, exist_ok=True)
    guard.resolve(path)
    if path.exists():
        if path.stat().st_size != len(data) or path.read_bytes() != data:
            raise ProtocolError("IMMUTABLE_ARTIFACT_CONFLICT", "Existing local GIS artifact differs")
        return
    fd, name = tempfile.mkstemp(prefix=".gis-", suffix=".tmp", dir=path.parent)
    temporary = guard.resolve(name, must_exist=True)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        guard.resolve(path)
        try:
            os.link(temporary, path)
        except FileExistsError:
            if path.stat().st_size != len(data) or path.read_bytes() != data:
                raise ProtocolError("IMMUTABLE_ARTIFACT_CONFLICT", "Concurrent local GIS artifact differs") from None
    finally:
        guard.resolve(temporary).unlink(missing_ok=True)


class GeospatialMcpAdapter:
    """A local capability binding; discovery does not itself grant execution authority."""

    def __init__(self, *, config_path: Path, project_root: Path, allowed_roots: list[str],
                 registry: SchemaRegistry | None = None, transport_factory: Callable = connect_stdio) -> None:
        self.registry = registry or SchemaRegistry()
        self.guard = PathGuard(allowed_roots)
        self.project = self.guard.resolve(project_root, must_exist=True)
        if not self.project.is_dir():
            raise SecurityError("MCP_PROJECT_INVALID", "Project root must be a directory")
        self.project_guard = PathGuard([self.project])
        self.config_path = self.guard.resolve(config_path, base_root=self.project, must_exist=True)
        self.config = load_document(self.config_path)
        self.registry.validate("geospatial-mcp-config", self.config)
        self.config_digest = sha256_digest(self.config)
        self.limits = self.config["limits"]
        python = Path(self.config["server_python"])
        if not python.is_absolute():
            raise SecurityError("MCP_PYTHON_NOT_ABSOLUTE", "Service interpreter must be an explicit absolute path")
        self.python = self.guard.resolve(python, must_exist=True)
        if not self.python.is_file():
            raise SecurityError("MCP_PYTHON_INVALID", "Service interpreter must be a regular file")
        self.data_root = self.guard.resolve(self.config["data_root"], base_root=self.project, must_exist=True)
        if not self.data_root.is_dir():
            raise SecurityError("MCP_DATA_ROOT_INVALID", "Data root must be a directory")
        self.catalog_path = self.guard.resolve(self.config["catalog_path"], base_root=self.project, must_exist=True)
        self.catalog = load_document(self.catalog_path)
        self._wire("catalog", self.catalog)
        self.catalog_digest = sha256_digest(self.catalog)
        if set(self.catalog["datasets"]) != set(self.config["allowed_dataset_ids"]):
            raise SecurityError("MCP_CATALOG_SCOPE_DENIED", "Operator catalog must contain exactly the project-authorized datasets")
        for entry in self.catalog["datasets"].values():
            self._catalog_file(entry["path"])
        self.output_root = self.project_guard.resolve(self.project / ".carto/geospatial")
        self.workspace = self.project_guard.resolve(self.output_root / "service")
        if self.workspace.is_relative_to(self.data_root) or self.data_root.is_relative_to(self.workspace):
            raise SecurityError("MCP_ROOTS_OVERLAP", "GIS data and service workspace roots must not overlap")
        self.transport_factory = transport_factory

    def _catalog_file(self, value: str) -> Path:
        path = self.guard.resolve(value, base_root=self.data_root, must_exist=True)
        if not path.is_relative_to(self.data_root) or not path.is_file() or path.suffix.lower() not in {".tif", ".tiff"}:
            raise SecurityError("MCP_DATASET_PATH_DENIED", "Dataset must be a TIFF inside the authorized data root")
        return path

    def make_gateway(self) -> ToolGateway:
        """Create the existing gateway/store, with project-only output guarding."""
        root = self.project_guard.resolve(self.output_root / "evidence")
        store = ImmutableArtifactStore(root, path_guard=self.project_guard)
        gateway = ToolGateway(self.registry.schema_root.parent / "policies/tool-bindings.yaml", store, self.registry)
        self.bind(gateway)
        return gateway

    def bind(self, gateway: ToolGateway) -> None:
        for operation, capability in CAPABILITIES.items():
            gateway.register(capability, self._handler(operation), input_schema="geospatial-request",
                             output_schema="geospatial-result")

    def _handler(self, operation: str):
        def handle(request: dict[str, Any], context: ExecutionContext) -> dict[str, Any]:
            if request["operation"] != operation:
                raise SecurityError("MCP_OPERATION_BINDING_MISMATCH", "Requested operation differs from its authorized capability")
            context.require_project_scope()
            if (context.tenant_id != self.config["tenant_id"] or context.project_id != self.config["project_id"]
                    or context.classification not in {"public", "internal"}
                    or context.environment != "local"):
                raise SecurityError("MCP_PROJECT_SCOPE_DENIED", "GIS configuration is bound to a different project or sensitivity scope")
            request = deepcopy(request)
            self._verify_source(request["source"])
            return asyncio.run(self._execute(request, context))
        return handle

    def _verify_source(self, source: dict[str, Any]) -> Path:
        # Never trust dataset_id alone. Bind the operator catalog to the authorized local bytes.
        self.guard.resolve(self.config_path, must_exist=True)
        self.guard.resolve(self.catalog_path, must_exist=True)
        if (sha256_digest(load_document(self.config_path)) != self.config_digest
                or sha256_digest(load_document(self.catalog_path)) != self.catalog_digest):
            raise ProtocolError("MCP_CONFIGURATION_DRIFT", "Operator configuration or catalog changed")
        if source["dataset_id"] not in self.config["allowed_dataset_ids"]:
            raise SecurityError("MCP_DATASET_SCOPE_DENIED", "Dataset is outside this project's configured subset")
        registered = self._catalog_file(self.catalog["datasets"][source["dataset_id"]]["path"])
        supplied = self.guard.resolve(source["path"], base_root=self.project, must_exist=True)
        if supplied != registered:
            raise SecurityError("MCP_SOURCE_BINDING_MISMATCH", "Dataset ID and authorized local path differ")
        for suffix in (".msk", ".aux.xml", ".ovr"):
            if self.guard.resolve(str(supplied) + suffix).exists():
                raise ProtocolError("RASTER_SIDECAR_UNSUPPORTED", "First batch requires a self-contained TIFF")
        digest, size = _file_identity(supplied, self.limits["max_input_bytes"])
        if digest != source["source_ref"]["digest"] or size != source["size_bytes"]:
            raise ProtocolError("RASTER_SOURCE_CHANGED", "Raster bytes differ from the authorized input snapshot")
        with supplied.open("rb") as stream:
            if stream.read(4) not in TIFF_SIGNATURES:
                raise ProtocolError("RASTER_SIGNATURE_INVALID", "Input does not have a TIFF signature")
        return supplied

    def _wire(self, kind: str, value: dict[str, Any]) -> None:
        try:
            canonical_json_bytes(value)  # Reject NaN/Infinity, even if supplied outside the JSON transport.
            self.registry.validate("geospatial-wire", {"kind": kind, "payload": value})
        except ProtocolError:
            raise ProtocolError("MCP_RESPONSE_INVALID", "GIS response does not match the pinned typed contract") from None

    def _metadata(self, value: dict[str, Any], crs: str | None) -> None:
        self._wire("metadata", value)
        if (value["width"] * value["height"] > self.limits["max_raster_pixels"]
                or value["band_count"] != 1 or len(value["bands"]) != 1
                or value["bands"][0]["band"] != 1 or value["bands"][0]["dtype"] not in DTYPE_RANGES):
            raise ProtocolError("RASTER_PROFILE_UNSUPPORTED", "Expected a bounded single-band 8/16/32-bit integer TIFF")
        if value["crs"] != crs:
            raise ProtocolError("RASTER_CRS_MISMATCH", "Actual raster CRS differs from the explicit input/output contract")
        if crs is not None and value["crs_type"] not in {"geographic", "projected"}:
            raise ProtocolError("RASTER_CRS_UNSUPPORTED", "Only horizontal geographic/projected CRS is admitted")
        x0, y0, x1, y1 = value["bounds"]
        if x1 <= x0 or y1 <= y0:
            raise ProtocolError("RASTER_METADATA_INVALID", "Raster bounds are not ordered")
        nodata = value["bands"][0]["nodata"]
        if nodata is not None and (not isinstance(nodata, (int, float)) or not math.isfinite(nodata)):
            raise ProtocolError("RASTER_METADATA_INVALID", "Integer raster has invalid NoData metadata")

    @staticmethod
    def _crs(source: dict[str, Any]) -> str | None:
        return None if source["crs"] is None else "EPSG:" + source["crs"]["code"]

    def _environment(self, source: dict[str, Any]) -> dict[str, str]:
        path = self._catalog_file(self.catalog["datasets"][source["dataset_id"]]["path"])
        # An immutable single-dataset catalog prevents a live catalog edit from widening the session.
        catalog = {"version": 1, "datasets": {source["dataset_id"]: {
            "kind": "raster", "path": path.relative_to(self.data_root).as_posix()}}}
        digest = sha256_digest(catalog).removeprefix("sha256:")
        snapshot = self.project_guard.resolve(self.output_root / "catalogs" / (digest + ".json"))
        _publish_bytes(self.project_guard, snapshot, canonical_json_bytes(catalog) + b"\n")
        self.project_guard.resolve(self.workspace).mkdir(parents=True, exist_ok=True)
        self.guard.resolve(self.python, must_exist=True)
        return {
            "GEO_DATA_ROOT": str(self.data_root), "GEO_DATA_CATALOG": str(snapshot),
            "GEO_WORKSPACE_ROOT": str(self.workspace), "GEO_LOG_LEVEL": "ERROR",
            "GEO_MAX_INPUT_BYTES": str(self.limits["max_input_bytes"]),
            "GEO_MAX_ARTIFACT_BYTES": str(self.limits["max_artifact_bytes"]),
            "GEO_MAX_RASTER_PIXELS": str(self.limits["max_raster_pixels"]),
            "GEO_MAX_RASTER_CLASSES": str(self.limits["max_raster_classes"]),
        }

    async def _execute(self, request: dict[str, Any], context: ExecutionContext) -> dict[str, Any]:
        source, operation = request["source"], request["operation"]
        environment = self._environment(source)
        async with self.transport_factory(python=str(self.python), cwd=str(self.workspace), env=environment,
                                          context=context, limits=self.limits) as session:
            if (session.server_info.name != "Geospatial Tools"
                    or session.server_info.version != self.config["server_version"]):
                raise ProtocolError("MCP_SERVER_VERSION_MISMATCH", "Unexpected GIS server identity/version")
            tool_digest = await session.discover(TOOLS[operation])
            output: dict[str, Any] = {
                "schema_version": 1, "operation": operation, "source_ref": source["source_ref"],
                "dataset_id": source["dataset_id"], "source_size_bytes": source["size_bytes"],
                "server": {"id": self.config["server_id"], "version": self.config["server_version"],
                           "config_digest": self.config_digest, "catalog_digest": self.catalog_digest,
                           "tool_catalog_digest": tool_digest}, "warnings": [],
            }
            if operation == "info":
                metadata = await session.call("geo_raster_info", {"dataset_id": source["dataset_id"]})
                self._metadata(metadata, self._crs(source))
                output.update(raster_info=metadata, warnings=metadata["warnings"])
            elif operation == "statistics":
                stats = await session.call("geo_raster_statistics", {"source": {"dataset_id": source["dataset_id"]}})
                self._wire("statistics", stats)
                self._metadata(stats["raster_info"], self._crs(source))
                self._statistics(stats, source)
                output.update(raster_info=stats["raster_info"], warnings=stats["warnings"],
                              statistics={key: stats[key] for key in ("total_pixels", "valid_pixels", "masked_pixels", "classes")})
            else:
                await self._reproject(session, request, output)
            self._verify_source(source)
            self.registry.validate("geospatial-result", output)
        return output

    def _statistics(self, stats: dict[str, Any], source: dict[str, Any]) -> None:
        if (stats["source"]["dataset_id"] != source["dataset_id"] or stats["sha256"] != source["source_ref"]["digest"][7:]
                or stats["size_bytes"] != source["size_bytes"]):
            raise ProtocolError("MCP_INPUT_IDENTITY_MISMATCH", "Statistics are for a different input snapshot")
        classes = stats["classes"]
        values = [item["value"] for item in classes]
        low, high = DTYPE_RANGES[stats["raster_info"]["bands"][0]["dtype"]]
        if (stats["total_pixels"] != stats["raster_info"]["width"] * stats["raster_info"]["height"]
                or stats["total_pixels"] != stats["valid_pixels"] + stats["masked_pixels"]
                or sum(item["count"] for item in classes) != stats["valid_pixels"]
                or len(classes) > self.limits["max_raster_classes"] or values != sorted(set(values))
                or any(not low <= value <= high for value in values)):
            raise ProtocolError("MCP_STATISTICS_INCONSISTENT", "Class counts/domain do not match raster totals")

    async def _reproject(self, session: Any, request: dict[str, Any], output: dict[str, Any]) -> None:
        source, params = request["source"], request["parameters"]
        metadata = await session.call("geo_raster_info", {"dataset_id": source["dataset_id"]})
        self._metadata(metadata, self._crs(source))
        a, b, _, d, e, _ = metadata["transform"]
        if source["crs"] is None or b != 0 or d != 0 or a <= 0 or e >= 0:
            raise ProtocolError("RASTER_REPROJECT_GRID_UNSUPPORTED", "Reprojection requires known CRS and a north-up affine grid")
        # Recheck immediately before mutation; session metadata is not a substitute for input binding.
        self._verify_source(source)
        arguments = {"source": {"dataset_id": source["dataset_id"]}, **params}
        result = await session.call("geo_raster_reproject", arguments)
        self._wire("task-result", result)
        task = await session.call("geo_get_task_info", {"task_id": result["task_id"]})
        self._wire("task-info", task)
        task_source = task["inputs"][0]
        if (task["task_id"] != result["task_id"] or task["parameters"] != arguments
                or task["artifacts"] != result["artifacts"] or task["summary"] != result["summary"]
                or task["warnings"] != result["warnings"]
                or task_source["source"]["dataset_id"] != source["dataset_id"]
                or task_source["sha256"] != source["source_ref"]["digest"][7:]
                or task_source["size_bytes"] != source["size_bytes"]):
            raise ProtocolError("MCP_TASK_BINDING_MISMATCH", "Task provenance does not match this exact request and source")
        artifact = result["artifacts"][0]
        info = await session.call("geo_get_artifact_info", {"artifact_id": artifact["artifact_id"]})
        self._wire("artifact-info", info)
        if (info != artifact or info["task_id"] != result["task_id"]
                or info["uri"] != "artifact://" + info["artifact_id"]
                or info["size_bytes"] > self.limits["max_artifact_bytes"]):
            raise ProtocolError("MCP_ARTIFACT_BINDING_MISMATCH", "Artifact is not the expected bounded task output")
        raster = info["raster_info"]
        self._metadata(raster, params["target_crs"])
        summary = result["summary"]
        if (info["crs"] != raster["crs"] or raster["bands"][0]["dtype"] != metadata["bands"][0]["dtype"]
                or any(summary[key] != raster[key] for key in ("crs", "width", "height"))
                or summary["resolution"] != raster["pixel_size"]
                or (params["resolution"] is not None and any(
                    not math.isclose(value, params["resolution"], rel_tol=1e-10) for value in raster["pixel_size"]))):
            raise ProtocolError("MCP_RASTER_OUTPUT_MISMATCH", "Reprojected metadata differs from the requested grid/profile")
        content = await session.read(info["uri"], info["size_bytes"])
        digest = "sha256:" + hashlib.sha256(content).hexdigest()
        if (len(content) != info["size_bytes"] or digest[7:] != info["sha256"]
                or content[:4] not in TIFF_SIGNATURES):
            raise ProtocolError("MCP_ARTIFACT_INTEGRITY_FAILED", "TIFF signature, byte count, or SHA256 differs")
        self._verify_source(source)
        target = self.project_guard.resolve(self.output_root / "artifacts" / (info["sha256"] + ".tif"))
        task_digest = sha256_digest(task)
        task_path = self.project_guard.resolve(self.output_root / "tasks" / (task_digest[7:] + ".json"))
        output.update(raster_info=raster, warnings=result["warnings"], artifact={
            "artifact_ref": {"id": info["artifact_id"].replace("_", "-"), "version": "1.0.0",
                             "digest": digest, "uri": target.as_posix()},
            "remote_artifact_id": info["artifact_id"], "remote_task_id": info["task_id"],
            "mime_type": "image/tiff", "size_bytes": info["size_bytes"], "task_digest": task_digest,
            "task_ref": {"id": info["task_id"].replace("_", "-"), "version": "1.0.0",
                         "digest": task_digest, "uri": task_path.as_posix()},
        })
        self.registry.validate("geospatial-result", output)
        _publish_bytes(self.project_guard, target, content)
        _publish_bytes(self.project_guard, task_path, canonical_json_bytes(task) + b"\n")
