from __future__ import annotations

import re
import struct
from pathlib import Path
from typing import Any, Callable

from ..artifacts import atomic_yaml, file_digest
from ..canonical import sha256_digest
from ..compiler.layout import LayoutResolver, overlay_bounds
from ..errors import ProtocolError, SecurityError
from ..scenario_registry import ScenarioRegistry
from ..schema_registry import SchemaRegistry, load_document
from ..security.paths import PathGuard
from ..validation.registry import CheckerRegistry
from ..validation.map_checks import legend_consistency
from .map_render import REQUIRED_TARGETS


Checker = Callable[[dict[str, Any]], tuple[bool, dict[str, Any], str | None]]
_PDF_PAGE = re.compile(rb"/Type\s*/Page(?!s)\b")
_PDF_MEDIA_BOX = re.compile(
    rb"/MediaBox\s*\[\s*([-+0-9.]+)\s+([-+0-9.]+)\s+([-+0-9.]+)\s+([-+0-9.]+)\s*\]"
)
_ALLOWED_RENDER_WARNINGS = frozenset({
    "PDF is an engineering preview and is not claimed to be fully vector.",
})


class FinalMapCheckService:
    """Run the registered deterministic final checks and freeze the G3 object."""

    def __init__(
        self,
        *,
        path_guard: PathGuard,
        project_root: Path,
        work_root: Path,
        registry: SchemaRegistry | None = None,
        policy_path: Path | None = None,
        execution_context=None,
    ) -> None:
        self.execution_context = execution_context
        self.path_guard = path_guard
        self.project_root = path_guard.resolve(project_root, must_exist=True)
        self.work_root = path_guard.resolve(work_root, must_exist=True)
        self.registry = registry or SchemaRegistry()
        self.checkers = CheckerRegistry(policy_path, self.registry)
        self.checker_set_digest = self.checkers.policy_digest
        self.definitions = self.checkers.definitions("final-check")
        handlers: dict[str, Checker] = {
            "final.artifact-integrity": self._artifact_integrity,
            "final.required-targets": self._required_targets,
            "final.pdf-page-contract": self._pdf_page_contract,
            "final.png-raster-contract": self._png_raster_contract,
            "final.font-policy": self._font_policy,
            "final.layout-elements": self._layout_elements,
            "final.legend-semantics": self._legend_semantics,
            "final.scenario-notice": self._scenario_notice,
            "final.render-binding": self._render_binding,
            "final.sensitive-content": self._sensitive_content,
            "final.renderer-warnings": self._renderer_warnings,
        }
        check_ids = tuple(item["id"] for item in self.definitions)
        missing = set(handlers) - set(check_ids)
        if missing:
            raise ProtocolError("FINAL_CHECKERS_MISSING", ",".join(sorted(missing)))
        for check_id, handler in handlers.items():
            self.checkers.register(check_id, lambda _, ctx, operation=handler: operation(ctx))
        self.checkers.require_handlers(check_ids)

    def inspect(
        self,
        *,
        lock: dict[str, Any],
        lock_ref: dict[str, str],
        scene: dict[str, Any],
        attempt: dict[str, Any],
        attempt_path: Path,
        receipt: dict[str, Any],
        evidence: dict[str, Any],
        evidence_path: Path,
    ) -> dict[str, Any]:
        selected = sorted(
            (item for item in evidence["output_artifacts"] if item["target"] in REQUIRED_TARGETS),
            key=lambda item: item["target"],
        )
        context = {
            "scenario_profile": ScenarioRegistry(self.registry).for_execution(lock["execution"]),
            "lock": lock,
            "lock_ref": lock_ref,
            "scene": scene,
            "attempt": attempt,
            "attempt_path": attempt_path,
            "receipt": receipt,
            "evidence": evidence,
            "evidence_path": evidence_path,
            "artifacts": selected,
        }
        if scene.get("renderer_id") == "rasterio-matplotlib-page":
            context["raster"] = self._raster_context(scene, lock, receipt)
        results = [self.checkers.evaluate(item["id"], lock, context).to_dict()
                   for item in self.definitions]
        counts = {
            severity: sum(item["severity"] == severity for item in results)
            for severity in ("blocker", "error", "warning", "info")
        }
        counts.update({
            "failed_blocker": sum(item["status"] == "failed" and item["severity"] == "blocker" for item in results),
            "failed_error": sum(item["status"] == "failed" and item["severity"] == "error" for item in results),
            "failed_warning": sum(item["status"] == "failed" and item["severity"] == "warning" for item in results),
        })
        status = "failed" if self.checkers.has_blocking_failure(results) else "passed"
        subject = self._subject(lock, attempt, evidence, selected)
        report = {
            "schema_version": 1,
            "report_id": f"final-check-{sha256_digest(subject)[7:23]}",
            "phase": "final-check",
            "subject_digest": sha256_digest(subject),
            "subject_ref": {
                "id": evidence["evidence_id"],
                "version": "1.0.0",
                "digest": sha256_digest(evidence),
                "uri": str(evidence_path),
            },
            "checker_set_digest": self.checker_set_digest,
            "checked_artifacts": selected,
            "counts": counts,
            "status": status,
            "results": results,
            "created_at": attempt["completed_at"],
        }
        self.registry.validate("validation-report", report)
        return report

    def _raster_context(self, scene, lock, receipt):
        from ..adapters.raster_page_renderer import RasterPageRenderer
        from ..compiler.raster_scene import RasterSceneCompiler
        from .raster_preparation import RasterPreparationService
        if self.execution_context is None:
            raise SecurityError("RASTER_EXECUTION_CONTEXT_REQUIRED", "Final checks require the trusted execution context")
        preparation = RasterPreparationService(project_root=self.project_root,
            allowed_roots=list(self.path_guard.allowed_roots), registry=self.registry)
        inputs = RasterSceneCompiler(preparation).validate_execution(scene, lock["execution"], self.execution_context)
        page = RasterPageRenderer(preparation).load_verified(receipt["page_output_ref"], self.execution_context)
        if (page["request_ref"] != scene["page_request_ref"]
                or receipt["renderer_id"] != scene["renderer_id"]
                or page["environment"] != receipt["runtime"]
                or page["environment"] != lock["execution"]["environment"]["runtime"]):
            raise ProtocolError("FINAL_CHECK_RASTER_BINDING", "Page, scene, receipt and locked runtime must agree")
        for item in receipt["output_artifacts"]:
            asset = page["outputs"][item["target"]]
            if (item["artifact_ref"]["digest"] != asset["artifact_ref"]["digest"]
                    or item["size_bytes"] != asset["size_bytes"]):
                raise ProtocolError("FINAL_CHECK_RASTER_BINDING", "Attested outputs differ from the verified page")
        return {**inputs, "output": page, "body": preparation._json_ref(page["body_ref"], "raster-map-body")}

    def report_path(self, attempt_id: str) -> Path:
        return self.path_guard.resolve(
            self.work_root / "final-checks" / attempt_id / "validation-report.yaml"
        )

    def write_report(self, report: dict[str, Any], attempt_id: str) -> Path:
        path = self.report_path(attempt_id)
        atomic_yaml(path, report)
        return path

    def normalize_destination(self, destination: str | Path) -> str:
        raw = Path(destination)
        if raw.is_absolute():
            raise SecurityError("DELIVERY_DESTINATION_NOT_RELATIVE", str(destination))
        resolved = self.path_guard.resolve(raw, base_root=self.project_root)
        try:
            relative = resolved.relative_to(self.project_root)
        except ValueError as exc:
            raise SecurityError("DELIVERY_DESTINATION_OUTSIDE_PROJECT", str(destination)) from exc
        if not relative.parts:
            raise SecurityError("DELIVERY_DESTINATION_INVALID", str(destination))
        return relative.as_posix()

    def build_manifest(
        self,
        *,
        request: dict[str, Any],
        lock: dict[str, Any],
        lock_ref: dict[str, str],
        attempt: dict[str, Any],
        attempt_path: Path,
        report: dict[str, Any],
        report_path: Path,
        recipient_id: str,
        recipient_type: str,
        destination: str | Path,
        idempotency_key: str,
    ) -> dict[str, Any]:
        if report["status"] != "passed":
            raise ProtocolError("FINAL_CHECK_NOT_PASSED", report["report_id"])
        profile = ScenarioRegistry(self.registry).for_execution(lock["execution"])
        relative_destination = self.normalize_destination(destination)
        artifacts = []
        for item in sorted(report["checked_artifacts"], key=lambda value: value["target"]):
            artifact_path = self.path_guard.resolve(item["artifact_ref"]["uri"], must_exist=True)
            try:
                relative_path = artifact_path.relative_to(self.project_root).as_posix()
            except ValueError as exc:
                raise SecurityError("DELIVERY_ARTIFACT_OUTSIDE_PROJECT", str(artifact_path)) from exc
            artifacts.append({
                "path": relative_path,
                "format": item["target"],
                "digest": item["artifact_ref"]["digest"],
                "size_bytes": item["size_bytes"],
            })
        body = {
            "schema_version": 1,
            "project_id": request["project_id"],
            "run_id": request["run_id"],
            "tenant_id": request["subject"]["tenant_id"],
            "lock_ref": lock_ref,
            "lock_digest": sha256_digest(lock),
            "execution_digest": lock["execution_digest"],
            "render_attempt_ref": {
                "id": attempt["attempt_id"], "version": "1.0.0",
                "digest": sha256_digest(attempt), "uri": str(attempt_path),
            },
            "renderer_execution_digest": attempt["renderer_execution_digest"],
            "validation_report_ref": {
                "id": report["report_id"], "version": "1.0.0",
                "digest": sha256_digest(report), "uri": str(report_path),
            },
            "artifacts": artifacts,
            "recipient": {"recipient_id": recipient_id, "recipient_type": recipient_type},
            "destination": {"kind": "local-allowed-root", "relative_path": relative_destination},
            "scope": request["scope"],
            "environment": request["environment"],
            "licenses": list(profile.definition["licenses"]),
            "limitations": [profile.notice],
            "idempotency_key": idempotency_key,
            "created_at": report["created_at"],
        }
        manifest = {
            "schema_version": 1,
            "manifest_id": f"delivery-manifest-{sha256_digest(body)[7:23]}",
            **{key: value for key, value in body.items() if key != "schema_version"},
        }
        self.registry.validate("delivery-manifest", manifest)
        return manifest

    def write_manifest(self, manifest: dict[str, Any]) -> Path:
        path = self.path_guard.resolve(
            self.work_root / "delivery-manifests" / f"{manifest['manifest_id']}.yaml"
        )
        atomic_yaml(path, manifest)
        return path

    @staticmethod
    def g3_context(manifest: dict[str, Any]) -> dict[str, str]:
        return {
            "gate_id": "G3",
            "action": "approve-delivery",
            "object_type": "delivery-manifest",
            "object_digest": sha256_digest(manifest),
            "scope": manifest["scope"],
            "tenant_id": manifest["tenant_id"],
            "environment": manifest["environment"],
        }

    @staticmethod
    def _subject(
        lock: dict[str, Any], attempt: dict[str, Any], evidence: dict[str, Any], artifacts: list[dict[str, Any]]
    ) -> dict[str, Any]:
        return {
            "lock_digest": sha256_digest(lock),
            "execution_digest": lock["execution_digest"],
            "attempt_digest": sha256_digest(attempt),
            "evidence_digest": sha256_digest(evidence),
            "artifacts": [
                {
                    "target": item["target"],
                    "digest": item["artifact_ref"]["digest"],
                    "size_bytes": item["size_bytes"],
                }
                for item in artifacts
            ],
        }

    def _artifact_path(self, item: dict[str, Any]) -> Path | None:
        uri = item.get("artifact_ref", {}).get("uri")
        if not uri:
            return None
        try:
            path = self.path_guard.resolve(uri)
        except (ProtocolError, SecurityError):
            return None
        return path if path.is_file() else None

    def _artifact_map(self, context: dict[str, Any]) -> dict[str, dict[str, Any]]:
        return {item["target"]: item for item in context["artifacts"]}

    def _artifact_integrity(self, context: dict[str, Any]) -> tuple[bool, dict[str, Any], None]:
        details = []
        passed = True
        for item in context["artifacts"]:
            path = self._artifact_path(item)
            signature_valid = False
            actual_size = path.stat().st_size if path else 0
            actual_digest = file_digest(path) if path else None
            if path is not None:
                header = path.read_bytes()[:24]
                signature_valid = (
                    item["target"] == "pdf" and header.startswith(b"%PDF-")
                    or item["target"] == "png" and header.startswith(b"\x89PNG\r\n\x1a\n")
                )
            integrity_valid = bool(
                signature_valid and actual_size == item["size_bytes"]
                and actual_digest == item["artifact_ref"]["digest"]
            )
            passed = passed and integrity_valid
            details.append({
                "target": item["target"], "exists": path is not None,
                "size_matches": actual_size == item["size_bytes"],
                "digest_matches": actual_digest == item["artifact_ref"]["digest"],
                "media_signature_valid": signature_valid,
                "integrity_valid": integrity_valid,
            })
        return passed, {"artifacts": details}, None

    def _required_targets(self, context: dict[str, Any]) -> tuple[bool, dict[str, Any], None]:
        selected = [item["target"] for item in context["artifacts"]]
        receipt_targets = [item["target"] for item in context["receipt"]["output_artifacts"]]
        attempt_targets = [item["target"] for item in context["attempt"]["output_artifacts"]]
        passed = (
            set(selected) == REQUIRED_TARGETS and len(selected) == 2
            and REQUIRED_TARGETS.issubset(receipt_targets)
            and REQUIRED_TARGETS.issubset(attempt_targets)
        )
        return passed, {
            "selected_targets": sorted(selected),
            "receipt_targets": sorted(receipt_targets),
            "attempt_targets": sorted(attempt_targets),
        }, None

    def _pdf_page_contract(self, context: dict[str, Any]) -> tuple[bool, dict[str, Any], None]:
        item = self._artifact_map(context).get("pdf")
        path = self._artifact_path(item) if item else None
        if path is None:
            return False, {"reason": "pdf-missing"}, None
        payload = path.read_bytes()
        page_count = len(_PDF_PAGE.findall(payload))
        match = _PDF_MEDIA_BOX.search(payload)
        width = height = 0.0
        if match:
            x0, y0, x1, y1 = (float(value) for value in match.groups())
            width, height = abs(x1 - x0), abs(y1 - y0)
        target = next((value for value in context["lock"]["execution"]["targets"].values() if value["format"] == "pdf"), None)
        if target is None:
            return False, {"reason": "pdf-target-not-locked"}, None
        expected_width = target["width_mm"] * 72 / 25.4
        expected_height = target["height_mm"] * 72 / 25.4
        size_matches = abs(width - expected_width) <= 3 and abs(height - expected_height) <= 3
        passed = payload.startswith(b"%PDF-") and b"%%EOF" in payload[-2048:] and page_count == 1 and size_matches
        return passed, {
            "page_count": page_count,
            "width_points": round(width, 3), "height_points": round(height, 3),
            "expected_width_points": round(expected_width, 3),
            "expected_height_points": round(expected_height, 3),
            "orientation": "landscape" if width > height else "portrait",
        }, None

    def _png_raster_contract(self, context: dict[str, Any]) -> tuple[bool, dict[str, Any], None]:
        item = self._artifact_map(context).get("png")
        path = self._artifact_path(item) if item else None
        if path is None:
            return False, {"reason": "png-missing"}, None
        header = path.read_bytes()[:33]
        if len(header) < 33 or header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
            return False, {"reason": "png-header-invalid"}, None
        width, height = struct.unpack("!II", header[16:24])
        bit_depth, color_type = header[24], header[25]
        target = next((value for value in context["lock"]["execution"]["targets"].values() if value["format"] == "png"), None)
        if target is None:
            return False, {"reason": "png-target-not-locked"}, None
        expected_width = round(target["width_mm"] / 25.4 * target["dpi"])
        expected_height = round(target["height_mm"] / 25.4 * target["dpi"])
        dpi_x = width / (target["width_mm"] / 25.4)
        dpi_y = height / (target["height_mm"] / 25.4)
        scene_viewport = context["scene"]["viewport"]
        passed = (
            (width, height) == (expected_width, expected_height)
            and (width, height) == (scene_viewport["width_px"], scene_viewport["height_px"])
            and abs(dpi_x - target["dpi"]) <= 0.1 and abs(dpi_y - target["dpi"]) <= 0.1
            and bit_depth == 8 and color_type in {2, 6}
        )
        return passed, {
            "width_px": width, "height_px": height,
            "expected_width_px": expected_width, "expected_height_px": expected_height,
            "inferred_dpi_x": round(dpi_x, 3), "inferred_dpi_y": round(dpi_y, 3),
            "locked_dpi": target["dpi"], "bit_depth": bit_depth, "color_type": color_type,
        }, None

    def _font_policy(self, context: dict[str, Any]) -> tuple[bool, dict[str, Any], None]:
        fonts = [item for item in context["scene"]["resources"] if item["kind"] == "font"]
        loaded = {item["resource_id"]: item for item in context["receipt"]["resource_evidence"]}
        locked = {item["id"]: item for item in context["lock"]["execution"].get("resolved_assets", [])}
        resource_ok = len(fonts) == 1 and all(
            loaded.get(item["id"], {}).get("status") == "loaded"
            and loaded[item["id"]]["digest"] == item["ref"]["digest"]
            and locked.get(item["id"], {}).get("digest") == item["ref"]["digest"]
            for item in fonts
        )
        pdf = self._artifact_map(context).get("pdf")
        path = self._artifact_path(pdf) if pdf else None
        payload = path.read_bytes() if path else b""
        pdf_font_evidence = any(marker in payload for marker in (b"/FontFile", b"/CIDFontType", b"/Type3"))
        if "raster" in context:
            output = context["raster"]["output"]
            font_ok = (output["font_snapshot"] == context["raster"]["font"]
                       and output["checks"]["glyph-coverage"] == "passed"
                       and not output["font_embedding_flags"] & (0x0002 | 0x0100 | 0x0200))
            return resource_ok and pdf_font_evidence and font_ok, {
                "font_family": output["font_family"], "resource_binding_valid": resource_ok,
                "pdf_font_evidence": pdf_font_evidence, "glyph_and_embedding_policy_valid": font_ok,
                "policy": "embed-approved-frozen-truetype"}, None
        passed = resource_ok and pdf_font_evidence
        return passed, {
            "font_resources": [item.get("font_family") for item in fonts],
            "resource_binding_valid": resource_ok,
            "pdf_font_evidence": pdf_font_evidence,
            "policy": "embed-approved",
        }, None

    def _layout_elements(self, context: dict[str, Any]) -> tuple[bool, dict[str, Any], None]:
        scene = context["scene"]
        if "raster" in context:
            LayoutResolver(self.registry).validate_execution(scene, context["lock"]["execution"])
            frames = {f["id"]: f for f in scene["resolved_layout"]["frames"] if f["type"] != "map"}
            measurements = context["raster"]["output"]["measurements"]
            valid = {m["frame_id"] for m in measurements} == set(frames)
            for m in measurements:
                frame = frames.get(m["frame_id"])
                if frame is None:
                    valid = False
                    continue
                x,y,w,h = m["bounds_px"]
                fx,fy,fw,fh = frame["bounds_px"]
                valid = valid and (x >= fx - 1e-5 and y >= fy - 1e-5 and w > 0 and h > 0
                                   and x+w <= fx+fw+1e-5 and y+h <= fy+fh+1e-5)
            return valid, {"layout_contract_valid": True, "frame_coverage_valid": valid,
                "measurements": measurements, "bounds_method": "matplotlib-measured-frozen-font",
                "optional_adornments": {k: context["raster"]["page"][k] is not None for k in ("scale_bar", "grid_north")}}, None
        required = {"title": "text", "legend": "legend", "scale": "scale-bar", "north": "north-arrow", "source": "attribution"}
        by_id = {item["id"]: item for item in scene["overlays"]}
        present = {key: by_id.get(key, {}).get("type") == value for key, value in required.items()}
        try:
            LayoutResolver(self.registry).validate_execution(scene, context["lock"]["execution"])
        except (ProtocolError, SecurityError) as exc:
            return False, {"required_elements": present, "layout_contract_valid": False,
                           "error_code": exc.code, "message": exc.message}, None
        resolved = scene["resolved_layout"]
        bounds = []
        for item in scene["overlays"]:
            x, y = item["position"]["x"], item["position"]["y"]
            bounds.append({"id": item["id"], "bounds_px": list(overlay_bounds(item, x, y))})
        return all(present.values()), {
            "required_elements": present, "layout_contract_valid": True,
            "layout_ref": resolved["contract_ref"], "resolver_version": resolved["resolver_version"],
            "safe_margin_px": resolved["page"]["safe_margin_px"],
            "frames": resolved["frames"], "overlay_bounds": bounds,
            "bounds_method": "conservative-fixed-primitive-envelope-not-font-measurement",
        }, None

    def _legend_semantics(self, context: dict[str, Any]) -> tuple[bool, dict[str, Any], str | None]:
        return legend_consistency(context)

    def _scenario_notice(self, context: dict[str, Any]) -> tuple[bool, dict[str, Any], None]:
        notice = context["scenario_profile"].notice
        if "raster" in context:
            notices = [item for item in context["raster"]["page"]["texts"] if item["text"] == notice]
        else:
            notices = [item for item in context["scene"]["overlays"]
                       if item.get("content") == notice and item.get("coordinate_space") == "page"]
        chain = (
            context["evidence"].get("scenario_notice") == notice
            and context["receipt"].get("scene_digest") == sha256_digest(context["scene"])
            and all(self._artifact_path(item) is not None for item in context["artifacts"])
        )
        return len(notices) == 1 and chain, {"scene_notice_count": len(notices), "attested_scene_to_outputs": chain}, None

    def _render_binding(self, context: dict[str, Any]) -> tuple[bool, dict[str, Any], None]:
        lock, attempt, receipt, evidence = context["lock"], context["attempt"], context["receipt"], context["evidence"]
        checks = {
            "lock": attempt["lock_digest"] == sha256_digest(lock) == evidence["lock_digest"],
            "business_execution": attempt["business_execution_digest"] == lock["execution_digest"] == evidence["business_execution_digest"],
            "renderer_execution": attempt["renderer_execution_digest"] == receipt["execution_digest"] == evidence["renderer_execution_digest"],
            "scene": attempt["render_scene_digest"] == receipt["scene_digest"] == evidence["render_scene_digest"] == sha256_digest(context["scene"]),
            "environment": attempt["environment_fingerprint"] == receipt["environment_fingerprint"] == evidence["environment_fingerprint"],
            "resources": attempt["resource_set_digest"] == receipt["resource_set_digest"] == evidence["resource_set_digest"],
            "attempt": evidence["attempt_digest"] == sha256_digest(attempt),
            "receipt": evidence["render_receipt_ref"]["digest"] == sha256_digest(receipt),
        }
        return all(checks.values()), checks, None

    def _sensitive_content(self, context: dict[str, Any]) -> tuple[bool, dict[str, Any], None]:
        forbidden = (
            b"CARTO_RENDER_ATTESTATION_KEY", b"CARTO_APPROVAL_HMAC_KEY", b"BEGIN PRIVATE KEY",
            b"DevTools",
        ) + tuple(name.encode("utf-8") for name in context["scenario_profile"].definition["internal_field_names"])
        findings: dict[str, list[str]] = {}
        for item in context["artifacts"]:
            path = self._artifact_path(item)
            payload = path.read_bytes() if path else b""
            hits = [marker.decode("utf-8") for marker in forbidden if marker in payload]
            if hits:
                findings[item["target"]] = hits
        if "raster" in context:
            # PDF streams may be compressed and SVG glyphs are paths: also inspect
            # the verified source strings actually used to produce these bytes.
            raster = context["raster"]
            strings = ([item["text"] for item in raster["page"]["texts"]]
                       + [raster["page"]["legend"]["title"]]
                       + [row["label"] for row in raster["portrayal"]["legend_items"]])
            if raster["page"]["grid_north"] is not None:
                strings.append(raster["page"]["grid_north"]["label"])
            if raster["page"]["scale_bar"] is not None:
                from ..adapters.raster_page_renderer import RasterPageRenderer
                strings.append(RasterPageRenderer._scale_label(raster["page"]["scale_bar"]))
            payload = "\n".join(strings).encode("utf-8")
            hits = [marker.decode("utf-8") for marker in forbidden if marker in payload]
            if hits:
                findings["frozen-rendered-text"] = hits
        return not findings, {"forbidden_markers": findings, "checked_marker_count": len(forbidden)}, None

    def _renderer_warnings(self, context: dict[str, Any]) -> tuple[bool, dict[str, Any], str]:
        warnings = context["receipt"].get("warnings", [])
        allowed = set() if "raster" in context else _ALLOWED_RENDER_WARNINGS
        unknown = sorted(set(warnings) - allowed)
        return not unknown, {"warnings": warnings, "unknown_warnings": unknown}, "accepted" if not unknown else "blocked"