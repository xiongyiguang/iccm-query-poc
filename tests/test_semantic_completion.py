import copy,json,sys,unittest,threading,urllib.request,urllib.error
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from request_contract import validate_route,scope_context,ground_unit,ground_domain,reconcile_reference,complete_contract,enforce
from attributes import CATALOG
from data import Store
from query_plan import execute_plan

def route(**kw):
    return dict(needs_history=False,identifier_field='identity',resolved_question=None,domain=None,
                thresholds=None,comparisons=[],unit={'state':'none','value':''},reference=None,projection='specified',scope=None,**kw) if not kw else {**route(),**kw}
def plan(**kw):return {**dict(operation='attributes',entity=None,scope='direct',clarification='',properties=['name'],query={'target':'config','filters':[{'field':'identity','operator':'equals','value':'MOHB'}]}),**kw}

class CompletionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.store=Store()
    @classmethod
    def tearDownClass(cls):cls.store.db.close()
    def test_units_are_required_and_cannot_be_dropped(self):
        d=route(comparisons=[{'field':'value','operator':'gt','value':'60'}],unit={'state':'ambiguous','value':''})
        p=plan(operation='search',properties=None,query={'target':'points','filters':d['comparisons']})
        self.assertEqual(complete_contract(p,d)['operation'],'clarify')
        with self.assertRaises(ValueError):enforce(p,d)
        d['unit']={'state':'specified','value':'摄氏度'}
        fixed=complete_contract(p,d);enforce(fixed,d)
        self.assertIn({'field':'unit','operator':'equals','value':'℃'},fixed['query']['filters'])
        bad=copy.deepcopy(p);bad['query']['filters'].append({'field':'unit','operator':'equals','value':'℉'})
        with self.assertRaises(ValueError):complete_contract(bad,d)
        self.assertNotIn({'field':'unit','operator':'equals','value':'℃'},p['query']['filters'])
    def test_missing_semantic_slot_is_not_silently_accepted(self):
        d=route();d.pop('unit')
        with self.assertRaises(ValueError):validate_route(d,strict=True)
    def test_current_literal_wins_over_stale_reference_without_guessing_tree(self):
        d=route(reference='MOHB01',domain='config',needs_history=True)
        p=plan();ctx={'entity':{'tree':'config','code':'MOHB01'}}
        fixed=reconcile_reference(d,p,'MOHB 那个设备是什么？',ctx)
        self.assertEqual(fixed['reference'],'MOHB');self.assertIsNone(fixed['domain']);self.assertFalse(fixed['needs_history'])
        self.assertEqual(complete_contract(p,fixed)['query']['target'],'objects')
        self.assertEqual(reconcile_reference(d,p,'构型MOHB是什么',ctx)['domain'],'config')
        for text in ['它叫什么','构型MOHB01是什么']:
            self.assertEqual(reconcile_reference(d,p,text,ctx),d)
    def test_new_reference_domain_requires_explicit_source_label(self):
        for tree,label in [('pbs','PBS'),('config','构型'),('equipment_class','设备类'),('part_class','部件类')]:
            d=route(reference='NEW',domain=tree)
            self.assertIsNone(ground_domain(d,'NEW是什么')['domain'])
            self.assertEqual(ground_domain(d,label+' NEW是什么')['domain'],tree)
            self.assertEqual(ground_domain({**d,'needs_history':True},'它叫什么')['domain'],tree)
    def test_domain_reply_is_not_a_new_object_name(self):
        ctx={'pending_question':'介绍下原名称','pending_reference':'原名称'}
        d=route(needs_history=True,identifier_field=None,reference='PBS',domain='pbs',resolved_question='介绍PBS')
        fixed,kept,_=scope_context(d,ctx,None)
        self.assertEqual(fixed['reference'],'原名称');self.assertIsNone(fixed['resolved_question']);self.assertEqual(kept,ctx)
        explicit,_,_=scope_context({**d,'identifier_field':'name'},ctx,None)
        self.assertEqual(explicit['reference'],'PBS');self.assertFalse(explicit['needs_history'])
    def test_unit_normalization_has_literal_provenance(self):
        d=route(unit={'state':'specified','value':'℃'})
        self.assertEqual(ground_unit(d,'超过60度',{})['unit']['state'],'ambiguous')
        for text in ['超过60摄氏度','大于60℃','超过60°C']:
            self.assertEqual(ground_unit(d,text,{})['unit']['state'],'specified')
        old={'dialogue':[{'question':'单位是摄氏度','answer':'摄氏度'}]}
        self.assertEqual(ground_unit(d,'超过60度',old)['unit']['state'],'ambiguous')
        self.assertEqual(ground_unit({**d,'needs_history':True},'改成超过60度',old)['unit']['state'],'specified')
        d=route(unit={'state':'ambiguous','value':''})
        p=plan(query={'target':'points','filters':[{'field':'code','operator':'equals','value':'P'}]},properties=['value','unit'])
        self.assertEqual(complete_contract(p,d),p);enforce(p,d)
    def test_candidate_reference_keeps_only_matching_pending_scope(self):
        ctx={'pending_request':plan(), 'outcome':{'candidates':[{'tree':'config','code':'MOHB'},{'tree':'equipment_class','code':'MOHB'}]}}
        d,c,_=scope_context(route(needs_history=True,reference='MOHB',domain='equipment_class'),ctx,None)
        self.assertEqual(c,ctx);self.assertTrue(d['needs_history'])
        ctx['pending_question']='MOHB是什么'
        d,c,_=scope_context(route(needs_history=True,reference='设备类描述1860',domain='equipment_class'),ctx,None)
        self.assertFalse(d['needs_history']);self.assertEqual(c,{})
    def test_new_reference_drops_old_domain_but_same_reference_preserves(self):
        context={'entity':{'tree':'config','code':'MOHB01'},'operation':'attributes'}
        d,c,s=scope_context(route(needs_history=True,reference='MOHB',resolved_question='旧问题'),context,None)
        self.assertFalse(d['needs_history']);self.assertEqual(c,{});self.assertIsNone(d['resolved_question'])
        fixed=complete_contract(plan(),d,c,s);self.assertEqual(fixed['query']['target'],'objects')
        for domain in ['pbs','config','equipment_class','part_class']:
            ctx={'entity':{'tree':domain,'code':'SAME'}}
            d,c,_=scope_context(route(needs_history=True,reference='SAME'),ctx,None)
            self.assertEqual(c,ctx);self.assertTrue(d['needs_history'])
    def test_pending_clarification_preserves_original_and_explicit_domain(self):
        context={'pending_question':'MOHB01下面多少东西','pending_reference':'MOHB01'}
        d,c,_=scope_context(route(needs_history=True,reference='MOHB01',domain='config',scope='all',resolved_question='完整请求'),context,None)
        self.assertEqual(c,context)
        p=plan(operation='search',properties=None,entity={'tree':'config','code':'MOHB01'},query={'target':'objects','filters':[]})
        fixed=complete_contract(p,d);self.assertEqual(fixed['query']['target'],'config');self.assertEqual(fixed['scope'],'all')
        result=execute_plan(self.store,fixed)
        # 直接遍历原始对象记录的父链，独立计算预期。
        parents={r['code']:r['parent'] for r in self.store.rows("SELECT code,parent FROM objects WHERE tree='config'")};expected=[]
        for key in parents:
            cur=parents[key];seen=set()
            while cur in parents and cur not in seen:
                if cur=='MOHB01':expected.append(key);break
                seen.add(cur);cur=parents[cur]
        self.assertEqual({r['code'] for r in result['records']},set(expected))
    def test_all_properties_expanded_after_resolution_and_evidence_complete(self):
        p=plan(properties=['name'],query={'target':'points','filters':[{'field':'code','operator':'equals','value':'XJ1ABC001PO.JVD.1ABC029MV.LBe_Y'}]})
        fixed=complete_contract(p,route(projection='all',domain='points'));self.assertEqual(fixed['properties'],['*'])
        r=execute_plan(self.store,fixed);attrs={x['property']:x for x in r['attributes']}
        required={k for k,v in CATALOG.items() if 'points' in v['fields']}
        self.assertTrue(required<=set(attrs));self.assertGreater(len(attrs),12)
        self.assertEqual(attrs['rate']['display_value'],'-0.000000000405')
        self.assertEqual(set(r['coverage']['requested']),set(attrs))
        for a in attrs.values():
            if a['status']=='known':self.assertTrue(all(e['fields'][a['field']]==a['value'] for e in a['evidence']))
    def test_explicit_projection_over_twelve_and_duplicate_rejection(self):
        from attributes import validate_properties
        validate_properties(plan(properties=list(CATALOG)))
        for props in [['*','name'],['name','name'],['unknown']]:
            with self.assertRaises(ValueError):validate_properties(plan(properties=props))
    def test_main_and_batch_model_schema_match_projection_catalog(self):
        from model import SCHEMA
        schema=json.loads(SCHEMA.read_text(encoding='utf-8-sig'))
        main=schema['properties']['properties']['anyOf'][1]
        child=schema['properties']['tasks']['items']['properties']['intent']['properties']['properties']
        for node in (main,child):
            self.assertEqual(node['maxItems'],len(CATALOG))
            self.assertEqual(set(node['items']['enum']),{'*',*CATALOG})
    def test_execution_failure_has_request_and_final_plan(self):
        import app
        from http.server import ThreadingHTTPServer
        old=app.STORE;app.STORE=self.store
        server=ThreadingHTTPServer(('127.0.0.1',0),app.Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        sid='completion-diagnostic';p=plan(operation='search',properties=None,entity={'tree':'config','code':'MOHB01'},query={'target':'pbs','filters':[]})
        try:
            body={'session':sid,'intent':p,'trace':True,'question':'诊断测试'}
            req=urllib.request.Request('http://127.0.0.1:'+str(server.server_port)+'/api/query',data=json.dumps(body).encode(),headers={'Content-Type':'application/json','X-Demo-Token':app.TOKEN})
            with self.assertRaises(urllib.error.HTTPError) as caught:urllib.request.urlopen(req)
            r=json.load(caught.exception);self.assertEqual(caught.exception.code,400)
            self.assertTrue(r['request_id']);self.assertEqual(r['diagnostic']['intent'],p);self.assertEqual(r['diagnostic']['question'],'诊断测试')
            self.assertFalse(app.SESSIONS[sid]['busy'])
        finally:server.shutdown();server.server_close();app.SESSIONS.pop(sid,None);app.STORE=old

if __name__=='__main__':unittest.main()
