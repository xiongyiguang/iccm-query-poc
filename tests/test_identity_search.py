import unittest,sys,sqlite3
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from query_filters import predicates,validate_query,describe
from data import Store

class IdentitySearchTests(unittest.TestCase):
 def test_union_once_and_extra_condition(self):
  db=sqlite3.connect(':memory:')
  db.execute('create table sample(name,code,level)')
  db.executemany('insert into sample values(?,?,?)',[('ABC','ABC','x'),('ABC','Z','x'),('Z','ABC','y'),('Z','Z','x')])
  q={'target':'config','filters':[{'field':'identity','operator':'contains','value':'ABC'},{'field':'level','operator':'equals','value':'x'}]}
  clauses,args=predicates(q)
  self.assertEqual(len(db.execute('select * from sample r where '+' AND '.join(clauses),args).fetchall()),2)
  self.assertIn('名称或编码',describe(q))
 def test_real_fields(self):
  s=Store()
  for field,count in [('name',0),('code',792),('identity',792)]:
   r=s.execute(dict(operation='search',entity=None,scope='direct',query={'target':'config','filters':[{'field':field,'operator':'contains','value':'MOHB'}]}))
   self.assertEqual(len(r['records']),count)
 def test_targets_and_safety(self):
  for target in ('pbs','config','parts','equipment','equipment_class','part_class','points'):
   for op in ('contains','equals','starts_with'):
    q={'target':target,'filters':[{'field':'identity','operator':op,'value':"x' OR 1=1 --"}]}
    sql,args=predicates(q);self.assertNotIn(q['filters'][0]['value'],str(sql));self.assertIn(q['filters'][0]['value'],args)
   q['filters'][0]['operator']='not_contains'
   with self.assertRaises(ValueError):validate_query(q)
if __name__=='__main__':unittest.main()
