import sys,unittest,copy
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from data import Store,QueryError
from model import validate,ModelUnavailable
class EntityNameTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.s=Store()
 def plan(self):return dict(operation='parts',entity={'tree':'config','name':'构型对象描述10435'},scope='direct',clarification='')
 def test_original(self):
  r=self.s.execute(validate(self.plan()));self.assertEqual([x['value'] for x in r['metrics']],[0,5749]);self.assertEqual(r['entity']['code'],'APAC01')
 def test_all(self):
  p=self.plan();p['scope']='all';self.assertEqual(len(self.s.execute(validate(p))['records']),5749)
 def test_missing_name(self):
  p=self.plan();p['entity']['name']='不存在的完整名称'
  with self.assertRaises(QueryError):self.s.execute(validate(p))
 def test_code_no_fallback(self):
  p=self.plan();p['entity']={'tree':'config','code':'构型对象描述10435'}
  with self.assertRaises(QueryError):self.s.execute(validate(p))
 def test_dual_identifier_rejected(self):
  p=self.plan();p['entity']['code']='APAC01'
  with self.assertRaises(ModelUnavailable):validate(p)
 def test_filtered_children(self):
  p=self.plan();p.update(operation='search',scope='all',query={'target':'parts','filters':[]});self.assertEqual(len(self.s.execute(validate(p))['records']),5749)
 def test_duplicate_name(self):
  ds=copy.deepcopy(self.s.dataset)
  for packet in ds:
   if packet['kind']=='config':
    row=next(x for x in packet['rows'] if x['对象代码']=='APAC01').copy();row['对象代码']='DUPLICATE';packet['rows'].append(row)
  with self.assertRaisesRegex(QueryError,'多个对象'):Store(dataset=ds).execute(validate(self.plan()))
