"""第三轮真实失败对应的目标完整性、完整集合计算及日期边界回归。"""
import copy,csv,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from data import Store,SOURCE
from query_plan import execute_plan
from result_goal import default_goal,validate_goal
from date_fields import parse_time
from business_request import apply_delta,compile_task,commit_state,RequestInvalid,extraction_context
from request_checklist import reconcile

class ResultGoalTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.store=Store()
  with (SOURCE/'测量点数据分析.csv').open(encoding='gb18030') as f:cls.raw=list(csv.DictReader(f))
 def goal(self,kind,**kw):return {**default_goal('search'),'kind':kind,**kw}
 def plan(self,goal,filters=[]):return {'operation':'search','entity':None,'scope':'direct','clarification':'','query':{'target':'points','filters':copy.deepcopy(filters)},'result_goal':goal}
 def test_earliest_returns_all_ties_not_entire_population(self):
  g=self.goal('extreme',field='time',direction='asc');r=execute_plan(self.store,self.plan(g))
  expected=min(parse_time(x['测量时间']) for x in self.raw if x['测量时间'])
  rows=[x for x in self.raw if parse_time(x['测量时间'])==expected]
  self.assertEqual(r['status'],'ok');self.assertEqual(len(r['records']),len(rows));self.assertEqual(len(rows),1461)
  self.assertTrue(all(parse_time(x['time'])==expected for x in r['records']));self.assertNotEqual(len(r['records']),len(self.raw))
  self.assertEqual(r['query_receipt']['result_goal'],g);self.assertTrue(r['goal_receipt']['completed'])
 def test_calendar_month_matches_independent_csv_parse(self):
  filters=[{'field':'time','operator':'date_gte','value':'2026-05-01'},{'field':'time','operator':'date_lt','value':'2026-06-01'}]
  r=execute_plan(self.store,self.plan(self.goal('count'),filters))
  expected=[x for x in self.raw if x['测量时间'] and parse_time('2026-05-01')<=parse_time(x['测量时间'])<parse_time('2026-06-01')]
  self.assertEqual(len(r['records']),len(expected));self.assertEqual(len(expected),829)
  self.assertEqual(r['query_receipt']['goal_receipt']['goal']['kind'],'count')
 def test_numeric_extreme_refuses_mixed_and_missing_units(self):
  r=execute_plan(self.store,self.plan(self.goal('extreme',field='value',direction='desc'),[{'field':'status','operator':'equals','value':'已报警'}]))
  self.assertEqual(r['status'],'clarify');self.assertEqual(r['records'],[]);self.assertNotIn('goal_receipt',r)
 def test_explicit_unit_extreme_has_source_proof(self):
  filters=[{'field':'status','operator':'equals','value':'已报警'},{'field':'unit','operator':'equals','value':'℃'}]
  r=execute_plan(self.store,self.plan(self.goal('extreme',field='value',direction='desc'),filters))
  self.assertEqual(r['status'],'ok');self.assertEqual(r['records'][0]['name'],'测量点名称4');self.assertEqual(r['records'][0]['value'],'70.80151367')
 def test_explicit_raw_difference_preserves_direction(self):
  operands=[{'field':'name','value':'测量点名称7'},{'field':'name','value':'测量点名称6'}]
  g=self.goal('difference',field='value',operands=operands,basis='raw_numbers');r=execute_plan(self.store,self.plan(g))
  self.assertEqual(r['status'],'ok');self.assertEqual(r['metrics'][0]['value'],'1.447999954');self.assertEqual(len(r['evidence']),2)
  self.assertEqual([x['name'] for x in r['operands']],[x['value'] for x in operands])
 def test_difference_does_not_assume_empty_units_are_comparable(self):
  g=self.goal('difference',field='value',operands=[{'field':'name','value':'测量点名称7'},{'field':'name','value':'测量点名称6'}]);r=execute_plan(self.store,self.plan(g))
  self.assertEqual(r['status'],'clarify');self.assertEqual(r['records'],[])
 def test_invalid_goal_never_disappears_during_validation(self):
  for change in ({'kind':'top_magic'},{'ties':'first'},{'limit':0},{'field':None}):
   g=self.goal('extreme',field='time',direction='asc',**({} if 'field' in change else {}));g.update(change)
   with self.subTest(change=change),self.assertRaises(ValueError):validate_goal(g,'search','points')
 def task(self):
  q='全部测点记录';delta={'version':1,'mode':'new','tasks':[{'base':None,'quote':q,'set':{'operation':'search','target':'points'},'filters':[]}]}
  return apply_delta(delta,None,q)[1]
 def test_goal_is_part_of_plan_equality(self):
  state=self.task();other=copy.deepcopy(state);other['tasks'][0]['result_goal']=self.goal('extreme',field='time',direction='asc')
  self.assertFalse(reconcile(state,['t1'],other,['t1'],self.store)['matches'])
  self.assertEqual(compile_task(other['tasks'][0])['result_goal']['kind'],'extreme')
 def test_modern_request_cannot_omit_goal(self):
  q='全部测点记录中，测量时间最早的是哪条';delta={'version':10,'mode':'new','roles':{'background':[],'output':[1,2],'control':[]},'tasks':[{'base':None,'action':'request','request_spans':[1,2],'spans':[1,2],'purpose':'data','subject_scope':'none','set':{'operation':'search','target':'points'},'filters':[]}]}
  with self.assertRaisesRegex(RequestInvalid,'结果目标'):apply_delta(delta,None,q)
 def test_ambiguous_outcome_keeps_current_request_draft(self):
  state=self.task();context=commit_state({'pending_request':{}},{'engine':'business_request','business_request_state':state,'changed_tasks':['t1']},{'status':'ambiguous','outcome':{'kind':'ambiguous'}},{'pending_business_request':state})
  self.assertEqual(context['pending_business_request']['tasks'],state['tasks']);self.assertEqual(extraction_context(context)['request_status'],'awaiting_object_resolution')

class DateBoundaryTests(unittest.TestCase):
 def test_month_edges_timezone_and_missing_values(self):
  from date_fields import compare_time
  rows=['2026/4/30 23:59','2026/5/1 0:00','2026/5/31 23:59','2026/6/1 0:00','','2026/2/30','1970/1/1 8:00']
  selected=[x for x in rows if compare_time(x,'date_gte','2026-05-01') and compare_time(x,'date_lt','2026-06-01')]
  self.assertEqual(selected,rows[1:3]);self.assertEqual(parse_time('2026-05-01T00:00:00+08:00'),parse_time('2026-04-30T16:00:00Z'))
 def test_threshold_sort_keeps_missing_last_and_respects_limit(self):
  from result_goal import apply_goal
  goal={**default_goal('attributes'),'kind':'sort','field':'thresholds','direction':'desc','limit':2}
  facts=[{'property':'actual_high1','status':'known','value':'34'},{'property':'actual_high2','status':'known','value':'80'},{'property':'actual_high3','status':'missing','value':''}]
  plan={'operation':'attributes','query':{'target':'points','filters':[]},'result_goal':goal}
  r=apply_goal(None,plan,{'status':'ok','attributes':facts,'records':[]})
  self.assertEqual([x['value'] for x in r['attributes']],['80','34']);self.assertTrue(r['goal_receipt']['completed'])
  goal['limit']=None;r=apply_goal(None,plan,{'status':'ok','attributes':facts,'records':[]})
  self.assertEqual(r['attributes'][-1]['status'],'missing')

class YearScopeProofTests(unittest.TestCase):
 def test_calendar_equality_respects_precision_and_rejects_invalid_period(self):
  from date_fields import compare_time
  from query_filters import validate_query
  for period in ('1970','1970-01','1970-01-01'):
   validate_query({'target':'points','filters':[{'field':'time','operator':'date_equals','value':period}]})
   self.assertEqual(compare_time('1970/1/1 8:00','date_equals',period),1)
  self.assertEqual(compare_time('1971/1/1 0:00','date_equals','1970'),0)
  self.assertEqual(compare_time('1970/1/2 0:00','date_equals','1970-01-01'),0)
  self.assertEqual(compare_time('','date_equals','1970'),0)
  for period in ('1970-13','1970-02-30','year1970'):
   with self.assertRaises(ValueError):validate_query({'target':'points','filters':[{'field':'time','operator':'date_equals','value':period}]})

 def test_year_text_and_range_equal_only_when_raw_values_prove_equivalence(self):
  from date_fields import canonical_year_filters
  class Rows:
   def __init__(self,values):self.values=values
   def rows(self,*args):return [{'time':x} for x in self.values]
  text=[('time','contains','1970')];span=[('time','date_gte','1970-01-01'),('time','date_lt','1971-01-01')]
  clean=Rows(['1970/1/1 8:00','2026/5/1 0:00',''])
  self.assertEqual(canonical_year_filters(text,clean),canonical_year_filters(span,clean))
  bad=Rows(['1970-not-a-date','2026/5/1 0:00'])
  self.assertNotEqual(canonical_year_filters(text,bad),canonical_year_filters(span,bad))
  self.assertEqual(canonical_year_filters([('name','contains','1970')],clean),[('name','contains','1970')])
 def test_native_snapshot_equivalence_never_accepts_extreme_as_list(self):
  from unittest.mock import patch
  from request_checklist import gate
  from test_business_request import patch as task_patch,delta,edit,condition
  store=Store();q='测量点名称4的情况'
  try:
   spec={'operation':'attributes','target':'points','properties':['value','unit','source','time','physical_quantity'],'result_goal':default_goal('attributes')}
   _,candidate,ids=apply_delta(delta([task_patch(None,spec,[edit('add',[],[condition('name','equals','测量点名称4')],q)],q)]),None,q)
   independent=copy.deepcopy(candidate);t=independent['tasks'][0];t['operation']='search';t['properties']=[];t['result_goal']=default_goal('search')
   with patch('request_checklist.extract',return_value=({'mode':'new','status':'ready'},{})),patch('request_checklist.compile_checklist',return_value=(compile_task(t),independent,['t1'],{})):
    r=gate(q,None,candidate,ids,'new',store);self.assertEqual(r['decision'],'accept');self.assertTrue(r['native_snapshot_projection'])
    t['result_goal']={**default_goal('search'),'kind':'extreme','field':'time','direction':'asc'}
    r=gate(q,None,candidate,ids,'new',store);self.assertEqual(r['decision'],'clarify')
  finally:store.db.close()

if __name__=='__main__':unittest.main()
