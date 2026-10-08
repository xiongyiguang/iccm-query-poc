"""读取、带依据解释和能力限制共用同一类型化任务契约。"""
import copy,sys,unittest
from pathlib import Path
from unittest.mock import patch as mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from business_request import apply_delta,compile_task,commit_state,RequestInvalid
from request_checklist import to_delta,compile_checklist,canonical_tasks,prior_view
from data_context import DOMAIN_FACTS
from query_plan import execute_plan
from data import Store,QueryError
import query_review,model,request_gateway

Q='测量点名称11的高2阈值和含义'
def read():
    return {'base':None,'quote':Q,'execute':True,'set':{'operation':'attributes','target':'points','properties':['actual_high2']},'filters':[{'action':'add','ids':[],'quote':Q,'conditions':[{'field':'name','operator':'equals','value':'测量点名称11'}]}]}
def note(kind='explain',topics=None,base=None):
    return {'base':base,'quote':Q,'execute':True,'set':{'operation':kind,'topics':topics or (['limits'] if kind=='unsupported' else ['alarm'])},'filters':[]}
def delta(tasks,mode='new'):return {'version':1,'mode':mode,'tasks':tasks}
def checklist(kind='explain'):
    return {'version':6,'status':'ready','mode':'new','clarification':'','tasks':[
        {'id':None,'execute':True,'spans':[1],'kind':'query','target':'points','properties':['actual_high2'],'unit':{'state':'none','value':''},'conditions':[{'field':'name','operator':'equals','value':'测量点名称11','spans':[1],'reference':None}]},
        {'id':None,'execute':True,'spans':[1],'kind':kind,'topics':['limits'] if kind=='unsupported' else ['alarm']}]}

class MixedRequestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.store=Store()
    @classmethod
    def tearDownClass(cls):cls.store.db.close()
    def mixed(self,kind='explain',reverse=False):
        tasks=[read(),note(kind)]
        return apply_delta(delta(tasks[::-1] if reverse else tasks),None,Q)
    def test_query_and_explanation_keep_both_and_commit_complete_state(self):
        for kind in ('explain','unsupported'):
            plan,state,ids=self.mixed(kind)
            result=execute_plan(self.store,plan)
            self.assertEqual([x['status'] for x in result['items']],['ok','conversation'])
            self.assertEqual(result['items'][0]['requested_properties'],['actual_high2'])
            context=commit_state({},dict(engine='business_request',business_request_state=state,changed_tasks=ids),result,{})
            self.assertEqual(context['business_request'],state)
    def test_pure_notes_do_not_query_database(self):
        for kind in ('explain','unsupported'):
            plan,state,ids=apply_delta(delta([note(kind)]),None,Q)
            with mock.object(self.store,'rows',side_effect=AssertionError('no data query')):
                response=execute_plan(self.store,plan)
            self.assertEqual(response['status'],'conversation')
            self.assertFalse(query_review.required(plan,{}))
            self.assertEqual(commit_state({},dict(business_request_state=state,changed_tasks=ids),response)['business_request'],state)
    def test_capability_boundary_cannot_have_other_topics(self):
        for topics in (['alarm'],['limits','quality'],[],['unknown']):
            t=note('unsupported');t['set']['topics']=topics
            with self.subTest(topics=topics),self.assertRaises(RequestInvalid):apply_delta(delta([t]),None,Q)
    def test_note_cannot_smuggle_query_fields_or_dynamic_counts(self):
        for key,value in [('target','points'),('properties',['value']),('scope','all'),('topics',['counts'])]:
            t=note();t['set'][key]=value
            with self.subTest(key=key),self.assertRaises(RequestInvalid):apply_delta(delta([t]),None,Q)
        t=note();t['filters']=read()['filters']
        with self.assertRaises(RequestInvalid):apply_delta(delta([t]),None,Q)
        t=read();t['set']['topics']=['alarm']
        with self.assertRaises(RequestInvalid):apply_delta(delta([t]),None,Q)
    def test_replace_query_with_note_erases_query_predicates(self):
        _,old,_=self.mixed();t=note(base='t1');t.update(replace_task=True,retain_filters=[])
        plan,state,ids=apply_delta(delta([t],'update'),old,Q)
        self.assertEqual(plan['operation'],'explain');self.assertEqual(ids,['t1'])
        self.assertEqual(state['tasks'][0]['filters'],[]);self.assertIsNone(state['tasks'][0]['target'])
        self.assertEqual(state['tasks'][1],old['tasks'][1])
        t['retain_filters']=['f1']
        with self.assertRaises(RequestInvalid):apply_delta(delta([t],'update'),old,Q)
    def test_replace_note_with_query_erases_explanation_topics(self):
        _,old,_=self.mixed();t=read();t.update(base='t2',replace_task=True,retain_filters=[])
        plan,state,ids=apply_delta(delta([t],'update'),old,Q)
        self.assertEqual(plan['operation'],'attributes');self.assertNotIn('topics',state['tasks'][1]);self.assertEqual(ids,['t2'])
    def test_cross_kind_without_replacement_is_rejected(self):
        _,old,_=self.mixed();t=note(base='t1')
        with self.assertRaises(RequestInvalid):apply_delta(delta([t],'update'),old,Q)
    def test_checklist_and_primary_compile_identical_mixed_requests(self):
        for kind in ('explain','unsupported'):
            plan,state,ids=self.mixed(kind)
            other,after,changed,_=compile_checklist(checklist(kind),None,Q,self.store)
            self.assertEqual(plan,other);self.assertEqual(canonical_tasks(state,ids,self.store),canonical_tasks(after,changed,self.store))
            self.assertEqual(prior_view(state)[1]['operation'],kind)
    def test_note_topic_is_part_of_semantic_comparison(self):
        _,state,ids=self.mixed();other=copy.deepcopy(state);other['tasks'][1]['topics']=['quality']
        self.assertNotEqual(canonical_tasks(state,ids,self.store),canonical_tasks(other,ids,self.store))
    def test_confirmation_note_is_readonly_and_commits_correct_number(self):
        for reverse in (False,True):
            plan,state,ids=self.mixed(reverse=reverse)
            session={'context':{}}
            draft=query_review.issue(session,'s','v',Q,plan,dict(engine='business_request',business_request_state=state,changed_tasks=ids,business_request_delta={'mode':'new'}))
            changes=[{k:copy.deepcopy(t[k]) for k in ('index','enabled','values')} for t in draft['review']['tasks']]
            ni=0 if reverse else 1
            self.assertFalse(changes[ni]['enabled']);self.assertIn('报警',draft['review']['tasks'][ni]['message'])
            bad=copy.deepcopy(changes);bad[ni]['values']['topics']=['quality']
            with self.assertRaises(QueryError):query_review.confirm(session,'s','v',draft['review']['id'],bad)
            final,trace,_=query_review.confirm(session,'s','v',draft['review']['id'],changes)
            self.assertEqual(trace['changed_tasks'],ids)
            result=execute_plan(self.store,final)
            self.assertEqual(len(commit_state({},trace,result)['business_request']['tasks']),2)
    def test_failed_query_does_not_commit_note_or_mutate_previous(self):
        _,old,_=self.mixed();_,state,ids=self.mixed('unsupported');original=copy.deepcopy(old)
        response={'status':'batch','items':[{'status':'error'},{'status':'conversation'}]}
        context=commit_state({},dict(engine='business_request',business_request_state=state,changed_tasks=ids),response,{'business_request':old})
        self.assertEqual(context['business_request'],old);self.assertEqual(old,original)
    def test_legacy_read_and_static_explanation_enters_complete_gateway(self):
        plan,state,ids=self.mixed();trace={'engine':'legacy','reference_context':None}
        with mock('request_checklist.extract',return_value=(checklist(),{})):
            bound=request_gateway.migrate(self.store,Q,plan,trace)
        self.assertEqual(bound,plan);self.assertEqual(trace['engine'],'business_request')
    def test_legacy_partial_migration_rejects_whole_plan(self):
        plan,_,_=self.mixed();plan['tasks'][1]['intent']={'operation':'threshold','entity':{'tree':'pbs','code':'X'},'scope':'direct','clarification':''}
        trace={};bound=request_gateway.migrate(self.store,Q,plan,trace)
        self.assertEqual(bound['operation'],'clarify');self.assertNotIn('tasks',bound)

if __name__=='__main__':unittest.main()
