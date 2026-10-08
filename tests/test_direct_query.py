"""2026-10-08 契约：明确的只读查询直接执行，保留真实歧义和依据。"""
import copy,sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from data import Store
from business_request import apply_delta,RequestInvalid,RequestAmbiguous
from request_gateway import reference_context
from query_plan import execute_plan
from query_presentation import attach_basis
from relationship_request import clarification_question
from test_object_scope import delta
import test_filters

class DirectQueryTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.store=Store()
 @classmethod
 def tearDownClass(cls):cls.store.db.close()
 def test_type_and_level_are_independent(self):
  p={'operation':'analyze','entity':{'tree':'config','code':'MOHB01'},'scope':'direct','clarification':'','query':{'target':'config','filters':[]},'analysis':{'kind':'group_count','group_by':'type','order':'desc','limit':100,'numerator':[]}}
  r=execute_plan(self.store,p)
  self.assertEqual({x['cells'][0]:x['cells'][2] for x in r['records']},{'部件':51,'子设备':1})
  attach_basis(r,p);self.assertIn('按对象类型分组',r['business_scope']);self.assertEqual(r['query_basis']['plan'],{k:v for k,v in p.items() if k!='clarification'})
  p['analysis']['group_by']='level';r=execute_plan(self.store,p)
  self.assertEqual([x['cells'] for x in r['records']],[['5','5',52]])
 def test_class_dictionary_cannot_guess_types_from_numbers(self):
  from analytics import validate_analysis
  p={'query':{'target':'equipment_class','filters':[]},'analysis':{'kind':'group_count','group_by':'type','order':'desc','limit':100,'numerator':[]}}
  with self.assertRaises(ValueError):validate_analysis(p)
 def test_new_literal_cannot_be_replaced_by_executed_old_identity(self):
  q='MOHB 那个设备是什么？';ctx={'entity':{'tree':'config','code':'MOHB01'}}
  refs=reference_context(ctx,None,self.store,q)
  d=delta(q,name='MOHB01',scope='confirmed',target='config')
  # 合法继承的条件无需本轮重复提供字面依据。
  oldq='构型MOHB01是什么';_,old,_=apply_delta(delta(oldq,name='MOHB01',scope='explicit',target='config'),None,oldq)
  d['mode']='update';d['tasks'][0].update(base='t1',filters=[])
  with self.assertRaisesRegex(RequestInvalid,'当前完整标识'):apply_delta(d,old,q,refs)
 def test_full_alias_and_pronoun_keep_confirmed_subject(self):
  for q in ('构型对象描述14477是什么','它是什么'):
   refs=reference_context({'entity':{'tree':'config','code':'MOHB01'}},None,self.store,q)
   oldq='构型MOHB01是什么';_,old,_=apply_delta(delta(oldq,name='MOHB01',scope='explicit',target='config'),None,oldq)
   d=delta(q,name='MOHB01',scope='confirmed',target='config');d['mode']='update';d['tasks'][0].update(base='t1',filters=[])
   p,_,_=apply_delta(d,old,q,refs);self.assertEqual(p['query']['filters'][0]['value'],'MOHB01')
 def test_background_mention_does_not_replace_requested_old_subject(self):
  q='MOHB暂不处理；继续查它';refs=reference_context({'entity':{'tree':'config','code':'MOHB01'}},None,self.store,q)
  oldq='构型MOHB01是什么';_,old,_=apply_delta(delta(oldq,name='MOHB01',scope='explicit',target='config'),None,oldq)
  d=delta(q,name='MOHB01',scope='confirmed',target='config');d['mode']='update';d['roles']={'background':[1],'output':[2],'control':[]};d['tasks'][0].update(base='t1',filters=[],spans=[2],request_spans=[2])
  p,_,_=apply_delta(d,old,q,refs);self.assertEqual(p['query']['filters'][0]['value'],'MOHB01')
 def test_only_one_relationship_slot_asked_at_a_time(self):
  task={'scope':'unspecified','population':'unspecified'}
  self.assertEqual(clarification_question(task),'您要统计直接下级，还是全部下级？')
  task['scope']='all';self.assertEqual(clarification_question(task),'您要统计所有下级对象，还是仅统计部件？')
 def test_identity_result_is_not_labelled_descendants(self):
  p={'operation':'attributes','entity':None,'scope':'direct','query':{'target':'config','filters':[{'field':'code','operator':'equals','value':'MOHB01'}]},'properties':['name'],'clarification':''}
  r=execute_plan(self.store,p);attach_basis(r,p);self.assertNotIn('下级',r['business_scope'])

 def test_legacy_descendant_receipt_retains_root_source_for_followup(self):
  from request_gateway import migrate_descendants
  from business_request import ground_identifiers
  q='只数直接部件呢？';refs=reference_context({'entity':{'tree':'config','code':'MOHB01'}},None,self.store,q)
  trace={'reference_context':refs,'context_route':{'decision':{'needs_history':True}}}
  p={'operation':'parts','entity':{'tree':'config','code':'MOHB01'},'scope':'direct','clarification':''}
  with patch('request_checklist.gate',return_value={'decision':'accept','choice':'candidate'}):out=migrate_descendants(self.store,q,p,trace)
  state=ground_identifiers(self.store,trace['business_request_state'],trace['changed_tasks'])
  self.assertEqual(state['tasks'][0]['filters'][0]['value'],'MOHB01')
  self.assertEqual(len(self.store.execute(out)['records']),51)
 def test_explicit_domain_is_not_inferred_from_an_object_name(self):
  from object_scope import explicit_domain
  name='设备类描述1860';refs=reference_context({},None,self.store,name+'是什么')
  self.assertFalse(explicit_domain(name+'是什么','equipment_class',refs))
  point='XJ3ABC002MO.TMP.3ABC112MT.U_Win_H1';q='监测点'+point+'的情况';refs=reference_context({},None,self.store,q)
  self.assertTrue(explicit_domain(q,'points',refs))
  self.assertFalse(explicit_domain('构型还是监测点','points'))

class DirectQueryHttpTests(unittest.TestCase):
 setUpClass=classmethod(test_filters.FilterHttpTests.setUpClass.__func__)
 tearDownClass=classmethod(test_filters.FilterHttpTests.tearDownClass.__func__)
 request=test_filters.FilterHttpTests.request
 def test_clear_complex_query_executes_without_review(self):
  import app,model
  from test_query_review import ReviewHttpTests,plan
  p=plan()
  def interpret(q,c,s,store=None):ReviewHttpTests.model_trace(p,q);return copy.deepcopy(p)
  with patch.object(app,'interpret',side_effect=interpret),patch('request_checklist.gate',return_value={'decision':'accept','choice':'candidate'}):
   r=self.request('/api/query',{'session':'direct-clear','question':'至少50，还不到80','trace':True})
  self.assertEqual(r['status'],'ok');self.assertNotIn('review',r);self.assertIn('query_basis',r)
  self.assertEqual(r['query_basis']['plan']['query'],p['query']);self.assertNotIn('pending_review',app.SESSIONS['direct-clear'])

if __name__=='__main__':unittest.main()
