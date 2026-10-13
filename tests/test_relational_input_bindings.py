"""固定源域与输出域、位置和型号交集，覆盖盲测失效模式及反例。"""
import copy,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from test_equipment_node_roles import dataset
from data import Store
from relational_state import compile_delta
from relational_delta_codec import normalize_delta
from relational_query import Graph,execute_task

class InputBindings(unittest.TestCase):
 def setUp(self):
  self.raw=dataset();self.store=self.make(self.raw)
 def make(self,raw):return Store(dataset=[{'kind':k,'file':k+'.csv','sha256':k,'rows':v,'seed':True} for k,v in raw.items()])
 def tearDown(self):self.store.db.close()
 def payload(self,q,classes=None,root='L',tree='pbs',target='pbs'):
  return {'version':2,'handled':True,'mode':'new','tasks':[{'id':1,'action':'new','quote':q,'set':{'kind':'collection','population':'devices','target_tree':target},'root':{'type':'literal','tree':tree,'field':'code','value':root,'quote':q},'classes':classes or [],'filters':[]}]}
 def model_edit(self,q,code='D',tree='config'):
  return {'action':'set','tree':'equipment_class','reference':{'type':'literal','tree':tree,'field':'code','value':code,'quote':q}}
 def run_payload(self,q,p,store=None):
  st=store or self.store;v,a=normalize_delta(p,q,{},st);r,_=compile_delta(v,q,{},st);return r['tasks'][0]['spec'],execute_task(Graph(st),r['tasks'][0]['spec']),a
 def test_missing_explicit_model_keeps_location_and_excludes_sibling(self):
  q='功能位置L下采用构型D的全部现场设备'
  spec,r,a=self.run_payload(q,self.payload(q))
  self.assertEqual(spec['root']['value'],'L');self.assertEqual(spec['classes'],{'equipment_class':'D'});self.assertEqual([x['code'] for x in r['records']],['L&D']);self.assertTrue(a)
 def test_explicit_config_reference_works_in_compatible_selector_slot(self):
  q='功能位置L下采用构型D的全部现场设备'
  spec,r,_=self.run_payload(q,self.payload(q,[self.model_edit(q)]))
  self.assertEqual(spec['classes'],{'equipment_class':'D'});self.assertEqual([x['code'] for x in r['records']],['L&D'])
 def test_real_zero_is_computed_with_both_inputs(self):
  raw=copy.deepcopy(self.raw);raw['pbs']=[x for x in raw['pbs'] if x['对象代码'] not in ('OTHER&D','OTHER&D#p')];st=self.make(raw)
  try:
   q='功能位置OTHER下有没有采用构型D的现场设备？请给数量及全部设备编码'
   spec,r,_=self.run_payload(q,self.payload(q,root='OTHER'),st);self.assertEqual(spec['classes'],{'equipment_class':'D'});self.assertEqual(r['status'],'ok');self.assertEqual(r['metrics'][0]['value'],0)
  finally:st.db.close()
 def test_class_source_with_template_target_preserves_dictionary_identity(self):
  q='按构型树父子关系，设备类TOP下的全部设备型号'
  spec,r,_=self.run_payload(q,self.payload(q,root='TOP',tree='config',target='config'))
  self.assertEqual(spec['root']['tree'],'equipment_class');self.assertEqual(spec['target_tree'],'config');self.assertEqual([x['code'] for x in r['records']],['D','E'])
 def test_explicit_config_category_source_not_changed_to_dictionary(self):
  q='构型TOP下的全部设备型号'
  spec,_,_=self.run_payload(q,self.payload(q,root='TOP',tree='config',target='config'));self.assertEqual(spec['root']['tree'],'config')
 def test_conflicting_model_dictionary_never_selects_sibling_class(self):
  raw=copy.deepcopy(self.raw);raw['equipment_class'][2]['父对象编码']='OTHER';st=self.make(raw)
  try:
   q='功能位置L下采用构型D的全部现场设备'
   with self.assertRaises(ValueError):self.run_payload(q,self.payload(q,[self.model_edit(q)]),st)
  finally:st.db.close()
 def test_missing_model_dictionary_is_not_a_false_zero(self):
  raw=copy.deepcopy(self.raw);raw['equipment_class']=[x for x in raw['equipment_class'] if x['对象编码']!='D'];st=self.make(raw)
  try:
   q='功能位置L下采用构型D的全部现场设备'
   with self.assertRaises(ValueError):self.run_payload(q,self.payload(q,[self.model_edit(q)]),st)
  finally:st.db.close()
 def test_config_class_cannot_be_mislabeled_as_model(self):
  q='功能位置L下采用构型C的全部现场设备'
  with self.assertRaises(ValueError):self.run_payload(q,self.payload(q,[self.model_edit(q,'C')]))
 def test_negative_adoption_does_not_become_positive_selection(self):
  q='功能位置L下没有采用构型D的现场设备'
  with self.assertRaises(ValueError):self.run_payload(q,self.payload(q))
 def test_multiple_model_inputs_are_not_arbitrarily_selected(self):
  q='功能位置L下采用构型D或采用构型E的全部现场设备'
  with self.assertRaises(ValueError):self.run_payload(q,self.payload(q))
 def test_other_explicit_model_is_not_overwritten(self):
  q='功能位置L下采用构型D的全部现场设备'
  with self.assertRaises(ValueError):self.run_payload(q,self.payload(q,[self.model_edit(q,'E')]))
 def test_direct_scope_and_other_class_condition_are_preserved(self):
  q='功能位置L下采用构型D的直属现场设备，并限定部件类B'
  p=self.payload(q,[{'action':'set','tree':'part_class','reference':{'type':'literal','tree':'part_class','field':'code','value':'B','quote':q}}]);p['tasks'][0]['set']['depth']='direct'
  spec,_,_=self.run_payload(q,p);self.assertEqual(spec['depth'],'direct');self.assertEqual(spec['classes'],{'equipment_class':'D','part_class':'B'});self.assertEqual(spec['root']['value'],'L')
 def test_short_task_quote_keeps_explicit_template_prelude(self):
  q='按构型树的父子关系，设备类TOP下的全部设备型号'
  p=self.payload(q,root='TOP',tree='equipment_class',target='config');p['tasks'][0]['quote']=q.split('，')[1]
  spec,r,_=self.run_payload(q,p);self.assertEqual(spec['target_tree'],'config');self.assertEqual([x['code'] for x in r['records']],['D','E'])
 def test_duplicate_model_comparison_is_the_same_scoped_selection(self):
  q='功能位置L下有没有采用构型D的现场设备？请给数量及全部设备编码'
  p=self.payload(q);p['tasks'][0]['compare_root']={'type':'literal','tree':'config','field':'code','value':'D','quote':q}
  spec,r,_=self.run_payload(q,p);self.assertIsNone(spec['compare_root']);self.assertEqual([x['code'] for x in r['records']],['L&D'])
 def test_different_comparison_root_cannot_be_silently_removed(self):
  q='功能位置L下采用构型D的现场设备，对比构型E'
  p=self.payload(q,[self.model_edit(q)]);p['tasks'][0]['compare_root']={'type':'literal','tree':'config','field':'code','value':'E','quote':q}
  spec,_,_=self.run_payload(q,p);self.assertEqual(spec['compare_root']['value'],'E')
 def test_nonadjacent_site_relation_missing_data_blocks_before_model(self):
  from relational_planner import interpret
  from unittest.mock import patch
  raw=copy.deepcopy(self.raw);raw['config']=[x for x in raw['config'] if x['对象代码']!='C'];st=self.make(raw)
  try:
   q='请查设备类C在现场对应的设备有哪些，并给台数'
   with patch('relational_planner.extract',side_effect=AssertionError('真实关联依据缺失不调用模型')):plan,trace=interpret(q,{},'unused',st)
   from relational_query import execute
   from relational_planner import bind
   bind(st,q,plan,{},trace);r=execute(st,plan);self.assertEqual(r['status'],'data_insufficient');self.assertEqual(r['metrics'],[]);self.assertFalse(trace['count_computed'])
  finally:st.db.close()
 def retained_lookup(self,q,tree='equipment_class',field='code',value='C',mutate=None):
  from relational_query import canonical
  spec=canonical({'kind':'relation','root':{'tree':tree,'field':field,'value':value}})
  ctx={'relational_state':{'tasks':[{'id':1,'spec':spec}]}}
  if mutate:mutate(ctx)
  raw={'version':2,'handled':True,'mode':'update','tasks':[{'id':1,'action':'retain'}]}
  adapted,a=normalize_delta(raw,q,ctx,self.store);plan,audit=compile_delta(adapted,q,ctx,self.store);return plan,a
 def test_explicit_repeat_read_same_full_code_reexecutes_the_actual_relation(self):
  p,a=self.retained_lookup('C那个设备是什么？');spec=p['tasks'][0]['spec'];self.assertEqual(spec['root'],{'tree':'equipment_class','field':'code','value':'C'});self.assertEqual(spec['kind'],'relation');self.assertTrue(a);self.assertEqual(execute_task(Graph(self.store),spec)['status'],'ok')
 def test_current_code_can_prove_a_saved_unique_name_identity(self):
  p,_=self.retained_lookup('C那个对象是什么？',field='name',value='类别');self.assertEqual(p['tasks'][0]['spec']['root'],{'tree':'equipment_class','field':'name','value':'类别'})
 def test_repeat_read_does_not_borrow_old_focus_for_a_different_identity(self):
  with self.assertRaises(ValueError):self.retained_lookup('D那个设备是什么？')
 def test_repeat_read_explicit_input_domain_change_requires_a_new_binding(self):
  with self.assertRaises(ValueError):self.retained_lookup('构型C是什么？')
 def test_negative_read_is_not_executed(self):
  with self.assertRaises(ValueError):self.retained_lookup('不要告诉我C是什么')
 def test_pure_control_retention_still_cannot_claim_delivery(self):
  with self.assertRaises(ValueError):self.retained_lookup('C只保留，不再查询')
 def test_saved_collection_cannot_be_reread_as_a_single_object(self):
  from relational_query import canonical
  with self.assertRaises(ValueError):self.retained_lookup('C是什么？',mutate=lambda ctx:ctx['relational_state']['tasks'][0].update(spec=canonical({'kind':'collection','population':'devices','root':{'tree':'equipment_class','field':'code','value':'C'}})))
 def test_multiple_saved_tasks_cannot_be_chosen_by_a_retention_action(self):
  def more(ctx):ctx['relational_state']['tasks'].append({'id':2,'spec':copy.deepcopy(ctx['relational_state']['tasks'][0]['spec'])})
  with self.assertRaises(ValueError):self.retained_lookup('C是什么？',mutate=more)
 def test_missing_current_record_cannot_reuse_an_old_relation_as_a_result(self):
  raw=copy.deepcopy(self.raw);raw['equipment_class']=[x for x in raw['equipment_class'] if x['对象编码']!='C'];old=self.store;self.store=self.make(raw)
  try:
   with self.assertRaises(ValueError):self.retained_lookup('C是什么？')
  finally:self.store.db.close();self.store=old
 def test_deictic_read_without_current_identity_is_not_guessed(self):
  with self.assertRaises(ValueError):self.retained_lookup('那个对象是什么？')
 def missing_context(self,**changes):
  from relational_query import canonical
  return {'relational_state':{'tasks':[{'id':1,'spec':canonical({'kind':'collection','population':'parts','root':{'tree':'pbs','field':'code','value':'L'},'only':'missing_class',**changes})}]}}
 def test_actual_missing_class_boundary_is_delivered_without_a_model_guess(self):
  from relational_planner import interpret,bind
  from relational_query import execute
  from unittest.mock import patch
  raw=copy.deepcopy(self.raw);raw['config']=[x for x in raw['config'] if x['对象代码']!='D#p'];st=self.make(raw)
  try:
   q='是否可以认定这些部件没有类别，或者用上级类别替代？';ctx=self.missing_context()
   with patch('relational_planner.extract',side_effect=AssertionError('登记结论边界不依赖模型分类')):plan,trace=interpret(q,ctx,'unused',st)
   bind(st,q,plan,ctx,trace);r=execute(st,plan);self.assertEqual(r['status'],'ok');self.assertIn('不能据此认定没有类别',r['answer']);self.assertIn('不能用上级类别替代',r['answer']);self.assertEqual([x['code'] for x in r['record_facts']],['L&D#p'])
  finally:st.db.close()
 def test_parent_replacement_question_uses_registered_boundary(self):
  from relational_input_bindings import classification_boundary_request
  self.assertIsNotNone(classification_boundary_request('能否用父级类别代替这些部件？',self.missing_context(),self.store))
 def test_normal_parts_set_is_not_replaced_with_a_missing_only_set(self):
  from relational_input_bindings import classification_boundary_request
  self.assertIsNone(classification_boundary_request('是否可以认定没有类别？',self.missing_context(only=None),self.store))
 def test_boundary_preserves_real_root_depth_and_class_conditions(self):
  from relational_input_bindings import classification_boundary_request
  ctx=self.missing_context(depth='direct',classes={'equipment_class':'C'});p=classification_boundary_request('能否认定这些部件没有类别？',ctx,self.store);s=p['relational_tasks'][0]['spec'];self.assertEqual(s['root']['value'],'L');self.assertEqual(s['depth'],'direct');self.assertEqual(s['classes'],{'equipment_class':'C'})
 def test_missing_subset_display_limit_is_not_expanded_by_boundary(self):
  from relational_input_bindings import classification_boundary_request
  self.assertIsNone(classification_boundary_request('是否可以认定没有类别？',self.missing_context(limit=3),self.store))
 def test_multiple_tasks_are_not_arbitrarily_chosen_for_boundary(self):
  from relational_input_bindings import classification_boundary_request
  ctx=self.missing_context();ctx['relational_state']['tasks'].append({'id':2,'spec':copy.deepcopy(ctx['relational_state']['tasks'][0]['spec'])});self.assertIsNone(classification_boundary_request('是否可以认定没有类别？',ctx,self.store))
 def test_new_identity_is_not_swallowed_by_the_old_missing_scope(self):
  from relational_input_bindings import classification_boundary_request
  self.assertIsNone(classification_boundary_request('OTHER的部件是否可以认定没有类别？',self.missing_context(),self.store))
 def test_pending_unexecuted_request_is_not_a_boundary_evidence_source(self):
  from relational_input_bindings import classification_boundary_request
  ctx=self.missing_context();ctx['pending_business_request']={'tasks':[]};self.assertIsNone(classification_boundary_request('是否可以认定没有类别？',ctx,self.store))
 def test_missing_class_words_do_not_steal_a_health_boundary_question(self):
  from relational_input_bindings import classification_boundary_request
  self.assertIsNone(classification_boundary_request('这些没有类别的部件是否可以认定健康？',self.missing_context(),self.store))

if __name__=='__main__':unittest.main()
