"""A3.1: explicit thematic decisions, exact attribute joins and real rendered evidence.

All geometries and numbers are synthetic, generated inside temporary project roots.
"""
from copy import deepcopy
from dataclasses import asdict, replace
from pathlib import Path
import json
import sys
SCRIPTS_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPTS_ROOT) not in sys.path: sys.path.insert(0, str(SCRIPTS_ROOT))
import tempfile
import unittest
from unittest.mock import patch

from carto_core.artifacts import atomic_yaml, file_digest, artifact_ref, utc_now
from carto_core.canonical import sha256_digest
from carto_core.errors import ProtocolError, SecurityError
from carto_core.schema_registry import SchemaRegistry
from carto_core.security.paths import PathGuard
from carto_core.contracts.execution import ExecutionContext
from carto_core.workflow.vector_preparation import VectorPreparationService
from carto_core.compiler.thematic_design import resolve_design
from carto_core.compiler.portrayal_resolver import metric_value
from carto_core.workflow.preparation_bundle import BundlePreparer
from carto_core.compiler.vector_portrayal import resolve_features
from carto_core.compiler.portrayal_resolver import radius
from carto_core.scenarios.general_thematic.dispatch import geometry_of_request, geometry_of_profile


def symbol(color):
    return {'color':color,'stroke':'#000000','stroke_width_pt':0.2,'radius_mm':1.0}


def density_design():
    return {'schema_version':1,'geometry':'polygon','kind':'choropleth','measurement':'density',
            'field':'population','unit':'people/km2',
            'normalization':{'denominator_field':'area','scale':1},
            'missing':{'policy':'reject','label':'No data','symbol':symbol('#888888')},
            'classification':{'method':'equal-interval','class_count':2},
            'symbols':[symbol('#2288CC'),symbol('#CC3322')]}


def count_design():
    return {'schema_version':1,'geometry':'point','kind':'proportional','measurement':'count',
            'field':'population','unit':'people','normalization':None,
            'missing':{'policy':'reject','label':'No data','symbol':symbol('#888888')},
            'maximum_value':100,'maximum_radius_mm':5,'minimum_radius_mm':0,
            'zero_policy':'omit','negative_policy':'reject','out_of_range':'reject',
            'legend_values':[25,100],'symbol':symbol('#2288CC')}


class ThematicDataTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='carto-a31-synthetic-')
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.registry=SchemaRegistry()
        self.context=ExecutionContext('a31-run','a31-tenant','a31-project','a31-operator',
                    frozenset({'operator'}),frozenset({'a31-project'}),frozenset({'read','join','classify','render-preview'}))
        self.service=VectorPreparationService(project_root=self.root,allowed_roots=[str(self.root)],registry=self.registry)
        self.table=self.root/'attributes.csv'
        self.table.write_text('code,pop,area\nA,10,2\nB,20,2\nC,40,4\n',encoding='utf8')
        self.source=self.make_source()

    def make_source(self, geometry='polygon'):
        features=[]
        for i,key in enumerate('ABC'):
            coords=[float(i),0.0] if geometry=='point' else [[[i,0],[i+.8,0],[i+.8,.8],[i,.8],[i,0]]]
            features.append({'type':'Feature','geometry':{'type':'Point' if geometry=='point' else 'Polygon','coordinates':coords},'properties':{'code':key}})
        p=self.root/(geometry+'.geojson');p.write_text(json.dumps({'type':'FeatureCollection','features':features}),encoding='utf8')
        return {'schema_version':1,'source_id':'regions','role':'thematic-features','format':'geojson','crs':'EPSG:4326','encoding':'utf-8',
                'files':[{'extension':'.geojson','path':str(p),'digest':file_digest(p),'size_bytes':p.stat().st_size}],
                'data_nature':'user-provided','contains_sensitive_coordinates':False,'contains_production_data':False,'license':'project-approved',
                'attribute_join':{'source_id':'indicators','path':str(self.table),'digest':file_digest(self.table),'size_bytes':self.table.stat().st_size,
                                  'geometry_key':'code','table_key':'code','fields':[{'column':'pop','field':'population','value_type':'number'},
                                   {'column':'area','field':'area','value_type':'number'}],'coverage':'exact','missing_policy':'reject'}}

    def prepared(self, source=None):
        artifact=self.service.prepare(source or self.source,self.context)
        return artifact, self.service.load_verified(artifact.ref(),self.context)

    def test_csv_values_enter_geometry_and_facts_digest(self):
        ref,report=self.prepared()
        self.assertEqual([10,20,40],[f['properties']['population'] for f in report['features']])
        self.assertEqual([0,1,2],[m['row_index'] for m in report['attribute_evidence']['matches']])
        old=BundlePreparer._vector_facts_digest(report)
        self.table.write_text('code,pop,area\nA,10,2\nB,35,2\nC,40,4\n',encoding='utf8')
        source=self.make_source();new,new_report=self.prepared(source)
        self.assertNotEqual(old,BundlePreparer._vector_facts_digest(new_report))
        # Frozen evidence stays reproducible even after the original file changes.
        self.assertEqual(report,self.service.load_verified(ref.ref(),self.context))

    def test_density_normalization_and_equal_intervals(self):
        _,report=self.prepared();encoding,stats=resolve_design(density_design(),report,self.registry)
        self.assertEqual([5,7.5,10],encoding['scale']['edges'])
        self.assertEqual({'count':3,'minimum':5,'maximum':10},stats)
        styles=resolve_features(report,encoding,self.registry)
        self.assertEqual(3,styles['counts']['visible_count'])
        self.assertEqual('graduated-color',__import__('carto_core.compiler.portrayal_resolver',fromlist=['expression_reference']).expression_reference('choropleth')['id'])

    def test_same_data_different_metric_changes_execution_values(self):
        _,report=self.prepared();d=density_design();normalized,_=resolve_design(d,report,self.registry)
        d['normalization']=None;d['measurement']='normalized-index';d['unit']='index'
        raw,_=resolve_design(d,report,self.registry)
        self.assertEqual([10,25,40],raw['scale']['edges']);self.assertNotEqual(raw,normalized)

    def test_proportional_area_scaling(self):
        _,report=self.prepared(self.make_source('point'));e,_=resolve_design(count_design(),report,self.registry)
        self.assertAlmostEqual(radius(e,25)**2/radius(e,100)**2,.25)
        self.assertEqual(3,resolve_features(report,e)['counts']['visible_count'])

    def test_raw_count_cannot_be_mislabeled_as_choropleth_design(self):
        d=density_design();d['measurement']='count'
        with self.assertRaises(ProtocolError):self.registry.validate('thematic-design',d)

    def test_unknown_nested_parameter_rejected(self):
        d=density_design();d['classification']['hidden_expression']='eval(1)'
        with self.assertRaises(ProtocolError):self.registry.validate('thematic-design',d)

    def test_join_requires_authorized_capability(self):
        with self.assertRaisesRegex(SecurityError,'CAPABILITY_NOT_AUTHORIZED'):
            self.service.prepare(self.source,replace(self.context,authorized_capabilities=frozenset({'read'})))

    def test_join_rejects_duplicates_unmatched_missing_nonfinite(self):
        for rows in ('A,1,2\nA,2,2\nC,4,4\n','A,1,2\nB,2,2\n','A,1,2\nB,2,2\nC,4,4\nD,1,1\n',
                     'A,nan,2\nB,2,2\nC,4,4\n','A,,2\nB,2,2\nC,4,4\n'):
            with self.subTest(rows_count=len(rows.splitlines())):
                self.table.write_text('code,pop,area\n'+rows,encoding='utf8')
                with self.assertRaises(ProtocolError):self.prepared(self.make_source())

    def test_zero_denominator_rejected_not_imputed(self):
        _,report=self.prepared();report['features'][0]['properties']['area']=0
        with self.assertRaisesRegex(ProtocolError,'THEMATIC_DENOMINATOR_INVALID'):resolve_design(density_design(),report)

    def test_table_drift_and_frozen_snapshot_tampering_rejected(self):
        artifact,report=self.prepared();self.table.write_text('changed',encoding='utf8')
        with self.assertRaisesRegex(ProtocolError,'THEMATIC_TABLE_DRIFT'):self.service.prepare(self.source,self.context)
        snapshot=Path(report['attribute_evidence']['asset']['artifact_ref']['uri']);snapshot.write_text('changed',encoding='utf8')
        with self.assertRaises(ProtocolError):self.service.load_verified(artifact.ref(),self.context)

    def test_geometry_not_inferred_from_version(self):
        with self.assertRaisesRegex(ProtocolError,'SCENARIO_GEOMETRY_REQUIRED'):geometry_of_request({'version':'4.0.0'})
        self.assertEqual('raster',geometry_of_profile({'template_geometry':'raster','template':{'version':'99.1.0'}}))

    def test_explicit_intervals_change_styles_when_table_values_change(self):
        _,report=self.prepared();d=density_design();d['normalization']=None;d['measurement']='normalized-index';d['unit']='index'
        d['classification']={'method':'manual','edges':[0,25,50],'labels':['Low','High']}
        e,_=resolve_design(d,report);before=resolve_features(report,e)['feature_styles']
        self.table.write_text('code,pop,area\nA,10,2\nB,35,2\nC,40,4\n',encoding='utf8')
        _,after_report=self.prepared(self.make_source());e2,_=resolve_design(d,after_report);after=resolve_features(after_report,e2)['feature_styles']
        self.assertNotEqual(before[1],after[1]);self.assertEqual(before[0],after[0])




class TemplateContractMergeTests(unittest.TestCase):
    """ADR-001 §9.5 项②: one contract source, two standalone geometry authors.

    Authoring only writes and validates package documents, so these cases pin the
    merged contract layer and its admission gates without GIS, renderer or approval
    seams. All data stays synthetic and inside a temporary root.
    """

    def setUp(self):
        from tests.fixtures.schema_cases import VALID_CASES, VARIANT_CASES
        self.temp=tempfile.TemporaryDirectory(prefix='carto-a31-contract-')
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.registry=SchemaRegistry()
        self.guard=PathGuard([self.root])
        self.work=self.root/'template-work';self.work.mkdir()
        self.request=deepcopy(VARIANT_CASES['general-template-create-request.vector'])
        self.brief={k:self.request[k] for k in ('kind','namespace','template_id','version')}
        self.raster_request=deepcopy(VALID_CASES['general-template-create-request'])
        self.generic_request=deepcopy(VALID_CASES['template-create-request'])

    def author(self):
        from carto_core.scenarios.general_thematic.vector import GeneralVectorAuthor
        return GeneralVectorAuthor(self.guard,self.work,self.registry)

    def test_vector_author_is_standalone_and_idempotent(self):
        from carto_core.scenarios.general_thematic.vector import GeneralVectorAuthor
        from carto_core.scenarios.general_thematic.raster import GeneralThematicAuthor
        # 项②(4): no inheritance in either direction; the shared source is the
        # geometry-free module-level contract functions, not a base class.
        self.assertEqual((object,),GeneralVectorAuthor.__bases__)
        self.assertFalse(issubclass(GeneralVectorAuthor,GeneralThematicAuthor))
        self.assertFalse(issubclass(GeneralThematicAuthor,GeneralVectorAuthor))
        author=self.author()
        package=author.author(self.request,self.brief)
        self.assertEqual(package,self.author().verify_existing(self.request,self.brief))

    def test_vector_template_declares_only_geometry_adaptation_differences(self):
        from carto_core.schema_registry import load_document
        from carto_core.scenarios.general_thematic.raster import scenario_contract, spatial_behavior_contract
        package=self.author().author(self.request,self.brief)
        root=Path(package['package_path'])
        scenario=load_document(root/'contracts/scenario.yaml')
        self.assertEqual('4.0.0',scenario['version'])
        self.assertEqual(['thematic-features'],scenario['data_role_refs'])
        for name in ('style','layout'):
            self.assertEqual('4.0.0',scenario['embedded'][name]['version'],name)
        # The embedded segments name the template version actually being authored;
        # before 项② the vector package carried a stale "@3.0.0" reference because the
        # inherited raster declaration was patched after the fact. (The identity
        # provenance assertion was removed with the map-brand segment, 2026-11-18;
        # version binding is covered by the per-segment loop above.)
        gates=load_document(root/'contracts/quality-gates.yaml')
        self.assertEqual(['protocol.schema-valid','cartography.legend-consistency'],
                         [check['id'] for check in gates['checks']])
        self.assertEqual('4.0.0',gates['baseline']['version'])
        self.assertEqual(sha256_digest({'namespace':'local','kind':'map-scenario',
                                        'id':'general-thematic-map','version':'4.0.0'}),
                         gates['baseline']['digest'])
        delivery=load_document(root/'contracts/delivery.yaml')
        self.assertEqual(('vector-map','whole-map'),
                         (delivery['targets'][0]['composition'],delivery['targets'][0]['vector_claim']))
        self.assertEqual(('flattened-raster','none'),
                         (delivery['targets'][1]['composition'],delivery['targets'][1]['vector_claim']))
        data_schema=load_document(root/'contracts/data.schema.yaml')
        self.assertEqual(['point','polygon'],data_schema['roles'][0]['geometry_types'])
        self.assertEqual([],data_schema['roles'][0]['fields'])
        portrayal=load_document(root/'contracts/portrayal.yaml')
        self.assertEqual(('vector-layer','vector'),(portrayal['layers'][0]['id'],portrayal['layers'][0]['geometry']))
        # Scale-band identity names the geometry it belongs to; the raster default stays
        # byte-identical so the @3.0.0 asset is not silently redefined.
        spatial=load_document(root/'contracts/spatial-behavior.yaml')
        self.assertEqual('native-vector',spatial['scale_bands'][0]['id'])
        self.assertEqual('native-raster',
                         spatial_behavior_contract(self.raster_request)['scale_bands'][0]['id'])
        # Single source proof: the two scenario declarations are byte-identical once
        # the geometry-adaptation parameters (version, data role) are normalized.
        raster_scenario=scenario_contract(self.raster_request)
        normalized=deepcopy(scenario_contract(self.raster_request,version='4.0.0',data_role='thematic-features'))
        normalized['version']='3.0.0'
        normalized['data_role_refs']=['classified-surface']
        for component in normalized['embedded'].values():component['version']='3.0.0'
        self.assertEqual(raster_scenario,normalized)

    def test_author_constants_match_the_registered_capability_profiles(self):
        # The shared gate pins version/profile from module constants; the versioned
        # capability policy stays the authority, so the two may never drift apart.
        from carto_core.scenario_registry import ScenarioRegistry
        from carto_core.scenarios.general_thematic import raster as general_thematic, vector as general_vector
        scenarios=ScenarioRegistry(self.registry)
        for module in (general_thematic,general_vector):
            profile=scenarios.for_template({'kind':'map-scenario','id':'general-thematic-map',
                                            'version':module.VERSION})
            with self.subTest(module=module.__name__):
                self.assertEqual(module.AUTHORING_PROFILE,profile.definition['authoring_profile'])
                self.assertEqual(module.VERSION,profile.definition['template']['version'])

    def test_vector_author_enforces_the_same_four_gates_as_raster(self):
        author=self.author()
        with self.assertRaisesRegex(ProtocolError,'CAPABILITY_NOT_AVAILABLE'):
            author.author(self.generic_request,self.brief)
        # Gates run before schema validation, so both geometries report the same code
        # for the same defect instead of a schema error on one side only.
        for mutation,code in [({'version':'3.0.0'},'CAPABILITY_NOT_AVAILABLE'),
                              ({'profile':'general-thematic-authoring'},'CAPABILITY_NOT_AVAILABLE'),
                              ({'targets':['svg','pdf','png']},'RENDER_TARGET_UNSUPPORTED'),
                              ({'display_crs':{'authority':'EPSG','code':'3857'}},'SOURCE_CRS_UNSUPPORTED')]:
            request=deepcopy(self.request);request.update(mutation)
            brief={k:request[k] for k in ('kind','namespace','template_id','version')}
            with self.subTest(mutation=mutation):
                with self.assertRaisesRegex(ProtocolError,code):
                    author.author(request,brief)
        with self.assertRaisesRegex(ProtocolError,'TEMPLATE_BRIEF_MISMATCH'):
            author.author(self.request,dict(self.brief,version='3.0.0'))


class ThematicWorkflowTests(unittest.TestCase):
    """Real vector preparation, compilation, preview, lock and local delivery.

    Only published-template repository discovery/installation is substituted by
    exact authored package metadata; no GIS/renderer/approval/check seams.
    """
    make_source = ThematicDataTests.make_source

    def setUp(self):
        from tests.test_general_thematic import (find_cjk_font, SCENE_TEXT, GOAL,
            build_installation, GenerationTests)
        from tests.fixtures.schema_cases import VALID_CASES, VARIANT_CASES
        from carto_core.scenarios.general_thematic.vector import GeneralVectorAuthor
        from carto_core.scenario_registry import ScenarioRegistry
        from carto_core.compiler.map_candidate import MapCandidateCompiler
        from carto_core.schema_registry import load_document
        from tests.helpers import release_test_font_handles
        ThematicDataTests.setUp(self)
        self.context=replace(self.context,tenant_id='test-tenant')
        font=find_cjk_font(SCENE_TEXT)
        if font is None:self.skipTest('An embeddable CJK TTF is required for real rendering')
        self.addCleanup(release_test_font_handles)
        (self.root/'fonts').mkdir()
        self.font_path=self.root/'fonts/selected-cjk.ttf'
        self.font_path.write_bytes(font.read_bytes())
        self.guard=PathGuard([self.root]);self.work=self.root/'work';self.work.mkdir()
        create=deepcopy(VALID_CASES['general-template-create-request'])
        create.update(geometry='vector',version='4.0.0',profile='general-vector-authoring',role_bindings={'thematic_features':'legend-sample'})
        brief={k:create[k] for k in ('kind','namespace','template_id','version')}
        template_work=self.root/'template-work';template_work.mkdir()
        package=GeneralVectorAuthor(self.guard,template_work,self.registry).author(create,brief)
        self.installation=build_installation(Path(package['package_path']),package)
        self.contracts=MapCandidateCompiler(self.guard,self.registry).load_contracts(self.installation)
        self.generate=deepcopy(VARIANT_CASES['general-generate-request.vector'])
        self.source['data_nature']='user-provided'
        self.generate.update(run_id=self.context.run_id,project_id=self.context.project_id,
            goal=GOAL,map_title='Population density',scope='project:'+self.context.project_id,
            subject={'tenant_id':self.context.tenant_id,'subject_id':self.context.subject_id,
                     'approver_subject_id':'synthetic-reviewer','namespace':self.context.project_id},
            vector_sources=[self.source],
            sources=[{'id':self.source['source_id'],'version':'1.0.0','digest':sha256_digest(self.source)}],
            allowed_capabilities=sorted(self.context.authorized_capabilities),
            font={'path':'fonts/selected-cjk.ttf','family':'Synthetic CJK','version':'1.0.0'},
            requested_at=utc_now())
        self.generate['template']['digest']=self.installation['template_ref']['digest']
        self.generate['vector_panels']=[{'id':'main-view','source_id':'regions',
            'title':'Regions','extent':[-1,-1,4,2],'design':density_design()}]
        self.scenarios=ScenarioRegistry(self.registry)
        self.intent=self.scenarios.generate_intent(self.generate)
        self.registry.validate('general-generate-request',self.generate)

    def workflow_at_compile(self):
        from tests.test_general_thematic import GenerationTests
        return GenerationTests.workflow_at_compile(self)

    def signed_file(self, name, action, kind, digest):
        from tests.test_general_thematic import sign
        path=self.root/(name+'.yaml')
        atomic_yaml(path,asdict(sign(name,action,kind,digest,
            subject_id=self.generate['subject']['approver_subject_id'],scope=self.generate['scope'])),create_once=False)
        return path

    def test_vector_full_workflow_joins_and_renders(self):
        from tests.test_general_thematic import APPROVAL_KEY, KEY
        from carto_core.schema_registry import load_document
        workflow,request_path=self.workflow_at_compile()
        compiled=workflow.compile(request_path,self.root/'workflow-g1.yaml',approval_key=APPROVAL_KEY)
        self.assertEqual('preview',compiled['state']['step'])
        plan=load_document(self.work/'plan/map-plan.yaml')
        view=plan['decisions']['thematic_views'][0]
        self.assertEqual([5,7.5,10],view['encoding']['scale']['edges'])
        self.assertEqual('graduated-color',view['expression_ref']['id'])
        scene=load_document(self.work/'candidates/render-scene.yaml')
        self.assertTrue(any(r['kind']=='data' and r['ref']['digest']==self.source['attribute_join']['digest'] for r in scene['resources']))
        preview=workflow.preview(request_path,attestation_key=KEY)
        g2=self.signed_file('g2','approve-freeze','resolved-map',preview['approval_object_digest'])
        frozen=workflow.freeze(request_path,g2,approval_key=APPROVAL_KEY,attestation_key=KEY)
        self.assertEqual('render',frozen['state']['step'])
        for name in ('brief_ref','freeze_ref'):
            saved=Path(frozen['lock']['approvals'][name])
            self.assertTrue(saved.is_file())
            self.assertEqual(saved.stem,sha256_digest(load_document(saved))[7:])
        # A user's original receipt file may disappear; audit evidence stays frozen.
        g2.unlink()
        saved=Path(frozen['lock']['approvals']['brief_ref']);original=saved.read_bytes()
        changed=load_document(saved);changed['nonce']='tampered-frozen-approval'
        atomic_yaml(saved,changed,create_once=False)
        with self.assertRaisesRegex(ProtocolError,'LOCK_INPUT_DRIFT.*MAP_SPEC_LOCK_APPROVAL_DRIFT'):
            workflow._locked_render_inputs(self.generate,attestation_key=KEY,browser=None)
        saved.write_bytes(original)
        with self.assertRaisesRegex(ProtocolError,'REVISION_NOT_ALLOWED'):
            workflow.revision_brief(request_path,self.root/'absent-proposal.yaml')
        workflow.render(request_path,attestation_key=KEY)
        checked=workflow.check(request_path,attestation_key=KEY)
        self.assertEqual('passed',checked['validation_report']['status'])
        args=dict(approval_key=APPROVAL_KEY,attestation_key=KEY,recipient_id='synthetic-recipient',
                  recipient_type='project-user',destination='delivery/a31',idempotency_key='a31-delivery-0001')
        wrong=self.signed_file('wrong-review','approve-freeze','resolved-map',sha256_digest(checked['validation_report']))
        with self.assertRaises(SecurityError):workflow.review(request_path,wrong,**args)
        approval=self.signed_file('review','approve-product-review','validation-report',sha256_digest(checked['validation_report']))
        from carto_core.workflow.map_final_check import FinalMapCheckService
        with patch.object(FinalMapCheckService, 'build_manifest', side_effect=RuntimeError('synthetic review interruption')):
            with self.assertRaisesRegex(RuntimeError, 'synthetic review interruption'):
                workflow.review(request_path, approval, **args)
        record_path = next((self.work/'reviews').glob('*.yaml'))
        before = file_digest(record_path)
        reviewed=workflow.review(request_path,approval,**args)
        self.assertEqual(before, file_digest(record_path))
        replay=workflow.review(request_path,approval,**args)
        self.assertEqual(reviewed['delivery_manifest'],replay['delivery_manifest'])
        review_ref=reviewed['delivery_manifest']['review_ref']
        self.registry.validate('product-review',load_document(Path(review_ref['uri'])))
        g3=self.signed_file('g3','approve-delivery','delivery-manifest',reviewed['g3']['object_digest'])
        review_path=Path(review_ref['uri']);original=review_path.read_bytes()
        review_path.write_bytes(original+b'\n# synthetic tampering is canonical-neutral\n')
        tampered=load_document(review_path);tampered['review_id']='different-review'
        atomic_yaml(review_path,tampered,create_once=False)
        with self.assertRaises(ProtocolError):workflow.deliver(request_path,g3,approval_key=APPROVAL_KEY)
        review_path.write_bytes(original)
        delivered=workflow.deliver(request_path,g3,approval_key=APPROVAL_KEY)
        self.assertEqual('succeeded',delivered['state']['status'])
        self.assertTrue((self.root/'delivery/a31/map.png').exists())
        self.assertTrue((self.root/'delivery/a31/map.pdf').exists())

    def test_categorical_expression_reaches_real_preview(self):
        from tests.test_general_thematic import APPROVAL_KEY, KEY
        from carto_core.schema_registry import load_document
        self.generate['map_title']='Category map'
        self.generate['vector_panels'][0]['design']={
            'schema_version':1,'geometry':'polygon','kind':'categorical','measurement':'nominal',
            'field':'code','unit':None,'legend_policy':'observed',
            'categories':[{'value':key,'label':'Category '+key,'symbol':symbol(color)}
                          for key,color in zip('ABC',['#2288CC','#CC3322','#228833'])],
            'missing':{'policy':'reject','label':'No data','symbol':symbol('#888888')}}
        workflow,path=self.workflow_at_compile()
        compiled=workflow.compile(path,self.root/'workflow-g1.yaml',approval_key=APPROVAL_KEY)
        preview=workflow.preview(path,attestation_key=KEY)
        plan=load_document(self.work/'plan/map-plan.yaml')
        self.assertEqual('categorical',plan['bindings']['layers'][0]['expression_ref']['id'])
        self.assertEqual(2,len(preview['evidence']['output_artifacts']))

    def test_multi_candidate_select_and_preview(self):
        from tests.test_general_thematic import APPROVAL_KEY, KEY
        from carto_core.schema_registry import load_document
        base=deepcopy(self.contracts['scenario']['embedded']['style'])
        style_a=deepcopy(base);style_a['typography']['title_pt']=16
        style_b=deepcopy(base);style_b['typography']['title_pt']=18
        self.generate['design_variants']=[
            {'variant_id':'variant-a','revised_cartography':style_a},
            {'variant_id':'variant-b','revised_cartography':style_b}]
        self.registry.validate('general-generate-request',self.generate)
        workflow,path=self.workflow_at_compile()
        compiled=workflow.compile(path,self.root/'workflow-g1.yaml',approval_key=APPROVAL_KEY)
        # Multi-candidate compile stops at select-candidate, not preview.
        self.assertEqual('select-candidate',compiled['state']['step'])
        cset=compiled['candidate_set']
        self.assertEqual(2,len(cset['candidates']))
        self.assertNotIn('selected',cset)  # program never selects
        run=self.context.run_id
        ids=sorted(c['candidate_id'] for c in cset['candidates'])
        self.assertEqual(['candidate-'+run+'-variant-a','candidate-'+run+'-variant-b'],ids)
        for cid in ids:
            self.assertTrue(workflow._design_path('candidates/'+cid+'/resolved-map.yaml').exists())
        # An unknown candidate id is rejected and leaves state untouched.
        with self.assertRaisesRegex(ProtocolError,'CANDIDATE_SELECTION_INVALID'):
            workflow.select_candidate(path,'candidate-does-not-exist')
        chosen=ids[1]
        selected=workflow.select_candidate(path,chosen)
        self.assertEqual('preview',selected['state']['step'])
        self.assertEqual(chosen,selected['selected_candidate_id'])
        # The externally chosen candidate is promoted to the active path preview reads.
        active=load_document(workflow._design_path('candidates/resolved-map.yaml'))
        self.assertEqual(chosen,active['candidate_id'])
        preview=workflow.preview(path,attestation_key=KEY)
        self.assertEqual('passed',preview['evidence']['status'])

    def test_revision_reuses_bundle_and_records_dependency_graph(self):
        from tests.test_general_thematic import APPROVAL_KEY, KEY
        from carto_core.schema_registry import load_document
        from carto_core.workflow import map_data_preparation
        workflow,path=self.workflow_at_compile()
        workflow.compile(path,self.root/'workflow-g1.yaml',approval_key=APPROVAL_KEY)
        preview=workflow.preview(path,attestation_key=KEY)
        first_bundle=load_document(workflow._design_path('data/prepared-data-bundle.yaml'))
        style=deepcopy(self.contracts['scenario']['embedded']['style'])
        style['typography']['title_pt']=17
        proposal={'schema_version':1,'proposal_id':'reuse-title','run_id':self.context.run_id,
                  'parent_revision':1,'changes':{'style':{'new_value':style}},
                  'justification':'Synthetic bundle-reuse acceptance'}
        proposal_path=self.root/'reuse-proposal.yaml';atomic_yaml(proposal_path,proposal)
        brief=workflow.revision_brief(path,proposal_path)
        g1=self.signed_file('reuse-g1','approve-map-brief','map-brief',brief['approval_object_digest'])
        revised=workflow.revise(path,proposal_path,g1,approval_key=APPROVAL_KEY)
        # The dependency graph is recorded beside the staged revision.
        graph=load_document(workflow._design_path('dependency-graph.yaml'))
        self.registry.validate('revision-dependency-graph',graph)
        self.assertTrue(graph['data_evidence_reusable'])
        self.assertIn('candidate',graph['invalidated_nodes'])
        self.assertIn('reusable_bundle_ref',graph)
        # The revised compile must skip prepare entirely: the bundle is reused.
        calls=[]
        original=map_data_preparation.MapDataPreparer.prepare
        def spy(preparer,request,ref):
            calls.append(1)
            return original(preparer,request,ref)
        with patch.object(map_data_preparation.MapDataPreparer,'prepare',side_effect=spy):
            workflow.compile(revised['request_path'],g1,approval_key=APPROVAL_KEY)
        self.assertEqual(0,len(calls))
        reused=load_document(workflow._design_path('data/prepared-data-bundle.yaml'))
        self.assertEqual(first_bundle,reused)
        new_preview=workflow.preview(revised['request_path'],attestation_key=KEY)
        self.assertEqual('passed',new_preview['evidence']['status'])

    def test_feature_labels_reach_real_rendering(self):
        from tests.test_general_thematic import APPROVAL_KEY, KEY
        from carto_core.schema_registry import load_document
        from carto_core.compiler.vector_portrayal import resolve_labels
        # Declare a label field on the panel: features carry a "code" property.
        self.generate['vector_panels'][0]['labels'] = {'field': 'code'}
        self.registry.validate('general-generate-request', self.generate)
        workflow, path = self.workflow_at_compile()
        compiled = workflow.compile(path, self.root/'workflow-g1.yaml', approval_key=APPROVAL_KEY)
        self.assertEqual('preview', compiled['state']['step'])
        # The resolved portrayal carries the label declaration and labels with anchors.
        # Chain: render-scene -> page_request_ref -> page-request.panels -> portrayal_ref.
        scene = load_document(workflow._design_path('candidates/render-scene.yaml'))
        page_request = load_document(Path(scene['page_request_ref']['uri']))
        label_portrayal = None
        for panel in page_request['panels']:
            ref = panel.get('portrayal_ref')
            if ref and ref.get('uri'):
                doc = load_document(Path(ref['uri']))
                if 'labels' in doc:
                    label_portrayal = doc
                    break
        self.assertIsNotNone(label_portrayal, 'No resolved portrayal carries labels')
        self.assertIn('label_source', label_portrayal)
        self.assertEqual({'field': 'code'}, label_portrayal['label_source'])
        labels = label_portrayal['labels']
        self.assertTrue(len(labels) >= 3)  # three features A, B, C
        self.assertEqual({'A', 'B', 'C'}, {l['text'] for l in labels})
        for label in labels:
            self.assertIn('anchor', label)
            self.assertEqual(2, len(label['anchor']))
        # The full preview renders successfully with labels on the page.
        preview = workflow.preview(path, attestation_key=KEY)
        self.assertEqual('passed', preview['evidence']['status'])
        self.assertEqual(2, len(preview['evidence']['output_artifacts']))

    def test_labels_missing_values_are_skipped_not_invented(self):
        """Pure unit test: resolve_labels skips missing/non-string/blank, never invents."""
        from carto_core.compiler.vector_portrayal import resolve_labels
        report = {'features': [
            {'id': 'feature-0', 'geometry': {'type': 'Point', 'coordinates': [0, 0]},
             'properties': {'code': 'A'}},
            {'id': 'feature-1', 'geometry': {'type': 'Point', 'coordinates': [1, 0]},
             'properties': {'code': ''}},          # blank -> skipped
            {'id': 'feature-2', 'geometry': {'type': 'Point', 'coordinates': [2, 0]},
             'properties': {'code': None}},        # null -> skipped
            {'id': 'feature-3', 'geometry': {'type': 'Point', 'coordinates': [3, 0]},
             'properties': {'other': 'x'}},        # field absent -> skipped
        ]}
        labels = resolve_labels(report, {'field': 'code'})
        self.assertEqual(1, len(labels))
        self.assertEqual('A', labels[0]['text'])
        self.assertEqual('feature-0', labels[0]['feature_id'])
        self.assertEqual([0.0, 0.0], labels[0]['anchor'])
        # max_labels truncates deterministically.
        report['features'].append(
            {'id': 'feature-4', 'geometry': {'type': 'Point', 'coordinates': [4, 0]},
             'properties': {'code': 'B'}})
        labels = resolve_labels(report, {'field': 'code', 'max_labels': 1})
        self.assertEqual(1, len(labels))

    def test_line_features_compile_and_render(self):
        from tests.test_general_thematic import APPROVAL_KEY, KEY
        from carto_core.schema_registry import load_document
        # Replace the polygon source with a line source (roads / routes).
        features = [
            {'type': 'Feature', 'geometry': {'type': 'LineString',
             'coordinates': [[0, 0], [1, 1], [2, 0]]}, 'properties': {'code': 'A'}},
            {'type': 'Feature', 'geometry': {'type': 'MultiLineString',
             'coordinates': [[[2, 0], [3, 1]], [[3, 1], [4, 0]]]}, 'properties': {'code': 'B'}},
        ]
        line_file = self.root / 'roads.geojson'
        line_file.write_text(json.dumps({'type': 'FeatureCollection', 'features': features}), encoding='utf8')
        source = {'schema_version': 1, 'source_id': 'regions', 'role': 'thematic-features',
                  'format': 'geojson', 'crs': 'EPSG:4326', 'encoding': 'utf-8',
                  'files': [{'extension': '.geojson', 'path': str(line_file),
                             'digest': file_digest(line_file), 'size_bytes': line_file.stat().st_size}],
                  'data_nature': 'user-provided', 'contains_sensitive_coordinates': False,
                  'contains_production_data': False, 'license': 'project-approved'}
        self.generate.update(vector_sources=[source],
            sources=[{'id': 'regions', 'version': '1.0.0', 'digest': sha256_digest(source)}])
        # Use a single-symbol line design (one color for all lines).
        self.generate['vector_panels'][0] = {
            'id': 'main-view', 'source_id': 'regions', 'title': 'Routes',
            'extent': [-1, -1, 5, 2],
            'design': {'schema_version': 1, 'geometry': 'line', 'kind': 'single',
                       'measurement': 'nominal', 'field': None, 'unit': None,
                       'label': 'Route', 'missing': {'policy': 'reject', 'label': 'No data',
                       'symbol': symbol('#888888')},
                       'symbol': symbol('#2288CC')}}
        # Remove labels declaration if present from prior tests.
        self.generate['vector_panels'][0].pop('labels', None)
        self.registry.validate('general-generate-request', self.generate)
        workflow, path = self.workflow_at_compile()
        compiled = workflow.compile(path, self.root/'workflow-g1.yaml', approval_key=APPROVAL_KEY)
        self.assertEqual('preview', compiled['state']['step'])
        # The resolved portrayal classifies features as line geometry.
        scene = load_document(workflow._design_path('candidates/render-scene.yaml'))
        page_request = load_document(Path(scene['page_request_ref']['uri']))
        panel = page_request['panels'][0]
        portrayal = load_document(Path(panel['portrayal_ref']['uri']))
        self.assertEqual('line', portrayal.get('encoding', {}).get('geometry_role'))
        self.assertEqual(2, portrayal['counts']['feature_count'])
        self.assertEqual(2, portrayal['counts']['visible_count'])
        # All features get the single symbol's color.
        for style in portrayal['feature_styles']:
            self.assertIsNotNone(style['style'])
            self.assertEqual('#2288CC', style['style']['symbol']['color'])
        # The full preview renders with the line drawing branch.
        preview = workflow.preview(path, attestation_key=KEY)
        self.assertEqual('passed', preview['evidence']['status'])

    def test_line_mixed_with_point_rejected(self):
        """A source must have one geometry family: line + point is rejected."""
        from carto_core.workflow.vector_preparation import VectorPreparationService
        from carto_core.errors import ProtocolError
        from carto_core.contracts.execution import ExecutionContext
        features = [
            {'type': 'Feature', 'geometry': {'type': 'LineString', 'coordinates': [[0, 0], [1, 1]]},
             'properties': {'code': 'A'}},
            {'type': 'Feature', 'geometry': {'type': 'Point', 'coordinates': [2, 2]},
             'properties': {'code': 'B'}},
        ]
        mixed_file = self.root / 'mixed.geojson'
        mixed_file.write_text(json.dumps({'type': 'FeatureCollection', 'features': features}), encoding='utf8')
        source = {'schema_version': 1, 'source_id': 'mixed', 'role': 'thematic-features',
                  'format': 'geojson', 'crs': 'EPSG:4326', 'encoding': 'utf-8',
                  'files': [{'extension': '.geojson', 'path': str(mixed_file),
                             'digest': file_digest(mixed_file), 'size_bytes': mixed_file.stat().st_size}],
                  'data_nature': 'user-provided', 'contains_sensitive_coordinates': False,
                  'contains_production_data': False, 'license': 'project-approved'}
        service = VectorPreparationService(project_root=self.root, allowed_roots=[str(self.root)],
                                           registry=self.registry)
        with self.assertRaisesRegex(ProtocolError, 'VECTOR_GEOMETRY_MIXED'):
            service.prepare(source, ExecutionContext('run', 'tenant', 'project', 'subj',
                              frozenset({'operator'}), frozenset({'project'}), frozenset()))

    def test_line_z_coordinates_rejected(self):
        """3D line geometries (Z coordinates) are rejected, same as point/polygon."""
        from carto_core.workflow.vector_preparation import VectorPreparationService
        from carto_core.errors import ProtocolError
        from carto_core.contracts.execution import ExecutionContext
        features = [
            {'type': 'Feature', 'geometry': {'type': 'LineString',
             'coordinates': [[0, 0, 100], [1, 1, 200]]}, 'properties': {'code': 'A'}},
        ]
        z_file = self.root / 'z_line.geojson'
        z_file.write_text(json.dumps({'type': 'FeatureCollection', 'features': features}), encoding='utf8')
        source = {'schema_version': 1, 'source_id': 'zline', 'role': 'thematic-features',
                  'format': 'geojson', 'crs': 'EPSG:4326', 'encoding': 'utf-8',
                  'files': [{'extension': '.geojson', 'path': str(z_file),
                             'digest': file_digest(z_file), 'size_bytes': z_file.stat().st_size}],
                  'data_nature': 'user-provided', 'contains_sensitive_coordinates': False,
                  'contains_production_data': False, 'license': 'project-approved'}
        service = VectorPreparationService(project_root=self.root, allowed_roots=[str(self.root)],
                                           registry=self.registry)
        with self.assertRaisesRegex(ProtocolError, 'VECTOR_GEOMETRY_INVALID'):
            service.prepare(source, ExecutionContext('run', 'tenant', 'project', 'subj',
                              frozenset({'operator'}), frozenset({'project'}), frozenset()))

    def _make_basemap_image(self):
        from PIL import Image as PILImage
        basemap_file = self.root / 'basemap.png'
        image = PILImage.new('RGB', (120, 100))
        for i in range(120):
            for j in range(100):
                image.putpixel((i, j), (200 - i, 180 - j, 160))
        image.save(basemap_file)
        return basemap_file

    def test_basemap_reaches_real_rendering(self):
        from tests.test_general_thematic import APPROVAL_KEY, KEY
        from carto_core.schema_registry import load_document
        basemap_file = self._make_basemap_image()
        self.generate['basemap'] = {
            'image': {'path': str(basemap_file)},
            'crs': {'authority': 'EPSG', 'code': '4326'},
            'extent': [-1, -1, 5, 2],
            'style': {'desaturate': 0.5, 'lighten': 0.2},
        }
        self.registry.validate('general-generate-request', self.generate)
        workflow, path = self.workflow_at_compile()
        compiled = workflow.compile(path, self.root / 'workflow-g1.yaml', approval_key=APPROVAL_KEY)
        self.assertEqual('preview', compiled['state']['step'])
        # The basemap is frozen into the page request with a digest-bound image.
        scene = load_document(workflow._design_path('candidates/render-scene.yaml'))
        page_request = load_document(Path(scene['page_request_ref']['uri']))
        frozen = page_request['basemap']
        self.assertEqual({'authority': 'EPSG', 'code': '4326'}, frozen['registration']['crs'])
        self.assertEqual([-1, -1, 5, 2], frozen['registration']['extent'])
        self.assertEqual('extent', frozen['registration']['kind'])
        self.assertEqual({'desaturate': 0.5, 'lighten': 0.2}, frozen['style'])
        self.assertEqual(basemap_file.stat().st_size, frozen['image']['size_bytes'])
        # The paint order is a frozen contract: ground first, figures above.
        self.assertEqual(['basemap', 'thematic', 'legends', 'charts', 'furniture'],
                         page_request['layer_stack'])
        # The full preview renders with the ground layer beneath the thematic features.
        preview = workflow.preview(path, attestation_key=KEY)
        self.assertEqual('passed', preview['evidence']['status'])

    def test_basemap_extent_insufficient_rejected(self):
        from tests.test_general_thematic import APPROVAL_KEY
        from carto_core.errors import ProtocolError
        basemap_file = self._make_basemap_image()
        self.generate['basemap'] = {
            'image': {'path': str(basemap_file)},
            'crs': {'authority': 'EPSG', 'code': '4326'},
            'extent': [0.9, 0.5, 1.2, 0.7],  # far smaller than the thematic bounds
        }
        workflow, path = self.workflow_at_compile()
        with self.assertRaisesRegex(ProtocolError, 'BASEMAP_EXTENT_INSUFFICIENT'):
            workflow.compile(path, self.root / 'workflow-g1.yaml', approval_key=APPROVAL_KEY)

    def test_basemap_crs_mismatch_rejected(self):
        from tests.test_general_thematic import APPROVAL_KEY
        from carto_core.errors import ProtocolError
        basemap_file = self._make_basemap_image()
        self.generate['basemap'] = {
            'image': {'path': str(basemap_file)},
            'crs': {'authority': 'EPSG', 'code': '3857'},  # display CRS is 4326
            'extent': [-1, -1, 5, 2],
        }
        workflow, path = self.workflow_at_compile()
        with self.assertRaisesRegex(ProtocolError, 'BASEMAP_CRS_MISMATCH'):
            workflow.compile(path, self.root / 'workflow-g1.yaml', approval_key=APPROVAL_KEY)

    def test_proportional_count_reaches_real_preview(self):
        from tests.test_general_thematic import APPROVAL_KEY, KEY
        from carto_core.schema_registry import load_document
        source=self.make_source('point');source['data_nature']='user-provided'
        self.generate.update(vector_sources=[source],map_title='Population counts',
            sources=[{'id':'regions','version':'1.0.0','digest':sha256_digest(source)}])
        self.generate['vector_panels'][0]['design']=count_design()
        workflow,path=self.workflow_at_compile()
        workflow.compile(path,self.root/'workflow-g1.yaml',approval_key=APPROVAL_KEY)
        preview=workflow.preview(path,attestation_key=KEY)
        plan=load_document(self.work/'plan/map-plan.yaml')
        encoding=plan['decisions']['thematic_views'][0]['encoding']
        self.assertEqual('proportional-symbol',plan['bindings']['layers'][0]['expression_ref']['id'])
        self.assertAlmostEqual(radius(encoding,10)**2/radius(encoding,40)**2,.25)
        self.assertEqual('passed',preview['evidence']['status'])

    def test_revision_preserves_history_rejects_stale_approvals_and_recovers(self):
        from tests.test_general_thematic import APPROVAL_KEY, KEY
        from carto_core.schema_registry import load_document
        workflow,path=self.workflow_at_compile()
        workflow.compile(path,self.root/'workflow-g1.yaml',approval_key=APPROVAL_KEY)
        preview=workflow.preview(path,attestation_key=KEY)
        old_g2=self.signed_file('old-g2','approve-freeze','resolved-map',preview['approval_object_digest'])
        old_files={ref['uri']:file_digest(Path(ref['uri']))
            for receipt in workflow.state_store.receipts() for ref in receipt['receipt']['output_refs'] if ref.get('uri')}
        style=deepcopy(self.contracts['scenario']['embedded']['style'])
        style['typography']['title_pt']=17
        design=density_design()
        design.update(normalization=None,measurement='normalized-index',unit='index',
                      classification={'method':'manual','edges':[0,25,50],'labels':['Low','High']})
        proposal={'schema_version':1,'proposal_id':'change-title','run_id':self.context.run_id,
                  'parent_revision':1,'changes':{'map_title':{'new_value':'Revised population density'},
                      'style':{'new_value':style},'panel_designs':{'new_value':{'main-view':design}}},
                  'justification':'Synthetic revision acceptance'}
        proposal_path=self.root/'proposal.yaml';atomic_yaml(proposal_path,proposal)
        brief=workflow.revision_brief(path,proposal_path)
        wrong=self.signed_file('proposal-g1','approve-map-brief','map-brief',sha256_digest(proposal))
        with self.assertRaisesRegex(SecurityError,'APPROVAL_OBJECT_MISMATCH'):
            workflow.revise(path,proposal_path,wrong,approval_key=APPROVAL_KEY)
        g1=self.signed_file('revised-g1','approve-map-brief','map-brief',brief['approval_object_digest'])
        # Interruption between durable revision writes/budget and journal commit.
        with patch.object(workflow.state_store,'complete_step',side_effect=RuntimeError('synthetic interruption')):
            with self.assertRaisesRegex(RuntimeError,'synthetic interruption'):
                workflow.revise(path,proposal_path,g1,approval_key=APPROVAL_KEY)
        self.assertEqual(sha256_digest(self.generate),workflow.state_store.load().input_fingerprint)
        revised=workflow.revise(path,proposal_path,g1,approval_key=APPROVAL_KEY)
        self.assertEqual(1,workflow._budget_store.load().revisions)
        self.assertEqual(brief['brief'],revised['brief'])
        revised_path=Path(revised['request_path'])
        self.assertEqual('revise',revised['receipt']['step'])
        self.assertEqual(self.generate,load_document(self.work/'request/generate-request.yaml'))
        workflow.compile(revised_path,g1,approval_key=APPROVAL_KEY)
        new_preview=workflow.preview(revised_path,attestation_key=KEY)
        self.assertNotEqual(preview['approval_object_digest'],new_preview['approval_object_digest'])
        for uri,digest in old_files.items():self.assertEqual(digest,file_digest(Path(uri)),uri)
        with self.assertRaisesRegex(SecurityError,'APPROVAL_OBJECT_MISMATCH'):
            workflow.freeze(revised_path,old_g2,approval_key=APPROVAL_KEY,attestation_key=KEY)
        new_g2=self.signed_file('new-g2','approve-freeze','resolved-map',new_preview['approval_object_digest'])
        workflow.freeze(revised_path,new_g2,approval_key=APPROVAL_KEY,attestation_key=KEY)

    def test_changed_attribute_csv_changes_rendered_pixels(self):
        from tests.test_general_thematic import APPROVAL_KEY, KEY
        from carto_core.schema_registry import load_document
        from carto_core.workflow.map_generation import MapGenerationWorkflow
        from carto_core.repository.template_installer import ProjectTemplateInstaller
        import numpy as np
        from PIL import Image
        design=density_design();design.update(normalization=None,measurement='normalized-index',unit='index',
            classification={'method':'manual','edges':[0,25,50],'labels':['Low','High']})
        self.generate['vector_panels'][0]['design']=design
        images=[];digests=[]
        for iteration in (1,2):
            if iteration==1:
                workflow,path=self.workflow_at_compile()
            else:
                self.table.write_text('code,pop,area\nA,10,2\nB,35,2\nC,40,4\n',encoding='utf8')
                source=self.make_source();source['data_nature']='user-provided'
                self.generate.update(run_id='a31-run-second',vector_sources=[source],
                    sources=[{'id':'regions','version':'1.0.0','digest':sha256_digest(source)}])
                path=self.root/'second-request.yaml';atomic_yaml(path,self.generate)
                workflow=MapGenerationWorkflow(allowed_roots=[self.root],project_root=self.root,
                    workdir=self.root/'second-work',repository_root=self.root/'template-repo',repository_scope='local:templates')
                seam=patch.object(workflow,'_verify_installed_template');seam.start();self.addCleanup(seam.stop)
                workflow.intake(path);brief=workflow.brief(path)
                self.signed_file('workflow-g1','approve-map-brief','map-brief',brief['approval_object_digest'])
            compiled=workflow.compile(path,self.root/'workflow-g1.yaml',approval_key=APPROVAL_KEY)
            preview=workflow.preview(path,attestation_key=KEY)
            png=next(a['artifact_ref']['uri'] for a in preview['evidence']['output_artifacts'] if a['target']=='png')
            with Image.open(png) as image:images.append(np.asarray(image.convert('RGB')).copy())
            digests.append(compiled['candidate']['execution_digest'])
        self.assertNotEqual(digests[0],digests[1])
        self.assertEqual(images[0].shape,images[1].shape)
        # Compare real pixels, not file metadata. Middle region changes classes.
        self.assertGreater(np.count_nonzero(np.any(images[0]!=images[1],axis=2)),1000)


    def test_material_facts_are_frozen_reproducible_and_verified(self):
        from tests.test_general_thematic import APPROVAL_KEY, KEY
        from carto_core.schema_registry import load_document
        from carto_core.workflow.map_data_preparation import MapDataPreparer
        note=self.root/'note.txt';note.write_text('Population survey: synthetic evidence only.',encoding='utf8')
        self.generate['material_sources']=[{'source_id':'note','path':'note.txt','format':'text/plain'}]
        preparer=MapDataPreparer(self.guard,self.root,self.work/'material-test',self.registry)
        first=preparer.prepare(self.generate,artifact_ref('generate-request',self.generate))
        second=preparer.prepare(self.generate,artifact_ref('generate-request',self.generate))
        self.assertEqual(first,second)
        workflow,path=self.workflow_at_compile()
        compiled=workflow.compile(path,self.root/'workflow-g1.yaml',approval_key=APPROVAL_KEY)
        ref=compiled['candidate']['execution']['material_facts_refs'][0]
        facts=load_document(Path(ref['uri']))
        self.registry.validate('data-facts',facts)
        snapshot=Path(facts['material_refs'][0]['uri'])
        self.assertNotEqual(snapshot,note)
        note.write_text('The original file has changed after the snapshot.',encoding='utf8')
        workflow.preview(path,attestation_key=KEY)
        snapshot.write_text('tampered frozen material',encoding='utf8')
        from carto_core.workflow.material_evidence import verify_material_facts
        with self.assertRaisesRegex(ProtocolError,'MATERIAL_SNAPSHOT_DRIFT'):
            verify_material_facts(compiled['candidate']['execution'],self.guard,self.root,self.registry)

    def test_map_gates_bind_independent_reviewer_not_operator(self):
        from tests.test_general_thematic import sign, APPROVAL_KEY
        from carto_core.schema_registry import load_document
        workflow,path=self.workflow_at_compile()
        brief=load_document(self.work/'brief/map-brief.yaml')
        operator=sign('operator-g1','approve-map-brief','map-brief',sha256_digest(brief),
                      subject_id=self.context.subject_id,scope=self.generate['scope'])
        approval=self.root/'operator-g1.yaml';atomic_yaml(approval,asdict(operator))
        with self.assertRaisesRegex(SecurityError,'APPROVAL_SUBJECT_MISMATCH'):
            workflow.compile(path,approval,approval_key=APPROVAL_KEY)
        self.assertFalse((self.work/'data/prepared-data-bundle.yaml').exists())
        self.assertEqual('waiting_approval',workflow.state_store.load().status)
        self.generate['subject']['approver_subject_id']=self.generate['subject']['subject_id']
        with self.assertRaisesRegex(SecurityError,'APPROVER_NOT_INDEPENDENT'):
            workflow._validate_runtime_request(self.generate)

    def test_revision_cannot_introduce_unauthorized_classification(self):
        self.generate['allowed_capabilities']=['read','join','render-preview']
        self.generate['vector_panels'][0]['design']={
            'schema_version':1,'geometry':'polygon','kind':'single','measurement':'nominal',
            'field':None,'unit':None,'label':'Regions','symbol':symbol('#2288CC'),
            'missing':{'policy':'reject','label':'No data','symbol':symbol('#888888')}}
        workflow,path=self.workflow_at_compile()
        proposal={'schema_version':1,'proposal_id':'unapproved-operation','run_id':self.context.run_id,
                  'parent_revision':1,'changes':{'panel_designs':{'new_value':{'main-view':density_design()}}},
                  'justification':'Must not add classify outside the authorized capability set'}
        prop=self.root/'unauthorized-design.yaml';atomic_yaml(prop,proposal)
        with self.assertRaisesRegex(SecurityError,'CAPABILITY_NOT_AUTHORIZED'):
            workflow.revision_brief(path,prop)
        self.assertEqual(sha256_digest(self.generate),workflow.state_store.load().input_fingerprint)
        self.assertEqual(0,workflow._budget_store.load().revisions)

    def test_three_revisions_are_cumulative_and_fourth_is_rejected(self):
        from tests.test_general_thematic import APPROVAL_KEY
        workflow,path=self.workflow_at_compile()
        for parent in (1,2,3,4):
            proposal={'schema_version':1,'proposal_id':'revision-'+str(parent),'run_id':self.context.run_id,
                      'parent_revision':parent,'changes':{'map_title':{'new_value':'Title '+str(parent)}},
                      'justification':'Synthetic budget acceptance'}
            prop=self.root/('proposal-'+str(parent)+'.yaml');atomic_yaml(prop,proposal)
            brief=workflow.revision_brief(path,prop)
            g1=self.signed_file('revision-'+str(parent),'approve-map-brief','map-brief',brief['approval_object_digest'])
            if parent<4:
                revised=workflow.revise(path,prop,g1,approval_key=APPROVAL_KEY);path=Path(revised['request_path'])
            else:
                with self.assertRaisesRegex(ProtocolError,'EXECUTION_BUDGET_EXCEEDED'):
                    workflow.revise(path,prop,g1,approval_key=APPROVAL_KEY)
        self.assertEqual(3,workflow._budget_store.load().revisions)


class ThematicApprovalTests(unittest.TestCase):
    def test_nonce_recovery_requires_same_run_receipt_and_object(self):
        from carto_core.security.nonce_store import NonceStore
        with tempfile.TemporaryDirectory() as directory:
            store=NonceStore(Path(directory)/'nonce.db')
            store.verify_and_consume('synthetic-nonce-123','receipt-a','run-a','sha256:'+'a'*64)
            self.assertTrue(store.is_consumed('synthetic-nonce-123'))
            store.verify_and_consume('synthetic-nonce-123','receipt-a','run-a','sha256:'+'a'*64)
            for receipt,run,digest in [('receipt-a','run-b','a'),('receipt-b','run-a','a'),('receipt-a','run-a','b')]:
                with self.assertRaisesRegex(SecurityError,'APPROVAL_NONCE_REPLAY'):
                    store.verify_and_consume('synthetic-nonce-123',receipt,run,'sha256:'+digest*64)

    def test_signed_approval_for_wrong_environment_is_rejected(self):
        from tests.test_general_thematic import sign, APPROVAL_KEY
        from carto_core.workflow.approvals import ApprovalGateCoordinator
        digest='sha256:'+'a'*64
        approval=sign('G1','approve-map-brief','map-brief',digest)
        coordinator=ApprovalGateCoordinator(APPROVAL_KEY,trusted_environment='production')
        with self.assertRaisesRegex(SecurityError,'APPROVAL_ENVIRONMENT_MISMATCH'):
            coordinator.require('G1',approval,digest)



    def test_template_approvals_bind_declared_approver_not_receipt_claims(self):
        from tests.test_general_thematic import PublishLineTests, APPROVAL_KEY, sign
        from carto_core.security.approval import sign_receipt
        PublishLineTests.setUp(self)
        PublishLineTests.run_to_validated(self)
        prepared=self.workflow.prepare_publication(self.request_path,
            repository_root=self.publish_kwargs['repository_root'],
            repository_scope=self.publish_kwargs['repository_scope'],
            idempotency_key=self.publish_kwargs['idempotency_key'])
        good=sign('TP','approve-template-publish','template-publication',prepared['object_digest'],
            subject_id=self.request['subject']['approver_subject_id'],scope=self.request['scope'],
            tenant_id=self.request['subject']['tenant_id'])
        for field in ('subject_id','tenant_id','scope','environment'):
            wrong=sign_receipt(replace(good,**{field:'wrong-value'}),APPROVAL_KEY)
            path=self.root/('bad-'+field+'.yaml');atomic_yaml(path,asdict(wrong))
            with self.subTest(field=field),self.assertRaises(SecurityError):
                self.workflow.publish(self.request_path,path,**self.publish_kwargs)
        self.assertEqual('waiting_approval',self.workflow.state_store.load().status)


class ThematicTemplateTests(unittest.TestCase):
    def test_vector_template_real_validation_and_publication(self):
        from tests.test_general_thematic import PublishLineTests, sign
        from carto_core.schema_registry import load_document
        PublishLineTests.setUp(self)
        self.request.update(geometry='vector',version='4.0.0',profile='general-vector-authoring',
                            role_bindings={'thematic_features':'legend-sample'})
        self.request_path.write_text(json.dumps(self.request,ensure_ascii=False),encoding='utf8')
        result=PublishLineTests.run_to_validated(self)
        self.assertEqual('passed',result['evidence']['status'], result['evidence']['check_results'] if 'check_results' in result['evidence'] else result['evidence'])
        # A3.1 uses active expression catalog options, not deprecated vector/explicit.
        portrayal=load_document(self.root/'work/staging/package/contracts/portrayal.yaml')
        self.assertEqual({'categorical','graduated-color','proportional-symbol'},
            {r['id'] for r in portrayal['layers'][0]['expression_options']})
        evidence=result['evidence']
        self.assertEqual(23,len(evidence['grid_cases']))
        prepared=self.workflow.prepare_publication(self.request_path,
            repository_root=self.publish_kwargs['repository_root'],
            repository_scope=self.publish_kwargs['repository_scope'],
            idempotency_key=self.publish_kwargs['idempotency_key'])
        approval=self.root/'tp.yaml'
        atomic_yaml(approval,asdict(sign('TP','approve-template-publish','template-publication',prepared['object_digest'],
            subject_id=self.request['subject']['approver_subject_id'],scope=self.request['scope'],
            tenant_id=self.request['subject']['tenant_id'])))
        published=self.workflow.publish(self.request_path,approval,**self.publish_kwargs)
        self.assertEqual('succeeded',published['state']['status'])

        # Continue from the actual published repository, with NO installer/admission seam.
        from tests.fixtures.schema_cases import VARIANT_CASES
        from tests.test_general_thematic import APPROVAL_KEY, KEY
        from carto_core.workflow.map_generation import MapGenerationWorkflow
        import fiona
        data_dir=self.root/'synthetic-regions';data_dir.mkdir()
        with fiona.open(str(data_dir/'regions.shp'),'w',driver='ESRI Shapefile',
                crs='EPSG:26911',encoding='UTF-8',
                schema={'geometry':'Polygon','properties':{'population':'float','area':'float'}}) as dst:
            for i,value in enumerate((10,20,40)):
                x=500000+i*1000;y=4400000
                dst.write({'geometry':{'type':'Polygon','coordinates':[[[x,y],[x+800,y],[x+800,y+800],[x,y+800],[x,y]]]},
                           'properties':{'population':float(value),'area':.64}})
        source={'schema_version':1,'source_id':'regions','role':'thematic-features',
            'format':'shapefile','crs':'EPSG:26911','encoding':'utf-8',
            'files':[{'extension':p.suffix,'path':str(p),'digest':file_digest(p),'size_bytes':p.stat().st_size}
                     for p in sorted(data_dir.iterdir()) if p.suffix in {'.shp','.shx','.dbf','.prj','.cpg'}],
            'data_nature':'user-provided','contains_production_data':False,
            'contains_sensitive_coordinates':False,'license':'project-approved'}
        request=deepcopy(VARIANT_CASES['general-generate-request.vector'])
        request.update(request_id='integrated-thematic',run_id='integrated-thematic',project_id='integrated-project',
            map_title='Synthetic population density',scope='project:integrated-project',
            subject={'subject_id':'integrated-operator','tenant_id':'test-tenant',
                     'approver_subject_id':'synthetic-reviewer','namespace':'integrated-project'},
            sources=[{'id':'regions','version':'1.0.0','digest':sha256_digest(source)}],vector_sources=[source],
            vector_panels=[{'id':'main-view','source_id':'regions','title':'Synthetic regions',
                           'extent':[499000,4399000,504000,4402000],'design':density_design()}],
            font={'path':str(self.font_path),'family':'Synthetic CJK','version':'1.0.0'},requested_at=utc_now())
        request['template']['digest']=evidence['package_ref']['digest']
        request_path=self.root/'integrated-map.yaml';atomic_yaml(request_path,request)
        work=self.root/'integrated-work'
        flow=MapGenerationWorkflow(allowed_roots=[self.root],project_root=self.root,workdir=work,
                                   repository_root=self.root/'repo',repository_scope='local:templates')
        def approval_file(name,action,kind,digest):
            target=self.root/(name+'.yaml')
            atomic_yaml(target,asdict(sign(name,action,kind,digest,
                subject_id=request['subject']['approver_subject_id'],scope=request['scope'])))
            return target
        flow.intake(request_path);brief=flow.brief(request_path)
        g1=approval_file('integrated-g1','approve-map-brief','map-brief',brief['approval_object_digest'])
        flow.compile(request_path,g1,approval_key=APPROVAL_KEY)
        preview=flow.preview(request_path,attestation_key=KEY)
        g2=approval_file('integrated-g2','approve-freeze','resolved-map',preview['approval_object_digest'])
        flow.freeze(request_path,g2,approval_key=APPROVAL_KEY,attestation_key=KEY)
        flow.render(request_path,attestation_key=KEY)
        check=flow.check(request_path,attestation_key=KEY)
        review=approval_file('integrated-review','approve-product-review','validation-report',sha256_digest(check['validation_report']))
        product=flow.review(request_path,review,approval_key=APPROVAL_KEY,attestation_key=KEY,
            recipient_id='synthetic-recipient',recipient_type='project-user',destination='delivery/integrated',
            idempotency_key='integrated-delivery-0001')
        g3=approval_file('integrated-g3','approve-delivery','delivery-manifest',product['g3']['object_digest'])
        result=flow.deliver(request_path,g3,approval_key=APPROVAL_KEY)
        self.assertEqual('succeeded',result['state']['status'])
        self.assertTrue((self.root/'delivery/integrated/map.png').exists())



if __name__=='__main__':unittest.main()
