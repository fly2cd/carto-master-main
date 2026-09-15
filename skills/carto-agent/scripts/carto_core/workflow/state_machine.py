from __future__ import annotations

import json
import os
import tempfile
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..canonical import sha256_digest
from ..errors import ProtocolError
from ..schema_registry import SchemaRegistry
from .models import JobState, StepReceipt


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


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


class WorkflowStateStore:
    def __init__(self, run_root: Path, registry: SchemaRegistry | None = None) -> None:
        self.run_root = run_root.resolve()
        self.registry = registry or SchemaRegistry()
        self.state_path = self.run_root / "job-state.json"

    def initialize(self, run_id: str, inputs: Any, step: str = "intake") -> JobState:
        if self.state_path.exists():
            raise ProtocolError("JOB_ALREADY_EXISTS", run_id)
        state = JobState(1, "pending", step, 1, run_id, sha256_digest(inputs))
        self._write_state(state)
        return state

    def load(self) -> JobState:
        if not self.state_path.exists():
            raise ProtocolError("JOB_STATE_NOT_FOUND", str(self.state_path))
        value = json.loads(self.state_path.read_text(encoding="utf-8"))
        self.registry.validate("job-state", value)
        return JobState(**value)

    def resume(self, inputs: Any, prerequisites: dict[str, Any]) -> JobState:
        state = self.load()
        if sha256_digest(inputs) != state.input_fingerprint:
            raise ProtocolError("JOB_INPUT_DRIFT", state.run_id)
        if state.last_receipt:
            receipt_path = self.run_root / state.last_receipt
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            self.registry.validate("step-receipt", receipt)
            expected = {key: sha256_digest(value) for key, value in prerequisites.items()}
            if receipt["prerequisite_fingerprints"] != expected:
                raise ProtocolError("JOB_PREREQUISITE_DRIFT", state.run_id)
        return state

    def complete_step(self, state: JobState, *, status: str, prerequisites: dict[str, Any], output_refs: list[dict[str, str]], tool_versions: dict[str, str] | None = None, next_step: str | None = None, error: dict[str, Any] | None = None) -> tuple[JobState, StepReceipt]:
        timestamp = _now()
        body = {"run_id": state.run_id, "step": state.step, "attempt": state.attempt, "status": status, "input_fingerprint": state.input_fingerprint, "prerequisite_fingerprints": {key: sha256_digest(value) for key, value in prerequisites.items()}, "tool_versions": dict(tool_versions or {}), "output_refs": output_refs, "started_at": timestamp, "completed_at": timestamp, "error": error}
        receipt = StepReceipt(1, f"receipt-{sha256_digest(body)[7:23]}", **body)
        value = receipt.to_dict()
        if error is None:
            value.pop("error")
        self.registry.validate("step-receipt", value)
        relative = Path("receipts") / f"{state.step}-{state.attempt}-{sha256_digest(value)[7:19]}.json"
        target = self.run_root / relative
        if target.exists():
            raise ProtocolError("STEP_RECEIPT_ALREADY_EXISTS", str(relative))
        _atomic_json(target, value)
        new_state = replace(state, status="pending" if next_step else status, step=next_step or state.step, attempt=1 if next_step else state.attempt, last_receipt=relative.as_posix())
        self._write_state(new_state)
        return new_state, receipt

    def retry(self, state: JobState) -> JobState:
        updated = replace(state, status="pending", attempt=state.attempt + 1)
        self._write_state(updated)
        return updated

    def _write_state(self, state: JobState) -> None:
        value = state.to_dict()
        self.registry.validate("job-state", value)
        _atomic_json(self.state_path, value)
