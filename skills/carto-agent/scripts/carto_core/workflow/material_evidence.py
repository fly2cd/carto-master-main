"""Persist and verify the bounded A2 material evidence used by thematic candidates.

Original files are not renderer dependencies: bytes, extraction and adoption are
frozen before compilation. This module executes no instructions found in content.
"""
from pathlib import Path

from ..artifacts import artifact_ref, atomic_yaml, file_digest
from ..canonical import sha256_digest
from ..errors import ProtocolError
from ..schema_registry import load_document
from ..security.paths import PathGuard
from .data_adoption import DataAdoptionService
from .material_extraction import MaterialExtractionService, MAX_SOURCE_BYTES, detect_format
from .static_assets import StaticAssetStore


class MaterialEvidenceService(StaticAssetStore):
    def __init__(self, guard, project, registry):
        self.guard = guard
        self.project_guard = PathGuard([project])
        self.root = self.project_guard.resolve(project / ".carto/material")
        self.registry = registry
        self.extractor = MaterialExtractionService(registry)
        self.adopter = DataAdoptionService(registry)

    def prepare(self, sources, project):
        extractions, refs, adopted = [], [], []
        fingerprint = sha256_digest({name: file_digest(Path(__file__).with_name(name))
                                    for name in ("material_evidence.py", "material_extraction.py", "data_adoption.py")})
        for source in sources:
            original = self.guard.resolve(source["path"], base_root=project, must_exist=True)
            fmt = source.get("format") or detect_format(original)
            extension = {"text/plain": ".txt", "text/csv": ".csv", "text/markdown": ".md"}.get(fmt)
            if extension is None:
                raise ProtocolError("MATERIAL_EXTRACTOR_MISSING", "No admitted material extractor for this format")
            asset = self.store_asset(self.read_bytes(original, MAX_SOURCE_BYTES), "material-source", extension)
            key = sha256_digest({"source_id": source["source_id"], "asset": asset,
                                 "format": fmt, "extractor": fingerprint})[7:]
            folder = self.project_guard.resolve(self.root / "evidence" / key)
            extraction_path = folder / "extraction.yaml"
            value = self.extractor.extract(Path(asset["artifact_ref"]["uri"]), self.project_guard,
                                           source["source_id"], fmt).body
            if extraction_path.exists():
                existing = load_document(extraction_path)
                self.registry.validate("extraction-result", existing)
                # Observation time is persisted once, not regenerated on retries.
                value["extracted_at"] = existing["extracted_at"]
                value["digest"] = sha256_digest({k: v for k, v in value.items() if k != "digest"})
                if value != existing:
                    raise ProtocolError("MATERIAL_EXTRACTION_DRIFT", "Frozen extraction differs from its bytes or extractor")
            atomic_yaml(extraction_path, value)
            decision = self.adopter.adopt_many([value])[0]
            adoption_path = folder / "adoption.yaml"
            if adoption_path.exists():
                existing = load_document(adoption_path)
                decision["adopted_at"] = existing["adopted_at"]
                if decision != existing:
                    raise ProtocolError("MATERIAL_ADOPTION_DRIFT", "Frozen adoption differs from material policy")
            atomic_yaml(adoption_path, decision)
            extractions.append(value)
            refs.append(artifact_ref("extraction-result", value, extraction_path))
            adopted.append(decision)
        return extractions, refs, adopted


def verify_material_facts(execution, guard, project, registry):
    """Verify the complete referenced facts ? immutable material byte chain."""
    for ref in execution.get("material_facts_refs", []):
        if ref["id"] != "data-facts" or not ref.get("uri"):
            raise ProtocolError("MATERIAL_FACTS_REFERENCE", "Expected a frozen facts document")
        path = guard.resolve(ref["uri"], must_exist=True)
        facts = load_document(path)
        registry.validate("data-facts", facts)
        if sha256_digest(facts) != ref["digest"]:
            raise ProtocolError("MATERIAL_FACTS_DRIFT", "Facts document changed")
        expected = sha256_digest({"refs": facts["material_refs"], "dims": facts["observed_dimensions"]})
        if expected != facts["facts_digest"]:
            raise ProtocolError("MATERIAL_FACTS_DRIFT", "Facts no longer describe their material inputs")
        snapshot_guard = PathGuard([project / ".carto/material"])
        for material in facts["material_refs"]:
            source = snapshot_guard.resolve(material["uri"], must_exist=True)
            if file_digest(source) != material["digest"]:
                raise ProtocolError("MATERIAL_SNAPSHOT_DRIFT", "Frozen material bytes changed")
