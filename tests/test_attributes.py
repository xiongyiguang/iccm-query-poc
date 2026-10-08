import sys,unittest,copy
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from data import Store,QueryError
from model import validate,ModelUnavailable
from attributes import check_coverage
from query_plan import task_context,execute_plan

class AttributeTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.store=Store()
 def intent(self,props=None,target='pbs',value='XXXX2834',field='name'):
  return dict(operation='attributes',entity=None,scope='direct',clarification='',properties=props or ['type'],query={'target':target,'filters':[{'field':field,'operator':'equals','value':value}]})
 def run_intent(self,i):return self.store.execute(validate(i))
 def test_original_type_and_followup(self):
  r=self.run_intent(self.intent());self.assertIn('对象类型：时序测点',r['answer']);self.assertEqual(r['records'],[])
  c=task_context(self.intent(),r);self.assertEqual(c['requested_properties'],['type']);self.assertEqual(c['answered_properties'],['type'])
  i=self.intent();i.pop('query');i['entity']=c['entity'];self.assertEqual(self.run_intent(i)['attributes'][0]['value'],'时序测点')
 def test_same_subject_different_properties(self):
  for prop,expected in [('name','XXXX2834'),('code','XJ2ABC002MO.MDI.2ABC002MM.Axi_X'),('type','时序测点'),('parent','XJ2ABC002MO')]:
   with self.subTest(prop=prop):self.assertEqual(self.run_intent(self.intent([prop]))['attributes'][0]['value'],expected)
 def test_point_name_and_pbs_type(self):
  r=self.run_intent(self.intent(['name','type'],'points','测量点名称5'))
  self.assertEqual([x['value'] for x in r['attributes']],['测量点名称5','时序测点'])
  self.assertEqual({e['file'] for e in r['evidence']},{'pbs.csv','测量点数据分析.csv'})
 def test_other_tree_numeric_level_not_type(self):
  r=self.run_intent(self.intent(['type','level'],'config','MOHB01','code'))
  self.assertEqual([x['value'] for x in r['attributes']],['设备','4'])
  r=self.run_intent(self.intent(['type','level'],'equipment_class','MOHB','code'))
  self.assertEqual(r['attributes'][0]['status'],'unsupported');self.assertEqual(r['attributes'][1]['status'],'known')
 def test_no_physical_quantity_guess(self):
  r=self.run_intent(self.intent(['physical_quantity','type']));self.assertIn('无法可靠确定',r['answer']);self.assertTrue(r['coverage']['complete'])
 def test_missing_value_not_zero(self):
  r=self.run_intent(self.intent(['prediction'],'points','测量点名称5'));self.assertEqual(r['attributes'][0]['status'],'missing');self.assertIn('未提供',r['answer'])
 def test_multiple_sources_and_scope(self):
  i=self.intent(['value','source'],'points','XJ2ABC001PO.MFB.2ABC029MV.LBe_Y','code');r=self.run_intent(i)
  self.assertEqual({x['value'] for x in r['attributes'] if x['property']=='value'},{'6','0'})
  i['query']['filters'].append({'field':'source','operator':'equals','value':'源系统3'})
  r=self.run_intent(i);self.assertEqual([x['value'] for x in r['attributes'] if x['property']=='value'],['6'])
  self.assertIn({'field':'source','operator':'equals','value':'源系统3'},task_context(i,r)['lookup_query']['filters'])
 def test_ambiguous_and_missing_not_first(self):
  i=self.intent();i['query']['filters'][0]['operator']='contains';i['query']['filters'][0]['value']='XXXX28'
  r=self.run_intent(i);self.assertEqual(r['status'],'clarify');self.assertIsNone(r['entity'])
  r=self.run_intent(self.intent(value='NOT-EXIST'));self.assertEqual(r['status'],'clarify')
 def test_invalid_and_dropped_properties(self):
  for props in [[],['type','type'],['sql'],None]:
   i=self.intent();i['properties']=props
   with self.assertRaises(ModelUnavailable):validate(i)
  i=self.intent();i['operation']='object'
  with self.assertRaises(ModelUnavailable):validate(i)
  with self.assertRaises(QueryError):self.store.execute(i)
 def test_evidence_and_coverage_guard(self):
  r=self.run_intent(self.intent());f=copy.deepcopy(r['attributes']);f[0]['value']='设备'
  with self.assertRaises(ValueError):check_coverage(['type'],f)
  with self.assertRaises(ValueError):check_coverage(['name','type'],r['attributes'])
 def test_batch_preserves_requested_properties(self):
  i={'operation':'batch','entity':None,'scope':'direct','clarification':'','tasks':[{'question':'类型','intent':self.intent()},{'question':'名字','intent':self.intent(['name'])}]}
  r=execute_plan(self.store,i);self.assertEqual(r['items'][0]['task_context']['requested_properties'],['type'])
 def test_unmatched_point_type_does_not_invent_pbs(self):
  row=self.store.rows("SELECT p.code FROM points p LEFT JOIN objects o ON o.tree='pbs' AND o.code=p.code WHERE o.code IS NULL LIMIT 1")[0]
  r=self.run_intent(self.intent(['type'],'points',row['code'],'code'));self.assertEqual(r['attributes'][0]['status'],'missing')

from test_filters import FilterHttpTests
from unittest.mock import patch

class AttributeHttpTests(FilterHttpTests):
 def test_attribute_context_and_correction(self):
  initial=dict(operation='attributes',entity=None,scope='direct',clarification='',properties=['name'],query={'target':'pbs','filters':[{'field':'name','operator':'equals','value':'XXXX2834'}]})
  first=self.request('/api/query',{'session':'attribute-http','intent':initial})
  def understand(question,context,selection):
   self.assertEqual(context['requested_properties'],['name'])
   self.assertEqual(context['answered_properties'],['name'])
   return dict(operation='attributes',entity=context['entity'],scope='direct',clarification='',properties=['type'])
  # 此 HTTP 测试只隔离核对上下文传播，两处语义依赖均被模拟；
  # 执行入口完整性另有阻断未经核验执行的集成测试。
  with patch.object(self.app,'interpret',understand),patch('request_checklist.gate',return_value={'decision':'accept','choice':'candidate'}):
   r=self.request('/api/query',{'session':'attribute-http','question':'不是名字，是类型'})
  self.assertEqual(r['context']['requested_properties'],['type'])
  self.assertIn('对象类型：时序测点',r['answer'])
  self.assertEqual(r['total'],0);self.assertTrue(r['coverage']['complete'])
  self.assertTrue(r['evidence']);self.assertNotIn('trace',r)
 def test_insufficient_property_retains_entity(self):
  i=dict(operation='attributes',entity={'tree':'pbs','code':'XJ2ABC002MO.MDI.2ABC002MM.Axi_X'},scope='direct',clarification='',properties=['physical_quantity'])
  r=self.request('/api/query',{'session':'insufficient-attribute','intent':i})
  self.assertEqual(r['context']['entity'],i['entity'])
  self.assertEqual(r['attributes'][0]['status'],'unsupported')
  self.request('/api/context',{'session':'insufficient-attribute'})
  self.assertEqual(self.app.SESSIONS['insufficient-attribute']['context'],{})

if __name__=='__main__':unittest.main()
