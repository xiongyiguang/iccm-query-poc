"""验证未完成任务的持续状态和范围说明，不把单项成功当作整组完成。"""
import copy,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from business_request import apply_delta,commit_state,compile_selected
from result_goal import default_goal
from query_plan import execute_plan,task_context
from query_presentation import attach_basis
from data import Store
from test_business_request import patch,delta,edit,condition

class GoalStateTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.store=Store()
 @classmethod
 def tearDownClass(cls):cls.store.db.close()
 def fixture(self,batch=False):
  q='空值排序';goal={**default_goal('search'),'kind':'sort','field':'value','direction':'desc','limit':3,'basis':'raw_numbers'}
  empty=patch(None,{'operation':'search','target':'points','result_goal':goal},[edit('add',[],[condition('value','is_blank','')],q)],q)
  patches=[patch(None,{'operation':'search','target':'points','result_goal':{**default_goal('search'),'kind':'count'}},[],q),empty] if batch else [empty]
  return apply_delta(delta(patches),None,q)
 def commit(self,state,ids,result,previous=None,mode='update'):
  trace={'engine':'business_request','business_request_state':state,'changed_tasks':ids,'business_request_delta':{'mode':mode}}
  return commit_state({},trace,result,previous)
 def test_missing_measurements_keep_goal_and_current_draft(self):
  plan,state,ids=self.fixture();r=execute_plan(self.store,plan);self.assertEqual(r['status'],'data_insufficient')
  c=self.commit(state,ids,r);self.assertEqual(c['pending_business_request']['tasks'],state['tasks']);self.assertEqual(c['pending_business_request']['pending_tasks'],['t1']);self.assertNotIn('business_request',c)
  self.assertEqual(task_context(plan,r)['pending_request'],plan)
 def test_unfinished_new_query_does_not_replace_previous_success(self):
  plan,state,ids=self.fixture();previous={'business_request':{'version':1,'tasks':[{'id':'old'}]}}
  c=self.commit(state,ids,execute_plan(self.store,plan),previous,mode='new');self.assertEqual(c['business_request'],previous['business_request']);self.assertEqual(c['pending_business_request']['tasks'],state['tasks'])
 def test_partial_batch_tracks_only_failed_task(self):
  plan,state,ids=self.fixture(True);r=execute_plan(self.store,plan)
  self.assertEqual([x['status'] for x in r['items']],['ok','data_insufficient'])
  self.assertIn('pending_request',r['items'][1]['task_context']);c=self.commit(state,ids,r,mode='new')
  self.assertEqual(c['pending_business_request']['pending_tasks'],['t2']);self.assertNotIn('business_request',c)
 def test_completing_other_branch_preserves_pending_and_its_slot(self):
  plan,state,ids=self.fixture(True);c=self.commit(state,ids,execute_plan(self.store,plan),mode='new');draft=c['pending_business_request'];c['pending_slot']={'task_id':'t2','kind':'choice','field':'unit'}
  first=compile_selected(draft,['t1'],['继续第一项']);nextc=self.commit(draft,['t1'],execute_plan(self.store,first),c)
  self.assertEqual(nextc['pending_business_request']['pending_tasks'],['t2']);self.assertEqual(nextc['pending_slot'],c['pending_slot']);self.assertNotIn('business_request',nextc)
 def test_completing_last_failed_branch_confirms_full_updated_state(self):
  plan,state,ids=self.fixture(True);c=self.commit(state,ids,execute_plan(self.store,plan),mode='new');draft=copy.deepcopy(c['pending_business_request']);draft['tasks'][1]['filters']=[]
  second=compile_selected(draft,['t2'],['取消空值条件']);r=execute_plan(self.store,second);self.assertEqual(r['status'],'ok')
  nextc=self.commit(draft,['t2'],r,c);self.assertNotIn('pending_business_request',nextc);self.assertNotIn('pending_tasks',nextc['business_request']);self.assertEqual(len(nextc['business_request']['tasks']),2)
  self.assertEqual(nextc['business_request']['tasks'][0],draft['tasks'][0]);self.assertEqual(nextc['business_request']['tasks'][1]['result_goal'],draft['tasks'][1]['result_goal'])
 def test_new_topic_never_inherits_old_pending_task_ids(self):
  plan,state,ids=self.fixture(True);c=self.commit(state,ids,execute_plan(self.store,plan),mode='new')
  newstate=copy.deepcopy(state);newstate['tasks']=[newstate['tasks'][1]];newstate['tasks'][0]['filters']=[]
  plan=compile_selected(newstate,['t2'],['另起话题']);nextc=self.commit(newstate,['t2'],execute_plan(self.store,plan),c,mode='new');self.assertNotIn('pending_business_request',nextc)
 def test_selection_must_satisfy_other_filters(self):
  from clarification_state import resolve_answer
  from test_goal_boundaries import CandidateContinuationTests
  helper=CandidateContinuationTests();state=helper.state();state['tasks'][0]['filters'].append({'id':'f2','field':'source','operator':'equals','value':'源系统2','source':{'quote':'源系统2'}})
  context={'pending_business_request':state,'outcome':{'kind':'ambiguous'}};selection={'tree':'pbs','code':'XJ2ABC001MO.TMP.2ABC109MT.BBe'}
  self.assertIsNone(resolve_answer('继续',context,selection,self.store));state['tasks'][0]['filters'][-1]['value']='源系统1'
  _,selected,_,_=resolve_answer('继续',context,selection,self.store)
  self.assertEqual(selected['tasks'][0]['filters'][-1],state['tasks'][0]['filters'][-1])
 def test_scope_description_matches_point_executor_instead_of_direct_enum(self):
  for op in ('search','analyze','measurements','alarms'):
   p={'operation':op,'entity':{'tree':'pbs','code':'XJ2ABC002MO&MOHB01'},'scope':'direct','query':{'target':'points','filters':[]}}
   r={'status':'ok','entity':p['entity'],'scope':'direct'};attach_basis(r,p);self.assertIn('自身及全部后代',r['business_scope']);self.assertNotIn('直接下级',r['business_scope'])
 def test_nonpoint_and_attribute_scopes_stay_distinct(self):
  p={'operation':'search','entity':{'tree':'config','code':'MOHB01'},'scope':'direct','query':{'target':'config','filters':[]}}
  r={'status':'ok','entity':p['entity'],'scope':'direct'};attach_basis(r,p);self.assertIn('直接下级',r['business_scope'])
  p.update(operation='attributes',query={'target':'points','filters':[]});r={'status':'ok','entity':p['entity']};attach_basis(r,p);self.assertNotIn('后代',r['business_scope'])

 def identity_state(self,target,field='name',value='设备类描述1860',operation='attributes',props=None):
  q=value+' identity';p=patch(None,{'operation':operation,'target':target,'properties':(['name','code'] if props is None else props),'result_goal':default_goal(operation)},[edit('add',[],[condition(field,'equals',value)],q)],q)
  state=apply_delta(delta([p]),None,q)[1];state['tasks'][0]['sources']['purpose']={'value':'identity'}
  return state
 def test_unique_cross_tree_identity_matches_actual_tree_without_mutation(self):
  from request_checklist import reconcile
  a=self.identity_state('objects');b=self.identity_state('equipment_class');before=copy.deepcopy(a)
  self.assertTrue(reconcile(a,['t1'],b,['t1'],self.store)['matches']);self.assertEqual(a,before)
 def test_multi_tree_same_code_does_not_collapse_to_single_tree(self):
  from request_checklist import reconcile
  self.assertFalse(reconcile(self.identity_state('objects','code','MOHB'),['t1'],self.identity_state('equipment_class','code','MOHB'),['t1'],self.store)['matches'])
 def test_object_list_domain_and_nonidentity_properties_stay_distinct(self):
  from request_checklist import reconcile
  for op,props in [('search',[]),('attributes',['name','major_equipment'])]:
   a=self.identity_state('objects',operation=op,props=props);b=self.identity_state('equipment_class',operation=op,props=props)
   if op=='search':a['tasks'][0]['properties']=b['tasks'][0]['properties']=[]
   self.assertFalse(reconcile(a,['t1'],b,['t1'],self.store)['matches'])
 def test_additional_condition_prevents_unique_domain_shortcut(self):
  from request_checklist import reconcile
  a=self.identity_state('objects');b=self.identity_state('equipment_class')
  f={'id':'f2','field':'level','operator':'equals','value':'3','source':{'quote':'3'}}
  a['tasks'][0]['filters'].append(copy.deepcopy(f));b['tasks'][0]['filters'].append(copy.deepcopy(f))
  self.assertFalse(reconcile(a,['t1'],b,['t1'],self.store)['matches'])

 def projection_gate(self,candidate,props=None):
  from request_checklist import gate
  from unittest.mock import patch as mockpatch
  q='设备类描述1860对应哪个设备类'
  answer={'version':13,'status':'ready','mode':'new','clarification':'','roles':{'background':[],'output':[1],'control':[]},'tasks':[{'id':None,'action':'request','request_spans':[1],'kind':'query','purpose':'identity','subject_scope':'unspecified','spans':[1],'target':'objects','properties':props or ['name','code','type','level','parent'],'unit':{'state':'none','value':''},'conditions':[{'field':'name','operator':'equals','value':'设备类描述1860','spans':[1],'reference':None}],'result_goal':default_goal('attributes')}]}
  with mockpatch('request_checklist.extract',return_value=(answer,{})):
   return gate(q,None,candidate,['t1'],'update',self.store)
 def test_proven_metadata_projection_accepts_same_full_future_state(self):
  out=self.projection_gate(self.identity_state('equipment_class'))
  self.assertEqual(out['decision'],'accept');self.assertEqual(out['choice'],'independent');self.assertTrue(out['proven_projection_future_state'])
 def test_metadata_projection_does_not_allow_new_to_drop_another_task(self):
  state=self.identity_state('equipment_class');second=copy.deepcopy(state['tasks'][0]);second['id']='t2';state['tasks'].append(second)
  out=self.projection_gate(state);self.assertEqual(out['decision'],'clarify')
 def test_nonmetadata_projection_difference_still_requires_clarification(self):
  out=self.projection_gate(self.identity_state('equipment_class'),['name','code','major_equipment'])
  self.assertEqual(out['decision'],'clarify')

 def test_unbounded_sort_and_extreme_never_reconcile_even_with_all_ties(self):
  from request_checklist import reconcile
  a=self.fixture()[1];t=a['tasks'][0];t['filters']=[];t['result_goal']={**default_goal('search'),'kind':'sort','field':'time','direction':'desc'}
  b=copy.deepcopy(a);b['tasks'][0]['result_goal']['kind']='extreme'
  self.assertFalse(reconcile(a,['t1'],b,['t1'],self.store)['matches'])
  c=copy.deepcopy(a);c['tasks'][0]['result_goal']['limit']=3
  self.assertFalse(reconcile(b,['t1'],c,['t1'],self.store)['matches'])

 def test_typed_quantity_constraint_is_clear_feedback_and_never_executes(self):
  import model
  from unittest.mock import patch as mockpatch
  from business_request import RequestInvalid
  q='前101条';goal={**default_goal('search'),'kind':'sort','field':'time','direction':'desc','limit':100}
  p,state,ids=apply_delta(delta([patch(None,{'operation':'search','target':'points','result_goal':goal},[],q)]),None,q)
  trace={'engine':'business_request','business_request_state':state,'changed_tasks':ids,'business_request_delta':{'mode':'new','tasks':[{'quote':q}]}}
  failure=RequestInvalid('invalid');failure.business_constraint={'code':'sort_limit_bounds','minimum':1,'maximum':100}
  old=model.get_trace();model.TRACE.value=trace
  try:
   with mockpatch('request_checklist.gate',side_effect=failure):out=model.bind_references(self.store,q,p,{})
   self.assertEqual(out['operation'],'clarify');self.assertIn('1至100',out['clarification']);self.assertIn('尚未执行',out['clarification']);self.assertNotIn('query',out)
  finally:model.TRACE.value=old

if __name__=='__main__':unittest.main()
