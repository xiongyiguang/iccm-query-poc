import unittest,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from data import Store
from model import validate,ModelUnavailable
class AnalyticsTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.s=Store()
 def intent(self,target='parts',kind='group_count',group='class_code',entity=None,filters=None,numerator=None):
  return dict(operation='analyze',entity=entity,scope='all',clarification='',query={'target':target,'filters':filters or []},analysis={'kind':kind,'group_by':group,'order':'desc','limit':100,'numerator':numerator or []})
 def test_parts(self):
  r=self.s.execute(self.intent(entity={'tree':'config','code':'MOHB01'}))
  self.assertEqual(sum(x['cells'][2] for x in r['records']),221)
  expected=self.s.rows("SELECT class_code,count(*) n FROM objects WHERE tree='config' AND level='部件' AND code IN (SELECT child FROM ancestors WHERE tree='config' AND ancestor='MOHB01') GROUP BY class_code")
  self.assertEqual({x['cells'][1]:x['cells'][2] for x in r['records']},{x['class_code']:x['n'] for x in expected})
 def test_ratio(self):
  r=self.s.execute(self.intent('points','ratio',None,filters=[{'field':'switch','operator':'equals','value':'开启'}],numerator=[{'field':'status','operator':'equals','value':'已报警'}]))
  self.assertEqual(r['chart']['numerator'],48)
  self.assertGreater(r['chart']['denominator'],48)
 def test_empty(self):
  r=self.s.execute(self.intent('points','ratio',None,filters=[{'field':'code','operator':'equals','value':'NO-SUCH'}],numerator=[{'field':'status','operator':'equals','value':'已报警'}]))
  self.assertEqual(r['chart']['denominator'],0);self.assertIn('无法计算',r['answer'])
 def test_ranking(self):
  i=self.intent('points',group='location',filters=[{'field':'status','operator':'equals','value':'已报警'},{'field':'switch','operator':'equals','value':'开启'}])
  full=self.s.execute(i);self.assertEqual(sum(x['cells'][2] for x in full['records']),48)
  i['analysis']['limit']=5;r=self.s.execute(i);self.assertEqual(r['records'],full['records'][:5])
 def test_reject_ignored_analysis(self):
  i=self.intent();i['operation']='search'
  with self.assertRaises(ModelUnavailable):validate(i)
 def test_parts_predicate_contract(self):
  i={'operation':'parts','entity':{'tree':'config','code':'MOHB01'},'scope':'all','clarification':'','query':{'target':'parts','filters':[]}}
  normalized=validate(i)
  self.assertEqual(normalized['operation'],'search')
  self.assertEqual(len(self.s.execute(normalized)['records']),221)
 def test_bad_group(self):
  i=self.intent();i['analysis']['group_by']='location'
  with self.assertRaises(ModelUnavailable):validate(i)
if __name__=='__main__':unittest.main()
