from __future__ import annotations

import shutil
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable

from ..adapters.backend_registry import VECTOR_PAGE, is_static
from ..canonical import sha256_digest
from ..compiler.map_candidate import MapCandidateCompiler
from ..compiler.map_lock import MapSpecLockCompiler
from ..errors import CartoError, ProtocolError, SecurityError
from ..repository.template_installer import ProjectTemplateInstaller
from ..repository.template_repository import TemplateRepository
from ..scenario_registry import ScenarioRegistry
from ..schema_registry import SchemaRegistry, load_document
from ..security.approval import ApprovalReceipt
from ..security.nonce_store import NonceStore
from ..security.paths import PathGuard
from .approvals import ApprovalGateCoordinator
from ..artifacts import artifact_ref, atomic_json, atomic_yaml, file_digest, utc_now
from .budget_store import BudgetStore
from .map_data_preparation import MapDataPreparer
from .map_delivery import MapDeliveryService
from .map_final_check import FinalMapCheckService
from .map_planning import MapPlanner
from .map_preview import MapPreviewService, freeze_object_digest
from .map_render import FormalMapRenderService, is_transient_render_error
from .models import ExecutionContext
from .state_machine import WorkflowStateStore, serialized_workflow_step

TOOL_VERSION = "0.4.0"


class MapGenerationWorkflow:
    """Map generation through exact approvals, final checks and recoverable local delivery."""

    REQUIRED_REQUEST_FIELDS = {
        "run_id", "audience", "scope", "environment", "requested_at", "template",
        "allowed_capabilities", "font", "intent",
    }

    def __init__(self, *, allowed_roots: list[str | Path], project_root: str | Path,
                 workdir: str | Path, repository_root: str | Path | None = None,
                 repository_scope: str | None = None, registry: SchemaRegistry | None = None) -> None:
        self.registry = registry or SchemaRegistry()
        self.path_guard = PathGuard(allowed_roots)
        self.project_root = self.path_guard.resolve(project_root, must_exist=True)
        if not self.project_root.is_dir():
            raise SecurityError("PROJECT_ROOT_INVALID", str(self.project_root))
        self.work_root = self.path_guard.resolve(workdir, base_root=self.project_root)
        self.work_root.mkdir(parents=True, exist_ok=True)
        self.state_store = WorkflowStateStore(self.work_root, self.registry)
        self.repository_root = (self.path_guard.resolve(repository_root, must_exist=True)
                                if repository_root is not None else None)
        self.repository_scope = repository_scope
        self._budget_store = BudgetStore(self.work_root, self.registry)
        self._nonce_store = NonceStore(self.work_root / ".nonce-ledger.db")

    def _gate_coordinator(self, approval_key: bytes, request: dict[str, Any]) -> ApprovalGateCoordinator:
        """Create an ApprovalGateCoordinator wired with NonceStore and trusted identity (R1+R3)."""
        ctx = ExecutionContext.from_generate_request(request)
        return ApprovalGateCoordinator(
            approval_key,
            nonce_store=self._nonce_store,
            trusted_subject_id=request["subject"]["approver_subject_id"],
            trusted_tenant_id=ctx.tenant_id,
            trusted_scope=request.get("scope"),
            trusted_environment=request["environment"],
        )

    @serialized_workflow_step
    def intake(self, request_path: str | Path) -> dict[str, Any]:
        request = self._read_request(request_path)
        self._validate_runtime_request(request)
        state = self.state_store.initialize(request["run_id"], request, step="intake")
        intent = self._intent(request)
        request_target = self.path_guard.resolve(self.work_root / "request/generate-request.yaml")
        intent_target = self.path_guard.resolve(self.work_root / "intent/map-intent.yaml")
        atomic_yaml(request_target, request)
        atomic_yaml(self.work_root / "request/original-request.yaml", request, create_once=True)
        atomic_yaml(intent_target, intent)
        state, receipt = self.state_store.complete_step(
            state, status="succeeded", prerequisites={},
            output_refs=[artifact_ref("generate-request", request, request_target),
                         artifact_ref("map-intent", intent, intent_target)],
            tool_versions={"map-intake": TOOL_VERSION}, next_step="brief",
        )
        return {"state": state.to_dict(), "receipt": receipt.to_dict(), "intent": intent}

    @serialized_workflow_step
    def brief(self, request_path: str | Path) -> dict[str, Any]:
        request, state = self._resume(request_path, "brief")
        intent = self._load("intent/map-intent.yaml", "map-intent")
        ScenarioRegistry(self.registry).require_request_intent(request, intent)
        template_ref = {key: request["template"][key] for key in ("kind", "id", "version", "digest")
                        if key in request["template"]}
        if "digest" not in template_ref:
            if self.repository_root is None or not self.repository_scope:
                raise ProtocolError("TEMPLATE_REPOSITORY_REQUIRED", "brief requires repository lookup when digest is omitted")
            entry = self._repository().discover(namespace=request["template"]["namespace"],
                                                kind=request["template"]["kind"],
                                                template_id=request["template"]["id"],
                                                version=request["template"]["version"])
            template_ref["digest"] = entry["digest"]
        source_plan = []
        for binding in sorted(request.get("source_bindings", []), key=lambda item: item["role"]):
            operations = [item for item in ("read", "filter", "join", "classify", "reproject")
                          if item in request["allowed_capabilities"]]
            source_plan.append({"role": binding["role"], "source_ref": binding["source_ref"],
                                "allowed_operations": operations, "path_digest": file_digest(
                                    self.path_guard.resolve(binding["path"], base_root=self.project_root, must_exist=True)),
                                "field_bindings": [{"semantic_role": item["semantic_role"],
                                                    "source_field": item["source_field"]}
                                                   for item in binding.get("field_bindings", [])]})
        if "vector_sources" in request:
            for source in sorted(request["vector_sources"], key=lambda item: item["source_id"]):
                actual = []
                for item in sorted(source["files"], key=lambda item: item["extension"]):
                    path = self.path_guard.resolve(item["path"], base_root=self.project_root, must_exist=True)
                    if path.stat().st_size != item["size_bytes"] or file_digest(path) != item["digest"]:
                        raise ProtocolError("VECTOR_SOURCE_CHANGED", "Vector sidecars differ from their declaration")
                    actual.append({"extension": item["extension"], "digest": item["digest"], "size_bytes": item["size_bytes"]})
                fields = sorted({p["design"]["field"] for p in request["vector_panels"] if p["source_id"] == source["source_id"] and p["design"]["field"] is not None})
                fields = sorted(set(fields) | {p["design"]["normalization"]["denominator_field"]
                    for p in request["vector_panels"] if p["source_id"] == source["source_id"] and p["design"].get("normalization")})
                source_plan.append({"role": source["role"], "source_ref": next(r for r in request["sources"] if r["id"] == source["source_id"]),
                                    "allowed_operations": [v for v in ("read", "join", "classify") if v in request["allowed_capabilities"]], "path_digest": sha256_digest({"geometry":actual,"attribute_join":source.get("attribute_join")}),
                                    "field_bindings": [{"semantic_role": "thematic-value", "source_field": f} for f in fields]})
        brief = {
            "schema_version": 1, "brief_id": f"brief-{request['run_id']}", "revision": 1,
            "intent_ref": artifact_ref("map-intent", intent), "purpose": request["goal"],
            "request_ref": artifact_ref("generate-request", request),
            "audience": request["audience"], "source_plan": source_plan,
            "targets": sorted(request["requested_outputs"]), "template_candidates": [template_ref],
            "delegation": {"allow_data_agent": False, "max_tool_calls": 0}, "approval_required": True,
            "project_id": request["project_id"], "business_scene": intent["business_scene"],
            "theme_tags": intent["theme_tags"], "tasks": intent["tasks"],
            "scope": request["scope"], "environment": request["environment"],
            "allowed_capabilities": sorted(request["allowed_capabilities"]),
        }
        self.registry.validate("map-brief", brief)
        target = self.path_guard.resolve(self.work_root / "brief/map-brief.yaml")
        atomic_yaml(target, brief)
        state, receipt = self.state_store.complete_step(
            state, status="waiting_approval", prerequisites={"intent": intent},
            output_refs=[artifact_ref("map-brief", brief, target)],
            tool_versions={"map-brief-builder": TOOL_VERSION}, next_step="compile",
        )
        return {"state": state.to_dict(), "receipt": receipt.to_dict(), "brief": brief,
                "approval_object_digest": sha256_digest(brief)}

    @serialized_workflow_step
    def compile(self, request_path: str | Path, approval_path: str | Path, *, approval_key: bytes) -> dict[str, Any]:
        request, state = self._resume(request_path, "compile")
        self._validate_runtime_request(request)
        intent = self._load("intent/map-intent.yaml", "map-intent")
        profile = ScenarioRegistry(self.registry).require_request_intent(request, intent)
        brief = self._load("brief/map-brief.yaml", "map-brief")
        profile.require_intent_projection(brief, intent, kind="BRIEF")
        approval_file = self._resolve_project_path(approval_path, must_exist=True)
        approval_value = load_document(approval_file)
        if not isinstance(approval_value, dict):
            raise ProtocolError("MAP_BRIEF_APPROVAL_REQUIRED", "Approval receipt must be an object")
        self.registry.validate("approval-receipt", approval_value)
        approval_receipt = ApprovalReceipt.from_dict(approval_value)
        coordinator = self._gate_coordinator(approval_key, request)
        coordinator.require("G1", approval_receipt, sha256_digest(brief),
                            run_id=request["run_id"])
        approval_snapshot = self._snapshot_approval(approval_value)
        if request.get("design_variants"):
            variant_result, outputs = self._compile_variant_set(request, intent, brief)
            outputs.append(artifact_ref("map-brief-approval", approval_value, approval_snapshot))
            state, receipt = self.state_store.complete_step(
                state, status="succeeded", prerequisites={"brief": brief, "approval": approval_value},
                output_refs=outputs, tool_versions={"map-candidate-compiler": TOOL_VERSION},
                next_step="select-candidate")
            return {"state": state.to_dict(), "receipt": receipt.to_dict(),
                    "candidate_set": variant_result["candidate_set"]}
        compiled, outputs = self._compile_approved_candidate(request, intent, brief)
        outputs.append(artifact_ref("map-brief-approval", approval_value, approval_snapshot))
        if compiled["preflight"]["status"] != "passed":
            self.state_store.complete_step(
                state, status="failed", prerequisites={"brief": brief, "approval": approval_value},
                output_refs=outputs, tool_versions={"map-candidate-compiler": TOOL_VERSION},
                error={"code": "CANDIDATE_QUALITY_FAILED", "message": compiled["preflight"]["report_id"]},
            )
            raise ProtocolError("CANDIDATE_QUALITY_FAILED", compiled["preflight"]["report_id"])
        state, receipt = self.state_store.complete_step(
            state, status="succeeded", prerequisites={"brief": brief, "approval": approval_value},
            output_refs=outputs, tool_versions={"map-candidate-compiler": TOOL_VERSION}, next_step="preview",
        )
        return {
            "state": state.to_dict(),
            "receipt": receipt.to_dict(),
            **compiled,
        }

    def _compile_approved_candidate(
        self,
        request: dict[str, Any],
        intent: dict[str, Any],
        brief: dict[str, Any],
    ) -> tuple[dict[str, Any], list[dict[str, str]]]:
        """Deterministically materialize and verify every G1-authorized candidate artifact."""
        repository = self._repository()
        installation = ProjectTemplateInstaller(
            path_guard=self.path_guard,
            project_root=self.project_root,
            repository=repository,
            registry=self.registry,
        ).install(request["template"])
        self._verify_installed_template(installation)
        installed_target = self.path_guard.resolve(self.work_root / "templates/installed-template.yaml")
        atomic_yaml(installed_target, installation)
        preparer = MapDataPreparer(
            self.path_guard,
            self.project_root,
            self.path_guard.resolve(self._design_path("data")),
            self.registry,
        )
        # W1-M2: reuse the prepared bundle when the dependency graph proves the
        # data evidence is not invalidated and the digest gate matches.
        bundle = self._reusable_bundle(request)
        if bundle is None:
            prepared = preparer.prepare(request, artifact_ref("generate-request", request))
            bundle = prepared["bundle"]
        bundle_target = self.path_guard.resolve(self._design_path("data/prepared-data-bundle.yaml"))
        atomic_yaml(bundle_target, bundle)
        compiler = self._candidate_compiler(request)
        contracts = compiler.load_contracts(installation)
        # R6: merge revised_cartography from the request into contracts so
        #     design-revision cartography changes are applied at compile time.
        if request.get("revised_cartography"):
            contracts.setdefault("scenario", {}).setdefault("embedded", {})
            contracts["scenario"]["embedded"]["cartography"] = deepcopy(request["revised_cartography"])
        # R6b: optional output_profile overrides the template's default canvas
        #     dimensions.  The template declares A4 landscape (297×210 mm) as its
        #     default; the request may supply a different page size within the
        #     scenario's output_constraints envelope (max 420×297 mm).
        if request.get("output_profile"):
            contracts.setdefault("scenario", {}).setdefault("embedded", {}).setdefault("layout", {}).setdefault("canvas", {})
            op = request["output_profile"]
            if "width_mm" in op:
                contracts["scenario"]["embedded"]["layout"]["canvas"]["width"] = op["width_mm"]
            if "height_mm" in op:
                contracts["scenario"]["embedded"]["layout"]["canvas"]["height"] = op["height_mm"]
        plan = MapPlanner(self.registry, project_root=self.project_root).build(request, intent, brief, bundle, installation, contracts)
        plan_target = self.path_guard.resolve(self._design_path("plan/map-plan.yaml"))
        atomic_yaml(plan_target, plan)
        font = self.path_guard.resolve(request["font"]["path"], base_root=self.project_root, must_exist=True)
        compiled = compiler.compile(request, intent, plan, bundle, installation, contracts, font)
        candidate_target = self.path_guard.resolve(self._design_path("candidates/resolved-map.yaml"))
        scene_target = self.path_guard.resolve(self._design_path("candidates/render-scene.yaml"))
        report_target = self.path_guard.resolve(self._design_path("candidates/preflight-report.yaml"))
        atomic_yaml(candidate_target, compiled["candidate"])
        atomic_yaml(scene_target, compiled["scene"])
        atomic_yaml(report_target, compiled["preflight"])
        outputs = [
            artifact_ref("installed-template", installation, installed_target),
            artifact_ref("prepared-data-bundle", bundle, bundle_target),
            artifact_ref("map-plan", plan, plan_target),
            artifact_ref("resolved-map", compiled["candidate"], candidate_target),
            artifact_ref("render-scene", compiled["scene"], scene_target),
            artifact_ref("preflight-report", compiled["preflight"], report_target),
        ]
        return compiled, outputs

    def _compile_variant_set(self, request: dict[str, Any], intent: dict[str, Any],
                             brief: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, str]]]:
        # Deterministically compile each externally supplied design variant into its own
        # immutable candidate directory plus a candidate-set. One template install, data
        # preparation and plan are shared; only cartography/output_profile differ. The
        # program never ranks or selects -- that is the separate select-candidate step.
        repository = self._repository()
        installation = ProjectTemplateInstaller(
            path_guard=self.path_guard, project_root=self.project_root,
            repository=repository, registry=self.registry).install(request["template"])
        self._verify_installed_template(installation)
        installed_target = self.path_guard.resolve(self.work_root / "templates/installed-template.yaml")
        atomic_yaml(installed_target, installation)
        preparer = MapDataPreparer(self.path_guard, self.project_root,
                                   self.path_guard.resolve(self._design_path("data")), self.registry)
        # W1-M2: reuse the prepared bundle when the dependency graph proves the
        # data evidence is not invalidated and the digest gate matches.
        bundle = self._reusable_bundle(request)
        if bundle is None:
            prepared = preparer.prepare(request, artifact_ref("generate-request", request))
            bundle = prepared["bundle"]
        bundle_target = self.path_guard.resolve(self._design_path("data/prepared-data-bundle.yaml"))
        atomic_yaml(bundle_target, bundle)
        compiler = self._candidate_compiler(request)
        contracts = compiler.load_contracts(installation)
        plan = MapPlanner(self.registry, project_root=self.project_root).build(
            request, intent, brief, bundle, installation, contracts)
        plan_target = self.path_guard.resolve(self._design_path("plan/map-plan.yaml"))
        atomic_yaml(plan_target, plan)
        font = self.path_guard.resolve(request["font"]["path"], base_root=self.project_root, must_exist=True)
        result = compiler.compile_variants(request, intent, plan, bundle, installation,
                                           contracts, font, request["design_variants"])
        outputs = [
            artifact_ref("installed-template", installation, installed_target),
            artifact_ref("prepared-data-bundle", bundle, bundle_target),
            artifact_ref("map-plan", plan, plan_target),
        ]
        for _variant_id, compiled in sorted(result["compiled"].items()):
            candidate = compiled["candidate"]
            cid = candidate["candidate_id"]
            cand_target = self.path_guard.resolve(self._design_path(f"candidates/{cid}/resolved-map.yaml"))
            scene_target = self.path_guard.resolve(self._design_path(f"candidates/{cid}/render-scene.yaml"))
            report_target = self.path_guard.resolve(self._design_path(f"candidates/{cid}/preflight-report.yaml"))
            atomic_yaml(cand_target, candidate)
            atomic_yaml(scene_target, compiled["scene"])
            atomic_yaml(report_target, compiled["preflight"])
            outputs += [
                artifact_ref("resolved-map", candidate, cand_target),
                artifact_ref("render-scene", compiled["scene"], scene_target),
                artifact_ref("preflight-report", compiled["preflight"], report_target),
            ]
        set_target = self.path_guard.resolve(self._design_path("candidates/candidate-set.yaml"))
        atomic_yaml(set_target, result["candidate_set"])
        outputs.append(artifact_ref("candidate-set", result["candidate_set"], set_target))
        return result, outputs

    @serialized_workflow_step
    def select_candidate(self, request_path: str | Path, candidate_id: str) -> dict[str, Any]:
        # Externally driven selection: promote one already-compiled candidate to the active
        # path so preview/freeze read it unchanged. The program never ranks or picks; the
        # caller supplies candidate_id. Selection is recorded in the immutable step receipt.
        request, state = self._resume(request_path, "select-candidate")
        candidate_set = self._load("candidates/candidate-set.yaml", "candidate-set")
        matches = [c for c in candidate_set["candidates"] if c["candidate_id"] == candidate_id]
        if len(matches) != 1:
            raise ProtocolError("CANDIDATE_SELECTION_INVALID", candidate_id)
        selected = matches[0]
        promoted: dict[str, Any] = {}
        active: dict[str, Any] = {}
        for name, schema in (("resolved-map", "resolved-map"), ("render-scene", "render-scene"),
                             ("preflight-report", "validation-report")):
            source = self.path_guard.resolve(
                self._design_path(f"candidates/{candidate_id}/{name}.yaml"), must_exist=True)
            document = load_document(source)
            self.registry.validate(schema, document)
            target = self.path_guard.resolve(self._design_path(f"candidates/{name}.yaml"))
            atomic_yaml(target, document, create_once=True)
            promoted[name] = document
            active[name] = target
        if (sha256_digest(promoted["resolved-map"]) != selected["resolved_map_digest"]
                or sha256_digest(promoted["render-scene"]) != selected["render_scene_digest"]):
            raise ProtocolError("CANDIDATE_SELECTION_DRIFT", candidate_id)
        state, receipt = self.state_store.complete_step(
            state, status="succeeded", prerequisites={"candidate_set": candidate_set},
            output_refs=[artifact_ref("resolved-map", promoted["resolved-map"], active["resolved-map"]),
                         artifact_ref("render-scene", promoted["render-scene"], active["render-scene"]),
                         artifact_ref("preflight-report", promoted["preflight-report"], active["preflight-report"])],
            tool_versions={"candidate-selection": TOOL_VERSION}, next_step="preview")
        return {"state": state.to_dict(), "receipt": receipt.to_dict(),
                "selected_candidate_id": candidate_id, "candidate": promoted["resolved-map"]}

    @serialized_workflow_step
    def preview(self, request_path: str | Path, *, attestation_key: bytes,
                browser: str | Path | None = None) -> dict[str, Any]:
        request, state = self._resume(request_path, "preview")
        candidate = self._load("candidates/resolved-map.yaml", "resolved-map")
        scene = self._load("candidates/render-scene.yaml", "render-scene")
        preflight = self._load("candidates/preflight-report.yaml", "validation-report")
        installation = self._load("templates/installed-template.yaml")
        self._verify_installed_template(installation)
        contracts = MapCandidateCompiler(self.path_guard, self.registry).load_contracts(installation)
        self._verify_candidate_inputs(candidate, scene, contracts, preflight)
        service = MapPreviewService(path_guard=self.path_guard,
                                    output_root=self.path_guard.resolve(self._design_path("previews")),
                                    attestation_key=attestation_key, browser=browser, registry=self.registry,
                                    project_root=self.project_root, context=ExecutionContext.from_generate_request(request))
        rendered = service.render(request, candidate, scene)
        receipt_target = self.path_guard.resolve(self._design_path("candidates/render-receipt.yaml"))
        evidence_target = self.path_guard.resolve(self._design_path("candidates/preview-evidence.yaml"))
        atomic_yaml(receipt_target, rendered["receipt"])
        atomic_yaml(evidence_target, rendered["evidence"])
        state, receipt = self.state_store.complete_step(
            state, status="waiting_approval", prerequisites={"candidate": candidate, "scene": scene, "preflight": preflight},
            output_refs=[artifact_ref("render-receipt", rendered["receipt"], receipt_target),
                         artifact_ref("map-preview-evidence", rendered["evidence"], evidence_target)],
            tool_versions={"controlled-map-preview": TOOL_VERSION}, next_step="freeze",
        )
        return {"state": state.to_dict(), "receipt": receipt.to_dict(), **rendered,
                "approval_object_digest": freeze_object_digest(request, candidate, rendered["evidence"])}

    @serialized_workflow_step
    def freeze(self, request_path: str | Path, approval_path: str | Path, *, approval_key: bytes,
               attestation_key: bytes,
               browser: str | Path | None = None,
               design_review_approval_path: str | Path | None = None) -> dict[str, Any]:
        request = self._read_request(request_path)
        state = self.state_store.load()
        if sha256_digest(request) != state.input_fingerprint:
            raise ProtocolError("JOB_INPUT_DRIFT", state.run_id)
        stored = self._load("request/generate-request.yaml", "generate-request")
        if stored != request:
            raise ProtocolError("JOB_INPUT_DRIFT", state.run_id)
        if state.step not in {"freeze", "render"}:
            raise ProtocolError("WORKFLOW_STEP_INVALID", f"expected=freeze; actual={state.step}")
        candidate = self._load("candidates/resolved-map.yaml", "resolved-map")
        scene = self._load("candidates/render-scene.yaml", "render-scene")
        preflight = self._load("candidates/preflight-report.yaml", "validation-report")
        receipt = self._load("candidates/render-receipt.yaml", "render-receipt")
        evidence = self._load("candidates/preview-evidence.yaml", "map-preview-evidence")
        installation = self._load("templates/installed-template.yaml")
        self._verify_installed_template(installation)
        contracts = MapCandidateCompiler(self.path_guard, self.registry).load_contracts(installation)
        self._verify_candidate_inputs(candidate, scene, contracts, preflight)
        service = MapPreviewService(path_guard=self.path_guard,
                                    output_root=self.path_guard.resolve(self._design_path("previews"), must_exist=True),
                                    attestation_key=attestation_key, browser=browser, registry=self.registry,
                                    project_root=self.project_root, context=ExecutionContext.from_generate_request(request))
        service.validate_persisted(candidate, scene, receipt)
        service.validate_evidence(evidence, candidate, scene, receipt, self.registry)
        approval_file = self._resolve_project_path(approval_path, must_exist=True)
        approval_value = load_document(approval_file)
        if not isinstance(approval_value, dict):
            raise ProtocolError("FREEZE_APPROVAL_REQUIRED", "Approval receipt must be an object")
        self.registry.validate("approval-receipt", approval_value)
        approval_receipt = ApprovalReceipt.from_dict(approval_value)
        coordinator = self._gate_coordinator(approval_key, request)
        approval_digest = freeze_object_digest(request, candidate, evidence)
        approved_brief_ref = self.state_store.find_output_ref("map-brief-approval")
        self._load_ref(approved_brief_ref, "approval-receipt")
        coordinator.require("G2", approval_receipt, approval_digest,
                            run_id=request["run_id"])
        design_review_ref = self._design_review_ref(
            request, candidate, evidence, coordinator, design_review_approval_path)
        compiler = MapSpecLockCompiler(self.registry)
        brief_approval_ref = approved_brief_ref["uri"]
        freeze_approval_ref = str(self._snapshot_approval(approval_value))
        target = self.path_guard.resolve(
            self.work_root / "locks" / f"lock-{request['run_id']}" / "map-spec-lock.yaml"
        )
        if target.exists():
            existing = load_document(target)
            if not isinstance(existing, dict):
                raise ProtocolError("MAP_SPEC_LOCK_INVALID", str(target))
            compiler.verify_existing(
                existing, request, candidate, evidence, receipt, preflight,
                brief_approval_ref=brief_approval_ref,
                freeze_approval_ref=freeze_approval_ref,
                design_review_ref=design_review_ref,
            )
            if state.step == "render":
                if state.status != "pending":
                    raise ProtocolError("JOB_RECOVERY_NOT_ALLOWED", f"status={state.status}; step={state.step}")
                coordinator.require(
                    "G2", approval_receipt, approval_digest, run_id=request["run_id"],
                )
                if self.state_store.find_output_digest("map-spec-lock") != sha256_digest(existing):
                    raise ProtocolError("JOB_PREREQUISITE_DRIFT", state.run_id)
                return {"state": state.to_dict(), "lock": existing, "idempotent_replay": True}
            if state.status not in {"pending", "waiting_approval"}:
                raise ProtocolError("JOB_RECOVERY_NOT_ALLOWED", f"status={state.status}; step={state.step}")
            coordinator.require(
                "G2", approval_receipt, approval_digest, run_id=request["run_id"],
            )
            state, step_receipt = self.state_store.complete_step(
                state, status="succeeded",
                prerequisites={"candidate": candidate, "preview": evidence,
                               "freeze_approval": approval_value},
                output_refs=[artifact_ref("map-spec-lock", existing, target)],
                tool_versions={"map-spec-freezer": TOOL_VERSION}, next_step="render",
            )
            return {"state": state.to_dict(), "receipt": step_receipt.to_dict(),
                    "lock": existing, "idempotent_replay": True}
        if state.step == "render":
            raise ProtocolError("JOB_PREREQUISITE_DRIFT", "map-spec-lock")
        coordinator.require(
            "G2", approval_receipt, approval_digest, run_id=request["run_id"],
        )
        lock = compiler.compile(
            request, candidate, evidence, receipt, preflight,
            brief_approval_ref=brief_approval_ref, freeze_approval_ref=freeze_approval_ref,
            design_review_ref=design_review_ref,
        )
        atomic_yaml(target, lock)
        state, step_receipt = self.state_store.complete_step(
            state, status="succeeded", prerequisites={"candidate": candidate, "preview": evidence,
                                                       "freeze_approval": approval_value},
            output_refs=[artifact_ref("map-spec-lock", lock, target)],
            tool_versions={"map-spec-freezer": TOOL_VERSION}, next_step="render",
        )
        return {"state": state.to_dict(), "receipt": step_receipt.to_dict(),
                "lock": lock, "idempotent_replay": False}

    @serialized_workflow_step
    def render(self, request_path: str | Path, *, attestation_key: bytes,
               browser: str | Path | None = None) -> dict[str, Any]:
        request = self._read_request(request_path)
        state = self.state_store.load()
        if sha256_digest(request) != state.input_fingerprint:
            raise ProtocolError("JOB_INPUT_DRIFT", state.run_id)
        stored = self._load("request/generate-request.yaml", "generate-request")
        if stored != request:
            raise ProtocolError("JOB_INPUT_DRIFT", state.run_id)
        if state.step == "check" and state.status == "pending":
            lock, lock_ref, scene, preview_receipt = self._locked_render_inputs(
                request, attestation_key=attestation_key, browser=browser
            )
            service = FormalMapRenderService(
                path_guard=self.path_guard, work_root=self.work_root,
                attestation_key=attestation_key, browser=browser, registry=self.registry,
                project_root=self.project_root, context=ExecutionContext.from_generate_request(request),
                renderer_id=scene["renderer_id"],
            )
            service.validate_environment(lock, preview_receipt)
            service.validate_scene(scene, lock["execution"])
            evidence_ref = self.state_store.find_output_ref("formal-render-evidence")
            evidence_path = self.path_guard.resolve(evidence_ref["uri"], must_exist=True)
            evidence = load_document(evidence_path)
            if not isinstance(evidence, dict):
                raise ProtocolError("FORMAL_RENDER_EVIDENCE_INVALID", str(evidence_path))
            self.registry.validate("formal-render-evidence", evidence)
            if sha256_digest(evidence) != evidence_ref["digest"]:
                raise ProtocolError("FORMAL_RENDER_EVIDENCE_DIGEST_MISMATCH", evidence["evidence_id"])
            attempt_path = self.path_guard.resolve(evidence["attempt_ref"]["uri"], must_exist=True)
            attempt = load_document(attempt_path)
            if not isinstance(attempt, dict):
                raise ProtocolError("RENDER_ATTEMPT_INVALID", str(attempt_path))
            self.registry.validate("render-attempt", attempt)
            existing = service.load_existing(
                request=request, lock=lock, lock_ref=lock_ref, scene=scene,
                attempt_number=attempt["attempt_number"],
            )
            if existing is None or existing["attempt"]["status"] != "succeeded":
                raise ProtocolError("FORMAL_RENDER_EVIDENCE_INVALID", evidence["evidence_id"])
            if existing["evidence"] != evidence:
                raise ProtocolError("FORMAL_RENDER_EVIDENCE_BINDING_MISMATCH", evidence["evidence_id"])
            return {"state": state.to_dict(), "attempt": existing["attempt"],
                    "render_receipt": existing["receipt"], "evidence": existing["evidence"],
                    "idempotent_replay": True}
        if state.step != "render":
            raise ProtocolError("WORKFLOW_STEP_INVALID", f"expected=render; actual={state.step}")
        if state.status != "pending":
            raise ProtocolError("WORKFLOW_STATUS_INVALID", f"expected=pending; actual={state.status}")

        started_at = utc_now()
        service = None
        lock: dict[str, Any]
        lock_ref: dict[str, str]
        scene: dict[str, Any]
        try:
            lock, lock_ref, scene, preview_receipt = self._locked_render_inputs(
                request, attestation_key=attestation_key, browser=browser
            )
            service = FormalMapRenderService(
                path_guard=self.path_guard, work_root=self.work_root,
                attestation_key=attestation_key, browser=browser, registry=self.registry,
                project_root=self.project_root, context=ExecutionContext.from_generate_request(request),
                renderer_id=scene["renderer_id"],
            )
            service.validate_environment(lock, preview_receipt)
            service.validate_scene(scene, lock["execution"])
        except CartoError as exc:
            normalized = exc if exc.code in {"LOCK_INPUT_DRIFT", "RENDER_ENVIRONMENT_DRIFT",
                                              "ENCODING_SEMANTICS_INVALID"} else ProtocolError(
                "LOCK_INPUT_DRIFT", f"{exc.code}: {exc.message}"
            )
            context = getattr(exc, "render_context", None)
            if context is None and "lock" in locals() and "lock_ref" in locals() and "scene" in locals():
                context = (lock, lock_ref, scene)
            if context is not None and service is not None:
                lock, lock_ref, scene = context
                attempt, attempt_path = service.record_failure(
                    request=request, lock=lock, lock_ref=lock_ref, scene=scene,
                    attempt_number=state.attempt, started_at=started_at,
                    error=normalized, retryable=False,
                )
                prerequisites = {"lock": lock, "scene": scene}
                output_refs = [artifact_ref("render-attempt", attempt, attempt_path)]
            else:
                prerequisites = {"request": request}
                output_refs = []
            self.state_store.complete_step(
                state, status="failed", prerequisites=prerequisites, output_refs=output_refs,
                tool_versions={"formal-map-render": TOOL_VERSION},
                error={"code": normalized.code, "message": normalized.message},
            )
            raise normalized

        existing = service.load_existing(
            request=request, lock=lock, lock_ref=lock_ref, scene=scene,
            attempt_number=state.attempt,
        )
        if existing is not None:
            if existing["attempt"]["status"] == "failed":
                error = existing["attempt"]["error"]
                self.state_store.complete_step(
                    state, status="failed", prerequisites={"lock": lock, "scene": scene},
                    output_refs=[artifact_ref("render-attempt", existing["attempt"], existing["attempt_path"])],
                    tool_versions={"formal-map-render": TOOL_VERSION}, error=error,
                )
                raise ProtocolError(error["code"], error["message"])
            return self._complete_formal_render(state, lock, scene, existing, idempotent_replay=True)

        output_directory = service.output_directory(lock["lock_id"], service.attempt_id(request["run_id"], state.attempt))
        if output_directory.exists():
            orphan = ProtocolError("RENDER_ATTEMPT_INCOMPLETE", str(output_directory))
            attempt, attempt_path = service.record_failure(
                request=request, lock=lock, lock_ref=lock_ref, scene=scene,
                attempt_number=state.attempt, started_at=started_at,
                error=orphan, retryable=True,
            )
            self.state_store.complete_step(
                state, status="failed", prerequisites={"lock": lock, "scene": scene},
                output_refs=[artifact_ref("render-attempt", attempt, attempt_path)],
                tool_versions={"formal-map-render": TOOL_VERSION},
                error={"code": orphan.code, "message": orphan.message},
            )
            raise orphan
        try:
            rendered = service.render(
                request=request, lock=lock, lock_ref=lock_ref, scene=scene,
                attempt_number=state.attempt, started_at=started_at,
            )
        except CartoError as exc:
            retryable = is_transient_render_error(exc)
            attempt, attempt_path = service.record_failure(
                request=request, lock=lock, lock_ref=lock_ref, scene=scene,
                attempt_number=state.attempt, started_at=started_at,
                error=exc, retryable=retryable,
            )
            self.state_store.complete_step(
                state, status="failed", prerequisites={"lock": lock, "scene": scene},
                output_refs=[artifact_ref("render-attempt", attempt, attempt_path)],
                tool_versions={"formal-map-render": TOOL_VERSION},
                error={"code": exc.code, "message": exc.message},
            )
            raise
        return self._complete_formal_render(state, lock, scene, rendered, idempotent_replay=False)

    def _complete_formal_render(self, state: Any, lock: dict[str, Any], scene: dict[str, Any],
                                rendered: dict[str, Any], *, idempotent_replay: bool) -> dict[str, Any]:
        state, step_receipt = self.state_store.complete_step(
            state, status="succeeded", prerequisites={"lock": lock, "scene": scene},
            output_refs=[
                artifact_ref("render-attempt", rendered["attempt"], rendered["attempt_path"]),
                artifact_ref("formal-render-receipt", rendered["receipt"], rendered["receipt_path"]),
                artifact_ref("formal-render-evidence", rendered["evidence"], rendered["evidence_path"]),
            ],
            tool_versions={"formal-map-render": TOOL_VERSION}, next_step="check",
        )
        return {"state": state.to_dict(), "receipt": step_receipt.to_dict(),
                "attempt": rendered["attempt"], "render_receipt": rendered["receipt"],
                "evidence": rendered["evidence"], "idempotent_replay": idempotent_replay}

    @serialized_workflow_step
    def check(
        self,
        request_path: str | Path,
        *,
        attestation_key: bytes,
        browser: str | Path | None = None,
    ) -> dict[str, Any]:
        """Auto final-check: validate rendered outputs, produce report, classify failures.

        Does NOT generate a delivery manifest — that is the responsibility of
        :meth:`review` (A1.3 split).
        """
        request, state = self._resume(request_path, "check")
        if state.status != "pending":
            raise ProtocolError("WORKFLOW_STATUS_INVALID", f"expected=pending; actual={state.status}")

        lock, lock_ref, scene, preview_receipt = self._locked_render_inputs(
            request, attestation_key=attestation_key, browser=browser
        )
        render_service = FormalMapRenderService(
            path_guard=self.path_guard, work_root=self.work_root,
            attestation_key=attestation_key, browser=browser, registry=self.registry,
            project_root=self.project_root, context=ExecutionContext.from_generate_request(request),
            renderer_id=scene["renderer_id"],
        )
        render_service.validate_environment(lock, preview_receipt)
        render_service.validate_scene(scene, lock["execution"])
        evidence_ref = self.state_store.find_output_ref("formal-render-evidence")
        evidence = self._load_ref(evidence_ref, "formal-render-evidence")
        attempt_number = int(evidence["attempt_ref"]["id"].rsplit("-", 1)[1])
        existing = render_service.load_existing(
            request=request, lock=lock, lock_ref=lock_ref, scene=scene,
            # FinalMapCheckService inspects the actual outputs and persists a failed
            # report/state for tampering; the loader must not fail before that step.
            attempt_number=attempt_number, verify_outputs=False,
        )
        if existing is None or existing["attempt"]["status"] != "succeeded":
            raise ProtocolError("FINAL_CHECK_RENDER_INVALID", evidence["evidence_id"])
        checker = FinalMapCheckService(
            path_guard=self.path_guard, project_root=self.project_root,
            work_root=self.work_root, registry=self.registry,
            execution_context=ExecutionContext.from_generate_request(request),
        )
        report = checker.inspect(
            lock=lock, lock_ref=lock_ref, scene=scene,
            attempt=existing["attempt"], attempt_path=existing["attempt_path"],
            receipt=existing["receipt"], evidence=existing["evidence"],
            evidence_path=existing["evidence_path"],
        )
        report_path = checker.write_report(report, existing["attempt"]["attempt_id"])
        report_ref = artifact_ref("final-validation-report", report, report_path)

        if report["status"] != "passed":
            classification = self._classify_check_failure(report)
            self.state_store.complete_step(
                state, status="failed",
                prerequisites={"lock": lock, "attempt": existing["attempt"],
                               "evidence": existing["evidence"]},
                output_refs=[report_ref],
                tool_versions={"final-map-check": TOOL_VERSION},
                error={"code": "FINAL_CHECK_FAILED", "message": report["report_id"],
                       "classification": classification},
            )
            raise ProtocolError("FINAL_CHECK_FAILED", report["report_id"])

        state, step_receipt = self.state_store.complete_step(
            state, status="waiting_approval",
            prerequisites={"lock": lock, "attempt": existing["attempt"],
                           "evidence": existing["evidence"]},
            output_refs=[report_ref],
            tool_versions={"final-map-check": TOOL_VERSION}, next_step="review",
        )
        return {
            "state": state.to_dict(), "receipt": step_receipt.to_dict(),
            "validation_report": report, "report_digest": sha256_digest(report),
        }

    @staticmethod
    def _classify_check_failure(report: dict[str, Any]) -> str:
        """Classify a failed check report to determine the recovery path.

        Returns one of: DESIGN_ISSUE, RENDER_ISSUE, DATA_ISSUE, MANIFEST_ISSUE.
        """
        results = report.get("results", [])
        for item in results:
            check_name = item.get("check", "")
            if any(tag in check_name for tag in ("appearance", "template", "layout")):
                return "DESIGN_ISSUE"
            if any(tag in check_name for tag in ("render", "output", "artifact", "export")):
                return "RENDER_ISSUE"
            if any(tag in check_name for tag in ("data", "source", "input", "encoding")):
                return "DATA_ISSUE"
        return "RENDER_ISSUE"  # default: treat unknown as render issue

    # ------------------------------------------------------------------
    # review (A1.3) — product review with manifest generation
    # ------------------------------------------------------------------

    @serialized_workflow_step
    def review(
        self,
        request_path: str | Path,
        approval_path: str | Path,
        *,
        approval_key: bytes,
        attestation_key: bytes,
        recipient_id: str,
        recipient_type: str,
        destination: str | Path,
        idempotency_key: str,
        browser: str | Path | None = None,
    ) -> dict[str, Any]:
        """Product/design review: validate review approval, build manifest, gate delivery.

        Entry: state.step="review", state.status="waiting_approval" (from check).
        Also handles deliver retry: when deliver is waiting_approval, re-enters via review
        to re-validate the check report and manifest (A1.3: G3-gated delivery).
        """
        request = self._read_request(request_path)
        state = self.state_store.load()
        if sha256_digest(request) != state.input_fingerprint:
            raise ProtocolError("JOB_INPUT_DRIFT", state.run_id)
        stored = self._load("request/generate-request.yaml", "generate-request")
        if stored != request:
            raise ProtocolError("JOB_INPUT_DRIFT", state.run_id)

        # deliver re-entry path (A1.3: G3 后提交不确定时可查状态)
        if state.step == "deliver" and state.status == "waiting_approval":
            report_ref = self.state_store.find_output_ref("final-validation-report")
            manifest_ref = self.state_store.find_output_ref("delivery-manifest")
            report = self._load_ref(report_ref, "validation-report")
            manifest = self._load_ref(manifest_ref, "delivery-manifest")
            MapDeliveryService(path_guard=self.path_guard, project_root=self.project_root,
                               work_root=self.work_root, registry=self.registry).validate_review(
                                   request, manifest, approval_key)
            self._validate_check_invocation(
                manifest, recipient_id=recipient_id, recipient_type=recipient_type,
                destination=destination, idempotency_key=idempotency_key,
            )
            lock, lock_ref, scene, preview_receipt = self._locked_render_inputs(
                request, attestation_key=attestation_key, browser=browser
            )
            service = FormalMapRenderService(
                path_guard=self.path_guard, work_root=self.work_root,
                attestation_key=attestation_key, browser=browser, registry=self.registry,
                project_root=self.project_root, context=ExecutionContext.from_generate_request(request),
                renderer_id=scene["renderer_id"],
            )
            service.validate_environment(lock, preview_receipt)
            service.validate_scene(scene, lock["execution"])
            attempt_number = int(manifest["render_attempt_ref"]["id"].rsplit("-", 1)[1])
            existing = service.load_existing(
                request=request, lock=lock, lock_ref=lock_ref, scene=scene,
                attempt_number=attempt_number,
            )
            if existing is None or existing["attempt"]["status"] != "succeeded":
                raise ProtocolError("FINAL_CHECK_RENDER_INVALID", manifest["manifest_id"])
            checker = FinalMapCheckService(
                path_guard=self.path_guard, project_root=self.project_root,
                work_root=self.work_root, registry=self.registry,
                execution_context=ExecutionContext.from_generate_request(request),
            )
            recomputed = checker.inspect(
                lock=lock, lock_ref=lock_ref, scene=scene,
                attempt=existing["attempt"], attempt_path=existing["attempt_path"],
                receipt=existing["receipt"], evidence=existing["evidence"],
                evidence_path=existing["evidence_path"],
            )
            if recomputed != report:
                raise ProtocolError("FINAL_CHECK_REPORT_DRIFT", report["report_id"])
            expected_manifest = checker.build_manifest(
                request=request, lock=lock, lock_ref=lock_ref,
                attempt=existing["attempt"], attempt_path=existing["attempt_path"],
                report=report, report_path=self.path_guard.resolve(report_ref["uri"], must_exist=True),
                recipient_id=recipient_id, recipient_type=recipient_type,
                destination=destination, idempotency_key=idempotency_key,
                review_ref=manifest["review_ref"],
            )
            if expected_manifest != manifest:
                raise ProtocolError("DELIVERY_MANIFEST_DRIFT", manifest["manifest_id"])
            return {
                "state": state.to_dict(), "validation_report": report,
                "delivery_manifest": manifest, "g3": checker.g3_context(manifest),
                "idempotent_replay": True,
            }

        if state.step != "review":
            raise ProtocolError("WORKFLOW_STEP_INVALID", f"expected=review; actual={state.step}")
        if state.status not in {"waiting_approval", "pending"}:
            raise ProtocolError("WORKFLOW_STATUS_INVALID", f"expected=waiting_approval; actual={state.status}")

        # verify approval on the review
        approval_file = self._resolve_project_path(approval_path, must_exist=True)
        approval_value = load_document(approval_file)
        if not isinstance(approval_value, dict):
            raise ProtocolError("REVIEW_APPROVAL_REQUIRED", "Approval receipt must be an object")
        self.registry.validate("approval-receipt", approval_value)
        approval_receipt = ApprovalReceipt.from_dict(approval_value)
        coordinator = self._gate_coordinator(approval_key, request)

        # load check report
        report_ref = self.state_store.find_output_ref("final-validation-report")
        report = self._load_ref(report_ref, "validation-report")

        # validate review approval against the check report
        coordinator.require_attestation(
            "approve-product-review", "validation-report", approval_receipt, sha256_digest(report),
            run_id=request["run_id"],
        )

        review_id = "review-" + sha256_digest(approval_value)[7:31]
        review_path = self.path_guard.resolve(self.work_root / "reviews" / (review_id + ".yaml"))
        review_record = {"schema_version": 1, "review_id": review_id,
                         "run_id": request["run_id"], "project_id": request["project_id"],
                         "report_ref": report_ref, "approval": approval_value, "reviewed_at": utc_now()}
        if review_path.exists():
            previous = load_document(review_path)
            self.registry.validate("product-review", previous)
            review_record["reviewed_at"] = previous["reviewed_at"]
            if previous != review_record:
                raise ProtocolError("PRODUCT_REVIEW_DRIFT", "Stored review differs from the approved product")
        self.registry.validate("product-review", review_record)
        atomic_yaml(review_path, review_record, create_once=True)
        review_ref = artifact_ref("product-review", review_record, review_path)

        # build delivery manifest (moved from check in A1.3)
        lock, lock_ref, scene, preview_receipt = self._locked_render_inputs(
            request, attestation_key=attestation_key, browser=browser
        )
        render_service = FormalMapRenderService(
            path_guard=self.path_guard, work_root=self.work_root,
            attestation_key=attestation_key, browser=browser, registry=self.registry,
            project_root=self.project_root, context=ExecutionContext.from_generate_request(request),
            renderer_id=scene["renderer_id"],
        )
        render_service.validate_environment(lock, preview_receipt)
        render_service.validate_scene(scene, lock["execution"])
        evidence_ref = self.state_store.find_output_ref("formal-render-evidence")
        evidence = self._load_ref(evidence_ref, "formal-render-evidence")
        attempt_number = int(evidence["attempt_ref"]["id"].rsplit("-", 1)[1])
        existing = render_service.load_existing(
            request=request, lock=lock, lock_ref=lock_ref, scene=scene,
            attempt_number=attempt_number, verify_outputs=True,
        )
        if existing is None or existing["attempt"]["status"] != "succeeded":
            raise ProtocolError("FINAL_CHECK_RENDER_INVALID", evidence["evidence_id"])

        checker = FinalMapCheckService(
            path_guard=self.path_guard, project_root=self.project_root,
            work_root=self.work_root, registry=self.registry,
            execution_context=ExecutionContext.from_generate_request(request),
        )
        recomputed = checker.inspect(
            lock=lock, lock_ref=lock_ref, scene=scene,
            attempt=existing["attempt"], attempt_path=existing["attempt_path"],
            receipt=existing["receipt"], evidence=existing["evidence"], evidence_path=existing["evidence_path"])
        if recomputed != report:
            raise ProtocolError("FINAL_CHECK_REPORT_DRIFT", report["report_id"])
        manifest = checker.build_manifest(
            request=request, lock=lock, lock_ref=lock_ref,
            attempt=existing["attempt"], attempt_path=existing["attempt_path"],
            report=report, report_path=self.path_guard.resolve(report_ref["uri"], must_exist=True),
            recipient_id=recipient_id, recipient_type=recipient_type,
            destination=destination, idempotency_key=idempotency_key, review_ref=review_ref,
        )
        manifest_path = checker.write_manifest(manifest)

        state, step_receipt = self.state_store.complete_step(
            state, status="waiting_approval",
            prerequisites={"lock": lock, "attempt": existing["attempt"],
                           "evidence": existing["evidence"], "report": report,
                           "review_approval": approval_value},
            output_refs=[review_ref, artifact_ref("delivery-manifest", manifest, manifest_path)],
            tool_versions={"production-review": TOOL_VERSION}, next_step="deliver",
        )
        return {
            "state": state.to_dict(), "receipt": step_receipt.to_dict(),
            "validation_report": report, "delivery_manifest": manifest,
            "g3": checker.g3_context(manifest), "idempotent_replay": False,
        }

    @serialized_workflow_step
    def deliver(
        self,
        request_path: str | Path,
        approval_path: str | Path,
        *,
        approval_key: bytes,
        failure_hook: Callable[[str], None] | None = None,
    ) -> dict[str, Any]:
        request = self._read_request(request_path)
        state = self.state_store.load()
        if sha256_digest(request) != state.input_fingerprint:
            raise ProtocolError("JOB_INPUT_DRIFT", state.run_id)
        stored = self._load("request/generate-request.yaml", "generate-request")
        if stored != request:
            raise ProtocolError("JOB_INPUT_DRIFT", state.run_id)
        if state.step != "deliver" or state.status not in {"waiting_approval", "succeeded"}:
            raise ProtocolError(
                "WORKFLOW_STEP_INVALID",
                f"expected=waiting_approval/deliver; actual={state.status}/{state.step}",
            )
        manifest_ref = self.state_store.find_output_ref("delivery-manifest")
        report_ref = self.state_store.find_output_ref("final-validation-report")
        manifest = self._load_ref(manifest_ref, "delivery-manifest")
        report = self._load_ref(report_ref, "validation-report")
        service = MapDeliveryService(
            path_guard=self.path_guard, project_root=self.project_root,
            work_root=self.work_root, registry=self.registry,
            nonce_store=self._nonce_store,
            trusted_subject_id=request["subject"]["approver_subject_id"],
            trusted_tenant_id=ExecutionContext.from_generate_request(request).tenant_id,
            trusted_scope=request.get("scope"),
            trusted_environment=request["environment"],
        )
        delivered = service.deliver(
            request=request, manifest=manifest, manifest_ref=manifest_ref, report=report,
            approval_path=approval_path, approval_key=approval_key,
            failure_hook=failure_hook,
        )
        transaction = delivered["transaction"]
        delivery_receipt = delivered["receipt"]
        transaction_ref = artifact_ref(
            transaction["transaction_id"], transaction, delivered["transaction_path"]
        )
        receipt_ref = artifact_ref(
            delivery_receipt["receipt_id"], delivery_receipt, delivered["receipt_path"]
        )
        if state.status == "succeeded":
            step_receipt = next(
                (
                    item["receipt"] for item in reversed(self.state_store.receipts())
                    if item["receipt"]["step"] == "deliver"
                    and item["receipt"]["status"] == "succeeded"
                ),
                None,
            )
            if step_receipt is None:
                raise ProtocolError("DELIVERY_STEP_RECEIPT_MISSING", state.run_id)
            return {
                "state": state.to_dict(), "receipt": step_receipt,
                "delivery_transaction": transaction, "delivery_receipt": delivery_receipt,
                "idempotent_replay": True,
            }
        if failure_hook:
            failure_hook("before-step-complete")
        state, step_receipt = self.state_store.complete_step(
            state, status="succeeded",
            prerequisites={"manifest": manifest, "approval": delivered["approval"]},
            output_refs=[transaction_ref, receipt_ref],
            tool_versions={"atomic-map-delivery": TOOL_VERSION},
        )
        return {
            "state": state.to_dict(), "receipt": step_receipt.to_dict(),
            "delivery_transaction": transaction, "delivery_receipt": delivery_receipt,
            "idempotent_replay": bool(delivered["idempotent_replay"]),
        }

    # ------------------------------------------------------------------
    # design revision (A1.2)
    # ------------------------------------------------------------------

    def _revision_documents(self, request_path, proposal_path):
        """Construct one exact G1 object; previewing and applying use the same code."""
        request = self._read_request(request_path)
        state = self.state_store.load()
        if sha256_digest(request) != state.input_fingerprint:
            raise ProtocolError("JOB_INPUT_DRIFT", state.run_id)
        if (state.step not in {"compile", "preview", "freeze"}
                or (self.work_root / "locks" / f"lock-{state.run_id}" / "map-spec-lock.yaml").exists()):
            raise ProtocolError("REVISION_NOT_ALLOWED", "Frozen designs require a new run and new approvals")
        if self._load("request/generate-request.yaml", "generate-request") != request:
            raise ProtocolError("JOB_INPUT_DRIFT", state.run_id)
        proposal = load_document(self._resolve_project_path(proposal_path, must_exist=True))
        self.registry.validate("design-revision-proposal", proposal)
        brief = self._load("brief/map-brief.yaml", "map-brief")
        if proposal["run_id"] != state.run_id or proposal["parent_revision"] != brief["revision"]:
            raise ProtocolError("REVISION_PARENT_DRIFT", "Proposal must identify the current design")
        revised = deepcopy(request)
        for key, change in proposal["changes"].items():
            if key == "panel_designs":
                panels = revised.get("vector_panels", revised.get("panels", []))
                if set(change["new_value"]) - {p["id"] for p in panels}:
                    raise ProtocolError("THEMATIC_VIEW_UNKNOWN", "Proposal refers to an unknown view")
                for panel in panels:
                    if panel["id"] in change["new_value"]:
                        panel["design"] = deepcopy(change["new_value"][panel["id"]])
            else:
                revised["revised_cartography" if key == "cartography" else key] = deepcopy(change["new_value"])
        self.registry.validate("generate-request", revised)
        self._validate_runtime_request(revised)
        result = deepcopy(brief)
        result.update(revision=brief["revision"] + 1,
                      brief_id=f"brief-{request['run_id']}-r{brief['revision'] + 1}",
                      request_ref=artifact_ref("generate-request", revised),
                      revision_proposal_ref=artifact_ref("design-revision-proposal", proposal))
        # A different thematic field changes the business binding shown to the approver.
        if revised["geometry"] == "vector":
            for source in result["source_plan"]:
                sid = source["source_ref"]["id"]
                fields = set()
                for panel in revised["vector_panels"]:
                    if panel["source_id"] != sid:
                        continue
                    design = panel["design"]
                    if design["field"] is not None:
                        fields.add(design["field"])
                    if design.get("normalization"):
                        fields.add(design["normalization"]["denominator_field"])
                source["field_bindings"] = [{"semantic_role": "thematic-value", "source_field": f}
                                            for f in sorted(fields)]
        self.registry.validate("map-brief", result)
        return request, state, proposal, brief, revised, result

    @serialized_workflow_step
    def revision_brief(self, request_path: str | Path, proposal_path: str | Path) -> dict[str, Any]:
        *_, brief = self._revision_documents(request_path, proposal_path)
        return {"brief": brief, "approval_object_digest": sha256_digest(brief),
                "action": "approve-map-brief", "object_type": "map-brief"}

    @serialized_workflow_step
    def revise(self, request_path: str | Path, proposal_path: str | Path,
               approval_path: str | Path, *, approval_key: bytes) -> dict[str, Any]:
        """Switch to an immutable design version through the state transition journal.

        G1 approves the complete revised MapBrief, not the proposal. All artifacts
        of the former design remain at their original immutable paths. A crash
        before transition commit resumes against the same staged revision.
        """
        request, state, proposal, brief, revised, revised_brief = self._revision_documents(request_path, proposal_path)
        revision = revised_brief["revision"]
        root = self.path_guard.resolve(self.work_root / "revisions" / f"r{revision}")
        proposal_target = root / "proposal.yaml"
        if proposal_target.exists() and load_document(proposal_target) != proposal:
            raise ProtocolError("REVISION_STAGING_CONFLICT", "Resume the already staged revision")
        budget = self._budget_store.load()
        # Reconcile an interrupted save without charging the same revision twice.
        expected_used = revision - 1
        if budget.revisions == expected_used - 1:
            budget.consume("revisions")
        elif budget.revisions != expected_used or not proposal_target.exists():
            raise ProtocolError("REVISION_BUDGET_DRIFT", "Budget does not match revision history")
        approval_value = load_document(self._resolve_project_path(approval_path, must_exist=True))
        self.registry.validate("approval-receipt", approval_value)
        self._gate_coordinator(approval_key, request).require(
            "G1", ApprovalReceipt.from_dict(approval_value), sha256_digest(revised_brief), run_id=state.run_id)
        request_target = root / "request/generate-request.yaml"
        brief_target = root / "brief/map-brief.yaml"
        atomic_yaml(proposal_target, proposal, create_once=True)
        atomic_yaml(request_target, revised, create_once=True)
        atomic_yaml(brief_target, revised_brief, create_once=True)
        # W1-M2: record the incremental invalidation analysis beside the staged
        # revision. reusable_bundle_ref points at the previous revision's bundle;
        # the digest gate re-verifies equivalence at compile time. The ref is only
        # recorded when a bundle already exists (revising before a first compile
        # stays valid without one).
        from .revision_graph import bundle_input_digest, compute_invalidation
        analysis = compute_invalidation(proposal["changes"])
        graph = {"schema_version": 1, "revision": revision, "run_id": request["run_id"],
                 "proposal_id": proposal["proposal_id"], **analysis,
                 "bundle_input_digest": bundle_input_digest(revised),
                 "created_at": utc_now()}
        previous_bundle_path = self.path_guard.resolve(self._design_path("data/prepared-data-bundle.yaml"))
        if previous_bundle_path.is_file():
            graph["reusable_bundle_ref"] = artifact_ref(
                "prepared-data-bundle", load_document(previous_bundle_path), previous_bundle_path)
        graph_target = root / "dependency-graph.yaml"
        if graph_target.exists():
            # Resume an interrupted revise: keep the staged timestamp, refuse drift
            # (same recovery pattern as the product-review record).
            previous_graph = load_document(graph_target)
            graph["created_at"] = previous_graph["created_at"]
            if previous_graph != graph:
                raise ProtocolError("DEPENDENCY_GRAPH_CONFLICT", "Staged graph differs from the interrupted revision")
        atomic_yaml(graph_target, graph, create_once=True)
        self._budget_store.save(budget)
        state, receipt = self.state_store.complete_step(
            state, status="succeeded", receipt_step="revise",
            prerequisites={"request": request, "brief": brief, "proposal": proposal,
                           "approval": approval_value, "dependency_graph": graph},
            output_refs=[artifact_ref("generate-request", revised, request_target),
                         artifact_ref("map-brief", revised_brief, brief_target),
                         artifact_ref("design-revision-proposal", proposal, proposal_target),
                         artifact_ref("revision-dependency-graph", graph, graph_target)],
            tool_versions={"design-revision": TOOL_VERSION}, next_step="compile",
            next_input_fingerprint=sha256_digest(revised))
        return {"state": state.to_dict(), "receipt": receipt.to_dict(), "revision": revision,
                "request_path": str(request_target), "brief": revised_brief,
                "proposal_id": proposal["proposal_id"], "changed_fields": sorted(proposal["changes"])}

    def _snapshot_approval(self, value: dict[str, Any]) -> Path:
        """Keep audit evidence independent of a caller's mutable approval file."""
        digest = sha256_digest(value)
        path = self.path_guard.resolve(self.work_root / "approvals" / (digest[7:] + ".yaml"))
        atomic_yaml(path, value, create_once=True)
        return path

    def _reusable_bundle(self, request: dict[str, Any]) -> dict[str, Any] | None:
        # W1-M2: reuse the prepared bundle when the revision dependency graph
        # proves the data evidence is not invalidated and the bundle-input digest
        # matches. Content addressing makes the shortcut equivalent: equal input
        # digest => deterministic prepare => byte-equal bundle. The reused bundle
        # keeps referencing the previous revision's frozen data evidence, which is
        # exactly the "unchanged evidence stays referenced" semantics.
        graph_path = self.path_guard.resolve(self._design_path("dependency-graph.yaml"))
        if not graph_path.is_file():
            return None
        graph = load_document(graph_path)
        self.registry.validate("revision-dependency-graph", graph)
        if not graph.get("data_evidence_reusable"):
            return None
        reference = graph.get("reusable_bundle_ref")
        if not reference:
            return None
        from .revision_graph import bundle_input_digest
        if bundle_input_digest(request) != graph["bundle_input_digest"]:
            return None
        source = self.path_guard.resolve(reference["uri"], must_exist=True)
        document = load_document(source)
        self.registry.validate("prepared-data-bundle", document)
        if sha256_digest(document) != reference["digest"]:
            raise ProtocolError("REUSABLE_BUNDLE_DRIFT", reference["id"])
        return document

    def _design_review_ref(self, request, candidate, evidence, coordinator,
                           design_review_approval_path):
        # Bind a design-review attestation to the exact candidate/preview being frozen.
        # Symmetric to the product-review record: the first freeze consumes the approval
        # nonce and creates the immutable record; a replay loads it without re-consuming.
        # The record is bound to candidate and preview digests, never a writable boolean.
        if design_review_approval_path is None:
            return None
        approval_value = load_document(
            self._resolve_project_path(design_review_approval_path, must_exist=True))
        if not isinstance(approval_value, dict):
            raise ProtocolError("DESIGN_REVIEW_APPROVAL_REQUIRED", "Approval receipt must be an object")
        self.registry.validate("approval-receipt", approval_value)
        review_id = "design-review-" + sha256_digest(approval_value)[7:31]
        review_path = self.path_guard.resolve(self.work_root / "design-reviews" / (review_id + ".yaml"))
        if review_path.exists():
            record = load_document(review_path)
            self.registry.validate("design-review-record", record)
        else:
            coordinator.require_attestation(
                "approve-design-review", "resolved-map",
                ApprovalReceipt.from_dict(approval_value), sha256_digest(candidate),
                run_id=request["run_id"])
            record = {"schema_version": 1, "review_id": review_id,
                      "run_id": request["run_id"], "project_id": request["project_id"],
                      "candidate_ref": artifact_ref("resolved-map", candidate),
                      "preview_evidence_ref": artifact_ref("map-preview-evidence", evidence),
                      "approval": approval_value, "reviewed_at": utc_now()}
            self.registry.validate("design-review-record", record)
            atomic_yaml(review_path, record, create_once=True)
        if (record["candidate_ref"]["digest"] != sha256_digest(candidate)
                or record["preview_evidence_ref"]["digest"] != sha256_digest(evidence)
                or record["run_id"] != request["run_id"]
                or record["project_id"] != request["project_id"]):
            raise ProtocolError("DESIGN_REVIEW_DRIFT", "Design review is not bound to this exact candidate")
        return artifact_ref("design-review-record", record, review_path)

    def _design_path(self, relative: str) -> Path:
        """Resolve the active immutable design from committed state, never a mutable alias."""
        state = self.state_store.load()
        for item in reversed(self.state_store.receipts()):
            for ref in item["receipt"]["output_refs"]:
                if ref["id"] == "generate-request" and ref["digest"] == state.input_fingerprint:
                    request_path = self.path_guard.resolve(ref["uri"], must_exist=True)
                    if sha256_digest(load_document(request_path)) != ref["digest"]:
                        raise ProtocolError("JOB_INPUT_DRIFT", state.run_id)
                    return self.path_guard.resolve(request_path.parent.parent / relative)
        # During intake there is not yet a committed request receipt.
        if state.step == "intake":
            return self.path_guard.resolve(self.work_root / relative)
        raise ProtocolError("WORKFLOW_RECEIPT_MISSING", "active generate-request")

    @serialized_workflow_step
    def delivery_status(self, idempotency_key: str) -> dict[str, Any]:
        repository = MapDeliveryService(
            path_guard=self.path_guard, project_root=self.project_root,
            work_root=self.work_root, registry=self.registry,
        ).repository
        result = repository.lookup(idempotency_key)
        if result is None:
            raise ProtocolError("DELIVERY_TRANSACTION_NOT_FOUND", idempotency_key)
        return result

    def _load_ref(self, ref: dict[str, str], schema: str) -> dict[str, Any]:
        path = self.path_guard.resolve(ref["uri"], must_exist=True)
        value = load_document(path)
        if not isinstance(value, dict):
            raise ProtocolError("WORKFLOW_ARTIFACT_INVALID", ref["id"])
        self.registry.validate(schema, value)
        if sha256_digest(value) != ref["digest"]:
            raise ProtocolError("WORKFLOW_ARTIFACT_DRIFT", ref["id"])
        return value

    def _validate_check_invocation(
        self, manifest: dict[str, Any], *, recipient_id: str, recipient_type: str,
        destination: str | Path, idempotency_key: str,
    ) -> None:
        checker = FinalMapCheckService(
            path_guard=self.path_guard, project_root=self.project_root,
            work_root=self.work_root, registry=self.registry,
        )
        expected = {
            "recipient": {"recipient_id": recipient_id, "recipient_type": recipient_type},
            "destination": {"kind": "local-allowed-root", "relative_path": checker.normalize_destination(destination)},
            "idempotency_key": idempotency_key,
        }
        if any(manifest[key] != value for key, value in expected.items()):
            raise ProtocolError("DELIVERY_MANIFEST_INPUT_MISMATCH", manifest["manifest_id"])
    def _locked_render_inputs(self, request: dict[str, Any], *, attestation_key: bytes,
                              browser: str | Path | None) -> tuple[dict[str, Any], dict[str, str], dict[str, Any], dict[str, Any]]:
        try:
            lock_path = self.path_guard.resolve(
                self.work_root / "locks" / f"lock-{request['run_id']}" / "map-spec-lock.yaml",
                must_exist=True,
            )
            lock = load_document(lock_path)
            if not isinstance(lock, dict):
                raise ProtocolError("MAP_SPEC_LOCK_INVALID", str(lock_path))
            self.registry.validate("map-spec-lock", lock)
            lock_ref = self.state_store.find_output_ref("map-spec-lock")
            if sha256_digest(lock) != lock_ref["digest"]:
                raise ProtocolError("MAP_SPEC_LOCK_DIGEST_MISMATCH", lock["lock_id"])
            if self.path_guard.resolve(lock_ref["uri"], must_exist=True) != lock_path:
                raise ProtocolError("MAP_SPEC_LOCK_REFERENCE_MISMATCH", lock["lock_id"])
            if lock["project_id"] != request["project_id"] or lock["run_id"] != request["run_id"]:
                raise ProtocolError("MAP_SPEC_LOCK_SCOPE_MISMATCH", lock["lock_id"])
            if lock["execution_digest"] != sha256_digest(lock["execution"]):
                raise ProtocolError("LOCK_EXECUTION_DIGEST_MISMATCH", lock["lock_id"])
            for approval_uri in lock["approvals"].values():
                path = self.path_guard.resolve(approval_uri, must_exist=True)
                approval = load_document(path)
                self.registry.validate("approval-receipt", approval)
                expected_path = self.path_guard.resolve(
                    self.work_root / "approvals" / (sha256_digest(approval)[7:] + ".yaml"))
                if path != expected_path:
                    raise ProtocolError("MAP_SPEC_LOCK_APPROVAL_DRIFT", "Frozen approval evidence changed")

            candidate = self._load("candidates/resolved-map.yaml", "resolved-map")
            scene = self._load("candidates/render-scene.yaml", "render-scene")
            preflight = self._load("candidates/preflight-report.yaml", "validation-report")
            preview_receipt = self._load("candidates/render-receipt.yaml", "render-receipt")
            evidence = self._load("candidates/preview-evidence.yaml", "map-preview-evidence")
            installation = self._load("templates/installed-template.yaml")
            if sha256_digest(candidate) != lock["candidate_digest"] or lock["candidate_ref"]["digest"] != lock["candidate_digest"]:
                raise ProtocolError("MAP_SPEC_LOCK_CANDIDATE_DRIFT", lock["lock_id"])
            if candidate["execution"] != lock["execution"] or candidate["execution_digest"] != lock["execution_digest"]:
                raise ProtocolError("MAP_SPEC_LOCK_EXECUTION_DRIFT", lock["lock_id"])
            if sha256_digest(scene) != lock["execution"]["render_scene_ref"]["digest"]:
                raise ProtocolError("MAP_SPEC_LOCK_SCENE_DRIFT", lock["lock_id"])
            if sha256_digest(preflight) != lock["evidence"]["preflight_ref"]["digest"]:
                raise ProtocolError("MAP_SPEC_LOCK_PREFLIGHT_DRIFT", lock["lock_id"])
            if evidence["evidence_digest"] != lock["preview_evidence_digest"] or evidence["evidence_digest"] != lock["evidence"]["preview_ref"]["digest"]:
                raise ProtocolError("MAP_SPEC_LOCK_PREVIEW_DRIFT", lock["lock_id"])
            if sha256_digest(preview_receipt) != lock["render_receipt_ref"]["digest"]:
                raise ProtocolError("MAP_SPEC_LOCK_PREVIEW_RECEIPT_DRIFT", lock["lock_id"])
            self._verify_installed_template(installation)
            contracts = MapCandidateCompiler(self.path_guard, self.registry).load_contracts(installation)
            self._verify_candidate_inputs(candidate, scene, contracts, preflight)
            preview_service = MapPreviewService(
                path_guard=self.path_guard,
                output_root=self.path_guard.resolve(self._design_path("previews"), must_exist=True),
                attestation_key=attestation_key, browser=browser, registry=self.registry,
                project_root=self.project_root, context=ExecutionContext.from_generate_request(request),
            )
            preview_service.validate_persisted(candidate, scene, preview_receipt)
            preview_service.validate_evidence(evidence, candidate, scene, preview_receipt, self.registry)
            MapSpecLockCompiler(self.registry).verify_existing(
                lock, request, candidate, evidence, preview_receipt, preflight,
                brief_approval_ref=lock["approvals"]["brief_ref"],
                freeze_approval_ref=lock["approvals"]["freeze_ref"],
            )
            if is_static(scene["renderer_id"]):
                self._verify_page_inputs(lock["execution"], scene, request)
                return lock, lock_ref, scene, preview_receipt
            refs = [
                *lock["execution"].get("dataset_refs", []),
                *lock["execution"].get("prepared_data_refs", []),
                *lock["execution"].get("resolved_assets", []),
                *(item["ref"] for item in scene["resources"]),
            ]
            for ref in refs:
                uri = ref.get("uri")
                if uri:
                    path = self.path_guard.resolve(uri, must_exist=True)
                    if not path.is_file() or file_digest(path) != ref["digest"]:
                        raise ProtocolError("MAP_SPEC_LOCK_RESOURCE_DRIFT", ref["id"])
            font_path = self.path_guard.resolve(request["font"]["path"], base_root=self.project_root, must_exist=True)
            font_refs = [item for item in lock["execution"].get("resolved_assets", []) if item["id"] == "map-font"]
            if len(font_refs) != 1 or file_digest(font_path) != font_refs[0]["digest"]:
                raise ProtocolError("MAP_SPEC_LOCK_FONT_DRIFT", "map-font")
            return lock, lock_ref, scene, preview_receipt
        except CartoError as exc:
            normalized = exc if exc.code in {
                "LOCK_INPUT_DRIFT", "RENDER_ENVIRONMENT_DRIFT", "ENCODING_SEMANTICS_INVALID"
            } else ProtocolError("LOCK_INPUT_DRIFT", f"{exc.code}: {exc.message}")
            if "lock" in locals() and "lock_ref" in locals() and "scene" in locals():
                normalized.render_context = (lock, lock_ref, scene)
            if normalized is exc:
                raise
            raise normalized from exc

    @serialized_workflow_step
    def status(self) -> dict[str, Any]:
        state = self.state_store.load()
        return {
            "state": state.to_dict(),
            "recovery": self.state_store.recovery_status(),
            "receipt_count": len(self.state_store.receipts()),
        }

    @serialized_workflow_step
    def retry(self) -> dict[str, Any]:
        state = self.state_store.load()
        if state.step == "check" and state.status == "failed":
            raise ProtocolError("JOB_RETRY_NOT_ALLOWED", "final check failures require a new render attempt or lock")
        if state.step == "render" and state.status == "failed":
            attempt_id = f"render-attempt-{state.run_id}-{state.attempt}"
            attempt_path = self.work_root / "render-attempts" / f"{attempt_id}.yaml"
            if not attempt_path.exists():
                raise ProtocolError("JOB_RETRY_NOT_ALLOWED", "render failure has no retryable attempt")
            attempt = self._load(f"render-attempts/{attempt_id}.yaml", "render-attempt")
            if not attempt["retryable"]:
                raise ProtocolError("JOB_RETRY_NOT_ALLOWED", f"render attempt {attempt_id} is not retryable")
        return {"state": self.state_store.retry(state).to_dict()}

    @serialized_workflow_step
    def receipts(self) -> dict[str, Any]:
        return {"receipts": self.state_store.receipts()}

    def _read_request(self, request_path: str | Path) -> dict[str, Any]:
        value = load_document(self._resolve_project_path(request_path, must_exist=True))
        if not isinstance(value, dict):
            raise ProtocolError("GENERATE_REQUEST_INVALID", "request must be an object")
        self.registry.validate("generate-request", value)
        ScenarioRegistry(self.registry).for_generate(value)
        return value

    def _resume(self, request_path: str | Path, expected_step: str) -> tuple[dict[str, Any], Any]:
        request = self._read_request(request_path)
        state = self.state_store.load()
        if sha256_digest(request) != state.input_fingerprint:
            raise ProtocolError("JOB_INPUT_DRIFT", state.run_id)
        if state.step != expected_step:
            raise ProtocolError("WORKFLOW_STEP_INVALID", f"expected={expected_step}; actual={state.step}")
        stored = self._load("request/generate-request.yaml", "generate-request")
        if stored != request:
            raise ProtocolError("JOB_INPUT_DRIFT", state.run_id)
        return request, state

    def _validate_runtime_request(self, request: dict[str, Any]) -> None:
        ScenarioRegistry(self.registry).for_generate(request)
        missing = sorted(self.REQUIRED_REQUEST_FIELDS - set(request))
        if missing:
            raise ProtocolError("GENERATE_REQUEST_INCOMPLETE", ",".join(missing))
        if request["template"]["kind"] != "map-scenario":
            raise ProtocolError("GENERATE_TEMPLATE_KIND_UNSUPPORTED", request["template"]["kind"])
        if request["scope"] != f"project:{request['project_id']}":
            raise SecurityError("PROJECT_SCOPE_DENIED", request["scope"])
        subject = request["subject"]
        if not subject.get("approver_subject_id"):
            raise ProtocolError("APPROVER_REQUIRED", "subject.approver_subject_id")
        if subject["approver_subject_id"] == subject["subject_id"]:
            raise SecurityError("APPROVER_NOT_INDEPENDENT", "The operator cannot approve their own map")
        required_capabilities = {"read", "render-preview"}
        if request.get("geometry") == "raster" or any(p.get("design", {}).get("kind") == "choropleth" for p in request.get("vector_panels", [])):
            required_capabilities.add("classify")
        if any(s.get("attribute_join") for s in request.get("vector_sources", [])):
            required_capabilities.add("join")
        if any(item.get("join", {}).get("required") for item in request.get("source_bindings", [])):
            required_capabilities.add("join")
        missing_capabilities = required_capabilities - set(request["allowed_capabilities"])
        if missing_capabilities:
            raise SecurityError("CAPABILITY_NOT_AUTHORIZED", ",".join(sorted(missing_capabilities)))
        if set(request["requested_outputs"]) - {"svg", "png", "pdf"}:
            raise ProtocolError("RENDER_TARGET_UNSUPPORTED", str(request["requested_outputs"]))
        def identity(ref: dict[str, Any]) -> tuple[str, str, str]:
            return ref["id"], ref["version"], ref["digest"]
        if "vector_sources" in request:
            from ..compiler.page_bindings import index_by
            sources = index_by(request["vector_sources"], "source_id")
            roots = index_by(request["sources"], "id")
            if request.get("source_bindings") or set(sources) != set(roots) or any(roots[sid]["version"] != "1.0.0" or roots[sid]["digest"] != sha256_digest(source) for sid, source in sources.items()):
                raise ProtocolError("GENERATE_SOURCE_REF_MISMATCH", "Vector source declarations must match root references")
            return
        if not request.get("source_bindings"):
            raise ProtocolError("GENERATE_REQUEST_INCOMPLETE", "source_bindings")
        if {identity(item) for item in request["sources"]} != {identity(item["source_ref"]) for item in request["source_bindings"]}:
            raise ProtocolError("SOURCE_REFERENCE_SET_MISMATCH", request["request_id"])

    def _intent(self, request: dict[str, Any]) -> dict[str, Any]:
        value = ScenarioRegistry(self.registry).generate_intent(request)
        self.registry.validate("map-intent", value)
        return value

    def _repository(self) -> TemplateRepository:
        if self.repository_root is None or not self.repository_scope:
            raise ProtocolError("TEMPLATE_REPOSITORY_REQUIRED", "repository root and scope are required")
        return TemplateRepository(path_guard=self.path_guard, root=self.repository_root,
                                  repository_scope=self.repository_scope, registry=self.registry)

    def _verify_installed_template(self, installation: dict[str, Any]) -> None:
        template_ref = installation.get("template_ref", {})
        required = ("kind", "id", "version", "digest")
        if not installation.get("namespace") or any(not template_ref.get(key) for key in required):
            raise ProtocolError("TEMPLATE_INSTALL_IDENTITY_MISMATCH", installation.get("installation_id", "unknown"))
        entry = self._repository().discover(
            namespace=installation["namespace"], kind=template_ref["kind"],
            template_id=template_ref["id"], version=template_ref["version"],
        )
        if entry["status"] != "published":
            raise ProtocolError("TEMPLATE_NOT_PUBLISHED", template_ref["id"])
        if entry["digest"] != template_ref["digest"]:
            raise ProtocolError("TEMPLATE_INSTALL_PACKAGE_DRIFT", template_ref["id"])
        if entry["manifest_digest"] != installation.get("manifest_digest"):
            raise ProtocolError("TEMPLATE_INSTALL_MANIFEST_DRIFT", template_ref["id"])

    def _candidate_compiler(self, request: dict[str, Any]) -> MapCandidateCompiler:
        """Composition root: inject the execution-layer ports the compiler may not import."""
        from .material_evidence import verify_material_facts
        from .preparation_bundle import BundlePreparer
        from .preparation_services import preparation_service
        return MapCandidateCompiler(self.path_guard, self.registry, project_root=self.project_root,
            context=ExecutionContext.from_generate_request(request), preparations=preparation_service,
            material_facts=verify_material_facts, bundles=BundlePreparer)

    def _verify_candidate_inputs(self, candidate: dict[str, Any], scene: dict[str, Any],
                                 contracts: dict[str, Any], preflight: dict[str, Any]) -> None:
        registry = ScenarioRegistry(self.registry)
        registry.for_execution(candidate["execution"]).require_scene(scene)
        request = self._load("request/generate-request.yaml", "generate-request")
        intent = self._load("intent/map-intent.yaml", "map-intent")
        registry.require_request_intent(request, intent)
        MapCandidateCompiler.require_execution_intent(candidate["execution"], intent)
        compiler = self._candidate_compiler(request)
        current = compiler.check_candidate(request, candidate, scene, contracts)
        if current != preflight or current["status"] != "passed":
            raise ProtocolError("CANDIDATE_PREFLIGHT_DRIFT", "Quality gates or their evidence changed; recompile before G2")
        if is_static(scene["renderer_id"]):
            return
        for ref in [*candidate["execution"]["dataset_refs"], *candidate["execution"].get("prepared_data_refs", []),
                    *candidate["execution"].get("resolved_assets", [])]:
            uri = ref.get("uri")
            if uri and file_digest(self.path_guard.resolve(uri, must_exist=True)) != ref["digest"]:
                raise ProtocolError("CANDIDATE_RESOURCE_DRIFT", ref["id"])

    def _verify_page_inputs(self, execution, scene, request):
        if scene["renderer_id"] == VECTOR_PAGE.renderer_id:
            from ..compiler.vector_scene import VectorSceneCompiler
            from .vector_preparation import VectorPreparationService
            service = VectorPreparationService(project_root=self.project_root,
                allowed_roots=list(self.path_guard.allowed_roots), registry=self.registry)
            VectorSceneCompiler(service).validate_generation(scene, execution, request, ExecutionContext.from_generate_request(request))
            return
        from ..compiler.raster_scene import RasterSceneCompiler
        from .preparation_bundle import BundlePreparer
        from .raster_preparation import RasterPreparationService
        preparation = RasterPreparationService(project_root=self.project_root,
            allowed_roots=list(self.path_guard.allowed_roots), registry=self.registry)
        RasterSceneCompiler(preparation, BundlePreparer).validate_generation(scene, execution, request, ExecutionContext.from_generate_request(request))

    def _resolve_project_path(self, value: str | Path, *, must_exist: bool = False) -> Path:
        return self.path_guard.resolve(value, base_root=self.project_root, must_exist=must_exist)

    def _load(self, relative: str, schema: str | None = None) -> dict[str, Any]:
        design_artifact = relative.startswith(("request/", "brief/", "plan/", "data/", "candidates/", "previews/"))
        path = self.path_guard.resolve(self._design_path(relative) if design_artifact else self.work_root / relative,
                                       must_exist=True)
        value = load_document(path)
        if not isinstance(value, dict):
            raise ProtocolError("WORKFLOW_ARTIFACT_INVALID", relative)
        if schema:
            self.registry.validate(schema, value)
        return value
