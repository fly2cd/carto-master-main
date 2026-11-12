"""Shared-legend rules use synthetic definitions, never business records."""
from __future__ import annotations
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import sys
import unittest

SCRIPTS = Path(__file__).resolve().parents[1]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
from carto_core.compiler.raster_legends import _merge_verified_reports, resolve_shared_legend
from carto_core.errors import CartoError, ProtocolError
from tests.test_raster_classification import PreparationFixture
from tests.helpers import compile_portrayal


def report(observed, policy='observed'):
    rows = []
    for order, (value, label, color) in enumerate([(1,'Category A','#112233'),
                                                  (2,'Category B','#445566'),
                                                  (3,'Category C','#778899')]):
        rows.append({'value':value,'semantic':'class','display':'color','label':label,
                     'color':color,'order':order,'count':5 if value in observed else 0,
                     'include_in_legend': policy == 'all' or value in observed})
    return {'status':'ready','questions':[], 'request':{'legend_policy':policy}, 'rows':rows}


class SharedLegendRulesTests(unittest.TestCase):
    def test_observed_union_is_ordered_and_deduplicated(self):
        result = _merge_verified_reports([report({1,2}),report({1,3})])
        self.assertEqual([1,2,3], [row['value'] for row in result])
        self.assertEqual([0,1,2], [row['order'] for row in result])

    def test_all_includes_common_unobserved_definitions(self):
        result = _merge_verified_reports([report({1},'all'),report({2},'all')])
        self.assertEqual([1,2,3], [row['value'] for row in result])

    def test_observed_does_not_add_unrequested_unobserved_category(self):
        result = _merge_verified_reports([report({1}),report({2})])
        self.assertEqual([1,2], [row['value'] for row in result])

    def test_counts_may_differ_without_changing_definition(self):
        first, second = report({1}), report({1})
        second['rows'][0]['count'] = 100
        self.assertEqual(_merge_verified_reports([first]), _merge_verified_reports([first,second]))

    def test_input_and_output_order_do_not_choose_color(self):
        first, second = report({1,2}), report({2,3})
        expected = _merge_verified_reports([first,second])
        second['rows'].reverse()
        self.assertEqual(expected, _merge_verified_reports([second,first]))

    def test_full_definition_must_match_even_for_unobserved_values(self):
        first, second = report({1}), report({1})
        second['rows'][2]['color'] = '#AABBCC'
        with self.assertRaisesRegex(ProtocolError, 'SHARED_LEGEND_DEFINITION_MISMATCH'):
            _merge_verified_reports([first,second])

    def test_definition_fields_are_not_automatically_reconciled(self):
        for key, value in [('value',4),('semantic','background'),('display','hidden'),
                           ('label','Other category'),('color','#FFFFFF'),('order',5)]:
            second = report({1,3})
            second['rows'][0][key] = value
            with self.subTest(key=key), self.assertRaisesRegex(ProtocolError, 'SHARED_LEGEND_DEFINITION_MISMATCH'):
                _merge_verified_reports([report({1,2}),second])

    def test_disjoint_partial_tables_are_not_assumed_compatible(self):
        first, second = report({1}), report({2})
        first['rows'] = first['rows'][:1]
        second['rows'] = second['rows'][1:2]
        with self.assertRaisesRegex(ProtocolError, 'SHARED_LEGEND_DEFINITION_MISMATCH'):
            _merge_verified_reports([first,second])

    def test_legend_policy_mismatch_is_not_a_fallback(self):
        with self.assertRaisesRegex(ProtocolError, 'SHARED_LEGEND_POLICY_MISMATCH'):
            _merge_verified_reports([report({1}),report({2},'all')])

    def test_all_inclusion_decisions_must_match(self):
        first, second = report({1},'all'), report({2},'all')
        second['rows'][2]['include_in_legend'] = False
        with self.assertRaisesRegex(ProtocolError, 'SHARED_LEGEND_INCLUSION_MISMATCH'):
            _merge_verified_reports([first,second])

    def test_hidden_categories_stay_hidden(self):
        first, second = report({1,2}), report({1,2})
        for value in (first,second):
            value['rows'][1].update(display='hidden',color=None,include_in_legend=False)
        self.assertEqual([1], [row['value'] for row in _merge_verified_reports([first,second])])

    def test_pending_empty_and_duplicate_inputs_fail(self):
        pending = report({1});pending['status'] = 'needs-clarification';pending['questions'] = [{}]
        with self.assertRaisesRegex(ProtocolError, 'CLARIFICATION_REQUIRED'):
            _merge_verified_reports([report({1}),pending])
        with self.assertRaisesRegex(ProtocolError, 'SHARED_LEGEND_EMPTY'):
            _merge_verified_reports([report(set()),report(set())])
        for duplicate_order in (False,True):
            value = report({1})
            if duplicate_order: value['rows'][1]['order'] = 0
            else: value['rows'].append(deepcopy(value['rows'][0]))
            with self.assertRaisesRegex(ProtocolError, 'SHARED_LEGEND_DEFINITION_INVALID'):
                _merge_verified_reports([value])

    def test_source_definitions_are_not_mutated(self):
        reports = [report({1,2}),report({2,3})]
        before = deepcopy(reports)
        result = _merge_verified_reports(reports)
        result[0]['label'] = 'Changed output only'
        self.assertEqual(before,reports)

    def test_count_bound_is_explicit(self):
        for reports in ([],[report({1})]*5):
            with self.assertRaisesRegex(ProtocolError, 'SHARED_LEGEND_INPUT_COUNT'):
                _merge_verified_reports(reports)


class SharedLegendEvidenceTests(PreparationFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.prepared = self.ready()
        self.portrayal = compile_portrayal(self.service,self.prepared,self.context).ref()

    def test_same_verified_source_can_be_reused_by_panels(self):
        one = resolve_shared_legend(self.service,[self.portrayal],self.context)
        self.assertEqual(one,resolve_shared_legend(self.service,[self.portrayal]*4,self.context))

    def test_forged_digest_and_wrong_context_are_rejected(self):
        bad = dict(self.portrayal,digest='sha256:'+'b'*64)
        with self.assertRaises(CartoError):
            resolve_shared_legend(self.service,[self.portrayal,bad],self.context)
        with self.assertRaises(CartoError):
            resolve_shared_legend(self.service,[self.portrayal],replace(self.context,subject_id='different-subject'))


if __name__ == '__main__':
    unittest.main()
