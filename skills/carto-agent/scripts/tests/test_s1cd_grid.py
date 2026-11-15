"""S1-C/D finite grids, real multi-source TIFFs and all-panel provenance.

Only synthetic data in TemporaryDirectory; no user approvals or business data.
"""
from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch

from carto_core.adapters.formal_renderer import environment_snapshot
from carto_core.adapters.page_renderer import PageRenderer
from carto_core.adapters.raster_renderer import _dependencies
from carto_core.compiler.grid_layout import grid_cases, instantiate_grid
from carto_core.compiler.layout import LayoutResolver
from carto_core.compiler.raster_page_contract import compile_page_request, validate_page_request
from carto_core.compiler.raster_scene import RasterSceneCompiler
from carto_core.errors import CartoError, ProtocolError
from carto_core.scenarios.general_thematic import layout_contract
from carto_core.workflow.preparation_bundle import BundlePreparer
from tests.fixtures.schema_cases import VALID_CASES
from tests.test_raster_classification import PreparationFixture
from tests.helpers import page_request, release_test_font_handles, set_raster, compile_portrayal


class GridContractTests(unittest.TestCase):
    def setUp(self):
        self.layout = layout_contract()
        self.resolver = LayoutResolver()

    def test_all_six_cases_use_one_immutable_template(self):
        original = deepcopy(self.layout)
        cases = grid_cases(self.layout)
        self.assertEqual(6, len(cases))
        digests = set()
        for params in cases:
            with self.subTest(params=params):
                resolved = self.resolver.resolve(self.layout, 300, parameters=params)
                self.resolver.validate(resolved)
                count = params['rows'] * params['columns']
                self.assertEqual(count, len(resolved['map_frame_ids']))
                legends = [f for f in resolved['contract']['frames'] if f['type'] == 'legend']
                self.assertEqual(1 if params['legend_mode'] == 'shared' else count, len(legends))
                self.assertEqual((3508, 2480), (resolved['page']['width_px'], resolved['page']['height_px']))
                digests.add(resolved['contract_ref']['digest'])
        self.assertEqual(1, len(digests))
        self.assertEqual(original, self.layout)

    def test_missing_unsupported_and_unknown_parameters_fail(self):
        for params in [None, {'rows': 2, 'columns': 1, 'legend_mode': 'shared'},
                       {'rows': 3, 'columns': 2, 'legend_mode': 'independent'},
                       {'rows': 1, 'columns': 2, 'legend_mode': 'auto'},
                       {'rows': 1, 'columns': 2, 'legend_mode': 'shared', 'freeform': True}]:
            with self.subTest(params=params), self.assertRaises(ProtocolError):
                self.resolver.resolve(self.layout, 300, parameters=params)

    def test_snapshot_and_explicit_map_selection_are_enforced(self):
        params = {'rows': 1, 'columns': 2, 'legend_mode': 'shared'}
        resolved = self.resolver.resolve(self.layout, 300, parameters=params)
        with self.assertRaisesRegex(ProtocolError, 'LAYOUT_MAP_BINDING_REQUIRED'):
            self.resolver.map_frame(resolved)
        self.assertEqual('view-r0-c1', self.resolver.map_frame(resolved, 'map-r0-c1')['content_id'])
        for field in ('contract', 'template_contract'):
            bad = deepcopy(resolved)
            bad[field]['frames'][0]['bounds'][0] += 1
            with self.subTest(field=field), self.assertRaises(ProtocolError):
                self.resolver.validate(bad)
        bad = deepcopy(resolved)
        bad['parameters']['legend_mode'] = 'independent'
        with self.assertRaises(ProtocolError):
            self.resolver.validate(bad)

    def test_grid_cannot_be_silently_used_as_fixed_layout(self):
        params = {'rows': 1, 'columns': 2, 'legend_mode': 'independent'}
        fixed = instantiate_grid(self.layout, params)
        with self.assertRaisesRegex(ProtocolError, 'LAYOUT_MAP_COUNT_UNSUPPORTED'):
            self.resolver.resolve(fixed, 300)
        with self.assertRaisesRegex(ProtocolError, 'GRID_PARAMETERS_UNSUPPORTED'):
            self.resolver.resolve(fixed, 300, parameters=params)

    def test_renderer_fingerprint_covers_grid_and_manifest_contracts(self):
        from carto_core.adapters.raster_renderer import renderer_digest
        from carto_core.adapters.formal_renderer import formal_renderer_digest
        original = Path.read_bytes
        for name, digest_fn in [("grid_layout.py", renderer_digest),
                                ("grid-parameters.schema.json", renderer_digest),
                                ("resolved-layout.schema.json", renderer_digest),
                                ("bundle-inputs.schema.json", formal_renderer_digest),
                                ("raster_legends.py", formal_renderer_digest)]:
            baseline = digest_fn()
            def altered(path, name=name):
                content = original(path)
                return content + b" " if path.name == name else content
            with self.subTest(name=name), patch.object(Path, "read_bytes", altered):
                self.assertNotEqual(baseline, digest_fn())

    def test_negative_cell_area_and_overlapping_frames_fail(self):
        for key, value in [('legend_width_mm', 300), ('column_gap_mm', 300)]:
            bad = deepcopy(self.layout)
            bad['grid'][key] = value
            with self.subTest(key=key), self.assertRaises(ProtocolError):
                self.resolver.resolve(bad, 300, parameters=grid_cases(bad)[2])
        bad = deepcopy(self.layout)
        bad['grid']['shared_legend_bounds'] = [10, 27, 277, 30]
        with self.assertRaisesRegex(ProtocolError, 'LAYOUT_FRAME_OVERLAP'):
            self.resolver.resolve(bad, 300, parameters=grid_cases(bad)[3])


class GridPageTests(PreparationFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        try:
            self.np, self.rio, _, _, _, _, self.Image = _dependencies()
            import fontTools  # noqa: F401
        except (CartoError, ImportError) as exc:
            self.skipTest(str(exc))
        self.addCleanup(release_test_font_handles)
        self.sources = []
        self.prepared = []
        self.portrayals = []
        for index, data in enumerate(([[1, 2], [2, 1]], [[1, 3, 3], [3, 1, 3]])):
            self.source_path = self.root / f'source-{index}.tif'
            self.request['source']['path'] = self.source_path.name
            self.request['source']['source_ref']['id'] = f'source-{index}'
            self.legend_path = self.root / f'legend-{index}.csv'
            self.request['legend']['path'] = self.legend_path.name
            self.legend_path.write_text('value,label,color\n1,Class A,#FF0000\n2,Class B,#00FF00\n3,Class C,#0000FF\n', encoding='utf-8')
            set_raster(self, self.np.array(data, dtype='uint8'), xsize=30 * (index + 1))
            prepared = self.analyze()
            report, _ = self.service.load_verified(prepared.ref())
            self.assertEqual('ready', report['status'])
            self.sources.append(deepcopy(self.request['source']))
            self.prepared.append(prepared)
            self.portrayals.append(compile_portrayal(self.service, prepared, self.context).ref())
        self.renderer = PageRenderer(self.service)

    def page(self, rows=1, columns=2, mode='shared', dpi=72):
        base = page_request(self.service, self.prepared[0], self.context, dpi=dpi)
        base.pop('appearance')
        base.pop('bindings')
        base['resolved_layout'] = LayoutResolver().resolve(
            layout_contract(), dpi,
            parameters={'rows': rows, 'columns': columns, 'legend_mode': mode})
        frames = base['resolved_layout']['contract']['frames']
        maps = [f for f in frames if f['type'] == 'map']
        base['portrayals'] = [{'view_id': f['content_id'], 'ref': self.portrayals[i % 2]}
                             for i, f in enumerate(maps)]
        base['legends'] = [{'content_id': f['content_id'], 'title': 'Classes'}
                          for f in frames if f['type'] == 'legend']
        base['texts'] = [{'content_id': f['content_id'], 'text': 'Synthetic map' if f['type'] == 'title' else 'Synthetic source'}
                         for f in frames if f['type'] not in {'map', 'legend'}]
        base['scale_bar'] = None
        base['grid_north'] = None
        return compile_page_request(self.service, base, VALID_CASES['cartography'], self.context, BundlePreparer)

    def test_multi_source_bundle_preserves_source_specific_extents_and_counts(self):
        bundle = BundlePreparer(self.service, "raster").build_many([p.ref() for p in self.prepared], self.context)
        self.assertEqual(2, len(bundle['role_bindings']))
        self.assertNotIn('combined_bbox', bundle['summary'])
        self.assertNotIn('category_counts', bundle['summary'])
        for binding in bundle['role_bindings']:
            self.assertIn('source_id', binding)
            self.assertEqual(2, binding['category_counts']['observed_class_count'])
        reused = BundlePreparer(self.service, "raster").build_many(
            [p.ref() for p in self.prepared] * 2, self.context)
        self.assertEqual(bundle, reused)

    def test_real_panels_independent_and_shared_union_render_without_extent_union(self):
        for mode in ('independent', 'shared'):
            with self.subTest(mode=mode):
                page = self.page(mode=mode)
                expected = [[1, 2], [1, 3]] if mode == 'independent' else [[1, 2, 3]]
                self.assertEqual(expected, [[item['value'] for item in legend['items']] for legend in page['legends']])
                artifact = self.renderer.render(page, self.context)
                output = self.renderer.load_verified(artifact.ref(), self.context)
                self.assertEqual(2, len(output['body_refs']))
                bodies = [self.service.document(item['ref'], 'raster-map-body') for item in output['body_refs']]
                self.assertNotEqual(bodies[0]['bounds'], bodies[1]['bounds'])
                for ref, body in zip(output['body_refs'], bodies):
                    self.assertEqual(ref['frame_id'], body['frame_id'])
                    self.assertEqual(next(x['ref'] for x in page['portrayals'] if x['view_id'] == ref['view_id']), body['portrayal_ref'])
                with self.Image.open(output['outputs']['png']['artifact_ref']['uri']) as image:
                    self.assertEqual((842, 595), image.size)
                    # Sample actual map interiors, not legend swatches or aggregate colors.
                    for body, expected in zip(bodies, (((255, 0, 0), (0, 255, 0)), ((255, 0, 0), (0, 0, 255)))):
                        x, y, w, h = body['image_rect']
                        source_width = 2 if body is bodies[0] else 3
                        actual = [image.getpixel((int(x + w * (i + 0.5) / source_width), int(y + h / 4)))[:3]
                                  for i in range(2)]
                        self.assertEqual(list(expected), actual)
                    colors = set(map(tuple, self.np.unique(self.np.asarray(image.convert('RGB')).reshape(-1, 3), axis=0)))
                    self.assertTrue({(255, 0, 0), (0, 255, 0), (0, 0, 255)} <= colors)

    def test_four_panel_reuse_freezes_all_bindings(self):
        page = self.page(rows=2, columns=2)
        bundle = self.service.save_document(
            BundlePreparer(self.service, "raster").build_many([p.ref() for p in self.prepared], self.context),
            'prepared-data-bundle')
        compiler = RasterSceneCompiler(self.service, bundles=BundlePreparer, pages=PageRenderer,
                                      environment=environment_snapshot)
        scene = compiler.compile(bundle_ref=bundle.ref(), page_request=page, context=self.context,
                                 scene_id='synthetic-grid')
        inputs = compiler.validate_scene(scene, self.context)
        self.assertEqual(4, len(inputs['layers']))
        self.assertEqual(2, len(inputs['bundle']['role_bindings']))
        output = self.service.document(self.renderer.render(page, self.context).ref(), 'page-output')
        self.assertEqual(4, len(output['body_refs']))
        self.assertEqual(4, len({item['frame_id'] for item in output['body_refs']}))
        self.assertEqual(4, len(page['bindings']['panels']))
        self.assertEqual(1, len(page['bindings']['sharing']['encoding_groups']))

    def test_class_definition_and_policy_conflicts_fail_shared_but_not_independent(self):
        for mutation in ('color', 'policy'):
            with self.subTest(mutation=mutation):
                if mutation == 'color':
                    self.legend_path.write_text('value,label,color\n1,Class A,#FF0000\n2,Class B,#00FF00\n3,Class C,#FFFF00\n', encoding='utf-8')
                    self.sync_inputs()
                else:
                    self.request['legend_policy'] = 'all'
                self.portrayals[1] = compile_portrayal(self.service, self.analyze(), self.context).ref()
                with self.assertRaisesRegex(ProtocolError, 'SHARED_LEGEND_(DEFINITION|POLICY)_MISMATCH'):
                    self.page()
                independent = self.page(mode='independent')
                self.assertEqual(2, len(independent['legends']))

    def test_mixed_crs_is_rejected_without_reprojection(self):
        self.request['source']['crs'] = {'authority': 'EPSG', 'code': '26912'}
        with self.rio.open(self.source_path, 'r+') as dataset:
            dataset.crs = 'EPSG:26912'
        self.evidence['raster_info']['crs'] = 'EPSG:26912'
        self.sync_inputs()
        other = self.analyze()
        with self.assertRaisesRegex(ProtocolError, 'BUNDLE_PROFILE_MISMATCH'):
            BundlePreparer(self.service, "raster").build_many([self.prepared[0].ref(), other.ref()], self.context)

    def test_long_shared_legend_labels_fail_actual_measurement(self):
        for index in range(2):
            report, evidence = self.service.load_verified(self.prepared[index].ref())
            self.request = deepcopy(report['request'])
            self.evidence = deepcopy(evidence)
            self.source_path = self.root / self.request['source']['path']
            self.legend_path = self.root / self.request['legend']['path']
            label = 'Long category label ' * 12
            self.legend_path.write_text(
                f'value,label,color\n1,Class A,#FF0000\n2,Class B,#00FF00\n3,{label},#0000FF\n', encoding='utf-8')
            self.sync_inputs()
            self.prepared[index] = self.analyze()
            self.portrayals[index] = compile_portrayal(self.service, self.prepared[index], self.context).ref()
        page = self.page()
        self.assertEqual(3, len(page['legends'][0]['items']))
        with self.assertRaisesRegex(CartoError, 'RASTER_PAGE_CONTENT_OVERFLOW'):
            self.renderer.render(page, self.context)

    def test_per_panel_bindings_and_shared_legend_tampering_fail(self):
        page = self.page()
        cases = []
        bad = deepcopy(page); bad['portrayals'].pop(); cases.append(bad)
        bad = deepcopy(page); bad['bindings']['panels'].pop(); cases.append(bad)
        bad = deepcopy(page); bad['portrayals'][1]['ref'] = deepcopy(bad['portrayals'][0]['ref']); cases.append(bad)
        bad = deepcopy(page); bad['legends'][0]['items'][2]['color'] = '#123456'; cases.append(bad)
        for index, bad in enumerate(cases):
            with self.subTest(index=index), self.assertRaises(CartoError):
                validate_page_request(self.service, bad, self.context, BundlePreparer)

    def test_output_body_omission_swap_and_second_panel_artifact_tamper_fail(self):
        output_ref = self.renderer.render(self.page(), self.context).ref()
        original = self.service.document(output_ref, 'page-output')
        for mutation in ('omit', 'swap'):
            bad = deepcopy(original)
            if mutation == 'omit':
                bad['body_refs'].pop()
            else:
                bad['body_refs'][0]['ref'], bad['body_refs'][1]['ref'] = bad['body_refs'][1]['ref'], bad['body_refs'][0]['ref']
            bad_ref = self.service.save_document(bad, 'page-output').ref()
            with self.subTest(mutation=mutation), self.assertRaisesRegex(CartoError, 'RASTER_PAGE_CHANGED'):
                self.renderer.load_verified(bad_ref, self.context)
        body = self.service.document(original['body_refs'][1]['ref'], 'raster-map-body')
        path = Path(body['image']['artifact_ref']['uri'])
        path.write_bytes(path.read_bytes() + b'tampered')
        with self.assertRaises(CartoError):
            self.renderer.load_verified(output_ref, self.context)

    def test_overflow_rejects_instead_of_shrinking_font(self):
        page = self.page(rows=2, columns=2, mode='independent')
        next(item for item in page['texts'] if item['content_id'] == 'caption-r0-c0')['text'] = 'synthetic long caption ' * 10
        with self.assertRaisesRegex(CartoError, 'RASTER_PAGE_CONTENT_OVERFLOW'):
            self.renderer.render(page, self.context)


if __name__ == '__main__':
    unittest.main()
