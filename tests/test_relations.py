import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from data import Store,QueryError
from query_plan import task_context
from test_filters import FilterHttpTests

class Relations(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.s=Store()
 def query(self,code,op='parent',tree='pbs'):
  return self.s.execute(dict(operation=op,entity={'tree':tree,'code':code},scope='direct'))
 def test_original_chain_and_repeat(self):
  first=self.query('XJ2ABC002MO.MDI.2ABC002MM.Axi_X')
  self.assertEqual(first['relation']['status'],'resolved');self.assertEqual(first['entity']['code'],'XJ2ABC002MO')
  self.assertEqual(first['path'][-1]['code'],'XJ2ABC002MO')
  second=self.query(first['entity']['code']);self.assertEqual(second['relation']['status'],'reference_only')
  self.assertEqual(second['relation']['target_code'],'XJ2ABC');self.assertIsNone(second['relation']['target'])
  self.assertEqual(second['entity'],first['entity']);self.assertEqual(second['records'],[])
  self.assertIn('XXXX6080',second['answer']);self.assertIn('没有包含',second['answer'])
  self.assertNotIn('请选择',second['answer']);self.assertEqual(self.query(second['entity']['code'])['answer'],second['answer'])
  self.assertEqual(second['relation']['evidence']['fields']['父对象代码'],'XJ2ABC')
 def test_blank_parent(self):
  r=self.s.rows("SELECT code FROM objects WHERE tree='config' AND parent='' LIMIT 1")[0]
  result=self.query(r['code'],tree='config');self.assertEqual(result['relation']['status'],'not_provided');self.assertIsNone(result['relation']['target_code'])
 def test_missing_class_reference(self):
  for op,field,target in [('part_class','class_code','part_class'),('equipment_class','parent','equipment_class')]:
   # 使用内存合成数据，不改变客户 CSV。
   s=Store();s.db.execute("PRAGMA query_only=OFF");s.db.execute("UPDATE objects SET "+field+"='MISSING-REF' WHERE tree='config' AND code='MOHB01'")
   s.db.execute("PRAGMA query_only=ON")
   result=s.execute({'operation':op,'entity':{'tree':'config','code':'MOHB01'},'scope':'direct'})
   self.assertEqual(result['relation']['status'],'reference_only');self.assertEqual(result['entity']['code'],'MOHB01')
   s.db.close()
 def test_invalid_subject_still_error(self):
  with self.assertRaises(QueryError):self.query('NO-SUCH-SUBJECT')
 def test_name_lookup_does_not_retain_child(self):
  i=dict(operation='parent',entity=None,scope='direct',query={'target':'pbs','filters':[{'field':'name','operator':'equals','value':'XXXX2834'}]})
  r=self.s.execute(i);c=task_context(i,r);self.assertNotIn('lookup_query',c);self.assertEqual(c['entity']['code'],'XJ2ABC002MO')

class RelationHttp(FilterHttpTests):
 def test_reference_only_is_success_and_retains_focus(self):
  i=dict(operation='parent',entity={'tree':'pbs','code':'XJ2ABC002MO'},scope='direct')
  r=self.request('/api/query',{'session':'parent-missing','intent':i})
  self.assertEqual(r['status'],'ok');self.assertEqual(r['context']['entity'],i['entity'])
  self.assertEqual(r['context']['relation']['status'],'reference_only')
  self.assertNotIn('XJ2ABC',[x['code'] for x in r['path']]);self.assertEqual(r['total'],0)

if __name__=='__main__':unittest.main()
