"""Code-digest coverage guards: a fingerprint list must cover the code that shapes its output.

The hand-maintained source-fingerprint lists in this codebase are the basis of every
"nothing changed underneath a frozen artifact" claim: preparation reports bind
``algorithm_digest`` / ``reader_digest``, portrayals bind ``compiler_digest``, pages and
render receipts bind ``page_renderer_digest`` / ``formal_renderer_digest``. Nothing derives
those lists from the actual dependency graph, so a module can take part in producing an
artifact and still be absent from the list -- the artifact then changes while its bound
digest does not, which is silent drift in a system whose whole point is fail-closed
attestation.

Two such gaps were measured (P0-2) and are guarded here:

* ``compiler/chart_core.py`` binds chart slots and validates chart declarations; it is
  called by ``adapters/static_page_renderer.py`` while painting a page and by
  ``compiler/vector_page.py`` while freezing one, yet it appeared in **no** fingerprint
  list at all.
* ``compiler/thematic_design.py`` supplies ``equal_interval_edges``, which
  ``workflow/raster_preparation.py`` uses to compute continuous class breaks, yet
  ``algorithm_digest`` did not cover it (a pre-existing gap: before Tier-2 the same
  function lived in ``workflow/thematic.py``, which that digest never listed either).

The assertions are behavioural -- they observe which files each digest function actually
reads -- so they survive list refactors and fail when a required module drops out or when
a new output-shaping module is added without being fingerprinted.

Synthetic only: no projects, approvals, data or rendering are touched.
"""
from __future__ import annotations

import contextlib
import pathlib
import sys
import unittest

SCRIPTS_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from carto_core.adapters.formal_renderer import (
    _formal_renderer_digest_raster, _formal_renderer_digest_vector,
)
from carto_core.adapters.page_renderer import page_renderer_digest
from carto_core.adapters.raster_renderer import renderer_digest
from carto_core.compiler.raster_portrayal import algorithm_digest, portrayal_compiler_digest
from carto_core.compiler.vector_portrayal import compiler_digest as vector_compiler_digest
from carto_core.workflow.vector_preparation import reader_digest


@contextlib.contextmanager
def files_read():
    """Yield the list of file names read via ``Path.read_bytes`` during the block."""
    seen: list[str] = []
    original = pathlib.Path.read_bytes

    def spy(self, *args, **kwargs):
        seen.append(self.name)
        return original(self, *args, **kwargs)

    pathlib.Path.read_bytes = spy
    try:
        yield seen
    finally:
        pathlib.Path.read_bytes = original


def read_by(fn) -> set[str]:
    with files_read() as seen:
        fn()
    return set(seen)


class PageDigestCoverageTests(unittest.TestCase):
    """The page digest is what a frozen page-request/page-output is bound to."""

    COMMON = {"page_renderer.py", "static_page_renderer.py", "layout.py", "appearance.py",
              "page_bindings.py", "grid_layout.py", "chart_core.py"}

    def test_both_geometries_cover_the_shared_page_shaping_modules(self):
        for geometry in ("raster", "vector"):
            with self.subTest(geometry=geometry):
                missing = self.COMMON - read_by(lambda g=geometry: page_renderer_digest(g))
                self.assertEqual(set(), missing,
                    f"page_renderer_digest({geometry!r}) does not fingerprint {sorted(missing)}; "
                    "output could change without the bound digest changing")

    def test_raster_page_covers_the_raster_contract_chain(self):
        required = {"raster_page_contract.py", "raster_legends.py", "raster_portrayal.py",
                    "raster_preparation.py"}
        missing = required - read_by(lambda: page_renderer_digest("raster"))
        self.assertEqual(set(), missing)

    def test_vector_page_covers_the_vector_chain(self):
        required = {"vector_page.py", "vector_portrayal.py", "portrayal_resolver.py",
                    "vector_preparation.py"}
        missing = required - read_by(lambda: page_renderer_digest("vector"))
        self.assertEqual(set(), missing)

    def test_raster_body_renderer_covers_layout_and_grid(self):
        missing = {"layout.py", "grid_layout.py", "svg_compositor.py", "raster_renderer.py"} - read_by(renderer_digest)
        self.assertEqual(set(), missing)


class PreparationDigestCoverageTests(unittest.TestCase):
    """Preparation/portrayal digests are what frozen reports and portrayals are bound to."""

    def test_algorithm_digest_covers_break_derivation(self):
        # equal_interval_edges (continuous class breaks) lives in the kernel and is reached
        # through workflow.thematic's re-export shim; without it the break math could change
        # while every frozen raster preparation still verified.
        required = {"raster_portrayal.py", "raster_preparation.py", "thematic_design.py"}
        missing = required - read_by(algorithm_digest)
        self.assertEqual(set(), missing,
            "algorithm_digest must fingerprint the code that derives class breaks")

    def test_portrayal_compiler_digest_covers_expression_catalog(self):
        missing = {"raster_portrayal.py", "map_expression_catalog.py"} - read_by(portrayal_compiler_digest)
        self.assertEqual(set(), missing)

    def test_vector_compiler_digest_covers_ir_derivation_and_evaluation(self):
        required = {"vector_portrayal.py", "portrayal_resolver.py", "thematic_design.py"}
        missing = required - read_by(vector_compiler_digest)
        self.assertEqual(set(), missing,
            "compiler_digest must cover both IR derivation and IR value evaluation")

    def test_reader_digest_covers_the_attribute_join_and_its_predicate(self):
        # join_attributes lives in thematic.py and calls finite(), which moved to
        # portrayal_resolver.py in Tier-2 Step4; both must stay fingerprinted.
        required = {"vector_preparation.py", "thematic.py", "material_extraction.py",
                    "portrayal_resolver.py"}
        missing = required - read_by(reader_digest)
        self.assertEqual(set(), missing)


class FormalRendererDigestCoverageTests(unittest.TestCase):
    """The render-receipt attestation must cover the scene compilers and the bundle contract."""

    def test_raster_attestation_covers_scene_and_bundle(self):
        required = {"formal_renderer.py", "raster_scene.py", "preparation_bundle.py",
                    "render_backend.py", "raster_page_contract.py"}
        missing = required - read_by(lambda: _formal_renderer_digest_raster(page_renderer_digest("raster")))
        self.assertEqual(set(), missing)

    def test_vector_attestation_covers_scene_and_bundle(self):
        required = {"formal_renderer.py", "vector_scene.py", "preparation_bundle.py",
                    "render_backend.py", "vector_page.py"}
        missing = required - read_by(lambda: _formal_renderer_digest_vector(page_renderer_digest("vector")))
        self.assertEqual(set(), missing)


if __name__ == "__main__":
    unittest.main()
