from __future__ import annotations

import asyncio
import base64
from contextlib import asynccontextmanager, redirect_stderr, redirect_stdout
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

SCRIPTS_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from carto_core.adapters.geospatial_mcp import CAPABILITIES, GeospatialMcpAdapter, TOOLS
from carto_core.adapters.mcp_stdio import StdioSession, _LocalSchemaValidation, connect_stdio
from carto_core.canonical import sha256_digest
from carto_core.cli import main
from carto_core.errors import CartoError, ProtocolError
from carto_core.scenario_registry import ScenarioRegistry
from carto_core.schema_registry import SchemaRegistry
from carto_core.workflow.models import ExecutionContext
from tests.fixtures.schema_cases import VALID_CASES


class FakeSession:
    def __init__(self, source, metadata):
        self.server_info = SimpleNamespace(name="Geospatial Tools", version="0.3.0")
        self.calls = []
        self.available = set.union(*TOOLS.values())
        self.on_call = None
        self.on_read = None
        self.content = b"II\x2a\x00" + b"controlled-output-fixture"
        output = deepcopy(metadata)
        output.update(crs="EPSG:4326", crs_type="geographic", coordinate_units=["degree", "degree"],
                      bounds=[10, 20, 10.003, 20.002], transform=[0.001, 0, 10, 0, -0.001, 20.002],
                      pixel_size=[0.001, 0.001], pixel_size_meters=None)
        artifact = {"artifact_id": "art_" + "a" * 32, "task_id": "task_" + "b" * 32,
                    "kind": "raster", "format": "tif", "mime_type": "image/tiff", "uri": "artifact://art_" + "a" * 32,
                    "size_bytes": len(self.content), "sha256": hashlib.sha256(self.content).hexdigest(),
                    "crs": output["crs"], "layer": None, "feature_count": None, "raster_info": output}
        summary = {"crs": output["crs"], "width": 3, "height": 2, "resampling": "nearest", "resolution": [0.001, 0.001]}
        task_result = {"task_id": artifact["task_id"], "artifacts": [deepcopy(artifact)], "summary": summary, "warnings": []}
        task = {**deepcopy(task_result), "tool": "geo_raster_reproject", "version": "0.3.0", "status": "succeeded",
                "started_at": "2026-11-05T00:00:00Z", "finished_at": "2026-11-05T00:00:01Z",
                "parameters": {"source": {"dataset_id": source["dataset_id"]}, "target_crs": "EPSG:4326", "resolution": None, "resampling": "nearest"},
                "inputs": [{"source": {"dataset_id": source["dataset_id"], "artifact_id": None, "layer": None},
                            "sha256": source["source_ref"]["digest"][7:], "size_bytes": source["size_bytes"]}], "error_code": None}
        self.responses = {
            "geo_raster_info": deepcopy(metadata),
            "geo_raster_statistics": {"source": {"dataset_id": source["dataset_id"], "artifact_id": None},
                                      "sha256": source["source_ref"]["digest"][7:], "size_bytes": source["size_bytes"],
                                      "raster_info": deepcopy(metadata), "total_pixels": 6, "valid_pixels": 6, "masked_pixels": 0,
                                      "classes": [{"value": 0, "count": 2}, {"value": 1, "count": 2}, {"value": 255, "count": 2}], "warnings": []},
            "geo_raster_reproject": task_result, "geo_get_task_info": task, "geo_get_artifact_info": artifact,
        }

    async def discover(self, required):
        if not required <= self.available:
            raise ProtocolError("MCP_CAPABILITY_NOT_AVAILABLE", "Missing tools")
        return sha256_digest(sorted(required))

    async def call(self, name, arguments):
        self.calls.append((name, deepcopy(arguments)))
        if self.on_call:
            self.on_call(name, arguments)
        return deepcopy(self.responses[name])

    async def read(self, uri, size):
        self.calls.append(("resources/read", {"uri": uri}))
        if self.on_read:
            self.on_read()
        return self.content


class GeospatialAdapterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.project = self.root / "project"
        self.data = self.root / "data"
        self.project.mkdir(); self.data.mkdir()
        self.input = self.data / "classified.tif"
        # This fixture tests transport/integrity contracts, not a TIFF decoder. Real TIFFs are tested separately.
        self.input.write_bytes(b"II\x2a\x00" + b"controlled-input-fixture")
        self.python = self.root / "operator-python"
        self.python.write_bytes(b"not executed by the unit-test transport")
        self.catalog = self.project / "datasets.json"
        self.catalog.write_text(json.dumps({"version": 1, "datasets": {"classified": {"kind": "raster", "path": "classified.tif"}}}), encoding="utf-8")
        self.config = deepcopy(VALID_CASES["geospatial-mcp-config"])
        self.config.update(server_python=str(self.python), data_root=str(self.data), catalog_path=str(self.catalog))
        self.config_path = self.project / "mcp.json"
        self.save_config()
        self.source = deepcopy(VALID_CASES["raster-input"])
        self.source.update(path=str(self.input), size_bytes=self.input.stat().st_size)
        self.source["source_ref"]["digest"] = "sha256:" + hashlib.sha256(self.input.read_bytes()).hexdigest()
        self.metadata = deepcopy(VALID_CASES["geospatial-wire"]["payload"])
        self.session = FakeSession(self.source, self.metadata)
        self.environments = []
        self.schemas = SchemaRegistry()

    def save_config(self):
        self.config_path.write_text(json.dumps(self.config), encoding="utf-8")

    @asynccontextmanager
    async def transport(self, **kwargs):
        self.environments.append(kwargs["env"])
        yield self.session

    def adapter(self):
        return GeospatialMcpAdapter(config_path=self.config_path, project_root=self.project,
                                     allowed_roots=[str(self.root)], transport_factory=self.transport)

    def context(self, operation="statistics"):
        return ExecutionContext("test-run", "test-tenant", "test-project", "test-subject",
                                frozenset({"operator"}), frozenset({"test-project"}),
                                frozenset({CAPABILITIES[operation]}))

    def request(self, operation="statistics"):
        result = {"schema_version": 1, "operation": operation, "source": deepcopy(self.source)}
        if operation == "reproject":
            result["parameters"] = {"target_crs": "EPSG:4326", "resolution": None, "resampling": "nearest"}
        return result

    def invoke(self, operation="statistics", request=None, context=None, adapter=None):
        adapter = adapter or self.adapter()
        receipt = adapter.make_gateway().invoke(CAPABILITIES[operation], request or self.request(operation),
                                               context or self.context(operation))
        output = json.loads(Path(receipt.artifact_refs[0]["uri"]).read_text(encoding="utf-8"))
        self.assertEqual(receipt.output_digest, sha256_digest(output))
        return receipt, output

    def assert_code(self, code, action):
        with self.assertRaises(CartoError) as raised:
            action()
        self.assertEqual(code, raised.exception.code)

    def assert_no_result(self):
        self.assertEqual([], list((self.project / ".carto/geospatial/evidence").rglob("*.json")))
        self.assertEqual([], list((self.project / ".carto/geospatial/artifacts").glob("*.tif")))

    def test_information_is_a_gateway_receipt_not_a_map(self):
        receipt, result = self.invoke("info")
        self.assertEqual("gis-raster-info", receipt.capability_id)
        self.assertEqual(self.source["source_ref"], result["source_ref"])
        self.assertEqual("EPSG:26911", result["raster_info"]["crs"])
        self.assertNotIn("statistics", result)
        self.assertNotIn("artifact", result)
        self.assertEqual([("geo_raster_info", {"dataset_id": "classified"})], self.session.calls)

    def test_statistics_preserve_zero_255_and_exact_totals(self):
        receipt, result = self.invoke()
        self.assertEqual([0, 1, 255], [c["value"] for c in result["statistics"]["classes"]])
        self.assertEqual(6, result["statistics"]["valid_pixels"])
        self.assertEqual(sha256_digest(self.request()), receipt.input_digest)
        self.assertEqual(self.adapter().config_digest, result["server"]["config_digest"])

    def test_all_masked_and_missing_crs_information_are_supported(self):
        self.source["crs"] = None
        stats = self.session.responses["geo_raster_statistics"]
        stats.update(valid_pixels=0, masked_pixels=6, classes=[])
        stats["raster_info"].update(crs=None, crs_type="undefined")
        _, result = self.invoke()
        self.assertEqual([], result["statistics"]["classes"])

    def test_gateway_scope_and_budget_fail_before_remote_calls(self):
        for change, code in [("capability", "CAPABILITY_SCOPE_DENIED"), ("namespace", "PROJECT_SCOPE_DENIED"),
                             ("tenant", "MCP_PROJECT_SCOPE_DENIED"), ("project", "MCP_PROJECT_SCOPE_DENIED"),
                             ("classification", "MCP_PROJECT_SCOPE_DENIED"), ("budget", "EXECUTION_BUDGET_EXCEEDED")]:
            with self.subTest(change=change):
                ctx = self.context()
                if change == "capability": ctx.authorized_capabilities = frozenset()
                if change == "namespace": ctx.namespaces = frozenset()
                if change == "tenant": ctx.tenant_id = "another-tenant"
                if change == "project": ctx.project_id = "another-project"; ctx.namespaces = frozenset({"another-project"})
                if change == "classification": ctx.classification = "restricted"
                if change == "budget": ctx.budget.max_tool_calls = 0
                self.assert_code(code, lambda: self.invoke(context=ctx))
        self.assertEqual([], self.session.calls)

    def test_operation_cannot_escalate_an_info_capability(self):
        self.assert_code("MCP_OPERATION_BINDING_MISMATCH", lambda: self.invoke("info", request=self.request("reproject")))
        self.assertEqual([], self.session.calls)

    def test_version_and_discovery_must_match(self):
        self.session.server_info.version = "0.4.0"
        self.assert_code("MCP_SERVER_VERSION_MISMATCH", self.invoke)
        self.session.server_info.version = "0.3.0"
        self.session.available.clear()
        self.assert_code("MCP_CAPABILITY_NOT_AVAILABLE", self.invoke)
        self.assertEqual([], self.session.calls)

    def test_source_digest_size_path_and_dataset_are_bound(self):
        cases = [("digest", "RASTER_SOURCE_CHANGED"), ("size", "RASTER_SOURCE_CHANGED"),
                 ("path", "MCP_SOURCE_BINDING_MISMATCH"), ("dataset", "MCP_DATASET_SCOPE_DENIED")]
        other = self.data / "other.tif"; other.write_bytes(self.input.read_bytes())
        for kind, code in cases:
            with self.subTest(kind=kind):
                request = self.request()
                if kind == "digest": request["source"]["source_ref"]["digest"] = "sha256:" + "f" * 64
                if kind == "size": request["source"]["size_bytes"] += 1
                if kind == "path": request["source"]["path"] = str(other)
                if kind == "dataset": request["source"]["dataset_id"] = "not-authorized"
                self.assert_code(code, lambda: self.invoke(request=request))
        self.assertEqual([], self.session.calls)

    def test_source_changes_during_remote_call_prevent_acceptance(self):
        self.session.on_call = lambda *args: self.input.write_bytes(b"II\x2a\x00changed")
        self.assert_code("RASTER_SOURCE_CHANGED", self.invoke)
        self.assert_no_result()

    def test_catalog_changes_during_remote_call_prevent_acceptance(self):
        self.session.on_call = lambda *args: self.catalog.write_text('{"version":1,"datasets":{}}', encoding="utf-8")
        self.assert_code("MCP_CONFIGURATION_DRIFT", self.invoke)
        self.assert_no_result()

    def test_config_changes_after_loading_prevent_start(self):
        adapter = self.adapter()
        self.config["limits"]["max_raster_pixels"] -= 1; self.save_config()
        self.assert_code("MCP_CONFIGURATION_DRIFT", lambda: self.invoke(adapter=adapter))
        self.assertEqual([], self.session.calls)

    def test_service_receives_only_single_dataset_snapshot_and_no_credentials(self):
        with patch.dict("os.environ", {"OPENAI_API_KEY": "must-not-forward", "GEO_DATA_ROOT": "must-not-use"}):
            self.invoke()
        env = self.environments[0]
        self.assertNotIn("OPENAI_API_KEY", env)
        self.assertEqual(str(self.data), env["GEO_DATA_ROOT"])
        snapshot = json.loads(Path(env["GEO_DATA_CATALOG"]).read_text(encoding="utf-8"))
        self.assertEqual({"classified"}, set(snapshot["datasets"]))
        self.assertNotEqual(self.catalog, Path(env["GEO_DATA_CATALOG"]))
        self.assertTrue(Path(env["GEO_WORKSPACE_ROOT"]).is_relative_to(self.project))

    def test_catalog_cannot_include_unapproved_dataset_or_escape_data_root(self):
        value = json.loads(self.catalog.read_text(encoding="utf-8"))
        value["datasets"]["another"] = value["datasets"]["classified"]
        self.catalog.write_text(json.dumps(value), encoding="utf-8")
        self.assert_code("MCP_CATALOG_SCOPE_DENIED", self.adapter)
        value["datasets"].pop("another")
        value["datasets"]["classified"]["path"] = str(self.python)
        self.catalog.write_text(json.dumps(value), encoding="utf-8")
        self.assert_code("MCP_DATASET_PATH_DENIED", self.adapter)

    def test_input_sidecar_and_excess_bytes_are_rejected(self):
        sidecar = Path(str(self.input) + ".msk"); sidecar.write_bytes(b"mask")
        self.assert_code("RASTER_SIDECAR_UNSUPPORTED", self.invoke)
        sidecar.unlink()
        self.config["limits"]["max_input_bytes"] = 1; self.save_config()
        self.assert_code("RASTER_INPUT_SIZE_INVALID", self.invoke)
        self.assertEqual([], self.session.calls)

    def test_local_symlink_is_not_followed(self):
        other = self.data / "real.tif"
        self.input.rename(other)
        try:
            self.input.symlink_to(other)
        except OSError:
            self.skipTest("OS does not permit symlink creation")
        self.assert_code("PATH_LINK_ESCAPE", self.adapter)

    def test_statistics_reject_unknown_nonfinite_identity_totals_and_domain(self):
        original = deepcopy(self.session.responses["geo_raster_statistics"])
        mutations = [lambda s: s.update(unexpected=True), lambda s: s["raster_info"]["bounds"].__setitem__(0, float("nan")),
                     lambda s: s.update(sha256="f" * 64), lambda s: s.update(valid_pixels=5),
                     lambda s: s["classes"][0].update(value=256), lambda s: s["classes"][1].update(value=0),
                     lambda s: s["classes"].reverse(), lambda s: s["raster_info"]["bands"][0].update(dtype="float32"),
                     lambda s: s["raster_info"].update(crs="EPSG:4326")]
        for index, mutate in enumerate(mutations):
            with self.subTest(case=index):
                changed = deepcopy(original); mutate(changed)
                self.session.responses["geo_raster_statistics"] = changed
                with self.assertRaises(CartoError): self.invoke()
                self.assert_no_result()

    def test_statistics_obey_pixel_and_class_limits(self):
        for key, limit in [("max_raster_pixels", 5), ("max_raster_classes", 2)]:
            with self.subTest(key=key):
                self.config["limits"][key] = limit; self.save_config()
                with self.assertRaises(CartoError): self.invoke()
                self.assert_no_result()
                self.config["limits"][key] = VALID_CASES["geospatial-mcp-config"]["limits"][key]

    def test_reprojection_downloads_only_verified_tiff_and_saves_task_evidence(self):
        receipt, result = self.invoke("reproject")
        art = result["artifact"]
        path = Path(art["artifact_ref"]["uri"])
        self.assertTrue(path.is_relative_to(self.project))
        self.assertEqual(self.session.content, path.read_bytes())
        self.assertEqual("image/tiff", art["mime_type"])
        self.assertEqual("sha256:" + hashlib.sha256(path.read_bytes()).hexdigest(), art["artifact_ref"]["digest"])
        task = json.loads(Path(art["task_ref"]["uri"]).read_text(encoding="utf-8"))
        self.assertEqual(art["task_digest"], sha256_digest(task))
        self.assertEqual("gis-raster-reproject", receipt.capability_id)
        self.assertEqual(1, sum(name == "geo_raster_reproject" for name, _ in self.session.calls))
        self.assertEqual("resources/read", self.session.calls[-1][0])

    def test_task_and_artifact_tampering_prevent_download(self):
        originals = deepcopy(self.session.responses)
        cases = [("geo_get_task_info", lambda x: x["inputs"][0].update(sha256="c" * 64)),
                 ("geo_get_task_info", lambda x: x["parameters"].update(target_crs="EPSG:3857")),
                 ("geo_get_task_info", lambda x: x.update(status="failed")),
                 ("geo_get_artifact_info", lambda x: x.update(uri="file:///etc/passwd")),
                 ("geo_get_artifact_info", lambda x: x.update(mime_type="image/png")),
                 ("geo_get_artifact_info", lambda x: x.update(size_bytes=999)),
                 ("geo_raster_reproject", lambda x: x["artifacts"].append(deepcopy(x["artifacts"][0])))]
        for name, mutate in cases:
            with self.subTest(name=name):
                self.session.responses = deepcopy(originals); self.session.calls.clear()
                mutate(self.session.responses[name])
                with self.assertRaises(CartoError): self.invoke("reproject")
                self.assertFalse(any(name == "resources/read" for name, _ in self.session.calls))
                self.assert_no_result()

    def test_download_checksum_or_late_source_change_is_not_published(self):
        self.session.content = b"II\x2a\x00tampered"
        self.assert_code("MCP_ARTIFACT_INTEGRITY_FAILED", lambda: self.invoke("reproject"))
        self.assert_no_result()
        self.session = FakeSession(self.source, self.metadata)
        self.session.on_read = lambda: self.input.write_bytes(b"II\x2a\x00changed")
        self.assert_code("RASTER_SOURCE_CHANGED", lambda: self.invoke("reproject"))
        self.assert_no_result()

    def test_existing_received_artifact_is_never_overwritten(self):
        _, result = self.invoke("reproject")
        target = Path(result["artifact"]["artifact_ref"]["uri"])
        target.write_bytes(b"do not overwrite")
        self.assert_code("IMMUTABLE_ARTIFACT_CONFLICT", lambda: self.invoke("reproject"))
        self.assertEqual(b"do not overwrite", target.read_bytes())

    def test_reprojection_requires_north_up_and_crs_before_mutation(self):
        self.session.responses["geo_raster_info"]["transform"][1] = 2
        self.assert_code("RASTER_REPROJECT_GRID_UNSUPPORTED", lambda: self.invoke("reproject"))
        self.assertFalse(any(name == "geo_raster_reproject" for name, _ in self.session.calls))

    def test_cli_refuses_mutation_before_constructing_adapter(self):
        path = self.project / "request.json"; path.write_text(json.dumps(self.request("reproject")), encoding="utf-8")
        with redirect_stderr(io.StringIO()) as err, patch("carto_core.adapters.geospatial_mcp.GeospatialMcpAdapter") as adapter:
            code = main(["data", "inspect-raster", str(path), "--mcp-config", str(self.config_path),
                         "--project-root", str(self.project), "--allowed-root", str(self.root), "--run-id", "test-run",
                         "--tenant-id", "test-tenant", "--project-id", "test-project", "--subject-id", "test-subject"])
        self.assertEqual(2, code)
        self.assertEqual("MCP_MUTATION_REQUIRES_WORKFLOW", json.loads(err.getvalue())["code"])
        adapter.assert_not_called()

    def test_raster_schema_evolution_does_not_enable_a_map_scene(self):
        request = deepcopy(VALID_CASES["generate-request"])
        request["source_bindings"] = [self.source]
        self.schemas.validate("generate-request", request)
        self.assert_code("CAPABILITY_NOT_AVAILABLE", lambda: ScenarioRegistry(self.schemas).for_generate(request))
        request["source_bindings"][0]["geometry_types"] = ["polygon"]
        self.assert_code("SCHEMA_VALIDATION_FAILED", lambda: self.schemas.validate("generate-request", request))

    def test_unrecognized_contract_options_are_rejected(self):
        for field, value in [("band", 2), ("mask_policy", "zero-is-nodata"), ("value_semantics", "continuous"),
                             ("contains_sensitive_coordinates", True), ("dataset_id", "../escape")]:
            request = self.request(); request["source"][field] = value
            with self.subTest(field=field), self.assertRaises(CartoError): self.invoke(request=request)
        for resampling in ("bilinear", "unknown"):
            request = self.request("reproject"); request["parameters"]["resampling"] = resampling
            with self.assertRaises(CartoError): self.invoke("reproject", request=request)
        for resolution in (-1, 0, float("nan"), float("inf")):
            request = self.request("reproject"); request["parameters"]["resolution"] = resolution
            with self.assertRaises(CartoError): self.invoke("reproject", request=request)
        self.assertEqual([], self.session.calls)


    def test_oversized_artifact_is_rejected_before_download(self):
        self.config["limits"]["max_artifact_bytes"] = 8
        self.save_config()
        self.assert_code("MCP_ARTIFACT_BINDING_MISMATCH", lambda: self.invoke("reproject"))
        self.assertFalse(any(name == "resources/read" for name, _ in self.session.calls))
        self.assert_no_result()

    def test_unknown_mutation_outcome_is_not_retried(self):
        def fail_after_mutation(name, arguments):
            if name == "geo_get_task_info":
                raise ProtocolError("MCP_TRANSPORT_FAILED", "Unknown outcome")
        self.session.on_call = fail_after_mutation
        self.assert_code("MCP_TRANSPORT_FAILED", lambda: self.invoke("reproject"))
        self.assertEqual(1, sum(name == "geo_raster_reproject" for name, _ in self.session.calls))
        self.assert_no_result()

    def test_session_close_failure_has_no_success_evidence_even_with_local_artifact(self):
        @asynccontextmanager
        async def close_failure(**kwargs):
            yield self.session
            raise ProtocolError("MCP_TRANSPORT_FAILED", "Unknown session outcome")
        adapter = self.adapter()
        adapter.transport_factory = close_failure
        self.assert_code("MCP_TRANSPORT_FAILED", lambda: self.invoke("reproject", adapter=adapter))
        self.assertEqual([], list((self.project / ".carto/geospatial/evidence").rglob("*.json")))
        self.assertEqual(1, len(list((self.project / ".carto/geospatial/artifacts").glob("*.tif"))))
        self.assertEqual(1, sum(name == "geo_raster_reproject" for name, _ in self.session.calls))

    def test_project_output_link_is_rejected_before_transport(self):
        output = self.project / ".carto"
        output.mkdir()
        # Deterministic link/junction boundary test, even on Windows without symlink privileges.
        with patch("carto_core.security.paths._is_link_or_junction", side_effect=lambda path: path == output):
            self.assert_code("PATH_LINK_ESCAPE", self.adapter)
        self.assertEqual([], self.environments)

    def test_guarded_evidence_store_refuses_outside_paths(self):
        from carto_core.repository.immutable_store import ImmutableArtifactStore, StoredArtifact
        adapter = self.adapter()
        store = ImmutableArtifactStore(self.project / "evidence", path_guard=adapter.project_guard)
        self.assert_code("PATH_OUTSIDE_ALLOWED_ROOT", lambda: store.put("../../escape", "1.0.0", {}))
        artifact = StoredArtifact("outside", "1.0.0", sha256_digest({}), self.data / "outside.json")
        self.assert_code("PATH_OUTSIDE_ALLOWED_ROOT", lambda: store.get(artifact))
        self.assertFalse((self.root / "escape").exists())


class StdioContractTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.context = ExecutionContext("run", "tenant", "project", "subject", frozenset(), frozenset({"project"}), frozenset())
        self.sdk = SimpleNamespace(call_tool=AsyncMock(), read_resource=AsyncMock(), list_tools=AsyncMock())
        self.session = StdioSession(self.sdk, SimpleNamespace(), self.context, deepcopy(VALID_CASES["geospatial-mcp-config"]["limits"]))

    async def test_text_only_and_tool_errors_are_not_parsed_as_success(self):
        for error, structured in [(False, None), (True, {"secret": "not-forwarded"})]:
            self.sdk.call_tool.return_value = SimpleNamespace(is_error=error, structured_content=structured,
                                                              model_dump=lambda **kwargs: {"isError": error})
            with self.assertRaises(ProtocolError) as raised:
                await self.session.call("geo_raster_info", {"dataset_id": "classified"})
            self.assertNotIn("secret", str(raised.exception))

    async def test_typed_result_and_response_budget(self):
        value = {"kind": "raster"}
        self.sdk.call_tool.return_value = SimpleNamespace(is_error=False, structured_content=value, model_dump=lambda **kwargs: value)
        self.assertEqual(value, await self.session.call("geo_raster_info", {}))
        self.session.limits["max_response_bytes"] = 1
        with self.assertRaises(ProtocolError): await self.session.call("geo_raster_info", {})
        self.assertEqual(2, self.context.budget.tool_calls)

    async def test_binary_resource_uri_mime_base64_and_size(self):
        uri = "artifact://art_" + "a" * 32
        data = b"II\x2a\x00sample"
        def part(**changes):
            fields = {"uri": uri, "mime_type": "image/tiff", "blob": base64.b64encode(data).decode("ascii")}
            fields.update(changes)
            self.sdk.read_resource.return_value = SimpleNamespace(contents=[SimpleNamespace(**fields)])
        part(); self.assertEqual(data, await self.session.read(uri, len(data)))
        for changes in ({"uri": "https://untrusted.invalid/file.tif"}, {"mime_type": "image/png"},
                        {"blob": "!" * 16}, {"blob": ""}):
            part(**changes)
            with self.assertRaises(ProtocolError): await self.session.read(uri, len(data))
        self.sdk.read_resource.return_value = SimpleNamespace(contents=[])
        with self.assertRaises(ProtocolError): await self.session.read(uri, len(data))

    async def test_discovery_ignores_rendering_and_rejects_missing_or_duplicates(self):
        tools = [SimpleNamespace(name=name, input_schema={}, output_schema={}) for name in ("geo_raster_info", "geo_render_vector_map")]
        response = SimpleNamespace(tools=tools, next_cursor=None, model_dump=lambda **kwargs: {"tools": [x.name for x in tools]})
        self.sdk.list_tools.return_value = response
        digest = await self.session.discover({"geo_raster_info"})
        self.assertEqual(sha256_digest([{"name": "geo_raster_info", "input": {}, "output": {}}]), digest)
        with self.assertRaises(ProtocolError): await self.session.discover({"not-installed"})
        tools.append(tools[0])
        with self.assertRaises(ProtocolError): await self.session.discover({"geo_raster_info"})


    async def test_binary_limit_is_checked_before_resource_request(self):
        for size in (0, -1, True, self.session.limits["max_artifact_bytes"] + 1):
            with self.subTest(size=size), self.assertRaises(ProtocolError):
                await self.session.read("artifact://art_" + "a" * 32, size)
        self.sdk.read_resource.assert_not_called()

    async def test_local_schema_hook_requires_typed_output_without_remote_validation(self):
        class RemoteValidation:
            async def validate_tool_result(self, name, result):
                raise AssertionError("Remote JSON Schema must not execute")
        class LocalSession(_LocalSchemaValidation, RemoteValidation):
            pass
        session = LocalSession()
        await session.validate_tool_result("geo_raster_info", SimpleNamespace(structured_content={}))
        with self.assertRaises(ProtocolError):
            await session.validate_tool_result("geo_raster_info", SimpleNamespace(structured_content=None))

    async def test_v2_discovery_pagination_and_repeated_cursor(self):
        try:
            from mcp.types import ListToolsResult, PaginatedRequestParams, Tool
        except ImportError:
            self.skipTest("Optional MCP SDK required")
        tool = Tool(name="geo_raster_info", input_schema={})
        self.sdk.list_tools.side_effect = [ListToolsResult(tools=[], next_cursor="next"), ListToolsResult(tools=[tool])]
        await self.session.discover({"geo_raster_info"})
        params = self.sdk.list_tools.call_args.kwargs["params"]
        self.assertIsInstance(params, PaginatedRequestParams)
        self.assertEqual("next", params.cursor)
        self.sdk.list_tools.side_effect = [ListToolsResult(tools=[], next_cursor="repeat")] * 2
        with self.assertRaises(ProtocolError) as raised:
            await self.session.discover({"geo_raster_info"})
        self.assertEqual("MCP_DISCOVERY_INVALID", raised.exception.code)

    async def test_transport_timeout_and_raw_errors_are_sanitized_without_retry(self):
        try:
            import mcp.client.stdio
        except ImportError:
            self.skipTest("Optional MCP SDK required")
        attempts = []
        @asynccontextmanager
        async def failed(params, **kwargs):
            attempts.append(params)
            raise RuntimeError("sensitive-transport-payload")
            yield
        @asynccontextmanager
        async def stalled(params, **kwargs):
            attempts.append(params)
            await asyncio.sleep(10)
            yield
        self.session.limits["timeout_seconds"] = 0.02
        for factory in (failed, stalled):
            with self.subTest(factory=factory.__name__):
                attempts.clear()
                with patch("mcp.client.stdio.stdio_client", factory), self.assertRaises(ProtocolError) as raised:
                    async with connect_stdio(python="operator-python", cwd=".", env={},
                                             context=self.context, limits=self.session.limits):
                        self.fail("Session must not yield")
                self.assertEqual("MCP_TRANSPORT_FAILED", raised.exception.code)
                self.assertNotIn("sensitive-transport-payload", str(raised.exception))
                self.assertEqual(1, len(attempts))
                self.assertEqual(["-I", "-B", "-m", "geospatial_mcp.server"], attempts[0].args)


if __name__ == "__main__":
    unittest.main()
