"""独立原始CSV父链核对Agent范围/说明/候选契约。"""
import copy,csv,unittest
from pathlib import Path
from unittest.mock import patch as mocked
from tools import DataTools
from test_request_protocol import patch,condition,goal

class ParentRanges(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.data=DataTools();d=Path(__file__).resolve().parents[2]/'中广核iCCM项目智能问数DEMO脱敏数据'
  with (d/'pbs.csv').open(encoding='gb18030') as f:cls.pbs=list(csv.DictReader(f))
  with (d/'测量点数据分析.csv').open(encoding='gb18030') as f:cls.points=list(csv.DictReader(f))
  cls.code='XJ2ABC002MO&MOHB01';cls.name=next(r['对象描述中文'] for r in cls.pbs if r['对象代码']==cls.code)
 def scope(self,code):
  children={}
  for r in self.pbs:children.setdefault(r['父对象代码'],[]).append(r['对象代码'])
  nodes={code};todo=[code]
  while todo:
   for n in children.get(todo.pop(),[]):
    if n not in nodes:nodes.add(n);todo.append(n)
  return [r for r in self.points if r['测量点编码'] in nodes]
 def execute(self,sid,q,p,mode='new'):
  self.data.begin_turn(sid,q);return self.data.call(sid,'iccm_request',{'request':{'mode':mode,'tasks':[p]}})
 def root(self,q,field='code',value=None):return {'tree':'pbs','field':field,'value':value or self.code,'quote':q}
 def test_code_range_counts_actual_parent_chain(self):
  q='PBS对象'+self.code+'范围内测点数量';p=patch(q,'count');p['parent_range']=self.root(q)
  r=self.execute('root-code',q,p);self.assertEqual(r['record_total'],len(self.scope(self.code)));self.assertEqual(r['entity']['code'],self.code)
  self.assertFalse(r['query']['filters']);self.assertEqual(r['request_state']['task_directory'][0]['parent_range']['entity']['code'],self.code)
 def test_name_resolves_same_root_not_point_name_filter(self):
  q='PBS对象名称'+self.name+'下面测点数量';p=patch(q,'count');p['parent_range']=self.root(q,'name',self.name)
  r=self.execute('root-name',q,p);self.assertEqual(r['record_total'],len(self.scope(self.code)));self.assertEqual(r['entity']['code'],self.code);self.assertEqual(r['query']['filters'],[])
 def test_source_and_status_keep_root(self):
  q='PBS对象'+self.code+'范围内源系统1且已报警测点数量';p=patch(q,'count',filters=[condition('source','equals','源系统1'),condition('status','equals','已报警')]);p['parent_range']=self.root(q)
  r=self.execute('root-filters',q,p);wanted=[x for x in self.scope(self.code) if x['源系统']=='源系统1' and x['状态']=='已报警'];self.assertEqual(r['record_total'],len(wanted));self.assertEqual(r['entity']['code'],self.code)
 def test_continuation_adds_condition_and_retains_root(self):
  q='PBS对象'+self.code+'范围内测点数量';p=patch(q,'count');p['parent_range']=self.root(q);self.execute('root-continue',q,p)
  q='只查源系统1，其他不变';p={'base':'t1','quote':q,'subject':None,'execute':True,'parent_range':'inherit','set':{},'filters':[{'action':'add','ids':[],'conditions':[condition('source','equals','源系统1')],'quote':q}]}
  r=self.execute('root-continue',q,p,'update');self.assertEqual(r['record_total'],sum(x['源系统']=='源系统1' for x in self.scope(self.code)));self.assertEqual(r['entity']['code'],self.code)
 def test_explicit_new_global_does_not_inherit_root(self):
  q='PBS对象'+self.code+'范围内测点数量';p=patch(q,'count');p['parent_range']=self.root(q);self.execute('root-new',q,p)
  q='新问题：统计全部测点记录';p=patch(q,'count');p['parent_range']='all_imported';r=self.execute('root-new',q,p);self.assertEqual(r['record_total'],len(self.points));self.assertIsNone(r.get('entity'))
 def test_invalid_root_source_does_not_create_confirmed_task(self):
  q='统计全部测点';p=patch(q,'count');p['parent_range']=self.root(q)
  with self.assertRaisesRegex(ValueError,'原话|依据'):self.execute('root-forged',q,p)
  self.assertNotIn('business_request',self.data.contexts.get('root-forged',{}))
 def test_root_domain_not_inferred_from_data_hit(self):
  q='对象'+self.code+'范围内测点数量';p=patch(q,'count');p['parent_range']=self.root(q)
  with self.assertRaisesRegex(ValueError,'明确属于PBS'):self.execute('root-unscoped',q,p)
 def test_missing_root_is_not_global_query_or_zero_count(self):
  q='PBS对象NOT_EXISTENT_987654范围内测点数量';p=patch(q,'count');p['parent_range']=self.root(q,'code','NOT_EXISTENT_987654')
  with mocked.object(self.data.store,'filtered',side_effect=AssertionError('不能查全表')):r=self.execute('root-missing',q,p)
  self.assertEqual(r['status'],'clarify');self.assertFalse(r.get('goal_receipt',{}).get('completed'));self.assertNotIn('business_request',self.data.contexts['root-missing'])
 def test_parent_cannot_be_supplied_as_point_subject(self):
  q='PBS对象'+self.name+'下面测点数量';p=patch(q,'count');p['subject']={'field':'name','value':self.name}
  with self.assertRaisesRegex(ValueError,'parent_range'):self.execute('root-subject',q,p)
 def test_domain_clarification_returns_real_candidates_and_keeps_draft(self):
  q='介绍MOHB';p=patch(q,operation='attributes',target='objects',properties=['name','code'],result_goal=goal('attributes'));p.update(subject={'field':'code','value':'MOHB'},purpose='introduction',subject_scope='unspecified')
  r=self.execute('root-domain',q,p);self.assertEqual(r['status'],'ambiguous');self.assertEqual({(x['tree'],x['code']) for x in r['records']},{('config','MOHB'),('equipment_class','MOHB')});self.assertTrue(all(x['evidence'] for x in r['records']));self.assertEqual(self.data.contexts['root-domain']['pending_business_request']['pending_reason'],'domain');self.assertFalse(r.get('goal_receipt',{}).get('completed'))
  q='PBS';p={'base':'t1','quote':q,'set':{'target':'pbs'},'filters':[],'subject':None,'execute':True,'purpose':'introduction','subject_scope':'explicit','parent_range':'inherit'};r=self.execute('root-domain',q,p,'update');self.assertEqual(r['status'],'ambiguous');self.assertEqual(r['record_total'],8029)
 def test_neutral_note_metadata_does_not_block_capability_receipt(self):
  q='说明当前预测能力边界';p=patch(q);p['set']={'operation':'unsupported','topics':['limits']};p['unit']={'state':'none','value':''};p['parent_range']='all_imported'
  with mocked.object(self.data.store,'filtered',side_effect=AssertionError('说明不能查数据')):r=self.execute('root-note',q,p)
  self.assertEqual(r['status'],'conversation');self.assertIn('预测',r['answer'])
 def test_explicit_clarification_candidates_preserve_empty_subject_and_pending_domain(self):
  q='介绍MOHB';p=patch(q,operation='attributes',target='objects',properties=['name','code'],result_goal=goal('attributes'))
  p.update(subject={'field':'code','value':'MOHB'},purpose='introduction',subject_scope='unspecified',execute=False)
  self.data.begin_turn('explicit-domain',q)
  with mocked.object(self.data.store,'filtered',side_effect=AssertionError('澄清不能执行属性查询')):
   r=self.data.call('explicit-domain','iccm_clarify',{'question':'请选择构型或设备类对象','request':{'mode':'new','tasks':[p]}})
  self.assertEqual(r['status'],'ambiguous');self.assertIsNone(r['entity']);self.assertEqual(r['scope'],'direct')
  self.assertEqual({(x['tree'],x['code']) for x in r['records']},{('config','MOHB'),('equipment_class','MOHB')})
  self.assertFalse(r['request_executed']);self.assertFalse(r.get('goal_receipt',{}).get('completed'))
  self.assertEqual(self.data.contexts['explicit-domain']['pending_business_request']['pending_reason'],'domain')
  p={'base':'t1','quote':'构型','set':{'target':'config'},'filters':[],'subject':None,'execute':True,'purpose':'introduction','subject_scope':'explicit','parent_range':'inherit'}
  r=self.execute('explicit-domain','构型',p,'update');self.assertEqual(r['status'],'ok')
  self.assertEqual(r['entity']['tree'],'config');self.assertEqual(r['entity']['code'],'MOHB')
 def test_note_actual_unit_not_silently_discarded(self):
  q='摄氏度预测';p=patch(q);p['set']={'operation':'unsupported','topics':['limits']};p['unit']={'state':'specified','value':'℃'}
  with self.assertRaisesRegex(ValueError,'说明任务'):self.execute('root-note-unit',q,p)
 def test_topics_cannot_carry_search_question(self):
  q='按层级分组计数';p=patch(q,'count');p['set']['topics']=[q]
  with self.assertRaisesRegex(ValueError,r'set\.topics\[0\]'):self.execute('root-topics',q,p)
 def test_time_sort_stays_inside_root(self):
  from datetime import datetime
  q='PBS对象'+self.code+'范围内按时间从晚到早取前3条';p=patch(q,result_goal=goal('sort',field='time',direction='desc',limit=3));p['parent_range']=self.root(q)
  r=self.execute('root-sort',q,p);wanted=sorted(self.scope(self.code),key=lambda x:x['测量点编码']);wanted.sort(key=lambda x:datetime.strptime(x['测量时间'],'%Y/%m/%d %H:%M') if x['测量时间'] else datetime.min,reverse=True)
  self.assertEqual([(x['code'],x['time']) for x in r['records']],[(x['测量点编码'],x['测量时间']) for x in wanted[:3]])


class RangePresentation(unittest.TestCase):
 def test_declared_root_is_not_shown_as_global_before_execution(self):
  from presentation import tool_view
  q='PBS对象ROOT_SAMPLE范围内测点数量';p=patch(q,'count');p['parent_range']={'tree':'pbs','field':'code','value':'ROOT_SAMPLE','quote':q}
  text=str(tool_view('iccm_request',{'request':{'mode':'new','tasks':[p]}}))
  self.assertIn('ROOT_SAMPLE',text);self.assertIn('待核验',text);self.assertNotIn('未限定父对象范围',text)
 def test_inherited_range_is_not_presented_as_new_global_scope(self):
  from presentation import tool_view
  p=patch('原范围不变','count');p['parent_range']='inherit'
  text=str(tool_view('iccm_request',{'request':{'mode':'update','tasks':[p]}}));self.assertIn('沿用原任务范围',text);self.assertNotIn('未限定父对象范围',text)
 def test_server_and_browser_use_same_verified_default_model(self):
  import threading
  from types import SimpleNamespace
  from server import Demo,MODELS
  from unittest.mock import Mock
  self.assertEqual(MODELS[0],'gpt-6-sol')
  d=Demo.__new__(Demo);d.lock=threading.RLock();d.sessions={};d.creating=0;d.model=None
  call=Mock(return_value={'model':'gpt-6-sol','thread':{'id':'offline-default'}});d.runtime=SimpleNamespace(new_thread=call)
  r=d.create();self.assertEqual(r['model'],'gpt-6-sol');self.assertEqual(call.call_args.kwargs['model'],'gpt-6-sol');self.assertEqual(call.call_args.kwargs['effort'],'low')
  html=(Path(__file__).resolve().parent/'web/index.html').read_text();self.assertIn('<option value="gpt-6-sol" selected>',html)
