"""S1-A/B uses synthetic inputs only; no scenario admission or approval bypass."""
from __future__ import annotations
from copy import deepcopy
from pathlib import Path
import sys
import unittest

SCRIPTS = Path(__file__).resolve().parents[1]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
from carto_core.artifacts import artifact_ref
from carto_core.compiler.appearance import resolve_appearance, require_appearance
from carto_core.compiler.page_bindings import build_single_bindings, category_counts, validate_bindings
from carto_core.compiler.raster_page_contract import compile_page_request
from carto_core.errors import CartoError, ProtocolError
from carto_core.schema_registry import SchemaRegistry
from tests.fixtures.schema_cases import VALID_CASES
from tests.test_raster_classification import PreparationFixture
from tests.helpers import page_request, rebind_page, release_test_font_handles, set_raster


class BindingContractTests(unittest.TestCase):
    def setUp(self):
        self.registry = SchemaRegistry()
        self.binding = deepcopy(VALID_CASES['page-bindings'])

    def test_single_binding_is_executable(self):
        self.assertEqual(self.binding, validate_bindings(self.binding, self.registry, executable=True))

    def test_duplicate_identity_is_not_resolved_by_position(self):
        self.binding['layers'].append(deepcopy(self.binding['layers'][0]))
        with self.assertRaisesRegex(ProtocolError, 'PAGE_BINDING_DUPLICATE'):
            validate_bindings(self.binding, self.registry)

    def test_dangling_data_and_view_references_fail(self):
        for section, key in [('layers', 'data_binding_id'), ('panels', 'view_id')]:
            value = deepcopy(self.binding)
            value[section][0][key] = 'missing-reference'
            with self.subTest(section=section), self.assertRaisesRegex(ProtocolError, 'PAGE_BINDING_REFERENCE'):
                validate_bindings(value, self.registry)

    def test_structural_multi_panel_is_not_executable(self):
        panel = deepcopy(self.binding['panels'][0])
        panel.update(id='second-panel', frame_id='second-frame')
        self.binding['panels'].append(panel)
        validate_bindings(self.binding, self.registry)
        with self.assertRaisesRegex(ProtocolError, 'PAGE_BINDING_UNSUPPORTED'):
            validate_bindings(self.binding, self.registry, executable=True)

    def test_unknown_fields_and_sharing_targets_fail(self):
        value = deepcopy(self.binding)
        value['silent_fallback'] = True
        with self.assertRaises(ProtocolError):
            validate_bindings(value, self.registry)
        self.binding['sharing']['encoding_groups'] = [{'id':'shared', 'members':['missing-one','missing-two']}]
        with self.assertRaisesRegex(ProtocolError, 'PAGE_BINDING_REFERENCE'):
            validate_bindings(self.binding, self.registry)

    def test_legend_cannot_invent_a_layer(self):
        self.binding['legends'][0]['layer_ids'] = ['missing-layer']
        with self.assertRaises(ProtocolError):
            validate_bindings(self.binding, self.registry)

    def test_category_counts_are_not_legend_capacity(self):
        rows = [
            {'count':10,'semantic':'class','display':'color','include_in_legend':True},
            {'count':0,'semantic':'class','display':'color','include_in_legend':True},
            {'count':4,'semantic':'background','display':'hidden','include_in_legend':False},
            {'count':1,'semantic':'class','display':'hidden','include_in_legend':False},
        ]
        counts = category_counts({'rows':rows})
        self.assertEqual({'observed_value_count':3,'defined_class_count':3,
                          'observed_class_count':2,'displayed_class_count':1,'legend_item_count':2}, counts)
        self.registry.validate('category-counts', counts)
        self.assertNotIn('legend_capacity', counts)

    def test_new_contract_versions_reject_old_documents(self):
        for name in ('cartography', 'map-plan', 'page-request'):
            value = deepcopy(VALID_CASES[name])
            self.assertEqual({'cartography':2,'map-plan':3,'page-request':4}[name], value['schema_version'])
            value['schema_version'] = 1
            with self.subTest(name=name), self.assertRaises(ProtocolError):
                self.registry.validate(name, value)
        for name in ('general-generate-request', 'general-template-create-request'):
            value = deepcopy(VALID_CASES[name])
            if name.endswith('generate-request'):
                value['template']['version'] = '1.0.0'
            else:
                value['version'] = '1.0.0'
            with self.subTest(name=name), self.assertRaises(ProtocolError):
                self.registry.validate(name, value)

    def test_style_and_layout_have_separate_sources(self):
        page = deepcopy(VALID_CASES['page-request'])
        style = page['appearance']['cartography']
        layout = page['resolved_layout']['contract']
        style['typography']['title_pt'] = 22
        layout['content_padding_mm'] = 3
        result = resolve_appearance(style, layout, page['portrayals'], self.registry)
        self.assertEqual(22, result['typography']['title_pt'])
        self.assertEqual(3, result['typography']['padding_mm'])
        self.assertNotIn('padding_mm', style['typography'])
        self.assertEqual(artifact_ref('cartography', style), result['style_ref'])
        self.assertEqual('2.0.0', result['style_ref']['version'])
        require_appearance(result, layout, page['portrayals'], self.registry)
        result['typography']['title_pt'] = 21
        with self.assertRaisesRegex(ProtocolError, 'APPEARANCE_BINDING_MISMATCH'):
            require_appearance(result, layout, page['portrayals'], self.registry)


class SinglePageNormalizationTests(PreparationFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        try:
            from carto_core.adapters.raster_renderer import _dependencies
            self.np, self.rio, self.mpl, _, _, _, self.Image = _dependencies()
            import fontTools
        except (CartoError, ImportError) as exc:
            self.skipTest(str(exc))
        self.addCleanup(release_test_font_handles)
        set_raster(self, self.np.array([[1,0,255],[255,1,0]], dtype='uint8'))
        self.prepared = self.ready()
        self.page = page_request(self.service, self.prepared, self.context, dpi=72)
        from carto_core.adapters.page_renderer import PageRenderer
        self.renderer = PageRenderer(self.service)

    def test_single_page_has_explicit_data_and_element_bindings(self):
        self.renderer._validate(self.page, self.context)
        self.assertNotIn('typography', self.page)
        binding = self.page['bindings']
        self.assertEqual(self.prepared.ref(), binding['data_bindings'][0]['prepared_ref'])
        self.assertEqual({'title','source'}, {element['id'] for element in binding['elements']})
        self.assertEqual(binding['views'][0]['id'], binding['panels'][0]['view_id'])

    def test_frame_order_does_not_select_identity(self):
        updated = deepcopy(self.page)
        layout = updated['resolved_layout']['contract']
        layout['frames'].reverse()
        from carto_core.compiler.layout import LayoutResolver
        updated['resolved_layout'] = LayoutResolver(self.service.registry).resolve(layout,72)
        result = rebind_page(self.service, updated, self.context)
        self.assertEqual(self.page['bindings'], result['bindings'])
        self.renderer._validate(result, self.context)

    def test_resolved_style_and_binding_tampering_fail(self):
        for change in ('font-size','source-style','data','view'):
            value = deepcopy(self.page)
            if change == 'font-size': value['appearance']['typography']['title_pt'] += 1
            elif change == 'source-style': value['appearance']['cartography']['typography']['title_pt'] += 1
            elif change == 'data': value['bindings']['data_bindings'][0]['prepared_ref']['digest'] = 'sha256:'+'b'*64
            else: value['bindings']['panels'][0]['view_id'] = 'different-view'
            with self.subTest(change=change), self.assertRaises(ProtocolError):
                self.renderer._validate(value,self.context)

    def test_legacy_reference_is_not_migrated(self):
        ref = self.renderer.freeze_request(self.page,self.context).ref()
        self.assertEqual('3.0.0', ref['version'])
        ref['version'] = '1.0.0'
        with self.assertRaisesRegex(ProtocolError, 'RASTER_REFERENCE_INVALID'):
            self.service._json_ref(ref,'page-request')

    def test_template_typography_changes_actual_measurement(self):
        first = self.renderer.render(self.page,self.context)
        one = self.service._json_ref(first.ref(),'page-output')
        updated = deepcopy(self.page)
        updated['appearance']['cartography']['typography']['title_pt'] = 14
        updated = rebind_page(self.service,updated,self.context)
        second = self.renderer.render(updated,self.context)
        two = self.service._json_ref(second.ref(),'page-output')
        height = lambda output: next(item['bounds_px'][3] for item in output['measurements'] if item['element_id']=='title')
        self.assertLess(height(two), height(one))
        self.assertEqual(self.page['portrayals'][0]['ref'], updated['portrayals'][0]['ref'])

    def test_unresolved_v1_input_requires_explicit_new_contract(self):
        raw = {k: deepcopy(v) for k, v in self.page.items() if k not in {"appearance", "bindings"}}
        raw["schema_version"] = 1
        with self.assertRaisesRegex(ProtocolError, "PAGE_CONTRACT_VERSION"):
            compile_page_request(self.service, raw, self.page["appearance"]["cartography"], self.context)

    def test_compiler_is_not_an_implicit_legacy_upgrade(self):
        with self.assertRaisesRegex(ProtocolError, 'PAGE_DESIGN_ALREADY_RESOLVED'):
            compile_page_request(self.service,self.page,self.page['appearance']['cartography'],self.context)


if __name__ == '__main__':
    unittest.main()
