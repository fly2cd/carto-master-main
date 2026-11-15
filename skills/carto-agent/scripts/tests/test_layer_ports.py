"""Layer-boundary guards for the de-cycled kernel (Tier-2 去环).

Why this module exists
----------------------
``compiler`` used to reach "up" into ``workflow`` for the bundle preparer, the
geometry preparation services, the material-facts verifier and the thematic
derivations; those references are what kept the historical ``compiler <-> workflow``
import cycle alive. Tier-1 relocated the shared contracts into the ``contracts``
leaf, Tier-2 replaced every remaining upward reference with an injected port
(``carto_core.contracts.protocols``).

Nothing at runtime enforces that boundary: a single ``from ..workflow.x import y``
re-added to a kernel module silently re-creates the cycle, and it would still pass
every functional test. These tests are the enforcement. They walk the AST, so
module-level, function-local (deferred) and ``if TYPE_CHECKING:`` annotation
imports all count; they pin the leaf property of ``contracts``; and they check that
the concrete execution-layer objects still satisfy the ports they are injected as,
so a renamed service method fails here instead of at map-generation time.

Synthetic fixtures only: temporary directories, no real approvals, data, GIS files
or rendering.
"""
from __future__ import annotations

import ast
from pathlib import Path
import sys
import tempfile
import unittest

SCRIPTS_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from carto_core.contracts import protocols
from carto_core.errors import ProtocolError
from carto_core.schema_registry import SchemaRegistry
from carto_core.security.paths import PathGuard

CORE = SCRIPTS_ROOT / "carto_core"
# Layers that must stay importable without the execution layer. ``scenarios`` and
# ``adapters`` are deliberately absent: they sit above ``workflow`` and may use it.
KERNEL_LAYERS = ("compiler", "contracts", "validation", "repository", "security")
FORBIDDEN = "carto_core.workflow"
# The only intra-package modules the ``contracts`` leaf may import.
SPINE = {"carto_core.errors", "carto_core.canonical", "carto_core.schema_registry",
         "carto_core.contracts"}


def package_of(path: Path) -> list[str]:
    """``.../carto_core/compiler/raster_scene.py`` -> ``["carto_core", "compiler"]``."""
    return list(path.parent.relative_to(SCRIPTS_ROOT).parts)


def imported_modules(path: Path):
    """Yield ``(lineno, absolute_module)`` for EVERY import in the file.

    ``ast.walk`` descends into function bodies and ``if TYPE_CHECKING:`` blocks, so
    neither a deferred import nor an annotation-only import can slip past. For
    ``from pkg import name`` both ``pkg`` and ``pkg.name`` are yielded, which is
    what catches the ``from .. import workflow`` form.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    package = package_of(path)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield node.lineno, alias.name
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                base = node.module or ""
            else:
                keep = len(package) - (node.level - 1)
                base = ".".join(package[:keep] + ([node.module] if node.module else []))
            yield node.lineno, base
            for alias in node.names:
                yield node.lineno, f"{base}.{alias.name}" if base else alias.name


def kernel_files(layers=KERNEL_LAYERS):
    for layer in layers:
        for path in sorted((CORE / layer).rglob("*.py")):
            if "__pycache__" not in path.parts:
                yield path


class KernelImportBoundaryTests(unittest.TestCase):
    def test_no_kernel_module_imports_the_execution_layer(self):
        offenders = []
        for path in kernel_files():
            for lineno, module in imported_modules(path):
                if module == FORBIDDEN or module.startswith(FORBIDDEN + "."):
                    offenders.append(f"{path.relative_to(SCRIPTS_ROOT)}:{lineno} -> {module}")
        self.assertEqual(
            [], offenders,
            "Kernel layers must obtain execution-layer collaborators through the "
            "injected ports in carto_core.contracts.protocols, never by import; "
            "an import here re-creates the compiler <-> workflow cycle")

    def test_contracts_package_is_a_dependency_leaf(self):
        offenders = []
        for path in kernel_files(("contracts",)):
            for lineno, module in imported_modules(path):
                if not module.startswith("carto_core"):
                    continue
                if ".".join(module.split(".")[:2]) not in SPINE:
                    offenders.append(f"{path.name}:{lineno} -> {module}")
        self.assertEqual(
            [], offenders,
            "contracts is the shared leaf: it may import only the spine "
            "(errors/canonical/schema_registry) and itself, so that both the kernel "
            "and the execution layer can depend on it downward")

    def test_kernel_still_imports_the_ports_it_depends_on(self):
        # Guards the guard: if the port module were renamed or emptied, the boundary
        # test above would pass vacuously.
        users = {path.name for path in kernel_files(("compiler",))
                 if any(module.startswith("carto_core.contracts.protocols")
                        for _, module in imported_modules(path))}
        self.assertTrue({"map_candidate.py", "raster_scene.py", "vector_scene.py"} <= users,
                        f"scene/candidate compilers no longer reference the ports: {sorted(users)}")


class PortConformanceTests(unittest.TestCase):
    """The concrete execution-layer objects must satisfy the ports structurally."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def raster_service(self):
        from carto_core.workflow.raster_preparation import RasterPreparationService
        return RasterPreparationService(project_root=self.root, allowed_roots=[str(self.root)])

    def vector_service(self):
        from carto_core.workflow.vector_preparation import VectorPreparationService
        return VectorPreparationService(project_root=self.root, allowed_roots=[str(self.root)])

    def test_services_satisfy_their_own_geometry_port_and_the_common_base(self):
        raster, vector = self.raster_service(), self.vector_service()
        self.assertIsInstance(raster, protocols.RasterPreparationProtocol)
        self.assertIsInstance(vector, protocols.VectorPreparationProtocol)
        for service in (raster, vector):
            self.assertIsInstance(service, protocols.PreparationServiceProtocol)

    def test_raster_service_does_not_satisfy_the_vector_port(self):
        # The two APIs are deliberately different (document/save vs
        # save_document/_json_ref, crs_contract only on the vector reader), so a
        # mis-wired geometry must not pass as the other port. The converse is not
        # asserted: VectorPreparationService also exposes save_document/_json_ref
        # aliases and is therefore a structural superset of the raster port.
        self.assertNotIsInstance(self.raster_service(), protocols.VectorPreparationProtocol)

    def test_bundle_preparer_satisfies_the_bundle_port_for_both_geometries(self):
        from carto_core.workflow.preparation_bundle import BundlePreparer
        self.assertIsInstance(BundlePreparer(self.raster_service(), "raster"),
                              protocols.BundlePreparerProtocol)
        self.assertIsInstance(BundlePreparer(self.vector_service(), "vector"),
                              protocols.BundlePreparerProtocol)
        with self.assertRaisesRegex(ProtocolError, "BUNDLE_GEOMETRY_UNKNOWN"):
            BundlePreparer(self.raster_service(), "point")

    def test_injected_callables_satisfy_the_callable_ports(self):
        # runtime_checkable callable ports only verify that __call__ exists; the
        # point is to reject a non-callable being wired in, not to check signatures.
        from carto_core.workflow.material_evidence import verify_material_facts
        from carto_core.workflow.preparation_bundle import BundlePreparer
        from carto_core.workflow.preparation_services import preparation_service
        self.assertIsInstance(preparation_service, protocols.PreparationServiceFactory)
        self.assertIsInstance(verify_material_facts, protocols.MaterialFactsVerifier)
        self.assertIsInstance(BundlePreparer, protocols.BundlePreparerFactory)
        self.assertNotIsInstance(object(), protocols.BundlePreparerFactory)

    def test_geometry_vocabulary_is_single_sourced(self):
        # contracts.protocols declares its own tuple to stay a leaf; pin it to the
        # execution-layer authority so the copy cannot drift.
        from carto_core.workflow.preparation_bundle import GEOMETRIES as BUNDLE_GEOMETRIES
        from carto_core.workflow.preparation_services import SERVICES
        self.assertEqual(protocols.GEOMETRIES, BUNDLE_GEOMETRIES)
        self.assertEqual(set(protocols.GEOMETRIES), set(SERVICES))


class FailClosedTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def test_preparation_factory_rejects_an_unknown_geometry(self):
        from carto_core.workflow.preparation_services import preparation_service
        with self.assertRaisesRegex(ProtocolError, "PREPARATION_GEOMETRY_UNKNOWN"):
            preparation_service("point", project_root=self.root, allowed_roots=[str(self.root)])

    def test_preparation_factory_returns_the_geometry_specific_service(self):
        from carto_core.workflow.preparation_services import preparation_service
        from carto_core.workflow.raster_preparation import RasterPreparationService
        from carto_core.workflow.vector_preparation import VectorPreparationService
        kwargs = {"project_root": self.root, "allowed_roots": [str(self.root)]}
        self.assertIsInstance(preparation_service("raster", **kwargs), RasterPreparationService)
        self.assertIsInstance(preparation_service("vector", **kwargs), VectorPreparationService)

    def test_candidate_compiler_names_a_missing_port_instead_of_importing(self):
        # _require_port is the single enforcement point check_candidate() uses for
        # all three injected ports; without it a missing port would surface as an
        # AttributeError from deep inside revalidation.
        from carto_core.compiler.map_candidate import MapCandidateCompiler
        from carto_core.workflow.preparation_bundle import BundlePreparer
        compiler = MapCandidateCompiler(PathGuard([self.root]), SchemaRegistry())
        for port in ("bundles", "preparations", "material_facts"):
            with self.subTest(port=port):
                with self.assertRaisesRegex(ProtocolError, "COMPILER_PORT_NOT_INJECTED"):
                    compiler._require_port(port)
        injected = MapCandidateCompiler(PathGuard([self.root]), SchemaRegistry(), bundles=BundlePreparer)
        self.assertIs(BundlePreparer, injected._require_port("bundles"))


if __name__ == "__main__":
    unittest.main()
