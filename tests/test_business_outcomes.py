import sys,unittest,copy,json,urllib.error
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from data import Store
from query_plan import execute_plan
import test_filters
class BusinessOutcomeTests(test_filters.FilterHttpTests):
 def plan(self):return dict(operation='analyze',entity={'tree':'pbs','code':'XJ3ABC002RR'},scope='all',clarification='',query={'target':'parts','filters':[],'equipment_class':{'field':'name','operator':'equals','value':'不存在的类别999'}},analysis={'kind':'group_count','group_by':'class_code','order':'desc','limit':100,'numerator':[]})
 def test_missing_class_http_normal_feedback(self):
  r=self.request('/api/query',{'session':'missing-class','intent':self.plan()});self.assertEqual(r['status'],'not_found');self.assertEqual(r['metrics'],[]);self.assertFalse(r['outcome']['count_computed']);self.assertIn('pending_request',r['context'])
 def test_missing_new_subject_clears_old_focus(self):
  self.request('/api/query',{'session':'stale','intent':dict(operation='parts',entity={'tree':'config','code':'MOHB01'},scope='direct')})
  r=self.request('/api/query',{'session':'stale','intent':self.plan()});self.assertNotIn('entity',r['context']);self.assertNotIn('query',r['context'])
 def test_successful_correction_clears_pending(self):
  p=self.plan();self.request('/api/query',{'session':'correction','intent':p});p['query']['equipment_class']['value']='设备类描述3727';r=self.request('/api/query',{'session':'correction','intent':p});self.assertEqual(r['classification_coverage']['verified_class_count'],23);self.assertNotIn('pending_request',r['context'])
 def test_normal_zero_is_ok(self):
  p=self.plan();p['query']['equipment_class']['value']='设备类描述3727';p['entity']['code']='XJ2ABC001MO';r=self.request('/api/query',{'session':'zero-ok','intent':p});self.assertEqual(r['status'],'ok');self.assertEqual(r['metrics'][0]['value'],0);self.assertNotIn('outcome',r)
 def test_missing_name_and_code(self):
  for ref in [{'tree':'config','name':'不存在的构型'},{'tree':'config','code':'NO-SUCH'}]:
   r=self.request('/api/query',{'session':'missing-object','intent':dict(operation='parts',entity=ref,scope='all')});self.assertEqual(r['status'],'not_found');self.assertEqual(r['metrics'],[])
 def test_detail_missing_resets_context(self):
  p=dict(operation='attributes',entity=None,scope='direct',properties=['name'],query={'target':'config','filters':[{'field':'name','operator':'equals','value':'不存在的构型'}]})
  r=self.request('/api/query',{'session':'missing-detail','intent':p});self.assertEqual(r['status'],'not_found');self.assertIn('pending_request',r['context'])
 def test_duplicate_and_incomplete_typed(self):
  s=Store();ds=copy.deepcopy(s.dataset)
  for packet in ds:
   if packet['kind']=='config':
    row=next(x for x in packet['rows'] if x['对象代码']=='MOHB01').copy();row['对象代码']='DUP';packet['rows'].append(row)
  p=dict(operation='parts',entity={'tree':'config','name':row['对象描述中文']},scope='all',clarification='')
  r=execute_plan(Store(dataset=ds),p);self.assertEqual(r['status'],'ambiguous');self.assertEqual(len(r['outcome']['candidates']),2)
  for packet in ds:
   if packet['kind']=='config':packet['rows']=[x for x in packet['rows'] if x['对象代码']!='RRGA02#1']
  p=self.plan();p['query']['equipment_class']['value']='设备类描述3727';r=execute_plan(Store(dataset=ds),p);self.assertEqual(r['status'],'incomplete');self.assertEqual(r['metrics'],[])
 def test_true_model_failure_not_business_result(self):
  from model import ModelUnavailable
  with patch.object(self.app,'interpret',side_effect=ModelUnavailable('network unavailable')):
   with self.assertRaises(urllib.error.HTTPError) as c:self.request('/api/query',{'session':'outage','question':'test'})
  self.assertEqual(c.exception.code,503)
