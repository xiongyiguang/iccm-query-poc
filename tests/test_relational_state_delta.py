"""状态所属权与真实身份的反例矩阵，不调用模型。"""
import copy,json,sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import test_relational_query as fixture
from relational_query import canonical,execute
from relational_state import compile_delta,condition_catalog,RelationalHandoff,exact_literal,reference

class StateDelta(unittest.TestCase):
 @classmethod
 def setUpClass(cls):fixture.Relations.setUpClass();cls.store=fixture.Relations.s
 def q(self,**kw):return canonical({'kind':'collection','population':'points','root':{'tree':'pbs','field':'code','value':'L&D'},**kw})
 def context(self,*specs):return {'relational_state':{'tasks':[{'id':i,'spec':copy.deepcopy(q),'resolved':{}} for i,q in enumerate(specs,1)]}}
 def task(self,tid=1,**kw):return {'id':tid,'action':'update','quote':'更新原结果','set':{},'filters':[],'classes':[],**kw}
 def payload(self,*patches,mode='update'):return {'version':2,'handled':True,'mode':mode,'tasks':list(patches)}
 def compile(self,payload,ctx,question='更新原结果'):return compile_delta(payload,question,ctx,self.store)
 def test_output_change_preserves_every_original_filter_and_root(self):
  filters=[{'field':'switch','operator':'equals','value':'开启'},{'field':'status','operator':'equals','value':'已报警'},{'field':'source','operator':'equals','value':'S'}]
  ctx=self.context(self.q(filters=filters,group_by='source'));before=copy.deepcopy(ctx)
  v,a=self.compile(self.payload(self.task(set={'group_by':None,'properties':['value'],'limit':3,'sort':['code']})),ctx)
  q=v['tasks'][0]['spec'];self.assertEqual(q['filters'],before['relational_state']['tasks'][0]['spec']['filters']);self.assertEqual(q['root']['value'],'L&D');self.assertIsNone(q['group_by']);self.assertEqual(q['limit'],3);self.assertEqual(ctx,before)
 def test_add_source_does_not_rebuild_output_or_existing_conditions(self):
  ctx=self.context(self.q(filters=[{'field':'switch','operator':'equals','value':'开启'}],group_by='location'))
  p=self.task(filters=[{'action':'add','condition':{'field':'source','operator':'equals','value':'S'},'quote':'更新原结果'}]);v,_=self.compile(self.payload(p),ctx)
  self.assertEqual(v['tasks'][0]['spec']['group_by'],'location');self.assertEqual(len(v['tasks'][0]['spec']['filters']),2)
 def test_removing_source_keeps_the_switch_condition(self):
  ctx=self.context(self.q(filters=[{'field':'switch','operator':'equals','value':'开启'},{'field':'source','operator':'equals','value':'S'}]))
  p=self.task(filters=[{'action':'remove','selector':{'field':'source'},'quote':'更新原结果'}]);v,_=self.compile(self.payload(p),ctx)
  self.assertEqual(v['tasks'][0]['spec']['filters'],[{'field':'switch','operator':'equals','value':'开启'}])
 def test_ambiguous_field_removal_cannot_drop_both_numeric_limits(self):
  ctx=self.context(self.q(filters=[{'field':'value','operator':'gt','value':'0'},{'field':'value','operator':'lt','value':'20'}]))
  p=self.task(filters=[{'action':'remove','selector':{'field':'value'},'quote':'更新原结果'}])
  with self.assertRaises(ValueError):self.compile(self.payload(p),ctx)
 def test_stable_condition_id_removes_only_the_selected_upper_limit(self):
  ctx=self.context(self.q(filters=[{'field':'value','operator':'gt','value':'0'},{'field':'value','operator':'lt','value':'20'}]));catalog=condition_catalog(ctx)['1'];fid=next(x['id'] for x in catalog if x['condition']['operator']=='lt')
  p=self.task(filters=[{'action':'remove','selector':{'id':fid},'quote':'更新原结果'}]);v,_=self.compile(self.payload(p),ctx)
  self.assertEqual(v['tasks'][0]['spec']['filters'],[{'field':'value','operator':'gt','value':'0'}])
 def test_replacing_lower_limit_leaves_upper_limit_unchanged(self):
  ctx=self.context(self.q(filters=[{'field':'value','operator':'gt','value':'0'},{'field':'value','operator':'lt','value':'20'}]))
  p=self.task(filters=[{'action':'replace','selector':{'field':'value','operator':'gt'},'condition':{'field':'value','operator':'gte','value':'3'},'quote':'更新原结果'}]);v,_=self.compile(self.payload(p),ctx)
  self.assertIn({'field':'value','operator':'lt','value':'20'},v['tasks'][0]['spec']['filters']);self.assertIn({'field':'value','operator':'gte','value':'3'},v['tasks'][0]['spec']['filters'])
 def test_new_numeric_interval_can_add_both_limits(self):
  p=self.task(filters=[{'action':'add','condition':{'field':'value','operator':op,'value':val},'quote':'更新原结果'} for op,val in [('gt','0'),('lt','20')]])
  v,_=self.compile(self.payload(p),self.context(self.q()));self.assertEqual(len(v['tasks'][0]['spec']['filters']),2)
 def test_unknown_condition_id_cannot_remove_anything(self):
  ctx=self.context(self.q(filters=[{'field':'source','operator':'equals','value':'S'}]));before=copy.deepcopy(ctx)
  p=self.task(filters=[{'action':'remove','selector':{'id':'f-unknown'},'quote':'更新原结果'}])
  with self.assertRaises(ValueError):self.compile(self.payload(p),ctx)
  self.assertEqual(ctx,before)
 def test_omitted_other_task_is_exactly_retained(self):
  first=self.q(group_by='source');second=self.q(population='parts',group_by='class',limit=2);ctx=self.context(first,second)
  v,a=self.compile(self.payload(self.task(set={'sort':['code']})),ctx)
  self.assertEqual(v['tasks'][1]['spec'],second);self.assertEqual(a['retained_ids'],[2])
 def test_unknown_task_number_cannot_modify_existing_task(self):
  with self.assertRaises(ValueError):self.compile(self.payload(self.task(tid=3)),self.context(self.q(),self.q(population='parts')))
 def test_pure_retain_cannot_claim_delivery(self):
  with self.assertRaises(ValueError):self.compile(self.payload({'id':1,'action':'retain'}),self.context(self.q()))
 def test_grouped_to_records_clears_ranking_but_keeps_class_constraint(self):
  ctx=self.context(self.q(population='parts',classes={'part_class':'BC'},group_by='class',limit=4))
  v,_=self.compile(self.payload(self.task(set={'group_by':None})),ctx);q=v['tasks'][0]['spec'];self.assertIsNone(q['group_by']);self.assertIsNone(q['limit']);self.assertEqual(q['classes'],{'part_class':'BC'})
 def test_explicit_keep_uses_old_columns_and_row_order(self):
  ctx=self.context(self.q(properties=['value'],sort=['source','line'],limit=2))
  v,_=self.compile(self.payload(self.task(set={'group_by':None,'properties':'keep','sort':'keep','limit':'keep'})),ctx)
  self.assertEqual(v['tasks'][0]['spec']['properties'],['value']);self.assertEqual(v['tasks'][0]['spec']['sort'],['source','line']);self.assertEqual(v['tasks'][0]['spec']['limit'],2)
 def test_keep_only_group_is_not_a_new_output_view(self):
  ctx=self.context(self.q(group_by='source',properties=['value'],limit=2))
  v,_=self.compile(self.payload(self.task(set={'group_by':'keep'})),ctx)
  self.assertEqual(v['tasks'][0]['spec'],ctx['relational_state']['tasks'][0]['spec'])
 def test_new_context_reference_cannot_reset_existing_filters(self):
  p=self.task(action='new',set={'kind':'collection','population':'points'},quote='从刚才结果中取明细')
  with self.assertRaises(ValueError):self.compile(self.payload(p,mode='new'),self.context(self.q(filters=[{'field':'switch','operator':'equals','value':'开启'}])),'从刚才结果中取明细')
 def test_literal_new_code_cannot_be_expanded_to_old_longer_code(self):
  p=self.task(root={'type':'literal','tree':'config','field':'code','value':'D#p1','quote':'构型D的记录'},quote='构型D的记录')
  with self.assertRaises(ValueError):self.compile(self.payload(p),self.context(self.q()),'构型D的记录')
 def test_both_models_using_old_root_cannot_swallow_a_new_ambiguous_code(self):
  ctx=self.context(canonical({'kind':'relation','root':{'tree':'config','field':'code','value':'D'}}))
  p=self.task(quote='EC是什么对象？')
  with self.assertRaises(RelationalHandoff):self.compile(self.payload(p),ctx,'EC是什么对象？')
 def test_ambiguous_new_tree_cannot_borrow_prior_different_root(self):
  p=self.task(root={'type':'literal','tree':'config','field':'code','value':'EC','quote':'EC是什么对象？'},quote='EC是什么对象？')
  with self.assertRaises(RelationalHandoff):self.compile(self.payload(p),self.context(self.q()),'EC是什么对象？')
 def test_explicit_tree_disambiguates_the_same_actual_code(self):
  p=self.task(root={'type':'literal','tree':'equipment_class','field':'code','value':'EC','quote':'设备类EC是什么对象？'},quote='设备类EC是什么对象？',set={'kind':'relation','population':'objects'})
  v,_=self.compile(self.payload(p),self.context(self.q()),'设备类EC是什么对象？');self.assertEqual(v['tasks'][0]['spec']['root'],{'tree':'equipment_class','field':'code','value':'EC'})
 def test_repeated_same_code_keeps_both_explicit_original_table_occurrences(self):
  text='分别查构型EC和设备类EC的描述与父编码'
  for tree in ('config','equipment_class'):
   root=exact_literal(tree,'code','EC',text,text,{},self.store);self.assertEqual(root['tree'],tree)
 def test_reverse_original_table_order_does_not_erase_second_code_occurrence(self):
  text='分别查设备类EC与构型EC的原层级'
  root=exact_literal('config','code','EC',text,text,{},self.store);self.assertEqual(root['tree'],'config')
 def test_single_explicit_domain_cannot_be_rebound_through_identity_alias(self):
  text='构型EC所属设备类的真实关联'
  for field in ('code','identity'):
   with self.subTest(field=field),self.assertRaises(ValueError):exact_literal('equipment_class',field,'EC',text,text,{},self.store)
 def test_current_same_selected_object_keeps_its_actual_tree(self):
  ctx=self.context(canonical({'kind':'relation','root':{'tree':'equipment_class','field':'code','value':'EC'}}))
  p=self.task(root={'type':'literal','tree':'equipment_class','field':'code','value':'EC','quote':'EC是什么对象？'},quote='EC是什么对象？')
  v,_=self.compile(self.payload(p),ctx,'EC是什么对象？');self.assertEqual(v['tasks'][0]['spec']['root']['tree'],'equipment_class')
 def test_parent_role_is_resolved_from_executed_identity(self):
  ctx=self.context(canonical({'kind':'relation','root':{'tree':'config','field':'code','value':'D'}}));ctx['relational_state']['tasks'][0]['resolved']={'parent':[{'tree':'config','code':'EC'}]}
  p=self.task(root={'type':'role','task':1,'role':'parent','quote':'更新原结果'})
  v,_=self.compile(self.payload(p),ctx);self.assertEqual(v['tasks'][0]['spec']['root']['value'],'EC')
 def test_dictionary_subject_is_an_actual_class_identity_not_only_a_class_filter(self):
  ctx=self.context(canonical({'kind':'relation','root':{'tree':'equipment_class','field':'code','value':'EC'}}));ctx['relational_state']['tasks'][0]['resolved']={'subject':[{'tree':'equipment_class','code':'EC','name':'设备分类'}]}
  ref={'type':'class','task':1,'tree':'equipment_class','quote':'刚才这个精确设备类'}
  self.assertEqual(reference(ref,ref['quote'],ctx,self.store),{'tree':'equipment_class','field':'code','value':'EC'})
 def test_related_class_is_not_the_dictionary_subject_of_a_different_tree(self):
  ctx=self.context(canonical({'kind':'relation','root':{'tree':'config','field':'code','value':'D'}}));ctx['relational_state']['tasks'][0]['resolved']={'subject':[{'tree':'config','code':'D'}],'equipment_class':[{'tree':'equipment_class','code':'EC'}]}
  ref={'type':'class','task':1,'tree':'equipment_class','quote':'刚才这个类'}
  with self.assertRaises(ValueError):reference(ref,ref['quote'],ctx,self.store)
 def test_class_subject_does_not_guess_parent_or_a_stale_root(self):
  ctx=self.context(canonical({'kind':'relation','root':{'tree':'equipment_class','field':'code','value':'EC'}}));ctx['relational_state']['tasks'][0]['resolved']={'subject':[{'tree':'equipment_class','code':'EC'}]}
  ref={'type':'class','task':1,'tree':'equipment_class','quote':'刚才这个类的上一级'}
  with self.assertRaises(ValueError):reference(ref,ref['quote'],ctx,self.store)
  ctx['relational_state']['tasks'][0]['spec']['root']['value']='OTHER';ref['quote']='刚才这个类'
  with self.assertRaises(ValueError):reference(ref,ref['quote'],ctx,self.store)
 def test_missing_or_multiple_parent_role_is_never_guessed(self):
  for records in ([],[{'tree':'config','code':'D'},{'tree':'config','code':'EC'}]):
   ctx=self.context(self.q());ctx['relational_state']['tasks'][0]['resolved']={'parent':records};p=self.task(root={'type':'role','task':1,'role':'parent','quote':'更新原结果'})
   with self.assertRaises(RelationalHandoff):self.compile(self.payload(p),ctx)
 def test_actual_history_root_changes_only_identity_not_current_filter(self):
  ctx=self.context(self.q(filters=[{'field':'source','operator':'equals','value':'S'}]));ctx['relational_history']=[{'question':'原对象','state':{'tasks':[{'id':1,'spec':self.q(root={'tree':'pbs','field':'code','value':'L'}),'resolved':{}}]}}]
  p=self.task(root={'type':'role','task':1,'history':0,'role':'root','quote':'更新原结果'});v,_=self.compile(self.payload(p),ctx)
  self.assertEqual(v['tasks'][0]['spec']['root']['value'],'L');self.assertEqual(v['tasks'][0]['spec']['filters'],ctx['relational_state']['tasks'][0]['spec']['filters'])
 def test_pending_draft_cannot_supply_role_identity(self):
  ctx=self.context(self.q());ctx['pending_business_request']={'tasks':[{'id':1,'resolved':{'parent':[{'tree':'config','code':'EC'}]}}]}
  with self.assertRaises(RelationalHandoff):self.compile(self.payload(self.task(root={'type':'role','task':1,'role':'parent','quote':'更新原结果'})),ctx)
 def test_whole_registered_table_can_replace_dictionary_root_without_guessing_class(self):
  old=canonical({'kind':'relation','root':{'tree':'part_class','field':'code','value':'BC'}});ctx=self.context(old)
  ctx['relational_state']['tasks'][0]['resolved']={'subject':[{'tree':'part_class','code':'BC'}]}
  text='查整个PBS表的部件，沿用刚才这个类'
  p=self.task(quote=text,set={'kind':'collection','population':'parts'},root={'type':'global','quote':'整个PBS表'},classes=[{'action':'set','tree':'part_class','reference':{'type':'class','task':1,'tree':'part_class','quote':'刚才这个类'}}])
  v,_=self.compile(self.payload(p),ctx,text);self.assertIsNone(v['tasks'][0]['spec']['root']);self.assertEqual(v['tasks'][0]['spec']['classes'],{'part_class':'BC'})
 def test_original_monitor_table_is_a_global_scope_with_source_condition(self):
  text='监测原表按来源筛选';p=self.task(action='new',quote=text,set={'kind':'collection','population':'points'},root={'type':'global','quote':'监测原表'},filters=[{'action':'add','condition':{'field':'source','operator':'equals','value':'S'},'quote':text}])
  v,_=self.compile(self.payload(p,mode='new'),{},text);self.assertIsNone(v['tasks'][0]['spec']['root']);self.assertEqual(v['tasks'][0]['spec']['filters'],[{'field':'source','operator':'equals','value':'S'}])
 def test_table_word_inside_object_name_is_not_whole_table_authority(self):
  text='名称为监测原表的设备'
  with self.assertRaises(ValueError):reference({'type':'global','quote':text},text,{},self.store)
 def test_explicit_history_code_keeps_actual_measurement_namespace_after_name_subset(self):
  code=canonical({'kind':'collection','population':'points','root':{'tree':'points','field':'code','value':'UNRELATED'}});name=canonical({**code,'root':{'tree':'points','field':'name','value':'点一'}});ctx=self.context(name);ctx['relational_history']=[{'state':{'tasks':[{'id':1,'spec':code}]}}]
  text='返回第一轮完整编码UNRELATED的全部原行'
  self.assertEqual(exact_literal('points','code','UNRELATED',text,text,ctx,self.store),code['root'])
 def test_current_explicit_tree_cannot_be_overridden_by_a_historical_code_namespace(self):
  code=canonical({'kind':'collection','population':'points','root':{'tree':'points','field':'code','value':'UNRELATED'}});ctx=self.context(code);ctx['relational_history']=[{'state':{'tasks':[{'id':1,'spec':code}]}}]
  text='这次用PBS完整编码UNRELATED，不用第一轮监测表'
  with self.assertRaises(ValueError):exact_literal('points','code','UNRELATED',text,text,ctx,self.store)
 def test_self_depth_requires_explicit_self_scope(self):
  with self.assertRaises(ValueError):self.compile(self.payload(self.task(set={'depth':'self'})),self.context(self.q()))
 def test_all_descendants_cannot_be_compiled_as_self(self):
  p=self.task(quote='设备自身及全部后代的监测',set={'depth':'self'})
  with self.assertRaises(ValueError):self.compile(self.payload(p),self.context(self.q()),'设备自身及全部后代的监测')
 def test_exact_points_root_automatically_selects_all_same_code_original_rows(self):
  p=self.task(action='new',quote='测点UNRELATED的全部原行',root={'type':'literal','tree':'points','field':'code','value':'UNRELATED','quote':'测点UNRELATED的全部原行'},set={'kind':'collection','population':'points','properties':['value']})
  v,_=self.compile(self.payload(p,mode='new'),{},'测点UNRELATED的全部原行');q=v['tasks'][0]['spec'];self.assertEqual(q['depth'],'self')
  r=execute(self.store,{'operation':'relational','entity':None,'scope':'direct','clarification':'','relational_tasks':v['tasks']});self.assertEqual(len(r['record_facts']),2)
 def test_runtime_rebinding_recompiles_both_deltas_and_rejects_tampering(self):
  from relational_planner import bind,bound_semantics
  ctx=self.context(self.q());raw=self.payload(self.task(quote='按来源分组',set={'group_by':'source'}));v,_=self.compile(raw,ctx,'按来源分组');v=bound_semantics(v,self.store)
  plan={'operation':'relational','entity':None,'scope':'direct','clarification':'','relational_tasks':v['tasks']};trace={'engine':'relational_request','source_question':'按来源分组','validated_intent':copy.deepcopy(plan),'candidate':{'extracted':raw},'independent':{'extracted':copy.deepcopy(raw)}}
  self.assertEqual(bind(self.store,'按来源分组',plan,ctx,trace),plan);trace['independent']['extracted']['tasks'][0]['set']['group_by']=None
  with self.assertRaises(ValueError):bind(self.store,'按来源分组',plan,ctx,trace)
 def test_malformed_model_envelope_is_repaired_without_candidate_leak(self):
  import io
  from relational_planner import extract
  def response(content):return io.StringIO(json.dumps({'id':'synthetic','model':'synthetic','choices':[{'message':{'content':content}}]}))
  record={}
  with patch('urllib.request.build_opener') as builder:
   builder.return_value.open.side_effect=[response('[]'),response('{"handled":false}')]
   result=extract('无法确认对象',{},'synthetic-key','synthetic',record,_store=self.store)
  self.assertEqual(result,{'handled':False});self.assertEqual(builder.return_value.open.call_count,2)
  self.assertEqual(record['schema_repair']['original']['extracted'],[])
  for call in builder.return_value.open.call_args_list:
   payload=json.loads(call.args[0].data)
   self.assertEqual(payload['response_format'],{'type':'json_object'})
   self.assertIn('json',payload['messages'][0]['content'].lower())

if __name__=='__main__':unittest.main()
