"""Unified bundle preparer: geometry-branched preparation, validation and loading.

Replaces raster_bundle.py and vector_bundle.py from the split-variant era. Both
geometry strategies produce the same ``prepared-data-bundle`` artifact kind with
identical structure (role_bindings, datasets, tool_receipts, quality_evidence,
open_issues). The internal preparation methods differ per geometry (MCP gateway
for raster, hermetic Fiona/Shapely for vector) but the bundle contract stays
identical.

Properties of a valid bundle, independent of geometry:

* Every preparation ref is re-verified before bundling.
* Sources must share CRS and declared data nature; no implicit reprojection.
* Exactly 1–4 unique source IDs; duplicate or conflicting preparations reject.
* The frozen bundle is recomputed on every load_verified call to detect drift.
"""
from __future__ import annotations
from copy import deepcopy
from typing import Any

from ..canonical import sha256_digest
from ..compiler.page_bindings import category_counts, index_by
from ..errors import ProtocolError, SecurityError
from .models import ExecutionContext
# crs_contract lives with the vector reader that owns the Fiona CRS authority
# (Tier-2 去环 Step5); re-exported here so the historical import path keeps working.
from .vector_preparation import crs_contract

GEOMETRIES = ("raster", "vector")


class BundlePreparer:
    """Geometry-branched bundle preparer.  Internal branching stays within geometry-
    specific strategy methods; callers use the same four-method interface regardless
    of geometry.
    """

    def __init__(self, preparation, geometry: str):
        if geometry not in GEOMETRIES:
            raise ProtocolError("BUNDLE_GEOMETRY_UNKNOWN", f"Geometry must be one of {GEOMETRIES}")
        self.preparation = preparation
        self.geometry = geometry

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    def _scope(self, context: ExecutionContext) -> dict[str, Any]:
        return {key: getattr(context, key) for key in ("run_id", "tenant_id", "project_id", "subject_id")}

    def _save_bundle(self, body: dict[str, Any]) -> dict[str, Any]:
        """Persist the bundle through the geometry-appropriate save path."""
        if self.geometry == "vector":
            ref = self.preparation.save('prepared-data-bundle', body).ref()
        else:
            ref = self.preparation.save_document(body, 'prepared-data-bundle').ref()
        return {"bundle": deepcopy(body), "bundle_ref": ref}

    # ------------------------------------------------------------------
    # build_many
    # ------------------------------------------------------------------

    def build_many(self, references: list[dict[str, Any]], context: ExecutionContext):
        """Build a bundle from 1–4 verified preparations.  Geometry determines the
        internal preparation loading, verification and binding construction.
        """
        context.require_project_scope()
        if not 1 <= len(references) <= 4:
            raise ProtocolError('BUNDLE_SOURCE_COUNT', 'One to four unique sources required')
        if self.geometry == "vector":
            return self._build_many_vector(references, context)
        return self._build_many_raster(references, context)

    def _build_many_raster(self, prepared_refs, context):
        sources: dict[str, Any] = {}
        for ref in prepared_refs:
            report, evidence = self.preparation.load_verified(ref)
            if report['context'] != self._scope(context):
                raise SecurityError('CLASSIFICATION_SCOPE_MISMATCH', 'Preparation belongs to another execution')
            if report['status'] != 'ready' or report['questions']:
                raise ProtocolError('CLASSIFICATION_CLARIFICATION_REQUIRED', 'Resolve every preparation')
            source = report['request']['source']
            sid = source['source_ref']['id']
            if sid in sources and sources[sid][0] != ref:
                raise ProtocolError('RASTER_SOURCE_ID_DUPLICATE', 'Different preparations use the same source ID')
            sources[sid] = (deepcopy(ref), report, evidence)
        bindings: list[dict[str, Any]] = []
        data: dict[str, Any] = {}
        receipts: dict[str, Any] = {}
        refs: list[dict[str, Any]] = []
        nature: set[str] = set()
        crs_set: set[str] = set()
        for sid, (ref, report, evidence) in sorted(sources.items()):
            source = report['request']['source']
            info = evidence['raster_info']
            asset = report['source_snapshot']['artifact_ref']
            nature.add(source['data_nature'])
            crs_set.add(sha256_digest(source['crs']))
            data[sha256_digest(asset)] = deepcopy(asset)
            receipts[sha256_digest(report['gis_result_ref'])] = deepcopy(report['gis_result_ref'])
            refs.append(ref)
            bindings.append({
                'data_type': 'raster', 'source_id': sid, 'role': source['role'],
                'dataset_ref': deepcopy(asset), 'prepared_ref': ref, 'band': source['band'],
                'bbox': info['bounds'], 'crs': source['crs'],
                'width': info['width'], 'height': info['height'],
                'category_counts': category_counts(report),
                'facts_digest': sha256_digest({
                    'source': source, 'raster_info': info,
                    'artifact_digest': asset['digest'],
                }),
                'semantic_fields': self._raster_semantic_fields(report),
            })
        if len(nature) != 1 or len(crs_set) != 1:
            raise ProtocolError('BUNDLE_PROFILE_MISMATCH', 'All sources must share nature and CRS; no implicit reprojection')
        task = self.preparation.save_document({
            'schema_version': 1,
            'inputs': [{'source_id': b['source_id'], 'prepared_ref': b['prepared_ref']} for b in bindings],
        }, 'bundle-inputs')
        summary: dict[str, Any] = {'data_nature': next(iter(nature))}
        if len(bindings) == 1:
            summary.update(combined_bbox=bindings[0]['bbox'], category_counts=bindings[0]['category_counts'])
        body: dict[str, Any] = {
            'schema_version': 1,
            'bundle_id': 'raster-bundle-' + task.digest[7:31],
            'task_ref': task.ref(),
            'datasets': [data[k] for k in sorted(data)],
            'transformations': [],
            'tool_receipts': [receipts[k] for k in sorted(receipts)],
            'quality_evidence': refs,
            'open_issues': [],
            'role_bindings': bindings,
            'summary': summary,
        }
        body['digest'] = sha256_digest(body)
        self.preparation.registry.validate('prepared-data-bundle', body)
        return body

    def _build_many_vector(self, references, context):
        entries: dict[str, Any] = {}
        for ref in references:
            report = self.preparation.load_verified(ref, context)
            sid = report['source']['source_id']
            if sid in entries and entries[sid][0] != ref:
                raise ProtocolError('VECTOR_SOURCE_DUPLICATE', 'A source has conflicting preparations')
            entries[sid] = (ref, report)
        if len({r['crs_wkt'] for _, r in entries.values()}) != 1 or len({r['source']['data_nature'] for _, r in entries.values()}) != 1:
            raise ProtocolError('VECTOR_SOURCE_PROFILE', 'Sources must share CRS and declared data nature')
        bindings: list[dict[str, Any]] = []
        for sid, (ref, report) in sorted(entries.items()):
            bindings.append({
                'data_type': 'vector', 'source_id': sid, 'role': report['source']['role'],
                'dataset_ref': deepcopy(ref), 'prepared_ref': deepcopy(ref),
                'geometry_types': [report['geometry']], 'feature_count': len(report['features']),
                'bbox': report['bounds'], 'crs': crs_contract(report),
                'semantic_fields': report['source'].get('semantic_fields', {}),
                'facts_digest': BundlePreparer._vector_facts_digest(report),
            })
        task = self.preparation.save('bundle-inputs', {
            'schema_version': 1,
            'inputs': [{'source_id': b['source_id'], 'prepared_ref': b['prepared_ref']} for b in bindings],
        })
        data_nature = next(iter(entries.values()))[1]['source']['data_nature']
        body: dict[str, Any] = {
            'schema_version': 1,
            'bundle_id': 'vector-bundle-' + sha256_digest(bindings)[7:31],
            'task_ref': task.ref(),
            'datasets': [b['dataset_ref'] for b in bindings],
            'transformations': [], 'tool_receipts': [],
            'quality_evidence': [b['prepared_ref'] for b in bindings],
            'role_bindings': bindings, 'open_issues': [],
            'summary': {'data_nature': data_nature},
        }
        body['digest'] = sha256_digest(body)
        self.preparation.registry.validate('prepared-data-bundle', body)
        return body

    # ------------------------------------------------------------------
    # prepare_request
    # ------------------------------------------------------------------

    def prepare_request(self, request: dict[str, Any], context: ExecutionContext):
        """Validate request bindings, build and persist the bundle."""
        self.preparation.registry.validate('generate-request', request)
        if self.geometry == "vector":
            return self._prepare_request_vector(request, context)
        return self._prepare_request_raster(request, context)

    def _prepare_request_raster(self, request, context):
        bindings = index_by(request.get('prepared_raster_bindings', []), 'source_id')
        bundle = self.build_many([b['prepared_ref'] for _, b in sorted(bindings.items())], context)
        self.validate_request(request, bundle, context)
        return self._save_bundle(bundle)

    def _prepare_request_vector(self, request, context):
        sources = index_by(request['vector_sources'], 'source_id')
        panels = index_by(request['vector_panels'], 'id')
        if {p['source_id'] for p in panels.values()} != set(sources):
            raise ProtocolError('VECTOR_SOURCE_BINDING', 'Every declared source must be used by a panel')
        refs = [self.preparation.prepare(source, context).ref()
                for _, source in sorted(sources.items())]
        bundle = self.build_many(refs, context)
        self.validate_request(request, bundle, context)
        return self._save_bundle(bundle)

    # ------------------------------------------------------------------
    # validate_request
    # ------------------------------------------------------------------

    def validate_request(self, request: dict[str, Any], bundle: dict[str, Any],
                         context: ExecutionContext) -> None:
        """Cross-check the request bindings against the frozen bundle. Geometry-
        specific binding layouts are verified against the appropriate preparation
        service.
        """
        self.preparation.registry.validate('generate-request', request)
        if self.geometry == "vector":
            self._validate_request_vector(request, bundle, context)
        else:
            self._validate_request_raster(request, bundle, context)

    # ------------------------------------------------------------------
    # Semantic helper
    # ------------------------------------------------------------------

    @staticmethod
    def _raster_semantic_fields(report: dict[str, Any]) -> dict[str, str]:
        """Extract semantic field mappings from a raster preparation report.

        Each classified row maps a pixel value (int) to a category label (str).
        These become the semantic_fields for the raster role binding.
        """
        rows = report.get('rows', [])
        fields: dict[str, str] = {}
        for row in rows:
            value = row.get('value')
            label = row.get('label')
            if value is not None and label:
                fields[f"value_{value}"] = label
        return fields

    @staticmethod
    def _vector_facts_digest(report: dict[str, Any]) -> str:
        """Compute facts digest from vector preparation geometry and attributes."""
        from ..canonical import sha256_digest
        crs = crs_contract(report)
        return sha256_digest({
            'geometry_type': report.get('geometry'),
            'feature_count': len(report.get('features', [])),
            'bounds': report.get('bounds'),
            'crs': crs,
            'source_manifest_digest': report.get('source_manifest_digest'),
            'attributes': [f['properties'] for f in report.get('features', [])],
            'attribute_evidence': report.get('attribute_evidence'),
        })

    # ------------------------------------------------------------------
    # Geometry-specific request verification
    # ------------------------------------------------------------------

    def _validate_request_raster(self, request, bundle, context):
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
            report, _ = self.preparation.load_verified(binding['prepared_ref'])
            if sources[sid] != report['request']['source'] or roots[sid] != sources[sid]['source_ref']:
                raise SecurityError('RASTER_GENERATE_SOURCE_MISMATCH', 'Declared source differs from frozen preparation')
        if (request.get('run_id') != context.run_id or request['project_id'] != context.project_id
                or request['subject']['tenant_id'] != context.tenant_id
                or request['subject']['subject_id'] != context.subject_id):
            raise SecurityError('RASTER_GENERATE_SOURCE_MISMATCH', 'Request scope differs')

    def _validate_request_vector(self, request, bundle, context):
        sources = index_by(request['vector_sources'], 'source_id')
        actual = index_by(bundle['role_bindings'], 'source_id')
        roots = index_by(request['sources'], 'id')
        if set(sources) != set(actual) or set(roots) != set(sources):
            raise ProtocolError('VECTOR_SOURCE_BINDING', 'Source identities differ')
        for sid, source in sources.items():
            report = self.preparation.load_verified(actual[sid]['prepared_ref'], context)
            if report['source'] != source or roots[sid]['digest'] != sha256_digest(source):
                raise ProtocolError('VECTOR_SOURCE_BINDING', 'Declared source contract changed')

    # ------------------------------------------------------------------
    # load_verified
    # ------------------------------------------------------------------

    def load_verified(self, ref: dict[str, str], context: ExecutionContext):
        """Load a frozen bundle, rebuild from its declared preparations, and assert
        the two match — drift is always detected, regardless of geometry.
        """
        if self.geometry == "vector":
            value = self.preparation.document(ref, 'prepared-data-bundle')
            if value != self.build_many([b['prepared_ref'] for b in value['role_bindings']], context):
                raise ProtocolError('VECTOR_BUNDLE_CHANGED', 'Bundle differs from verified source bindings')
            return value
        # Raster: document() returns (value,) for prepared-data-bundle
        bundle = self.preparation.document(ref, 'prepared-data-bundle')
        inputs = self.preparation.document(bundle['task_ref'], 'bundle-inputs')
        refs = index_by(inputs['inputs'], 'source_id')
        if bundle != self.build_many([v['prepared_ref'] for _, v in sorted(refs.items())], context):
            raise ProtocolError('RASTER_BUNDLE_CHANGED', 'Bundle differs from verified preparations')
        return bundle

    # ------------------------------------------------------------------
    # Convenience: single-ref build
    # ------------------------------------------------------------------

    def build(self, prepared_ref, context):
        return self.build_many([prepared_ref], context)

    def prepare(self, prepared_ref, context):
        if self.geometry == "vector":
            return self.preparation.save('prepared-data-bundle', self.build(prepared_ref, context))
        return self.preparation.save_document(self.build(prepared_ref, context), 'prepared-data-bundle')