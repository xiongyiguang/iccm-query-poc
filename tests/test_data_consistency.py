import sys,unittest,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from data import Store,QueryError
from query_filters import POINT_FIELDS,POINT_RAW_FIELDS,validate_query
from attributes import CATALOG
from data_context import point_summary,knowledge_context
from model import validate,ModelUnavailable

def plan(op='search',entity=None,**kw):return dict(operation=op,entity=entity,scope='direct',clarification='',**kw)
def query(field,operator='not_blank',value=''):
 return plan(query={'target':'points','filters':[dict(field=field,operator=operator,value=value)]})

class ConsistencyTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.s=Store()
 def test_all_scalar_point_properties_filterable(self):
  self.assertEqual(set(POINT_FIELDS)|set(POINT_RAW_FIELDS),{k for k,v in CATALOG.items() if 'points' in v['fields']})
 def test_empty_prediction_is_not_zero_value(self):
  self.assertEqual(len(self.s.execute(query('prediction'))['records']),0)
  self.assertEqual(len(self.s.execute(query('prediction','is_blank'))['records']),12985)
  r=self.s.execute(query('value','equals','0'));self.assertGreater(len(r['records']),0)
  self.assertEqual(point_summary(r['records'])['with_value'],len(r['records']))
 def test_alarm_reason_independent_from_status(self):
  r=self.s.execute(query('alarm_reason'));self.assertEqual(len(r['records']),80)
  summary=point_summary(r['records']);self.assertEqual(summary['states'],{'已报警':48,'未报警':32})
  self.assertEqual(summary['reasons'],{'真实值报警':80})
 def test_sql_payload_literal_and_unknown_field(self):
  self.assertEqual(self.s.execute(query('alarm_reason','equals',"' OR 1=1 --"))['records'],[])
  with self.assertRaises(ValueError):validate_query(query('other')['query'])
 def test_read_then_navigate_then_unresolved(self):
  subject={'tree':'pbs','code':'XJ2ABC002MO.MDI.2ABC002MM.Axi_X'}
  p=plan('parent',subject,navigate=False);validate(p);r=self.s.execute(p)
  self.assertEqual(r['entity'],subject);self.assertFalse(r['relation']['navigated'])
  r=self.s.execute({**p,'navigate':True});self.assertEqual(r['entity']['code'],'XJ2ABC002MO')
  self.assertTrue(r['relation']['navigated'])
  r2=self.s.execute(plan('parent',r['entity'],navigate=True))
  self.assertEqual(r2['relation']['status'],'reference_only');self.assertEqual(r2['entity'],r['entity'])
 def test_navigation_validation(self):
  for p in [plan('search',navigate=False),plan('parent',navigate='false')]:
   with self.assertRaises(ModelUnavailable):validate(p)
   with self.assertRaises(QueryError):self.s.execute(p)
 def test_full_scope_summary(self):
  r=self.s.execute(plan('measurements',{'tree':'pbs','code':'XJ2ABC001MO'}));s=point_summary(r['records'])
  self.assertEqual(s['records'],901);self.assertEqual(s['with_value'],135)
  self.assertEqual(s['states'],{'已报警':10,'未报警':120,'未提供':771})
  self.assertIn('135',r['answer'])
 def test_snapshot_knowledge_counts_not_model_generated(self):
  k=knowledge_context(self.s);self.assertEqual(k['point_to_pbs']['matched_records'],12341)
  self.assertEqual(k['point_to_pbs']['unmatched_records'],644)
  self.assertEqual(k['tree_counts']['pbs'],16796)
  self.assertEqual(k['pbs_function_locations'],200)
  self.assertEqual(len(k['facts']['architecture']),5)
 def test_population_reference_does_not_change_filter(self):
  r=self.s.execute(query('status','equals','已报警'))
  self.assertEqual(len(r['records']),48)
  self.assertIn('2312',r['note']);self.assertIn('10625',r['note'])
  self.assertIn('全表状态参考',r['note'])
 def test_verified_explanation_dynamic_counts(self):
  p=plan('explain',topics=['counts','coverage','references']);validate(p);r=self.s.execute(p)
  for value in ['16796','200','12985','12341','644']:self.assertIn(value,r['answer'])
  self.assertEqual(r['explanation_topics'],p['topics'])
  self.assertEqual(r['records'],[])
  self.assertNotIn('其他树',r['answer'])
 def test_explanation_rejects_unverified_extensions(self):
  for p in [plan('explain',topics=['unknown']),plan('explain',topics=['counts'],message='invented'),plan('search',topics=['counts']),plan('explain',topics=['counts','counts'])]:
   with self.assertRaises(ModelUnavailable):validate(p)
   with self.assertRaises(QueryError):self.s.execute(p)
 def test_relation_comparison_reads_all_parent_fields(self):
  p=plan('relation_check',subjects=[{'tree':'config','identifier':x} for x in ['MO','MOH','MOHB']]);validate(p);r=self.s.execute(p)
  self.assertEqual({(e['parent'],e['child']) for e in r['relation_edges']},{('MO','MOH'),('MOH','MOHB')})
  self.assertEqual(len(r['records']),3)
  p['subjects'].reverse();self.assertEqual({(e['parent'],e['child']) for e in self.s.execute(p)['relation_edges']},{('MO','MOH'),('MOH','MOHB')})
 def test_relation_comparison_missing_and_unrelated(self):
  p=plan('relation_check',subjects=[{'tree':'config','identifier':x} for x in ['MO','NO-SUCH-OBJECT']]);r=self.s.execute(p);self.assertEqual(r['status'],'clarify');self.assertEqual(r['relation_edges'],[])
  p['subjects'][1]['identifier']='MOHB01';self.assertEqual(self.s.execute(p)['relation_edges'],[])
 def test_relation_comparison_validation(self):
  for p in [plan('relation_check',subjects=[]),plan('search',subjects=[{}]),plan('relation_check',subjects=[{'tree':'unknown','identifier':'MO'}]*2)]:
   with self.assertRaises(ModelUnavailable):validate(p)
   with self.assertRaises(QueryError):self.s.execute(p)
 def test_identical_value_threshold_plan_coalescing(self):
  import copy
  a=plan('attributes',{'tree':'pbs','code':'XJ2ABC001MO.TMP.2ABC109MT.BBe'},properties=['value']);t=plan('threshold',a['entity'])
  b=plan('batch',tasks=[{'question':'value','intent':a},{'question':'threshold','intent':t}])
  self.assertEqual(validate(copy.deepcopy(b))['operation'],'threshold')
  b['tasks'][0]['intent']['properties']=['value','alarm_reason'];self.assertEqual(validate(copy.deepcopy(b))['operation'],'batch')
  b['tasks'][0]['intent']['properties']=['value'];b['tasks'][1]['intent']['entity']={'tree':'pbs','code':'different'};self.assertEqual(validate(b)['operation'],'batch')
 def test_partial_and_non_numeric_raw_values(self):
  rs=[{'evidence':{'fields':{'测量值':v,'状态':s}}} for v,s in [('0',''),('Y','已报警'),('','未报警')]]
  self.assertEqual(point_summary(rs)['with_value'],2)

if __name__=='__main__':unittest.main()
