from __future__ import annotations

from pathlib import Path
from typing import Any

from ..adapters.controlled_renderer import BrowserLimits
from ..adapters.render_backend import create_render_backend
from ..canonical import sha256_digest
from ..errors import CartoError, ProtocolError
from ..scenario_registry import ScenarioRegistry
from ..schema_registry import SchemaRegistry, load_document
from ..security.paths import PathGuard
from ..artifacts import atomic_yaml, file_digest, utc_now


FORMAL_TARGET_ID = "formal-map"
REQUIRED_TARGETS = frozenset({"pdf", "png"})
TRANSIENT_RENDER_ERRORS = frozenset({
    "RENDER_TIMEOUT",
    "RENDER_BROWSER_FAILED",
    "RENDER_BROWSER_COMMAND_FAILED",
    "RENDER_BROWSER_NOT_READY",
    "RENDER_BROWSER_START_TIMEOUT",
    "RENDER_DEBUG_CONNECTION_CLOSED",
})


class FormalMapRenderService:
    """Perform one immutable formal render attempt from a frozen RenderScene."""

    def __init__(
        self,
        *,
        path_guard: PathGuard,
        work_root: Path,
        attestation_key: bytes,
        browser: str | Path | None = None,
        registry: SchemaRegistry | None = None,
        limits: BrowserLimits | None = None,
        renderer_id: str = "maplibre-web",
        project_root: Path | None = None,
        context=None,
    ) -> None:
        self.path_guard = path_guard
        self.work_root = path_guard.resolve(work_root, must_exist=True)
        self.registry = registry or SchemaRegistry()
        self.attestation_key = attestation_key
        self.limits = limits or BrowserLimits()
        self.browser = browser
        self.renderer_id, self.project_root, self.context = renderer_id, project_root, context
        self.backend = self._backend(self.work_root / "output")
        self.profile = self.backend.profile

    def _backend(self, output_root):
        return create_render_backend(self.renderer_id, path_guard=self.path_guard, output_root=output_root,
            attestation_key=self.attestation_key, browser=self.browser, limits=self.limits, registry=self.registry,
            project_root=self.project_root, context=self.context)

    @property
    def profile_digest(self) -> str:
        return self.profile.profile_digest()

    @property
    def environment_fingerprint(self) -> str:
        return self.backend.environment_fingerprint

    def validate_environment(self, lock: dict[str, Any], preview_receipt: dict[str, Any]) -> None:
        if (preview_receipt["renderer_profile_digest"] != self.profile_digest
                or preview_receipt["renderer_id"] != self.renderer_id
                or lock["environment_fingerprint"] != self.environment_fingerprint
                or lock["execution"]["environment"] != self.backend.environment_snapshot()):
            raise ProtocolError("RENDER_ENVIRONMENT_DRIFT", "Renderer differs from the G2-bound preview and lock")

    def validate_scene(self, scene: dict[str, Any], execution: dict[str, Any]) -> None:
        profile = ScenarioRegistry(self.registry).for_execution(execution)
        profile.require_scene(scene)
        self.backend.validate_scene(scene, execution)
        if not REQUIRED_TARGETS.issubset(scene["export"]["targets"]):
            raise ProtocolError("ENCODING_SEMANTICS_INVALID", "Formal rendering requires locked PDF and PNG targets")
        if self.backend.scene_texts(scene).count(profile.notice) != 1:
            raise ProtocolError("ENCODING_SEMANTICS_INVALID", "Locked scene must contain the scenario disclosure exactly once")

    def attempt_id(self, run_id: str, attempt_number: int) -> str:
        return f"render-attempt-{run_id}-{attempt_number}"

    def attempt_record_path(self, attempt_id: str) -> Path:
        return self.path_guard.resolve(self.work_root / "render-attempts" / f"{attempt_id}.yaml")

    def evidence_path(self, run_id: str, attempt_number: int) -> Path:
        return self.path_guard.resolve(
            self.work_root / "formal-render" / f"formal-render-{run_id}-{attempt_number}.yaml"
        )

    def output_directory(self, lock_id: str, attempt_id: str) -> Path:
        return self.path_guard.resolve(self.work_root / "output" / lock_id / FORMAL_TARGET_ID / attempt_id)

    def previous_attempt_ref(self, run_id: str, attempt_number: int) -> dict[str, str] | None:
        if attempt_number <= 1:
            return None
        previous_id = self.attempt_id(run_id, attempt_number - 1)
        previous_path = self.attempt_record_path(previous_id)
        previous = load_document(self.path_guard.resolve(previous_path, must_exist=True))
        if not isinstance(previous, dict):
            raise ProtocolError("RENDER_ATTEMPT_INVALID", previous_id)
        self.registry.validate("render-attempt", previous)
        return {
            "id": previous_id,
            "version": "1.0.0",
            "digest": sha256_digest(previous),
            "uri": str(previous_path),
        }

    def render(
        self,
        *,
        request: dict[str, Any],
        lock: dict[str, Any],
        lock_ref: dict[str, str],
        scene: dict[str, Any],
        attempt_number: int,
        started_at: str,
    ) -> dict[str, Any]:
        self.validate_scene(scene, lock["execution"])
        attempt_id = self.attempt_id(request["run_id"], attempt_number)
        target_root = self.path_guard.resolve(
            self.work_root / "output" / lock["lock_id"] / FORMAL_TARGET_ID
        )
        target_root.mkdir(parents=True, exist_ok=True)
        output_directory = self.output_directory(lock["lock_id"], attempt_id)
        if output_directory.exists():
            raise ProtocolError("RENDER_ATTEMPT_INCOMPLETE", str(output_directory))
        backend = self._backend(target_root)
        receipt = backend.render(attempt_id, scene)
        backend.validate_receipt(scene, receipt, expected_session_id=attempt_id)
        receipt_path = self.path_guard.resolve(output_directory / "render-receipt.yaml")
        atomic_yaml(receipt_path, receipt)
        completed_at = receipt["render_completed_at"]
        attempt: dict[str, Any] = {
            "schema_version": 1,
            "attempt_id": attempt_id,
            "project_id": request["project_id"],
            "run_id": request["run_id"],
            "lock_ref": lock_ref,
            "lock_digest": sha256_digest(lock),
            "business_execution_digest": lock["execution_digest"],
            "target_id": FORMAL_TARGET_ID,
            "attempt_number": attempt_number,
            "status": "succeeded",
            "render_scene_digest": sha256_digest(scene),
            "renderer_profile_digest": receipt["renderer_profile_digest"],
            "renderer_execution_digest": receipt["execution_digest"],
            "resource_set_digest": receipt["resource_set_digest"],
            "environment_fingerprint": receipt["environment_fingerprint"],
            "output_artifacts": [
                {"target": item["target"], "artifact_ref": item["artifact_ref"]}
                for item in receipt["output_artifacts"]
            ],
            "render_receipt_ref": {
                "id": receipt["receipt_id"],
                "version": "1.0.0",
                "digest": sha256_digest(receipt),
                "uri": str(receipt_path),
            },
            "retryable": False,
            "started_at": started_at,
            "completed_at": completed_at,
        }
        previous = self.previous_attempt_ref(request["run_id"], attempt_number)
        if previous is not None:
            attempt["previous_attempt_ref"] = previous
        self.registry.validate("render-attempt", attempt)
        attempt_path = self.attempt_record_path(attempt_id)
        atomic_yaml(attempt_path, attempt)
        evidence = self.build_evidence(request, lock, lock_ref, attempt, attempt_path, receipt, completed_at)
        evidence_path = self.evidence_path(request["run_id"], attempt_number)
        atomic_yaml(evidence_path, evidence)
        return {
            "attempt": attempt,
            "attempt_path": attempt_path,
            "receipt": receipt,
            "receipt_path": receipt_path,
            "evidence": evidence,
            "evidence_path": evidence_path,
        }

    def record_failure(
        self,
        *,
        request: dict[str, Any],
        lock: dict[str, Any],
        lock_ref: dict[str, str],
        scene: dict[str, Any],
        attempt_number: int,
        started_at: str,
        error: CartoError,
        retryable: bool,
    ) -> tuple[dict[str, Any], Path]:
        attempt_id = self.attempt_id(request["run_id"], attempt_number)
        attempt: dict[str, Any] = {
            "schema_version": 1,
            "attempt_id": attempt_id,
            "project_id": request["project_id"],
            "run_id": request["run_id"],
            "lock_ref": lock_ref,
            "lock_digest": sha256_digest(lock),
            "business_execution_digest": lock["execution_digest"],
            "target_id": FORMAL_TARGET_ID,
            "attempt_number": attempt_number,
            "status": "failed",
            "render_scene_digest": sha256_digest(scene),
            "renderer_profile_digest": self.profile_digest,
            "environment_fingerprint": self.environment_fingerprint,
            "retryable": retryable,
            "error": {"code": error.code, "message": error.message},
            "started_at": started_at,
            "completed_at": utc_now(),
        }
        if retryable:
            attempt["retry_reason"] = error.code
        previous = self.previous_attempt_ref(request["run_id"], attempt_number)
        if previous is not None:
            attempt["previous_attempt_ref"] = previous
        self.registry.validate("render-attempt", attempt)
        path = self.attempt_record_path(attempt_id)
        atomic_yaml(path, attempt)
        return attempt, path

    def build_evidence(
        self,
        request: dict[str, Any],
        lock: dict[str, Any],
        lock_ref: dict[str, str],
        attempt: dict[str, Any],
        attempt_path: Path,
        receipt: dict[str, Any],
        created_at: str,
    ) -> dict[str, Any]:
        body = {
            "schema_version": 1,
            "evidence_id": f"formal-render-{request['run_id']}-{attempt['attempt_number']}",
            "project_id": request["project_id"],
            "run_id": request["run_id"],
            "lock_ref": lock_ref,
            "lock_digest": sha256_digest(lock),
            "business_execution_digest": lock["execution_digest"],
            "attempt_ref": {
                "id": attempt["attempt_id"],
                "version": "1.0.0",
                "digest": sha256_digest(attempt),
                "uri": str(attempt_path),
            },
            "attempt_digest": sha256_digest(attempt),
            "render_scene_digest": attempt["render_scene_digest"],
            "renderer_profile_digest": attempt["renderer_profile_digest"],
            "renderer_execution_digest": attempt["renderer_execution_digest"],
            "resource_set_digest": attempt["resource_set_digest"],
            "environment_fingerprint": attempt["environment_fingerprint"],
            "render_receipt_ref": attempt["render_receipt_ref"],
            "output_artifacts": [
                {
                    "target": item["target"],
                    "artifact_ref": item["artifact_ref"],
                    "size_bytes": item["size_bytes"],
                    "media_type": item["media_type"],
                }
                for item in receipt["output_artifacts"]
            ],
            "required_targets": ["pdf", "png"],
            "scenario_notice": ScenarioRegistry(self.registry).for_execution(lock["execution"]).notice,
            "quality_status": "not-checked",
            "created_at": created_at,
        }
        evidence = {**body, "evidence_digest": sha256_digest(body)}
        self.registry.validate("formal-render-evidence", evidence)
        return evidence

    def load_existing(
        self,
        *,
        request: dict[str, Any],
        lock: dict[str, Any],
        lock_ref: dict[str, str],
        scene: dict[str, Any],
        attempt_number: int,
        verify_outputs: bool = True,
    ) -> dict[str, Any] | None:
        attempt_id = self.attempt_id(request["run_id"], attempt_number)
        attempt_path = self.attempt_record_path(attempt_id)
        if not attempt_path.exists():
            return None
        attempt = load_document(self.path_guard.resolve(attempt_path, must_exist=True))
        if not isinstance(attempt, dict):
            raise ProtocolError("RENDER_ATTEMPT_INVALID", attempt_id)
        self.registry.validate("render-attempt", attempt)
        expected = {
            "attempt_id": attempt_id,
            "project_id": request["project_id"],
            "run_id": request["run_id"],
            "lock_ref": lock_ref,
            "lock_digest": sha256_digest(lock),
            "business_execution_digest": lock["execution_digest"],
            "target_id": FORMAL_TARGET_ID,
            "attempt_number": attempt_number,
            "render_scene_digest": sha256_digest(scene),
            "renderer_profile_digest": self.profile_digest,
            "environment_fingerprint": self.environment_fingerprint,
        }
        if any(attempt.get(key) != value for key, value in expected.items()):
            raise ProtocolError("RENDER_ATTEMPT_BINDING_MISMATCH", attempt_id)
        if attempt["status"] == "failed":
            return {"attempt": attempt, "attempt_path": attempt_path}
        receipt_path = self.path_guard.resolve(attempt["render_receipt_ref"]["uri"], must_exist=True)
        receipt = load_document(receipt_path)
        if not isinstance(receipt, dict) or sha256_digest(receipt) != attempt["render_receipt_ref"]["digest"]:
            raise ProtocolError("RENDER_ATTEMPT_RECEIPT_DRIFT", attempt_id)
        backend = self._backend(self.work_root / "output" / lock["lock_id"] / FORMAL_TARGET_ID)
        backend.validate_receipt(scene, receipt, verify_outputs=verify_outputs, expected_session_id=attempt_id)
        if receipt["execution_digest"] != attempt["renderer_execution_digest"]:
            raise ProtocolError("RENDER_ATTEMPT_RECEIPT_DRIFT", attempt_id)
        evidence_path = self.evidence_path(request["run_id"], attempt_number)
        if evidence_path.exists():
            evidence = load_document(self.path_guard.resolve(evidence_path, must_exist=True))
            if not isinstance(evidence, dict):
                raise ProtocolError("FORMAL_RENDER_EVIDENCE_INVALID", attempt_id)
        else:
            evidence = self.build_evidence(
                request, lock, lock_ref, attempt, attempt_path, receipt, attempt["completed_at"]
            )
            atomic_yaml(evidence_path, evidence)
        self.validate_evidence(
            evidence, lock, lock_ref, attempt, attempt_path, receipt, verify_outputs=verify_outputs
        )
        return {
            "attempt": attempt,
            "attempt_path": attempt_path,
            "receipt": receipt,
            "receipt_path": receipt_path,
            "evidence": evidence,
            "evidence_path": evidence_path,
        }

    def validate_evidence(
        self,
        evidence: dict[str, Any],
        lock: dict[str, Any],
        lock_ref: dict[str, str],
        attempt: dict[str, Any],
        attempt_path: Path,
        receipt: dict[str, Any],
        *,
        verify_outputs: bool = True,
    ) -> None:
        self.registry.validate("formal-render-evidence", evidence)
        body = dict(evidence)
        supplied = body.pop("evidence_digest")
        if sha256_digest(body) != supplied:
            raise ProtocolError("FORMAL_RENDER_EVIDENCE_DIGEST_MISMATCH", evidence["evidence_id"])
        expected = self.build_evidence(
            {"project_id": lock["project_id"], "run_id": lock["run_id"]},
            lock,
            lock_ref,
            attempt,
            attempt_path,
            receipt,
            evidence["created_at"],
        )
        if evidence != expected:
            raise ProtocolError("FORMAL_RENDER_EVIDENCE_BINDING_MISMATCH", evidence["evidence_id"])
        targets = {item["target"] for item in evidence["output_artifacts"]}
        if not REQUIRED_TARGETS.issubset(targets):
            raise ProtocolError("FORMAL_RENDER_REQUIRED_OUTPUT_MISSING", evidence["evidence_id"])
        if verify_outputs:
            for item in receipt["output_artifacts"]:
                path = self.path_guard.resolve(item["artifact_ref"]["uri"], must_exist=True)
                if path.stat().st_size != item["size_bytes"] or file_digest(path) != item["artifact_ref"]["digest"]:
                    raise ProtocolError("FORMAL_RENDER_OUTPUT_DRIFT", item["target"])


def is_transient_render_error(error: CartoError) -> bool:
    return error.code in TRANSIENT_RENDER_ERRORS or error.code == "RENDER_ATTEMPT_INCOMPLETE"
