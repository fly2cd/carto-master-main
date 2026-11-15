"""Structural ports the kernel ``compiler`` layer depends on instead of ``workflow``.

Why this module exists
----------------------
``compiler`` is the formal-verification kernel: it must be importable on its own,
without dragging the execution layer in. The scene compilers nevertheless reached
"up" into ``carto_core.workflow`` for three kinds of collaborator -- the bundle
preparer, the geometry preparation services and the material-facts verifier -- and
those runtime edges are what kept the historical ``compiler <-> workflow`` cycle
alive after Tier-1 relocated the shared *contracts* (``contracts.execution`` /
``contracts.bundle``). This module declares those collaborators as ports so the
compiler can depend downward on a leaf again.

Every port is a ``typing.Protocol``: structural, nominal-free, zero runtime
coupling. The concrete implementations stay in ``workflow``
(``preparation_bundle.BundlePreparer``,
``raster_preparation.RasterPreparationService``,
``vector_preparation.VectorPreparationService``,
``material_evidence.verify_material_facts``) and are handed to the compiler by the
composition roots (``workflow.map_generation``, ``workflow.map_final_check``,
``adapters.formal_renderer``, ``scenarios.*``) through constructor injection.

Layer rule
----------
This package is a LEAF. It may import only the standard library and the true spine
(``carto_core.errors`` / ``canonical`` / ``schema_registry``) -- never ``workflow``,
``compiler`` or ``adapters``. Keeping ``registry`` typed as the concrete
``SchemaRegistry`` is allowed because ``schema_registry`` is spine, not a layer.

Signature note
--------------
The raster and vector preparation services deliberately do NOT share a signature:
``load_verified(ref)`` returns ``(report, evidence)`` for raster while
``load_verified(ref, context)`` returns ``report`` for vector, and persistence is
``save_document(value, kind)`` versus ``save(kind, value)``. Following the standing
constraint that execution-layer components with divergent APIs stay separate rather
than being force-unified, they get two protocols over a small common base. Callers
must therefore pick the protocol that matches the geometry they inject; a raster
compiler holding a vector service is a composition-root bug, not something this
layer papers over.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from ..schema_registry import SchemaRegistry

#: Geometry identifiers admitted by the bundle preparer. Declared here (not imported
#: from ``workflow.preparation_bundle``) so the leaf stays a leaf; the execution
#: layer keeps its own authoritative tuple and the guard test pins the two together.
GEOMETRIES = ("raster", "vector")


@runtime_checkable
class PreparationServiceProtocol(Protocol):
    """Members every preparation service exposes, with an identical call contract.

    ``load_verified`` and persistence are NOT here: their signatures and return shapes
    genuinely differ per geometry, so they stay on the geometry-specific protocols.
    """

    #: Schema registry used for every contract validation; never optional.
    registry: SchemaRegistry

    def snapshot_bytes(self, asset: dict[str, Any], kind: str, extension: str) -> bytes:
        """Re-read frozen bytes and assert they still match their artifact ref."""

    def document(self, ref: dict[str, str], kind: str) -> dict[str, Any]:
        """Load an immutable JSON document by reference and re-verify its digest.

        Both geometries provide it under this name (the raster implementation was
        ``_json_ref`` until P1 Step A); it is the single way to read back a frozen
        contract document, and it is what makes geometry-agnostic call sites --
        ``adapters.formal_renderer`` / ``adapters.page_renderer`` -- possible.
        """


@runtime_checkable
class RasterPreparationProtocol(PreparationServiceProtocol, Protocol):
    """Raster preparation port (MCP-gateway backed classification/continuous)."""

    def save_document(self, value: dict[str, Any], schema: str) -> Any:
        """Validate against ``schema`` and store the document content-addressed."""

    def load_verified(self, reference: dict[str, str]) -> tuple[dict[str, Any], dict[str, Any]]:
        """Return ``(report, gis_evidence)`` for a frozen preparation reference."""


@runtime_checkable
class VectorPreparationProtocol(PreparationServiceProtocol, Protocol):
    """Vector preparation port (hermetic Fiona/Shapely reader)."""

    def save(self, kind: str, value: dict[str, Any]) -> Any:
        """Validate against ``kind`` and store the document content-addressed."""

    def load_verified(self, ref: dict[str, str], context: Any) -> dict[str, Any]:
        """Return the prepared-data report, re-verified against its frozen inputs."""

    def crs_contract(self, report: dict[str, Any]) -> dict[str, Any]:
        """Reconstruct the CRS contract (EPSG, or CUSTOM + WKT digest) of a report.

        Declared on the port because the derivation needs the vector reader's CRS
        authority (Fiona), which is an execution-layer dependency the compiler must
        not import.
        """


@runtime_checkable
class BundlePreparerProtocol(Protocol):
    """Frozen ``prepared-data-bundle`` port: build, re-verify and load.

    The implementation is geometry-branched but the contract is geometry-agnostic:
    1-4 unique sources, shared CRS and declared data nature, no implicit
    reprojection, and every load recomputes the bundle so drift always surfaces.
    """

    def build_many(self, references: list[dict[str, Any]], context: Any) -> dict[str, Any]:
        """Build (but do not persist) a bundle from 1-4 verified preparations."""

    def load_verified(self, ref: dict[str, str], context: Any) -> dict[str, Any]:
        """Load a frozen bundle and assert it equals a rebuild from its sources."""

    def validate_request(self, request: dict[str, Any], bundle: dict[str, Any],
                         context: Any) -> None:
        """Cross-check generate-request bindings against the frozen bundle."""


@runtime_checkable
class BundlePreparerFactory(Protocol):
    """Port that binds a preparation service and a geometry into a bundle preparer.

    Injected as the concrete ``workflow.preparation_bundle.BundlePreparer`` class
    itself, which satisfies this signature structurally. The geometry stays chosen
    by the component that knows it -- a raster scene compiler always prepares a
    raster bundle -- so a composition root cannot hand a compiler a preparer bound
    to the wrong geometry (Tier-2 去环 Step7).
    """

    def __call__(self, preparation: PreparationServiceProtocol,
                 geometry: str) -> BundlePreparerProtocol:
        """Return the bundle preparer for ``geometry`` (one of :data:`GEOMETRIES`)."""


@runtime_checkable
class PreparationServiceFactory(Protocol):
    """Composition-root port that builds the preparation service for a geometry.

    The compiler needs raster *and* vector services in the same revalidation pass
    (``check_candidate`` branches on ``renderer_id``) but must not construct them,
    because that would re-import the execution layer. The factory keeps the
    "which concrete service" decision where the trusted project root is known.
    """

    def __call__(self, geometry: str, *, project_root: Path, allowed_roots: list[str],
                 registry: SchemaRegistry) -> PreparationServiceProtocol:
        """Return the preparation service for ``geometry`` (one of :data:`GEOMETRIES`)."""


@runtime_checkable
class MaterialFactsVerifier(Protocol):
    """Port for the A2 material byte-chain verification.

    Implemented by ``workflow.material_evidence.verify_material_facts``. Injected
    rather than imported so ``compiler.map_candidate`` can re-verify the frozen
    material facts of a candidate without reaching into the execution layer.
    """

    def __call__(self, execution: dict[str, Any], guard: Any, project_root: Path,
                 registry: SchemaRegistry) -> None:
        """Verify every ``material_facts_refs`` chain; raise on any drift."""
