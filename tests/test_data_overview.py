import unittest,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from data import Store
from model import validate,ModelUnavailable
class DataOverviewTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.store=Store()
 def test_overview(self):
  r=self.store.execute(validate(dict(operation='data_overview',entity=None,scope='direct',clarification='')))
  self.assertEqual([x['cells'][1] for x in r['records']],[16796,24025,3748,1631,12985])
  self.assertEqual(r['status'],'conversation');self.assertIsNone(r['entity']);self.assertIn('并非所有记录均可关联',r['note'])
 def test_no_silent_filter_loss(self):
  with self.assertRaises(ModelUnavailable):validate(dict(operation='data_overview',entity={'tree':'config','code':'MOHB01'},scope='direct',clarification=''))
