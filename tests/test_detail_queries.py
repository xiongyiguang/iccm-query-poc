import unittest,sys,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from data import Store,QueryError
from model import validate,ModelUnavailable
from query_plan import execute_plan

class Details(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.s=Store()
 def intent(self,op='threshold',field='name',value='测量点名称11',target='points',operator='equals',entity=None):
  return dict(operation=op,entity=entity,scope='direct',clarification='',query=dict(target=target,filters=[dict(field=field,operator=operator,value=value)]))
 def test_original_name_to_threshold(self):
  r=self.s.execute(validate(self.intent()))
  self.assertEqual(r['entity']['code'],'XJ2ABC001MO.TMP.2ABC109MT.BBe')
  self.assertEqual({m['label']:m['value'] for m in r['metrics']},{'真实值报警阈值-低2':'20','真实值报警阈值-低1':'30','真实值报警阈值-高1':'34','真实值报警阈值-高2':'80','真实值报警阈值-高3':'90'})
  self.assertEqual(r['records'][0]['difference'],'6.69898987')
  self.assertNotIn('query',r)
  self.assertEqual(r['records'][0]['high1'],'34')
  self.assertEqual(len(r['threshold_details'][0]['thresholds']),18)
 def test_duration_missing_timestamps_before_object_selection(self):
  queries=[{'target':'points','filters':[]},self.intent()['query'],
   self.intent(value='NOT-EXIST')['query'],self.intent(value='测量点名称1',operator='starts_with')['query'],
   {'target':'points','filters':[{'field':'status','operator':'equals','value':'已报警'}]}]
  for query in queries:
   with self.subTest(query=query):
    r=self.s.execute(dict(operation='duration',entity=None,scope='direct',query=query))
    self.assertEqual(r['status'],'data_insufficient')
    self.assertEqual(r['records'],[]);self.assertEqual(r['metrics'],[])
    self.assertEqual(r['lookup_query'],query)
    self.assertIn('缺少报警开始时间和恢复时间',r['answer'])
    self.assertNotIn('请选择',r['answer']);self.assertIsNone(r['entity'])
 def test_duration_preserves_subject_and_rejects_invalid_query(self):
  subject={'tree':'pbs','code':'XJ2ABC001MO.TMP.2ABC109MT.BBe'}
  r=self.s.execute(dict(operation='duration',entity=subject,scope='direct'))
  self.assertEqual(r['entity'],subject);self.assertEqual(r['status'],'data_insufficient')
  for query in [self.intent(field='SQL')['query'],self.intent(target='config')['query']]:
   with self.assertRaises(QueryError):self.s.execute(dict(operation='duration',entity=None,query=query))
 def test_conditions_not_dropped(self):
  i=self.intent();i['query']['filters'].append(dict(field='switch',operator='equals',value='关闭'))
  r=self.s.execute(validate(i));self.assertEqual(r['status'],'clarify');self.assertEqual(r['records'],[])
 def test_ambiguous_not_first(self):
  r=self.s.execute(validate(self.intent(value='测量点名称1',operator='starts_with')))
  self.assertEqual(r['status'],'clarify');self.assertGreater(len({x['code'] for x in r['records']}),1)
  self.assertIsNone(r['entity'])
 def test_multisource_retained(self):
  r=self.s.execute(validate(self.intent(field='code',value='XJ2ABC001PO.ZRs.2ABC003KA.UGb')))
  self.assertEqual(len(r['records']),4);self.assertEqual(len(r['threshold_details']),4)
  for x in r['records']:
   self.assertEqual(x['value'],x['evidence']['fields']['测量值'] or '未提供')
 def test_missing_threshold_keeps_value(self):
  rows=self.s.rows('SELECT code,raw FROM points')
  row=next(x for x in rows if json.loads(x['raw']).get('测量值') and not json.loads(x['raw']).get('真实值报警阈值-高1'))
  r=self.s.execute(validate(self.intent(field='code',value=row['code'])))
  self.assertEqual(r['status'],'ok');self.assertTrue(any(x['high1']=='未提供' and x['difference']=='无法计算' for x in r['records']))
 def test_relationship_name_resolution(self):
  r=self.s.execute(validate(self.intent(op='equipment_class',target='config',value='构型对象描述14477')))
  self.assertIn('设备类描述1860',r['answer'])
 def test_unsupported_operation_and_predicate(self):
  for i in [self.intent(op='alarms'),self.intent(field='SQL'),self.intent(op='threshold',target='config')]:
   with self.assertRaises((ModelUnavailable,QueryError)):self.s.execute(validate(i))
 def test_batch_keeps_normalization(self):
  part=dict(operation='parts',entity={'tree':'config','code':'MOHB01'},scope='direct',clarification='',query={'target':'parts','filters':[]})
  plan=dict(operation='batch',entity=None,scope='direct',clarification='',tasks=[{'question':'parts','intent':part},{'question':'threshold','intent':self.intent()}])
  r=execute_plan(self.s,plan)
  self.assertEqual([x['status'] for x in r['items']],['ok','ok']);self.assertEqual(len(r['items'][0]['records']),51)
 def test_same_subject_property_plan_coalesces(self):
  measurement=self.intent(op='measurement');threshold=self.intent()
  plan=dict(operation='batch',entity=None,scope='direct',clarification='',tasks=[{'question':'value','intent':measurement},{'question':'threshold','intent':threshold}])
  self.assertEqual(validate(plan)['operation'],'threshold')
  different=self.intent(value='测量点名称12')
  plan['tasks'][1]['intent']=different
  self.assertEqual(validate(plan)['operation'],'batch')
 def test_lookup_context_retains_record_conditions(self):
  i=self.intent();i['query']['filters'].append(dict(field='switch',operator='equals',value='开启'))
  r=self.s.execute(validate(i))
  self.assertIn(dict(field='switch',operator='equals',value='开启'),r['lookup_query']['filters'])
  self.assertIn(dict(field='code',operator='equals',value=r['entity']['code']),r['lookup_query']['filters'])
 def test_point_name_and_pbs_name_are_distinguished(self):
  r=self.s.execute(dict(operation='object',entity={'tree':'pbs','code':'XJ2ABC001MO.TMP.2ABC109MT.BBe'},scope='direct'))
  self.assertIn('测点名称：测量点名称11',r['answer']);self.assertIn('PBS对象名称：',r['answer'])

if __name__=='__main__':unittest.main()
