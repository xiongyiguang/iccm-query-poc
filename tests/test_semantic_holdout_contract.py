import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from request_contract import validate_route,scope_context,complete_contract,enforce
from typed_fields import compare

def route(**kw):
 return dict(needs_history=False,identifier_field=None,resolved_question=None,domain=None,thresholds=None,comparisons=[],unit={'state':'none','value':''},reference=None,projection='specified',scope=None,properties=[],context_mode='new',**kw) if not kw else {**route(),**kw}

class HoldoutContractTests(unittest.TestCase):
 def test_replace_subject_preserves_projection_but_never_identity(self):
  ctx={'entity':{'tree':'pbs','code':'OLD'},'query':{'target':'points','filters':[{'field':'code','operator':'equals','value':'OLD'}]},'requested_properties':['actual_high3','prediction'],'pending_reference':'OLD','dialogue':[{'question':'OLD','answer':'old'}]}
  d,c,s=scope_context(route(needs_history=True,reference='NEW',context_mode='replace_subject'),ctx,ctx['entity'])
  self.assertIsNone(s);self.assertNotIn('entity',c);self.assertNotIn('query',c);self.assertNotIn('pending_reference',c)
  self.assertEqual(d['properties'],['actual_high3','prediction']);self.assertEqual(c['requested_properties'],d['properties'])
  self.assertEqual(ctx['entity']['code'],'OLD')
 def test_independent_new_subject_does_not_inherit_projection(self):
  d,c,s=scope_context(route(reference='NEW'),{'entity':{'code':'OLD'},'requested_properties':['rate']},None)
  self.assertEqual(c,{});self.assertEqual(d['properties'],[])
 def test_mixed_projection_compiles_as_attributes_without_loss(self):
  p={'operation':'threshold','entity':{'tree':'pbs','code':'P'},'scope':'direct','thresholds':['actual_low2']}
  d=route(properties=['actual_low2','prediction'],thresholds=['actual_low2'])
  out=complete_contract(p,d);self.assertEqual(out['operation'],'attributes');self.assertEqual(out['properties'],d['properties']);enforce(out,d)
  self.assertEqual(p['operation'],'threshold')
 def test_missing_plain_property_is_rejected(self):
  p={'operation':'attributes','entity':None,'scope':'direct','properties':['actual_high3']}
  with self.assertRaises(ValueError):enforce(p,route(properties=['actual_high3','prediction']))
 def test_projection_is_validated_against_shared_catalog(self):
  validate_route(route(properties=['actual_high3','prediction']),strict=True)
  for props in [['imaginary'],['rate','rate'],[{}]]:
   with self.assertRaises(ValueError):validate_route(route(properties=props),strict=True)
 def test_replace_subject_requires_new_identity_and_history(self):
  for d in [route(context_mode='replace_subject'),route(context_mode='replace_subject',reference='P')]:
   with self.assertRaises(ValueError):validate_route(d)
 def test_interval_endpoints_are_independent(self):
  lower={'field':'value','operator':'gte','value':'12'}
  upper={'field':'value','operator':'lt','value':'15'}
  p={'operation':'search','query':{'target':'points','filters':[lower,{**upper,'operator':'lte'}]}}
  with self.assertRaises(ValueError):enforce(p,route(comparisons=[lower,upper]))
  self.assertTrue(compare('12','gte','12'));self.assertFalse(compare('15','lt','15'));self.assertTrue(compare('14.999','lt','15'))
 def test_parent_identity_resolves_data_without_overriding_explicit_name(self):
  from request_contract import bind_subject_identity
  from unittest.mock import Mock
  store=Mock();store.rows.return_value=[{'tree':'config','code':'P','name':'Parent'}]
  p={'operation':'parts','entity':{'tree':'config','name':'P'},'scope':'all'}
  d=route(reference='P',domain='config',identifier_field='identity')
  self.assertEqual(bind_subject_identity(store,p,d)['entity'],{'tree':'config','code':'P'})
  store.rows.return_value=[]
  self.assertEqual(bind_subject_identity(store,p,{**d,'identifier_field':'name'}),p)
  self.assertIn('name=?',store.rows.call_args.args[0]);self.assertNotIn(' OR ',store.rows.call_args.args[0])
  store.rows.return_value=[{'tree':'config','code':'P','name':'Parent'},{'tree':'config','code':'OTHER','name':'P'}]
  self.assertEqual(bind_subject_identity(store,p,d)['operation'],'clarify')
 def test_filter_fields_do_not_require_detail_projection(self):
  p={'operation':'search','query':{'target':'points','filters':[{'field':'value','operator':'gt','value':'3'}]}}
  enforce(p,route(properties=['value']))
 def test_disagreement_review_cannot_change_field_value_or_extra_filters(self):
  import model,json
  from unittest.mock import patch,MagicMock
  low={'field':'value','operator':'gte','value':'12'};high={'field':'value','operator':'lt','value':'15'}
  other={'field':'unit','operator':'equals','value':'℃'}
  p={'operation':'search','query':{'target':'points','filters':[low,{**high,'operator':'lte'},other]}}
  d=route(comparisons=[low,high]);response=MagicMock()
  response.__enter__.return_value.read.return_value=json.dumps({'choices':[{'finish_reason':'stop','message':{'content':json.dumps({'choice':'route','source':'不到15'})}}]}).encode()
  with patch.object(model.urllib.request,'build_opener') as opener:
   opener.return_value.open.return_value=response
   fixed,decision=model.review_comparison_disagreement('至少12，不到15℃',{},p,d,'synthetic')
  self.assertEqual(fixed['query']['filters'],[other,low,high]);self.assertEqual(decision['comparisons'],[low,high])
  self.assertEqual(p['query']['filters'][1]['operator'],'lte')
 def test_disagreement_missing_source_is_rejected(self):
  import model,json
  from unittest.mock import patch,MagicMock
  f={'field':'rate','operator':'lt','value':'3'};p={'operation':'search','query':{'target':'points','filters':[{**f,'operator':'lte'}]}}
  response=MagicMock();response.__enter__.return_value.read.return_value=json.dumps({'choices':[{'finish_reason':'stop','message':{'content':json.dumps({'choice':'route','source':'不存在的原话'})}}]}).encode()
  with patch.object(model.urllib.request,'build_opener') as opener:
   opener.return_value.open.return_value=response
   with self.assertRaises(model.PlanInvalid):model.review_comparison_disagreement('低于3',{},p,route(comparisons=[f]),'synthetic')
 def test_filter_edit_keeps_search_task_not_object_details(self):
  ctx={'operation':'search','scope':'direct','query':{'target':'points','filters':[{'field':'name','operator':'starts_with','value':'prefix'},{'field':'source','operator':'equals','value':'S'}]}}
  d,c,sel=scope_context(route(needs_history=True,context_mode='followup',reference='exact'),ctx,None)
  self.assertTrue(d['needs_history']);self.assertEqual(c['operation'],'search');self.assertEqual(c['query']['filters'],[{'field':'source','operator':'equals','value':'S'}])
 def test_same_confirmed_identity_keeps_domain_even_if_route_calls_new(self):
  d,c,_=scope_context(route(reference='OBJ'),{'entity':{'tree':'equipment_class','code':'OBJ'}},None)
  self.assertTrue(d['needs_history']);self.assertEqual(d['domain'],'equipment_class')
 def test_introduction_and_identity_have_different_missing_domain_behavior(self):
  p={'operation':'attributes','entity':None,'scope':'direct','properties':['name']}
  d=route(reference='X',request_kind='introduction')
  self.assertEqual(complete_contract(p,d)['operation'],'clarify')
  d['request_kind']='identity';out=complete_contract({'operation':'clarify'},d)
  self.assertEqual(out['query']['target'],'objects');self.assertEqual(out['query']['filters'][0]['value'],'X')
 def test_entity_reference_also_reconciles_stale_route(self):
  from request_contract import reconcile_reference
  d=route(needs_history=True,reference='OLD',domain='config')
  p={'operation':'attributes','entity':{'tree':'config','code':'NEW'},'properties':['name']}
  out=reconcile_reference(d,p,'NEW是什么',{})
  self.assertEqual(out['reference'],'NEW');self.assertIsNone(out['domain']);self.assertFalse(out['needs_history'])
 def test_unextracted_identifier_does_not_override_explicit_name_filter(self):
  import model,json
  from unittest.mock import patch,MagicMock
  p={'operation':'search','entity':None,'scope':'direct','clarification':'','query':{'target':'points','filters':[{'field':'name','operator':'starts_with','value':'Alpha'}]}}
  def response(v):
   x=MagicMock();x.__enter__.return_value.read.return_value=json.dumps({'choices':[{'finish_reason':'stop','message':{'content':json.dumps(v)}}]}).encode();return x
  with patch.dict(model.os.environ,{'DEEPSEEK_API_KEY':'synthetic','ICCM_REQUEST_ENGINE':'legacy'}),patch.object(model.urllib.request,'build_opener') as opener:
   opener.return_value.open.side_effect=[response(route()),response(p)]
   self.assertEqual(model.interpret('names starting with Alpha',{},None)['query']['filters'][0]['field'],'name')
 def test_planner_does_not_receive_current_route_to_copy(self):
  import inspect,model
  source=inspect.getsource(model.interpret)
  self.assertNotIn("'semantic_requirements':route",source)
 def test_category_binding_uses_full_literal_data_values_only(self):
  from request_contract import bind_categorical_values
  from unittest.mock import Mock
  store=Mock();store.rows.return_value=[{'value':'Plant3'},{'value':'Plant30'}]
  p={'operation':'search','query':{'target':'points','filters':[{'field':'source','operator':'equals','value':'3'}]}}
  self.assertEqual(bind_categorical_values(store,p,'Plant3 records')['query']['filters'][0]['value'],'Plant3')
  self.assertEqual(bind_categorical_values(store,p,'Plant30 records')['query']['filters'][0]['value'],'Plant30')
  self.assertEqual(bind_categorical_values(store,p,'Plant300 records'),p)
  self.assertEqual(bind_categorical_values(store,p,'source 3 records'),p)
  self.assertEqual(bind_categorical_values(store,p,'Plant3 and Plant30')['operation'],'clarify')
  self.assertEqual(p['query']['filters'][0]['value'],'3')
 def test_category_binding_never_expands_partial_matching_or_existing_value(self):
  from request_contract import bind_categorical_values
  from unittest.mock import Mock
  store=Mock();store.rows.return_value=[{'value':'3'},{'value':'Plant3'}]
  p={'operation':'search','query':{'target':'points','filters':[{'field':'source','operator':'equals','value':'3'}]}}
  self.assertEqual(bind_categorical_values(store,p,'Plant3'),p)
  p['query']['filters'][0]['operator']='contains'
  self.assertEqual(bind_categorical_values(store,p,'Plant3'),p)
if __name__=='__main__':unittest.main()

