"""接入表示兼容不能扩大身份、清空条件、放过未知字段或篡改冻结目标。"""
import copy,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import test_relational_query as fixtures
from relational_query import canonical
from relational_state import compile_delta,exact_literal,RelationalHandoff,condition_id
from relational_delta_codec import normalize_delta

class Codec(unittest.TestCase):
 @classmethod
 def setUpClass(cls):fixtures.Relations.setUpClass();cls.s=fixtures.Relations.s
 def q(self,**kw):return canonical({'kind':'collection','population':'points','root':{'tree':'pbs','field':'code','value':'L&D'},**kw})
 def context(self,q=None):return {'relational_state':{'tasks':[{'id':1,'spec':q or self.q(),'resolved':{}}]}}
 def raw(self,**kw):return {'version':2,'handled':True,'mode':'update','tasks':[{'id':1,'action':'update','quote':'更新原结果','set':{},**kw}]}
 def run_delta(self,raw,ctx,question='更新原结果'):
  v,a=normalize_delta(raw,question,ctx,self.s);return compile_delta(v,question,ctx,self.s)[0],a
 def test_omitted_empty_actions_preserve_all_filters_and_classes(self):
  ctx=self.context(self.q(classes={'equipment_class':'EC'},filters=[{'field':'source','operator':'equals','value':'S'}]));before=copy.deepcopy(ctx)
  v,_=self.run_delta(self.raw(),ctx);self.assertEqual(v['tasks'][0]['spec'],ctx['relational_state']['tasks'][0]['spec']);self.assertEqual(ctx,before)
 def test_retain_selector_is_no_mutation_of_real_filter(self):
  f={'field':'source','operator':'equals','value':'S'};q=self.q(filters=[f]);v,_=self.run_delta(self.raw(filters=[{'action':'retain','selector':{'id':condition_id(f)}}]),self.context(q));self.assertEqual(v['tasks'][0]['spec'],q)
 def test_classification_output_roles_are_not_new_filters(self):
  from relational_query import Graph,execute_task
  spec=self.q(root={'tree':'pbs','field':'code','value':'L&D#p1'},kind='relation',population='objects');ctx=self.context(spec);ctx['relational_state']['tasks'][0]['resolved']=execute_task(Graph(self.s),spec)['relation_facts']
  q='沿这个对象的真实关系，给出所属设备类和部件类的编码及描述';edits=[{'action':'set','tree':tree,'reference':{'type':'role','task':1,'role':tree,'quote':'所属'+word}} for tree,word in [('equipment_class','设备类'),('part_class','部件类')]]
  raw=self.raw(quote=q,set={'kind':'relation','population':'objects','properties':['code','name']},classes=edits);v,_=self.run_delta(raw,ctx,q);self.assertEqual(v['tasks'][0]['spec']['classes'],{});self.assertEqual(v['tasks'][0]['spec']['root'],spec['root'])
 def test_point_measurement_projection_matches_actual_default_delivery(self):
  from relational_planner import bound_semantics
  a={'handled':True,'tasks':[{'id':1,'spec':self.q(properties=['value'])}]};b={'handled':True,'tasks':[{'id':1,'spec':self.q()}]};self.assertEqual(bound_semantics(a,self.s),bound_semantics(b,self.s))
 def test_combined_removal_uses_original_current_span_for_actual_conditions(self):
  q='撤掉开启及已报警条件';ctx=self.context(self.q(filters=[{'field':'switch','operator':'equals','value':'开启'},{'field':'status','operator':'equals','value':'已报警'}]));raw=self.raw(quote=q,filters=[{'action':'remove','selector':{'field':'status'},'quote':'撤掉已报警条件'}]);v,_=self.run_delta(raw,ctx,q);self.assertEqual(v['tasks'][0]['spec']['filters'],[])
 def test_malformed_quote_without_raw_removal_proof_still_rejected(self):
  q='保留开启及已报警条件';ctx=self.context(self.q(filters=[{'field':'switch','operator':'equals','value':'开启'},{'field':'status','operator':'equals','value':'已报警'}]));raw=self.raw(quote=q,filters=[{'action':'remove','selector':{'field':'status'},'quote':'撤掉已报警条件'}])
  with self.assertRaises(ValueError):self.run_delta(raw,ctx,q)
 def test_unsupported_global_operand_cannot_expand_explicit_prior_two_sets(self):
  a=self.q(root={'tree':'pbs','field':'code','value':'L&D'},population='parts');b=self.q(root={'tree':'config','field':'code','value':'D'},population='parts');ctx=self.context(b);ctx['relational_history']=[{'state':self.context(a)['relational_state']},{'state':self.context(b)['relational_state']}]
  q='对照刚才两套部件集合及构型D真实下级';raw=self.raw(quote=q,set={'kind':'compare','population':'parts'},root={'type':'global','quote':'两套部件集合'},compare_root={'type':'literal','tree':'config','field':'code','value':'D','quote':'构型D'});v,_=self.run_delta(raw,ctx,q);self.assertEqual(v['tasks'][0]['spec']['root']['value'],'L&D');self.assertEqual(v['tasks'][0]['spec']['compare_root']['value'],'D')
 def test_output_role_without_actual_class_role_cannot_be_invented(self):
  q='给出所属设备类的编码及描述';raw=self.raw(quote=q,set={'kind':'relation','population':'objects'},classes=[{'action':'set','tree':'equipment_class','reference':{'type':'role','task':1,'role':'equipment_class','quote':'所属设备类'}}])
  with self.assertRaises(ValueError):self.run_delta(raw,self.context(),q)
 def test_retain_selector_unknown_is_rejected(self):
  with self.assertRaises(ValueError):self.run_delta(self.raw(filters=[{'action':'retain','selector':{'id':'unknown'}}]),self.context())
 def test_retain_cannot_create_condition_or_accept_old_quote(self):
  f={'field':'source','operator':'equals','value':'S'};ctx=self.context(self.q(filters=[f]))
  for edit in [{'action':'retain','selector':{'id':condition_id(f)},'condition':f},{'action':'retain','selector':{'id':condition_id(f)},'quote':'历史来源'}]:
   with self.assertRaises(ValueError):self.run_delta(self.raw(filters=[edit]),ctx)
 def test_unary_predicate_absent_argument_has_exact_empty_representation(self):
  v,_=self.run_delta(self.raw(filters=[{'action':'add','quote':'更新原结果','condition':{'field':'time','operator':'is_blank'}}]),self.context());self.assertEqual(v['tasks'][0]['spec']['filters'],[{'field':'time','operator':'is_blank','value':''}])
 def test_binary_predicate_missing_value_is_not_defaulted(self):
  with self.assertRaises(ValueError):self.run_delta(self.raw(filters=[{'action':'add','quote':'更新原结果','condition':{'field':'time','operator':'date_equals'}}]),self.context())
 def test_empty_object_is_only_a_no_edit_not_clear_classes(self):
  ctx=self.context(self.q(classes={'equipment_class':'EC'}));v,_=self.run_delta(self.raw(classes={},filters={}),ctx)
  self.assertEqual(v['tasks'][0]['spec']['classes'],{'equipment_class':'EC'})
 def test_nested_known_root_is_equivalent_to_action_level_root(self):
  root={'type':'literal','tree':'pbs','field':'code','value':'L','quote':'PBS L的记录'};raw=self.raw(quote='PBS L的记录',set={'root':root})
  v,_=self.run_delta(raw,self.context(),'PBS L的记录');self.assertEqual(v['tasks'][0]['spec']['root']['value'],'L')
 def test_conflicting_duplicate_root_is_rejected(self):
  raw=self.raw(root={'type':'literal','tree':'pbs','field':'code','value':'L','quote':'PBS L的记录'},set={'root':{'type':'literal','tree':'pbs','field':'code','value':'L&D','quote':'更新原结果'}})
  with self.assertRaises(ValueError):self.run_delta(raw,self.context())
 def test_unknown_nested_field_is_not_silently_dropped(self):
  with self.assertRaises(ValueError):self.run_delta(self.raw(set={'sql':'SELECT 1'}),self.context())
 def test_relation_self_depth_is_representation_not_collection_scope(self):
  q=canonical({'kind':'relation','population':'objects','root':{'tree':'config','field':'code','value':'D'}});v,_=self.run_delta(self.raw(set={'depth':'self'}),self.context(q));self.assertEqual(v['tasks'][0]['spec'],q)
 def test_new_collection_default_all_does_not_require_repeated_all_word(self):
  raw=self.raw(action='new',quote='PBS L&D下级范围的设备',root={'type':'literal','tree':'pbs','field':'code','value':'L&D','quote':'PBS L&D'},set={'kind':'collection','population':'devices','depth':'all'});raw['mode']='new'
  v,_=self.run_delta(raw,{},'PBS L&D下级范围的设备');self.assertEqual(v['tasks'][0]['spec']['depth'],'all')
 def test_explicit_current_new_unique_code_cannot_be_swallowed_by_old_root(self):
  q=canonical({'kind':'relation','root':{'tree':'config','field':'code','value':'D'}})
  with self.assertRaises(RelationalHandoff):self.run_delta(self.raw(quote='PBS L&D的实际关联'),self.context(q),'PBS L&D的实际关联')
 def test_current_exact_class_name_proves_alias_code_without_prefix_guess(self):
  root=exact_literal('equipment_class','code','EC','设备分类的原记录','设备分类的原记录',{},self.s);self.assertEqual(root['value'],'EC')
 def test_name_subrecord_cannot_expand_to_all_same_code_records(self):
  with self.assertRaises(ValueError):exact_literal('points','code','UNRELATED','点一的原行','点一的原行',{},self.s)
 def test_nonexistent_alias_cannot_be_guessed(self):
  with self.assertRaises(ValueError):exact_literal('config','code','D#p1','构型D','构型D',{},self.s)
 def test_repeated_actual_current_root_keeps_old_identity_not_free_old_literal(self):
  raw=self.raw(root={'type':'literal','tree':'pbs','field':'code','value':'L&D','quote':'刚才这个设备'},quote='刚才这个设备的原结果')
  v,_=self.run_delta(raw,self.context(),'刚才这个设备的原结果');self.assertEqual(v['tasks'][0]['spec']['root']['value'],'L&D')
 def test_historical_literal_requires_named_ordinal_and_exact_executed_root(self):
  ctx=self.context(self.q(root=None));ctx['relational_history']=[{'question':'首问实际PBS','state':{'tasks':[{'id':1,'spec':self.q(),'resolved':{}}]}}]
  raw=self.raw(root={'type':'literal','tree':'pbs','field':'code','value':'L&D','quote':'回到第一轮的对象'},quote='回到第一轮的对象')
  v,_=self.run_delta(raw,ctx,'回到第一轮的对象');self.assertEqual(v['tasks'][0]['spec']['root']['value'],'L&D')
 def test_history_without_explicit_ordinal_cannot_authorize_old_literal(self):
  ctx=self.context(self.q(root=None));ctx['relational_history']=[{'state':{'tasks':[{'id':1,'spec':self.q()}]}}]
  raw=self.raw(root={'type':'literal','tree':'pbs','field':'code','value':'L&D','quote':'一个以前的设备'},quote='一个以前的设备')
  with self.assertRaises(ValueError):self.run_delta(raw,ctx,'一个以前的设备')
 def test_incorrect_new_deictic_mode_does_not_clear_old_conditions(self):
  ctx=self.context(self.q(filters=[{'field':'switch','operator':'equals','value':'开启'}]));raw=self.raw(action='new',quote='从刚才结果中取明细',set={'kind':'collection','population':'points'});raw['mode']='new'
  v,_=self.run_delta(raw,ctx,'从刚才结果中取明细');self.assertEqual(v['tasks'][0]['spec']['filters'],ctx['relational_state']['tasks'][0]['spec']['filters'])
 def test_explicit_remove_source_is_compiled_from_actual_unique_condition(self):
  ctx=self.context(self.q(filters=[{'field':'source','operator':'equals','value':'S'},{'field':'switch','operator':'equals','value':'开启'}]))
  v,_=self.run_delta(self.raw(quote='撤销来源条件，开关不变'),ctx,'撤销来源条件，开关不变');self.assertEqual(v['tasks'][0]['spec']['filters'],[{'field':'switch','operator':'equals','value':'开启'}])
 def test_remove_phrase_does_not_consume_following_add_clause(self):
  ctx=self.context(self.q(filters=[{'field':'source','operator':'equals','value':'S'},{'field':'value','operator':'gt','value':'0'}]))
  v,_=self.run_delta(self.raw(quote='取消来源并再限定测量值大于5'),ctx,'取消来源并再限定测量值大于5');self.assertIn({'field':'value','operator':'gt','value':'0'},v['tasks'][0]['spec']['filters'])
 def test_plain_row_order_does_not_create_source_group(self):
  raw=self.raw(action='new',quote='监测表UNRELATED的原行按来源再行号排序',set={'kind':'relation','population':'points','depth':'self','group_by':'source','properties':['value','line'],'sort':['source','line']},root={'type':'literal','tree':'points','field':'code','value':'UNRELATED','quote':'UNRELATED'});raw['mode']='new'
  v,_=self.run_delta(raw,{},'监测表UNRELATED的原行按来源再行号排序');q=v['tasks'][0]['spec'];self.assertEqual(q['kind'],'collection');self.assertIsNone(q['group_by']);self.assertEqual(q['sort'],['source','line']);self.assertEqual(q['depth'],'self')
 def test_fixed_group_quantity_sort_is_normalized_only_for_grouped_view(self):
  v,_=self.run_delta(self.raw(set={'sort':['count']}),self.context(self.q(group_by='source')));self.assertEqual(v['tasks'][0]['spec']['sort'],[])
  with self.assertRaises(ValueError):self.run_delta(self.raw(set={'sort':['count']}),self.context())
 def test_unknown_sort_is_still_rejected_in_grouped_view(self):
  with self.assertRaises(ValueError):self.run_delta(self.raw(set={'sort':['unsafe']}),self.context(self.q(group_by='source')))
 def test_root_unknown_extra_cannot_hide_in_redundant_global_reference(self):
  raw=self.raw(root={'type':'global','quote':'更新原结果','sql':'unsafe'})
  with self.assertRaises(ValueError):self.run_delta(raw,self.context(self.q(root=None)))
 def test_existing_class_repetition_has_no_removal_effect(self):
  ctx=self.context(self.q(classes={'equipment_class':'EC'}));ref={'type':'literal','tree':'equipment_class','field':'code','value':'EC','quote':'保留刚才设备类'}
  v,_=self.run_delta(self.raw(quote='保留刚才设备类',classes=[{'action':'set','tree':'equipment_class','reference':ref}]),ctx,'保留刚才设备类');self.assertEqual(v['tasks'][0]['spec']['classes'],{'equipment_class':'EC'})
 def test_keep_count_metrics_does_not_restore_old_record_projection(self):
  ctx=self.context(self.q(properties=['value']));raw=self.raw(quote='改按来源分组，保留原行数和不同编码数',set={'group_by':'source','properties':'keep'})
  v,_=self.run_delta(raw,ctx,'改按来源分组，保留原行数和不同编码数');self.assertEqual(v['tasks'][0]['spec']['properties'],[])
 def test_explicit_keep_columns_survives_view_change(self):
  ctx=self.context(self.q(properties=['value']));raw=self.raw(quote='改按来源分组，原字段保持',set={'group_by':'source','properties':'keep'})
  v,_=self.run_delta(raw,ctx,'改按来源分组，原字段保持');self.assertEqual(v['tasks'][0]['spec']['properties'],['value'])
 def test_cancel_source_group_does_not_cancel_source_filter(self):
  ctx=self.context(self.q(group_by='source',filters=[{'field':'source','operator':'equals','value':'S'}]));raw=self.raw(quote='取消来源分组，改为明细',set={'group_by':None})
  v,_=self.run_delta(raw,ctx,'取消来源分组，改为明细');self.assertEqual(v['tasks'][0]['spec']['filters'],ctx['relational_state']['tasks'][0]['spec']['filters'])
 def test_declared_filter_remove_cannot_borrow_output_only_control_quote(self):
  ctx=self.context(self.q(filters=[{'field':'source','operator':'equals','value':'S'}]));raw=self.raw(quote='取消来源分组',filters=[{'action':'remove','selector':{'field':'source'},'quote':'取消来源分组'}])
  with self.assertRaises(ValueError):self.run_delta(raw,ctx,'取消来源分组')

class StateOwnership(unittest.TestCase):
 setUpClass=classmethod(Codec.setUpClass.__func__)
 q=Codec.q
 context=Codec.context
 raw=Codec.raw
 run_delta=Codec.run_delta
 def test_collection_group_retains_explicit_direct_depth(self):
  raw=self.raw(action='new',quote='PBS L&D直属下一层按对象类型统计',root={'type':'literal','tree':'pbs','field':'code','value':'L&D','quote':'PBS L&D'},set={'kind':'relation','population':'objects','group_by':'type','depth':'direct'});raw['mode']='new'
  v,_=self.run_delta(raw,{},'PBS L&D直属下一层按对象类型统计');q=v['tasks'][0]['spec'];self.assertEqual(q['kind'],'collection');self.assertEqual(q['depth'],'direct')
 def test_view_switch_retains_unmatched_record_predicate(self):
  ctx=self.context(self.q(only='unmatched'));v,_=self.run_delta(self.raw(set={'group_by':None}),ctx);self.assertEqual(v['tasks'][0]['spec']['only'],'unmatched')
 def test_explicit_clear_only_changes_record_predicate(self):
  ctx=self.context(self.q(only='unmatched'));v,_=self.run_delta(self.raw(quote='取消只看未匹配',set={'group_by':None,'only':None}),ctx,'取消只看未匹配');self.assertIsNone(v['tasks'][0]['spec']['only'])
 def test_outer_registered_setting_is_equivalent(self):
  v,_=self.run_delta(self.raw(properties=['value']),self.context());self.assertEqual(v['tasks'][0]['spec']['properties'],['value'])
 def test_conflicting_setting_is_rejected(self):
  with self.assertRaises(ValueError):self.run_delta(self.raw(properties=['value'],set={'properties':['unit']}),self.context())
 def test_required_relation_does_not_delegate_graph_grouping(self):
  from relational_planner import required_relation
  self.assertTrue(required_relation('按部件类别分布统计，缺失单列',{}));self.assertTrue(required_relation('沿用设备再只看来源，改按来源分组',self.context()))
 def test_raw_numeric_extreme_still_uses_mature_path(self):
  from relational_planner import required_relation
  self.assertFalse(required_relation('仍看这些测点按测量值排序',self.context()));self.assertFalse(required_relation('计算两者差值',self.context()))
 def test_required_graph_cannot_silently_fallthrough(self):
  import io,json
  from unittest.mock import patch
  from relational_planner import extract
  def resp():return io.StringIO(json.dumps({'choices':[{'message':{'content':'{"handled":false}'}}]}))
  with patch('urllib.request.build_opener') as b:
   b.return_value.open.side_effect=[resp(),resp()]
   with self.assertRaises(ValueError):extract('按部件类别分布统计',{'relational_required':True},'synthetic','synthetic',{},_store=self.s)

class ReferenceProofs(unittest.TestCase):
 setUpClass=classmethod(Codec.setUpClass.__func__)
 q=Codec.q
 context=Codec.context
 raw=Codec.raw
 run_delta=Codec.run_delta
 def test_class_quote_uses_same_task_tree_qualifier(self):
  raw=self.raw(action='new',quote='PBS L的设备类EC现场设备',root={'type':'literal','tree':'pbs','field':'code','value':'L','quote':'L'},set={'kind':'collection','population':'devices'},classes=[{'action':'set','tree':'equipment_class','reference':{'type':'literal','tree':'equipment_class','field':'code','value':'EC','quote':'EC'}}]);raw['mode']='new'
  v,_=self.run_delta(raw,{},'PBS L的设备类EC现场设备');self.assertEqual(v['tasks'][0]['spec']['classes'],{'equipment_class':'EC'})
 def test_explicit_history_role_uses_executed_ordinal(self):
  ctx=self.context(self.q(root=None));ctx['relational_history']=[{'state':{'tasks':[{'id':1,'spec':self.q(),'resolved':{}}]}}]
  raw=self.raw(quote='回到第一轮对象',root={'type':'role','task':1,'role':'root','quote':'第一轮对象'})
  v,_=self.run_delta(raw,ctx,'回到第一轮对象');self.assertEqual(v['tasks'][0]['spec']['root']['value'],'L&D')
 def test_single_class_edit_is_not_a_class_value_dictionary(self):
  ctx=self.context(self.q(classes={'equipment_class':'EC'}));raw=self.raw(quote='撤销设备类限定',classes={'action':'remove','tree':'equipment_class','quote':'撤销设备类限定'})
  v,_=self.run_delta(raw,ctx,'撤销设备类限定');self.assertEqual(v['tasks'][0]['spec']['classes'],{})

class RegisteredViews(unittest.TestCase):
 setUpClass=classmethod(Codec.setUpClass.__func__)
 q=Codec.q
 context=Codec.context
 raw=Codec.raw
 run_delta=Codec.run_delta
 def test_relation_population_is_not_a_descendant_collection(self):
  raw=self.raw(action='new',quote='构型D#p1所属分类',root={'type':'literal','tree':'config','field':'code','value':'D#p1','quote':'构型D#p1'},set={'kind':'relation','population':'parts','depth':'self'});raw['mode']='new'
  v,_=self.run_delta(raw,{},'构型D#p1所属分类');self.assertEqual(v['tasks'][0]['spec']['kind'],'relation');self.assertEqual(v['tasks'][0]['spec']['population'],'objects')
 def test_registered_relation_roles_are_delivered_without_raw_field_keys(self):
  raw=self.raw(action='new',quote='PBS L&D关联设备类',root={'type':'literal','tree':'pbs','field':'code','value':'L&D','quote':'PBS L&D'},set={'kind':'relation','population':'objects','properties':['equipment_class','pbs']});raw['mode']='new'
  v,_=self.run_delta(raw,{},'PBS L&D关联设备类');self.assertEqual(v['tasks'][0]['spec']['properties'],[])
 def test_unknown_relation_projection_still_rejected(self):
  with self.assertRaises(ValueError):self.run_delta(self.raw(set={'kind':'relation','properties':['sql']}),self.context())
 def test_same_code_table_comparison_is_two_original_relation_tasks(self):
  raw=self.raw(action='new',quote='EC构型树和设备类表分别查各自父编码是否同一条记录',root={'type':'literal','tree':'config','field':'code','value':'EC','quote':'EC构型树'},compare_root={'type':'literal','tree':'equipment_class','field':'code','value':'EC','quote':'设备类表'},set={'kind':'compare','population':'objects'});raw['mode']='new'
  v,_=self.run_delta(raw,{},'EC构型树和设备类表分别查各自父编码是否同一条记录');self.assertEqual([x['spec']['kind'] for x in v['tasks']],['relation','relation']);self.assertEqual({x['spec']['root']['tree'] for x in v['tasks']},{'config','equipment_class'})
 def test_traversing_parent_to_read_class_retains_subject(self):
  ctx=self.context(canonical({'kind':'relation','root':{'tree':'config','field':'code','value':'D'}}));ctx['relational_state']['tasks'][0]['resolved']={'parent':[{'tree':'config','code':'EC'}]}
  raw=self.raw(quote='沿真实父级继续查所属设备类',root={'type':'role','task':1,'role':'parent','quote':'真实父级'},set={'kind':'relation','population':'objects'})
  v,_=self.run_delta(raw,ctx,'沿真实父级继续查所属设备类');self.assertEqual(v['tasks'][0]['spec']['root']['value'],'D')
 def test_explicit_parent_itself_still_changes_subject(self):
  ctx=self.context(canonical({'kind':'relation','root':{'tree':'config','field':'code','value':'D'}}));ctx['relational_state']['tasks'][0]['resolved']={'parent':[{'tree':'config','code':'EC'}]}
  raw=self.raw(quote='改查真实父级本身',root={'type':'role','task':1,'role':'parent','quote':'真实父级本身'})
  v,_=self.run_delta(raw,ctx,'改查真实父级本身');self.assertEqual(v['tasks'][0]['spec']['root']['value'],'EC')
 def test_unproven_null_does_not_clear_record_scope(self):
  ctx=self.context(self.q(only='unmatched'));v,_=self.run_delta(self.raw(set={'group_by':None,'only':None}),ctx);self.assertEqual(v['tasks'][0]['spec']['only'],'unmatched')
 def test_false_version_compatibility_has_no_business_slots(self):
  v,_=normalize_delta({'version':2,'handled':False},'',{});self.assertEqual(v,{'handled':False})
  v,_=normalize_delta({'version':2,'handled':False,'tasks':[]},'',{});self.assertIn('tasks',v)
 def test_role_comparison_uses_two_executed_original_tables(self):
  pbs=self.q(population='parts');cfg=self.q(population='parts',root={'tree':'config','field':'code','value':'D'})
  ctx=self.context(cfg);ctx['relational_history']=[{'state':{'tasks':[{'id':1,'spec':pbs}]}},{'state':{'tasks':[{'id':1,'spec':cfg}]}}]
  raw=self.raw(quote='对照刚才两套部件集合',set={'kind':'compare','population':'parts','depth':'all'},root={'type':'role','task':1,'role':'root','quote':'刚才两套部件集合'},compare_root={'type':'role','task':1,'role':'root','quote':'刚才两套部件集合'})
  v,_=self.run_delta(raw,ctx,'对照刚才两套部件集合');q=v['tasks'][0]['spec'];self.assertEqual(q['root']['tree'],'pbs');self.assertEqual(q['compare_root']['tree'],'config')

class CollectionBoundaries(unittest.TestCase):
 setUpClass=classmethod(Codec.setUpClass.__func__)
 q=Codec.q
 context=Codec.context
 raw=Codec.raw
 run_delta=Codec.run_delta
 def test_direct_objects_are_collection_with_real_parent_edges(self):
  from relational_query import execute
  raw=self.raw(action='new',quote='构型D的直接对象',root={'type':'literal','tree':'config','field':'code','value':'D','quote':'构型D'},set={'kind':'relation','population':'objects','depth':'direct'});raw['mode']='new'
  v,_=self.run_delta(raw,{},'构型D的直接对象');q=v['tasks'][0]['spec'];self.assertEqual(q['kind'],'collection');self.assertEqual(q['depth'],'direct')
  r=execute(self.s,{'operation':'relational','entity':None,'scope':'direct','clarification':'','relational_tasks':v['tasks']});self.assertEqual(r['population_facts']['record_count'],3)
 def test_pbs_all_levels_is_explicit_whole_tree_target(self):
  from relational_query import execute
  raw=self.raw(action='new',quote='统计PBS各层级对象数量',root={'type':'global','quote':'PBS各层级'},set={'kind':'collection','population':'objects','group_by':'type'});raw['mode']='new'
  v,_=self.run_delta(raw,{},'统计PBS各层级对象数量');r=execute(self.s,{'operation':'relational','entity':None,'scope':'direct','clarification':'','relational_tasks':v['tasks']});self.assertEqual(r['population_facts']['record_count'],7)
 def test_requested_actual_class_candidates_are_not_extra_primary_objects(self):
  raw=self.raw(action='new',quote='构型D所属设备类究竟应该读取EC还是D',root={'type':'literal','tree':'config','field':'code','value':'D','quote':'构型D'},set={'kind':'relation','population':'objects'});raw['mode']='new'
  v,_=self.run_delta(raw,{},'构型D所属设备类究竟应该读取EC还是D');self.assertEqual(v['tasks'][0]['spec']['root']['value'],'D')
 def test_alternative_class_does_not_authorize_wrong_primary(self):
  raw=self.raw(action='new',quote='EC所属的类别究竟应该读取什么',root={'type':'literal','tree':'config','field':'code','value':'D','quote':'EC所属的类别究竟应该读取什么'},set={'kind':'relation','population':'objects'});raw['mode']='new'
  with self.assertRaises(ValueError):self.run_delta(raw,{},'EC所属的类别究竟应该读取什么')

 def test_next_layer_parts_is_a_collection_even_when_model_calls_it_relation(self):
  text='构型D查下一层部件编码名称'
  raw=self.raw(action='new',quote=text,set={'kind':'relation','population':'parts','depth':'direct','properties':['code','name']},root={'type':'literal','tree':'config','field':'code','value':'D','quote':'构型D'});raw['mode']='new'
  v,_=self.run_delta(raw,{},text);self.assertEqual(v['tasks'][0]['spec'],canonical({'kind':'collection','population':'parts','depth':'direct','root':{'tree':'config','field':'code','value':'D'}}))
 def test_all_levels_changes_collection_depth_without_changing_identity(self):
  old=self.q(population='parts',root={'tree':'config','field':'code','value':'D'},depth='direct');text='同根查所有层级部件'
  v,_=self.run_delta(self.raw(quote=text,set={'kind':'relation','population':'parts','depth':'all'}),self.context(old),text)
  self.assertEqual(v['tasks'][0]['spec'],canonical({**old,'depth':'all'}))
 def test_original_level_projection_keeps_dictionary_relation(self):
  text='设备类EC读取原层级和父编码';raw=self.raw(action='new',quote=text,set={'kind':'relation','population':'objects','properties':['level','parent']},root={'type':'literal','tree':'equipment_class','field':'code','value':'EC','quote':'设备类EC'});raw['mode']='new'
  v,_=self.run_delta(raw,{},text);self.assertEqual(v['tasks'][0]['spec']['kind'],'relation')
 def test_explicit_pbs_type_count_is_not_reclassified_as_dictionary_groups(self):
  text='统计PBS所有类型的对象数量'
  raw=self.raw(action='new',quote=text,set={'kind':'collection','population':'objects','group_by':'class'},root={'type':'global','quote':text});raw['mode']='new'
  v,_=self.run_delta(raw,{},text);self.assertEqual(v['tasks'][0]['spec']['group_by'],'type')
 def test_explicit_pbs_layer_count_from_empty_group_uses_original_type_field(self):
  text='统计PBS各层级的对象数量';raw=self.raw(action='new',quote=text,set={'kind':'collection','population':'objects','group_by':None},root={'type':'global','quote':text});raw['mode']='new'
  v,_=self.run_delta(raw,{},text);self.assertEqual(v['tasks'][0]['spec']['group_by'],'type')
 def test_template_numeric_level_does_not_use_pbs_type_group_alias(self):
  text='构型D按类别统计，说明PBS各层级数量与它不同';raw=self.raw(action='new',quote=text,set={'kind':'collection','population':'objects','group_by':'class'},root={'type':'literal','tree':'config','field':'code','value':'D','quote':'构型D'});raw['mode']='new'
  v,_=self.run_delta(raw,{},text);self.assertEqual(v['tasks'][0]['spec']['group_by'],'class')
 def test_other_explicit_group_target_is_not_overwritten_by_type_mentions(self):
  text='PBS各层级对象范围按分类分组统计数量';raw=self.raw(action='new',quote=text,set={'kind':'collection','population':'objects','group_by':'class'},root={'type':'global','quote':text});raw['mode']='new'
  v,_=self.run_delta(raw,{},text);self.assertEqual(v['tasks'][0]['spec']['group_by'],'class')
 def test_return_to_executed_record_explicitly_ends_instance_goal(self):
  prior=canonical({'kind':'relation','root':{'tree':'part_class','field':'code','value':'BC'}})
  ctx=self.context(self.q(root=None,classes={'part_class':'BC'},filters=[{'field':'source','operator':'equals','value':'S'}]));ctx['relational_history']=[{'state':{'tasks':[{'id':1,'spec':prior,'resolved':{}}]}}]
  text='返回第一轮原记录，不继续查询实例集合';raw=self.raw(quote=text,set={'kind':'relation','population':'objects'},root={'type':'role','task':1,'role':'root','history':0,'quote':'第一轮原记录'})
  v,_=self.run_delta(raw,ctx,text);self.assertEqual(v['tasks'][0]['spec'],prior)
 def test_return_to_history_with_continued_conditions_is_not_an_independent_new_goal(self):
  old=self.q(filters=[{'field':'source','operator':'equals','value':'S'}]);ctx=self.context(old);ctx['relational_history']=[{'state':{'tasks':[{'id':1,'spec':self.q(root={'tree':'pbs','field':'code','value':'L'})}]}}]
  text='返回第一轮对象，继续使用来源条件';raw=self.raw(quote=text,root={'type':'role','task':1,'role':'root','history':0,'quote':'第一轮对象'})
  v,_=self.run_delta(raw,ctx,text);self.assertEqual(v['tasks'][0]['spec']['filters'],old['filters'])
 def test_unexecuted_history_cannot_restart_and_supply_an_identity(self):
  text='返回第一轮原记录，不继续查询实例集合';raw=self.raw(quote=text,set={'kind':'relation','population':'objects'},root={'type':'role','task':1,'role':'root','history':0,'quote':'第一轮原记录'})
  with self.assertRaises(ValueError):self.run_delta(raw,self.context(),text)
 def test_history_role_without_repeated_index_can_end_instance_goal(self):
  prior=canonical({'kind':'relation','root':{'tree':'part_class','field':'code','value':'BC'}});ctx=self.context(self.q(root=None,classes={'part_class':'BC'}));ctx['relational_history']=[{'state':{'tasks':[{'id':1,'spec':prior}]}}]
  text='返回第一轮原记录，不继续查询实例集合';raw=self.raw(quote=text,set={'kind':'relation','population':'objects'},root={'type':'role','task':1,'role':'root','quote':'第一轮原记录'})
  v,_=self.run_delta(raw,ctx,text);self.assertEqual(v['tasks'][0]['spec'],prior)
 def test_historical_literal_is_first_proven_then_ends_instance_goal(self):
  prior=canonical({'kind':'relation','root':{'tree':'part_class','field':'code','value':'BC'}});ctx=self.context(self.q(root=None,classes={'part_class':'BC'}));ctx['relational_history']=[{'state':{'tasks':[{'id':1,'spec':prior}]}}]
  text='返回第一轮原记录，不继续查询实例集合';raw=self.raw(quote=text,set={'kind':'relation','population':'objects'},root={'type':'literal','tree':'part_class','field':'code','value':'BC','quote':'第一轮原记录'})
  v,_=self.run_delta(raw,ctx,text);self.assertEqual(v['tasks'][0]['spec'],prior)
 def test_registered_role_code_and_name_are_delivered_by_actual_relation_cards(self):
  from relational_query import execute_task,Graph
  text='PBS L&D#p1自身及用于关联的构型、部件类编码名称';raw=self.raw(action='new',quote=text,set={'kind':'relation','population':'parts','properties':['config_code','part_class_name']},root={'type':'literal','tree':'pbs','field':'code','value':'L&D#p1','quote':'PBS L&D#p1'});raw['mode']='new'
  v,_=self.run_delta(raw,{},text);q=v['tasks'][0]['spec'];self.assertEqual(q['properties'],[]);r=execute_task(Graph(self.s),q);self.assertTrue(any('D#p1' in x['cells'] for x in r['records']));self.assertTrue(any('部件分类' in x['cells'] for x in r['records']))
 def test_unknown_role_field_cannot_be_silently_dropped(self):
  text='PBS L&D原关联';raw=self.raw(action='new',quote=text,set={'kind':'relation','population':'objects','properties':['fabricated_config_code']},root={'type':'literal','tree':'pbs','field':'code','value':'L&D','quote':'PBS L&D'});raw['mode']='new'
  with self.assertRaises(ValueError):self.run_delta(raw,{},text)
 def test_collection_role_projection_is_not_claimed_as_a_fixed_relation_card(self):
  text='PBS L&D全部部件的构型编码明细';raw=self.raw(action='new',quote=text,set={'kind':'collection','population':'parts','properties':['config_code']},root={'type':'literal','tree':'pbs','field':'code','value':'L&D','quote':'PBS L&D'});raw['mode']='new'
  with self.assertRaises(ValueError):self.run_delta(raw,{},text)
 def test_structured_property_is_rejected_as_protocol_error(self):
  text='PBS L&D原关联';raw=self.raw(action='new',quote=text,set={'kind':'relation','population':'objects','properties':[{'config_code':'injected'}]},root={'type':'literal','tree':'pbs','field':'code','value':'L&D','quote':'PBS L&D'});raw['mode']='new'
  with self.assertRaises(ValueError):self.run_delta(raw,{},text)
 def test_class_reference_uses_same_registered_outer_condition_namespace(self):
  old=self.q(root=None,population='devices',classes={'equipment_class':'EC'});text='同一个类保持，改查所有监测原行按来源统计';raw=self.raw(quote=text,set={'kind':'collection','population':'points','group_by':'source'},classes=[{'action':'set','tree':'equipment_class','reference':{'type':'class','task':1,'quote':'同一个类保持'}}])
  v,_=self.run_delta(raw,self.context(old),text);self.assertEqual(v['tasks'][0]['spec']['classes'],{'equipment_class':'EC'});self.assertEqual(v['tasks'][0]['spec']['population'],'points')
 def test_conflicting_class_discriminators_are_not_repaired_by_picking_one(self):
  text='类别保持';raw=self.raw(quote=text,classes=[{'action':'set','tree':'equipment_class','reference':{'type':'class','task':1,'tree':'part_class','quote':text}}])
  with self.assertRaises(ValueError):self.run_delta(raw,self.context(self.q(classes={'equipment_class':'EC','part_class':'BC'})),text)
 def test_unregistered_outer_namespace_cannot_fill_class_identity(self):
  text='类别保持';raw=self.raw(quote=text,classes=[{'action':'set','tree':'pbs','reference':{'type':'class','task':1,'quote':text}}])
  with self.assertRaises(ValueError):self.run_delta(raw,self.context(),text)
 def test_population_and_group_change_cannot_remove_prior_device_class_without_source(self):
  old=self.q(root=None,population='devices',classes={'equipment_class':'EC'});text='这些现场设备的全部下级部件按部件类统计'
  raw=self.raw(quote=text,set={'kind':'collection','population':'parts','group_by':'class'},classes=[{'action':'remove','tree':'equipment_class','quote':'这些现场设备'}])
  v,_=self.run_delta(raw,self.context(old),text);self.assertEqual(v['tasks'][0]['spec']['classes'],old['classes']);self.assertEqual(v['tasks'][0]['spec']['group_by'],'class')
 def test_explicit_part_class_cancel_cannot_also_delete_device_class(self):
  old=self.q(classes={'equipment_class':'EC','part_class':'BC'});text='取消部件类条件，其他保持'
  raw=self.raw(quote=text,classes=[{'action':'remove','tree':t,'quote':'取消部件类条件'}for t in ('equipment_class','part_class')])
  v,_=self.run_delta(raw,self.context(old),text);self.assertEqual(v['tasks'][0]['spec']['classes'],{'equipment_class':'EC'})
 def test_cancel_class_display_group_keeps_actual_class_predicate(self):
  old=self.q(root=None,population='devices',classes={'equipment_class':'EC'},group_by='class');text='取消设备类分组，改为设备明细'
  raw=self.raw(quote=text,set={'group_by':None},classes=[{'action':'remove','tree':'equipment_class','quote':'取消设备类分组'}])
  v,_=self.run_delta(raw,self.context(old),text);self.assertEqual(v['tasks'][0]['spec']['classes'],old['classes']);self.assertIsNone(v['tasks'][0]['spec']['group_by'])
 def test_record_grouping_without_filter_change_cannot_delete_source(self):
  old=self.q(filters=[{'field':'source','operator':'equals','value':'S'},{'field':'switch','operator':'equals','value':'开启'}]);text='这些监测原行按来源统计'
  raw=self.raw(quote=text,set={'group_by':'source'},filters=[{'action':'remove','selector':{'field':'source'},'quote':'这些监测原行'}])
  v,_=self.run_delta(raw,self.context(old),text);self.assertEqual(v['tasks'][0]['spec']['filters'],old['filters'])
 def test_cancel_display_limit_does_not_authorize_source_filter_removal(self):
  old=self.q(filters=[{'field':'source','operator':'equals','value':'S'}],limit=2);text='取消前2条，原来源条件保持'
  raw=self.raw(quote=text,set={'limit':None},filters=[{'action':'remove','selector':{'field':'source'},'quote':'取消前2条'}])
  v,_=self.run_delta(raw,self.context(old),text);self.assertEqual(v['tasks'][0]['spec']['filters'],old['filters']);self.assertIsNone(v['tasks'][0]['spec']['limit'])
 def test_omitted_numeric_field_needs_exact_existing_endpoint_not_prefix(self):
  old=self.q(filters=[{'field':'value','operator':'gt','value':'10'}]);text='撤掉大于100条件'
  raw=self.raw(quote=text,filters=[{'action':'remove','selector':{'field':'value','operator':'gt','value':'10'},'quote':text}])
  v,_=self.run_delta(raw,self.context(old),text);self.assertEqual(v['tasks'][0]['spec']['filters'],old['filters'])
 def test_verified_single_device_replaces_explicitly_ended_class_collection(self):
  old=self.q(root=None,population='devices',classes={'equipment_class':'EC'});ctx=self.context(old);first=self.q();ctx['relational_history']=[{'state':{'tasks':[{'id':1,'spec':first}]}}]
  text='返回第一轮设备，查它全部部件，不再统计这个设备类的所有设备';raw=self.raw(quote=text,set={'kind':'collection','population':'parts','group_by':'class'},root={'type':'role','task':1,'role':'root','history':0,'quote':'第一轮设备'},classes=[{'action':'remove','tree':'equipment_class','quote':'不再统计这个设备类的所有设备'}])
  v,_=self.run_delta(raw,ctx,text);self.assertEqual(v['tasks'][0]['spec']['root'],first['root']);self.assertEqual(v['tasks'][0]['spec']['classes'],{})
 def test_stopping_class_statistics_without_a_proven_device_does_not_open_global_scope(self):
  old=self.q(root=None,population='devices',classes={'equipment_class':'EC'});text='不再统计这个设备类的所有设备'
  raw=self.raw(quote=text,classes=[{'action':'remove','tree':'equipment_class','quote':text}]);v,_=self.run_delta(raw,self.context(old),text);self.assertEqual(v['tasks'][0]['spec']['classes'],old['classes'])
 def test_verified_location_is_also_a_specific_root_for_explicit_scope_replacement(self):
  old=self.q(root=None,population='devices',classes={'equipment_class':'EC'});text='PBS L的部件，不再统计这个设备类的所有设备';raw=self.raw(quote=text,set={'kind':'collection','population':'parts'},root={'type':'literal','tree':'pbs','field':'code','value':'L','quote':'PBS L'},classes=[{'action':'remove','tree':'equipment_class','quote':'不再统计这个设备类的所有设备'}])
  v,_=self.run_delta(raw,self.context(old),text);self.assertEqual(v['tasks'][0]['spec']['classes'],{});self.assertEqual(v['tasks'][0]['spec']['root']['value'],'L')
 def test_unique_class_collection_reference_can_be_ended_when_returning_to_known_root(self):
  old=self.q(root=None,population='devices',classes={'equipment_class':'EC'});ctx=self.context(old);first=self.q();ctx['relational_history']=[{'state':{'tasks':[{'id':1,'spec':first}]}}]
  text='返回第一轮设备，统计监测来源，不再取这个类的全表设备';raw=self.raw(quote=text,set={'kind':'collection','population':'points','group_by':'source'},root={'type':'role','task':1,'role':'root','history':0,'quote':'第一轮设备'},classes=[{'action':'remove','tree':'equipment_class','quote':'不再取这个类的全表设备'}])
  v,_=self.run_delta(raw,ctx,text);self.assertEqual(v['tasks'][0]['spec']['classes'],{});self.assertEqual(v['tasks'][0]['spec']['root'],first['root'])
 def test_actual_historical_subject_and_root_are_same_dictionary_identity(self):
  prior=canonical({'kind':'relation','root':{'tree':'part_class','field':'code','value':'BC'}});ctx=self.context(self.q(root=None,classes={'part_class':'BC'}));ctx['relational_history']=[{'state':{'tasks':[{'id':1,'spec':prior,'resolved':{'subject':[{'tree':'part_class','code':'BC'}]}}]}}]
  text='返回第一轮原记录，不继续查询实例集合';raw=self.raw(quote=text,set={'kind':'relation','population':'objects'},root={'type':'role','task':1,'role':'subject','history':0,'quote':'第一轮原记录'})
  v,_=self.run_delta(raw,ctx,text);self.assertEqual(v['tasks'][0]['spec'],prior)
 def test_summary_is_a_grouping_operation_not_a_record_list(self):
  text='全监测按实际功能位置汇总原记录数';raw=self.raw(action='new',quote=text,set={'kind':'collection','population':'points','group_by':'location'},root={'type':'global','quote':'全监测'});raw['mode']='new'
  v,_=self.run_delta(raw,{},text);self.assertEqual(v['tasks'][0]['spec']['group_by'],'location')
 def test_missing_members_also_included_does_not_create_an_exclusive_filter(self):
  old=self.q(population='parts',depth='direct',properties=['parent']);text='扩大到全部后代部件，父编码列保持，分类资料缺少的也不能漏掉';raw=self.raw(quote=text,set={'depth':'all','only':'missing_class'})
  v,_=self.run_delta(raw,self.context(old),text);self.assertIsNone(v['tasks'][0]['spec']['only']);self.assertEqual(v['tasks'][0]['spec']['properties'],['parent'])
 def test_explicit_only_missing_is_not_widened_by_do_not_omit_missing(self):
  text='只取缺少分类资料的部件，这些缺少的也不能漏掉';raw=self.raw(quote=text,set={'only':'missing_class'})
  v,_=self.run_delta(raw,self.context(self.q(population='parts')),text);self.assertEqual(v['tasks'][0]['spec']['only'],'missing_class')
 def test_historical_role_uses_same_task_source_when_only_duplicate_quote_is_omitted(self):
  pbs=self.q(population='parts');cfg=self.q(population='parts',root={'tree':'config','field':'code','value':'D'});ctx=self.context(cfg);ctx['relational_history']=[{'state':{'tasks':[{'id':1,'spec':pbs}]}},{'state':{'tasks':[{'id':1,'spec':cfg}]}}]
  text='对照前两轮PBS部件与构型部件';raw=self.raw(action='new',quote=text,set={'kind':'compare','population':'parts'},root={'type':'role','task':1,'role':'root','history':0},compare_root={'type':'role','task':1,'role':'root','history':1});raw['mode']='new'
  v,_=self.run_delta(raw,ctx,text);self.assertEqual(v['tasks'][0]['spec']['root'],pbs['root']);self.assertEqual(v['tasks'][0]['spec']['compare_root'],cfg['root'])
 def test_missing_literal_source_cannot_be_filled_from_task_quote(self):
  text='返回第一轮对象';raw=self.raw(quote=text,root={'type':'literal','tree':'pbs','field':'code','value':'L&D'})
  with self.assertRaises(ValueError):self.run_delta(raw,self.context(),text)
 def test_previous_two_executed_collections_bind_actual_trees_before_role_lookup(self):
  pbs=self.q(population='parts');cfg=self.q(population='parts',root={'tree':'config','field':'code','value':'D'});ctx=self.context(cfg);ctx['relational_history']=[{'state':{'tasks':[{'id':1,'spec':pbs}]}},{'state':{'tasks':[{'id':1,'spec':cfg}]}}]
  text='对照前两轮PBS部件集合和构型部件集合，列两边数量和不一致项';raw=self.raw(action='new',quote=text,set={'kind':'compare','population':'parts'},root={'type':'role','task':1,'role':'root','quote':'前两轮PBS部件集合'},compare_root={'type':'role','task':1,'role':'config','quote':'构型部件集合'});raw['mode']='new'
  v,_=self.run_delta(raw,ctx,text);self.assertEqual(v['tasks'][0]['spec']['root'],pbs['root']);self.assertEqual(v['tasks'][0]['spec']['compare_root'],cfg['root'])
 def test_same_message_same_device_uses_actual_common_literal_source(self):
  text='第一项PBS L&D全部部件类别分布；第二项同一PBS设备全部监测原行来源分布'
  root={'type':'literal','tree':'pbs','field':'code','value':'L&D','quote':'PBS L&D'};wrong={**root,'quote':'同一PBS设备L&D'}
  raw={'version':2,'handled':True,'mode':'new','tasks':[{'id':1,'action':'new','quote':'第一项PBS L&D全部部件类别分布','set':{'kind':'collection','population':'parts','group_by':'class'},'root':root},{'id':2,'action':'new','quote':'第二项同一PBS设备全部监测原行来源分布','set':{'kind':'collection','population':'points','group_by':'source'},'root':wrong}]}
  v,_=self.run_delta(raw,{},text);self.assertEqual([x['spec']['root']for x in v['tasks']],[{'tree':'pbs','field':'code','value':'L&D'}]*2)
 def test_missing_same_message_actual_anchor_does_not_authorize_literal_quote_repair(self):
  text='第一项PBS L的部件；第二项同一PBS设备的监测';raw={'version':2,'handled':True,'mode':'new','tasks':[{'id':1,'action':'new','quote':'第一项PBS L的部件','set':{'kind':'collection','population':'parts'},'root':{'type':'literal','tree':'pbs','field':'code','value':'L','quote':'PBS L'}},{'id':2,'action':'new','quote':'第二项同一PBS设备的监测','set':{'kind':'collection','population':'points'},'root':{'type':'literal','tree':'pbs','field':'code','value':'L&D','quote':'同一PBS设备L&D'}}]}
  with self.assertRaises(ValueError):self.run_delta(raw,{},text)
 def test_complete_distribution_keeps_unclassifiable_parts_instead_of_only_missing(self):
  text='按部件类别统计，无法分类的部件另列';raw=self.raw(quote=text,set={'kind':'collection','population':'parts','group_by':'class','only':'missing_class'})
  v,_=self.run_delta(raw,self.context(self.q(population='parts')),text);self.assertIsNone(v['tasks'][0]['spec']['only'])
 def test_explicit_only_unclassifiable_does_not_become_complete_distribution(self):
  text='只取无法分类的部件，按类别分组，无法分类单列';raw=self.raw(quote=text,set={'kind':'collection','population':'parts','group_by':'class','only':'missing_class'})
  with self.assertRaises(ValueError):self.run_delta(raw,self.context(self.q(population='parts')),text)

class ClassNodeFocus(unittest.TestCase):
 setUpClass=classmethod(Codec.setUpClass.__func__)
 q=Codec.q
 context=Codec.context
 raw=Codec.raw
 run_delta=Codec.run_delta
 def test_config_class_node_links_exact_existing_dictionary_identity(self):
  from relational_query import Graph
  g=Graph(self.s);c=g.links(g.objects[('config','EC')]);self.assertEqual(c['equipment_class']['tree'],'equipment_class');self.assertEqual(c['equipment_class']['code'],'EC');self.assertEqual(c['subject']['tree'],'config')
 def test_device_class_still_uses_actual_device_parent(self):
  from relational_query import Graph
  g=Graph(self.s);self.assertEqual(g.links(g.objects[('config','D')])['equipment_class']['code'],'EC')
 def test_bare_class_focus_uses_actual_executed_role(self):
  ctx=self.context(canonical({'kind':'relation','root':{'tree':'config','field':'code','value':'EC'}}));ctx['relational_state']['tasks'][0]['resolved']={'equipment_class':[{'tree':'equipment_class','code':'EC'}]}
  raw=self.raw(action='new',quote='设备类呢',root={'type':'global','quote':'设备类呢'},set={'kind':'relation','population':'objects'});raw['mode']='new'
  v,_=self.run_delta(raw,ctx,'设备类呢');self.assertEqual(v['tasks'][0]['spec']['root'],{'tree':'equipment_class','field':'code','value':'EC'})

class DeltaIntentControls(unittest.TestCase):
 setUpClass=classmethod(Codec.setUpClass.__func__)
 q=Codec.q
 context=Codec.context
 raw=Codec.raw
 run_delta=Codec.run_delta
 def test_distribution_missing_group_is_not_exclusive_filter(self):
  raw=self.raw(quote='按部件类分布统计，缺失关联单列',set={'kind':'collection','population':'parts','group_by':'class','only':'missing_class'})
  v,_=self.run_delta(raw,self.context(self.q(population='parts')),'按部件类分布统计，缺失关联单列');q=v['tasks'][0]['spec'];self.assertEqual(q['group_by'],'class');self.assertIsNone(q['only'])
 def test_explicit_missing_only_cannot_be_hidden_in_distribution(self):
  raw=self.raw(quote='只看缺失部件，按部件类统计，缺失单列',set={'group_by':'class','only':'missing_class'})
  with self.assertRaises(ValueError):self.run_delta(raw,self.context(self.q(population='parts')),'只看缺失部件，按部件类统计，缺失单列')
 def test_remove_last_filter_keeps_single_point_relation_delivery(self):
  ctx=self.context(self.q(root={'tree':'points','field':'code','value':'UNRELATED'},filters=[{'field':'source','operator':'equals','value':'S'}]))
  raw=self.raw(quote='撤销来源条件，沿真实父边查关联',set={'kind':'relation','population':'points'},filters=[{'action':'remove','selector':{'field':'source'},'quote':'撤销来源条件'}])
  v,_=self.run_delta(raw,ctx,'撤销来源条件，沿真实父边查关联');self.assertEqual(v['tasks'][0]['spec']['kind'],'relation');self.assertEqual(v['tasks'][0]['spec']['filters'],[])
 def test_unrequested_sort_is_not_a_task_change(self):
  ctx=self.context(self.q(sort=['source','line']));v,_=self.run_delta(self.raw(quote='逐行列原CSV行号',set={'properties':['line'],'sort':['line']}),ctx,'逐行列原CSV行号');self.assertEqual(v['tasks'][0]['spec']['sort'],['source','line'])
 def test_explicit_sort_is_still_applied(self):
  v,_=self.run_delta(self.raw(quote='按原行号升序',set={'sort':['line']}),self.context(),'按原行号升序');self.assertEqual(v['tasks'][0]['spec']['sort'],['line'])
 def test_missing_reason_is_delivered_by_fixed_view(self):
  raw=self.raw(quote='只查缺失分类部件，列缺失原因',set={'kind':'collection','population':'parts','only':'missing_class','properties':['code','name','missing_reason']})
  v,_=self.run_delta(raw,self.context(self.q(population='parts')),'只查缺失分类部件，列缺失原因');self.assertEqual(v['tasks'][0]['spec']['properties'],[])
 def test_explicit_new_same_root_does_not_keep_old_class_filter(self):
  ctx=self.context(self.q(classes={'part_class':'BC'},filters=[{'field':'source','operator':'equals','value':'S'}]))
  raw=self.raw(quote='现在另查PBS L&D全部监测按功能位置分组',set={'kind':'collection','population':'points','group_by':'location'})
  v,_=self.run_delta(raw,ctx,'现在另查PBS L&D全部监测按功能位置分组');q=v['tasks'][0]['spec'];self.assertEqual(q['root']['value'],'L&D');self.assertEqual(q['classes'],{});self.assertEqual(q['filters'],[])
 def test_only_one_branch_new_target_does_not_reset_other_task(self):
  q=self.q();ctx={'relational_state':{'tasks':[{'id':1,'spec':q},{'id':2,'spec':self.q(population='parts')}]}}
  raw=self.raw(quote='只修改第一项，另查PBS L的设备；第二项保持',set={'kind':'collection','population':'devices'},root={'type':'literal','tree':'pbs','field':'code','value':'L','quote':'PBS L'})
  v,_=self.run_delta(raw,ctx,'只修改第一项，另查PBS L的设备；第二项保持');self.assertEqual(v['tasks'][1]['spec'],ctx['relational_state']['tasks'][1]['spec'])
 def test_registered_type_quantity_question_requires_graph_path(self):
  from relational_planner import required_relation
  self.assertTrue(required_relation('构型直属下级按对象类型分别有多少个',{}))

class TaskOwnershipRegression(unittest.TestCase):
 setUpClass=classmethod(Codec.setUpClass.__func__)
 q=Codec.q
 context=Codec.context
 raw=Codec.raw
 run_delta=Codec.run_delta
 def test_same_view_defaults_do_not_erase_presentation_or_condition(self):
  before=self.q(group_by='source',properties=['value'],limit=2,only='unmatched',filters=[{'field':'switch','operator':'equals','value':'开启'}]);ctx=self.context(before)
  raw=self.raw(quote='再限定来源为S，其余不变',set={'kind':'collection','population':'points','group_by':None,'properties':[],'sort':[],'limit':None,'only':None},filters=[{'action':'add','condition':{'field':'source','operator':'equals','value':'S'},'quote':'再限定来源为S'}])
  v,_=self.run_delta(raw,ctx,'再限定来源为S，其余不变');q=v['tasks'][0]['spec']
  for key in ('kind','population','group_by','properties','limit','sort','only','root','classes'):self.assertEqual(q[key],before[key],key)
  self.assertEqual(len(q['filters']),2)
 def test_unrequested_source_distribution_is_not_added_for_two_totals(self):
  raw=self.raw(action='new',quote='PBS L&D全部后代测点，分别给原记录数和不同编码数',set={'kind':'collection','population':'points','group_by':'source'},root={'type':'literal','tree':'pbs','field':'code','value':'L&D','quote':'PBS L&D'});raw['mode']='new'
  v,_=self.run_delta(raw,{},'PBS L&D全部后代测点，分别给原记录数和不同编码数');self.assertIsNone(v['tasks'][0]['spec']['group_by'])
 def test_malformed_role_is_never_silently_rewritten(self):
  raw=self.raw(quote='对照刚才两套部件集合',set={'kind':'compare','population':'parts'},root={'type':'role','task':1,'role':'root'})
  with self.assertRaises(ValueError):self.run_delta(raw,self.context(),'对照刚才两套部件集合')
 def test_explicit_pbs_identity_cannot_be_changed_by_later_point_goal_word(self):
  with self.assertRaises(ValueError):exact_literal('points','code','UNRELATED','PBS UNRELATED的监测原行','PBS UNRELATED的监测原行',{},self.s)
 def test_actual_point_table_qualifier_is_supported(self):
  self.assertEqual(exact_literal('points','code','UNRELATED','监测表UNRELATED的原行','监测表UNRELATED的原行',{},self.s)['tree'],'points')
 def test_monitor_range_is_not_changed_into_single_object(self):
  raw=self.raw(action='new',quote='PBS L&D自身及全部后代监测记录',root={'type':'literal','tree':'pbs','field':'code','value':'L&D','quote':'PBS L&D'},set={'kind':'relation','population':'points','depth':'all'});raw['mode']='new'
  v,_=self.run_delta(raw,{},'PBS L&D自身及全部后代监测记录');self.assertEqual(v['tasks'][0]['spec']['kind'],'collection');self.assertEqual(v['tasks'][0]['spec']['population'],'points')
 def test_global_source_is_checked_on_complete_same_task_quote(self):
  raw=self.raw(action='new',quote='统计PBS各层级对象数量',root={'type':'global','quote':'PBS'},set={'kind':'collection','population':'objects','group_by':'type'});raw['mode']='new'
  v,_=self.run_delta(raw,{},'统计PBS各层级对象数量');self.assertIsNone(v['tasks'][0]['spec']['root'])
 def test_existing_plain_query_owner_handles_plain_filter_edit(self):
  from relational_planner import interpret,ENTRY_TRACE
  from unittest.mock import patch
  with patch('relational_planner.extract') as model:
   v=interpret('取消报警状态条件，只看来源S',{'business_request':{'tasks':[{'id':'t1'}]}},'synthetic')
  self.assertIsNone(v);model.assert_not_called();self.assertEqual(ENTRY_TRACE.value['reason'],'existing_business_owner')

class ProtectedBranchCompilation(unittest.TestCase):
 setUpClass=classmethod(Codec.setUpClass.__func__)
 q=Codec.q
 context=Codec.context
 raw=Codec.raw
 run_delta=Codec.run_delta
 def test_protected_branch_draft_is_discarded_before_reference_binding(self):
  ctx={'relational_state':{'tasks':[{'id':1,'spec':self.q()},{'id':2,'spec':self.q(population='parts')}]}}
  raw=self.raw(quote='只修改第一项，改按来源分组；第二项保持',set={'group_by':'source'})
  raw['tasks'].append({'id':2,'action':'update','root':{'type':'role','task':999,'sql':'invalid'},'set':{'unknown':'invalid'}})
  v,_=self.run_delta(raw,ctx,'只修改第一项，改按来源分组；第二项保持');self.assertEqual(v['tasks'][1]['spec'],ctx['relational_state']['tasks'][1]['spec']);self.assertEqual(v['tasks'][0]['spec']['group_by'],'source')
 def test_active_branch_unknown_reference_is_not_laundered(self):
  ctx={'relational_state':{'tasks':[{'id':1,'spec':self.q()},{'id':2,'spec':self.q(population='parts')}]}}
  raw=self.raw(quote='只修改第一项，第二项保持',root={'type':'role','task':999,'sql':'invalid'})
  with self.assertRaises(ValueError):self.run_delta(raw,ctx,'只修改第一项，第二项保持')

class NumericPredicateIdentity(unittest.TestCase):
 setUpClass=classmethod(Codec.setUpClass.__func__)
 q=Codec.q
 context=Codec.context
 raw=Codec.raw
 run_delta=Codec.run_delta
 def test_equivalent_decimal_format_has_stable_condition_identity(self):
  self.assertEqual(condition_id({'field':'value','operator':'gt','value':'1.50'}),condition_id({'field':'value','operator':'gt','value':'1.5'}));self.assertNotEqual(condition_id({'field':'value','operator':'gte','value':'1.5'}),condition_id({'field':'value','operator':'gt','value':'1.5'}))
 def test_numeric_precision_is_never_rounded_by_normalization(self):
  from relational_query import canonical_condition
  value='123456789012345678901234567890.123456789'
  self.assertEqual(canonical_condition({'field':'value','operator':'gt','value':value})['value'],value)
 def test_semantically_repeated_numeric_condition_is_single_predicate(self):
  q=self.q(filters=[{'field':'value','operator':'gt','value':'1.50'},{'field':'value','operator':'gt','value':'1.5'}]);self.assertEqual(len(q['filters']),1)
 def test_remove_equivalent_endpoint_keeps_other_interval_bound(self):
  ctx=self.context(self.q(filters=[{'field':'value','operator':'gt','value':'1.5'},{'field':'value','operator':'lt','value':'10'}]))
  raw=self.raw(quote='撤掉大于1.50条件',filters=[{'action':'remove','selector':{'field':'value','operator':'gt','value':'1.50'},'quote':'撤掉大于1.50条件'}])
  v,_=self.run_delta(raw,ctx,'撤掉大于1.50条件');self.assertEqual(v['tasks'][0]['spec']['filters'],[{'field':'value','operator':'lt','value':'10'}])
 def test_source_text_and_numeric_code_are_not_normalized_as_numbers(self):
  from relational_query import canonical_condition
  for field in ('source','code'):
   self.assertEqual(canonical_condition({'field':field,'operator':'equals','value':'001.50'})['value'],'001.50')

class MissingPredicateAndRowView(unittest.TestCase):
 setUpClass=classmethod(Codec.setUpClass.__func__)
 q=Codec.q
 context=Codec.context
 raw=Codec.raw
 run_delta=Codec.run_delta
 def test_explicit_missing_location_cannot_become_missing_class(self):
  q='只列刚才没有精确功能位置归属的原记录，取消分组';raw=self.raw(quote=q,set={'group_by':None,'only':'missing_class'})
  v,_=self.run_delta(raw,self.context(self.q(group_by='location')),q);self.assertEqual(v['tasks'][0]['spec']['only'],'unmatched')
 def test_explicit_missing_class_cannot_become_missing_location(self):
  q='只查缺失分类依据的现场部件';raw=self.raw(quote=q,set={'kind':'collection','population':'parts','only':'unmatched'})
  v,_=self.run_delta(raw,self.context(self.q(population='parts')),q);self.assertEqual(v['tasks'][0]['spec']['only'],'missing_class')
 def test_checking_whether_missing_does_not_filter_records(self):
  q='只列这些记录，检查是否没有功能位置';raw=self.raw(quote=q,set={'properties':['line']})
  v,_=self.run_delta(raw,self.context(),q);self.assertIsNone(v['tasks'][0]['spec']['only'])
 def test_explicit_ordered_original_rows_cancels_old_source_distribution(self):
  q='所有监测原记录按原CSV行号升序，列所属现场部件及功能位置';raw=self.raw(quote=q,set={'group_by':None,'sort':['line'],'properties':['pbs_part','location'],'limit':2})
  v,_=self.run_delta(raw,self.context(self.q(group_by='source')),q);spec=v['tasks'][0]['spec'];self.assertIsNone(spec['group_by']);self.assertEqual(spec['sort'],['line']);self.assertEqual(spec['limit'],2)

class ScopeCompatibleRepresentations(unittest.TestCase):
 setUpClass=classmethod(Codec.setUpClass.__func__)
 q=Codec.q
 context=Codec.context
 raw=Codec.raw
 run_delta=Codec.run_delta
 def test_unique_class_name_after_position_clause_is_not_a_pbs_identity(self):
  root=exact_literal('equipment_class','name','设备分类','PBS L位置内，设备分类对应的现场设备','PBS L位置内，设备分类对应的现场设备',{},self.s);self.assertEqual(root['tree'],'equipment_class')
 def test_empty_default_compare_root_is_noop_for_noncomparison(self):
  raw=self.raw(set={'compare_root':None});v,_=self.run_delta(raw,self.context());self.assertIsNone(v['tasks'][0]['spec']['compare_root'])
 def test_empty_compare_root_cannot_clear_real_comparison_operand(self):
  q=self.q(population='parts',kind='compare',compare_root={'tree':'config','field':'code','value':'D'})
  with self.assertRaises(ValueError):self.run_delta(self.raw(compare_root=None),self.context(q))
 def test_repeated_old_root_without_current_quote_does_not_change_identity(self):
  raw=self.raw(root={'type':'literal','tree':'pbs','field':'code','value':'L&D','quote':'上一轮完整PBS L&D'},set={'properties':['value']})
  v,_=self.run_delta(raw,self.context());self.assertEqual(v['tasks'][0]['spec']['root']['value'],'L&D')
 def test_stale_different_root_quote_is_not_accepted(self):
  raw=self.raw(root={'type':'literal','tree':'pbs','field':'code','value':'L','quote':'上一轮完整PBS L'},set={'properties':['value']})
  with self.assertRaises(ValueError):self.run_delta(raw,self.context())
 def test_explicit_code_order_records_are_not_old_location_distribution(self):
  q='从原记录按完整编码升序取前3条，列测量值';raw=self.raw(quote=q,set={'group_by':None,'sort':['code'],'limit':3,'properties':['value'],'only':'unmatched'})
  v,_=self.run_delta(raw,self.context(self.q(group_by='location')),q);self.assertIsNone(v['tasks'][0]['spec']['group_by'])
 def test_class_filter_record_delivery_cancels_old_class_summary(self):
  q='取消前4类限制，只查当前部件类，列出编码和数量';raw=self.raw(quote=q,set={'kind':'collection','population':'parts','group_by':'class','limit':None})
  v,_=self.run_delta(raw,self.context(self.q(population='parts',group_by='class',limit=4)),q);self.assertIsNone(v['tasks'][0]['spec']['group_by']);self.assertIsNone(v['tasks'][0]['spec']['limit'])
 def test_projection_with_missing_annotation_does_not_add_predicate(self):
  q='只列编码名称并注明没有功能位置时的原因';raw=self.raw(quote=q,set={'properties':['name','code']})
  v,_=self.run_delta(raw,self.context(),q);self.assertIsNone(v['tasks'][0]['spec']['only'])

class DomainSourceCompatibility(unittest.TestCase):
 setUpClass=classmethod(Codec.setUpClass.__func__)
 q=Codec.q
 context=Codec.context
 raw=Codec.raw
 run_delta=Codec.run_delta
 def test_shared_original_table_sentence_need_not_be_rewritten_as_quote(self):
  text='EC在构型树和设备类表里分别查描述和父编码'
  raw=self.raw(action='new',quote='查设备类EC的父编码',root={'type':'literal','tree':'equipment_class','field':'code','value':'EC','quote':'EC在设备类表'},set={'kind':'relation','population':'objects'});raw['mode']='new'
  v,_=self.run_delta(raw,{},text);self.assertEqual(v['tasks'][0]['spec']['root']['tree'],'equipment_class')
 def test_quote_fallback_does_not_accept_unknown_code(self):
  raw=self.raw(action='new',quote='查不存在的编码',root={'type':'literal','tree':'config','field':'code','value':'FAKE','quote':'FAKE在构型树'},set={'kind':'relation','population':'objects'});raw['mode']='new'
  with self.assertRaises(ValueError):self.run_delta(raw,{},'EC在构型树原记录')
 def test_pbs_layer_alias_uses_same_original_type_field(self):
  raw=self.raw(action='new',quote='统计PBS各层级对象数量',root={'type':'global','quote':'PBS'},set={'kind':'collection','population':'objects','group_by':'level'});raw['mode']='new'
  v,_=self.run_delta(raw,{},'统计PBS各层级对象数量');self.assertEqual(v['tasks'][0]['spec']['group_by'],'type')
 def test_config_numeric_layer_cannot_be_changed_to_type_distribution(self):
  raw=self.raw(action='new',quote='构型D全部下级按原登记层级统计',root={'type':'literal','tree':'config','field':'code','value':'D','quote':'构型D'},set={'kind':'collection','population':'objects','group_by':'level'});raw['mode']='new'
  with self.assertRaises(ValueError):self.run_delta(raw,{},'构型D全部下级按原登记层级统计')
 def test_two_collection_comparison_fills_only_unique_executed_missing_operand(self):
  pbs=self.q(population='parts');cfg=self.q(population='parts',root={'tree':'config','field':'code','value':'D'});ctx=self.context(cfg);ctx['relational_history']=[{'state':{'tasks':[{'id':1,'spec':pbs}]}},{'state':{'tasks':[{'id':1,'spec':cfg}]}}]
  raw=self.raw(quote='对照刚才两套部件集合',set={'kind':'compare','population':'parts'},compare_root={'type':'literal','tree':'config','field':'code','value':'D','quote':'D'})
  raw['tasks'][0]['quote']='对照刚才两套部件集合D';v,_=self.run_delta(raw,ctx,'对照刚才两套部件集合D');self.assertEqual(v['tasks'][0]['spec']['root']['tree'],'pbs')

class ClassificationNodeShape(unittest.TestCase):
 def test_real_class_node_type_small_class_uses_exact_dictionary_counterpart(self):
  from data import Store
  from relational_query import Graph
  cfg=fixtures.obj('EC','TOP','小类节点','小类',config=True);eq={'对象编码':'EC','父对象编码':'TOP','描述':'字典原描述','层级':'3'}
  store=Store(dataset=[{'kind':kind,'file':kind+'.csv','sha256':'0'*64,'rows':rows} for kind,rows in [('config',[cfg]),('equipment_class',[eq])]])
  try:
   g=Graph(store);links=g.links(g.objects[('config','EC')]);self.assertEqual(links['equipment_class']['tree'],'equipment_class');self.assertEqual(links['equipment_class']['name'],'字典原描述');self.assertEqual(links['subject']['name'],'小类节点')
  finally:store.db.close()

class RetainedClassCondition(unittest.TestCase):
 setUpClass=classmethod(Codec.setUpClass.__func__)
 q=Codec.q
 context=Codec.context
 raw=Codec.raw
 run_delta=Codec.run_delta
 def test_declared_keep_class_does_not_rebind_to_pbs_root_role(self):
  q='仍保留功能位置和设备类这两个限制，按部件类统计';ctx=self.context(self.q(classes={'equipment_class':'EC'}));raw=self.raw(quote=q,set={'kind':'collection','population':'parts','group_by':'class'},classes=[{'action':'set','tree':'equipment_class','reference':{'type':'role','task':1,'role':'root','quote':'设备类'}}])
  v,_=self.run_delta(raw,ctx,q);self.assertEqual(v['tasks'][0]['spec']['classes'],{'equipment_class':'EC'})
 def test_declared_keep_does_not_hide_explicit_cancel(self):
  q='保持范围，取消设备类限制';ctx=self.context(self.q(classes={'equipment_class':'EC'}));raw=self.raw(quote=q,classes=[{'action':'remove','tree':'equipment_class','quote':'取消设备类限制'}])
  v,_=self.run_delta(raw,ctx,q);self.assertEqual(v['tasks'][0]['spec']['classes'],{})

class AssociationAndComparisonDelivery(unittest.TestCase):
 setUpClass=classmethod(Codec.setUpClass.__func__)
 q=Codec.q
 context=Codec.context
 raw=Codec.raw
 run_delta=Codec.run_delta
 def association_context(self,config_id=1):
  roots={config_id:{'tree':'config','field':'code','value':'D'},3-config_id:{'tree':'equipment_class','field':'code','value':'EC'}}
  return {'relational_state':{'tasks':[{'id':i,'spec':canonical({'kind':'relation','root':roots[i]})} for i in (1,2)]}}
 def test_current_association_omitted_root_and_old_retained_branch_have_one_new_goal(self):
  text='构型D所属设备类究竟应该读取EC还是D'
  raw={'version':2,'handled':True,'mode':'update','tasks':[{'id':1,'action':'update','quote':text,'set':{'kind':'relation','population':'objects'}},{'id':2,'action':'retain'}]}
  v,_=self.run_delta(raw,self.association_context(),text);self.assertEqual(len(v['tasks']),1);self.assertEqual(v['tasks'][0]['spec']['root'],{'tree':'config','field':'code','value':'D'})
 def test_current_association_actual_role_roots_do_not_retain_old_alternative_task(self):
  text='构型D所属设备类究竟应该读取EC还是D'
  raw={'version':2,'handled':True,'mode':'update','tasks':[{'id':i,'action':'update','quote':text,'set':{'kind':'relation','population':'objects'},'root':{'type':'role','task':i,'role':'root','quote':text}} for i in (1,2)]}
  v,_=self.run_delta(raw,self.association_context(),text);self.assertEqual(len(v['tasks']),1);self.assertEqual(v['tasks'][0]['spec']['root']['tree'],'config')
 def test_current_independent_association_allocates_new_task_one_after_old_second_subject(self):
  text='构型D所属设备类究竟应该读取EC还是D'
  raw={'version':2,'handled':True,'mode':'update','tasks':[{'id':1,'action':'retain'},{'id':2,'action':'update','quote':text,'set':{'kind':'relation','population':'objects'}}]}
  v,_=self.run_delta(raw,self.association_context(2),text);self.assertEqual([t['id'] for t in v['tasks']],[1]);self.assertEqual(v['tasks'][0]['spec']['root']['tree'],'config')
 def test_old_root_cannot_supply_unmentioned_complete_current_subject(self):
  text='构型EC所属设备类究竟应该读取EC还是D'
  raw=self.raw(quote=text,set={'kind':'relation','population':'objects'})
  with self.assertRaises(ValueError):self.run_delta(raw,self.association_context(),text)
 def test_additional_class_table_query_is_not_silently_removed_as_an_alternative(self):
  text='构型D所属设备类究竟应该读取EC还是D，另外查设备类EC的父编码'
  raw={'version':2,'handled':True,'mode':'update','tasks':[{'id':i,'action':'update','quote':text,'set':{'kind':'relation','population':'objects'}} for i in (1,2)]}
  v,_=self.run_delta(raw,self.association_context(),text);self.assertEqual(len(v['tasks']),2)
 def test_explicit_numbered_update_keeps_other_task_despite_full_association_subject(self):
  text='只修改第1项：构型D所属设备类究竟应该读取EC还是D'
  raw=self.raw(quote=text,set={'kind':'relation','population':'objects'})
  ctx=self.association_context();v,_=self.run_delta(raw,ctx,text);self.assertEqual(len(v['tasks']),2);self.assertEqual(v['tasks'][1]['spec'],ctx['relational_state']['tasks'][1]['spec'])
 def test_current_single_association_replaces_previous_original_table_batch(self):
  text='构型D所属的设备类究竟应该读取EC还是D'
  ctx={'relational_state':{'tasks':[{'id':1,'spec':canonical({'kind':'relation','root':{'tree':'config','field':'code','value':'D'}})},{'id':2,'spec':canonical({'kind':'relation','root':{'tree':'equipment_class','field':'code','value':'EC'}})}]}}
  tasks=[{'id':tid,'action':'update','quote':text,'set':{'kind':'relation','population':'objects','boundary':'same_record'},'root':{'type':'literal','tree':tree,'field':'code','value':v,'quote':quote}} for tid,tree,v,quote in [(1,'config','D','构型D'),(2,'equipment_class','EC','EC')]]
  raw={'version':2,'handled':True,'mode':'update','tasks':tasks};v,_=self.run_delta(raw,ctx,text);self.assertEqual(len(v['tasks']),1);self.assertEqual(v['tasks'][0]['spec']['root']['tree'],'config')
 def test_executed_two_table_compare_is_not_reversed_by_current_template_code(self):
  pbs=self.q(population='parts');cfg=self.q(population='parts',root={'tree':'config','field':'code','value':'D'});ctx=self.context(cfg);ctx['relational_history']=[{'state':{'tasks':[{'id':1,'spec':pbs}]}},{'state':{'tasks':[{'id':1,'spec':cfg}]}}]
  text='对照刚才两套部件集合，构型D真实下级核对'
  raw=self.raw(quote=text,set={'kind':'compare','population':'parts'},root={'type':'literal','tree':'config','field':'code','value':'D','quote':'构型D'},compare_root={'type':'role','task':1,'role':'root','quote':'刚才两套部件集合'})
  v,_=self.run_delta(raw,ctx,text);self.assertEqual(v['tasks'][0]['spec']['root']['tree'],'pbs');self.assertEqual(v['tasks'][0]['spec']['compare_root']['tree'],'config')


 def test_synthetic_literal_quote_uses_proved_current_source(self):
  text='查询PBS中的L&D下级部件'
  raw=self.raw(action='new',quote=text,set={'kind':'collection','population':'parts'},root={'type':'literal','tree':'pbs','field':'code','value':'L&D','quote':'PBS L&D'});raw['mode']='new'
  v,a=self.run_delta(raw,{},text);self.assertEqual(v['tasks'][0]['spec']['root']['value'],'L&D');self.assertTrue(any('真实引文' in x for x in a))
 def test_synthetic_literal_quote_cannot_import_absent_old_code(self):
  text='查询PBS中的L下级部件'
  raw=self.raw(action='new',quote=text,set={'kind':'collection','population':'parts'},root={'type':'literal','tree':'pbs','field':'code','value':'L&D','quote':'PBS L&D'});raw['mode']='new'
  with self.assertRaises(ValueError):self.run_delta(raw,self.context(),text)
 def test_synthetic_literal_quote_cannot_override_current_tree(self):
  text='查询PBS中的L&D下级部件'
  raw=self.raw(action='new',quote=text,set={'kind':'collection','population':'parts'},root={'type':'literal','tree':'config','field':'code','value':'L&D','quote':'构型L&D'});raw['mode']='new'
  with self.assertRaises(ValueError):self.run_delta(raw,{},text)

if __name__=='__main__':unittest.main()

class FoundationContracts(unittest.TestCase):
 setUpClass=classmethod(Codec.setUpClass.__func__)
 run_delta=Codec.run_delta
 def new(self,question,properties=None,pop='parts'):
  return {'version':2,'handled':True,'mode':'new','tasks':[{'id':1,'action':'new','quote':question,'set':{'kind':'collection','population':pop,'depth':'direct','properties':properties or []},'root':{'type':'literal','tree':'config','field':'code','value':'D','quote':'构型树设备D'}}]}
 def pair(self,question):
  return {'version':2,'handled':True,'mode':'new','tasks':[{'id':1,'action':'new','quote':'设备类字典EC','set':{'kind':'relation','population':'objects'},'root':{'type':'literal','tree':'equipment_class','field':'code','value':'EC','quote':'设备类字典EC'}},{'id':2,'action':'new','quote':'它的直接父记录','set':{'kind':'relation','population':'objects'},'root':{'type':'role','task':1,'role':'parent','quote':'它的直接父记录'}}]}
 def test_explicit_parent_column_is_not_lost_by_empty_independent_projection(self):
  q='只查构型树设备D的直接下级部件，逐条列编码、名称和父编码'
  v,_=self.run_delta(self.new(q),{},q);self.assertEqual(v['tasks'][0]['spec']['properties'],['parent']);self.assertEqual(v['tasks'][0]['spec']['depth'],'direct')
 def test_parent_completion_preserves_other_explicit_columns(self):
  q='只查构型树设备D的直接下级部件，逐条给父编码及原层级'
  v,_=self.run_delta(self.new(q,['level']),{},q);self.assertEqual(v['tasks'][0]['spec']['properties'],['level','parent'])
 def test_explicit_no_parent_column_cannot_be_added(self):
  q='只查构型树设备D的直接下级部件，只列编码和名称，不要列父编码'
  v,_=self.run_delta(self.new(q),{},q);self.assertNotIn('parent',v['tasks'][0]['spec']['properties'])
 def test_dictionary_subject_and_actual_direct_parent_share_one_receipt(self):
  q='查设备类字典EC和它的直接父记录，给编码和名称'
  v,a=self.run_delta(self.pair(q),{},q);self.assertEqual(len(v['tasks']),1);self.assertEqual(v['tasks'][0]['spec']['root']['value'],'EC');self.assertTrue(any('同一关系回执' in x for x in a))
 def test_explicit_numbered_parent_tasks_are_not_silently_merged(self):
  q='第一项查设备类字典EC，第二项查它的直接父记录'
  v,_=normalize_delta(self.pair(q),q,{},self.s);self.assertEqual(len(v['tasks']),2)
 def test_parent_merge_does_not_hide_unknown_identity_keys(self):
  q='查设备类字典EC和它的直接父记录';raw=self.pair(q);raw['tasks'][0]['root']['sql']='unsafe'
  with self.assertRaises(ValueError):normalize_delta(raw,q,{},self.s)
 def test_missing_class_explanation_has_one_collection_contract(self):
  root={'tree':'pbs','field':'code','value':'L&D'}
  a=canonical({'kind':'collection','population':'parts','root':root,'only':'missing_class','boundary':'classification','properties':['parent']})
  b=canonical({'kind':'collection','population':'parts','root':root,'only':'missing_class','properties':['parent','class_code']})
  self.assertEqual(a,b);self.assertEqual(a['only'],'missing_class');self.assertIsNone(a['boundary'])
 def test_classification_normalization_does_not_erase_other_boundaries(self):
  q=canonical({'kind':'collection','population':'parts','root':{'tree':'pbs','field':'code','value':'L&D'},'only':'missing_class','boundary':'duration'})
  self.assertEqual(q['boundary'],'duration')

class ClassInstanceAnchor(unittest.TestCase):
 setUpClass=classmethod(Codec.setUpClass.__func__)
 def request(self,q,root='EC'):
  return {'version':2,'handled':True,'mode':'new','tasks':[{'id':1,'action':'new','quote':q,'set':{'kind':'relation','population':'devices','depth':'all'},'root':{'type':'literal','tree':'config','field':'code','value':root,'quote':'完整类编码'+root},'classes':[{'action':'set','tree':'equipment_class','reference':{'type':'literal','tree':'equipment_class','field':'name','value':'设备分类','quote':'设备类字典中的“设备分类”'}}]}]}
 def test_explicit_global_instance_lookup_uses_proven_class_anchor(self):
  from relational_planner import bound_semantics
  q='用设备类字典中的“设备分类”（完整类编码EC）反查全部PBS现场设备，列编码和名称'
  raw,a=normalize_delta(self.request(q),q,{},self.s);v=bound_semantics(compile_delta(raw,q,{},self.s)[0],self.s);spec=v['tasks'][0]['spec'];self.assertIsNone(spec['root']);self.assertEqual(spec['classes'],{'equipment_class':'EC'});self.assertEqual(spec['population'],'devices')
 def test_real_pbs_range_prevents_global_class_anchor_rewrite(self):
  q='用设备类字典中的“设备分类”（完整类编码EC）在PBS L&D下级反查全部PBS现场设备'
  raw,_=normalize_delta(self.request(q),q,{},self.s);self.assertEqual(raw['tasks'][0]['root']['tree'],'config')
 def test_equipment_template_is_not_a_class_node_anchor(self):
  q='用设备类字典中的“设备分类”（完整类编码D）反查全部PBS现场设备'
  raw,_=normalize_delta(self.request(q,'D'),q,{},self.s);self.assertEqual(raw['tasks'][0]['root']['value'],'D');self.assertEqual(raw['tasks'][0]['root']['tree'],'config')
