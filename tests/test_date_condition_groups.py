"""时间段是同一逻辑条件；原话覆盖与实际执行分别验证。"""
import copy,sys,unittest
from pathlib import Path
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'backend'),str(Path(__file__).resolve().parent)]
from data import Store
from relational_query import canonical,Graph,execute_task
from relational_delta_codec import normalize_delta
from relational_state import compile_delta
from question_coverage import audit,CoverageInvalid
from test_question_coverage import single,f
import test_relational_query as fixture


class Dates(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  fixture.Relations.setUpClass();cls.s=fixture.Relations.s
 def context(self):
  return {'relational_state':{'tasks':[{'id':1,'spec':canonical({'kind':'collection','population':'points','filters':[f('source','S'),f('time','2025-06-01','date_gte'),f('time','2025-07-01','date_lt')]}),'resolved':{}}]}}
 def raw(self,q,edits):return {'version':2,'handled':True,'mode':'update','tasks':[{'id':1,'action':'update','quote':q,'set':{},'filters':edits}]}
 def compile(self,q,edits):
  d,notes=normalize_delta(self.raw(q,edits),q,self.context(),self.s);return compile_delta(d,q,self.context(),self.s)[0]['tasks'][0]['spec'],notes
 def test_calendar_replacement_removes_actual_old_two_boundaries(self):
  q='时间条件换为2024年，保留来源条件';spec,_=self.compile(q,[{'action':'add','condition':f('time','2024','date_equals'),'quote':'时间条件换为2024年'}]);self.assertEqual(spec['filters'],[f('source','S'),f('time','2024','date_equals')]);self.assertEqual(audit(self.s,q,single(spec['filters']),self.context())['status'],'covered')
 def test_replace_representation_has_same_period_without_residual_bound(self):
  q='测量时间条件改为2024年';spec,_=self.compile(q,[{'action':'replace','selector':{'field':'time','operator':'date_gte'},'condition':f('time','2024','date_equals'),'quote':q},{'action':'remove','selector':{'field':'time','operator':'date_lt'},'quote':q}]);self.assertEqual(spec['filters'],[f('source','S'),f('time','2024','date_equals')])
 def test_whole_field_cancel_removes_both_date_bounds(self):
  spec,_=self.compile('撤销测量时间限制',[]);self.assertEqual(spec['filters'],[f('source','S')])
 def test_whole_field_selector_expands_only_raw_authorized_date_group(self):
  q='撤销测量时间限制';spec,_=self.compile(q,[{'action':'remove','selector':{'field':'time'},'quote':q}]);self.assertEqual(spec['filters'],[f('source','S')])
 def test_specific_old_boundary_does_not_clear_other_boundary(self):
  q='撤销时间不早于2025-06-01的条件';spec,_=self.compile(q,[{'action':'remove','selector':{'field':'time','operator':'date_gte'},'quote':q}]);self.assertIn(f('time','2025-07-01','date_lt'),spec['filters'])
 def test_missing_model_new_period_is_not_invented_by_program(self):
  q='时间条件换为2024年';spec,_=self.compile(q,[]);self.assertIn(f('time','2025-07-01','date_lt'),spec['filters'])
  with self.assertRaises(CoverageInvalid):audit(self.s,q,single(spec['filters']),self.context())
 def test_stale_extra_date_period_cannot_cover_replacement(self):
  with self.assertRaises(CoverageInvalid):audit(self.s,'时间条件改成2024年',single([f('time','2024','date_equals'),f('time','2025','date_equals')]))
 def test_half_open_new_period_proves_replacement(self):self.assertEqual(audit(self.s,'时间条件换为2024年',single([f('time','2024-01-01','date_gte'),f('time','2025-01-01','date_lt')]))['status'],'covered')
 def test_equivalent_redundant_precision_preserves_period(self):
  q='时间条件换为2024年';spec,_=self.compile(q,[{'action':'add','condition':{**f('time','2024','date_equals'),'precision':'year'},'quote':q}]);self.assertIn(f('time','2024','date_equals'),spec['filters'])
 def test_conflicting_precision_is_rejected(self):
  q='时间条件换为2024年'
  with self.assertRaises(ValueError):self.compile(q,[{'action':'add','condition':{**f('time','2024','date_equals'),'precision':'month'},'quote':q}])
 def test_complete_chinese_calendar_literal_keeps_exact_precision(self):
  self.assertEqual(audit(self.s,'测量时间在2024年9月',single([f('time','2024年9月','date_equals')]))['status'],'covered')
 def test_date_literal_unknown_tail_is_not_truncated(self):
  from date_fields import calendar_period
  self.assertIsNone(calendar_period('2024年9月未知'));self.assertIsNone(calendar_period('2024/9/99'))


class DateExecution(unittest.TestCase):
 def setUp(self):
  times=['2025/6/2 23:59','2025/6/3 8:00','2025-06-02T16:00:00Z','2025/7/1 0:00','','invalid']
  self.s=Store(dataset=[{'kind':'points','file':'points.csv','sha256':'fixture','seed':True,'rows':[{'测量点编码':'P'+str(i),'测量时间':t} for i,t in enumerate(times)]}]);self.g=Graph(self.s)
 def tearDown(self):self.s.db.close()
 def codes(self,filters):return {r['code'] for r in execute_task(self.g,canonical({'kind':'collection','population':'points','filters':filters}))['record_facts']}
 def test_year_month_day_instant_have_exact_business_timezone_boundaries(self):
  for value,want in [('2025',{'P0','P1','P2','P3'}),('2025-06',{'P0','P1','P2'}),('2025-06-03',{'P1','P2'}),('2025/6/3 8:00',{'P1'})]:self.assertEqual(self.codes([f('time',value,'date_equals')]),want)
 def test_range_excludes_end_and_unparseable_dates(self):self.assertEqual(self.codes([f('time','2025-06-03','date_gte'),f('time','2025-07-01','date_lt')]),{'P1','P2'})
 def test_sql_and_graph_use_same_registered_date_operator(self):
  sql={r['code'] for r in self.s.rows('SELECT code FROM points WHERE date_compare(time,?,?)=1',['date_equals','2025-06-03'])};self.assertEqual(sql,{'P1','P2'});self.assertEqual(self.codes([f('time','2025-06-03','date_equals')]),sql)
 def test_chinese_and_unpadded_calendar_aliases_preserve_original_time(self):
  for v in ('2025年6月3日','2025/6/3','2025-6-3'):self.assertEqual(self.codes([f('time',v,'date_equals')]),{'P1','P2'})
  self.assertEqual(self.s.rows('SELECT time FROM points WHERE code=?',['P1'])[0]['time'],'2025/6/3 8:00')
 def test_point_collection_always_displays_measurement_value(self):
  for group in (None,'source'):
   q=canonical({'kind':'collection','population':'points','group_by':group});r=execute_task(self.g,q);self.assertIn('测量值',r['columns'])


if __name__=='__main__':unittest.main()
