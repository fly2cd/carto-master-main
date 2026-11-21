"""leadership-visit request_binding: data-preparation request-body binding (I-4b).

The kernel ``BundlePreparer`` keeps the geometry-branched bundle mechanics; this
module supplies scenario-specific validation that cross-checks the request bindings
against the frozen bundle.
"""
from __future__ import annotations

from typing import Any

from ...canonical import sha256_digest
from ...compiler.page_bindings import index_by
from ...errors import ProtocolError


def prepare_request(preparer, request: dict[str, Any], context) -> dict[str, Any]:
    """Validate request bindings, build and persist the bundle."""
    preparer.preparation.registry.validate("generate-request", request)
    # Leadership visit: single data preparer entry, single role
    refs = [preparer.preparation.prepare(request).ref()]
    bundle = preparer.build_many(refs, context)
    validate_request(preparer, request, bundle, context)
    return preparer.save_bundle(bundle)


def validate_request(preparer, request: dict[str, Any], bundle: dict[str, Any],
                     context) -> None:
    """Cross-check the request bindings against the frozen bundle."""
    preparer.preparation.registry.validate("generate-request", request)
    roles = index_by(bundle.get("role_bindings", []), "source_id")
    if "route-stops" not in roles:
        raise ProtocolError("LEADERSHIP_BUNDLE_MISSING_STOPS",
                            "Prepared bundle must contain route-stops role binding")
    stop_binding = roles["route-stops"]
    if stop_binding.get("feature_count", 0) < 1:
        raise ProtocolError("LEADERSHIP_BUNDLE_EMPTY_STOPS",
                            "Route-stops must contain at least one feature")
    # Verify bundle shared_semantics agree with the request
    semantics = bundle.get("shared_semantics", {})
    if semantics.get("stop_count", 0) < 1:
        raise ProtocolError("LEADERSHIP_BUNDLE_INVALID_SEMANTICS",
                            "Bundle semantics missing stop_count")