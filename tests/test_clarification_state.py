"""澄清只更新一个槽位，并且不能伪造当前会话授权。"""
import copy,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from test_business_request import patch,delta,edit,condition
from business_request import apply_delta,commit_state
from clarification_state import make_slot,resolve_answer
from result_goal import default_goal
from data import Store
from request_checklist import literal_references
from operation_capabilities import operations_for
import model

class ClarificationStateTests(unittest.TestCase):
 def state(self):
  q='对象11的阈值';g=default_goal('attributes')
  return apply_delta(delta([patch(None,{'operation':'attributes','target':'points','properties':['actual_high1'],'result_goal':g},[edit('add',[],[condition('code','equals','11')],q)],q)]),None,q)[1]
 def context(self):
  a=self.state();b=copy.deepcopy(a);b['tasks'][0]['filters'][0]['field']='identity';slot=make_slot(a['tasks'],b['tasks'])
  return {'pending_business_request':a,'pending_slot':slot}
 def test_short_name_changes_identity_field_not_projection(self):
  context=self.context();before=copy.deepcopy(context);plan,state,ids,resolution=resolve_answer('名称',context)
  self.assertEqual(plan['query']['filters'],[condition('name','equals','11')]);self.assertEqual(plan['properties'],['actual_high1'])
  self.assertEqual(state['tasks'][0]['result_goal'],before['pending_business_request']['tasks'][0]['result_goal']);self.assertEqual(context,before)
 def test_free_answer_is_not_automatically_authorized(self):
  for q in ('另查对象22','名称和编码','名称，但查全部对象','查询名称'):
   self.assertIsNone(resolve_answer(q,self.context()))
 def test_stale_slot_does_not_change_another_identity(self):
  context=self.context();context['pending_business_request']['tasks'][0]['filters'][0]['value']='22';self.assertIsNone(resolve_answer('名称',context))
 def test_programmatic_binding_uses_current_context_and_one_use_seal(self):
  from request_gateway import require_verified
  store=Store();context=self.context()
  try:
   plan=model.interpret('名称',context,None);bound=model.bind_references(store,'名称',plan,context);require_verified(store,'名称',bound)
   with self.assertRaises(ValueError):require_verified(store,'名称',bound)
   model.interpret('名称',context,None)
   changed=copy.deepcopy(context);changed['pending_slot']['identity_value']='22'
   with self.assertRaises(model.PlanInvalid):model.bind_references(store,'名称',plan,changed)
  finally:store.db.close()
 def test_failed_query_preserves_draft_without_committing_success(self):
  state=self.state();context=commit_state({}, {'engine':'business_request','business_request_state':state,'changed_tasks':['t1']},{'status':'ambiguous','outcome':{'kind':'ambiguous'}},{})
  self.assertNotIn('business_request',context);self.assertEqual(context['pending_business_request']['tasks'],state['tasks'])
 def test_coordinate_expansion_uses_known_prefix_and_existing_row(self):
  store=Store()
  try:
   refs=literal_references('测量点名称7和6的测量值相差多少',store)
   self.assertEqual([(r['value'],r['kind']) for r in refs if r.get('kind')=='coordinated_literal'],[('测量点名称6','coordinated_literal')])
   self.assertFalse(any(r.get('kind')=='coordinated_literal' for r in literal_references('测量点名称7和999999999的测量值',store)))
   self.assertFalse(any(r.get('kind')=='coordinated_literal' for r in literal_references('7和6相差多少',store)))
  finally:store.db.close()
 def test_original_pbs_object_reports_distinct_missing_reasons(self):
  store=Store()
  try:
   r=operations_for(store,{'tree':'pbs','code':'XJ1ABC002PO.PPR.1CGR054LP.RSQ'})
   self.assertEqual(len(r['operations']),4);self.assertTrue(all(not x['enabled'] for x in r['operations']))
   self.assertEqual(len({x['reason'] for x in r['operations']}),4)
  finally:store.db.close()

class AliasAndDomainTests(unittest.TestCase):
 def test_verified_alias_keeps_full_identity_and_rejects_joined_token(self):
  from business_request import ground_identifiers
  from identifier_aliases import schema_name_aliases
  store=Store()
  try:
   for value in ('测量点11','测量点名称11'):
    q='测量点11的阈值是多少'
    refs={'references':literal_references(q,store)}
    state=apply_delta(delta([patch(None,{'operation':'attributes','target':'points','properties':['actual_high2'],'result_goal':default_goal('attributes')},[edit('add',[],[condition('name','equals',value)],q)],q)]),None,q,refs)[1]
    grounded=ground_identifiers(store,state,['t1'])
    self.assertEqual(grounded['tasks'][0]['filters'][0]['value'],'测量点名称11')
   self.assertFalse(schema_name_aliases('测量点11abc',store))
   self.assertFalse(schema_name_aliases('测量点999999',store))
  finally:store.db.close()
 def test_confirmed_attribute_label_is_new_read_not_pending_identity_answer(self):
  state=ClarificationStateTests().state();context={'business_request':state}
  plan,after,ids,proof=resolve_answer('名称',context)
  self.assertEqual(plan['properties'],['name']);self.assertEqual(plan['query']['filters'],[condition('code','equals','11')])
  self.assertEqual(after['tasks'][0]['result_goal'],default_goal('attributes'))
  self.assertEqual(resolve_answer('名称',ClarificationStateTests().context())[0]['properties'],['actual_high1'])
 def test_domain_reply_preserves_identity_properties_and_goal(self):
  q='介绍下PBS的MOHB';t=patch(None,{'operation':'attributes','target':'pbs','properties':['name','code','type'],'result_goal':default_goal('attributes')},[edit('add',[],[condition('identity','equals','MOHB')],q)],q)
  t.update(purpose='introduction',subject_scope='explicit');state=apply_delta(delta([t]),None,q)[1]
  context={'pending_business_request':state}
  for reply,domain in [('那构型呢','config'),('设备类呢','equipment_class')]:
   plan,after,ids,proof=resolve_answer(reply,context)
   self.assertEqual(plan['query']['target'],domain);self.assertEqual(plan['query']['filters'],[condition('identity','equals','MOHB')])
   self.assertEqual(plan['properties'],['name','code','type']);self.assertEqual(after['tasks'][0]['result_goal'],default_goal('attributes'))
   context={'business_request':after}
  self.assertIsNone(resolve_answer('设备类，但查另一个对象',context))

class ReferenceAndDisagreementTests(unittest.TestCase):
 def test_cross_domain_selection_requires_independently_verified_reference(self):
  from request_checklist import resolve_sources
  q='继续';c={'version':4,'status':'ready','mode':'new','clarification':'','tasks':[{'id':None,'spans':[1],'target':'points','properties':['value'],'unit':{'state':'none','value':''},'conditions':[{'field':'identity','operator':'equals','value':'POINT','spans':[],'reference':1}]}]}
  refs={'references':[{'id':1,'domain':'pbs','field':'code','value':'POINT','kind':'user_selection','quote':'POINT'}]}
  with self.assertRaises(ValueError):resolve_sources(c,q,refs)
  refs['references'].append({**refs['references'][0],'id':2,'domain':'points'})
  self.assertEqual(resolve_sources(c,q,refs)['tasks'][0]['conditions'][0]['value'],'POINT')
 def test_equivalent_identity_disagreement_asks_actual_projection_difference(self):
  from semantic_review import business_question
  a={'operation':'attributes','target':'points','scope':'direct','properties':['name'],'filters':[condition('code','equals','P1')]}
  b={**a,'properties':['actual_high2'],'filters':[condition('name','equals','N1')]}
  canonical={'candidate':[{'filters':[('resolved_identity','equals','same')]}],'independent':[{'filters':[('resolved_identity','equals','same')]}]}
  question=business_question([a],[b],'update','update',canonical)
  self.assertIn('查看',question);self.assertNotIn('P1',question);self.assertNotIn('N1',question)
  self.assertIsNone(make_slot([{**a,'id':'t1'}],[{**b,'id':'t1'}],canonical))

if __name__=='__main__':unittest.main()
