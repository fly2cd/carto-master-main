from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from ..canonical import sha256_digest
from ..compiler.map_candidate import MapCandidateCompiler
from ..compiler.map_lock import MapSpecLockCompiler
from ..errors import CartoError, ProtocolError, SecurityError
from ..repository.template_installer import ProjectTemplateInstaller
from ..repository.template_repository import TemplateRepository
from ..schema_registry import SchemaRegistry, load_document
from ..security.approval import ApprovalReceipt, SqliteNonceStore
from ..security.paths import PathGuard
from .approvals import ApprovalGateCoordinator
from .map_data_preparation import FloodDataPreparer, artifact_ref, atomic_json, atomic_yaml, file_digest, utc_now
from .map_delivery import MapDeliveryService
from .map_final_check import FinalMapCheckService
from .map_planning import MapPlanner
from .map_preview import MapPreviewService, freeze_object_digest
from .map_render import FormalMapRenderService, is_transient_render_error
from .models import ExecutionContext
from .state_machine import WorkflowStateStore, serialized_workflow_step

TOOL_VERSION = "0.3.3"


class MapGenerationWorkflow:
    """Map generation through final checks and the pre-G3 delivery safe stop."""

    REQUIRED_REQUEST_FIELDS = {
        "run_id", "audience", "scope", "environment", "requested_at", "template",
        "allowed_capabilities", "source_bindings", "font",
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

    @serialized_workflow_step
    def intake(self, request_path: str | Path) -> dict[str, Any]:
        request = self._read_request(request_path)
        self._validate_runtime_request(request)
        state = self.state_store.initialize(request["run_id"], request, step="intake")
        intent = self._intent(request)
        request_target = self.path_guard.resolve(self.work_root / "request/generate-request.yaml")
        intent_target = self.path_guard.resolve(self.work_root / "intent/map-intent.yaml")
        atomic_yaml(request_target, request)
        atomic_yaml(intent_target, intent)
        state, receipt = self.state_store.complete_step(
            state, status="succeeded", prerequisites={},
            output_refs=[self._ref("generate-request", request, request_target),
                         self._ref("map-intent", intent, intent_target)],
            tool_versions={"map-intake": TOOL_VERSION}, next_step="brief",
        )
        return {"state": state.to_dict(), "receipt": receipt.to_dict(), "intent": intent}

    @serialized_workflow_step
    def brief(self, request_path: str | Path) -> dict[str, Any]:
        request, state = self._resume(request_path, "brief")
        intent = self._load("intent/map-intent.yaml", "map-intent")
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
        for binding in sorted(request["source_bindings"], key=lambda item: item["role"]):
            operations = [item for item in ("read", "filter", "join", "classify", "reproject")
                          if item in request["allowed_capabilities"]]
            source_plan.append({"role": binding["role"], "source_ref": binding["source_ref"],
                                "allowed_operations": operations, "path_digest": file_digest(
                                    self.path_guard.resolve(binding["path"], base_root=self.project_root, must_exist=True)),
                                "field_bindings": [{"semantic_role": item["semantic_role"],
                                                    "source_field": item["source_field"]}
                                                   for item in binding["field_bindings"]]})
        brief = {
            "schema_version": 1, "brief_id": f"brief-{request['run_id']}", "revision": 1,
            "intent_ref": artifact_ref("map-intent", intent), "purpose": request["goal"],
            "audience": request["audience"], "source_plan": source_plan,
            "targets": sorted(request["requested_outputs"]), "template_candidates": [template_ref],
            "delegation": {"allow_data_agent": False, "max_tool_calls": 0}, "approval_required": True,
            "project_id": request["project_id"], "business_scene": "emergency_mapping",
            "scope": request["scope"], "environment": request["environment"],
            "allowed_capabilities": sorted(request["allowed_capabilities"]),
        }
        self.registry.validate("map-brief", brief)
        target = self.path_guard.resolve(self.work_root / "brief/map-brief.yaml")
        atomic_yaml(target, brief)
        state, receipt = self.state_store.complete_step(
            state, status="waiting_approval", prerequisites={"intent": intent},
            output_refs=[self._ref("map-brief", brief, target)],
            tool_versions={"map-brief-builder": TOOL_VERSION}, next_step="compile",
        )
        return {"state": state.to_dict(), "receipt": receipt.to_dict(), "brief": brief,
                "approval_object_digest": sha256_digest(brief)}

    @serialized_workflow_step
    def compile(self, request_path: str | Path, approval_path: str | Path, *, approval_key: bytes,
                nonce_db: str | Path, policy_id: str, issuer: str) -> dict[str, Any]:
        request, state = self._resume(request_path, "compile")
        intent = self._load("intent/map-intent.yaml", "map-intent")
        brief = self._load("brief/map-brief.yaml", "map-brief")
        context = self._context(request)
        approval_file = self._resolve_project_path(approval_path, must_exist=True)
        approval_value = load_document(approval_file)
        if not isinstance(approval_value, dict):
            raise ProtocolError("MAP_BRIEF_APPROVAL_REQUIRED", "Approval receipt must be an object")
        self.registry.validate("approval-receipt", approval_value)
        approval_receipt = ApprovalReceipt.from_dict(approval_value)
        approval_copy = self.path_guard.resolve(self.work_root / "approvals/g1-map-brief.yaml")
        approval_journal_exists = approval_copy.exists()
        nonce_path = self._resolve_project_path(nonce_db)
        nonce_path.parent.mkdir(parents=True, exist_ok=True)
        nonce_store = SqliteNonceStore(str(nonce_path))
        coordinator = ApprovalGateCoordinator(approval_key, nonce_store, policy_id, issuer)
        coordinator.validate(
            "G1", approval_receipt, sha256_digest(brief), context,
            approver_subject_id=request["subject"]["approver_subject_id"],
            expected_scope=request["scope"],
        )
        atomic_yaml(approval_copy, approval_value)
        already_consumed = nonce_store.contains(approval_receipt.issuer, approval_receipt.nonce)
        if already_consumed:
            if not approval_journal_exists:
                raise SecurityError(
                    "APPROVAL_RECOVERY_EVIDENCE_MISSING",
                    "Consumed G1 approval has no workflow-local intent record",
                )
            coordinator.require_consumed(
                "G1", approval_receipt, sha256_digest(brief), context,
                approver_subject_id=request["subject"]["approver_subject_id"],
                expected_scope=request["scope"],
            )
        else:
            coordinator.require(
                "G1", approval_receipt, sha256_digest(brief), context,
                approver_subject_id=request["subject"]["approver_subject_id"],
                expected_scope=request["scope"],
            )
        compiled, outputs = self._compile_approved_candidate(request, intent, brief)
        state, receipt = self.state_store.complete_step(
            state, status="succeeded", prerequisites={"brief": brief, "approval": approval_value},
            output_refs=outputs, tool_versions={"map-candidate-compiler": TOOL_VERSION}, next_step="preview",
        )
        return {
            "state": state.to_dict(),
            "receipt": receipt.to_dict(),
            **compiled,
            "idempotent_replay": already_consumed,
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
        preparer = FloodDataPreparer(
            self.path_guard,
            self.project_root,
            self.path_guard.resolve(self.work_root / "data"),
            self.registry,
        )
        prepared = preparer.prepare(request, artifact_ref("generate-request", request))
        bundle = prepared["bundle"]
        bundle_target = self.path_guard.resolve(self.work_root / "data/prepared-data-bundle.yaml")
        atomic_yaml(bundle_target, bundle)
        compiler = MapCandidateCompiler(self.path_guard, self.registry)
        contracts = compiler.load_contracts(installation)
        plan = MapPlanner(self.registry).build(request, intent, brief, bundle, installation, contracts)
        plan_target = self.path_guard.resolve(self.work_root / "plan/map-plan.yaml")
        atomic_yaml(plan_target, plan)
        font = self.path_guard.resolve(request["font"]["path"], base_root=self.project_root, must_exist=True)
        compiled = compiler.compile(request, intent, plan, bundle, installation, contracts, font)
        candidate_target = self.path_guard.resolve(self.work_root / "candidates/resolved-map.yaml")
        scene_target = self.path_guard.resolve(self.work_root / "candidates/render-scene.yaml")
        report_target = self.path_guard.resolve(self.work_root / "candidates/preflight-report.yaml")
        atomic_yaml(candidate_target, compiled["candidate"])
        atomic_yaml(scene_target, compiled["scene"])
        atomic_yaml(report_target, compiled["preflight"])
        outputs = [
            self._ref("installed-template", installation, installed_target),
            self._ref("prepared-data-bundle", bundle, bundle_target),
            self._ref("map-plan", plan, plan_target),
            self._ref("resolved-map", compiled["candidate"], candidate_target),
            self._ref("render-scene", compiled["scene"], scene_target),
            self._ref("preflight-report", compiled["preflight"], report_target),
        ]
        return compiled, outputs

    @serialized_workflow_step
    def preview(self, request_path: str | Path, *, attestation_key: bytes,
                browser: str | Path | None = None) -> dict[str, Any]:
        request, state = self._resume(request_path, "preview")
        candidate = self._load("candidates/resolved-map.yaml", "resolved-map")
        scene = self._load("candidates/render-scene.yaml", "render-scene")
        preflight = self._load("candidates/preflight-report.yaml", "validation-report")
        installation = self._load("templates/installed-template.yaml")
        self._verify_installed_template(installation)
        MapCandidateCompiler(self.path_guard, self.registry).load_contracts(installation)
        self._verify_candidate_inputs(candidate, scene)
        service = MapPreviewService(path_guard=self.path_guard,
                                    output_root=self.path_guard.resolve(self.work_root / "previews"),
                                    attestation_key=attestation_key, browser=browser, registry=self.registry)
        rendered = service.render(request, candidate, scene)
        receipt_target = self.path_guard.resolve(self.work_root / "candidates/render-receipt.yaml")
        evidence_target = self.path_guard.resolve(self.work_root / "candidates/preview-evidence.yaml")
        atomic_yaml(receipt_target, rendered["receipt"])
        atomic_yaml(evidence_target, rendered["evidence"])
        state, receipt = self.state_store.complete_step(
            state, status="waiting_approval", prerequisites={"candidate": candidate, "scene": scene, "preflight": preflight},
            output_refs=[self._ref("render-receipt", rendered["receipt"], receipt_target),
                         self._ref("map-preview-evidence", rendered["evidence"], evidence_target)],
            tool_versions={"controlled-map-preview": TOOL_VERSION}, next_step="freeze",
        )
        return {"state": state.to_dict(), "receipt": receipt.to_dict(), **rendered,
                "approval_object_digest": freeze_object_digest(request, candidate, rendered["evidence"])}

    @serialized_workflow_step
    def freeze(self, request_path: str | Path, approval_path: str | Path, *, approval_key: bytes,
               attestation_key: bytes, nonce_db: str | Path, policy_id: str, issuer: str,
               browser: str | Path | None = None) -> dict[str, Any]:
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
        MapCandidateCompiler(self.path_guard, self.registry).load_contracts(installation)
        self._verify_candidate_inputs(candidate, scene)
        service = MapPreviewService(path_guard=self.path_guard,
                                    output_root=self.path_guard.resolve(self.work_root / "previews", must_exist=True),
                                    attestation_key=attestation_key, browser=browser, registry=self.registry)
        service.validate_persisted(candidate, scene, receipt)
        service.validate_evidence(evidence, candidate, scene, receipt, self.registry)
        approval_file = self._resolve_project_path(approval_path, must_exist=True)
        approval_value = load_document(approval_file)
        if not isinstance(approval_value, dict):
            raise ProtocolError("FREEZE_APPROVAL_REQUIRED", "Approval receipt must be an object")
        self.registry.validate("approval-receipt", approval_value)
        approval_receipt = ApprovalReceipt.from_dict(approval_value)
        nonce_path = self._resolve_project_path(nonce_db)
        nonce_path.parent.mkdir(parents=True, exist_ok=True)
        coordinator = ApprovalGateCoordinator(
            approval_key, SqliteNonceStore(str(nonce_path)), policy_id, issuer,
        )
        approval_digest = freeze_object_digest(request, candidate, evidence)
        compiler = MapSpecLockCompiler(self.registry)
        brief_approval_ref = "approvals/g1-map-brief.yaml"
        freeze_approval_ref = str(approval_file)
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
            )
            if state.step == "render":
                if state.status != "pending":
                    raise ProtocolError("JOB_RECOVERY_NOT_ALLOWED", f"status={state.status}; step={state.step}")
                coordinator.require_consumed(
                    "G2", approval_receipt, approval_digest, self._context(request),
                    approver_subject_id=request["subject"]["approver_subject_id"],
                    expected_scope=request["scope"],
                )
                if self.state_store.find_output_digest("map-spec-lock") != sha256_digest(existing):
                    raise ProtocolError("JOB_PREREQUISITE_DRIFT", state.run_id)
                return {"state": state.to_dict(), "lock": existing, "idempotent_replay": True}
            if state.status not in {"pending", "waiting_approval"}:
                raise ProtocolError("JOB_RECOVERY_NOT_ALLOWED", f"status={state.status}; step={state.step}")
            coordinator.require_consumed(
                "G2", approval_receipt, approval_digest, self._context(request),
                approver_subject_id=request["subject"]["approver_subject_id"],
                expected_scope=request["scope"],
            )
            state, step_receipt = self.state_store.complete_step(
                state, status="succeeded",
                prerequisites={"candidate": candidate, "preview": evidence,
                               "freeze_approval": approval_value},
                output_refs=[self._ref("map-spec-lock", existing, target)],
                tool_versions={"map-spec-freezer": TOOL_VERSION}, next_step="render",
            )
            return {"state": state.to_dict(), "receipt": step_receipt.to_dict(),
                    "lock": existing, "idempotent_replay": True}
        if state.step == "render":
            raise ProtocolError("JOB_PREREQUISITE_DRIFT", "map-spec-lock")
        coordinator.require(
            "G2", approval_receipt, approval_digest, self._context(request),
            approver_subject_id=request["subject"]["approver_subject_id"],
            expected_scope=request["scope"],
        )
        lock = compiler.compile(
            request, candidate, evidence, receipt, preflight,
            brief_approval_ref=brief_approval_ref, freeze_approval_ref=freeze_approval_ref,
        )
        atomic_yaml(target, lock)
        state, step_receipt = self.state_store.complete_step(
            state, status="succeeded", prerequisites={"candidate": candidate, "preview": evidence,
                                                       "freeze_approval": approval_value},
            output_refs=[self._ref("map-spec-lock", lock, target)],
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
            service = FormalMapRenderService(
                path_guard=self.path_guard, work_root=self.work_root,
                attestation_key=attestation_key, browser=browser, registry=self.registry,
            )
            lock, lock_ref, scene, preview_receipt = self._locked_render_inputs(
                request, attestation_key=attestation_key, browser=browser
            )
            service.validate_environment(lock, preview_receipt)
            service.validate_scene(scene)
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
        service = FormalMapRenderService(
            path_guard=self.path_guard, work_root=self.work_root,
            attestation_key=attestation_key, browser=browser, registry=self.registry,
        )
        lock: dict[str, Any]
        lock_ref: dict[str, str]
        scene: dict[str, Any]
        try:
            lock, lock_ref, scene, preview_receipt = self._locked_render_inputs(
                request, attestation_key=attestation_key, browser=browser
            )
            service.validate_environment(lock, preview_receipt)
            service.validate_scene(scene)
        except CartoError as exc:
            normalized = exc if exc.code in {"LOCK_INPUT_DRIFT", "RENDER_ENVIRONMENT_DRIFT",
                                              "ENCODING_SEMANTICS_INVALID"} else ProtocolError(
                "LOCK_INPUT_DRIFT", f"{exc.code}: {exc.message}"
            )
            context = getattr(exc, "render_context", None)
            if context is None and "lock" in locals() and "lock_ref" in locals() and "scene" in locals():
                context = (lock, lock_ref, scene)
            if context is not None:
                lock, lock_ref, scene = context
                attempt, attempt_path = service.record_failure(
                    request=request, lock=lock, lock_ref=lock_ref, scene=scene,
                    attempt_number=state.attempt, started_at=started_at,
                    error=normalized, retryable=False,
                )
                prerequisites = {"lock": lock, "scene": scene}
                output_refs = [self._ref("render-attempt", attempt, attempt_path)]
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
                    output_refs=[self._ref("render-attempt", existing["attempt"], existing["attempt_path"])],
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
                output_refs=[self._ref("render-attempt", attempt, attempt_path)],
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
                output_refs=[self._ref("render-attempt", attempt, attempt_path)],
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
                self._ref("render-attempt", rendered["attempt"], rendered["attempt_path"]),
                self._ref("formal-render-receipt", rendered["receipt"], rendered["receipt_path"]),
                self._ref("formal-render-evidence", rendered["evidence"], rendered["evidence_path"]),
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
        recipient_id: str,
        recipient_type: str,
        destination: str | Path,
        idempotency_key: str,
        browser: str | Path | None = None,
    ) -> dict[str, Any]:
        request = self._read_request(request_path)
        state = self.state_store.load()
        if sha256_digest(request) != state.input_fingerprint:
            raise ProtocolError("JOB_INPUT_DRIFT", state.run_id)
        stored = self._load("request/generate-request.yaml", "generate-request")
        if stored != request:
            raise ProtocolError("JOB_INPUT_DRIFT", state.run_id)
        if state.step == "deliver" and state.status == "waiting_approval":
            report_ref = self.state_store.find_output_ref("final-validation-report")
            manifest_ref = self.state_store.find_output_ref("delivery-manifest")
            report = self._load_ref(report_ref, "validation-report")
            manifest = self._load_ref(manifest_ref, "delivery-manifest")
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
            )
            service.validate_environment(lock, preview_receipt)
            service.validate_scene(scene)
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
            )
            if expected_manifest != manifest:
                raise ProtocolError("DELIVERY_MANIFEST_DRIFT", manifest["manifest_id"])
            return {
                "state": state.to_dict(), "validation_report": report,
                "delivery_manifest": manifest, "g3": checker.g3_context(manifest),
                "idempotent_replay": True,
            }
        if state.step != "check":
            raise ProtocolError("WORKFLOW_STEP_INVALID", f"expected=check; actual={state.step}")
        if state.status != "pending":
            raise ProtocolError("WORKFLOW_STATUS_INVALID", f"expected=pending; actual={state.status}")

        lock, lock_ref, scene, preview_receipt = self._locked_render_inputs(
            request, attestation_key=attestation_key, browser=browser
        )
        render_service = FormalMapRenderService(
            path_guard=self.path_guard, work_root=self.work_root,
            attestation_key=attestation_key, browser=browser, registry=self.registry,
        )
        render_service.validate_environment(lock, preview_receipt)
        render_service.validate_scene(scene)
        evidence_ref = self.state_store.find_output_ref("formal-render-evidence")
        evidence = self._load_ref(evidence_ref, "formal-render-evidence")
        attempt_number = int(evidence["attempt_ref"]["id"].rsplit("-", 1)[1])
        existing = render_service.load_existing(
            request=request, lock=lock, lock_ref=lock_ref, scene=scene,
            attempt_number=attempt_number, verify_outputs=False,
        )
        if existing is None or existing["attempt"]["status"] != "succeeded":
            raise ProtocolError("FINAL_CHECK_RENDER_INVALID", evidence["evidence_id"])
        checker = FinalMapCheckService(
            path_guard=self.path_guard, project_root=self.project_root,
            work_root=self.work_root, registry=self.registry,
        )
        report = checker.inspect(
            lock=lock, lock_ref=lock_ref, scene=scene,
            attempt=existing["attempt"], attempt_path=existing["attempt_path"],
            receipt=existing["receipt"], evidence=existing["evidence"],
            evidence_path=existing["evidence_path"],
        )
        report_path = checker.write_report(report, existing["attempt"]["attempt_id"])
        report_ref = self._ref("final-validation-report", report, report_path)
        if report["status"] != "passed":
            self.state_store.complete_step(
                state, status="failed",
                prerequisites={"lock": lock, "attempt": existing["attempt"], "evidence": existing["evidence"]},
                output_refs=[report_ref],
                tool_versions={"final-map-check": TOOL_VERSION},
                error={"code": "FINAL_CHECK_FAILED", "message": report["report_id"]},
            )
            raise ProtocolError("FINAL_CHECK_FAILED", report["report_id"])
        manifest = checker.build_manifest(
            request=request, lock=lock, lock_ref=lock_ref,
            attempt=existing["attempt"], attempt_path=existing["attempt_path"],
            report=report, report_path=report_path,
            recipient_id=recipient_id, recipient_type=recipient_type,
            destination=destination, idempotency_key=idempotency_key,
        )
        manifest_path = checker.write_manifest(manifest)
        state, step_receipt = self.state_store.complete_step(
            state, status="waiting_approval",
            prerequisites={"lock": lock, "attempt": existing["attempt"], "evidence": existing["evidence"]},
            output_refs=[report_ref, self._ref("delivery-manifest", manifest, manifest_path)],
            tool_versions={"final-map-check": TOOL_VERSION}, next_step="deliver",
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
        nonce_db: str | Path,
        policy_id: str,
        issuer: str,
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
        )
        delivered = service.deliver(
            request=request, manifest=manifest, manifest_ref=manifest_ref, report=report,
            approval_path=approval_path, approval_key=approval_key, nonce_db=nonce_db,
            policy_id=policy_id, issuer=issuer, failure_hook=failure_hook,
        )
        transaction = delivered["transaction"]
        delivery_receipt = delivered["receipt"]
        transaction_ref = self._ref(
            transaction["transaction_id"], transaction, delivered["transaction_path"]
        )
        receipt_ref = self._ref(
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
            "idempotent_replay": bool(delivered["idempotent_replay"] or delivered["approval_replay"]),
        }

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
            MapCandidateCompiler(self.path_guard, self.registry).load_contracts(installation)
            self._verify_candidate_inputs(candidate, scene)
            preview_service = MapPreviewService(
                path_guard=self.path_guard,
                output_root=self.path_guard.resolve(self.work_root / "previews", must_exist=True),
                attestation_key=attestation_key, browser=browser, registry=self.registry,
            )
            preview_service.validate_persisted(candidate, scene, preview_receipt)
            preview_service.validate_evidence(evidence, candidate, scene, preview_receipt, self.registry)
            MapSpecLockCompiler(self.registry).verify_existing(
                lock, request, candidate, evidence, preview_receipt, preflight,
                brief_approval_ref=lock["approvals"]["brief_ref"],
                freeze_approval_ref=lock["approvals"]["freeze_ref"],
            )
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
        missing = sorted(self.REQUIRED_REQUEST_FIELDS - set(request))
        if missing:
            raise ProtocolError("GENERATE_REQUEST_INCOMPLETE", ",".join(missing))
        if request.get("scene_hint") not in {None, "emergency_mapping"}:
            raise ProtocolError("GENERATE_SCENE_UNSUPPORTED", str(request.get("scene_hint")))
        if request["template"]["kind"] != "map-scenario":
            raise ProtocolError("GENERATE_TEMPLATE_KIND_UNSUPPORTED", request["template"]["kind"])
        if request["scope"] != f"project:{request['project_id']}":
            raise SecurityError("PROJECT_SCOPE_DENIED", request["scope"])
        subject = request["subject"]
        if not subject.get("approver_subject_id"):
            raise ProtocolError("APPROVER_REQUIRED", "subject.approver_subject_id")
        required_capabilities = {"read", "classify", "render-preview"}
        if any(item.get("join", {}).get("required") for item in request["source_bindings"]):
            required_capabilities.add("join")
        missing_capabilities = required_capabilities - set(request["allowed_capabilities"])
        if missing_capabilities:
            raise SecurityError("CAPABILITY_NOT_AUTHORIZED", ",".join(sorted(missing_capabilities)))
        if set(request["requested_outputs"]) - {"svg", "png", "pdf"}:
            raise ProtocolError("RENDER_TARGET_UNSUPPORTED", str(request["requested_outputs"]))
        def identity(ref: dict[str, Any]) -> tuple[str, str, str]:
            return ref["id"], ref["version"], ref["digest"]
        if {identity(item) for item in request["sources"]} != {identity(item["source_ref"]) for item in request["source_bindings"]}:
            raise ProtocolError("SOURCE_REFERENCE_SET_MISMATCH", request["request_id"])

    def _intent(self, request: dict[str, Any]) -> dict[str, Any]:
        profile = {"profile_version": "1.0.0", "scene": "emergency_mapping", "task": "hazard-result-map"}
        value = {"schema_version": 1, "intent_id": f"intent-{request['run_id']}", "revision": 1,
                 "profile_version": "1.0.0", "business_scene": "emergency_mapping", "theme": "flood-risk",
                 "tasks": ["hazard-result-map"], "intent_status": "resolved", "readiness_status": "ready",
                 "missing_items": [], "evidence_refs": [artifact_ref("intent-profile", profile)]}
        self.registry.validate("map-intent", value)
        return value

    def _context(self, request: dict[str, Any]) -> ExecutionContext:
        return ExecutionContext(run_id=request["run_id"], tenant_id=request["subject"]["tenant_id"],
                                project_id=request["project_id"], subject_id=request["subject"]["subject_id"],
                                roles=frozenset({"operator"}), namespaces=frozenset({request["project_id"]}),
                                authorized_capabilities=frozenset(request["allowed_capabilities"]),
                                environment=request["environment"])

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

    def _verify_candidate_inputs(self, candidate: dict[str, Any], scene: dict[str, Any]) -> None:
        if candidate["execution_digest"] != sha256_digest(candidate["execution"]):
            raise ProtocolError("CANDIDATE_EXECUTION_DIGEST_MISMATCH", candidate["candidate_id"])
        if candidate["execution"].get("render_scene_ref", {}).get("digest") != sha256_digest(scene):
            raise ProtocolError("CANDIDATE_SCENE_DIGEST_MISMATCH", candidate["candidate_id"])
        for ref in [*candidate["execution"]["dataset_refs"], *candidate["execution"].get("prepared_data_refs", []),
                    *candidate["execution"].get("resolved_assets", [])]:
            uri = ref.get("uri")
            if uri and file_digest(self.path_guard.resolve(uri, must_exist=True)) != ref["digest"]:
                raise ProtocolError("CANDIDATE_RESOURCE_DRIFT", ref["id"])

    def _resolve_project_path(self, value: str | Path, *, must_exist: bool = False) -> Path:
        return self.path_guard.resolve(value, base_root=self.project_root, must_exist=must_exist)

    def _load(self, relative: str, schema: str | None = None) -> dict[str, Any]:
        path = self.path_guard.resolve(self.work_root / relative, must_exist=True)
        value = load_document(path)
        if not isinstance(value, dict):
            raise ProtocolError("WORKFLOW_ARTIFACT_INVALID", relative)
        if schema:
            self.registry.validate(schema, value)
        return value

    @staticmethod
    def _ref(identifier: str, value: Any, path: Path) -> dict[str, str]:
        return {"id": identifier, "version": "1.0.0", "digest": sha256_digest(value), "uri": str(path)}
