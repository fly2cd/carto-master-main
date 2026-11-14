from __future__ import annotations

from pathlib import Path
from typing import Any

from ..schema_registry import SchemaRegistry
from ..security.paths import PathGuard
from .data_adoption import DataAdoptionService
from .material_extraction import MaterialExtractionService

# Keys MapDataPreparer augments onto the scenario-prepared bundle for material
# (non-GIS) provenance. Scenario candidate compilers re-prepare the GIS bundle
# without these, so bundle-identity comparisons must exclude them; material
# integrity is bound separately via execution.material_facts_refs (P0-1).
MATERIAL_BUNDLE_KEYS = frozenset({"material_sources", "adoption_evidence", "data_facts"})


def bundle_core(bundle: dict[str, Any]) -> dict[str, Any]:
    """GIS-core view of a bundle, excluding MapDataPreparer material augmentation."""
    return {k: v for k, v in bundle.items() if k not in MATERIAL_BUNDLE_KEYS}


class MapDataPreparer:
    """Select the registered data adapter and handle material extraction.

    The primary GIS data path is delegated to the scenario's registered
    data_preparer adapter. Additionally, if the request contains
    ``material_sources``, those are extracted and adopted before the bundle
    is returned — adding provenance, extraction evidence, and adoption
    records to the prepared-data-bundle.
    """

    def __init__(self, path_guard: PathGuard, project_root: Path, output_root: Path,
                 registry: SchemaRegistry | None = None) -> None:
        self.path_guard = path_guard
        self.project_root = path_guard.resolve(project_root, must_exist=True)
        self.output_root = path_guard.resolve(output_root)
        self.registry = registry or SchemaRegistry()
        self._extraction_service = MaterialExtractionService(self.registry)
        self._adoption_service = DataAdoptionService(self.registry)

    def prepare(self, request: dict[str, Any], request_ref: dict[str, str]) -> dict[str, Any]:
        from ..scenario_registry import ScenarioRegistry

        profile = ScenarioRegistry(self.registry).for_generate(request)
        adapter = profile.component("data_preparer")(
            self.path_guard, self.project_root, self.output_root, self.registry)
        result = adapter.prepare(request, request_ref)

        # A2: material extraction and adoption
        material_sources = request.get("material_sources", [])
        if material_sources:
            from .material_evidence import MaterialEvidenceService
            extraction_dicts, extraction_refs, adopted = MaterialEvidenceService(
                self.path_guard, self.project_root, self.registry).prepare(material_sources, self.project_root)
            facts = self._adoption_service.build_data_facts(extraction_dicts, adopted)

            bundle = result["bundle"]
            bundle["material_sources"] = extraction_refs
            bundle["adoption_evidence"] = adopted
            if facts:
                from ..artifacts import artifact_ref, atomic_yaml
                self.registry.validate("data-facts", facts)
                atomic_yaml(Path(self.output_root) / "data-facts.yaml", facts)
                bundle["data_facts"] = artifact_ref("data-facts", facts,
                    Path(self.output_root) / "data-facts.yaml")
            self.registry.validate("prepared-data-bundle", bundle)
            result["bundle"] = bundle

        return result
