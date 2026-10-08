import copy,json,sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import model
from data import Store
from query_plan import execute_plan
from test_query_plan import one,batch
from test_statistics_review import response,intent
import test_filters

class ContractTests(unittest.TestCase):
 def setUp(self):
  model.TRACE.value={}
  self.p=batch(one('parts',{'tree':'config','code':'MOHB01'}),one('alarms'))
 def test_empty_slots_are_semantically_neutral(self):
  p={**self.p,**dict.fromkeys(['analysis','query','properties','message'])}
  self.assertEqual(model.prepare_plan(p),self.p)
  self.assertIn('analysis',p) # 调用者提供的依据不可修改。
 def test_global_constraints_never_dropped(self):
  for field,value in [('analysis',{}),('query',{'target':'points','filters':[]}),('properties',[]),('extra',None),('entity',{'tree':'pbs','code':'x'}),('scope','all')]:
   with self.subTest(field=field),self.assertRaises(model.PlanInvalid):model.prepare_plan({**self.p,field:value})
 def test_bad_child_keeps_other_task_and_trace(self):
  self.p['tasks'][0]['intent']['operation']='unsupported'
  parsed=model.prepare_plan(self.p);r=execute_plan(Store(),parsed)
  self.assertEqual([x['status'] for x in r['items']],['clarify','ok'])
  self.assertEqual(len(r['items'][1]['records']),48)
  self.assertEqual(model.get_trace()['task_errors'][0]['task_number'],1)
  self.assertEqual(self.p['tasks'][0]['intent']['operation'],'unsupported')
 def test_incomplete_envelope_rejected(self):
  for tasks in [[],self.p['tasks'][:1],self.p['tasks']*3,[{'question':'x','intent':self.p},self.p['tasks'][1]],[{'intent':one('alarms')},self.p['tasks'][1]]]:
   with self.subTest(tasks=tasks),self.assertRaises(model.PlanInvalid):model.prepare_plan({**self.p,'tasks':tasks})
 def test_four_and_duplicate_tasks_retained(self):
  p={**self.p,'tasks':self.p['tasks']*2}
  self.assertEqual(len(model.prepare_plan(p)['tasks']),4)
 def test_review_ids_cannot_drop_duplicate_or_invent(self):
  for ids in [[1],[1,1],[1,3],[True,2]]:
   with self.assertRaises(model.PlanInvalid):model.merge_review(self.p,{'tasks':[{'task_number':n,'intent':one('alarms')} for n in ids]})
 def test_review_ids_allow_reordered_response_preserve_questions(self):
  r=model.merge_review(self.p,{'tasks':[{'task_number':2,'intent':one('alarms')},{'task_number':1,'intent':one('duration')}]})
  self.assertEqual([t['question'] for t in r['tasks']],[t['question'] for t in self.p['tasks']])
  self.assertEqual([t['intent']['operation'] for t in r['tasks']],['duration','alarms'])
 def test_child_schema_shares_operation_and_property_catalog(self):
  s=json.loads(model.SCHEMA.read_text(encoding='utf-8'));child=s['properties']['tasks']['items']['properties']['intent']
  self.assertEqual(set(child['properties']['operation']['enum']),set(s['properties']['operation']['enum'])-{'batch'})
  self.assertIn('properties',child['properties'])
 def test_mixed_attributes_and_unsupported_statistics(self):
  a={**one('attributes',{'tree':'config','code':'MOHB01'}),'properties':['type']}
  b=intent();b['analysis']['group_by']='location'
  r=execute_plan(Store(),model.prepare_plan(batch(a,b)))
  self.assertEqual([x['status'] for x in r['items']],['ok','clarify'])
 def test_review_corrects_filter_before_execution(self):
  bad=intent('group_count',5);bad['query']['filters']=[dict(field='switch',operator='equals',value='开启')]
  good=copy.deepcopy(bad);good['query']['filters'].append(dict(field='status',operator='equals',value='已报警'))
  with patch.dict(model.os.environ,{'DEEPSEEK_API_KEY':'test-only','ICCM_REQUEST_ENGINE':'legacy'}),patch.object(model.urllib.request,'build_opener') as net:
   net.return_value.open.side_effect=[response({'unit':{'state':'none','value':''},'reference':None,'projection':'specified','scope':None,'needs_history':False,'identifier_field':None}),response(bad),response(good)]
   self.assertEqual(model.interpret('对符合两个条件的记录分组',{},None),good)

class DiagnosticsHttpTests(test_filters.FilterHttpTests):
 def test_plan_error_has_opt_in_trace_and_distinct_status(self):
  import app,urllib.error
  model.TRACE.value={'stage':'plan_validation'}
  with patch.object(app,'interpret',side_effect=model.PlanInvalid('未执行')),patch.object(app,'get_trace',return_value={'stage':'plan_validation'}):
   for trace in [True,False]:
    with self.assertRaises(urllib.error.HTTPError) as caught:self.request('/api/query',{'session':'bad-plan','question':'test','trace':trace})
    self.assertEqual(caught.exception.code,422)
    body=json.load(caught.exception);self.assertEqual(body['error_code'],'plan_invalid')
    self.assertEqual('trace' in body,trace);self.assertFalse(body['model_unavailable'])
 def test_partial_plan_pages_and_context(self):
  import app
  p=batch(one('alarms'),one('not-supported'));parsed=model.prepare_plan(p)
  with patch.object(app,'interpret',return_value=parsed):
   r=self.request('/api/query',{'session':'partial-plan','question':'test'})
  self.assertEqual(r['status'],'batch')
  self.assertEqual([x['status'] for x in r['items']],['ok','clarify'])
  self.assertEqual(r['context']['branches'][1]['status'],'clarify')
  page=self.request('/api/page',{'session':'partial-plan','result':r['items'][0]['result'],'page':2})
  self.assertEqual(len(page['records']),8)

if __name__=='__main__':unittest.main()
