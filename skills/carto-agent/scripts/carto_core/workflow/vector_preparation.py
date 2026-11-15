"""Bounded vector inputs with closed sidecar sets and immutable provenance.

No implicit coordinate transformation or business interpretation. Optional exact
CSV joins are authorized and evidenced; numeric expression resolution belongs to
the thematic planner. Dependencies are explicit and never auto-installed.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
from typing import Any
from ..canonical import sha256_digest
from ..errors import ProtocolError, SecurityError
from ..artifacts import atomic_write_bytes, protocol_version
from ..repository.immutable_store import ImmutableArtifactStore, StoredArtifact
from ..schema_registry import SchemaRegistry
from ..security.paths import PathGuard
from ..contracts.bundle import context_snapshot

MAX_BYTES = 32 * 1024 * 1024
MAX_FEATURES = 10000
MAX_VERTICES = 200000


def dependencies():
    try:
        import fiona
        import shapely
        from shapely.geometry import shape, mapping
        from shapely.geometry.polygon import orient
        from fiona.crs import CRS
    except ImportError:
        raise ProtocolError('VECTOR_DEPENDENCY_MISSING',
                            'The explicit vector-rendering extra (Fiona/Shapely) is required') from None
    return fiona, shapely, shape, mapping, orient, CRS


def crs_contract(report: dict[str, Any]) -> dict[str, Any]:
    """Reconstruct the CRS contract from a vector preparation report.

    Relocated from ``workflow.preparation_bundle`` (Tier-2 去环 Step5): the
    derivation needs this module's Fiona CRS authority, and its result is frozen
    into both the bundle role bindings and the page view bindings, so it belongs
    with the reader that owns the authority and is covered by the same code
    fingerprints. ``preparation_bundle`` re-exports it for existing importers, and
    the compiler consumes it through ``VectorPreparationService.crs_contract`` --
    the injected port -- instead of importing the execution layer.
    """
    CRS = dependencies()[-1]
    crs = CRS.from_wkt(report['crs_wkt'])
    code = crs.to_epsg()
    if code is not None:
        return {'authority': 'EPSG', 'code': str(code)}
    return {'authority': 'CUSTOM', 'code': 'native-vector', 'wkt_digest': sha256_digest(report['crs_wkt'])}


def reader_digest():
    return sha256_digest({'version': '1.0.0', 'files': {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in
        [Path(__file__), Path(__file__).with_name('thematic.py'), Path(__file__).with_name('material_extraction.py'),
         # finite/metric_value moved to the kernel in Tier-2 去环 Step4: the reader's
         # attribute join calls finite(), so the fingerprint must follow the code.
         Path(__file__).resolve().parents[1] / 'compiler' / 'portrayal_resolver.py', *[Path(__file__).resolve().parents[3] / 'schemas' / (name + '.schema.json')
                          for name in ('vector-input', 'vector-prepared-data')]]}})


# context_snapshot relocated to the neutral leaf ``carto_core.contracts.bundle``
# (single authoritative definition; it was duplicated in compiler/raster_scene.py).
# Imported at the top of this module and re-exported for existing importers such
# as compiler.vector_scene (``from ..workflow.vector_preparation import context_snapshot``).


def _json(payload):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ProtocolError('VECTOR_JSON_DUPLICATE', 'Duplicate JSON member')
            result[key] = value
        return result
    try:
        return json.loads(payload.decode('utf-8'), object_pairs_hook=unique,
                          parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (UnicodeError, ValueError, RecursionError):
        raise ProtocolError('VECTOR_JSON_INVALID', 'Expected bounded finite UTF-8 JSON') from None


def _positions(value):
    if not isinstance(value, (list, tuple)) or not value:
        raise ProtocolError('VECTOR_GEOMETRY_INVALID', 'Missing coordinates')
    if isinstance(value[0], (int, float)):
        if len(value) != 2 or any(isinstance(v, bool) or not math.isfinite(v) for v in value):
            raise ProtocolError('VECTOR_GEOMETRY_INVALID', 'Only finite two-dimensional coordinates are supported')
        yield value
    else:
        for item in value:
            yield from _positions(item)


from .static_assets import StaticAssetStore


class VectorPreparationService(StaticAssetStore):
    def __init__(self, *, project_root, allowed_roots, registry=None):
        self.guard = PathGuard(allowed_roots)
        self.project = self.guard.resolve(project_root, must_exist=True)
        self.project_guard = PathGuard([self.project])
        self.registry = registry or SchemaRegistry()
        self.root = self.project_guard.resolve(self.project / '.carto/vector')
        self.store = ImmutableArtifactStore(self.root / 'documents', path_guard=self.project_guard)

    def save(self, kind, value):
        try:
            self.registry.validate(kind, value)
        except ProtocolError:
            raise ProtocolError('VECTOR_DOCUMENT_INVALID', 'Vector document violates its strict contract') from None
        return self.store.put(kind, protocol_version(kind), value)

    def save_document(self, value, kind):
        return self.save(kind, value)

    def _json_ref(self, ref, kind):
        return self.document(ref, kind)

    def document(self, ref, kind):
        expected_version = protocol_version(kind)
        if (set(ref) != {'id', 'version', 'digest', 'uri'} or ref['id'] != kind or ref['version'] != expected_version):
            raise ProtocolError('VECTOR_REFERENCE_INVALID', 'Wrong vector artifact identity')
        expected = self.store.root / kind / expected_version / (ref['digest'].removeprefix('sha256:') + '.json')
        path = self.project_guard.resolve(ref['uri'], must_exist=True)
        if path != self.project_guard.resolve(expected, must_exist=True) or path.stat().st_size > 64 * 1024 * 1024:
            raise SecurityError('VECTOR_REFERENCE_INVALID', 'Reference is outside its immutable namespace')
        value = _json(path.read_bytes())
        try:
            self.registry.validate(kind, value)
        except ProtocolError:
            raise ProtocolError('VECTOR_DOCUMENT_INVALID', 'Invalid frozen vector document') from None
        if sha256_digest(value) != ref['digest']:
            raise ProtocolError('VECTOR_SNAPSHOT_CHANGED', 'Vector document digest differs')
        return value

    def crs_contract(self, report):
        """CRS contract of a prepared report; delegates to the module function.

        Exposed as a service member so ``compiler.vector_page`` can reach it
        through the injected preparation port (contracts.protocols.
        VectorPreparationProtocol) rather than importing this layer.
        """
        return crs_contract(report)

    def _snapshot_inputs(self, source):
        files = {item['extension']: item for item in source['files']}
        required = {'.geojson'} if source['format'] == 'geojson' else {'.shp', '.shx', '.dbf', '.prj'}
        allowed = required if source['format'] == 'geojson' else required | {'.cpg'}
        if len(files) != len(source['files']) or not required <= set(files) <= allowed:
            raise ProtocolError('VECTOR_SIDECAR_SET', 'An exact mandatory input/sidecar set is required')
        paths = [self.guard.resolve(item['path'], base_root=self.project, must_exist=True) for item in files.values()]
        if source['format'] == 'shapefile' and (len({p.parent for p in paths}) != 1 or len({p.stem for p in paths}) != 1):
            raise ProtocolError('VECTOR_SIDECAR_SET', 'Shapefile sidecars must share a directory and basename')
        payloads = {}
        for extension, item in sorted(files.items()):
            path = self.guard.resolve(item['path'], base_root=self.project, must_exist=True)
            if path.suffix.lower() != extension or not path.is_file() or path.stat().st_size != item['size_bytes']:
                raise ProtocolError('VECTOR_SOURCE_CHANGED', 'Input size or extension differs')
            data = path.read_bytes()
            if len(data) != item['size_bytes'] or len(data) > MAX_BYTES or 'sha256:' + hashlib.sha256(data).hexdigest() != item['digest']:
                raise ProtocolError('VECTOR_SOURCE_CHANGED', 'Input bytes differ from the declared digest')
            payloads[extension] = data
        if sum(map(len, payloads.values())) > MAX_BYTES:
            raise SecurityError('VECTOR_INPUT_TOO_LARGE', 'Combined input exceeds the vector byte limit')
        digest = sha256_digest([{k: v for k, v in item.items() if k != 'path'} for _, item in sorted(files.items())])
        directory = self.project_guard.resolve(self.root / 'inputs' / digest[7:])
        directory.mkdir(parents=True, exist_ok=True)
        assets = []
        for ext, data in payloads.items():
            target = self.project_guard.resolve(directory / ('dataset' + ext))
            if target.exists():
                if target.read_bytes() != data:
                    raise ProtocolError('VECTOR_SNAPSHOT_CHANGED', 'Immutable vector sidecar changed')
            else:
                atomic_write_bytes(target, data)
            assets.append({'extension': ext, 'ref': {'id': 'vector-source', 'version': '1.0.0',
                           'digest': files[ext]['digest'], 'uri': str(target)}, 'size_bytes': len(data)})
        return digest, assets

    def _read(self, source, assets):
        fiona, shapely, shape, mapping, orient, CRS = dependencies()
        by_ext = {a['extension']: Path(a['ref']['uri']) for a in assets}
        try:
            expected_crs = CRS.from_user_input(source['crs'])
            if not (expected_crs.is_geographic or expected_crs.is_projected):
                raise ProtocolError('VECTOR_CRS_UNSUPPORTED', 'Only geographic or projected planar views are supported')
            if source['format'] == 'geojson':
                if expected_crs != CRS.from_epsg(4326):
                    raise ProtocolError('VECTOR_CRS_MISMATCH', 'GeoJSON requires EPSG:4326; no implicit conversion')
                collection = _json(by_ext['.geojson'].read_bytes())
                if not isinstance(collection, dict) or set(collection) != {'type', 'features'} or collection['type'] != 'FeatureCollection':
                    raise ProtocolError('VECTOR_GEOJSON_INVALID', 'Expected a strict GeoJSON FeatureCollection')
                records = collection['features']
                if not isinstance(records, list):
                    raise ProtocolError('VECTOR_GEOJSON_INVALID', 'Features must be an array')
                raw = []
                for feature in records:
                    if not isinstance(feature, dict) or not {'type', 'geometry', 'properties'} <= set(feature) <= {'type', 'geometry', 'properties', 'id'} or feature['type'] != 'Feature':
                        raise ProtocolError('VECTOR_GEOJSON_INVALID', 'Unsupported GeoJSON feature members')
                    raw.append((feature['geometry'], feature['properties']))
            else:
                # Only a local isolated mandatory sidecar set reaches GDAL. No URLs,
                # archives, virtual file systems, alternate drivers or source discovery.
                with fiona.open(str(by_ext['.shp']), 'r', enabled_drivers=['ESRI Shapefile'],
                                encoding=source['encoding']) as dataset:
                    if dataset.crs != expected_crs:
                        raise ProtocolError('VECTOR_CRS_MISMATCH', 'PRJ does not match the explicit source CRS')
                    if not 1 <= len(dataset) <= MAX_FEATURES:
                        raise SecurityError('VECTOR_FEATURE_LIMIT', 'Unsupported vector record count')
                    raw = [(dict(row['geometry']) if row['geometry'] else None, dict(row['properties'])) for row in dataset]
            if not 1 <= len(raw) <= MAX_FEATURES:
                raise SecurityError('VECTOR_FEATURE_LIMIT', 'Unsupported vector record count')
            features, geometries, count = [], [], 0
            for index, (geometry, props) in enumerate(raw):
                if not isinstance(geometry, dict) or geometry.get('type') not in {'Point', 'Polygon', 'MultiPolygon', 'LineString', 'MultiLineString'}:
                    raise ProtocolError('VECTOR_GEOMETRY_UNSUPPORTED', 'Only point, line and polygon sources are enabled')
                if set(geometry) - {'type', 'coordinates', 'geometries'} or geometry.get('geometries'):
                    raise ProtocolError('VECTOR_GEOMETRY_INVALID', 'Geometry collections are unsupported')
                for position in _positions(geometry['coordinates']):
                    count += 1
                    if count > MAX_VERTICES:
                        raise SecurityError('VECTOR_VERTEX_LIMIT', 'Vector geometry exceeds the vertex budget')
                    if expected_crs.is_geographic and not (-180 <= position[0] <= 180 and -90 <= position[1] <= 90):
                        raise ProtocolError('VECTOR_GEOMETRY_INVALID', 'Geographic coordinate is outside bounds')
                geom = shape(geometry)
                if geom.is_empty or not geom.is_valid or geom.has_z:
                    raise ProtocolError('VECTOR_GEOMETRY_INVALID', 'Empty, invalid or non-2D geometry; no automatic repair')
                if geom.geom_type == 'Polygon':geom = orient(geom, sign=1.0)
                if geom.geom_type == 'MultiPolygon':
                    from shapely.geometry import MultiPolygon
                    geom = MultiPolygon([orient(part, sign=1.0) for part in geom.geoms])
                # Normalize tuples to plain JSON without guessing IDs or numeric fields.
                features.append({'id': f'feature-{index}', 'geometry': json.loads(json.dumps(mapping(geom))), 'properties': props})
                geometries.append(geom)
            kinds = {'point' if g.geom_type == 'Point' else 'line' if g.geom_type in ('LineString', 'MultiLineString') else 'polygon' for g in geometries}
            if len(kinds) != 1:
                raise ProtocolError('VECTOR_GEOMETRY_MIXED', 'A source must have one geometry family')
            bounds = [min(g.bounds[0] for g in geometries), min(g.bounds[1] for g in geometries),
                      max(g.bounds[2] for g in geometries), max(g.bounds[3] for g in geometries)]
            if expected_crs.is_geographic and bounds[2] - bounds[0] > 180:
                raise ProtocolError('VECTOR_DATELINE_UNSUPPORTED', 'Antimeridian wrapping is not enabled')
            return {'features': features, 'bounds': bounds, 'geometry': kinds.pop(),
                    'crs_wkt': expected_crs.to_wkt(), 'crs_kind': 'geographic' if expected_crs.is_geographic else 'projected',
                    'runtime': {'fiona': fiona.__version__, 'shapely': shapely.__version__, 'gdal': fiona.__gdal_version__}}
        except (ProtocolError, SecurityError):raise
        except Exception:
            # Do not expose driver errors, business rows, coordinates or source paths.
            raise ProtocolError('VECTOR_READ_FAILED', 'Vector input could not be read under the declared contract') from None

    def prepare(self, source, context):
        self.registry.validate('vector-input', source)
        identity = context_snapshot(context)
        digest, assets = self._snapshot_inputs(source)
        body = {'schema_version': 1, 'kind': 'vector-prepared-data', 'context': identity,
                'source': deepcopy(source), 'source_manifest_digest': digest, 'source_assets': assets,
                **self._read(source, assets), 'reader_digest': reader_digest()}
        if source.get('attribute_join'):
            if 'join' not in context.authorized_capabilities:
                raise SecurityError('CAPABILITY_NOT_AUTHORIZED', 'Attribute join was not authorized')
            from .thematic import join_attributes
            body['attribute_evidence'] = join_attributes(self, body, source['attribute_join'])
        return self.save('vector-prepared-data', body)

    def load_verified(self, ref, context):
        value = self.document(ref, 'vector-prepared-data')
        if value['context'] != context_snapshot(context):
            raise SecurityError('VECTOR_SCOPE_MISMATCH', 'Preparation belongs to another execution')
        if value['reader_digest'] != reader_digest():
            raise ProtocolError('VECTOR_READER_CHANGED', 'Prepare again with the current reader')
        declared = {item['extension']: item for item in value['source']['files']}
        digest = sha256_digest([{k: v for k, v in item.items() if k != 'path'} for _, item in sorted(declared.items())])
        if digest != value['source_manifest_digest'] or len(value['source_assets']) != len(declared):
            raise ProtocolError('VECTOR_SNAPSHOT_CHANGED', 'Input manifest differs')
        if {a['extension'] for a in value['source_assets']} != set(declared):
            raise ProtocolError('VECTOR_SNAPSHOT_CHANGED', 'Missing or duplicate frozen sidecar')
        for asset in value['source_assets']:
            ext = asset['extension']
            path = self.project_guard.resolve(asset['ref']['uri'], must_exist=True)
            expected = self.project_guard.resolve(self.root / 'inputs' / digest[7:] / ('dataset' + ext), must_exist=True)
            if (path != expected or asset['ref']['digest'] != declared[ext]['digest']
                    or path.stat().st_size != asset['size_bytes'] or asset['size_bytes'] != declared[ext]['size_bytes']
                    or 'sha256:' + hashlib.sha256(path.read_bytes()).hexdigest() != asset['ref']['digest']):
                raise ProtocolError('VECTOR_SNAPSHOT_CHANGED', 'Frozen sidecar changed')
        rebuilt = self._read(value['source'], value['source_assets'])
        if value['source'].get('attribute_join'):
            from .thematic import join_attributes
            if 'attribute_evidence' not in value:
                raise ProtocolError('THEMATIC_EVIDENCE_MISSING', 'Joined data must retain its source evidence')
            evidence = join_attributes(self, rebuilt, value['source']['attribute_join'], value['attribute_evidence']['asset'])
            if evidence != value['attribute_evidence']:
                raise ProtocolError('THEMATIC_EVIDENCE_DRIFT', 'Join evidence differs')
        if any(value[key] != item for key, item in rebuilt.items()):
            raise ProtocolError('VECTOR_PREPARATION_CHANGED', 'Prepared geometry, attributes or runtime differ')
        return value
