"""扩展验证结果目标的操作契约、日期精度及十进制运算边界。"""
import copy,sys,unittest
from decimal import Decimal,getcontext
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from date_fields import canonical_year_filters
from result_goal import default_goal,validate_plan_goal,difference

class CalendarProofTests(unittest.TestCase):
 class Store:
  def rows(self,*args):return []
 def pair(self,start,end):return [('time','date_gte',start),('time','date_lt',end)]
 def test_fractional_year_bounds_never_become_calendar_year(self):
  for fraction in ('001','000001','999999'):
   bounds=self.pair('2026-01-01T00:00:00.'+fraction+'+08:00','2027-01-01T00:00:00.'+fraction+'+08:00')
   with self.subTest(fraction=fraction):self.assertEqual(canonical_year_filters(bounds,self.Store()),bounds)
 def test_timezone_aligned_year_is_equivalent(self):
  bounds=self.pair('2025-12-31T16:00:00Z','2026-12-31T16:00:00Z')
  self.assertEqual(canonical_year_filters(bounds,self.Store()),[('time','calendar_year','2026')])
 def test_utc_year_and_mismatched_upper_bound_keep_original(self):
  for bounds in (self.pair('2026-01-01T00:00:00Z','2027-01-01T00:00:00Z'),self.pair('2026-01-01','2027-01-01T00:00:00.001+08:00')):
   self.assertEqual(canonical_year_filters(bounds,self.Store()),bounds)

 def test_day_and_month_periods_match_exact_half_open_bounds(self):
  cases=[('2026-05-23','2026-05-24','calendar_day'),('2024-02-29','2024-03-01','calendar_day'),('2026-12-31','2027-01-01','calendar_day'),('2026-05','2026-06-01','calendar_month'),('2026-12','2027-01-01','calendar_month')]
  for value,end,label in cases:
   start=value+'-01' if label=='calendar_month' else value
   expected=[('time',label,value)]
   with self.subTest(value=value):
    self.assertEqual(canonical_year_filters(self.pair(start,end),self.Store()),expected)
    self.assertEqual(canonical_year_filters([('time','date_equals',value)],self.Store()),expected)
 def test_day_timezone_equivalence_preserves_business_date(self):
  self.assertEqual(canonical_year_filters(self.pair('2026-05-22T16:00:00Z','2026-05-23T16:00:00Z'),self.Store()),[('time','calendar_day','2026-05-23')])
 def test_period_fractional_and_shifted_boundaries_never_match(self):
  for bounds in (self.pair('2026-05-23T00:00:00.000001','2026-05-24T00:00:00.000001'),self.pair('2026-05-23','2026-05-24T00:00:00.001'),self.pair('2026-05-01','2026-06-01T00:00:00.001'),self.pair('2026-05-23T00:00:00Z','2026-05-24T00:00:00Z')):
   with self.subTest(bounds=bounds):self.assertEqual(canonical_year_filters(bounds,self.Store()),bounds)
 def test_exact_midnight_and_invalid_calendar_date_are_not_periods(self):
  for value in ('2026-05-23T00:00:00','2026-02-29','2026-13','9999-12-31'):
   fs=[('time','date_equals',value)]
   self.assertEqual(canonical_year_filters(fs,self.Store()),fs)
 def test_calendar_normalization_preserves_other_filters_and_input(self):
  fs=[('source','equals','源系统1')]+self.pair('2026-05-23','2026-05-24');before=copy.deepcopy(fs)
  result=canonical_year_filters(fs,self.Store());self.assertEqual(fs,before)
  self.assertEqual(result,[('source','equals','源系统1'),('time','calendar_day','2026-05-23')])

class GoalOperationTests(unittest.TestCase):
 def test_quantity_constraint_is_typed_and_valid_bounds_still_work(self):
  from result_goal import validate_goal,GoalConstraintError
  base={**default_goal('search'),'kind':'sort','field':'time','direction':'desc'}
  for limit in (0,101):
   with self.assertRaises(GoalConstraintError) as caught:validate_goal({**base,'limit':limit},'search','points')
   self.assertEqual(caught.exception.business_constraint,{'code':'sort_limit_bounds','minimum':1,'maximum':100})
  for limit in (1,100):self.assertEqual(validate_goal({**base,'limit':limit},'search','points')['limit'],limit)
 def test_wrong_quantity_type_is_not_a_business_constraint(self):
  from result_goal import validate_goal
  base={**default_goal('search'),'kind':'sort','field':'time','direction':'desc'}
  for limit in (True,'101',101.0,[]):
   with self.assertRaises(ValueError) as caught:validate_goal({**base,'limit':limit},'search','points')
   self.assertFalse(hasattr(caught.exception,'business_constraint'))
 def test_malformed_goal_enumeration_is_validation_error(self):
  from result_goal import validate_goal
  for value in ([],{},None,1):
   with self.subTest(value=value),self.assertRaises(ValueError):validate_goal({**default_goal('search'),'kind':value},'search','points')
 def plan(self,operation,kind,field=None,**kwargs):
  goal={**default_goal(operation),'kind':kind,'field':field,**kwargs}
  return {'operation':operation,'entity':None,'query':{'target':'points','filters':[]},'result_goal':goal}
 def test_record_computations_cannot_run_on_attribute_projection(self):
  for kind in ('sort','extreme'):
   for field in ('time','value'):
    p=self.plan('attributes',kind,field,direction='asc')
    with self.subTest(kind=kind,field=field),self.assertRaisesRegex(ValueError,'记录|search'):validate_plan_goal(p)
 def test_difference_requires_record_query(self):
  p=self.plan('attributes','difference','value',basis='raw_numbers',operands=[{'field':'name','value':'A'},{'field':'name','value':'B'}])
  with self.assertRaisesRegex(ValueError,'记录|search'):validate_plan_goal(p)
 def test_record_and_threshold_paths_stay_available(self):
  for kind in ('sort','extreme'):
   for field in ('time','value'):validate_plan_goal(self.plan('search',kind,field,direction='desc'))
  validate_plan_goal(self.plan('attributes','sort','thresholds',direction='asc'))
  with self.assertRaises(ValueError):validate_plan_goal(self.plan('search','sort','thresholds',direction='asc'))
 def test_pending_clarification_keeps_unexecuted_goal(self):
  validate_plan_goal(self.plan('clarify','extreme','time',direction='asc'))

class ExactDifferenceTests(unittest.TestCase):
 class Store:
  def __init__(self,a,b):self.values={'A':a,'B':b}
  def filtered(self,intent):
   name=intent['query']['filters'][-1]['value']
   return {'records':[{'value':self.values[name],'name':name,'unit':'','time':'2026-01-01','evidence':{'file':'synthetic','line':1,'fields':{}}}]}
 def run_difference(self,a,b,direction=None):
  goal={**default_goal('search'),'kind':'difference','field':'value','direction':direction,'basis':'raw_numbers','operands':[{'field':'name','value':'A'},{'field':'name','value':'B'}]}
  return difference(self.Store(a,b),{'operation':'search','query':{'target':'points','filters':[]}},goal)
 def test_large_minus_small_preserves_all_digits(self):
  before=getcontext().prec
  r=self.run_difference('1e30','1');self.assertEqual(Decimal(r['metrics'][0]['value']),Decimal('9'*30));self.assertEqual(getcontext().prec,before)
 def test_extreme_allowed_exponent_gap_is_exact(self):
  expected=Decimal('9'*200+'.'+'9'*200)
  r=self.run_difference('1e200','1e-200');self.assertEqual(Decimal(r['metrics'][0]['value']),expected)
 def test_zero_negative_reverse_and_missing_values(self):
  for a,b,expected in [('0','0','0'),('-0.001','1.999','-2.000'),('1','1e30','-'+'9'*30)]:
   with self.subTest(a=a,b=b):self.assertEqual(Decimal(self.run_difference(a,b)['metrics'][0]['value']),Decimal(expected))
  for bad in ('','NaN','Infinity'):self.assertEqual(self.run_difference(bad,'1')['status'],'data_insufficient')
 def test_absolute_difference_is_explicit_and_symmetric(self):
  for a,b in [('1','2'),('2','1')]:
   r=self.run_difference(a,b,'absolute');self.assertEqual(r['metrics'][0]['value'],'1');self.assertEqual(r['goal_receipt']['goal']['direction'],'absolute')
  self.assertEqual(self.run_difference('1','2')['metrics'][0]['value'],'-1')

class CandidateContinuationTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  from data import Store
  cls.store=Store()
 @classmethod
 def tearDownClass(cls):cls.store.db.close()
 def state(self,field='code',value='2ABC109MT',operation='attributes'):
  from test_business_request import patch,delta,edit,condition
  from business_request import apply_delta
  q=value+'的测量值';props=['value'] if operation=='attributes' else []
  return apply_delta(delta([patch(None,{'operation':operation,'target':'points','properties':props,'result_goal':default_goal(operation)},[edit('add',[],[condition(field,'equals',value)],q)],q)]),None,q)[1]
 def test_candidate_equivalence_does_not_certify_exact_match(self):
  from request_checklist import reconcile
  a=self.state();b=self.state('identity');comparison=reconcile(a,['t1'],b,['t1'],self.store)
  self.assertTrue(comparison['matches']);self.assertEqual(comparison['candidate'][0]['filters'][0][0],'unresolved_identity_suggestion')
  self.assertFalse(reconcile(self.state('name'),['t1'],b,['t1'],self.store)['matches'])
  self.assertFalse(reconcile(self.state('code',operation='search'),['t1'],self.state('identity',operation='search'),['t1'],self.store)['matches'])
 def test_empty_candidate_sets_cannot_make_fields_equivalent(self):
  from request_checklist import reconcile
  self.assertFalse(reconcile(self.state('code','NON_EXISTING_9999'),['t1'],self.state('identity','NON_EXISTING_9999'),['t1'],self.store)['matches'])
 def test_selection_preserves_goal_and_filters_and_rejects_unrelated(self):
  from clarification_state import resolve_answer
  context={'pending_business_request':self.state(),'outcome':{'kind':'ambiguous'}};before=copy.deepcopy(context)
  selection={'tree':'pbs','code':'XJ2ABC001MO.TMP.2ABC109MT.BBe'}
  plan,state,ids,proof=resolve_answer('继续',context,selection,self.store)
  self.assertEqual(plan['query']['filters'],[{'field':'code','operator':'equals','value':selection['code']}]);self.assertEqual(plan['properties'],['value']);self.assertEqual(context,before)
  self.assertEqual(state['tasks'][0]['result_goal'],before['pending_business_request']['tasks'][0]['result_goal'])
  for q,s in [('继续，但改问阈值',selection),('继续',{'tree':'pbs','code':'XJ3ABC002MO.TMP.3ABC112MT.U_Win_H1'})]:self.assertIsNone(resolve_answer(q,context,s,self.store))
 def test_selected_identity_stays_grounded_on_later_short_followup(self):
  from clarification_state import resolve_answer
  from business_request import ground_identifiers
  context={'pending_business_request':self.state(),'outcome':{'kind':'ambiguous'}}
  selection={'tree':'pbs','code':'XJ2ABC001MO.TMP.2ABC109MT.BBe'}
  _,state,ids,_=resolve_answer('继续',context,selection,self.store)
  grounded=ground_identifiers(self.store,state,ids)
  self.assertEqual(grounded['tasks'][0]['filters'][0]['value'],selection['code'])
 def test_invalid_selection_source_cannot_ground_literal(self):
  from business_request import ground_identifiers,RequestInvalid
  state=self.state('code','XJ2ABC001MO.TMP.2ABC109MT.BBe');f=state['tasks'][0]['filters'][0]
  f['source']={'kind':'user_selection','quote':'继续','selection':{'tree':'config','code':f['value']}}
  with self.assertRaises(RequestInvalid):ground_identifiers(self.store,state,['t1'])
 def test_selection_rechecked_against_current_context_and_one_use_seal(self):
  import model
  from request_gateway import require_verified
  context={'pending_business_request':self.state(),'outcome':{'kind':'ambiguous'}};s={'tree':'pbs','code':'XJ2ABC001MO.TMP.2ABC109MT.BBe'}
  plan=model.interpret('继续',context,s,store=self.store);bound=model.bind_references(self.store,'继续',plan,context);require_verified(self.store,'继续',bound)
  with self.assertRaises(ValueError):require_verified(self.store,'继续',bound)
  plan=model.interpret('继续',context,s,store=self.store);changed=copy.deepcopy(context);changed['pending_business_request']['tasks'][0]['filters'][0]['value']='NON_EXISTING_9999'
  with self.assertRaises(model.PlanInvalid):model.bind_references(self.store,'继续',plan,changed)

if __name__=='__main__':unittest.main()
