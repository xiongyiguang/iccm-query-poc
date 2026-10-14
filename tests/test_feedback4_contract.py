"""公共状态、范围及时间等价契约；合成不同对象、反例和数据边界。"""
import copy,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from test_equipment_node_roles import dataset
from data import Store
from relational_query import canonical,execute_task,Graph
from relational_delta_codec import normalize_delta
from relational_state import compile_delta
from relational_continuity import prepared_context,pending_scope
from date_fields import canonical_time_filters
def canonical_year_filters(filters,store):
 from date_fields import canonical_year_filters as calendar_filters
 return canonical_time_filters(calendar_filters(filters,store))
from query_scope import table_count,domain_clarification

class Feedback4Contract(unittest.TestCase):
 def setUp(self):self.store=Store(dataset=[{'kind':k,'file':k+'.csv','sha256':k,'rows':v,'seed':True} for k,v in dataset().items()])
 def tearDown(self):self.store.db.close()
 def focus(self,operation='attributes',code='D'):
  entity={'tree':'config','code':code};return {'entity':entity,'query_receipt':{'operation':operation,'resolved_entity':entity,'scope':'direct'}}
 def collection(self):return {'relational_state':{'tasks':[{'id':1,'spec':canonical({'root':{'tree':'config','field':'code','value':'D'},'kind':'collection','population':'parts','depth':'direct'})}]}}
 def test_attribute_focus_can_be_referenced_as_an_actual_root(self):
  ctx=prepared_context(self.focus(),self.store);q='它有哪些直接部件？';raw={'version':2,'handled':True,'mode':'new','tasks':[{'id':1,'action':'new','quote':q,'root':{'type':'role','task':1,'role':'root','quote':'它'},'set':{'kind':'collection','population':'parts','depth':'direct'},'classes':[],'filters':[]}]}
  p,_=compile_delta(normalize_delta(raw,q,ctx,self.store)[0],q,ctx,self.store);self.assertEqual(p['tasks'][0]['spec']['root']['value'],'D');self.assertEqual(execute_task(Graph(self.store),p['tasks'][0]['spec'])['population_facts']['part_total'],1)
 def test_parts_focus_imports_the_actual_depth(self):self.assertEqual(prepared_context(self.focus('parts'),self.store)['relational_state']['tasks'][0]['spec']['depth'],'direct')
 def test_unresolved_draft_does_not_become_an_executed_focus(self):
  ctx=self.focus();ctx['pending_business_request']={'tasks':[]};self.assertNotIn('relational_state',prepared_context(ctx,self.store))
 def test_missing_record_cannot_become_a_focus(self):self.assertNotIn('relational_state',prepared_context(self.focus(code='MISSING'),self.store))
 def test_receipt_and_focus_must_match(self):
  ctx=self.focus();ctx['query_receipt']['resolved_entity']={'tree':'config','code':'E'};self.assertNotIn('relational_state',prepared_context(ctx,self.store))
 def test_measurement_receipt_physical_pbs_address_is_not_a_relation_focus(self):
  entity={'tree':'pbs','code':'L&D#p'};ctx={'entity':entity,'query_receipt':{'operation':'attributes','resolved_entity':entity,'scope':'direct','query':{'target':'points','filters':[]},'grain':'measurement_record'}}
  self.assertNotIn('relational_state',prepared_context(ctx,self.store))
 def test_child_receipt_of_multiple_tasks_is_not_a_global_single_focus(self):
  ctx=self.focus();ctx['business_request']={'tasks':[{'id':'t1','operation':'attributes'},{'id':'t2','operation':'attributes'}]};self.assertNotIn('relational_state',prepared_context(ctx,self.store))
 def test_multitask_measurement_owner_survives_a_child_attribute_response(self):
  from relational_planner import interpret
  from unittest.mock import patch
  entity={'tree':'pbs','code':'L&D#p'};ctx={'entity':entity,'query_receipt':{'operation':'attributes','resolved_entity':entity,'scope':'direct','query':{'target':'points','filters':[]},'grain':'measurement_record'},'business_request':{'tasks':[{'id':'t1','operation':'attributes','target':'points'},{'id':'t2','operation':'attributes','target':'points'}]}}
  with patch('relational_planner.extract',side_effect=AssertionError('测量原表的实际多任务不能按物理地址变成Graph任务')):self.assertIsNone(interpret('第一项改为只查点的名称，第二项不变',ctx,'unused',self.store))
 def draft(self):
  ctx=self.collection();ctx['pending_business_request']={'tasks':[{'id':'t1','operation':'descendants','target':'config','scope':'unspecified','population':'parts','filters':[{'field':'code','operator':'equals','value':'E'}]}]};return ctx
 def test_scope_answer_uses_pending_root_instead_of_last_success(self):
  p=pending_scope('直接下级',self.draft(),self.store);self.assertEqual((p['relational_tasks'][0]['spec']['root']['value'],p['relational_tasks'][0]['spec']['depth']),('E','direct'))
 def test_scope_answer_does_not_accept_extra_identity(self):self.assertIsNone(pending_scope('直接下级，查D',self.draft(),self.store))
 def test_multiple_drafts_are_not_arbitrarily_selected(self):
  ctx=self.draft();ctx['pending_business_request']['tasks']*=2;self.assertIsNone(pending_scope('直接下级',ctx,self.store))
 def test_scope_answer_requires_actual_unique_root(self):
  ctx=self.draft();ctx['pending_business_request']['tasks'][0]['filters'][0]['value']='MISSING';self.assertIsNone(pending_scope('直接下级',ctx,self.store))
 def rebind(self,q,mode='new',root='E',fields=None):
  raw={'version':2,'handled':True,'mode':mode,'tasks':[{'id':1,'action':mode,'quote':q,'root':{'type':'literal','tree':'config','field':'code','value':root,'quote':q},'set':fields or {'kind':'collection','population':'parts','depth':'all'},'classes':[],'filters':[]}]}
  ctx=self.collection();p,_=compile_delta(normalize_delta(raw,q,ctx,self.store)[0],q,ctx,self.store);return p['tasks'][0]['spec']
 def test_simple_root_rebind_keeps_depth_across_multiple_turns(self):
  self.assertEqual(self.rebind('构型E下面有哪些部件？')['depth'],'direct')
 def test_explicit_all_depth_changes_the_scope(self):self.assertEqual(self.rebind('构型E的全部下级部件有哪些？')['depth'],'all')
 def test_cross_table_code_keeps_source_only_for_same_simple_collection(self):
  # E在构型和设备类表同码，更新该构型集合允许继承原来源域。
  self.assertEqual(self.rebind('E下面有哪些部件？')['root']['tree'],'config')
 def test_full_default_representation_does_not_reset_continuous_depth(self):
  f={'kind':'collection','population':'parts','depth':'all','group_by':None,'properties':[],'limit':None,'sort':['code'],'only':None,'boundary':None,'target_tree':None}
  self.assertEqual(self.rebind('E下面有哪些部件？',fields=f)['depth'],'direct')
 def test_nested_empty_comparison_representation_keeps_same_continuity(self):
  f={'kind':'collection','population':'parts','depth':'direct','properties':[],'limit':None,'sort':['code'],'only':None,'boundary':None,'compare_root':None,'target_tree':None}
  self.assertEqual(self.rebind('E下面有哪些部件？',fields=f)['depth'],'direct')
 def test_explicit_new_query_does_not_inherit_depth(self):self.assertEqual(self.rebind('新问题，构型E下面有哪些部件？')['depth'],'all')
 def test_repeat_collection_reexecutes_same_actual_scope(self):
  q='构型D下面有哪些部件？';raw={'version':2,'handled':True,'mode':'update','tasks':[{'id':1,'action':'retain'}]};ctx=self.collection();p,_=compile_delta(normalize_delta(raw,q,ctx,self.store)[0],q,ctx,self.store);self.assertEqual(p['tasks'][0]['spec']['depth'],'direct')
 def test_retain_does_not_query_an_unmentioned_or_different_root(self):
  ctx=self.collection();raw={'version':2,'handled':True,'mode':'update','tasks':[{'id':1,'action':'retain'}]}
  for q in ('构型E下面有哪些部件？','构型D只保留，不查询','构型D下面有哪些部件，不要执行'):
   with self.subTest(q=q),self.assertRaises(ValueError):compile_delta(normalize_delta(raw,q,ctx,self.store)[0],q,ctx,self.store)
 def test_same_time_formats_are_identical(self):
  a=canonical_year_filters([('time','date_equals','1970-01-01T08:00')],self.store);b=canonical_year_filters([('time','date_equals','1970-01-01T08:00:00')],self.store);self.assertEqual(a,b)
 def test_same_time_zone_offsets_are_identical(self):self.assertEqual(canonical_year_filters([('time','date_equals','2025-01-01T08:00+08:00')],self.store),canonical_year_filters([('time','date_equals','2025-01-01T00:00Z')],self.store))
 def test_calendar_day_and_instant_are_not_equivalent(self):self.assertNotEqual(canonical_year_filters([('time','date_equals','2025-01-01')],self.store),canonical_year_filters([('time','date_equals','2025-01-01T00:00')],self.store))
 def test_fractional_seconds_are_not_lost(self):self.assertNotEqual(canonical_year_filters([('time','date_equals','2025-01-01T00:00:00.1')],self.store),canonical_year_filters([('time','date_equals','2025-01-01T00:00:00.2')],self.store))
 def test_explicit_table_count_is_not_a_root_query(self):
  from model import interpret,bind_references
  from query_plan import execute_plan
  q='构型树里一共有多少个对象？';p=interpret(q,{},None,self.store);p=bind_references(self.store,q,p,{});r=execute_plan(self.store,p);self.assertEqual(r['goal_receipt']['population'],len(dataset()['config']));self.assertTrue(r['goal_receipt']['completed'])
 def test_table_scope_applies_to_other_registered_tables(self):
  self.assertEqual(table_count('设备类表里面有多少条记录？',self.store)['query']['target'],'equipment_class')
 def test_filtered_node_or_negative_query_is_not_unconditionally_counted(self):
  for q in ('构型树D下有多少对象？','构型树里报警对象有多少？','不要统计构型树里有多少对象','构型树和PBS表一共有多少对象？','测点表有多少不同编码？'):
   self.assertIsNone(table_count(q,self.store),q)
 def test_ambiguous_relation_gets_business_clarification(self):self.assertIsNotNone(domain_clarification('D对应的设备类是什么？',{},self.store))
 def test_explicit_source_domain_does_not_get_extra_clarification(self):self.assertIsNone(domain_clarification('构型D对应的设备类是什么？',{},self.store))
 def model_quantity(self,q,limit='99'):
  from business_request import resolve_request_actions
  from result_goal import default_goal
  return resolve_request_actions({'version':10,'mode':'new','roles':{'background':[],'output':[1],'control':[]},'tasks':[{'base':None,'action':'request','request_spans':[1],'spans':[1],'set':{'result_goal':{**default_goal('search'),'kind':'sort','field':'time','direction':'desc','limit':limit}}}]},q,'base')['tasks'][0]['set']['result_goal']
 def test_model_integer_string_is_normalized_only_from_current_quantity_source(self):self.assertEqual(self.model_quantity('全部记录按时间排序，返回前99条'.replace('，',''))['limit'],99)
 def test_quantity_normalization_keeps_invalid_bounds_for_the_strict_validator(self):
  from result_goal import validate_goal,GoalConstraintError
  with self.assertRaises(GoalConstraintError):validate_goal(self.model_quantity('返回前101条',limit='101'),'search','points')
 def test_quantity_in_object_name_or_without_source_is_not_normalized(self):
  for q in ('读取“前99条”的记录','读取名为前99条的记录','按时间排序','不要返回前99条'):
   self.assertEqual(self.model_quantity(q)['limit'],'99')
 def test_execution_api_still_rejects_string_integer(self):
  from result_goal import validate_goal,default_goal
  with self.assertRaises(ValueError):validate_goal({**default_goal('search'),'kind':'sort','field':'time','direction':'desc','limit':'99'},'search','points')
 def test_scalar_multitask_owner_does_not_enter_graph_extraction(self):
  from relational_planner import interpret
  from unittest.mock import patch
  ctx={'business_request':{'tasks':[{'id':'t1','operation':'attributes'},{'id':'t2','operation':'attributes'}]}}
  with patch('relational_planner.extract',side_effect=AssertionError('实际类型化多任务由原编译器持有')):self.assertIsNone(interpret('第一项改为只查名称，第二项不变',ctx,'unused',self.store))

if __name__=='__main__':unittest.main()
