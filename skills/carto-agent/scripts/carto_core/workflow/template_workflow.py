from __future__ import annotations

from pathlib import Path
from typing import Any


from ..artifacts import artifact_ref, atomic_yaml
from ..canonical import sha256_digest
from ..errors import ProtocolError, SecurityError
from ..schema_registry import SchemaRegistry, load_document
from ..repository.template_repository import TemplateRepository
from ..security.approval import ApprovalReceipt
from ..security.nonce_store import NonceStore
from ..security.paths import PathGuard
from .approvals import ApprovalGateCoordinator
from ..contracts.execution import ExecutionContext
from .state_machine import WorkflowStateStore, serialized_workflow_step
from .template_analysis import ControlledSourceAnalyzer
from .template_author import MapScenarioAuthor
from .template_brief import build_template_brief
from .template_validation import TemplatePackageValidator

TOOL_VERSION = "0.2.4"


class TemplateCreationWorkflow:
    """U-P2 analyze -> brief -> author -> validate -> publish workflow."""

    # Evidence schema validated by _load_evidence; segment subclasses override it.
    _evidence_schema = "template-validation-evidence"

    def __init__(
        self,
        *,
        allowed_roots: list[str | Path],
        project_root: str | Path,
        workdir: str | Path,
        registry: SchemaRegistry | None = None,
    ) -> None:
        self.registry = registry or SchemaRegistry()
        self.path_guard = PathGuard(allowed_roots)
        self.project_root = self.path_guard.resolve(project_root, must_exist=True)
        if not self.project_root.is_dir():
            raise SecurityError("PROJECT_ROOT_INVALID", str(self.project_root))
        self.work_root = self.path_guard.resolve(workdir, base_root=self.project_root)
        self.work_root.mkdir(parents=True, exist_ok=True)
        self.analyzer = ControlledSourceAnalyzer(self.path_guard, self.project_root, self.registry)
        self.state_store = WorkflowStateStore(self.work_root, self.registry)
        self._nonce_store = NonceStore(self.work_root / ".nonce-ledger.db")

    def _gate_coordinator(self, key, request):
        if request["subject"]["approver_subject_id"] == request["subject"]["requester_subject_id"]:
            raise SecurityError("APPROVER_NOT_INDEPENDENT", "The template author cannot approve their own work")
        return ApprovalGateCoordinator(
            key, nonce_store=self._nonce_store,
            trusted_subject_id=request["subject"]["approver_subject_id"],
            trusted_tenant_id=request["subject"]["tenant_id"],
            trusted_scope=request["scope"],
            trusted_environment=request["subject"]["environment"])

    @serialized_workflow_step
    def analyze(self, request_path: str | Path) -> dict[str, Any]:
        request, manifest, summaries = self.analyzer.load_inputs(
            self._resolve_project_path(request_path, must_exist=True)
        )
        inputs = self.analyzer.input_snapshot(request, manifest, summaries)
        state = self.state_store.initialize(request["request_id"], inputs, step="analyze")
        analysis = self.analyzer.analyze(request, manifest, summaries)
        analysis_path = self.path_guard.resolve(self.work_root / "analysis/template-analysis.yaml")
        snapshot_path = self.path_guard.resolve(self.work_root / "sources/source-manifest.yaml")
        atomic_yaml(snapshot_path, manifest)
        atomic_yaml(analysis_path, analysis)
        refs = [
            artifact_ref("source-manifest-snapshot", manifest, "sources/source-manifest.yaml"),
            artifact_ref("template-analysis", analysis, "analysis/template-analysis.yaml"),
        ]
        state, receipt = self.state_store.complete_step(
            state,
            status="succeeded",
            prerequisites={},
            output_refs=refs,
            tool_versions={"template-analyzer": TOOL_VERSION},
            next_step="brief",
        )
        return {"state": state.to_dict(), "receipt": receipt.to_dict(), "analysis": analysis}

    @serialized_workflow_step
    def brief(self, request_path: str | Path) -> dict[str, Any]:
        request, manifest, summaries = self.analyzer.load_inputs(
            self._resolve_project_path(request_path, must_exist=True)
        )
        inputs = self.analyzer.input_snapshot(request, manifest, summaries)
        state = self.state_store.resume(inputs, {})
        self._require_step(state.step, "brief")
        analysis = self._load_yaml("analysis/template-analysis.yaml", "template-analysis")
        self._verify_last_output("template-analysis", analysis)
        brief = build_template_brief(request, analysis, self.registry)
        brief_path = self.path_guard.resolve(self.work_root / "template_brief.yaml")
        atomic_yaml(brief_path, brief)
        state, receipt = self.state_store.complete_step(
            state,
            status="succeeded",
            prerequisites={"analysis": analysis},
            output_refs=[artifact_ref("template-brief", brief, "template_brief.yaml")],
            tool_versions={"template-brief-builder": TOOL_VERSION},
            next_step="author",
        )
        return {
            "state": state.to_dict(),
            "receipt": receipt.to_dict(),
            "brief": brief,
        }

    @serialized_workflow_step
    def author(
        self,
        request_path: str | Path,
    ) -> dict[str, Any]:
        package_root = self.path_guard.resolve(self.work_root / "staging/package")
        package_exists = package_root.exists()
        if package_exists and self.state_store.load().step != "author":
            raise ProtocolError("STAGING_PACKAGE_EXISTS", str(package_root))
        request, manifest, summaries = self.analyzer.load_inputs(
            self._resolve_project_path(request_path, must_exist=True)
        )
        inputs = self.analyzer.input_snapshot(request, manifest, summaries)
        analysis = self._load_yaml("analysis/template-analysis.yaml", "template-analysis")
        state = self.state_store.resume(inputs, {"analysis": analysis})
        if package_exists and state.step != "author":
            raise ProtocolError("STAGING_PACKAGE_EXISTS", str(package_root))
        self._require_step(state.step, "author")
        brief = self._load_yaml("template_brief.yaml", "template-brief")
        self._verify_last_output("template-brief", brief)

        author = MapScenarioAuthor(self.path_guard, self.work_root, self.registry)
        package = (
            author.verify_existing(request, brief)
            if package_exists
            else author.author(request, brief)
        )
        package_ref = {
            "id": "staging-package",
            "version": request["version"],
            "digest": package["package_digest"],
            "uri": "staging/package",
        }
        state, step_receipt = self.state_store.complete_step(
            state,
            status="succeeded",
            prerequisites={"analysis": analysis, "brief": brief},
            output_refs=[package_ref],
            tool_versions={"map-scenario-author": TOOL_VERSION},
            next_step="validate",
        )
        return {
            "state": state.to_dict(),
            "receipt": step_receipt.to_dict(),
            "package": package,
        }

    @serialized_workflow_step
    def validate(
        self,
        request_path: str | Path,
        *,
        attestation_key: bytes,
        browser: str | Path | None = None,
        font_path: str | Path | None = None,
        repository_root: str | Path | None = None,
        repository_scope: str | None = None,
    ) -> dict[str, Any]:
        request, inputs, state = self._resume_request(request_path)
        self._require_step(state.step, "validate")
        expected = self._expected_validation(request)
        package_root = self.path_guard.resolve(self.work_root / "staging/package", must_exist=True)
        validation_relative = Path("validation")
        if state.attempt > 1:
            validation_relative /= f"attempt-{state.attempt}"
        validation_root = self.path_guard.resolve(self.work_root / validation_relative)
        repository = None
        if repository_root is not None or repository_scope is not None:
            if repository_root is None or not repository_scope:
                raise ProtocolError("TEMPLATE_REPOSITORY_REQUIRED", "repository root and scope must be supplied together")
            repository = TemplateRepository(
                path_guard=self.path_guard,
                root=self._resolve_project_path(repository_root, must_exist=False),
                repository_scope=repository_scope, registry=self.registry,
            )
        validator = TemplatePackageValidator(
            path_guard=self.path_guard,
            package_root=package_root,
            evidence_root=validation_root,
            attestation_key=attestation_key,
            registry=self.registry,
            browser=browser,
            font_path=font_path,
            context=self._validation_context(request, state),
            repository=repository,
        )
        evidence = validator.validate(expected, request["targets"])
        authored_digest = self._last_output_digest("staging-package")
        if evidence["status"] == "passed" and evidence["package_ref"]["digest"] != authored_digest:
            raise ProtocolError("JOB_PREREQUISITE_DRIFT", state.run_id)
        evidence_ref = {
            "id": "template-validation-evidence",
            "version": "1.0.0",
            "digest": evidence["evidence_digest"],
            "uri": (validation_relative / "template-validation-evidence.yaml").as_posix(),
        }
        passed = evidence["status"] == "passed"
        state, step_receipt = self.state_store.complete_step(
            state,
            status="succeeded" if passed else "failed",
            prerequisites={"package_ref": evidence["package_ref"]},
            output_refs=[evidence_ref],
            tool_versions={"template-validator": "1.0.0", "fixture-renderer": "1.0.0"},
            next_step="prepare-publish" if passed else None,
            error=None if passed else {"code": "TEMPLATE_VALIDATION_FAILED", "message": "blocker/error checks failed"},
        )
        return {"state": state.to_dict(), "receipt": step_receipt.to_dict(), "evidence": evidence}

    def _load_evidence(self, state) -> tuple[dict[str, Any], dict[str, str], Path]:
        evidence_ref = self.state_store.find_output_ref("template-validation-evidence")
        evidence_uri = evidence_ref.get("uri")
        if not evidence_uri or Path(evidence_uri).is_absolute():
            raise ProtocolError("WORKFLOW_ARTIFACT_REF_INVALID", str(evidence_uri))
        evidence_path = self.path_guard.resolve(self.work_root / evidence_uri, must_exist=True)
        try:
            evidence_path.relative_to(self.work_root)
        except ValueError as exc:
            raise ProtocolError("WORKFLOW_ARTIFACT_REF_INVALID", evidence_uri) from exc
        evidence = load_document(evidence_path)
        if not isinstance(evidence, dict):
            raise ProtocolError("WORKFLOW_ARTIFACT_INVALID", evidence_uri)
        self.registry.validate(self._evidence_schema, evidence)
        if evidence.get("evidence_digest") != evidence_ref["digest"]:
            raise ProtocolError("JOB_PREREQUISITE_DRIFT", state.run_id)
        return evidence, evidence_ref, evidence_path

    @serialized_workflow_step
    def prepare_publication(
        self,
        request_path: str | Path,
        *,
        repository_root: str | Path,
        repository_scope: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Machine preparation of the frozen, operator-approved publication object.

        Not an approval gate: consumes no nonce, signs nothing, publishes nothing.
        Repeating the same preparation reuses the same object and digest.
        """
        request, inputs, state = self._resume_request(request_path)
        if state.step == "publish" and state.status == "waiting_approval":
            ref = self.state_store.find_output_ref("template-publication")
            obj = self._load_yaml(ref["uri"], "template-publication")
            if sha256_digest(obj) != ref["digest"]:
                raise ProtocolError("PUBLICATION_OBJECT_DRIFT", state.run_id)
            return {"state": state.to_dict(), "publication_object": obj,
                    "object_digest": ref["digest"], "idempotent_prepare": True}
        self._require_step(state.step, "prepare-publish")
        evidence, evidence_ref, _ = self._load_evidence(state)
        if evidence["status"] != "passed":
            raise ProtocolError("TEMPLATE_VALIDATION_FAILED", "Only passed validation may be prepared")
        if evidence["package_ref"]["digest"] != self._last_output_digest("staging-package"):
            raise ProtocolError("JOB_PREREQUISITE_DRIFT", state.run_id)
        root = self._resolve_project_path(repository_root, must_exist=False)
        package = evidence["package_ref"]
        obj = {
            "schema_version": 1,
            "run_id": state.run_id,
            "request_digest": sha256_digest(inputs),
            "package_ref": {key: package[key] for key in ("kind", "id", "version", "digest")},
            "evidence_ref": evidence_ref,
            "repository_scope": repository_scope,
            "repository_root": root.as_posix(),
            "idempotency_key": idempotency_key,
        }
        self.registry.validate("template-publication", obj)
        obj_path = self.path_guard.resolve(self.work_root / "publication/template-publication.yaml")
        if obj_path.exists():
            if load_document(obj_path) != obj:
                raise ProtocolError("PUBLICATION_OBJECT_DRIFT", str(obj_path))
        else:
            atomic_yaml(obj_path, obj)
        obj_ref = {"id": "template-publication", "version": "1.0.0",
                   "digest": sha256_digest(obj), "uri": "publication/template-publication.yaml"}
        state, receipt = self.state_store.complete_step(
            state,
            status="waiting_approval",
            prerequisites={"evidence": evidence},
            output_refs=[obj_ref],
            tool_versions={"template-publication-preparer": TOOL_VERSION},
            next_step="publish",
        )
        return {"state": state.to_dict(), "receipt": receipt.to_dict(),
                "publication_object": obj, "object_digest": obj_ref["digest"],
                "previews": evidence.get("preview_artifacts", []),
                "approval": {"gate_id": "TP", "action": "approve-template-publish",
                             "object_type": "template-publication", "object_digest": obj_ref["digest"],
                             "scope": request["scope"]}}

    @serialized_workflow_step
    def publish(
        self,
        request_path: str | Path,
        approval_path: str | Path | None,
        *,
        repository_root: str | Path,
        repository_scope: str,
        idempotency_key: str,
        approval_key: bytes,
        renderer_attestation_key: bytes,
    ) -> dict[str, Any]:
        request, inputs, state = self._resume_request(request_path)
        self._require_step(state.step, "publish")
        obj_ref = self.state_store.find_output_ref("template-publication")
        obj = self._load_yaml(obj_ref["uri"], "template-publication")
        if sha256_digest(obj) != obj_ref["digest"]:
            raise ProtocolError("PUBLICATION_OBJECT_DRIFT", state.run_id)
        if obj["run_id"] != state.run_id or obj["request_digest"] != sha256_digest(inputs):
            raise ProtocolError("PUBLICATION_OBJECT_DRIFT", state.run_id)
        root = self._resolve_project_path(repository_root, must_exist=False)
        if (root.as_posix() != obj["repository_root"] or repository_scope != obj["repository_scope"]
                or idempotency_key != obj["idempotency_key"]):
            raise ProtocolError("PUBLICATION_TARGET_MISMATCH", state.run_id)
        evidence, evidence_ref, evidence_path = self._load_evidence(state)
        if evidence["evidence_digest"] != obj["evidence_ref"]["digest"]:
            raise ProtocolError("PUBLICATION_OBJECT_DRIFT", state.run_id)
        package_root = self.path_guard.resolve(self.work_root / "staging/package", must_exist=True)
        repository = TemplateRepository(
            path_guard=self.path_guard, root=root,
            repository_scope=obj["repository_scope"], registry=self.registry,
        )
        snapshot = self._verify_for_publish(
            evidence, request, state, package_root, evidence_path, renderer_attestation_key, repository)
        if snapshot["package_digest"] != obj["package_ref"]["digest"]:
            raise ProtocolError("PUBLICATION_OBJECT_DRIFT", state.run_id)
        publication_digest = sha256_digest(obj)
        coordinator = self._gate_coordinator(approval_key, request)
        prior = repository.lookup_idempotency(
            obj["idempotency_key"], package_digest=snapshot["package_digest"],
            evidence_digest=evidence["evidence_digest"], publication_digest=publication_digest,
        )
        if prior is not None:
            approval_value = repository.load_publication_approval(prior)
            if sha256_digest(repository.load_publication_object(prior)) != publication_digest:
                raise ProtocolError("PUBLICATION_OBJECT_DRIFT", state.run_id)
            if state.status == "succeeded":
                if self.state_store.find_output_digest("publication-receipt") != sha256_digest(prior):
                    raise ProtocolError("JOB_PREREQUISITE_DRIFT", state.run_id)
                return {"state": state.to_dict(), "publication": prior, "idempotent_replay": True}
            if state.status not in {"pending", "waiting_approval"}:
                raise ProtocolError("JOB_RECOVERY_NOT_ALLOWED", f"status={state.status}")
            coordinator.require(
                "TP", ApprovalReceipt.from_dict(approval_value), publication_digest,
                run_id=state.run_id,
            )
            publication_ref = {
                "id": "publication-receipt", "version": "1.0.0",
                "digest": sha256_digest(prior),
            }
            state, step_receipt = self.state_store.complete_step(
                state, status="succeeded",
                prerequisites={"package_ref": evidence["package_ref"], "evidence": evidence,
                               "approval": approval_value},
                output_refs=[publication_ref],
                tool_versions={"template-publisher": "1.0.0"},
            )
            return {"state": state.to_dict(), "receipt": step_receipt.to_dict(),
                    "publication": prior, "idempotent_replay": True}
        if approval_path is None:
            raise ProtocolError("PUBLICATION_APPROVAL_REQUIRED", "Publication approval receipt is required")
        approval_resolved = self._resolve_project_path(approval_path, must_exist=True)
        approval_value = load_document(approval_resolved)
        if not isinstance(approval_value, dict):
            raise ProtocolError("PUBLICATION_APPROVAL_REQUIRED", "Approval receipt must be an object")
        self.registry.validate("approval-receipt", approval_value)
        coordinator.require(
            "TP", ApprovalReceipt.from_dict(approval_value), publication_digest,
            run_id=state.run_id,
        )
        publication = repository.publish(
            package_root=package_root, snapshot=snapshot, evidence=evidence,
            approval=approval_value, idempotency_key=obj["idempotency_key"],
            publication_object=obj,
        )
        publication_ref = {
            "id": "publication-receipt", "version": "1.0.0",
            "digest": sha256_digest(publication),
        }
        state, step_receipt = self.state_store.complete_step(
            state, status="succeeded",
            prerequisites={"package_ref": evidence["package_ref"], "evidence": evidence, "approval": approval_value},
            output_refs=[publication_ref],
            tool_versions={"template-publisher": "1.0.0"},
        )
        return {"state": state.to_dict(), "receipt": step_receipt.to_dict(),
                "publication": publication, "idempotent_replay": False}

    @serialized_workflow_step
    def status(self) -> dict[str, Any]:
        state = self.state_store.load()
        return {
            "state": state.to_dict(),
            "recovery": self.state_store.recovery_status(),
            "receipt_count": len(self.state_store.receipts()),
            "staging_package_exists": self.path_guard.resolve(self.work_root / "staging/package").is_dir(),
        }

    @serialized_workflow_step
    def retry(self) -> dict[str, Any]:
        return {"state": self.state_store.retry().to_dict()}

    @serialized_workflow_step
    def receipts(self) -> dict[str, Any]:
        return {"receipts": self.state_store.receipts()}

    def _resume_request(self, request_path: str | Path) -> tuple[dict[str, Any], dict[str, Any], Any]:
        request, manifest, summaries = self.analyzer.load_inputs(
            self._resolve_project_path(request_path, must_exist=True)
        )
        inputs = self.analyzer.input_snapshot(request, manifest, summaries)
        state = self.state_store.load()
        if sha256_digest(inputs) != state.input_fingerprint:
            raise ProtocolError("JOB_INPUT_DRIFT", state.run_id)
        return request, inputs, state

    def _last_output_digest(self, artifact_id: str) -> str:
        return self.state_store.find_output_digest(artifact_id)

    @staticmethod
    def _expected_identity(request: dict[str, Any]) -> dict[str, str]:
        return {"namespace": request["namespace"], "kind": request["kind"],
                "id": request["template_id"], "version": request["version"]}

    @staticmethod
    def _validation_context(request: dict[str, Any], state: Any) -> ExecutionContext:
        """Trusted fixture-render scope; identical across validate and publish re-verification."""
        context = ExecutionContext(
            run_id=state.run_id,
            tenant_id=request["subject"]["tenant_id"],
            project_id=request["subject"]["project_id"],
            subject_id=request["subject"]["requester_subject_id"],
            roles=frozenset({"template-validator"}),
            namespaces=frozenset({request["subject"]["project_id"]}),
            # Trusted fixture-render scope: the data-type-level tool capabilities
            # validation scenes may invoke through ToolGateway (raster statistics
            # for the general route, image registration/display for image-basemap
            # scenarios). Scenario admission stays with the registry/policy.
            authorized_capabilities=frozenset({"gis-raster-statistics",
                                                "geo-to-image-pixels",
                                                "image-display-bounds"}),
            environment=request["subject"]["environment"],
        )
        context.require_project_scope()
        return context

    @classmethod
    def _expected_validation(cls, request: dict[str, Any]) -> dict[str, Any]:
        return {**cls._expected_identity(request), "source_crs": request["source_crs"],
                "display_crs": request["display_crs"]}

    def _verify_for_publish(self, evidence, request, state, package_root, evidence_path,
                            attestation_key, repository):
        """Publish-time re-verification hook; segment subclasses swap the validator."""
        validator = TemplatePackageValidator(
            path_guard=self.path_guard, package_root=package_root,
            evidence_root=evidence_path.parent, attestation_key=attestation_key,
            registry=self.registry, context=self._validation_context(request, state),
            repository=repository,
        )
        return validator.verify_evidence(evidence, self._expected_validation(request), request["targets"])

    def _resolve_project_path(self, value: str | Path, *, must_exist: bool) -> Path:
        candidate = Path(value)
        return self.path_guard.resolve(
            candidate if candidate.is_absolute() else value,
            base_root=None if candidate.is_absolute() else self.project_root,
            must_exist=must_exist,
        )

    def _load_yaml(self, relative: str, schema_name: str) -> dict[str, Any]:
        path = self.path_guard.resolve(self.work_root / relative, must_exist=True)
        value = load_document(path)
        if not isinstance(value, dict):
            raise ProtocolError("WORKFLOW_ARTIFACT_INVALID", relative)
        self.registry.validate(schema_name, value)
        return value

    def _verify_last_output(self, artifact_id: str, value: dict[str, Any]) -> None:
        state = self.state_store.load()
        if self.state_store.find_output_digest(artifact_id) != sha256_digest(value):
            raise ProtocolError("JOB_PREREQUISITE_DRIFT", state.run_id)

    @staticmethod
    def _require_step(actual: str, expected: str) -> None:
        if actual != expected:
            raise ProtocolError("WORKFLOW_STEP_MISMATCH", f"expected={expected}; actual={actual}")