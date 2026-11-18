"""general-thematic request binding preparation/validation (moved from BundlePreparer, I-4b).

The kernel ``BundlePreparer`` keeps the geometry-branched bundle mechanics (build_many,
load_verified, save_bundle); this module supplies the scenario-specific request-body
binding understanding: which request fields declare sources/preparations/panels and how
they cross-check against the frozen bundle. Moved verbatim; error codes preserved.
"""
from __future__ import annotations

from typing import Any

from ...canonical import sha256_digest
from ...compiler.page_bindings import index_by
from ...errors import ProtocolError, SecurityError


def prepare_request(preparer, request: dict[str, Any], context):
    """Validate request bindings, build and persist the bundle."""
    preparer.preparation.registry.validate('generate-request', request)
    if preparer.geometry == "vector":
        return _prepare_request_vector(preparer, request, context)
    return _prepare_request_raster(preparer, request, context)


def _prepare_request_raster(preparer, request, context):
    bindings = index_by(request.get('prepared_raster_bindings', []), 'source_id')
    bundle = preparer.build_many([b['prepared_ref'] for _, b in sorted(bindings.items())], context)
    validate_request(preparer, request, bundle, context)
    return preparer.save_bundle(bundle)


def _prepare_request_vector(preparer, request, context):
    sources = index_by(request['vector_sources'], 'source_id')
    panels = index_by(request['vector_panels'], 'id')
    if {p['source_id'] for p in panels.values()} != set(sources):
        raise ProtocolError('VECTOR_SOURCE_BINDING', 'Every declared source must be used by a panel')
    refs = [preparer.preparation.prepare(source, context).ref()
            for _, source in sorted(sources.items())]
    bundle = preparer.build_many(refs, context)
    validate_request(preparer, request, bundle, context)
    return preparer.save_bundle(bundle)


def validate_request(preparer, request: dict[str, Any], bundle: dict[str, Any], context) -> None:
    """Cross-check the request bindings against the frozen bundle."""
    preparer.preparation.registry.validate('generate-request', request)
    if preparer.geometry == "vector":
        _validate_request_vector(preparer, request, bundle, context)
    else:
        _validate_request_raster(preparer, request, bundle, context)


def _validate_request_raster(preparer, request, bundle, context):
    sources: dict[str, Any] = {}
    for source in request.get('source_bindings', []):
        sid = source['source_ref']['id']
        if sid in sources:
            raise ProtocolError('RASTER_SOURCE_ID_DUPLICATE', 'Source IDs must be unique')
        sources[sid] = source
    declared = index_by(request.get('prepared_raster_bindings', []), 'source_id')
    actual = index_by(bundle['role_bindings'], 'source_id')
    if not 1 <= len(actual) <= 4 or set(sources) != set(actual) or set(declared) != set(actual):
        raise ProtocolError('RASTER_GENERATE_BINDING_REQUIRED', 'Explicit sources and preparations must match')
    roots = index_by(request['sources'], 'id')
    if set(roots) != set(actual):
        raise ProtocolError('RASTER_GENERATE_SOURCE_MISMATCH', 'Source references differ')
    for sid, binding in actual.items():
        expected = {'source_id': sid, 'role': binding['role'], 'prepared_ref': binding['prepared_ref']}
        if declared[sid] != expected:
            raise ProtocolError('RASTER_GENERATE_BINDING_MISMATCH', 'Preparation binding differs')
        report, _ = preparer.preparation.load_verified(binding['prepared_ref'])
        if sources[sid] != report['request']['source'] or roots[sid] != sources[sid]['source_ref']:
            raise SecurityError('RASTER_GENERATE_SOURCE_MISMATCH', 'Declared source differs from frozen preparation')
    if (request.get('run_id') != context.run_id or request['project_id'] != context.project_id
            or request['subject']['tenant_id'] != context.tenant_id
            or request['subject']['subject_id'] != context.subject_id):
        raise SecurityError('RASTER_GENERATE_SOURCE_MISMATCH', 'Request scope differs')


def _validate_request_vector(preparer, request, bundle, context):
    sources = index_by(request['vector_sources'], 'source_id')
    actual = index_by(bundle['role_bindings'], 'source_id')
    roots = index_by(request['sources'], 'id')
    if set(sources) != set(actual) or set(roots) != set(sources):
        raise ProtocolError('VECTOR_SOURCE_BINDING', 'Source identities differ')
    for sid, source in sources.items():
        report = preparer.preparation.load_verified(actual[sid]['prepared_ref'], context)
        if report['source'] != source or roots[sid]['digest'] != sha256_digest(source):
            raise ProtocolError('VECTOR_SOURCE_BINDING', 'Declared source contract changed')