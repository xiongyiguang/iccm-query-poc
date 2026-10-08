import unittest,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from data import Store
from model import validate,ModelUnavailable
from query_plan import execute_plan
import test_filters

def one(op,entity=None):return {'operation':op,'entity':entity,'scope':'direct','clarification':''}
def batch(a,b):return {'operation':'batch','entity':None,'scope':'direct','clarification':'','tasks':[{'question':'部件','intent':a},{'question':'报警','intent':b}]}
class PlanTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.store=Store()
 def test_two_queries_and_scopes(self):
  p=batch(one('parts',{'tree':'config','code':'MOHB01'}),one('alarms'))
  r=execute_plan(self.store,p);self.assertEqual([len(x['records']) for x in r['items']],[51,48])
  self.assertIsNone(r['items'][1]['entity'])
 def test_partial_failure_and_missing_data(self):
  r=execute_plan(self.store,batch(one('object',{'tree':'pbs','code':'not-exist'}),one('alarms')))
  self.assertEqual([x['status'] for x in r['items']],['not_found','ok'])
  r=execute_plan(self.store,batch(one('duration'),one('alarms')))
  self.assertEqual([x['status'] for x in r['items']],['data_insufficient','ok'])
 def test_nested_excess_and_single_tasks_rejected(self):
  p=batch(one('alarms'),one('alarms'))
  for bad in [{**p,'tasks':[p]}, {**p,'tasks':p['tasks']*3},{**one('alarms'),'tasks':p['tasks']}]:
   with self.assertRaises(ModelUnavailable):validate(bad)
class PlanHttpTests(test_filters.FilterHttpTests):
 def test_independent_pages_and_branches(self):
  r=self.request('/api/query',{'session':'batch-page','intent':batch(one('parts',{'tree':'config','code':'MOHB01'}),one('alarms'))})
  self.assertEqual(r['status'],'batch');self.assertEqual([x['total'] for x in r['items']],[51,48])
  self.assertNotEqual(r['items'][0]['result'],r['items'][1]['result']);self.assertNotIn('entity',r['context'])
  for item,n in zip(r['items'],[11,8]):
   pg=self.request('/api/page',{'session':'batch-page','result':item['result'],'page':2});self.assertEqual(len(pg['records']),n)
if __name__=='__main__':unittest.main(verbosity=2)
