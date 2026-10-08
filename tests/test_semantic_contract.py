import unittest,sys,copy
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from data import Store
from query_plan import execute_plan,task_context
from model import ModelUnavailable
class SemanticContractTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.s=Store()
 def plan(self):
  return dict(operation='analyze',entity={'tree':'pbs','name':'XXXX6143'},scope='all',clarification='',query={'target':'parts','filters':[],'equipment_class':{'field':'name','operator':'equals','value':'设备类描述3727'}},analysis={'kind':'group_count','group_by':'class_code','order':'desc','limit':100,'numerator':[]})
 def test_named_scope_cross_relation(self):
  r=execute_plan(self.s,self.plan());self.assertEqual(r['classification_coverage']['verified_class_count'],23);self.assertEqual(r['query_receipt']['resolved_entity']['code'],'XJ3ABC002RR');self.assertEqual(r['query_receipt']['grain'],'pbs_object')
 def test_context_keeps_relation_and_grain(self):
  p=self.plan();r=execute_plan(self.s,p);c=task_context(p,r);self.assertEqual(c['query']['equipment_class'],p['query']['equipment_class']);self.assertEqual(c['query_receipt']['grain'],'pbs_object')
 def test_same_intent_in_batch(self):
  p=self.plan();r=execute_plan(self.s,dict(operation='batch',entity=None,scope='direct',clarification='',tasks=[{'question':'A','intent':p},{'question':'B','intent':dict(operation='parts',entity={'tree':'config','name':'构型对象描述10435'},scope='direct',clarification='')}]))
  self.assertEqual(r['items'][0]['classification_coverage']['verified_class_count'],23);self.assertEqual(r['items'][1]['metrics'][1]['value'],5749)
 def test_unknown_reference_not_verified_category(self):
  ds=copy.deepcopy(self.s.dataset)
  for pkt in ds:
   if pkt['kind']=='part_class':pkt['rows']=[r for r in pkt['rows'] if r['对象编码']!='ZZZZZ00']
  r=execute_plan(Store(dataset=ds),self.plan());self.assertEqual(r['classification_coverage']['verified_class_count'],22);self.assertEqual(r['classification_coverage']['unmatched_codes'],['ZZZZZ00']);self.assertEqual(sum(x['cells'][2] for x in r['records']),90);self.assertIn('不能据此确认完整类别数',r['answer'])
 def test_blank_category_not_verified(self):
  ds=copy.deepcopy(self.s.dataset)
  for pkt in ds:
   if pkt['kind']=='config':
    for row in pkt['rows']:
     if row['对象代码']=='RRGA02#1':row['所属部件类代码']=''
  r=execute_plan(Store(dataset=ds),self.plan());self.assertEqual(r['classification_coverage']['missing_class_records'],1);self.assertEqual(sum(x['cells'][2] for x in r['records']),90)
 def test_category_dictionary_evidence(self):
  r=execute_plan(self.s,self.plan());self.assertTrue(any(x['file']=='部件类.csv' for x in r['evidence']))
 def test_single_and_batch_normalization_equal(self):
  p=dict(operation='parts',entity={'tree':'config','code':'MOHB01'},scope='direct',clarification='',query={'target':'parts','filters':[]})
  single=execute_plan(self.s,p);batch=execute_plan(self.s,dict(operation='batch',entity=None,scope='direct',clarification='',tasks=[{'question':'A','intent':p},{'question':'B','intent':p}]))
  self.assertEqual(single['records'],batch['items'][0]['records']);self.assertEqual(single['query_receipt']['operation'],'search')
 def test_unexecuted_analysis_rejected(self):
  p=self.plan();p['operation']='search'
  with self.assertRaises(ModelUnavailable):execute_plan(self.s,p)
 def test_named_scope_and_part_filter(self):
  p=self.plan();p['query']['filters']=[{'field':'class_code','operator':'equals','value':'ZZZZZ00'}];r=execute_plan(self.s,p);self.assertEqual(r['metrics'][0]['value'],39);self.assertEqual(r['classification_coverage']['verified_class_count'],1)
 def test_wrong_range_empty_not_global(self):
  p=self.plan();p['entity']={'tree':'pbs','code':'XJ2ABC001MO'};r=execute_plan(self.s,p);self.assertEqual(r['classification_coverage']['verified_class_count'],0);self.assertEqual(r['records'],[])

 def test_truncated_reference_diagnostic(self):
  from reference_binding import diagnose,apply_repairs
  p=self.plan();p['query']['equipment_class']['value']='3727'
  issues=diagnose(self.s,p,'功能位置名称XXXX6143内，设备类描述3727对应的设备，其部件有多少类？')
  self.assertEqual(len(issues),1);self.assertEqual(issues[0]['candidates'][0]['name'],'设备类描述3727')
  fixed=apply_repairs(p,issues,{'repairs':[{'reference':0,'candidate':0}]});self.assertEqual(fixed,self.plan());self.assertEqual(p['query']['equipment_class']['value'],'3727')
 def test_missing_name_no_speculative_candidate(self):
  from reference_binding import diagnose
  p=self.plan();p['query']['equipment_class']['value']='不存在的类别999'
  self.assertEqual(diagnose(self.s,p,'不存在的类别999'),[])
 def test_reference_patch_cannot_change_scope_or_analysis(self):
  from reference_binding import diagnose,apply_repairs
  p=self.plan();p['query']['equipment_class']['value']='3727';issues=diagnose(self.s,p,'设备类描述3727')
  for response in [{'repairs':[{'reference':0,'candidate':0,'scope':'direct'}]},{'repairs':[{'reference':0,'candidate':99}]},{'repairs':[],'entity':None}]:
   with self.assertRaises(ValueError):apply_repairs(p,issues,response)
 def test_reference_decline_preserves_error(self):
  from reference_binding import diagnose,apply_repairs
  p=self.plan();p['query']['equipment_class']['value']='3727';issues=diagnose(self.s,p,'设备类描述3727')
  self.assertEqual(apply_repairs(p,issues,{'repairs':[]}),p)
