import copy,json,sys,unittest
from pathlib import Path
from unittest.mock import MagicMock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from data import Store
from query_plan import execute_plan,task_context
from attributes import display_value
from analytics import planner_groups
import model

class TeamFeedbackTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.s=Store()
 def detail(self,value,field='identity',target='points',filters=None):
  return dict(operation='attributes',entity=None,scope='direct',clarification='',properties=['value','unit'],query={'target':target,'filters':[{'field':field,'operator':'equals','value':value}]+(filters or [])})
 def group(self,target):
  return dict(operation='analyze',entity=None,scope='all',clarification='',query={'target':target,'filters':[]},analysis={'kind':'group_count','group_by':'level','order':'desc','limit':100,'numerator':[]})
 def test_original_partial_point_requires_selection(self):
  p=self.detail('2ABC109MT');r=execute_plan(self.s,p)
  self.assertEqual(r['status'],'ambiguous');self.assertTrue(r['candidate_only']);self.assertFalse(r['outcome']['count_computed'])
  self.assertIn('XJ2ABC001MO.TMP.2ABC109MT.BBe',[x['code'] for x in r['records']])
  self.assertTrue(all('value' not in x for x in r['records']));self.assertEqual(p['query']['filters'][0]['operator'],'equals')
 def test_exact_code_and_name_neutral(self):
  p=self.detail('MOHB01',target='config');p['properties']=['type','level'];r=execute_plan(self.s,p)
  self.assertEqual(r['status'],'ok');self.assertEqual(r['entity']['code'],'MOHB01')
 def test_explicit_name_not_swapped_to_code(self):
  p=self.detail('MOHB01',field='name',target='config');p['properties']=['name'];r=execute_plan(self.s,p)
  self.assertEqual(r['status'],'not_found')
 def test_candidate_scope_and_source_preserved(self):
  p=self.detail('2ABC109MT',filters=[{'field':'source','operator':'equals','value':'不存在的源'}]);r=execute_plan(self.s,p)
  self.assertEqual(r['status'],'not_found')
  p=self.detail('2ABC109MT');p['entity']={'tree':'pbs','code':'XJ3ABC002RR'};r=execute_plan(self.s,p)
  self.assertEqual(r['status'],'not_found')
 def test_no_candidate_for_short_or_illegal_or_missing(self):
  for value in ['2','%__',"' OR 1=1 --",'NO-SUCH-IDENTIFIER']:
   self.assertEqual(execute_plan(self.s,self.detail(value))['status'],'not_found')
 def test_statistics_do_not_fuzz(self):
  p=self.detail('2ABC109MT');p.pop('properties');p['operation']='search';r=execute_plan(self.s,p)
  self.assertEqual(r['status'],'ok');self.assertEqual(r['records'],[]);self.assertNotIn('candidate_only',r)
 def test_original_pbs_groups_and_all_tree_levels(self):
  from attributes import CATALOG
  for target in ['pbs','config','equipment_class','part_class']:
   r=execute_plan(self.s,self.group(target));field=CATALOG['level']['fields'][target]
   expected={}
   for row in self.s.rows('SELECT raw FROM objects WHERE tree=?',(target,)):
    key=json.loads(row['raw']).get(field) or '—';expected[key]=expected.get(key,0)+1
   self.assertEqual({x['cells'][1]:x['cells'][2] for x in r['records']},expected)
   self.assertEqual(sum(x['cells'][2] for x in r['records']),r['metrics'][0]['value'])
 def test_group_empty_and_top_n(self):
  p=self.group('pbs');p['query']['filters']=[{'field':'code','operator':'equals','value':'NO-SUCH'}]
  self.assertEqual(execute_plan(self.s,p)['records'],[])
  p=self.group('pbs');full=execute_plan(self.s,p);p['analysis']['limit']=1
  self.assertEqual(execute_plan(self.s,p)['records'],full['records'][:1])
 def test_unsupported_group_rejected(self):
  with self.assertRaises(model.ModelUnavailable):execute_plan(self.s,self.group('points'))
 def test_decimal_display_not_float(self):
  for raw,want in [('-4.05E-10','-0.000000000405'),('1.234567890123456789E18','1234567890123456789'),('0E-3','0.000'),('1E3','1000')]:
   self.assertEqual(display_value('rate',raw),want)
  for raw in ['1E999999','NaN','badE10','',None]:self.assertEqual(display_value('rate',raw),raw)
  self.assertEqual(display_value('code','1E3'),'1E3')
 def test_numeric_evidence_unchanged(self):
  p=self.detail('XJ1ABC1PO.JVD.1ABC029MV.LBe_Y');p['properties']=['rate']
  # 从数据独立定位原始变化速率样本，不依赖截图文字。
  row=self.s.rows("SELECT code FROM points WHERE json_extract(raw,'$.变化速率')='-4.05E-10' LIMIT 1")
  self.assertTrue(row);p['query']['filters'][0]['value']=row[0]['code'];r=execute_plan(self.s,p)
  f=next(f for f in r['attributes'] if f['value']=='-4.05E-10')
  self.assertEqual(f['display_value'],'-0.000000000405');self.assertEqual(f['evidence'][0]['fields']['变化速率'],f['value'])
 def test_clarification_context_is_pending(self):
  p=dict(operation='clarify',entity=None,scope='direct',clarification='请说明对象树')
  c=task_context(p,execute_plan(self.s,p));self.assertEqual(c['pending_request'],p);self.assertNotIn('entity',c)
 def test_router_receives_pending_and_independent_question_drops_it(self):
  p=dict(operation='clarify',entity=None,scope='direct',clarification='请说明对象树')
  route=MagicMock();route.__enter__.return_value.read.return_value=json.dumps({'choices':[{'message':{'content':json.dumps({'unit':{'state':'none','value':''},'reference':None,'projection':'specified','scope':None,'needs_history':False,'identifier_field':None})}}]}).encode()
  answer=MagicMock();answer.__enter__.return_value.read.return_value=json.dumps({'choices':[{'finish_reason':'stop','message':{'content':json.dumps(p)}}]}).encode()
  ctx={'pending_question':'介绍某对象','clarification':'请说明对象树'}
  with patch.dict(model.os.environ,{'DEEPSEEK_API_KEY':'test-only','ICCM_REQUEST_ENGINE':'legacy'}),patch.object(model.urllib.request,'build_opener') as f:
   f.return_value.open.side_effect=[route,answer];model.interpret('新的独立问题',ctx,None)
   first=json.loads(f.return_value.open.call_args_list[0].args[0].data)
   self.assertEqual(json.loads(first['messages'][1]['content'])['context'],ctx)
   final=json.loads(f.return_value.open.call_args_list[1].args[0].data)
   self.assertIn('"context": {}',final['messages'][1]['content'])

 def test_route_contract_repairs_unqualified_detail_and_preserves_explicit_name(self):
  for field in ['identity','name']:
   p=dict(operation='attributes',entity={'tree':'config','name':'MOHB01'},scope='direct',clarification='',properties=['type'])
   route=MagicMock();route.__enter__.return_value.read.return_value=json.dumps({'choices':[{'message':{'content':json.dumps({'unit':{'state':'none','value':''},'reference':None,'projection':'specified','scope':None,'needs_history':False,'identifier_field':field,'resolved_question':None})}}]}).encode()
   answer=MagicMock();answer.__enter__.return_value.read.return_value=json.dumps({'choices':[{'finish_reason':'stop','message':{'content':json.dumps(p)}}]}).encode()
   with patch.dict(model.os.environ,{'DEEPSEEK_API_KEY':'test-only','ICCM_REQUEST_ENGINE':'legacy'}),patch.object(model.urllib.request,'build_opener') as f:
    f.return_value.open.side_effect=[route,answer];resolved=model.interpret('synthetic',{},None)
   self.assertEqual(resolved['query']['filters'][0]['field'],field)
   self.assertEqual(execute_plan(self.s,resolved)['status'],'ok' if field=='identity' else 'not_found')

 def test_pending_question_semantically_completed_before_planner(self):
  p=dict(operation='clarify',entity=None,scope='direct',clarification='synthetic')
  route=MagicMock();route.__enter__.return_value.read.return_value=json.dumps({'choices':[{'message':{'content':json.dumps({'unit':{'state':'none','value':''},'reference':None,'projection':'specified','scope':None,'needs_history':True,'identifier_field':'identity','resolved_question':'介绍PBS中的XXXX1'})}}]}).encode()
  answer=MagicMock();answer.__enter__.return_value.read.return_value=json.dumps({'choices':[{'finish_reason':'stop','message':{'content':json.dumps(p)}}]}).encode()
  with patch.dict(model.os.environ,{'DEEPSEEK_API_KEY':'test-only','ICCM_REQUEST_ENGINE':'legacy'}),patch.object(model.urllib.request,'build_opener') as f:
   f.return_value.open.side_effect=[route,answer];model.interpret('PBS',{'pending_question':'介绍XXXX1'},None)
   body=json.loads(f.return_value.open.call_args_list[1].args[0].data)
  self.assertIn('当前待执行请求："介绍PBS中的XXXX1"',body['messages'][1]['content'])

if __name__=='__main__':unittest.main()
