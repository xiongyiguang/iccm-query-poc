"""话语动作证据与不可变保留动作遵循不同契约。"""
import copy,json,sys,unittest
from pathlib import Path
from unittest.mock import patch,MagicMock
from concurrent.futures import Future
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from business_request import apply_delta,RequestInvalid,resolve_delta_sources,execution_quotes,compile_selected
from request_checklist import compile_checklist,to_delta
from data import Store
from query_plan import execute_plan
from request_gateway import reference_context
import request_checklist,model

Q='已知测量点名称61的时间异常。请读取它的测量值。第二项原样保留。'
ROLES={'background':[1],'request':[2],'context':[3]}
def request():
    return {'base':None,'action':'request','request_spans':[2],'spans':[1,2],
        'set':{'operation':'attributes','target':'points','properties':['value']},
        'filters':[{'action':'add','ids':[],'conditions':[{'field':'name','operator':'equals','value':'测量点名称61'}],'spans':[1]}]}
def wire(tasks=None,mode='new',roles=None):return {'version':5,'mode':mode,'roles':copy.deepcopy(roles or ROLES),'tasks':copy.deepcopy(tasks if tasks is not None else [request()])}
def checklist():
    return {'version':7,'status':'ready','mode':'new','roles':copy.deepcopy(ROLES),'clarification':'','tasks':[
        {'id':None,'action':'request','request_spans':[2],'spans':[1,2],'kind':'query','target':'points','properties':['value'],
         'unit':{'state':'none','value':''},'conditions':[{'field':'name','operator':'equals','value':'测量点名称61','spans':[1],'reference':None}]}]}

class RequestActionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.store=Store()
    @classmethod
    def tearDownClass(cls):cls.store.db.close()
    def old(self):
        a=request();b=copy.deepcopy(a);b['filters'][0]['conditions'][0]['value']='测量点名称62';b['spans']=[1,2]
        q='已知测量点名称61和测量点名称62。请读取它们的测量值。两项都查询。'
        return apply_delta(wire([a,b]),None,q)[1]
    def test_background_can_locate_but_cannot_authorize_reading(self):
        plan,state,ids=apply_delta(wire(),None,Q)
        self.assertEqual(plan['properties'],['value']);self.assertEqual(ids,['t1'])
        self.assertEqual(state['tasks'][0]['sources']['request']['quote'],'请读取它的测量值。')
        self.assertEqual(state['tasks'][0]['filters'][0]['source']['quote'],'已知测量点名称61的时间异常。')
        d=wire();d['tasks'][0]['request_spans']=[1]
        with self.assertRaises(RequestInvalid):apply_delta(d,None,Q)
    def test_roles_are_complete_unique_and_real(self):
        for roles in ({'background':[1],'request':[2],'context':[]},{'background':[1],'request':[1,2],'context':[3]},
                      {'background':[1],'request':[2],'context':[4]},{'background':[True],'request':[2],'context':[3]}):
            with self.subTest(roles=roles),self.assertRaises(RequestInvalid):apply_delta(wire(roles=roles),None,Q)
    def test_no_request_can_be_silently_omitted(self):
        d=wire(roles={'background':[1],'request':[2,3],'context':[]})
        with self.assertRaises(RequestInvalid):apply_delta(d,None,Q)
        d=wire();d['tasks'][0]['spans']=[1]
        with self.assertRaises(RequestInvalid):apply_delta(d,None,Q)
    def test_new_request_cannot_supply_competing_execution_or_rewrite_evidence(self):
        for key,value in [('execute',False),('quote',Q),('request_quote','invented')]:
            d=wire();d['tasks'][0][key]=value
            with self.subTest(key=key),self.assertRaises(RequestInvalid):apply_delta(d,None,Q)
    def test_retain_is_only_existing_id_and_action(self):
        old=self.old();a=request();a.update(base='t1',set={'properties':['unit']},filters=[])
        for extra in ({'set':{}},{'topics':['quality']},{'execute':False},{'spans':[]},{'conditions':[]}):
            d=wire([a,{'base':'t2','action':'retain',**extra}],'update')
            with self.subTest(extra=extra),self.assertRaises(RequestInvalid):apply_delta(d,old,Q)
        for bad in ('absent',None,'t1'):
            with self.subTest(base=bad),self.assertRaises(RequestInvalid):apply_delta(wire([a,{'base':bad,'action':'retain'}],'update'),old,Q)
    def test_retain_in_either_order_keeps_exact_prior_and_quote_mapping(self):
        old=self.old();before=copy.deepcopy(old);a=request();a.update(base='t1',set={'properties':['unit']},filters=[])
        for tasks in ([a,{'base':'t2','action':'retain'}],[{'base':'t2','action':'retain'},a]):
            d=resolve_delta_sources(wire(tasks,'update'),Q);plan,state,ids=apply_delta(d,old,Q)
            self.assertEqual(state['tasks'][1],before['tasks'][1]);self.assertEqual(ids,['t1'])
            self.assertEqual(plan,compile_selected(state,ids,execution_quotes(d)))
        self.assertEqual(old,before)
    def test_all_retained_needs_no_new_evidence_and_no_sql(self):
        old=self.old();q='先原样保留两项。'
        plan,state,ids=apply_delta(wire([{'base':'t2','action':'retain'},{'base':'t1','action':'retain'}],'update',{'background':[],'request':[],'context':[1]}),old,q)
        self.assertEqual(ids,[]);self.assertEqual(state['tasks'],old['tasks'])
        with patch.object(self.store,'rows',side_effect=AssertionError('no SQL')):result=execute_plan(self.store,plan)
        self.assertEqual(result['status'],'conversation')
    def test_query_to_explanation_is_delivery_without_sql(self):
        old=self.old();q='第一项不再读取。改为解释报警阈值。第二项原样保留。'
        a={'base':'t1','action':'request','request_spans':[2],'spans':[1,2],'replace_task':True,'retain_filters':[],
           'set':{'operation':'explain','topics':['alarm']},'filters':[]}
        d=wire([a,{'base':'t2','action':'retain'}],'update',{'background':[],'request':[2],'context':[1,3]})
        plan,state,ids=apply_delta(d,old,q);self.assertEqual(ids,['t1']);self.assertEqual(state['tasks'][0]['filters'],[])
        with patch.object(self.store,'rows',side_effect=AssertionError('no SQL')):result=execute_plan(self.store,plan)
        self.assertEqual(result['status'],'conversation');self.assertEqual(state['tasks'][1],old['tasks'][1])
    def test_independent_request_retention_matches_primary(self):
        old=self.old();a=request();a.update(base='t1',set={'properties':['unit']},filters=[])
        p1,s1,ids=apply_delta(wire([a,{'base':'t2','action':'retain'}],'update'),old,Q)
        c=checklist();c['mode']='update';c['tasks'][0].update(id='t1',properties=['unit']);c['tasks'][0]['conditions'][0]['spans']=[]
        c['tasks'].append({'id':'t2','action':'retain'})
        p2,s2,ids2,_=compile_checklist(c,old,Q,self.store)
        self.assertEqual(p1,p2);self.assertEqual(ids,ids2);self.assertEqual(s1['tasks'][1],s2['tasks'][1])
        self.assertEqual(s2['tasks'][0]['sources']['request']['quote'],'请读取它的测量值。')
    def test_independent_retain_cannot_smuggle_fields(self):
        c=checklist();c['mode']='update';c['tasks'][0]['id']='t1';c['tasks'].append({'id':'t2','action':'retain','topics':['quality']})
        with self.assertRaises(RequestInvalid):to_delta(c,self.old(),Q)
    def test_old_protocol_remains_compatible(self):
        d=wire();d.pop('roles');d['version']=4;t=d['tasks'][0];t.pop('action');t.pop('request_spans');t['execute']=True
        self.assertEqual(apply_delta(d,None,Q)[0]['properties'],['value'])
    def test_explicit_output_control_protocol_compiles_same_semantics(self):
        d=wire();d['version']=6;d['roles']={'background':[1],'output':[2],'control':[3]}
        c=checklist();c['version']=8;c['roles']=copy.deepcopy(d['roles'])
        a=apply_delta(d,None,Q);b=compile_checklist(c,None,Q,self.store)
        self.assertEqual(a[0],b[0]);self.assertEqual(a[2],b[2])
        d['roles']['output']=[1];d['roles']['background']=[2]
        with self.assertRaises(RequestInvalid):apply_delta(d,None,Q)
    def test_current_literal_cross_clause_binding_has_real_source(self):
        d=wire();d['tasks'][0]['spans']=[2];d['tasks'][0]['filters'][0]['spans']=[2]
        refs=reference_context({},None,self.store,Q)
        plan,state,_=apply_delta(d,None,Q,refs)
        f=state['tasks'][0]['filters'][0]
        self.assertEqual(f['source']['kind'],'current_literal')
        self.assertEqual(f['source']['quote'],'测量点名称61')
        self.assertEqual(plan['query']['target'],'points')
        d['tasks'][0]['filters'][0]['conditions'][0]['value']='测量点名称6'
        with self.assertRaises(RequestInvalid):apply_delta(d,None,Q,refs)
    def test_current_literal_cannot_change_domain_or_invent_offsets(self):
        d=wire();d['tasks'][0]['spans']=[2];d['tasks'][0]['filters'][0]['spans']=[2];d['tasks'][0]['set']['target']='config'
        refs=reference_context({},None,self.store,Q)
        with self.assertRaises(RequestInvalid):apply_delta(d,None,Q,refs)
        refs=reference_context({},None,self.store,Q,[{'domain':'points','field':'name','value':'测量点名称61','start':0,'end':1}])
        self.assertEqual(refs['references'],[])
    def test_prefetched_capability_is_scoped_and_not_consumed(self):
        future=Future();trace={};future.set_result(({'status':'ready'},trace));key=request_checklist.extraction_key(Q,None,None)
        with patch.object(request_checklist._ASYNC,'pending',(key,future),create=True):
            self.assertFalse(request_checklist.prefetched_ready(Q+'new',None,None))
            self.assertTrue(request_checklist.prefetched_ready(Q,None,None))
            self.assertIs(request_checklist._ASYNC.pending[1],future)
        self.assertTrue(trace['capability_checked_at_route'])
    def test_default_route_does_not_treat_ready_as_capability_proof(self):
        slots={'needs_history':False,'identifier_field':'code','resolved_question':None,'domain':'config',
               'thresholds':None,'comparisons':[],'unit':{'state':'none','value':''},'reference':'MOHB01',
               'projection':'specified','scope':'all','properties':[],'context_mode':'new','request_kind':'other'}
        intent={'operation':'parts','entity':{'tree':'config','code':'MOHB01'},'scope':'all','clarification':''}
        def response(value):
            r=MagicMock();r.__enter__.return_value.read.return_value=json.dumps({'choices':[{'finish_reason':'stop','message':{'content':json.dumps(value)}}]}).encode();return r
        for override in ({},{'ICCM_TYPED_ENTRY_RETRY':'0'}):
            with self.subTest(override=override),patch.dict(model.os.environ,{'DEEPSEEK_API_KEY':'test-only','ICCM_REQUEST_ENGINE':'contract',**override},clear=True),patch('request_checklist.prefetch'),patch('request_checklist.prefetched_ready',return_value=True) as readiness,patch.object(model.urllib.request,'build_opener') as factory:
                factory.return_value.open.side_effect=[response({'business_request':None,'legacy':slots}),response(intent)]
                plan=model.interpret('构型MOHB01的全部下级部件',{},None,self.store)
                self.assertEqual(plan,intent);readiness.assert_not_called()
                self.assertNotIn('typed_entry_retry',model.get_trace()['context_route'])
    def test_legacy_entry_retries_typed_request_without_sharing_independent_plan(self):
        from business_request import unpack_route
        q='请判断设备有无故障。'
        typed={'business_request':{'version':10,'mode':'new','roles':{'background':[],'output':[1],'control':[]},'tasks':[
            {'base':None,'action':'request','request_spans':[1],'spans':[1],'set':{'operation':'unsupported','topics':['limits']},'filters':[]}]},'legacy':None}
        slots=unpack_route(typed);slots.pop('business_request');legacy={'business_request':None,'legacy':slots}
        def response(value):
            r=MagicMock();r.__enter__.return_value.read.return_value=json.dumps({'choices':[{'finish_reason':'stop','message':{'content':json.dumps(value)}}]}).encode();return r
        with patch.dict(model.os.environ,{'DEEPSEEK_API_KEY':'test-only','ICCM_REQUEST_ENGINE':'contract','ICCM_TYPED_ENTRY_RETRY':'1'}),patch('request_checklist.prefetch'),patch('request_checklist.prefetched_ready',return_value=True),patch.object(model.urllib.request,'build_opener') as factory:
            factory.return_value.open.side_effect=[response(legacy),response(typed)]
            plan=model.interpret(q,{},None,self.store)
            self.assertEqual(factory.return_value.open.call_count,2);self.assertEqual(plan['operation'],'conversation')
            self.assertTrue(model.get_trace()['context_route']['typed_entry_retry'])
            with patch('request_checklist.gate',return_value={'decision':'accept','choice':'candidate'}) as gate:
                final=model.bind_references(self.store,q,plan,{})
            gate.assert_called_once();self.assertEqual(final,plan)
            body=json.loads(factory.return_value.open.call_args.args[0].data)
            self.assertNotIn('independent',body['messages'][-1]['content'])
        with patch.dict(model.os.environ,{'DEEPSEEK_API_KEY':'test-only','ICCM_REQUEST_ENGINE':'contract','ICCM_TYPED_ENTRY_RETRY':'1'}),patch('request_checklist.prefetch'),patch('request_checklist.prefetched_ready',return_value=True),patch.object(model.urllib.request,'build_opener') as factory:
            factory.return_value.open.side_effect=[response(legacy),response(legacy)]
            with self.assertRaises(model.PlanInvalid):model.interpret(q,{},None,self.store)
            self.assertEqual(factory.return_value.open.call_count,2)

if __name__=='__main__':unittest.main()
