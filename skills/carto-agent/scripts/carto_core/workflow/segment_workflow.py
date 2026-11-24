"""Typed segment creation workflow (map-style/map-layout), plan phase-1 foundation.

Strangler-Fig dispatch: SegmentCreationWorkflow subclasses TemplateCreationWorkflow and
overrides only the data-source-coupled steps (analyze/brief/author/validate). It REUSES
the parent's WorkflowStateStore, step receipts, single-write lock, prepare_publication and
publish chain — there is no second state machine (plan §4). The scenario parent class is
untouched, so map-scenario behavior is byte-identical (zero regression).

Segments carry a confirmed design contract, not business data: no sources, CRS, geometry
or role bindings (plan §1.2.4). Segment sample rendering via the platform validation host
is a separate increment; until delivered, validate fails closed as a roadmap-declared
not_implemented capability (never a silent pass).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ..artifacts import artifact_ref, atomic_yaml, utc_now
from ..canonical import sha256_digest
from ..errors import ProtocolError, SecurityError
from ..repository.segment_authoring import author_segment_package, verify_segment_package
from ..repository.template_matching import SEGMENT_CONTRACTS
from ..schema_registry import SchemaRegistry, load_document
from ..security.paths import PathGuard
from .state_machine import serialized_workflow_step
from .segment_validation import SegmentPackageValidator
from .template_workflow import TOOL_VERSION, TemplateCreationWorkflow

_SEGMENT_KINDS = frozenset(SEGMENT_CONTRACTS)


def create_template_workflow(
    kind: str, *, allowed_roots: list[str | Path], project_root: str | Path,
    workdir: str | Path, registry: SchemaRegistry | None = None,
) -> TemplateCreationWorkflow:
    """Closed kind dispatch: scenario -> existing workflow; segments -> segment workflow."""
    if kind == "map-scenario":
        return TemplateCreationWorkflow(
            allowed_roots=allowed_roots, project_root=project_root, workdir=workdir, registry=registry)
    if kind in _SEGMENT_KINDS:
        return SegmentCreationWorkflow(
            allowed_roots=allowed_roots, project_root=project_root, workdir=workdir, registry=registry)
    raise ProtocolError("TEMPLATE_KIND_UNSUPPORTED", kind)


def create_workflow_for_request(
    request_path: str | Path, *, allowed_roots: list[str | Path], project_root: str | Path,
    workdir: str | Path, registry: SchemaRegistry | None = None,
) -> TemplateCreationWorkflow:
    """Peek the request kind (no full validation yet) and dispatch to the typed workflow.

    The selected workflow step re-validates the request closed-world; this peek only reads
    ``kind`` to choose the strategy. Unknown/missing kind fails closed via the factory.
    """
    guard = PathGuard(allowed_roots)
    proj = guard.resolve(project_root, must_exist=True)
    candidate = Path(request_path)
    resolved = guard.resolve(
        candidate if candidate.is_absolute() else request_path,
        base_root=None if candidate.is_absolute() else proj, must_exist=True)
    request = load_document(resolved)
    kind = request.get("kind") if isinstance(request, dict) else None
    return create_template_workflow(
        kind, allowed_roots=allowed_roots, project_root=project_root, workdir=workdir, registry=registry)


class SegmentCreationWorkflow(TemplateCreationWorkflow):
    """map-style/map-layout creation reusing the generic state machine and publish chain."""

    _evidence_schema = "segment-validation-evidence"

    def _resume_request(self, request_path):
        request = self._load_segment_request(request_path)
        inputs = self._segment_inputs(request)
        state = self.state_store.load()
        if sha256_digest(inputs) != state.input_fingerprint:
            raise ProtocolError("JOB_INPUT_DRIFT", state.run_id)
        return request, inputs, state

    @classmethod
    def _expected_validation(cls, request):
        reference_declared = any(str(d.get("path", "")).startswith("/reference/")
                                 for d in request.get("decisions", []))
        return {**cls._expected_identity(request), "design_digest": sha256_digest(request["design"]),
                "reference_declared": reference_declared}

    def _load_segment_request(self, request_path: str | Path) -> dict[str, Any]:
        resolved = self._resolve_project_path(request_path, must_exist=True)
        request = load_document(resolved)
        if not isinstance(request, dict):
            raise ProtocolError("TEMPLATE_REQUEST_INVALID", "Segment request must be an object")
        self.registry.validate("segment-create-request", request)
        if request["kind"] not in _SEGMENT_KINDS:
            raise ProtocolError("TEMPLATE_KIND_UNSUPPORTED", request["kind"])
        if request["scope"] != f"project:{request['subject']['project_id']}":
            raise SecurityError("PROJECT_SCOPE_DENIED", request["scope"])
        return request

    @staticmethod
    def _segment_inputs(request: dict[str, Any]) -> dict[str, Any]:
        return {"request": request, "design_digest": sha256_digest(request["design"])}

    def _validate_design(self, request: dict[str, Any]) -> None:
        _, schema_name = SEGMENT_CONTRACTS[request["kind"]]
        self.registry.validate(schema_name, request["design"])

    @serialized_workflow_step
    def analyze(self, request_path: str | Path) -> dict[str, Any]:
        request = self._load_segment_request(request_path)
        self._validate_design(request)
        inputs = self._segment_inputs(request)
        state = self.state_store.initialize(request["request_id"], inputs, step="analyze")
        analysis = self._build_analysis(request, inputs)
        analysis_path = self.path_guard.resolve(self.work_root / "analysis/segment-analysis.yaml")
        atomic_yaml(analysis_path, analysis)
        state, receipt = self.state_store.complete_step(
            state, status="succeeded", prerequisites={},
            output_refs=[artifact_ref("segment-analysis", analysis, "analysis/segment-analysis.yaml")],
            tool_versions={"segment-analyzer": TOOL_VERSION}, next_step="brief",
        )
        return {"state": state.to_dict(), "receipt": receipt.to_dict(), "analysis": analysis}

    def _build_analysis(self, request: dict[str, Any], inputs: dict[str, Any]) -> dict[str, Any]:
        source_ref = f"request:{request['request_id']}"
        evidence = [
            {"path": "/purpose", "value_origin": "user_decision",
             "value": request["purpose"], "source_ref": source_ref},
            {"path": "/kind", "value_origin": "user_decision",
             "value": request["kind"], "source_ref": source_ref},
            {"path": "/targets", "value_origin": "user_decision",
             "value": request["targets"], "source_ref": source_ref},
        ]
        for decision in request.get("decisions", []):
            evidence.append({"path": decision["path"], "value_origin": "user_decision",
                             "value": decision["value"], "source_ref": decision["source_ref"]})
        analysis = {
            "schema_version": 1,
            "analysis_id": f"analysis-{request['request_id']}",
            "request_digest": sha256_digest(request),
            "design_digest": inputs["design_digest"],
            "kind": request["kind"],
            "evidence_records": evidence,
            "open_questions": [],
        }
        self.registry.validate("segment-analysis", analysis)
        return analysis

    def _build_brief(self, request: dict[str, Any], inputs: dict[str, Any],
                     analysis: dict[str, Any]) -> dict[str, Any]:
        brief = {
            "schema_version": 1,
            "brief_id": f"brief-{request['request_id']}",
            "kind": request["kind"],
            "namespace": request["namespace"],
            "template_id": request["template_id"],
            "version": request["version"],
            "scope": request["scope"],
            "purpose": request["purpose"],
            "audience": request["audience"],
            "reuse_intent": request["reuse_intent"],
            "supported_uses": request["supported_uses"],
            "excluded_uses": request["excluded_uses"],
            "authoring_mode": request["authoring_mode"],
            "targets": request["targets"],
            "design_digest": inputs["design_digest"],
            "evidence_records": analysis["evidence_records"],
            "decisions": [r for r in analysis["evidence_records"] if r["value_origin"] == "user_decision"],
            "open_questions": analysis["open_questions"],
            "revision": 1,
        }
        self.registry.validate("segment-brief", brief)
        return brief

    @serialized_workflow_step
    def brief(self, request_path: str | Path) -> dict[str, Any]:
        request = self._load_segment_request(request_path)
        inputs = self._segment_inputs(request)
        state = self.state_store.resume(inputs, {})
        self._require_step(state.step, "brief")
        analysis = self._load_yaml("analysis/segment-analysis.yaml", "segment-analysis")
        self._verify_last_output("segment-analysis", analysis)
        brief = self._build_brief(request, inputs, analysis)
        brief_path = self.path_guard.resolve(self.work_root / "segment_brief.yaml")
        atomic_yaml(brief_path, brief)
        state, receipt = self.state_store.complete_step(
            state, status="succeeded", prerequisites={"analysis": analysis},
            output_refs=[artifact_ref("segment-brief", brief, "segment_brief.yaml")],
            tool_versions={"segment-brief-builder": TOOL_VERSION}, next_step="author",
        )
        return {"state": state.to_dict(), "receipt": receipt.to_dict(), "brief": brief}

    def _author_kwargs(self, request: dict[str, Any]) -> dict[str, Any]:
        return dict(
            kind=request["kind"], namespace=request["namespace"],
            template_id=request["template_id"], version=request["version"],
            contract=request["design"], summary=request["purpose"],
            requested_at=request["requested_at"], lock_id=f"lock-{request['request_id']}",
            registry=self.registry,
        )

    @serialized_workflow_step
    def author(self, request_path: str | Path) -> dict[str, Any]:
        package_root = self.path_guard.resolve(self.work_root / "staging/package")
        package_exists = package_root.exists()
        if package_exists and self.state_store.load().step != "author":
            raise ProtocolError("STAGING_PACKAGE_EXISTS", str(package_root))
        request = self._load_segment_request(request_path)
        inputs = self._segment_inputs(request)
        analysis = self._load_yaml("analysis/segment-analysis.yaml", "segment-analysis")
        state = self.state_store.resume(inputs, {"analysis": analysis})
        if package_exists and state.step != "author":
            raise ProtocolError("STAGING_PACKAGE_EXISTS", str(package_root))
        self._require_step(state.step, "author")
        brief = self._load_yaml("segment_brief.yaml", "segment-brief")
        self._verify_last_output("segment-brief", brief)
        kwargs = self._author_kwargs(request)
        package = (
            verify_segment_package(self.path_guard, self.work_root, **kwargs)
            if package_exists
            else author_segment_package(self.path_guard, self.work_root, **kwargs)
        )
        package_ref = {"id": "staging-package", "version": request["version"],
                       "digest": package["package_digest"], "uri": "staging/package"}
        state, step_receipt = self.state_store.complete_step(
            state, status="succeeded", prerequisites={"analysis": analysis, "brief": brief},
            output_refs=[package_ref], tool_versions={"segment-author": TOOL_VERSION},
            next_step="validate",
        )
        return {"state": state.to_dict(), "receipt": step_receipt.to_dict(), "package": package}

    @serialized_workflow_step
    def validate(self, request_path: str | Path, *, attestation_key: bytes,
                 browser: str | Path | None = None, font_path: str | Path | None = None,
                 repository_root: str | Path | None = None,
                 repository_scope: str | None = None,
                 publication_request: str | Path | None = None) -> dict[str, Any]:
        request, inputs, state = self._resume_request(request_path)
        self._require_step(state.step, "validate")
        expected = self._expected_validation(request)
        package_root = self.path_guard.resolve(self.work_root / "staging/package", must_exist=True)
        validation_relative = Path("validation")
        if state.attempt > 1:
            validation_relative /= f"attempt-{state.attempt}"
        validation_root = self.path_guard.resolve(self.work_root / validation_relative)
        validator = SegmentPackageValidator(
            path_guard=self.path_guard, package_root=package_root, evidence_root=validation_root,
            attestation_key=attestation_key, registry=self.registry, font_path=font_path,
            context=self._validation_context(request, state))
        evidence = validator.validate(expected, request["targets"], request["design"])
        authored_digest = self._last_output_digest("staging-package")
        if evidence["status"] == "passed" and evidence["package_ref"]["digest"] != authored_digest:
            raise ProtocolError("JOB_PREREQUISITE_DRIFT", state.run_id)
        evidence_ref = {"id": "template-validation-evidence", "version": "1.0.0",
                        "digest": evidence["evidence_digest"],
                        "uri": (validation_relative / "segment-validation-evidence.yaml").as_posix()}
        passed = evidence["status"] == "passed"
        # §5.2 default draft endpoint: a passed validation ends at validated-draft unless a
        # trusted READY publication-request explicitly authorizes advancing to prepare-publish.
        # The orchestrator never auto-follows publication; an intent-only request still stops.
        publish_ready = False
        if passed and publication_request is not None:
            pub = self._load_publication_request(publication_request, request)
            publish_ready = pub["intent_state"] == "ready"
        next_step = "prepare-publish" if (passed and publish_ready) else None
        state, step_receipt = self.state_store.complete_step(
            state, status="succeeded" if passed else "failed",
            prerequisites={"package_ref": evidence["package_ref"]}, output_refs=[evidence_ref],
            tool_versions={"segment-validator": "1.0.0"},
            next_step=next_step,
            error=None if passed else {"code": "TEMPLATE_VALIDATION_FAILED", "message": "segment validation failed"},
        )
        result_kind = ("ready-to-publish" if (passed and publish_ready)
                       else "validated-draft" if passed else "failed")
        return {"state": state.to_dict(), "receipt": step_receipt.to_dict(),
                "evidence": evidence, "result_kind": result_kind}

    def _load_publication_request(self, publication_request: str | Path,
                                  request: dict[str, Any]) -> dict[str, Any]:
        resolved = self._resolve_project_path(publication_request, must_exist=True)
        pub = load_document(resolved)
        self.registry.validate("publication-request", pub)
        if pub["request_id"] != request["request_id"] or pub["kind"] != request["kind"]:
            raise ProtocolError("PUBLICATION_REQUEST_BINDING_MISMATCH", request["request_id"])
        return pub

    @serialized_workflow_step
    def import_draft(self, request_path: str | Path) -> dict[str, Any]:
        """A->B deferred publication entry (design §8.4): import a finished creation run A's
        immutable draft/evidence into a NEW publication run B, then continue author->validate->
        prepare-publish->publish under B's own final identity.

        A is only READ: it must already be a finished creation run (succeeded/validate). The
        source binding (request.source_import) pins A.run_id, draft content digest and evidence
        digest; B's design must equal A's draft content exactly. The import receipt references the
        original draft/evidence by digest — it never copies or re-signs A's step receipts. B's
        input fingerprint covers the source binding via the request, so a changed source/design
        cannot sneak through a failed-step retry. No second state machine: B reuses this class.
        """
        request = self._load_segment_request(request_path)
        source = request.get("source_import")
        if source is None:
            raise ProtocolError("IMPORT_SOURCE_REQUIRED", request["request_id"])
        self._validate_design(request)
        inputs = self._segment_inputs(request)
        source_run_root = self._resolve_project_path(source["source_run_uri"], must_exist=True)
        source_state = load_document(source_run_root / "job-state.json")
        if not isinstance(source_state, dict) or source_state.get("run_id") != source["source_run_id"]:
            raise ProtocolError("IMPORT_SOURCE_RUN_MISMATCH", source["source_run_id"])
        if source_state.get("status") != "succeeded" or source_state.get("step") != "validate":
            raise ProtocolError("IMPORT_SOURCE_NOT_FINISHED", source["source_run_id"])
        evidence_path = self._resolve_project_path(source["source_evidence_uri"], must_exist=True)
        evidence = load_document(evidence_path)
        if not isinstance(evidence, dict):
            raise ProtocolError("IMPORT_EVIDENCE_INVALID", source["source_evidence_uri"])
        self.registry.validate("segment-validation-evidence", evidence)
        if evidence["evidence_digest"] != source["source_evidence_digest"]:
            raise ProtocolError("IMPORT_EVIDENCE_DRIFT", source["source_run_id"])
        if evidence["status"] != "passed":
            raise ProtocolError("IMPORT_EVIDENCE_NOT_PASSED", source["source_run_id"])
        if evidence["design_digest"] != source["source_draft_digest"]:
            raise ProtocolError("IMPORT_DRAFT_DRIFT", source["source_run_id"])
        if sha256_digest(request["design"]) != source["source_draft_digest"]:
            raise ProtocolError("IMPORT_DESIGN_DRIFT", request["request_id"])
        state = self.state_store.initialize(request["request_id"], inputs, step="import-draft")
        record = {
            "schema_version": 1,
            "import_id": f"import-{request['request_id']}",
            "source_run_id": source["source_run_id"],
            "source_draft_digest": source["source_draft_digest"],
            "source_evidence_digest": source["source_evidence_digest"],
            "source_evidence_id": evidence["evidence_id"],
            "imported_design_digest": sha256_digest(request["design"]),
            "created_at": utc_now(),
        }
        self.registry.validate("draft-import-record", record)
        record_path = self.path_guard.resolve(self.work_root / "import/draft-import-record.yaml")
        atomic_yaml(record_path, record)
        # B folds analyze+brief into import-draft (design §8.4: import-draft -> author). The same
        # builders materialize the analysis/brief artifacts author consumes; the import receipt's
        # prerequisite fingerprint binds the analysis so author's resume check lines up. A's step
        # receipts are never copied or re-signed.
        analysis = self._build_analysis(request, inputs)
        atomic_yaml(self.path_guard.resolve(self.work_root / "analysis/segment-analysis.yaml"), analysis)
        brief = self._build_brief(request, inputs, analysis)
        atomic_yaml(self.path_guard.resolve(self.work_root / "segment_brief.yaml"), brief)
        state, receipt = self.state_store.complete_step(
            state, status="succeeded", prerequisites={"analysis": analysis},
            output_refs=[
                artifact_ref("draft-import-record", record, "import/draft-import-record.yaml"),
                artifact_ref("segment-analysis", analysis, "analysis/segment-analysis.yaml"),
                artifact_ref("segment-brief", brief, "segment_brief.yaml"),
            ],
            tool_versions={"segment-importer": TOOL_VERSION}, next_step="author",
        )
        return {"state": state.to_dict(), "receipt": receipt.to_dict(), "import_record": record}

    def _verify_for_publish(self, evidence, request, state, package_root, evidence_path,
                            attestation_key, repository):
        validator = SegmentPackageValidator(
            path_guard=self.path_guard, package_root=package_root, evidence_root=evidence_path.parent,
            attestation_key=attestation_key, registry=self.registry, font_path=None,
            context=self._validation_context(request, state))
        return validator.verify_evidence(evidence, self._expected_validation(request),
                                         request["targets"], request["design"])