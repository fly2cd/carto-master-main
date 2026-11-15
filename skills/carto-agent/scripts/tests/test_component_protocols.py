"""Enforcement for the scenario component contracts (compiler/component_protocols.py).

The registry's closed ``_COMPONENTS`` allowlist decides *which* objects a scenario bundle
provides; ``component_protocols`` declares *what shape* they must have. Until P0-3 nothing
checked the second half -- measured against the real components, 6 of the 8 declared
protocols had drifted (``prepare_request`` vs the actual ``prepare``, ``plan`` vs ``build``,
a four-parameter ``compile`` vs the real seven, ``LegendChecker`` with three parameters and
a dict return vs the real one-parameter triple, ``Author`` missing ``verify_existing``,
``ValidationScene`` missing ``validation_expression``).

Three things are asserted per registered component:
  1. it has a declared protocol at all (no unprotocolled component can be added silently);
  2. it structurally satisfies that protocol (``isinstance`` against the runtime_checkable
     protocol -- this proves the methods exist, nothing more);
  3. every declared method's parameter names, kinds and default-presence match exactly
     (this is what catches the drift above, since ``isinstance`` cannot).

For the four components the framework constructs, the construction signature is checked the
same way against the matching factory protocol.

Synthetic only: this reads declarations and signatures; it prepares no data, renders
nothing and touches no project.
"""
from __future__ import annotations

import inspect
from importlib import import_module
from pathlib import Path
import sys
import unittest

SCRIPTS_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from carto_core import scenario_registry
from carto_core.compiler import component_protocols as cp


def protocol_methods(protocol) -> list[str]:
    """Declared member names of a Protocol, portably (typing.get_protocol_members is 3.12+)."""
    names = [name for name, value in vars(protocol).items()
             if callable(value) and not name.startswith("_")]
    if "__call__" in vars(protocol):
        names.append("__call__")
    return sorted(names)


def shape(target) -> list[tuple[str, str, bool]]:
    """Parameter (name, kind, has-default) triples, ignoring the bound ``self``."""
    out = []
    for param in inspect.signature(target).parameters.values():
        if param.name == "self":
            continue
        out.append((param.name, param.kind.name, param.default is not inspect.Parameter.empty))
    return out


def resolve(entry: tuple[str, str]) -> tuple[str, object]:
    """``(module_path, attribute)`` from the allowlist -> ``(attribute, object)``."""
    module_path, attribute = entry
    return attribute, getattr(import_module(module_path, package="carto_core"), attribute)


class ComponentContractTests(unittest.TestCase):
    def setUp(self):
        # The allowlist is private by design (it is not request-supplied configuration);
        # this test is its enforcement point, so it reads it directly.
        self.bundles = dict(scenario_registry._COMPONENTS)
        self.assertTrue(self.bundles, "no scenario bundle registered; nothing would be checked")

    def test_every_registered_component_has_a_declared_protocol(self):
        for bundle, components in self.bundles.items():
            for name in components:
                with self.subTest(bundle=bundle, component=name):
                    self.assertIn(name, cp.COMPONENT_PROTOCOLS,
                        f"{bundle}.{name} is registered but has no protocol; declare one in "
                        "compiler/component_protocols.py and add it to COMPONENT_PROTOCOLS")

    def test_every_required_component_is_covered(self):
        required = {name for names in scenario_registry.REQUIRED_COMPONENTS.values() for name in names}
        self.assertEqual(set(), required - set(cp.COMPONENT_PROTOCOLS))

    def test_components_satisfy_their_protocol_structurally(self):
        for bundle, components in self.bundles.items():
            for name, entry in components.items():
                attribute, obj = resolve(entry)
                protocol = cp.COMPONENT_PROTOCOLS[name]
                with self.subTest(bundle=bundle, component=name):
                    self.assertIsInstance(obj, protocol,
                        f"{attribute} does not provide the members declared by {protocol.__name__}")

    def test_component_signatures_match_the_declared_contract(self):
        for bundle, components in self.bundles.items():
            for name, entry in components.items():
                attribute, obj = resolve(entry)
                protocol = cp.COMPONENT_PROTOCOLS[name]
                for method in protocol_methods(protocol):
                    declared = shape(getattr(protocol, method))
                    if method == "__call__":
                        actual_target = obj if inspect.isfunction(obj) else getattr(obj, method)
                    else:
                        actual_target = getattr(obj, method)
                    with self.subTest(bundle=bundle, component=name, method=method):
                        self.assertTrue(callable(actual_target),
                            f"{attribute} has no callable {method}")
                        self.assertEqual(declared, shape(actual_target),
                            f"{attribute}.{method} drifted from {protocol.__name__}.{method}; "
                            "update the protocol deliberately (it is the published contract) "
                            "or fix the component")

    def test_constructed_components_match_their_factory_contract(self):
        for bundle, components in self.bundles.items():
            for name, entry in components.items():
                if name not in cp.COMPONENT_CONSTRUCTORS:
                    continue
                attribute, component = resolve(entry)
                factory = cp.COMPONENT_CONSTRUCTORS[name]
                with self.subTest(bundle=bundle, component=name):
                    self.assertTrue(inspect.isclass(component),
                        f"{attribute} is constructed by the framework and must be a class")
                    self.assertIsInstance(component, factory)
                    self.assertEqual(shape(getattr(factory, "__call__")), shape(component),
                        f"{attribute}.__init__ drifted from {factory.__name__}; the framework "
                        "call site would break at construction time")

    def test_class_valued_components_declare_a_construction_contract(self):
        # Guards the guard, in both directions: a component the framework instantiates must
        # publish its constructor shape, and a ready-made instance/function must not claim one.
        for bundle, components in self.bundles.items():
            for name, entry in components.items():
                attribute, obj = resolve(entry)
                with self.subTest(bundle=bundle, component=name):
                    self.assertEqual(inspect.isclass(obj), name in cp.COMPONENT_CONSTRUCTORS,
                        f"{attribute}: class-valued components need an entry in "
                        "COMPONENT_CONSTRUCTORS; instance/function-valued ones must not have one")

    def test_component_vocabulary_has_no_undeclared_protocol(self):
        registered = {name for components in self.bundles.values() for name in components}
        self.assertEqual(set(cp.COMPONENT_PROTOCOLS), registered,
            "COMPONENT_PROTOCOLS and the registry allowlist disagree; a protocol without a "
            "component is dead documentation, a component without a protocol is unchecked")


if __name__ == "__main__":
    unittest.main()
