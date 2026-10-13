"""类别反查、实际执行历史及原字段交付的异构回归，不调用模型。"""
import copy
import unittest
import test_relational_query as fixtures
from relational_query import canonical,execute,validate_plan,Graph,execute_task
from relational_planner import ground,bound_semantics,remember_context,normalized

class SemanticState(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  fixtures.Relations.setUpClass();cls.store=fixtures.Relations.s
 def q(self,**kw):return canonical({'root':{'tree':'pbs','field':'code','value':'L&D'},'kind':'collection','population':'parts',**kw})
 def plan(self,*specs):return {'operation':'relational','entity':None,'scope':'direct','clarification':'','relational_tasks':[{'id':i,'spec':q} for i,q in enumerate(specs,1)]}
 def relation(self,tree,code,**kw):return self.q(root={'tree':tree,'field':'code','value':code},kind='relation',population='objects',**kw)
 def test_class_anchor_reverse_devices_does_not_enumerate_dictionary(self):
  q=self.q(root={'tree':'equipment_class','field':'code','value':'EC'},population='devices');r=execute(self.store,self.plan(q))
  self.assertEqual([x['code'] for x in r['record_facts']],['L&D']);self.assertIsNone(r['relational_state']['tasks'][0]['spec']['root'])
 def test_class_anchor_reverse_points_keeps_duplicate_original_rows(self):
  q=self.q(root={'tree':'part_class','field':'name','value':'部件分类'},population='points');r=execute(self.store,self.plan(q))
  self.assertEqual((r['population_facts']['record_count'],r['population_facts']['distinct_code_count']),(2,1))
 def test_class_name_anchor_and_class_code_filter_are_proven_same_identity(self):
  q=self.q(root={'tree':'equipment_class','field':'name','value':'设备分类'},population='devices',classes={'equipment_class':'EC'})
  r=execute(self.store,self.plan(q));self.assertEqual([x['code'] for x in r['record_facts']],['L&D'])
 def test_unique_object_name_and_code_are_still_equivalent(self):
  a={'handled':True,'tasks':self.plan(self.relation('pbs','L&D'))['relational_tasks']};b=copy.deepcopy(a);b['tasks'][0]['spec']['root']={'tree':'pbs','field':'name','value':'设备'}
  self.assertEqual(bound_semantics(a,self.store),bound_semantics(b,self.store))
 def test_only_one_task_change_copies_other_real_spec(self):
  from relational_planner import retain_unchanged_tasks
  old=[{'id':1,'spec':self.relation('config','D')},{'id':2,'spec':self.relation('equipment_class','EC')}]
  proposal={'handled':True,'tasks':[{'id':1,'spec':self.relation('config','D#p1')},{'id':2,'spec':self.relation('equipment_class','TOP')}]}
  value,proof=retain_unchanged_tasks(proposal,'只修改第一项，改查其部件；第二项保持上轮目标。',{'relational_state':{'tasks':old}})
  self.assertEqual(value['tasks'][1],old[1]);self.assertEqual(value['tasks'][0]['spec']['root']['value'],'D#p1');self.assertEqual(proof['retained_ids'],[2]);self.assertEqual(proof['restored_ids'],[2])
 def test_retained_parent_description_does_not_walk_again(self):
  from relational_planner import retain_unchanged_tasks
  old=[{'id':1,'spec':self.relation('config','D')},{'id':2,'spec':self.relation('equipment_class','EC')}];proposal={'handled':True,'tasks':[{'id':1,'spec':self.relation('config','D#p1')},{'id':2,'spec':self.relation('equipment_class','TOP')}]}
  value,_=retain_unchanged_tasks(proposal,'第一项改查部件；第二项保持上轮的分类上一级。',{'relational_state':{'tasks':old}});self.assertEqual(value['tasks'][1],old[1])
 def test_partial_condition_retain_does_not_freeze_whole_task(self):
  from relational_planner import retain_unchanged_tasks
  old=[{'id':1,'spec':self.relation('config','D')},{'id':2,'spec':self.relation('equipment_class','EC')}];proposal={'handled':True,'tasks':[{'id':1,'spec':self.relation('config','D')},{'id':2,'spec':self.relation('equipment_class','TOP')}]}
  value,proof=retain_unchanged_tasks(proposal,'第二项保持来源条件，但改查上级记录。',{'relational_state':{'tasks':old}});self.assertEqual(value,proposal);self.assertEqual(proof,{})
 def test_task_control_inside_object_quote_does_not_protect_task(self):
  from relational_planner import retain_unchanged_tasks
  old=[{'id':1,'spec':self.relation('config','D')},{'id':2,'spec':self.relation('equipment_class','EC')}];proposal={'handled':True,'tasks':[{'id':1,'spec':self.relation('config','D')},{'id':2,'spec':self.relation('equipment_class','TOP')}]}
  value,proof=retain_unchanged_tasks(proposal,'查名字叫“第二项保持”的记录。',{'relational_state':{'tasks':old}});self.assertEqual(value,proposal);self.assertEqual(proof,{})
 def test_unquoted_explicit_object_name_is_not_a_task_control(self):
  from relational_planner import retain_unchanged_tasks
  old=[{'id':1,'spec':self.relation('config','D')},{'id':2,'spec':self.relation('equipment_class','EC')}];proposal={'handled':True,'tasks':[{'id':1,'spec':self.relation('config','D')},{'id':2,'spec':self.relation('equipment_class','TOP')}]}
  value,proof=retain_unchanged_tasks(proposal,'查名字叫第二项保持的记录。',{'relational_state':{'tasks':old}});self.assertEqual(value,proposal);self.assertEqual(proof,{})
 def test_exclusive_control_cannot_add_unrequested_task(self):
  from relational_planner import retain_unchanged_tasks
  old=[{'id':1,'spec':self.relation('config','D')},{'id':2,'spec':self.relation('equipment_class','EC')}];proposal={'handled':True,'tasks':old+[{'id':3,'spec':self.relation('config','EC')}]}
  with self.assertRaises(ValueError):retain_unchanged_tasks(proposal,'仅修改任务1的根范围',{'relational_state':{'tasks':old}})
 def test_dictionary_relation_stays_dictionary(self):
  q=self.relation('equipment_class','EC');self.assertEqual(q['root']['tree'],'equipment_class');self.assertEqual(q['kind'],'relation');self.assertEqual(q['classes'],{})
 def test_conflicting_class_anchor_does_not_overwrite_filter(self):
  q=self.q(root={'tree':'equipment_class','field':'code','value':'EC'},population='devices',classes={'equipment_class':'OTHER'})
  with self.assertRaises(ValueError):execute(self.store,self.plan(q))
 def test_executed_class_constraint_is_grounded_for_followup(self):
  prior={'relational_state':{'tasks':[{'id':1,'spec':self.q(classes={'equipment_class':'EC'}),'resolved':{}}]}}
  ground([{'spec':self.q(population='points',root=None,classes={'equipment_class':'EC'})}],'这些设备改查监测记录',prior,self.store)
 def test_pending_draft_class_is_not_an_executed_identity(self):
  prior={'pending_business_request':{'classes':{'equipment_class':'EC'}}}
  with self.assertRaises(ValueError):ground([{'spec':self.q(population='devices',root=None,classes={'equipment_class':'EC'})}],'按刚才类别查询',prior,self.store)
 def test_cross_turn_root_is_grounded_by_actual_history(self):
  prior={'relational_history':[{'question':'原先的设备','state':{'tasks':[{'id':1,'spec':self.q(),'resolved':{}}]}}]}
  ground([{'spec':self.q()}],'返回第一轮指定设备',prior,self.store)
 def test_history_retains_snapshot_not_mutable_current_reference(self):
  state={'tasks':[{'id':1,'spec':self.q(),'resolved':{}}]};now={'relational_state':state};remember_context({},now,'实际查询')
  state['tasks'][0]['spec']['classes']={'part_class':'BC'};self.assertEqual(now['relational_history'][0]['state']['tasks'][0]['spec']['classes'],{})
 def test_history_is_bounded_and_does_not_commit_failed_draft(self):
  current={}
  for i in range(9):
   previous=copy.deepcopy(current);current={'relational_state':{'tasks':[{'id':1,'spec':self.q(limit=i+1),'resolved':{}}]}};remember_context(previous,current,'实际查询')
  self.assertEqual(len(current['relational_history']),6)
  no_state={};remember_context(current,no_state,'失败的未执行原话');self.assertEqual(no_state['relational_history'],current['relational_history'])
 def test_original_config_numeric_level_is_separate_from_type_description(self):
  r=execute_task(Graph(self.store),self.relation('config','D'));cs=[x['cells'] for x in r['records']]
  self.assertTrue(any(c[1:4]==['D','层级','7'] for c in cs));self.assertTrue(any(c[1:4]==['D','设备模板','设备'] for c in cs))
 def test_source_grouping_projects_requested_original_thresholds(self):
  q=self.q(root={'tree':'points','field':'code','value':'UNRELATED'},population='points',group_by='source',properties=['actual_high2','estimate_high2'])
  r=execute_task(Graph(self.store),q);raw=[x['cells'] for x in r['records'] if x['cells'][0]=='原记录'];self.assertEqual(len(raw),2)
  ix=r['columns'].index('真实值报警阈值-高2');iy=r['columns'].index('估计值报警阈值-高2');self.assertEqual([(x[ix],x[iy]) for x in raw],[('1','300'),('未提供','未提供')])
 def test_one_stale_comparison_flag_does_not_block_two_exact_tasks(self):
  a=self.relation('config','D');b=self.relation('equipment_class','EC',boundary='same_record');v=normalized({'handled':True,'tasks':self.plan(a,b)['relational_tasks']});v=bound_semantics(v,self.store)
  self.assertTrue(all(t['spec']['boundary'] is None for t in v['tasks']));r=execute(self.store,self.plan(*[t['spec'] for t in v['tasks']]));self.assertEqual(r['status'],'batch');self.assertEqual(len(r['items']),2);self.assertNotIn('同码位于不同',r['items'][1]['answer'])
 def test_true_same_code_note_is_proven_across_original_tables(self):
  a=self.relation('config','EC');b=self.relation('equipment_class','EC');v=bound_semantics({'handled':True,'tasks':self.plan(a,b)['relational_tasks']},self.store)
  r=execute(self.store,self.plan(*[t['spec'] for t in v['tasks']]));self.assertTrue(all('已核实同码' in x['answer'] for x in r['items']))
 def test_explicit_record_sort_does_not_delegate_to_scalar_attributes(self):
  from unittest.mock import patch
  from relational_planner import interpret
  q=self.q(root={'tree':'points','field':'code','value':'UNRELATED'},population='points',properties=['value'],sort=['source','line'])
  candidate={'handled':True,'tasks':self.plan(q)['relational_tasks']}
  with patch('relational_planner.extract',return_value=copy.deepcopy(candidate)) as extract:
   plan,trace=interpret('UNRELATED原始记录按来源再行号排列，列出测量值',{},'unused',self.store)
  self.assertEqual(extract.call_count,2);self.assertEqual(plan['relational_tasks'][0]['spec']['sort'],['source','line'])
 def test_explicit_original_line_projection_stays_record_delivery(self):
  from unittest.mock import patch
  from relational_planner import interpret
  q=self.q(root={'tree':'points','field':'code','value':'UNRELATED'},population='points',properties=['value'])
  candidate={'handled':True,'tasks':self.plan(q)['relational_tasks']}
  def extracted(question,context,key,model,record,**kwargs):
   raw=copy.deepcopy(candidate);raw['tasks'][0]['spec']['properties']=['line','value'];record['extracted']=raw;return copy.deepcopy(candidate)
  with patch('relational_planner.extract',side_effect=extracted):plan,_=interpret('UNRELATED逐行给原CSV行号和测量值',{},'unused',self.store)
  self.assertEqual(plan['operation'],'relational')
 def test_current_ambiguous_code_directory_keeps_both_trees_before_extraction(self):
  from unittest.mock import patch
  from relational_planner import interpret
  captured=[]
  def decline(question,context,*args,**kwargs):captured.append(copy.deepcopy(context));return {'handled':False}
  old={'relational_state':{'tasks':[{'id':1,'spec':self.relation('config','D')}]}}
  with patch('relational_planner.extract',side_effect=decline):self.assertIsNone(interpret('EC是什么对象？',old,'unused',self.store))
  refs=captured[0]['relational_literal_references'];self.assertEqual({x['domain'] for x in refs if x['value']=='EC'},{'config','equipment_class'})
  self.assertEqual(old['relational_state']['tasks'][0]['spec']['root']['value'],'D');self.assertNotIn('relational_literal_references',old)
 def test_short_code_inside_an_explicit_complete_object_is_not_a_new_reference(self):
  from unittest.mock import patch
  from relational_planner import interpret
  captured=[]
  def decline(question,context,*args,**kwargs):captured.append(copy.deepcopy(context));return {'handled':False}
  with patch('relational_planner.extract',side_effect=decline):interpret('PBS L&D的实际关联是什么？',{},'unused',self.store)
  refs=captured[0]['relational_literal_references'];self.assertIn('L&D',[x['value'] for x in refs]);self.assertNotIn('D',[x['value'] for x in refs])
 def test_single_same_record_flag_is_still_rejected(self):
  with self.assertRaises(ValueError):validate_plan(self.plan(self.relation('config','D',boundary='same_record')))

class BatchHistoryHTTP(unittest.TestCase):
 def test_executed_batch_history_is_saved_after_current_state_commit(self):
  import app,json,threading,urllib.request,uuid
  from http.server import ThreadingHTTPServer
  from unittest.mock import patch
  fixtures.Relations.setUpClass();store=fixtures.Relations.s;old_store=app.STORE;old_sessions=dict(app.SESSIONS)
  app.STORE=store;app.SESSIONS.clear();server=ThreadingHTTPServer(('127.0.0.1',0),app.Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();url='http://127.0.0.1:'+str(server.server_port)
  sid='history-'+uuid.uuid4().hex
  try:
   with urllib.request.urlopen(url+'/api/meta') as response:meta=json.load(response)
   roots=[('D','EC'),('D#p1','EC')];previous=[]
   for roots_pair in roots:
    tasks=[{'id':i,'spec':canonical({'kind':'relation','population':'objects','root':{'tree':tree,'field':'code','value':code}})} for i,(tree,code) in enumerate(zip(('config','equipment_class'),roots_pair),1)]
    plan={'operation':'relational','entity':None,'scope':'direct','clarification':'','relational_tasks':tasks};trace={'engine':'relational_request','context_route':{'decision':{'needs_history':True}}};question='两个实际关系任务'
    with patch.object(app,'interpret',return_value=plan),patch.object(app,'get_trace',return_value=trace),patch('model.bind_references',side_effect=lambda store,question,intent,context:intent),patch('request_gateway.require_verified',return_value=None):
     req=urllib.request.Request(url+'/api/query',data=json.dumps({'session':sid,'question':question,'version':meta['version']}).encode(),headers={'Content-Type':'application/json','Origin':url,'X-Demo-Token':meta['token']})
     try:
      with urllib.request.urlopen(req) as response:data=json.load(response)
     except __import__('urllib.error').error.HTTPError as error:raise AssertionError(json.load(error))
    self.assertEqual(data['status'],'batch');history=data['context']['relational_history'];previous.append(history)
   self.assertEqual(len(previous[-1]),2);self.assertEqual(previous[-1][0]['state']['tasks'][0]['spec']['root']['value'],'D');self.assertEqual(previous[-1][-1]['state']['tasks'][0]['spec']['root']['value'],'D#p1');self.assertEqual(previous[-1][-1]['state']['tasks'][1]['spec']['root']['value'],'EC')
  finally:
   server.shutdown();server.server_close();thread.join();app.STORE=old_store;app.SESSIONS.clear();app.SESSIONS.update(old_sessions)

if __name__=='__main__':unittest.main()
