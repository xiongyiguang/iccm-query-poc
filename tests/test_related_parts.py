import unittest,sys,copy
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from data import Store,QueryError
from model import validate,ModelUnavailable
from query_plan import task_context
class RelatedPartsTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.s=Store()
 def plan(self):
  return dict(operation='analyze',entity={'tree':'pbs','code':'XJ3ABC002RR'},scope='all',clarification='',query={'target':'parts','filters':[],'equipment_class':{'field':'name','operator':'equals','value':'设备类描述3727'}},analysis={'kind':'group_count','group_by':'class_code','order':'desc','limit':100,'numerator':[]})
 def test_original(self):
  r=self.s.execute(validate(self.plan()));self.assertEqual([m['value'] for m in r['metrics']],[90,23]);self.assertEqual(sum(x['cells'][2] for x in r['records']),90)
 def test_code(self):
  p=self.plan();p['query']['equipment_class'].update(field='code',value='RRGA02');self.assertEqual(self.s.execute(validate(p))['metrics'][1]['value'],23)
 def test_different_scope(self):
  p=self.plan();p['entity']['code']='XJ2ABC001MO';self.assertEqual(self.s.execute(validate(p))['metrics'][0]['value'],0)
 def test_missing_class(self):
  p=self.plan();p['query']['equipment_class']['value']='不存在的分类'
  with self.assertRaises(QueryError):self.s.execute(validate(p))
 def test_filter_and_context(self):
  p=self.plan();p['query']['filters']=[{'field':'class_code','operator':'equals','value':'ZZZZZ00'}]
  r=self.s.execute(validate(p));self.assertEqual([m['value'] for m in r['metrics']],[39,1]);self.assertEqual(task_context(p,r)['query'],p['query'])
 def test_direct(self):
  p=self.plan();p['scope']='direct';self.assertEqual(self.s.execute(validate(p))['metrics'][0]['value'],90)
 def test_no_scope_rejected(self):
  p=self.plan();p['entity']=None
  with self.assertRaises(QueryError):self.s.execute(validate(p))
 def test_wrong_target_rejected(self):
  p=self.plan();p['query']['target']='points'
  with self.assertRaises(ModelUnavailable):validate(p)
 def test_missing_link_fails_closed(self):
  ds=copy.deepcopy(self.s.dataset)
  for packet in ds:
   if packet['kind']=='config':packet['rows']=[r for r in packet['rows'] if r.get('对象代码',r.get('对象编码'))!='RRGA02#1']
  s=Store(dataset=ds)
  with self.assertRaises(QueryError):s.execute(validate(self.plan()))
 def test_top_groups_retains_total(self):
  p=self.plan();p['analysis']['limit']=5;r=self.s.execute(validate(p));self.assertEqual(len(r['records']),5);self.assertEqual(r['metrics'][1]['value'],23)
