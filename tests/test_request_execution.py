"""本轮执行任务集合独立于保留的已确认任务状态。"""
import copy,sys,unittest
from pathlib import Path
from unittest.mock import patch as mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from business_request import apply_delta,resolve_delta_sources,compile_selected,execution_quotes,RequestInvalid
from test_business_request import patch,delta,edit,condition
from request_checklist import to_delta,compile_checklist,gate
import model,query_review


class ExecutionMembershipTests(unittest.TestCase):
    def setUp(self):
        q='PointA PointB'
        ts=[patch(None,{'operation':'attributes','target':'points','properties':['value','unit']},
                  [edit('add',[],[condition('name','equals',name)],q)],q) for name in ('PointA','PointB')]
        self.state=apply_delta(delta(ts),None,q)[1]
        self.q='第一项只读测量值；第二项保留但不执行。'
    def request(self,reverse=False):
        tasks=[{'base':'t1','execute':True,'spans':[1],'set':{'properties':['value']},'filters':[]},
               {'base':'t2','execute':False,'spans':[2],'set':{},'filters':[]}]
        return {'version':3,'mode':'update','tasks':tasks[::-1] if reverse else tasks}
    def checklist(self):
        return {'version':5,'status':'ready','mode':'update','clarification':'','tasks':[
            {'id':t['id'],'execute':t['id']=='t1','spans':[i], 'target':t['target'],
             'properties':['value'] if t['id']=='t1' else t['properties'], 'unit':t['unit'],
             'conditions':[{**{k:f[k] for k in ('field','operator','value')},'spans':[],'reference':None} for f in t['filters']]}
            for i,t in enumerate(self.state['tasks'],1)]}
    def test_retained_task_order_does_not_shift_execution_sources(self):
        before=copy.deepcopy(self.state)
        for reverse in (False,True):
            d=resolve_delta_sources(self.request(reverse),self.q)
            plan,state,ids=apply_delta(d,self.state,self.q)
            self.assertEqual(ids,['t1']);self.assertEqual(state['tasks'][1],before['tasks'][1])
            self.assertEqual(plan,compile_selected(state,ids,execution_quotes(d)))
            self.assertEqual(plan['properties'],['value'])
        self.assertEqual(self.state,before)
    def test_all_retained_is_valid_no_query_plan(self):
        d=self.request();d['tasks'][0].update(execute=False,set={})
        plan,state,ids=apply_delta(d,self.state,self.q)
        self.assertEqual(ids,[]);self.assertEqual(state['tasks'],self.state['tasks'])
        self.assertEqual(model.validate(plan)['operation'],'conversation')
        self.assertFalse(query_review.required(plan,{'business_request':self.state}))
    def test_explicit_requery_without_changes_still_executes(self):
        d=self.request();d['tasks'][0]['set']={};d['tasks'][1]['execute']=True
        plan,state,ids=apply_delta(d,self.state,self.q)
        self.assertEqual(ids,['t1','t2']);self.assertEqual(plan['operation'],'batch')
        self.assertEqual(state['tasks'],self.state['tasks'])
    def test_non_execution_cannot_hide_mutations(self):
        for mutation in ({'set':{'properties':['status']}},{'filters':[edit('remove',['f2'],[],self.q)]},
                         {'unit':{'state':'none','value':''}},{'replace_task':True}):
            d=self.request();d['tasks'][1].update(mutation)
            with self.subTest(mutation=mutation),self.assertRaises(RequestInvalid):apply_delta(d,self.state,self.q)
    def test_false_requires_existing_unique_task(self):
        for base in ('missing','t1',None):
            d=self.request();d['tasks'][1]['base']=base
            with self.subTest(base=base),self.assertRaises(RequestInvalid):apply_delta(d,self.state,self.q)
        d=self.request();d['mode']='new'
        with self.assertRaises(RequestInvalid):apply_delta(d,self.state,self.q)
    def test_explicit_execution_requires_real_boolean(self):
        for value in (None,0,1,'false',[],{}):
            d=self.request();d['tasks'][1]['execute']=value
            with self.subTest(value=value),self.assertRaises(RequestInvalid):apply_delta(d,self.state,self.q)
        d=self.request();d['tasks'][1].pop('execute')
        with self.assertRaises(RequestInvalid):apply_delta(d,self.state,self.q)
    def test_checklist_preserves_false_with_same_state(self):
        d=to_delta(self.checklist(),self.state,self.q)
        plan,state,ids=apply_delta(d,self.state,self.q)
        self.assertEqual(ids,['t1']);self.assertFalse(d['tasks'][1]['execute'])
        self.assertEqual(state['tasks'][1],self.state['tasks'][1])
        self.assertEqual(plan['properties'],['value'])
    def test_checklist_rejects_hidden_property_or_condition_changes(self):
        for field,value in [('properties',['status']),('conditions',[]),('target','config'),('unit',{'state':'specified','value':'℃'})]:
            c=self.checklist();c['tasks'][1][field]=value
            with self.subTest(field=field),self.assertRaises(RequestInvalid):to_delta(c,self.state,self.q)
    def test_checklist_new_protocol_requires_execute(self):
        c=self.checklist();c['tasks'][1].pop('execute')
        with self.assertRaises(RequestInvalid):to_delta(c,self.state,self.q)
    def test_compilation_never_silently_zips_mismatched_sources(self):
        with self.assertRaises(RequestInvalid):compile_selected(self.state,['t1'],[])
    def test_confirmation_commits_only_executed_changes_preserves_sibling(self):
        d=resolve_delta_sources(self.request(True),self.q);plan,state,ids=apply_delta(d,self.state,self.q)
        session={'context':{'business_request':self.state}}
        preview=query_review.issue(session,'sid','v1',self.q,plan,{'engine':'business_request','business_request_delta':d,'business_request_state':state,'changed_tasks':ids})
        changes=[{k:t[k] for k in ('index','enabled','values')} for t in preview['review']['tasks']]
        _,trace,_=query_review.confirm(session,'sid','v1',preview['review']['id'],changes)
        self.assertEqual(trace['changed_tasks'],['t1'])
        self.assertEqual(trace['business_request_state']['tasks'][1],self.state['tasks'][1])


if __name__=='__main__':unittest.main()
