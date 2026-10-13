"""反向集合目标域与源身份分离，不按业务编码或名称前缀判断。"""
import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from test_equipment_node_roles import dataset
from data import Store
from relational_query import Graph,canonical,execute_task
from relational_state import compile_delta
class Targets(unittest.TestCase):
 def setUp(self):
  self.raw=dataset();self.store=Store(dataset=[{'kind':k,'file':k+'.csv','sha256':k,'rows':v,'seed':True} for k,v in self.raw.items()]);self.g=Graph(self.store)
 def tearDown(self):self.store.db.close()
 def query(self,code='D',tree='config',target='pbs',**extra):return canonical({'root':{'tree':tree,'field':'code','value':code},'kind':'collection','population':'devices','target_tree':target,**extra})
 def test_model_reverse_keeps_two_positions_and_excludes_sibling(self):
  r=execute_task(self.g,self.query());self.assertEqual([x['code'] for x in r['records']],['L&D','OTHER&D']);self.assertIn('功能位置编码',r['columns'])
 def test_class_reverse_keeps_all_models(self):self.assertEqual(len(execute_task(self.g,self.query('C'))['records']),3)
 def test_config_default_remains_template_children(self):self.assertEqual(execute_task(self.g,self.query(target=None,population='parts'))['record_facts'][0]['code'],'D#p')
 def test_dictionary_class_to_config_models(self):self.assertEqual([x['code'] for x in execute_task(self.g,self.query('C','equipment_class','config'))['records']],['D','E'])
 def test_dictionary_direct_and_all_preserve_depth(self):self.assertEqual(len(execute_task(self.g,self.query('TOP','equipment_class','config',depth='direct'))['records']),0);self.assertEqual(len(execute_task(self.g,self.query('TOP','equipment_class','config'))['records']),2)
 def test_dictionary_model_relation_preserves_subject_and_counterpart(self):
  r=execute_task(self.g,canonical({'root':{'tree':'equipment_class','field':'code','value':'D'},'kind':'relation'}));self.assertEqual(r['relation_facts']['subject'][0]['tree'],'equipment_class');self.assertEqual(r['relation_facts']['config'][0]['code'],'D');self.assertEqual(r['relation_facts']['equipment_class'][0]['code'],'C')
 def test_missing_counterpart_relation_keeps_known_subject(self):
  self.g.objects.pop(('config','D'));r=execute_task(self.g,canonical({'root':{'tree':'equipment_class','field':'code','value':'D'},'kind':'relation'}));self.assertEqual(r['relation_facts']['subject'][0]['code'],'D');self.assertFalse(r['relation_facts']['config']);self.assertTrue(any('缺少' in x['reason'] for x in r['missing_links']))
 def test_conflict_counterpart_does_not_emit_false_template_zero(self):
  self.g.objects[('config','D')]['parent']='E';r=execute_task(self.g,self.query('D','equipment_class','config'));self.assertEqual(r['status'],'data_insufficient');self.assertEqual(r['metrics'],[])
 def test_known_model_with_no_instances_is_real_zero(self):
  self.g.objects={k:v for k,v in self.g.objects.items() if k[0]!='pbs'};r=execute_task(self.g,self.query());self.assertEqual(r['status'],'ok');self.assertEqual(r['metrics'][0]['value'],0)
 def test_same_tree_explicit_target_equivalent_to_default(self):self.assertEqual(self.query(target='config'),self.query(target=None))
 def test_target_not_valid_for_single_relation(self):
  with self.assertRaises(ValueError):canonical({'root':{'tree':'config','field':'code','value':'D'},'kind':'relation','target_tree':'pbs'})
 def test_target_domain_requires_source_evidence(self):
  p={'version':2,'handled':True,'mode':'new','tasks':[{'id':1,'action':'new','quote':'构型D下的部件','set':{'kind':'collection','population':'parts','target_tree':'pbs'},'root':{'type':'literal','tree':'config','field':'code','value':'D','quote':'构型D'},'classes':[],'filters':[]}]}
  with self.assertRaises(ValueError):compile_delta(p,'构型D下的部件',{},self.store)
 def test_relation_set_with_redundant_destination_uses_fixed_roles(self):
  from relational_delta_codec import normalize_delta
  q='现场设备L&D对应的构型和设备类'
  p={'version':2,'handled':True,'mode':'new','tasks':[{'id':1,'action':'new','quote':q,'set':{'kind':'relation','population':'devices','target_tree':'config'},'root':{'type':'literal','tree':'pbs','field':'code','value':'L&D','quote':q},'classes':[],'filters':[]}]}
  v,a=normalize_delta(p,q,{},self.store);r,_=compile_delta(v,q,{},self.store);self.assertIsNone(r['tasks'][0]['spec']['target_tree']);self.assertEqual(r['tasks'][0]['spec']['kind'],'relation')
 def test_declared_template_population_constrains_objects(self):
  from relational_delta_codec import normalize_delta
  q='设备类类别下面的全部设备构型，列出全部编码'
  p={'version':2,'handled':True,'mode':'new','tasks':[{'id':1,'action':'new','quote':q,'set':{'kind':'collection','population':'objects','target_tree':'config'},'root':{'type':'literal','tree':'equipment_class','field':'code','value':'C','quote':q},'classes':[],'filters':[]}]}
  v,a=normalize_delta(p,q,{},self.store);r,_=compile_delta(v,q,{},self.store);self.assertEqual(r['tasks'][0]['spec']['population'],'devices')
 def test_unknown_role_guard_blocks_model_and_false_zero(self):
  from unittest.mock import patch
  from relational_planner import interpret
  self.raw['config'][2]['父对象代码']='E'
  st=Store(dataset=[{'kind':k,'file':k+'.csv','sha256':k,'rows':v,'seed':True} for k,v in self.raw.items()])
  try:
   with patch('relational_planner.extract',side_effect=AssertionError('数据前提失败不调用模型')):
    plan,trace=interpret('设备类表完整编码D对应的现场设备有哪些',{},'unused',st)
   r=execute_task(Graph(st),canonical({'kind':'collection','population':'devices','classes':{'equipment_class':'D'}}));self.assertFalse(trace['count_computed']);from relational_planner import bind;self.assertEqual(bind(st,'设备类表完整编码D对应的现场设备有哪些',plan,{},trace),plan);self.assertTrue(trace['gateway']['data_rechecked']);self.assertEqual(r['status'],'data_insufficient');self.assertEqual(r['metrics'],[])
  finally:st.db.close()
 def test_valid_and_scoped_query_not_short_circuited_by_data_guard(self):
  from unittest.mock import patch
  from relational_planner import interpret
  with patch('relational_planner.extract',return_value={'handled':False}) as m:
   self.assertIsNone(interpret('PBS功能位置L下设备类表完整编码D对应的现场设备有哪些',{},'unused',self.store));self.assertEqual(m.call_count,1)
 def test_all_template_objects_not_narrowed_to_device_models(self):
  from relational_delta_codec import normalize_delta
  q='设备类类别下全部构型对象，包括设备构型、子设备和部件'
  p={'version':2,'handled':True,'mode':'new','tasks':[{'id':1,'action':'new','quote':q,'set':{'kind':'collection','population':'objects','target_tree':'config'},'root':{'type':'literal','tree':'equipment_class','field':'code','value':'C','quote':q},'classes':[],'filters':[]}]}
  v,a=normalize_delta(p,q,{},self.store);self.assertEqual(v['tasks'][0]['set']['population'],'objects')
 def test_config_category_self_scope_not_all_instances(self):self.assertEqual(len(execute_task(self.g,self.query('C',depth='self'))['records']),0)
 def test_unknown_role_guard_does_not_choose_ambiguous_or_other_input_tree(self):
  from relational_planner import data_prerequisite
  self.raw['config'][2]['父对象代码']='E'
  st=Store(dataset=[{'kind':k,'file':k+'.csv','sha256':k,'rows':v,'seed':True} for k,v in self.raw.items()])
  try:
   for q in ['编码D在全PBS的现场设备有哪些','构型D在全PBS的现场设备有哪些？给所属设备类']:
    with self.subTest(question=q):self.assertIsNone(data_prerequisite(q,{},st))
  finally:st.db.close()
 def test_data_guard_gateway_rejects_modified_plan(self):
  from relational_planner import interpret,bind
  from unittest.mock import patch
  self.raw['config'][2]['父对象代码']='E'
  st=Store(dataset=[{'kind':k,'file':k+'.csv','sha256':k,'rows':v,'seed':True} for k,v in self.raw.items()])
  try:
   with patch('relational_planner.extract',side_effect=AssertionError('不能调用模型')):plan,trace=interpret('设备类表完整编码D对应的现场设备有哪些',{},'unused',st)
   plan['relational_tasks'][0]['spec']['population']='parts'
   with self.assertRaises(ValueError):bind(st,'设备类表完整编码D对应的现场设备有哪些',plan,{},trace)
  finally:st.db.close()
 def test_actual_reference_capabilities_expose_roles_without_counts(self):
  from relational_capabilities import reference_capabilities
  r=reference_capabilities(self.store,[{'domain':'equipment_class','value':'D'},{'domain':'config','value':'D'}]);self.assertEqual(len(r),2)
  self.assertEqual(r[0]['relation']['roles']['equipment_class']['code'],'C');self.assertTrue(any(x['target_tree']=='pbs' for x in r[1]['collections']));self.assertNotIn('answer',str(r));self.assertNotIn('record_count',str(r))
 def test_misplaced_config_selector_restores_original_domain(self):
  from relational_delta_codec import normalize_delta
  q='设备构型D的全部现场部件，给完整编码'
  p={'version':2,'handled':True,'mode':'new','tasks':[{'id':1,'action':'new','quote':q,'set':{'kind':'collection','population':'parts'},'root':{'type':'global','quote':q},'classes':[{'action':'set','tree':'equipment_class','reference':{'type':'literal','tree':'equipment_class','field':'code','value':'D','quote':q}}],'filters':[]}]}
  v,a=normalize_delta(p,q,{},self.store);r,_=compile_delta(v,q,{},self.store);spec=r['tasks'][0]['spec'];self.assertEqual(spec['root']['tree'],'config');self.assertEqual(spec['target_tree'],'pbs');self.assertEqual(spec['classes'],{});self.assertEqual(len(execute_task(self.g,spec)['records']),2)
 def test_dictionary_anchor_not_extra_site_filter_for_template(self):
  from relational_delta_codec import normalize_delta
  q='设备类类别的全部设备构型，列全编码'
  root={'type':'literal','tree':'equipment_class','field':'code','value':'C','quote':q}
  p={'version':2,'handled':True,'mode':'new','tasks':[{'id':1,'action':'new','quote':q,'set':{'kind':'collection','population':'devices','target_tree':'config'},'root':root,'classes':[{'action':'set','tree':'equipment_class','reference':root}],'filters':[]}]}
  v,a=normalize_delta(p,q,{},self.store);self.assertEqual(v['tasks'][0]['classes'],[])
 def test_explicit_additional_class_filter_kept_for_template(self):
  from relational_delta_codec import normalize_delta
  q='设备类类别的全部设备构型，再按设备类类别筛选，列全编码'
  root={'type':'literal','tree':'equipment_class','field':'code','value':'C','quote':q}
  p={'version':2,'handled':True,'mode':'new','tasks':[{'id':1,'action':'new','quote':q,'set':{'kind':'collection','population':'devices','target_tree':'config'},'root':root,'classes':[{'action':'set','tree':'equipment_class','reference':root}],'filters':[]}]}
  v,a=normalize_delta(p,q,{},self.store);self.assertEqual(len(v['tasks'][0]['classes']),1)
 def test_explicit_template_goal_not_defaulted_to_site(self):
  from relational_delta_codec import normalize_delta
  q='设备类类别下的直属设备构型，列全构型设备编码，不看现场设备'
  p={'version':2,'handled':True,'mode':'new','tasks':[{'id':1,'action':'new','quote':q,'set':{'kind':'collection','population':'devices','depth':'direct'},'root':{'type':'literal','tree':'equipment_class','field':'code','value':'C','quote':q},'classes':[],'filters':[]}]}
  v,a=normalize_delta(p,q,{},self.store);r,_=compile_delta(v,q,{},self.store);self.assertEqual(r['tasks'][0]['spec']['target_tree'],'config');self.assertEqual(r['tasks'][0]['spec']['depth'],'direct')
 def test_missing_role_capability_is_known_but_blocked_not_unsupported(self):
  from relational_capabilities import reference_capabilities
  self.g.objects.pop(('config','D'))
  self.raw['config']=[x for x in self.raw['config'] if x['对象代码']!='D']
  st=Store(dataset=[{'kind':k,'file':k+'.csv','sha256':k,'rows':v,'seed':True} for k,v in self.raw.items()])
  try:
   r=reference_capabilities(st,[{'domain':'equipment_class','value':'D'}])[0];self.assertTrue(r['blocked_reason']);self.assertTrue(all(x['blocked'] for x in r['collections']));self.assertNotIn('record_count',str(r))
  finally:st.db.close()
 def test_redundant_site_target_needs_no_new_domain_keyword(self):
  q='L下的部件'
  p={'version':2,'handled':True,'mode':'new','tasks':[{'id':1,'action':'new','quote':q,'set':{'kind':'collection','population':'parts','target_tree':'pbs'},'root':{'type':'literal','tree':'pbs','field':'code','value':'L','quote':q},'classes':[],'filters':[]}]}
  r,_=compile_delta(p,q,{},self.store);self.assertIsNone(r['tasks'][0]['spec']['target_tree'])
 def test_equivalent_remove_wrapper_keeps_strict_action(self):
  from relational_delta_codec import normalize_delta
  before=canonical({'kind':'collection','population':'parts','classes':{'equipment_class':'D'}});q='取消设备类条件'
  ctx={'relational_state':{'tasks':[{'id':1,'spec':before,'resolved':{}}]}}
  p={'version':2,'handled':True,'mode':'update','tasks':[{'id':1,'action':'update','quote':q,'set':{},'classes':{'remove':{'action':'remove','tree':'equipment_class','quote':q}},'filters':[]}]}
  v,a=normalize_delta(p,q,ctx,self.store);r,_=compile_delta(v,q,ctx,self.store);self.assertEqual(r['tasks'][0]['spec']['classes'],{})
 def test_count_only_class_preserves_two_metrics_and_direct_scope(self):
  from relational_delta_codec import normalize_delta
  q='构型D直属部件数量和不同部件类数量'
  p={'version':2,'handled':True,'mode':'new','tasks':[{'id':1,'action':'new','quote':q,'set':{'kind':'collection','population':'parts','depth':'direct','group_by':'class'},'root':{'type':'literal','tree':'config','field':'code','value':'D','quote':q},'classes':[],'filters':[]}]}
  v,a=normalize_delta(p,q,{},self.store);r,_=compile_delta(v,q,{},self.store);spec=r['tasks'][0]['spec'];out=execute_task(self.g,spec);self.assertEqual(spec['depth'],'direct');self.assertEqual(out['population_facts']['part_total'],1);self.assertEqual(out['population_facts']['distinct_resolved_classes'],1);self.assertEqual([x['code'] for x in out['record_facts']],['D#p'])
 def test_missing_predicate_not_reinterpreted_on_projection_update(self):
  from relational_delta_codec import normalize_delta
  before=canonical({'kind':'collection','population':'points','only':'unmatched'});q='从刚才未关联记录中取前三条，列测量值'
  ctx={'relational_state':{'tasks':[{'id':1,'spec':before,'resolved':{}}]}}
  p={'version':2,'handled':True,'mode':'update','tasks':[{'id':1,'action':'update','quote':q,'set':{'only':'missing_class','limit':3,'properties':['value']},'classes':[],'filters':[]}]}
  v,a=normalize_delta(p,q,ctx,self.store);r,_=compile_delta(v,q,ctx,self.store);self.assertEqual(r['tasks'][0]['spec']['only'],'unmatched')
 def test_point_input_keeps_source_and_delivers_pbs_role(self):
  from relational_delta_codec import normalize_delta
  q='测点编码L&D#p沿精确PBS记录查最近现场部件'
  p={'version':2,'handled':True,'mode':'new','tasks':[{'id':1,'action':'new','quote':q,'set':{'kind':'relation','population':'objects'},'root':{'type':'literal','tree':'pbs','field':'code','value':'L&D#p','quote':q},'classes':[],'filters':[]}]}
  v,a=normalize_delta(p,q,{},self.store);r,_=compile_delta(v,q,{},self.store);self.assertEqual(r['tasks'][0]['spec']['root']['tree'],'points');out=execute_task(self.g,r['tasks'][0]['spec']);self.assertEqual(out['relation_facts']['pbs'][0]['code'],'L&D#p')
 def test_unqualified_global_object_stats_handoff_to_domain_clarification(self):
  from relational_planner import interpret
  from unittest.mock import patch
  with patch('relational_planner.extract',return_value={'handled':True,'tasks':[{'id':1,'spec':canonical({'kind':'collection','population':'objects','group_by':'type'})}]}):
   self.assertIsNone(interpret('按对象层级统计对象编码',{},'unused',self.store))
 def test_unrequested_direct_depth_uses_program_all_default(self):
  from relational_delta_codec import normalize_delta
  q='构型D下的构型部件有多少个'
  p={'version':2,'handled':True,'mode':'new','tasks':[{'id':1,'action':'new','quote':q,'set':{'kind':'collection','population':'parts','depth':'direct'},'root':{'type':'literal','tree':'config','field':'code','value':'D','quote':q},'classes':[],'filters':[]}]}
  v,a=normalize_delta(p,q,{},self.store);r,_=compile_delta(v,q,{},self.store);self.assertEqual(r['tasks'][0]['spec']['depth'],'all')
 def test_actual_location_missing_group_subset_cannot_switch_to_class(self):
  from relational_delta_codec import normalize_delta
  q='从刚才未关联记录中取前三条，列测量值'
  old=canonical({'kind':'collection','population':'points','group_by':'location'});ctx={'relational_state':{'tasks':[{'id':1,'spec':old,'resolved':{}}]}}
  p={'version':2,'handled':True,'mode':'update','tasks':[{'id':1,'action':'update','quote':q,'set':{'group_by':None,'only':'missing_class','limit':3,'properties':['value']},'classes':[],'filters':[]}]}
  v,a=normalize_delta(p,q,ctx,self.store);r,_=compile_delta(v,q,ctx,self.store);self.assertEqual(r['tasks'][0]['spec']['only'],'unmatched')
 def test_explicit_cancel_class_is_compiled_even_without_model_edit(self):
  from relational_delta_codec import normalize_delta
  q='改查PBS现场设备L&D的全部部件，不再统计这个设备类的所有设备'
  old=canonical({'kind':'collection','population':'devices','classes':{'equipment_class':'C'}});ctx={'relational_state':{'tasks':[{'id':1,'spec':old,'resolved':{}}]}}
  p={'version':2,'handled':True,'mode':'update','tasks':[{'id':1,'action':'update','quote':q,'set':{'population':'parts'},'root':{'type':'literal','tree':'pbs','field':'code','value':'L&D','quote':q},'classes':[],'filters':[]}]}
  v,a=normalize_delta(p,q,ctx,self.store);r,_=compile_delta(v,q,ctx,self.store);self.assertEqual(r['tasks'][0]['spec']['classes'],{})
 def test_explicit_full_codes_keeps_detail_for_two_count_metrics(self):
  from relational_delta_codec import normalize_delta
  q='构型D直属部件数量和不同部件类数量，列全构型部件编码'
  p={'version':2,'handled':True,'mode':'new','tasks':[{'id':1,'action':'new','quote':q,'set':{'kind':'collection','population':'parts','depth':'direct','group_by':'class'},'root':{'type':'literal','tree':'config','field':'code','value':'D','quote':q},'classes':[],'filters':[]}]}
  v,a=normalize_delta(p,q,{},self.store);r,_=compile_delta(v,q,{},self.store);self.assertIsNone(r['tasks'][0]['spec']['group_by']);self.assertEqual(execute_task(self.g,r['tasks'][0]['spec'])['records'][0]['code'],'D#p')
 def test_redundant_null_global_root_update_keeps_scope(self):
  from relational_delta_codec import normalize_delta
  q='保留这个设备类，列出全部部件'
  old=canonical({'kind':'collection','population':'parts','classes':{'equipment_class':'C'}});ctx={'relational_state':{'tasks':[{'id':1,'spec':old,'resolved':{}}]}}
  p={'version':2,'handled':True,'mode':'update','tasks':[{'id':1,'action':'update','quote':q,'set':{'group_by':None},'root':None,'classes':[],'filters':[]}]}
  v,a=normalize_delta(p,q,ctx,self.store);r,_=compile_delta(v,q,ctx,self.store);self.assertIsNone(r['tasks'][0]['spec']['root']);self.assertEqual(r['tasks'][0]['spec']['classes'],old['classes'])
 def test_null_update_cannot_clear_nonempty_root(self):
  from relational_delta_codec import normalize_delta
  q='列出全部部件';old=canonical({'kind':'collection','population':'parts','root':{'tree':'pbs','field':'code','value':'L'}});ctx={'relational_state':{'tasks':[{'id':1,'spec':old,'resolved':{}}]}}
  p={'version':2,'handled':True,'mode':'update','tasks':[{'id':1,'action':'update','quote':q,'set':{},'root':None,'classes':[],'filters':[]}]}
  with self.assertRaises(ValueError):compile_delta(normalize_delta(p,q,ctx,self.store)[0],q,ctx,self.store)
 def test_known_target_hint_for_single_relation_keeps_actual_root(self):
  from relational_delta_codec import normalize_delta
  q='设备类表编码C的原记录'
  p={'version':2,'handled':True,'mode':'new','tasks':[{'id':1,'action':'new','quote':q,'set':{'kind':'relation','population':'objects','target_tree':'equipment_class'},'root':{'type':'literal','tree':'equipment_class','field':'code','value':'C','quote':q},'classes':[],'filters':[]}]}
  v,a=normalize_delta(p,q,{},self.store);r,_=compile_delta(v,q,{},self.store);self.assertIsNone(r['tasks'][0]['spec']['target_tree']);self.assertEqual(r['tasks'][0]['spec']['root']['tree'],'equipment_class')
 def test_reverse_receipt_matches_delivered_pbs_and_preserves_config_subject(self):
  from relational_query import execute
  q=self.query();r=execute(self.store,{'relational_tasks':[{'id':1,'spec':q}]})
  self.assertEqual([x['code'] for x in r['record_facts']],['L&D','OTHER&D']);self.assertEqual(r['entity']['tree'],'config');self.assertEqual(r['query_receipt']['query']['target'],'pbs');self.assertEqual(r['query_receipt']['grain'],'pbs_object');self.assertEqual(r['grain'],'pbs_object')
 def test_dictionary_template_receipt_matches_actual_config_objects(self):
  from relational_query import execute
  q=self.query('C','equipment_class','config');r=execute(self.store,{'relational_tasks':[{'id':1,'spec':q}]})
  self.assertEqual([x['code'] for x in r['record_facts']],['D','E']);self.assertEqual(r['entity']['tree'],'equipment_class');self.assertEqual(r['query_receipt']['query']['target'],'config');self.assertEqual(r['query_receipt']['grain'],'config_object')
 def test_reverse_parts_receipt_cannot_claim_template_parts(self):
  from relational_query import execute
  q=self.query(population='parts');r=execute(self.store,{'relational_tasks':[{'id':1,'spec':q}]})
  self.assertEqual([x['code'] for x in r['record_facts']],['L&D#p','OTHER&D#p']);self.assertEqual(r['query_receipt']['query']['target'],'pbs');self.assertEqual(r['query_receipt']['grain'],'pbs_object')

 def handoff_payload(self,root):
  q='全PBS范围采用构型树编码D的现场设备，完整编码与位置逐台列出并给总数'
  return q,{'version':2,'handled':True,'mode':'new','tasks':[{'id':1,'action':'new','quote':q,'set':{'kind':'collection','population':'devices','target_tree':'pbs'},'root':root,'classes':[],'filters':[]}]}
 def extract_responses(self,question,context,payloads):
  from unittest.mock import patch,Mock
  import io,json
  from relational_planner import extract
  replies=iter(payloads);calls=[]
  def open_response(request,timeout):
   calls.append(request)
   return io.BytesIO(json.dumps({'model':'synthetic','choices':[{'message':{'content':json.dumps(next(replies))}}]}).encode())
  trace={}
  with patch('relational_planner.urllib.request.build_opener',return_value=Mock(open=open_response)):
   result=extract(question,context,'synthetic-key','synthetic-model',trace,_store=self.store)
  return result,trace,len(calls)
 def test_explicit_relation_lost_input_retries_instead_of_legacy_handoff(self):
  from relational_planner import literal_relation_inputs
  q,bad=self.handoff_payload({'type':'global','quote':'全PBS范围'})
  _,good=self.handoff_payload({'type':'literal','tree':'config','field':'code','value':'D','quote':'构型树编码D'})
  context={'relational_required':True,'relational_bound_inputs':literal_relation_inputs(q,self.store)};self.assertEqual(context['relational_bound_inputs'],[{'tree':'config','field':'identity','value':'D'}])
  result,trace,calls=self.extract_responses(q,context,[bad,good]);self.assertTrue(result['handled']);self.assertEqual(result['tasks'][0]['spec']['root']['value'],'D');self.assertEqual(calls,2);self.assertIn('protected_inputs',trace['schema_repair']['original'])
 def test_repeated_input_loss_is_blocked_without_broad_query(self):
  from relational_planner import literal_relation_inputs
  q,bad=self.handoff_payload({'type':'global','quote':'全PBS范围'})
  with self.assertRaises(ValueError):self.extract_responses(q,{'relational_required':True,'relational_bound_inputs':literal_relation_inputs(q,self.store)},[bad,bad])
 def test_real_ambiguous_input_keeps_clarification_handoff(self):
  from relational_planner import literal_relation_inputs
  q='D对应哪个设备';self.assertEqual(literal_relation_inputs(q,self.store),[])
  p={'version':2,'handled':True,'mode':'new','tasks':[{'id':1,'action':'new','quote':q,'set':{'kind':'relation'},'root':{'type':'literal','tree':'config','field':'code','value':'D','quote':'D'},'classes':[],'filters':[]}]}
  result,trace,calls=self.extract_responses(q,{'relational_required':True,'relational_bound_inputs':[]},[p]);self.assertEqual(result,{'handled':False});self.assertEqual(calls,1)

if __name__=='__main__':unittest.main()
