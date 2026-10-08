import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from data import Store,QueryError
class BrowserTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.s=Store()
 def test_current_paths_and_children(self):
  r=self.s.browse('config','MOHB01');self.assertEqual(r['current']['code'],'MOHB01');self.assertTrue(all(x['parent']=='MOHB01' for x in r['records']));self.assertGreater(r['total'],24)
  child=r['records'][0];d=self.s.browse('config',child['code']);self.assertEqual(d['path'][-1]['code'],'MOHB01')
 def test_roots_are_real(self):
  for tree in ['pbs','config','equipment_class','part_class']:
   r=self.s.browse(tree)
   for o in r['records']:self.assertFalse(self.s.rows('SELECT 1 FROM objects WHERE tree=? AND code=?',(tree,o['parent'])))
 def test_leaf_search_and_paging(self):
  r=self.s.browse('pbs',text='XXXX9648');self.assertEqual(r['total'],1)
  o=r['records'][0];self.assertEqual(self.s.browse('pbs',o['code'])['total'],o['children'])
  r=self.s.browse('config',text='1',page=999999);self.assertLessEqual(len(r['records']),24);self.assertGreater(r['total'],24)
 def test_invalid_and_literal(self):
  with self.assertRaises(QueryError):self.s.browse('other')
  self.assertEqual(self.s.browse('config',text="' OR 1=1 --")['total'],0)
if __name__=='__main__':unittest.main(verbosity=2)
