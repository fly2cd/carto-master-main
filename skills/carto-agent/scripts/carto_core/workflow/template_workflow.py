from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

import yaml

from ..canonical import sha256_digest
from ..errors import ProtocolError, SecurityError
from ..schema_registry import SchemaRegistry, load_document
from ..repository.template_repository import TemplateRepository
from ..security.approval import ApprovalReceipt, SqliteNonceStore
from ..security.paths import PathGuard
from .approvals import ApprovalGateCoordinator
from .models import ExecutionContext
from .state_machine import WorkflowStateStore, serialized_workflow_step
from .template_analysis import ControlledSourceAnalyzer
from .template_author import MapScenarioAuthor
from .template_brief import build_template_brief
from .template_validation import TemplatePackageValidator

TOOL_VERSION = "0.2.4"


def _atomic_yaml_once(path: Path, value: dict[str, Any]) -> None:
    if path.exists():
        if load_document(path) == value:
            return
        raise ProtocolError("IMMUTABLE_ARTIFACT_CONFLICT", str(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            yaml.safe_dump(value, stream, allow_unicode=True, sort_keys=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        temporary = Path(name)
        if temporary.exists():
            temporary.unlink()


class TemplateCreationWorkflow:
    """U-P2 analyze -> brief -> author -> validate -> publish workflow."""

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
        _atomic_yaml_once(snapshot_path, manifest)
        _atomic_yaml_once(analysis_path, analysis)
        refs = [
            self._artifact_ref("source-manifest-snapshot", manifest, "sources/source-manifest.yaml"),
            self._artifact_ref("template-analysis", analysis, "analysis/template-analysis.yaml"),
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
        _atomic_yaml_once(brief_path, brief)
        state, receipt = self.state_store.complete_step(
            state,
            status="waiting_approval",
            prerequisites={"analysis": analysis},
            output_refs=[self._artifact_ref("template-brief", brief, "template_brief.yaml")],
            tool_versions={"template-brief-builder": TOOL_VERSION},
            next_step="author",
        )
        return {
            "state": state.to_dict(),
            "receipt": receipt.to_dict(),
            "brief": brief,
            "approval": {
                "gate_id": "T1",
                "action": "approve-template-brief",
                "object_type": "template-brief",
                "object_digest": sha256_digest(brief),
                "scope": request["scope"],
            },
        }

    @serialized_workflow_step
    def author(
        self,
        request_path: str | Path,
        approval_path: str | Path | None,
        *,
        approval_key: bytes,
        nonce_db: str | Path,
        policy_id: str,
        issuer: str,
    ) -> dict[str, Any]:
        if approval_path is None:
            raise ProtocolError("BRIEF_NOT_CONFIRMED", "A T1 template-brief approval is required")
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

        approval_resolved = self._resolve_project_path(approval_path, must_exist=True)
        approval_value = load_document(approval_resolved)
        if not isinstance(approval_value, dict):
            raise ProtocolError("BRIEF_NOT_CONFIRMED", "Approval receipt must be an object")
        self.registry.validate("approval-receipt", approval_value)
        receipt = ApprovalReceipt.from_dict(approval_value)
        approval_copy = self.path_guard.resolve(self.work_root / "approvals/t1-template-brief.yaml")
        approval_journal_exists = approval_copy.exists()
        nonce_path = self._resolve_project_path(nonce_db, must_exist=False)
        nonce_path.parent.mkdir(parents=True, exist_ok=True)
        nonce_store = SqliteNonceStore(str(nonce_path))
        context = ExecutionContext(
            run_id=state.run_id,
            tenant_id=request["subject"]["tenant_id"],
            project_id=request["subject"]["project_id"],
            subject_id=request["subject"]["requester_subject_id"],
            roles=frozenset({"template-author"}),
            namespaces=frozenset({request["subject"]["project_id"]}),
            authorized_capabilities=frozenset({"create-template-author"}),
            environment=request["subject"]["environment"],
        )
        context.require_project_scope()
        coordinator = ApprovalGateCoordinator(
            approval_key,
            nonce_store,
            policy_id,
            issuer,
        )
        coordinator.validate(
            "T1",
            receipt,
            sha256_digest(brief),
            context,
            approver_subject_id=request["subject"]["approver_subject_id"],
        )
        _atomic_yaml_once(approval_copy, approval_value)
        already_consumed = nonce_store.contains(receipt.issuer, receipt.nonce)
        if already_consumed:
            if not approval_journal_exists:
                raise SecurityError(
                    "APPROVAL_RECOVERY_EVIDENCE_MISSING",
                    "Consumed T1 approval has no workflow-local intent record",
                )
            coordinator.require_consumed(
                "T1",
                receipt,
                sha256_digest(brief),
                context,
                approver_subject_id=request["subject"]["approver_subject_id"],
            )
        else:
            if package_exists:
                raise SecurityError(
                    "APPROVAL_NONCE_NOT_CONSUMED",
                    "Existing staging package is not backed by a consumed approval",
                )
            coordinator.require(
                "T1",
                receipt,
                sha256_digest(brief),
                context,
                approver_subject_id=request["subject"]["approver_subject_id"],
            )
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
            prerequisites={"analysis": analysis, "brief": brief, "approval": approval_value},
            output_refs=[package_ref],
            tool_versions={"map-scenario-author": TOOL_VERSION},
            next_step="validate",
        )
        return {
            "state": state.to_dict(),
            "receipt": step_receipt.to_dict(),
            "package": package,
            "idempotent_replay": already_consumed,
        }

    @serialized_workflow_step
    def validate(
        self,
        request_path: str | Path,
        *,
        attestation_key: bytes,
        browser: str | Path | None = None,
        font_path: str | Path | None = None,
    ) -> dict[str, Any]:
        request, inputs, state = self._resume_request(request_path)
        self._require_step(state.step, "validate")
        expected = self._expected_validation(request)
        package_root = self.path_guard.resolve(self.work_root / "staging/package", must_exist=True)
        validation_relative = Path("validation")
        if state.attempt > 1:
            validation_relative /= f"attempt-{state.attempt}"
        validation_root = self.path_guard.resolve(self.work_root / validation_relative)
        validator = TemplatePackageValidator(
            path_guard=self.path_guard,
            package_root=package_root,
            evidence_root=validation_root,
            attestation_key=attestation_key,
            registry=self.registry,
            browser=browser,
            font_path=font_path,
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
            next_step="publish" if passed else None,
            error=None if passed else {"code": "TEMPLATE_VALIDATION_FAILED", "message": "blocker/error checks failed"},
        )
        return {"state": state.to_dict(), "receipt": step_receipt.to_dict(), "evidence": evidence}

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
        nonce_db: str | Path,
        policy_id: str,
        issuer: str,
    ) -> dict[str, Any]:
        request, inputs, state = self._resume_request(request_path)
        self._require_step(state.step, "publish")
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
        self.registry.validate("template-validation-evidence", evidence)
        if evidence.get("evidence_digest") != evidence_ref["digest"]:
            raise ProtocolError("JOB_PREREQUISITE_DRIFT", state.run_id)
        package_root = self.path_guard.resolve(self.work_root / "staging/package", must_exist=True)
        validator = TemplatePackageValidator(
            path_guard=self.path_guard, package_root=package_root,
            evidence_root=evidence_path.parent, attestation_key=renderer_attestation_key,
            registry=self.registry,
        )
        snapshot = validator.verify_evidence(evidence, self._expected_validation(request), request["targets"])
        repository_path = self._resolve_project_path(repository_root, must_exist=False)
        repository = TemplateRepository(
            path_guard=self.path_guard, root=repository_path,
            repository_scope=repository_scope, registry=self.registry,
        )
        nonce_path = self._resolve_project_path(nonce_db, must_exist=False)
        nonce_path.parent.mkdir(parents=True, exist_ok=True)
        nonce_store = SqliteNonceStore(str(nonce_path))
        coordinator = ApprovalGateCoordinator(approval_key, nonce_store, policy_id, issuer)
        context = ExecutionContext(
            run_id=state.run_id, tenant_id=request["subject"]["tenant_id"],
            project_id=request["subject"]["project_id"],
            subject_id=request["subject"]["requester_subject_id"],
            roles=frozenset({"template-publisher"}),
            namespaces=frozenset({request["namespace"]}),
            authorized_capabilities=frozenset({"create-template-publish"}),
            environment=request["subject"]["environment"],
        )
        publication_object = {
            "package_digest": snapshot["package_digest"],
            "evidence_digest": evidence["evidence_digest"],
            "repository_scope": repository_scope,
        }
        publication_digest = sha256_digest(publication_object)
        prior = repository.lookup_idempotency(
            idempotency_key, package_digest=snapshot["package_digest"],
            evidence_digest=evidence["evidence_digest"],
        )
        if prior is not None:
            if state.status == "succeeded":
                if self.state_store.find_output_digest("publication-receipt") != sha256_digest(prior):
                    raise ProtocolError("JOB_PREREQUISITE_DRIFT", state.run_id)
                return {"state": state.to_dict(), "publication": prior, "idempotent_replay": True}
            if state.status not in {"pending", "waiting_approval"}:
                raise ProtocolError("JOB_RECOVERY_NOT_ALLOWED", f"status={state.status}")
            approval_value = repository.load_publication_approval(prior)
            coordinator.require_consumed(
                "TP", ApprovalReceipt.from_dict(approval_value), publication_digest, context,
                approver_subject_id=request["subject"]["approver_subject_id"],
                expected_scope=repository_scope,
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
            "TP", ApprovalReceipt.from_dict(approval_value), publication_digest, context,
            approver_subject_id=request["subject"]["approver_subject_id"],
            expected_scope=repository_scope,
        )
        publication = repository.publish(
            package_root=package_root, snapshot=snapshot, evidence=evidence,
            approval=approval_value, idempotency_key=idempotency_key,
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

    @classmethod
    def _expected_validation(cls, request: dict[str, Any]) -> dict[str, Any]:
        return {**cls._expected_identity(request), "source_crs": request["source_crs"],
                "display_crs": request["display_crs"]}

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
    def _artifact_ref(artifact_id: str, value: dict[str, Any], uri: str) -> dict[str, str]:
        return {"id": artifact_id, "version": "1.0.0", "digest": sha256_digest(value), "uri": uri}

    @staticmethod
    def _require_step(actual: str, expected: str) -> None:
        if actual != expected:
            raise ProtocolError("WORKFLOW_STEP_MISMATCH", f"expected={expected}; actual={actual}")