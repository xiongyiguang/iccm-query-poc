import copy,json,sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'backend'),str(Path(__file__).resolve().parent)]
from business_request import RequestInvalid
from request_gateway import ordinary,adapt,migrate,seal,require_verified,clear_verification,validate_categories
from test_request_checklist import checklist,prior
import replay_semantic_holdout as h


def plan(filters,op='search',props=None):
    p={'operation':op,'entity':None,'scope':'direct','clarification':'','query':{'target':'points','filters':filters}}
    if props:p['properties']=props
    return p


class Store:
    version='v1'
    def rows(self,sql,args):return []


class GatewayTests(unittest.TestCase):
    def test_legacy_name_attribute_is_verified_before_program_code_resolution(self):
        import model,sqlite3
        class Names:
            version='test-v1'
            def __init__(self):
                self.db=sqlite3.connect(':memory:');self.db.row_factory=sqlite3.Row
                self.db.execute('create table objects(tree text,code text,name text)')
                self.db.execute('create table points(code text,name text)')
                self.db.execute('insert into objects values(?,?,?)',('equipment_class','C1','类别甲'))
            def rows(self,sql,args):return [dict(x) for x in self.db.execute(sql,args)]
        s=Names();q='类别甲的名称与编码'
        p={'operation':'attributes','entity':{'tree':'equipment_class','name':'类别甲'},'scope':'direct','clarification':'','properties':['name','code']}
        try:
            model.TRACE.value={'engine':'legacy','context_route':{'decision':{'domain':'equipment_class','reference':'类别甲','identifier_field':None,'context_mode':'new'}}}
            with patch('request_checklist.gate',return_value={'decision':'accept','choice':'candidate'}):
                out=model.bind_references(s,q,p)
            self.assertIsNone(out['entity'])
            self.assertEqual(out['query'],{'target':'equipment_class','filters':[h.f('identity','equals','类别甲')]})
            require_verified(s,q,out)
        finally:s.db.close();model.TRACE.value=None;clear_verification()
    def test_pre_turn_frame_preserves_pending_prompt_and_verified_complete_subject(self):
        import sqlite3
        from request_gateway import reference_context
        class Entities:
            def __init__(self):
                self.db=sqlite3.connect(':memory:');self.db.row_factory=sqlite3.Row
                self.db.execute('create table objects(tree text,code text,name text)')
                self.db.execute('create table points(code text,name text)')
                self.db.executemany('insert into objects values(?,?,?)',[('config','C1','构型甲'),('equipment_class','C1','类别甲')])
            def rows(self,sql,args):return [dict(x) for x in self.db.execute(sql,args)]
        s=Entities()
        try:
            context={'entity':{'tree':'equipment_class','code':'C1'},'pending_question':'介绍类别甲',
                     'clarification':'请选择对象树','pending_reference':'类别甲',
                     'pending_request':{'operation':'clarify'},'dialogue':[{'question':'介绍类别甲'}]}
            original=copy.deepcopy(context)
            out=reference_context(context,{'tree':'config','code':'C1'},s)
            self.assertEqual(out['confirmed_subjects'],[{'tree':'config','code':'C1','name':'构型甲','kind':'user_selection'},
                                                      {'tree':'equipment_class','code':'C1','name':'类别甲','kind':'executed_entity'}])
            self.assertEqual(out['pending']['question'],'介绍类别甲');self.assertEqual(out['pending']['asked'],'请选择对象树')
            out['pending']['request']['operation']='mutated';self.assertEqual(context,original)
            empty=reference_context({},None,s);self.assertEqual(empty['confirmed_subjects'],[]);self.assertIsNone(empty['pending'])
            ambiguous={'pending_request':{'operation':'attributes','properties':['name','code']},
                       'outcome':{'kind':'ambiguous'},'dialogue':[{'question':'C1的名称编码'}]}
            frame=reference_context(ambiguous,{'tree':'config','code':'C1'},s)
            self.assertEqual(frame['pending']['request']['properties'],['name','code'])
            self.assertEqual(frame['pending']['question'],'C1的名称编码')
            self.assertEqual([x['id'] for x in frame['references']],list(range(1,len(frame['references'])+1)))
        finally:s.db.close()
    def test_grounding_never_accepts_existing_short_identifier_inside_longer_literal(self):
        import sqlite3
        from business_request import ground_identifiers
        class Names:
            def __init__(self):
                self.db=sqlite3.connect(':memory:');self.db.row_factory=sqlite3.Row
                self.db.execute('create table points(name text,code text,system text)')
                self.db.executemany('insert into points values(?,?,?)',[('测点7','C7','s'),('测点71','C71','s')])
            def rows(self,sql,args):return [dict(x) for x in self.db.execute(sql,args)]
        s=Names()
        def state(field,value,quote,kind=None):
            out=prior(h.search([h.f(field,'equals',value)]))
            out['tasks'][0]['filters'][0]['source']={'quote':quote}
            if kind:out['tasks'][0]['filters'][0]['source']['kind']=kind
            return out
        try:
            short=state('name','测点7','查测点71')
            fixed=ground_identifiers(s,short,['t1'])
            self.assertEqual(fixed['tasks'][0]['filters'][0]['value'],'测点71')
            self.assertEqual(short['tasks'][0]['filters'][0]['value'],'测点7')
            both=ground_identifiers(s,state('name','测点7','查测点7和测点71'),['t1'])
            self.assertEqual(both['tasks'][0]['filters'][0]['value'],'测点7')
            with self.assertRaises(RequestInvalid):ground_identifiers(s,state('code','C7','查C7-extra'),['t1'])
            receipt=ground_identifiers(s,state('code','C7','它的读数','executed_receipt'),['t1'])
            self.assertEqual(receipt['tasks'][0]['filters'][0]['value'],'C7')
        finally:s.db.close()
    def test_catalog_includes_temperature_unit_and_marks_large_samples_incomplete(self):
        import sqlite3
        from request_checklist import business_catalog
        class CatalogStore:
            def __init__(self):
                self.db=sqlite3.connect(':memory:');self.db.row_factory=sqlite3.Row
                self.db.execute('create table points(system text,status text,switch text,unit text)')
            def rows(self,sql,args):return [dict(x) for x in self.db.execute(sql,args)]
        s=CatalogStore()
        try:
            s.db.executemany('insert into points values(?,?,?,?)',[('s','未报警','开启',str(i)) for i in range(45)]+[('s','未报警','开启','℃')])
            c=business_catalog(s);self.assertEqual(len(c['point_categories']['unit']),46);self.assertIn('℃',c['point_categories']['unit']);self.assertTrue(c['category_coverage']['unit']['complete'])
            s.db.executemany('insert into points values(?,?,?,?)',[('s','未报警','开启','U'+str(i)) for i in range(130)])
            c=business_catalog(s);self.assertEqual(len(c['point_categories']['unit']),128);self.assertFalse(c['category_coverage']['unit']['complete'])
        finally:s.db.close()
    def test_literal_linking_excludes_fragments_but_preserves_cross_tree_identity(self):
        import sqlite3
        from request_checklist import literal_references
        class RefStore:
            def __init__(self):
                self.db=sqlite3.connect(':memory:');self.db.row_factory=sqlite3.Row
                self.db.execute('create table points(name text,code text)');self.db.execute('create table objects(name text,code text,tree text)')
                self.db.executemany('insert into objects values(?,?,?)',[('equipment','MOHB01','config'),('class','MOHB01','equipment_class'),('fragment','M','part_class'),('digit','1','part_class'),('suffix','B','part_class'),('设备类描述1860','1860','equipment_class')])
            def rows(self,sql,args):return [dict(x) for x in self.db.execute(sql,args)]
        s=RefStore()
        try:
            refs=literal_references('看MOHB01和设备类描述1860，还有MOHB01-extra',s)
            self.assertEqual({(x['domain'],x['field'],x['value']) for x in refs},{('config','code','MOHB01'),('equipment_class','code','MOHB01'),('equipment_class','name','设备类描述1860')})
            refs=literal_references('设备类描述1860和1860，另查M',s)
            self.assertIn(('code','1860'),{(x['field'],x['value']) for x in refs});self.assertIn(('code','M'),{(x['field'],x['value']) for x in refs})
            self.assertEqual(literal_references('MOHB01-extra',s),[])
        finally:s.db.close()
    def test_endpoint_review_cannot_change_values_fields_or_merge_requests(self):
        from endpoint_review import prepare,select
        from request_checklist import reconcile,request_view
        q='range from7 through9'
        a=prior(h.search([h.f('value','gte','7'),h.f('value','lte','9')]))
        b=prior(h.search([h.f('value','gt','7'),h.f('value','lt','9')]))
        for state in (a,b):
            for f in state['tasks'][0]['filters']:f['source']={'quote':q}
        def build(a,b):return prepare(q,reconcile(a,['t1'],b,['t1'],None),{'candidate':request_view(a,['t1']),'independent':request_view(b,['t1'])})
        prepared=build(a,b);self.assertEqual(len(prepared['boundaries']),2)
        def answer(values):return {'decisions':[{'id':i+1,'included':v,'source':q} for i,v in enumerate(values)]}
        self.assertEqual(select(prepared,answer([True,True]),q),'candidate')
        self.assertEqual(select(prepared,answer([False,False]),q),'independent')
        self.assertEqual(select(prepared,answer([True,False]),q),'clarify')
        self.assertEqual(select(prepared,answer([None,False]),q),'clarify')
        with self.assertRaises(RequestInvalid):select(prepared,answer([True]),q)
        with self.assertRaises(RequestInvalid):select(prepared,answer([1,False]),q)
        for field,value in [('value','8'),('operator','eq_num'),('field','rate')]:
            bad=copy.deepcopy(b);bad['tasks'][0]['filters'][0][field]=value;self.assertIsNone(build(a,bad))
        bad=copy.deepcopy(b);bad['tasks'][0]['properties']=['unit'];self.assertIsNone(build(a,bad))
    def test_endpoint_only_disagreement_uses_fact_review_without_whole_request_vote(self):
        from request_checklist import gate
        q='below9';a=prior(h.search([h.f('value','lte','9')]))
        a['tasks'][0]['filters'][0]['source']={'quote':q}
        answer=checklist(q,[(h.f('value','lt','9'),q)])
        with patch.dict('os.environ',{'ICCM_ENDPOINT_REVIEW':'1'}),patch('request_checklist.extract',return_value=(answer,{})),patch('endpoint_review.adjudicate',return_value={'choice':'independent','reason':'exclusive'}) as endpoint,patch('request_checklist.adjudicate') as whole:
            out=gate(q,None,a,['t1'],'new',None)
        endpoint.assert_called_once();whole.assert_not_called();self.assertEqual(out['plan']['query']['filters'],[h.f('value','lt','9')])
        self.assertEqual(out['decision'],'accept')
    def test_source_ids_restore_exact_text_and_reject_fabricated_evidence(self):
        from business_request import apply_delta,resolve_delta_sources
        q='超过5，低于9。'
        d={'version':2,'mode':'new','tasks':[{'base':None,'spans':[1,2],'set':{'operation':'search','target':'points'},'filters':[{'action':'add','ids':[],'conditions':[h.f('value','gt','5')],'spans':[1]},{'action':'add','ids':[],'conditions':[h.f('value','lt','9')],'spans':[2]}]}]}
        d['tasks'][0]['unit']={'state':'none','value':''}
        p,state,ids=apply_delta(d,None,q)
        self.assertEqual(state['tasks'][0]['filters'][1]['source']['quote'],'低于9。')
        self.assertEqual(d['version'],2);self.assertNotIn('quote',d['tasks'][0])
        for spans in ([],[0],[3],[True],[1,1]):
            bad=copy.deepcopy(d);bad['tasks'][0]['filters'][0]['spans']=spans
            with self.assertRaises(RequestInvalid):apply_delta(bad,None,q)
        bad=copy.deepcopy(d);bad['tasks'][0]['quote']='伪造原文'
        with self.assertRaises(RequestInvalid):resolve_delta_sources(bad,q)
    def setUp(self):clear_verification();self.store=Store()
    def tearDown(self):
        from request_checklist import discard_extraction
        discard_extraction()
    def test_parallel_extraction_reads_only_pre_turn_evidence_and_is_consumed_once(self):
        from request_checklist import prefetch,gate,business_catalog
        q='above7';state=prior(h.search([h.f('value','gt','7')]))
        answer=checklist(q,[(h.f('value','gt','7'),q)])
        metadata={'business_catalog':business_catalog(),'literal_references':[]}
        with patch('request_checklist.extract',return_value=(answer,{})) as extract:
            prefetch(q,None,metadata,None)
            out=gate(q,None,state,['t1'],'new',None)
            self.assertEqual(extract.call_count,1);self.assertTrue(out['extraction']['prefetched'])
            self.assertEqual(extract.call_args.args[0],q)
            self.assertIsNone(extract.call_args.args[1]);self.assertNotIn('candidate',extract.call_args.kwargs)
            gate(q,None,state,['t1'],'new',None);self.assertEqual(extract.call_count,2)
    def test_unit_concept_normalization_does_not_guess_bare_or_conflicting_scales(self):
        from typed_fields import canonical_unit
        from business_request import apply_delta,RequestAmbiguous
        self.assertEqual(canonical_unit('摄氏温标'),'℃')
        self.assertEqual(canonical_unit('华氏温度'),'℉')
        self.assertEqual(canonical_unit('摄氏/华氏'),'摄氏/华氏')
        self.assertEqual(canonical_unit('度'),'度')
        q='摄氏温标，超过12';p=plan([h.f('unit','equals','℃'),h.f('value','gt','12')])
        out,_,_,_=adapt(p,q,None,'new',self.store)
        self.assertEqual(out['query'],p['query'])
    def test_bounded_repair_can_only_fill_an_inactive_null_union_member(self):
        from business_request import unpack_route
        request={'version':1,'mode':'new','tasks':[]}
        out=unpack_route({'business_request':request},normalize_inactive=True)
        self.assertEqual(out['business_request'],request)
        for invalid in ({},{'business_request':None},{'business_request':request,'legacy':{}},{'business_request':request,'extra':None}):
            with self.assertRaises(RequestInvalid):unpack_route(invalid,normalize_inactive=True)
    def test_adjudicator_receives_computed_boundary_facts_not_just_operator_names(self):
        from request_checklist import adjudicate,request_view
        from unittest.mock import MagicMock
        a=prior(h.search([h.f('value','gte','50'),h.f('value','lte','80')]))
        b=prior(h.search([h.f('value','gte','50'),h.f('value','lt','80')]))
        response=MagicMock();response.__enter__.return_value.read.return_value=json.dumps({'choices':[{'finish_reason':'stop','message':{'content':json.dumps({'choice':'independent','spans':[1],'reason':'strict upper endpoint'})}}]}).encode()
        with patch('urllib.request.build_opener') as net:
            net.return_value.open.return_value=response
            adjudicate('at least50 below80',None,{'candidate':request_view(a,['t1']),'independent':request_view(b,['t1'])},'new','new','mock')
            payload=json.loads(json.loads(net.return_value.open.call_args.args[0].data)['messages'][1]['content'])
        self.assertEqual(payload['computed_semantics']['candidate'][0]['intervals'][0]['included_boundary_count'],2)
        self.assertEqual(payload['computed_semantics']['independent'][0]['intervals'][0]['included_boundary_count'],1)
    def test_proof_required_and_bound_to_request_plan_dataset_and_single_use(self):
        p=plan([h.f('value','gt','7')]);q='above7'
        with self.assertRaises(RequestInvalid):require_verified(self.store,q,p)
        seal(self.store,q,p)
        changed=copy.deepcopy(p);changed['query']['filters'][0]['value']='9'
        with self.assertRaises(RequestInvalid):require_verified(self.store,q,changed)
        with self.assertRaises(RequestInvalid):require_verified(self.store,'other',p)
        self.store.version='v2'
        with self.assertRaises(RequestInvalid):require_verified(self.store,q,p)
        self.store.version='v1';require_verified(self.store,q,copy.deepcopy(p))
        with self.assertRaises(RequestInvalid):require_verified(self.store,q,p)
    def test_ordinary_capability_does_not_depend_on_engine(self):
        self.assertTrue(ordinary(plan([])))
        self.assertTrue(ordinary(plan([h.f('name','equals','Point1')],'attributes',['value'])))
        p=plan([]);p['query']['equipment_class']={};self.assertFalse(ordinary(p))
    def test_equal_single_task_future_state_does_not_require_free_text_adjudication(self):
        from request_checklist import gate
        q='above7';state=prior(h.search([h.f('value','gt','7')]))
        answer=checklist(q,[(h.f('value','gt','7'),q)])
        with patch('request_checklist.extract',return_value=(answer,{})),patch('request_checklist.adjudicate') as judge:
            out=gate(q,state,state,['t1'],'update',None)
        judge.assert_not_called();self.assertEqual(out['decision'],'accept')
        old=copy.deepcopy(state);old['tasks'].append({**copy.deepcopy(old['tasks'][0]),'id':'t2'})
        with patch('request_checklist.extract',return_value=(answer,{})),patch('request_checklist.adjudicate',return_value={'choice':'clarify','reason':'would remove another task','spans':[1]}) as judge:
            out=gate(q,old,old,['t1'],'update',None)
        judge.assert_not_called();self.assertEqual(out['decision'],'clarify');self.assertIn('新查询',out['reason']);self.assertIn('后续对话',out['semantic_review']['state_warning'])
    def test_adapter_cannot_invent_literal_identity(self):
        with self.assertRaises(RequestInvalid):adapt(plan([h.f('name','equals','Point3')]),'read Point2',None,'new',self.store)
    def test_prior_literal_can_ground_short_reply_but_not_unrelated_tree(self):
        refs={'references':[{'value':'Name9','field':'name','domain':'pbs','kind':'history_literal','quote':'介绍Name9'}]}
        p=plan([h.f('name','equals','Name9')]);p['query']['target']='pbs'
        _,state,_,_=adapt(p,'PBS',None,'new',self.store,refs)
        self.assertEqual(state['tasks'][0]['filters'][0]['source']['kind'],'history_literal')
        p['query']['target']='points'
        with self.assertRaises(RequestInvalid):adapt(p,'PBS',None,'new',self.store,refs)
    def test_model_catalog_and_executor_share_exact_filter_capabilities(self):
        from query_filters import filter_fields,validate_query
        from request_checklist import business_catalog
        catalog=business_catalog()
        for target,key in [('points','point_conditions'),('objects','object_conditions')]:
            self.assertEqual(catalog[key],filter_fields(target));self.assertIn('identity',catalog[key])
            for field in catalog[key]:validate_query({'target':target,'filters':[h.f(field,'equals','1')]})
    def test_adapter_preserves_untouched_filter_ids_and_removes_only_explicit_plan_changes(self):
        old=prior(h.search([h.f('source','equals','Plant3'),h.f('value','gt','7')]))
        p=plan([h.f('source','equals','Plant3'),h.f('value','gt','8')])
        out,state,ids,d=adapt(p,'lower above8',old,'update',self.store)
        self.assertEqual(out['query'],p['query']);self.assertEqual(ids,['t1'])
        self.assertEqual(state['tasks'][0]['filters'][0]['source'],old['tasks'][0]['filters'][0]['source'])
        self.assertEqual(len(d['tasks'][0]['filters']),1)
    def test_ambiguous_old_task_mapping_never_chooses_arbitrary_branch(self):
        old=prior(h.search([]));old['tasks'].append({**copy.deepcopy(old['tasks'][0]),'id':'t2'})
        with self.assertRaises(RequestInvalid):adapt(plan([]),'modify one',old,'update',self.store)
    def test_legacy_ordinary_must_reach_independent_gate_and_commit_typed_request(self):
        q='above7';p=plan([h.f('value','gt','7')]);trace={'engine':'legacy'}
        with patch('request_checklist.gate',return_value={'decision':'accept','choice':'candidate'}) as gate:
            out=migrate(self.store,q,p,trace)
        gate.assert_called_once();self.assertEqual(out['query'],p['query'])
        self.assertEqual(trace['engine'],'business_request');self.assertEqual(trace['original_engine'],'legacy')
        self.assertTrue(trace['business_request_state'])
    def test_mixed_batch_cannot_hide_ordinary_query(self):
        special={'operation':'count','entity':{'tree':'config','code':'C'},'scope':'all'}
        p={'operation':'batch','tasks':[{'question':'q','intent':plan([])},{'question':'count','intent':special}]}
        with patch('request_checklist.gate') as gate:out=migrate(self.store,'q; count',p,{})
        gate.assert_not_called();self.assertEqual(out['operation'],'clarify')
        self.assertNotIn('tasks',out)  # 不能执行任何未经核验的其他子任务。
        self.assertEqual(p['tasks'][1]['intent'],special);self.assertEqual(p['tasks'][0]['intent']['operation'],'search')
    def test_category_partial_negation_invalid_candidate_cannot_be_selected(self):
        q='未报警';bad=prior(h.search([h.f('status','not_contains','报警')]))
        answer=checklist(q,[(h.f('status','equals','未报警'),q)])
        from request_checklist import gate
        with patch('request_checklist.extract',return_value=(answer,{})),patch('request_checklist.adjudicate') as judge:
            out=gate(q,None,bad,['t1'],'new',self.store)
        judge.assert_not_called();self.assertEqual(out['choice'],'independent')
        self.assertEqual(out['plan']['query']['filters'],[h.f('status','equals','未报警')])
    def test_explicit_quoted_literal_category_matching_stays_supported(self):
        s=prior(h.search([h.f('status','not_contains','报警')]))
        s['tasks'][0]['filters'][0]['source']={'quote':'不包含“报警”这两个字'}
        validate_categories(s,['t1'],self.store)

from test_filters import FilterHttpTests

class GatewayHttpTests(FilterHttpTests):
    def test_unverified_model_plan_never_reaches_executor(self):
        import urllib.error
        p=plan([h.f('value','gt','7')])
        with patch.object(self.app,'interpret',return_value=p),patch('model.bind_references',return_value=p),patch.object(self.app,'execute_plan') as execute:
            with self.assertRaises(urllib.error.HTTPError) as caught:self.request('/api/query',{'session':'guard-missing','question':'above7'})
            body=json.load(caught.exception)
            self.assertEqual(caught.exception.code,400);self.assertIn('未经过',body['error']);execute.assert_not_called()
    def test_plan_changed_after_gate_never_reaches_executor(self):
        import urllib.error
        p=plan([h.f('value','gt','7')])
        def corrupt(store,question,proposal,context):
            seal(store,question,proposal);out=copy.deepcopy(proposal);out['query']['filters'][0]['value']='9';return out
        with patch.object(self.app,'interpret',return_value=p),patch('model.bind_references',side_effect=corrupt),patch.object(self.app,'execute_plan') as execute:
            with self.assertRaises(urllib.error.HTTPError) as caught:self.request('/api/query',{'session':'guard-changed','question':'above7'})
            self.assertEqual(caught.exception.code,400);execute.assert_not_called()

if __name__=='__main__':unittest.main()
