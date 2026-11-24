"""Reference-image -> segment creation orchestration (plan phase 2 closed loop).

Ties the pure phase-2 modules into the typed segment workflow WITHOUT a second state
machine: this is the PRE-entry that produces a confirmed-design segment-create-request
draft from a reference image, plus the POST-validate perceptual comparison. The human
still confirms the draft and signs TP; nothing here auto-ingests or auto-approves.

Flow:
  prepare_reference_segment_request:
    intake (safe freeze) -> extract_proposal -> assemble_segment_design -> draft request.
    Reference provenance (intake/proposal digests, recovery error) is recorded as request
    ``decisions`` so it flows through analyze -> brief -> TP via the existing evidence path.
  compare_reference_render (after the segment sample render):
    three-way round-trip decomposition + redline deviation; a faithful extract is not a
    redline exemption (blockers require an explicit authorized recolor).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from ..artifacts import atomic_yaml
from ..canonical import sha256_digest
from ..compiler.reference_comparison import redline_deviation, round_trip_report
from ..compiler.reference_extraction import extract_proposal, round_trip_palette
from ..schema_registry import SchemaRegistry
from .reference_intake import assemble_segment_design, intake_reference


def prepare_reference_segment_request(
    path_guard: Any, image_path: str | Path, *, work_root: str | Path,
    kind: str, base_design: dict[str, Any],
    request_id: str, proposal_id: str, license: str, selected_segments: list[str],
    namespace: str, template_id: str, version: str, purpose: str,
    audience: list[str], reuse_intent: str, supported_uses: list[str],
    excluded_uses: list[str], authoring_mode: str, targets: list[str],
    subject: dict[str, Any], requested_at: str,
    k: int = 4, user_layout: Optional[dict] = None,
    user_typography: Optional[dict] = None,
    registry: SchemaRegistry | None = None,
) -> dict[str, Any]:
    """Produce a draft segment-create-request from a reference image (non-authoritative).

    Freezes intake + proposal evidence under work_root/reference and binds their digests
    (plus the recovery error) into the request decisions. The returned draft MUST be
    confirmed by the user and submitted to SegmentCreationWorkflow; it is not auto-ingested.
    """
    registry = registry or SchemaRegistry()
    root = path_guard.resolve(work_root, must_exist=True)
    intake, raw = intake_reference(
        path_guard, image_path, intake_id=f"intake-{request_id}", license=license, registry=registry)
    proposal = extract_proposal(
        raw, proposal_id=proposal_id, license=license, k=k,
        selected_segments=selected_segments, user_layout=user_layout, user_typography=user_typography)
    registry.validate("template-proposal", proposal)
    design = assemble_segment_design(proposal, kind=kind, base_design=base_design, registry=registry)

    reference_dir = root / "reference"
    reference_dir.mkdir(parents=True, exist_ok=True)
    atomic_yaml(path_guard.resolve(reference_dir / "intake.yaml"), intake)
    atomic_yaml(path_guard.resolve(reference_dir / "proposal.yaml"), proposal)
    # Freeze a controlled evidence copy of the reference pixels so the post-validate
    # round-trip comparison can re-read them; this copy is never published into a package.
    path_guard.resolve(reference_dir / "reference.png").write_bytes(raw)

    proposed_colors = proposal["recovered"]["ramps"][0]["colors"]
    recovery = round_trip_palette(raw, proposed_colors, k)
    request = {
        "schema_version": 1,
        "request_id": request_id,
        "kind": kind,
        "namespace": namespace,
        "template_id": template_id,
        "version": version,
        "purpose": purpose,
        "audience": audience,
        "reuse_intent": reuse_intent,
        "supported_uses": supported_uses,
        "excluded_uses": excluded_uses,
        "authoring_mode": authoring_mode,
        "targets": targets,
        "scope": f"project:{subject['project_id']}",
        "subject": subject,
        "design": design,
        "requested_at": requested_at,
        "decisions": [
            {"path": "/reference/intake_digest", "value": intake["source_image"]["digest"],
             "source_ref": f"reference-intake:{intake['intake_id']}"},
            {"path": "/reference/proposal_digest", "value": sha256_digest(proposal),
             "source_ref": f"template-proposal:{proposal_id}"},
            {"path": "/reference/recovery_error_delta_e2000", "value": recovery,
             "source_ref": f"reference-intake:{intake['intake_id']}"},
        ],
    }
    registry.validate("segment-create-request", request)
    return {"request": request, "intake": intake, "proposal": proposal,
            "recovery_error_delta_e2000": recovery}


def compare_reference_render(reference_png: bytes, rendered_png: bytes, *,
                             proposed_colors: list[str],
                             effective_colors: Optional[list[str]] = None,
                             k: int | None = None,
                             registry: SchemaRegistry | None = None) -> dict[str, Any]:
    """Post-validate perceptual comparison: three-way round-trip + redline deviation.

    The caller freezes this report and binds it to the TP approval object. A blocker in
    redline_deviation requires an explicit authorized recolor (deviation), never a silent
    pass even when the extraction is faithful.
    """
    report = round_trip_report(reference_png, rendered_png, proposed_colors=proposed_colors,
                               effective_colors=effective_colors, k=k)
    effective = effective_colors if effective_colors is not None else proposed_colors
    deviation = redline_deviation(effective, registry=registry)
    return {"round_trip": report, "redline_deviation": deviation}