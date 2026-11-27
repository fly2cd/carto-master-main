"""Default design preset mechanism (explicit preset + confirmed expansion).

Design principles honored:
  * a default is an EXPLICIT registered preset (policies/default-presets.yaml), never a
    kernel-hardcoded style/layout;
  * it is proposed only when the request carries NO explicit template;
  * expansion requires explicit confirmation (user/LLM); unconfirmed expansion is refused;
  * expansion produces a NEW request BEFORE intake (never mutates an intake'd request);
  * the kernel re-verifies the expanded template at intake (published + admitted).

The preset declares a default SCENARIO template (whose embedded style/layout are the
declared visual defaults). It does not invent appearance; it selects a published preset.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from ..errors import ProtocolError
from ..schema_registry import SchemaRegistry, load_document


def default_policy_path() -> Path:
    return Path(__file__).resolve().parents[3] / "policies" / "default-presets.yaml"


def load_presets(registry: SchemaRegistry | None = None) -> list[dict[str, Any]]:
    registry = registry or SchemaRegistry()
    policy = load_document(default_policy_path())
    registry.validate("default-presets", policy)
    return policy["presets"]


def propose_default(business_scene: str, geometry: str,
                    registry: SchemaRegistry | None = None) -> dict[str, Any] | None:
    """Advisory: return the registered default preset for a business context, or None."""
    for preset in load_presets(registry):
        if preset["business_scene"] == business_scene and preset["geometry"] == geometry:
            return preset
    return None


def expand_default_request(request: dict[str, Any], *, confirmed: bool,
                           registry: SchemaRegistry | None = None) -> dict[str, Any]:
    """Expand a template-less request with the registered default, only if confirmed.

    An explicit template always wins (no default applied). Without confirmation the
    expansion is refused (default is a choice, not a silent fallback). The result is a new
    request carrying default_provenance; it must still pass intake/G1 like any request.
    """
    if request.get("template"):
        return request  # explicit selection wins; default never overrides a choice
    if not confirmed:
        raise ProtocolError("DEFAULT_EXPANSION_UNCONFIRMED",
                            "default template expansion requires explicit confirmation")
    intent = request.get("intent", {})
    business_scene = intent.get("business_scene")
    geometry = request.get("geometry")
    preset = propose_default(business_scene, geometry, registry)
    if preset is None:
        raise ProtocolError("DEFAULT_PRESET_UNKNOWN", f"{business_scene}/{geometry}")
    expanded = deepcopy(request)
    expanded["template"] = deepcopy(preset["template"])
    expanded["default_provenance"] = {
        "expanded": True,
        "business_scene": business_scene,
        "geometry": geometry,
        "preset_template": deepcopy(preset["template"]),
    }
    return expanded