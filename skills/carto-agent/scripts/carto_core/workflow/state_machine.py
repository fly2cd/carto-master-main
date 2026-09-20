from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Iterator, TypeVar

from ..canonical import sha256_digest
from ..errors import ProtocolError
from ..schema_registry import SchemaRegistry
from .models import JobState, StepReceipt


F = TypeVar("F", bound=Callable[..., Any])


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        temporary = Path(name)
        if temporary.exists():
            temporary.unlink()


def _create_json_once(path: Path, value: dict[str, Any]) -> None:
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ProtocolError("IMMUTABLE_ARTIFACT_INVALID", str(path)) from exc
        if existing != value:
            raise ProtocolError("IMMUTABLE_ARTIFACT_CONFLICT", str(path))
        return
    _atomic_json(path, value)


class _RunFileLock:
    def __init__(self, path: Path, timeout_seconds: float) -> None:
        self.path = path
        self.timeout_seconds = timeout_seconds
        self._stream: Any = None

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._stream = self.path.open("a+b")
        if self.path.stat().st_size == 0:
            self._stream.write(b"\0")
            self._stream.flush()
        deadline = time.monotonic() + self.timeout_seconds
        while True:
            try:
                self._try_lock()
                return
            except (BlockingIOError, OSError):
                if time.monotonic() >= deadline:
                    self._stream.close()
                    self._stream = None
                    raise ProtocolError("JOB_OPERATION_LOCKED", str(self.path))
                time.sleep(0.05)

    def release(self) -> None:
        if self._stream is None:
            return
        try:
            self._unlock()
        finally:
            self._stream.close()
            self._stream = None

    def _try_lock(self) -> None:
        self._stream.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(self._stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(self._stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _unlock(self) -> None:
        self._stream.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(self._stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(self._stream.fileno(), fcntl.LOCK_UN)


def serialized_workflow_step(function: F) -> F:
    """Hold the run-wide single-writer lock for one public workflow mutation."""

    @wraps(function)
    def wrapped(self: Any, *args: Any, **kwargs: Any) -> Any:
        with self.state_store.operation():
            return function(self, *args, **kwargs)

    return wrapped  # type: ignore[return-value]


class WorkflowStateStore:
    def __init__(self, run_root: Path, registry: SchemaRegistry | None = None,
                 *, lock_timeout_seconds: float = 10.0) -> None:
        self.run_root = run_root.resolve()
        self.registry = registry or SchemaRegistry()
        self.state_path = self.run_root / "job-state.json"
        self.transition_path = self.run_root / ".state-transition.json"
        self.lock_path = self.run_root / ".workflow.lock"
        self.lock_timeout_seconds = lock_timeout_seconds
        self._thread_lock = threading.RLock()
        self._local = threading.local()
        self._last_recovery = False

    @contextmanager
    def operation(self) -> Iterator[None]:
        """Serialize a complete workflow step across threads and processes."""
        with self._thread_lock:
            depth = getattr(self._local, "depth", 0)
            lock: _RunFileLock | None = None
            if depth == 0:
                lock = _RunFileLock(self.lock_path, self.lock_timeout_seconds)
                lock.acquire()
                self._local.started_at = _now()
                self._local.lock = lock
            self._local.depth = depth + 1
            try:
                yield
            finally:
                self._local.depth -= 1
                if self._local.depth == 0:
                    held = getattr(self._local, "lock", None)
                    self._local.started_at = None
                    self._local.lock = None
                    if held is not None:
                        held.release()

    def initialize(self, run_id: str, inputs: Any, step: str = "intake") -> JobState:
        with self.operation():
            if self.state_path.exists():
                self._recover_unlocked()
                raise ProtocolError("JOB_ALREADY_EXISTS", run_id)
            state = JobState(1, 1, "pending", step, 1, run_id, sha256_digest(inputs))
            self._write_state_unlocked(state)
            return state

    def load(self) -> JobState:
        with self.operation():
            self._last_recovery = self._recover_unlocked()
            return self._read_state_unlocked()

    def recovery_status(self) -> dict[str, Any]:
        return {
            "recovered_transition": self._last_recovery,
            "pending_transition": self.transition_path.exists(),
        }

    def resume(self, inputs: Any, prerequisites: dict[str, Any]) -> JobState:
        with self.operation():
            state = self.load()
            if sha256_digest(inputs) != state.input_fingerprint:
                raise ProtocolError("JOB_INPUT_DRIFT", state.run_id)
            if state.last_receipt and state.status != "failed":
                receipt = self._read_receipt_unlocked(state.last_receipt)
                expected = {key: sha256_digest(value) for key, value in prerequisites.items()}
                if receipt["prerequisite_fingerprints"] != expected:
                    raise ProtocolError("JOB_PREREQUISITE_DRIFT", state.run_id)
            return state

    def complete_step(
        self,
        state: JobState,
        *,
        status: str,
        prerequisites: dict[str, Any],
        output_refs: list[dict[str, str]],
        tool_versions: dict[str, str] | None = None,
        next_step: str | None = None,
        error: dict[str, Any] | None = None,
    ) -> tuple[JobState, StepReceipt]:
        with self.operation():
            self._recover_unlocked()
            current = self._read_state_unlocked()
            self._require_current(state, current)
            completed_at = _now()
            started_at = getattr(self._local, "started_at", None) or completed_at
            body = {
                "run_id": state.run_id,
                "step": state.step,
                "attempt": state.attempt,
                "status": status,
                "input_fingerprint": state.input_fingerprint,
                "prerequisite_fingerprints": {
                    key: sha256_digest(value) for key, value in prerequisites.items()
                },
                "tool_versions": dict(tool_versions or {}),
                "output_refs": output_refs,
                "started_at": started_at,
                "completed_at": completed_at,
                "error": error,
            }
            receipt = StepReceipt(1, f"receipt-{sha256_digest(body)[7:23]}", **body)
            receipt_value = receipt.to_dict()
            if error is None:
                receipt_value.pop("error")
            self.registry.validate("step-receipt", receipt_value)
            relative = Path("receipts") / (
                f"{state.step}-{state.attempt}-{sha256_digest(receipt_value)[7:19]}.json"
            )
            next_status = status if next_step is None or status == "waiting_approval" else "pending"
            new_state = replace(
                state,
                revision=state.revision + 1,
                status=next_status,
                step=next_step or state.step,
                attempt=1 if next_step else state.attempt,
                last_receipt=relative.as_posix(),
            )
            transition_basis = {
                "run_id": state.run_id,
                "expected_revision": state.revision,
                "receipt_path": relative.as_posix(),
                "receipt_digest": sha256_digest(receipt_value),
                "previous_state": state.to_dict(),
                "next_state": new_state.to_dict(),
                "created_at": completed_at,
            }
            transition = {
                "schema_version": 1,
                "transition_id": f"transition-{sha256_digest(transition_basis)[7:23]}",
                **transition_basis,
            }
            self.registry.validate("job-state", new_state.to_dict())
            self.registry.validate("state-transition", transition)
            _atomic_json(self.transition_path, transition)
            _create_json_once(self.run_root / relative, receipt_value)
            self._write_state_unlocked(new_state)
            self.transition_path.unlink()
            return new_state, receipt

    def retry(self, state: JobState | None = None) -> JobState:
        with self.operation():
            self._recover_unlocked()
            current = self._read_state_unlocked()
            if state is not None:
                self._require_current(state, current)
            if current.status != "failed":
                raise ProtocolError("JOB_RETRY_NOT_ALLOWED", f"status={current.status}")
            updated = replace(
                current,
                revision=current.revision + 1,
                status="pending",
                attempt=current.attempt + 1,
            )
            self._write_state_unlocked(updated)
            return updated

    def receipts(self) -> list[dict[str, Any]]:
        with self.operation():
            self._recover_unlocked()
            root = self.run_root / "receipts"
            if not root.exists():
                return []
            result: list[dict[str, Any]] = []
            for path in sorted(root.glob("*.json")):
                value = json.loads(path.read_text(encoding="utf-8"))
                self.registry.validate("step-receipt", value)
                result.append({"path": path.relative_to(self.run_root).as_posix(), "receipt": value})
            result.sort(key=lambda item: (
                item["receipt"]["completed_at"], item["receipt"]["step"], item["receipt"]["attempt"]
            ))
            return result

    def find_output_ref(self, artifact_id: str) -> dict[str, str]:
        for item in reversed(self.receipts()):
            receipt = item["receipt"]
            if receipt["status"] == "failed":
                continue
            for output in receipt["output_refs"]:
                if output["id"] == artifact_id:
                    return dict(output)
        raise ProtocolError("WORKFLOW_RECEIPT_MISSING", artifact_id)

    def find_output_digest(self, artifact_id: str) -> str:
        return self.find_output_ref(artifact_id)["digest"]

    def _read_state_unlocked(self) -> JobState:
        if not self.state_path.exists():
            raise ProtocolError("JOB_STATE_NOT_FOUND", str(self.state_path))
        try:
            value = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ProtocolError("JOB_STATE_INVALID", str(self.state_path)) from exc
        self.registry.validate("job-state", value)
        return JobState(**value)

    def _read_receipt_unlocked(self, relative: str) -> dict[str, Any]:
        receipt_root = (self.run_root / "receipts").resolve()
        receipt_path = (self.run_root / relative).resolve()
        try:
            receipt_path.relative_to(receipt_root)
        except ValueError as exc:
            raise ProtocolError("STEP_RECEIPT_PATH_INVALID", relative) from exc
        if not receipt_path.is_file():
            raise ProtocolError("STEP_RECEIPT_NOT_FOUND", relative)
        try:
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ProtocolError("STEP_RECEIPT_INVALID", relative) from exc
        self.registry.validate("step-receipt", receipt)
        return receipt

    def _recover_unlocked(self) -> bool:
        if not self.transition_path.exists():
            return False
        try:
            transition = json.loads(self.transition_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ProtocolError("JOB_TRANSITION_INVALID", str(self.transition_path)) from exc
        self.registry.validate("state-transition", transition)
        previous = JobState(**transition["previous_state"])
        following = JobState(**transition["next_state"])
        if (
            transition["run_id"] != previous.run_id
            or following.run_id != previous.run_id
            or transition["expected_revision"] != previous.revision
            or following.revision != previous.revision + 1
        ):
            raise ProtocolError("JOB_TRANSITION_INVALID", transition["transition_id"])
        try:
            receipt = self._read_receipt_unlocked(transition["receipt_path"])
        except ProtocolError as exc:
            if exc.code == "STEP_RECEIPT_NOT_FOUND":
                raise ProtocolError("JOB_TRANSITION_INCOMPLETE", transition["transition_id"]) from exc
            raise
        if sha256_digest(receipt) != transition["receipt_digest"]:
            raise ProtocolError("JOB_TRANSITION_RECEIPT_DRIFT", transition["transition_id"])
        current = self._read_state_unlocked()
        if current.to_dict() == previous.to_dict():
            self._write_state_unlocked(following)
        elif current.to_dict() != following.to_dict():
            raise ProtocolError("JOB_TRANSITION_CONFLICT", transition["transition_id"])
        self.transition_path.unlink()
        return True

    @staticmethod
    def _require_current(expected: JobState, current: JobState) -> None:
        if expected.revision != current.revision or expected.to_dict() != current.to_dict():
            raise ProtocolError(
                "JOB_STATE_STALE",
                f"expected_revision={expected.revision}; actual_revision={current.revision}",
            )

    def _write_state_unlocked(self, state: JobState) -> None:
        value = state.to_dict()
        self.registry.validate("job-state", value)
        _atomic_json(self.state_path, value)