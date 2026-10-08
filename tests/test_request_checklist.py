import copy,json,sys,unittest
from pathlib import Path
from unittest.mock import patch,MagicMock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from request_checklist import to_delta,compile_checklist,reconcile,extract,gate,adjudicate
from business_request import RequestInvalid,RequestAmbiguous
from compare_request_checklist import prior
import replay_semantic_holdout as h

def checklist(q,conditions,id=None,mode='new',unit=None):
    return {'status':'ready','mode':mode,'clarification':'','tasks':[{'id':id,'quote':q,'operation':'search','target':'points','properties':[],
      'unit':unit or {'state':'none','value':''},'conditions':[{**f,'quote':quote} for f,quote in conditions]}]}
class ChecklistTests(unittest.TestCase):
    def test_empty_prior_continuation_compiles_same_complete_request_without_mutating_input(self):
        q='value above 5';new=checklist(q,[(h.f('value','gt','5'),q)])
        continued=copy.deepcopy(new);continued['mode']='update';original=copy.deepcopy(continued)
        self.assertEqual(to_delta(continued,None,q),to_delta(new,None,q))
        self.assertEqual(continued,original)
        from business_request import apply_delta
        self.assertEqual(apply_delta(to_delta(continued,None,q),None,q)[0]['query']['filters'],[h.f('value','gt','5')])
        for bad in (dict(continued,tasks=[dict(continued['tasks'][0],id='t1')]),):
            with self.assertRaises(RequestInvalid):to_delta(bad,None,q)
        known=prior(h.search([h.f('value','gt','7')]))
        with self.assertRaises(RequestInvalid):to_delta(continued,known,q)
        inherited=copy.deepcopy(continued);inherited['tasks'][0]['conditions'][0]['quote']=None
        with self.assertRaises(RequestInvalid):to_delta(inherited,None,q)
    def test_transition_facts_distinguish_retention_execution_and_new_group(self):
        from request_checklist import transition_facts
        from test_business_request import BusinessRequestTests
        state=BusinessRequestTests().two_object_tasks();original=copy.deepcopy(state)
        second=copy.deepcopy(state['tasks'][1]);second['target']='equipment_class'
        facts=transition_facts(state,[second],'update')
        self.assertEqual(facts['executed_task_ids'],['t2'])
        self.assertEqual(facts['preserved_without_execution'],['t1'])
        self.assertEqual(facts['state_after'][0]['target'],'config')
        self.assertEqual(facts['state_after'][1]['target'],'equipment_class')
        replay=transition_facts(state,[state['tasks'][0]],'update')
        self.assertEqual(replay['executed_task_ids'],['t1'])
        self.assertEqual(transition_facts(state,[second],'new')['preserved_without_execution'],[])
        self.assertEqual(len(transition_facts(state,[second],'new')['state_after']),1)
        self.assertEqual(state,original)
    def test_shape_repair_identifies_extra_field_without_accepting_or_removing_it(self):
        q='value above 5'
        answer=checklist(q,[(h.f('value','gt','5'),q)])
        answer['tasks'][0]['clarification']=''
        original=copy.deepcopy(answer)
        with self.assertRaisesRegex(RequestInvalid,r'checklist.tasks.*clarification'):to_delta(answer,None,q)
        self.assertEqual(answer,original)
    def test_complete_changed_domain_checklist_replaces_one_task_not_whole_group(self):
        from test_business_request import BusinessRequestTests
        from business_request import apply_delta
        state=BusinessRequestTests().two_object_tasks();q='first task use class tree and code only'
        answer=checklist(q,[(h.f('code','equals','C1'),None)],'t1','update')
        answer['tasks'][0].update(operation='attributes',target='equipment_class',properties=['code'])
        d=to_delta(answer,state,q);p,out,_=apply_delta(d,state,q)
        self.assertTrue(d['tasks'][0]['replace_task']);self.assertEqual(d['tasks'][0]['retain_filters'],['f1'])
        self.assertEqual(p['query']['target'],'equipment_class');self.assertEqual(p['properties'],['code'])
        self.assertEqual(out['tasks'][1],state['tasks'][1])
    def test_explicit_history_reference_is_not_a_prior_filter_and_is_source_bound(self):
        q='PBS'
        refs={'references':[{'id':1,'domain':'pbs','field':'name','value':'Name9','kind':'history_literal','quote':'介绍Name9'}]}
        c={'version':4,'status':'ready','mode':'new','clarification':'','tasks':[{'id':None,'spans':[1],'target':'pbs','properties':['name','code'],'unit':{'state':'none','value':''},'conditions':[{'field':'identity','operator':'equals','value':'Name9','spans':[],'reference':1}]}]}
        original=copy.deepcopy(c)
        from business_request import apply_delta
        delta=to_delta(c,None,q,refs);plan,state,_=apply_delta(delta,None,q,refs)
        self.assertEqual(plan['query']['filters'],[h.f('identity','equals','Name9')]);self.assertEqual(c,original)
        self.assertEqual(state['tasks'][0]['filters'][0]['source']['kind'],'history_literal')
        self.assertEqual(state['tasks'][0]['filters'][0]['source']['quote'],'介绍Name9')
        bads=[]
        for updates in ({'reference':2},{'reference':True},{'value':'Other'},{'operator':'contains'},{'field':'code'},{'spans':[1]},{'reference':None}):
            bad=copy.deepcopy(c);bad['tasks'][0]['conditions'][0].update(updates);bads.append(bad)
        bad=copy.deepcopy(c);bad['tasks'][0]['target']='equipment_class';bads.append(bad)
        for bad in bads:
            with self.subTest(bad=bad),self.assertRaises(RequestInvalid):to_delta(bad,None,q,refs)
    def test_v4_actual_prior_filter_keeps_its_original_evidence(self):
        prior_state=prior(h.search([h.f('value','gt','7')]))
        q='保持原条件'
        c={'version':4,'status':'ready','mode':'update','clarification':'','tasks':[{'id':'t1','spans':[1],'target':'points','properties':[],'unit':{'state':'none','value':''},'conditions':[{'field':'value','operator':'gt','value':'7','spans':[],'reference':None}]}]}
        d=to_delta(c,prior_state,q,{'references':[]});self.assertEqual(d['tasks'][0]['filters'],[])
    def test_primary_missing_envelope_field_gets_one_bounded_structural_repair(self):
        import model
        q='value above 5'
        request={'version':1,'mode':'new','tasks':[{'base':None,'quote':q,'set':{'operation':'search','target':'points'},'filters':[{'action':'add','ids':[],'quote':q,'conditions':[h.f('value','gt','5')]}],'unit':{'state':'none','value':''}}]}
        def response(value):
            reply=MagicMock();reply.__enter__.return_value.read.return_value=json.dumps({'choices':[{'finish_reason':'stop','message':{'content':json.dumps(value)}}]}).encode();return reply
        with patch.dict(model.os.environ,{'DEEPSEEK_API_KEY':'test-only','ICCM_REQUEST_ENGINE':'contract'}),patch('urllib.request.build_opener') as net:
            net.return_value.open.side_effect=[response({'business_request':request}),response({'business_request':request,'legacy':None})]
            plan=model.interpret(q,{},None)
        self.assertEqual(plan['query']['filters'],[h.f('value','gt','5')])
        self.assertEqual(net.return_value.open.call_count,2)
        self.assertEqual(model.get_trace()['context_route']['repairs'],1)
    def test_unsupported_capability_cannot_be_overruled_by_a_model_vote(self):
        q='Point1 value';candidate=prior(h.attrs('Point1',['value']))
        answer={'status':'unsupported','mode':'new','tasks':[],'clarification':'uncertain reference'}
        for choice in ('candidate','independent','clarify'):
            with patch('request_checklist.extract',return_value=(answer,{})),patch('request_checklist.adjudicate',return_value={'choice':choice,'reason':'source checked','spans':[1]}) as judge:
                out=gate(q,None,candidate,['t1'],'new',None)
            judge.assert_not_called();self.assertEqual(out['decision'],'clarify')
            self.assertTrue(out['capability_rejected'])
            self.assertNotIn('plan',out);self.assertNotIn('pending_state',out)
    def test_even_plausible_candidate_cannot_waive_independent_missing_prerequisite(self):
        q='above 5 Celsius';candidate=prior(h.search([h.f('value','gt','5'),h.f('unit','equals','℃')]))
        answer=checklist(q,[(h.f('value','gt','5'),q)],unit={'state':'ambiguous','value':''})
        answer['status']='clarify'
        with patch('request_checklist.extract',return_value=(answer,{})),patch('request_checklist.adjudicate',return_value={'choice':'candidate','reason':'explicit Celsius','spans':[1]}) as judge:
            out=gate(q,None,candidate,['t1'],'new',None)
        self.assertEqual(out['decision'],'clarify');self.assertNotIn('plan',out)
        self.assertIn('pending_state',out);judge.assert_not_called()
    def test_adjudication_uses_grounded_requests_with_sources_not_equality_keys(self):
        q='Point1 value';candidate=prior(h.attrs('Point1',['value']))
        independent=copy.deepcopy(candidate);independent['tasks'][0]['properties']=['unit']
        from request_checklist import request_view,business_catalog
        view=request_view(candidate,['t1'])
        self.assertEqual(view[0]['filters'][0]['value'],'Point1')
        self.assertIn('source',view[0]['filters'][0])
        self.assertNotIn('resolved_identity',json.dumps(view))
        self.assertEqual(business_catalog()['targets']['config']['tree'],'config')
        self.assertIn('构型树',business_catalog()['targets']['config']['label'])
        self.assertEqual(business_catalog()['properties']['physical_quantity']['fields'],{})
        view[0]['filters'][0]['value']='modified'
        self.assertEqual(candidate['tasks'][0]['filters'][0]['value'],'Point1')
    def test_literal_references_keep_full_names_and_multiple_objects(self):
        import sqlite3
        from request_checklist import literal_references
        class Store:
            def __init__(self):
                self.db=sqlite3.connect(':memory:');self.db.row_factory=sqlite3.Row
                self.db.execute('create table points(name text,code text)')
                self.db.execute('create table objects(name text,code text,tree text)')
                self.db.executemany('insert into points values(?,?)',[('测量点名称7','C7'),('测量点名称71','C71'),('测量点名称19','C19')])
            def rows(self,sql,args):return [dict(r) for r in self.db.execute(sql,args)]
        s=Store()
        try:
            q='测量点名称71和测量点名称19'
            refs=literal_references(q,s)
            self.assertEqual({r['value'] for r in refs},{'测量点名称71','测量点名称19'})
            for r in refs:self.assertEqual(q[r['start']:r['end']],r['value'])
        finally:s.db.close()
    def test_independent_unit_ambiguity_preserves_its_draft_without_execution(self):
        q='under 29 degrees'
        answer=checklist(q,[(h.f('value','lt','29'),q)],unit={'state':'ambiguous','value':''})
        answer['status']='clarify'
        with patch('request_checklist.extract',return_value=(answer,{})),patch('request_checklist.adjudicate',return_value={'choice':'independent','reason':'unit unspecified','spans':[1]}) as judge:
            out=gate(q,None,prior(h.search([h.f('value','lt','29')])),['t1'],'new',None)
        self.assertEqual(out['decision'],'clarify');self.assertNotIn('plan',out)
        self.assertEqual(out['pending_state']['tasks'][0]['filters'][0]['value'],'29')
        judge.assert_not_called()
    def test_projection_is_the_single_source_of_query_form(self):
        from request_checklist import resolve_sources
        q='Point1 value';c={'version':3,'status':'ready','mode':'new','clarification':'','tasks':[{'id':None,'spans':[1],'target':'points','properties':['value'],'unit':{'state':'none','value':''},'conditions':[{'field':'identity','operator':'equals','value':'Point1','spans':[1]}]}]}
        delta=to_delta(c,None,q);self.assertEqual(delta['tasks'][0]['set']['operation'],'attributes')
        c['tasks'][0]['properties']=[];self.assertEqual(to_delta(c,None,q)['tasks'][0]['set']['operation'],'search')
        c['tasks'][0]['operation']='attributes'
        with self.assertRaises(RequestInvalid):to_delta(c,None,q)
    def test_gate_catches_omitted_condition_and_requires_visible_confirmation(self):
        q='above 7; unit provided';good=prior(h.search([h.f('value','gt','7'),h.f('unit','not_blank','')]))
        bad=copy.deepcopy(good);bad['tasks'][0]['filters'].pop()
        answer=checklist(q,[(h.f('value','gt','7'),q),(h.f('unit','not_blank',''),q)])
        with patch('request_checklist.extract',return_value=(answer,{})),patch('request_checklist.adjudicate',side_effect=AssertionError('no free override')):
            out=gate(q,None,bad,['t1'],'new',None)
        self.assertEqual(out['decision'],'clarify');self.assertEqual(out['choice'],'clarify');self.assertIn('已提供',out['reason']);self.assertIn('pending_state',out);self.assertNotIn('state',out);self.assertEqual(len(bad['tasks'][0]['filters']),1)
    def test_gate_equal_conditions_never_calls_free_text_verdict(self):
        q='above 7';state=prior(h.search([h.f('value','gt','7')]))
        answer=checklist(q,[(h.f('value','gt','7'),q)])
        with patch('request_checklist.extract',return_value=(answer,{})),patch('request_checklist.adjudicate') as adjudicator:
            out=gate(q,None,state,['t1'],'new',None)
        self.assertEqual(out['decision'],'accept');adjudicator.assert_not_called()
    def test_bad_independent_schema_or_human_clarification_cannot_execute(self):
        q='above 7';state=prior(h.search([h.f('value','gt','7')]))
        with patch('request_checklist.extract',return_value=({},{})):
            out=gate(q,None,state,['t1'],'new',None)
        self.assertEqual(out['decision'],'clarify');self.assertNotIn('plan',out)
    def test_adjudicator_cannot_return_a_new_plan(self):
        response=MagicMock();response.__enter__.return_value.read.return_value=json.dumps({'choices':[{'finish_reason':'stop','message':{'content':json.dumps({'choice':'candidate','spans':[1],'reason':'okay','plan':{}})}}]}).encode()
        with patch('urllib.request.build_opener') as net:
            net.return_value.open.return_value=response
            with self.assertRaises(RequestInvalid):adjudicate('q',None,{'candidate':[],'independent':[]},'new','new','mock')
    def test_identity_equivalence_keeps_duplicate_rows_and_object_trees(self):
        import sqlite3
        class Store:
            def __init__(self):
                self.db=sqlite3.connect(':memory:');self.db.row_factory=sqlite3.Row
                self.db.execute('create table points(line integer,code text,name text)')
                self.db.executemany('insert into points values(?,?,?)',[(1,'C','N1'),(2,'C','N2')])
            def rows(self,sql,args):return [dict(r) for r in self.db.execute(sql,args)]
        s=Store()
        try:
            a=prior(h.search([h.f('name','equals','N1')]))
            b=prior(h.search([h.f('code','equals','C')]))
            self.assertFalse(reconcile(a,['t1'],b,['t1'],s)['matches'])
        finally:s.db.close()
    def test_inherited_condition_must_exist_in_same_task(self):
        q='change lower to 8';p=prior(h.search([h.f('value','gt','5')]))
        c=checklist(q,[(h.f('unit','not_blank',''),None)],'t1','update')
        with self.assertRaises(RequestInvalid):to_delta(c,p,q)
    def test_complete_checklist_becomes_only_required_changes(self):
        q='upper 10';p=prior(h.search([h.f('source','equals','源系统1'),h.f('value','gt','5')]))
        c=checklist(q,[(h.f('source','equals','源系统1'),None),(h.f('value','gt','5'),None),(h.f('value','lt','10'),q)],'t1','update')
        d=to_delta(c,p,q);self.assertEqual(len(d['tasks'][0]['filters']),1);self.assertEqual(d['tasks'][0]['filters'][0]['action'],'add')
    def test_no_candidate_in_independent_extractor_input(self):
        response=MagicMock();response.__enter__.return_value.read.return_value=json.dumps({'model':'mock','choices':[{'finish_reason':'stop','message':{'content':json.dumps({'version':2,'status':'unsupported','mode':'new','tasks':[],'clarification':'q'}),'reasoning_content':'not retained'}}]}).encode()
        with patch('urllib.request.build_opener') as net:
            net.return_value.open.return_value=response;_,trace=extract('question',None)
            body=json.loads(net.return_value.open.call_args.args[0].data);payload=json.loads(body['messages'][1]['content'])
            self.assertEqual(set(payload),{'question','prior','segments'});self.assertNotIn('reasoning_content',str(trace))
    def test_schema_repair_has_one_attempt_and_never_sees_candidate(self):
        response=MagicMock();response.__enter__.return_value.read.return_value=json.dumps({'choices':[{'finish_reason':'stop','message':{'content':'{}'}}]}).encode()
        with patch('urllib.request.build_opener') as net:
            net.return_value.open.return_value=response
            with self.assertRaises(RequestInvalid):extract('question',None)
            self.assertEqual(net.return_value.open.call_count,2)
    def test_source_ids_resolve_to_exact_raw_span(self):
        from request_checklist import resolve_sources,source_segments
        q='至少50，但不到80；单位摄氏度。';cs=source_segments(q)
        self.assertEqual([x['id'] for x in cs],[1,2,3])
        x={'version':2,'tasks':[{'spans':[1,3],'conditions':[{'spans':[1,2]},{'spans':[]}]}]}
        out=resolve_sources(x,q);self.assertEqual(out['tasks'][0]['quote'],q);self.assertEqual(out['tasks'][0]['conditions'][0]['quote'],'至少50，但不到80；');self.assertIsNone(out['tasks'][0]['conditions'][1]['quote'])
        x['tasks'][0]['spans']=[4]
        with self.assertRaises(RequestInvalid):resolve_sources(x,q)
    def test_missing_unit_is_a_deterministic_mismatch(self):
        good=prior(h.search([h.f('value','gt','7'),h.f('unit','not_blank','')]))
        bad=copy.deepcopy(good);bad['tasks'][0]['filters'].pop()
        self.assertFalse(reconcile(bad,['t1'],good,['t1'],None)['matches'])
        self.assertTrue(reconcile(good,['t1'],good,['t1'],None)['matches'])
    def test_numeric_spellings_and_property_order_are_equivalent(self):
        a=prior(h.search([h.f('value','gt','7')]))
        b=copy.deepcopy(a);b['tasks'][0]['filters'][0]['value']='7.00'
        self.assertTrue(reconcile(a,['t1'],b,['t1'],None)['matches'])
    def test_unsupported_cannot_smuggle_tasks(self):
        c={'status':'unsupported','mode':'new','tasks':[{}],'clarification':'OR'}
        with self.assertRaises(RequestInvalid):to_delta(c,None,'OR')
    def test_sources_are_immutable_and_stale_quotes_rejected(self):
        q='new';p=prior(h.search([h.f('value','gt','5')]));before=copy.deepcopy(p)
        c=checklist(q,[(h.f('value','gt','6'),'old')],'t1','update')
        with self.assertRaises(RequestInvalid):to_delta(c,p,q)
        self.assertEqual(p,before)
