import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from task_scope import validate,compare,guard
from unittest.mock import patch
from business_request import RequestInvalid
class ScopeTests(unittest.TestCase):
 def task(self,kind,props=[]):return {'kind':kind,'properties':props,'spans':[1]}
 def test_diagnosis_never_authorizes_threshold_query(self):
  expected={'tasks':[self.task('unsupported')]}
  self.assertFalse(compare(expected,{'operation':'threshold'})['matches'])
  self.assertTrue(compare(expected,{'operation':'explain'})['matches'])
 def test_explicit_read_and_explanation_both_required(self):
  wanted={'tasks':[self.task('read',['actual_high2']),self.task('explain')]}
  plan={'operation':'batch','tasks':[{'intent':{'operation':'threshold','thresholds':['actual_high2']}},{'intent':{'operation':'explain'}}]}
  self.assertTrue(compare(wanted,plan)['matches'])
  plan['tasks'].pop()
  self.assertFalse(compare(wanted,plan)['matches'])
 def test_duplicates_not_silently_merged_or_added(self):
  wanted={'tasks':[self.task('read',['value']),self.task('read',['value'])]}
  plan={'operation':'attributes','properties':['value']}
  self.assertFalse(compare(wanted,plan)['matches'])
  self.assertTrue(compare(wanted,{'operation':'batch','tasks':[{'intent':plan},{'intent':plan}]})['matches'])
 def test_projection_must_match_exactly(self):
  wanted={'tasks':[self.task('read',['time'])]}
  self.assertFalse(compare(wanted,{'operation':'attributes','properties':['value','time']})['matches'])
 def test_contract_rejects_fabricated_sources_and_properties(self):
  for task in [dict(kind='read',properties=['SQL'],spans=[1]),dict(kind='read',properties=['value'],spans=[999]),dict(kind='unsupported',properties=['value'],spans=[1]),dict(kind='read',properties=[],spans=[1])]:
   with self.assertRaises(RequestInvalid):validate({'tasks':[task]},'真实原话。')
 def test_task_order_is_not_semantics(self):
  wanted={'tasks':[self.task('parent'),self.task('read',['value'])]}
  plan={'operation':'batch','tasks':[{'intent':{'operation':'attributes','properties':['value']}},{'intent':{'operation':'parent'}}]}
  self.assertTrue(compare(wanted,plan)['matches'])
 def test_guard_rejects_real_old_plan_without_mutation(self):
  import copy
  p={'operation':'batch','tasks':[{'intent':{'operation':'threshold'}},{'intent':{'operation':'explain'}}]};old=copy.deepcopy(p);trace={}
  with patch.dict('os.environ',{'ICCM_TASK_SCOPE_REVIEW':'1'}),patch('task_scope.extract',return_value=({'tasks':[self.task('unsupported')]},{})):
   out=guard('诊断设备',p,trace)
  self.assertEqual(out['operation'],'conversation');self.assertEqual(p,old);self.assertEqual(trace['task_scope']['status'],'rejected')
 def test_guard_preserves_explicit_relation_and_explanation(self):
  p={'operation':'batch','tasks':[{'intent':{'operation':'parent'}},{'intent':{'operation':'explain'}}]};trace={}
  with patch.dict('os.environ',{'ICCM_TASK_SCOPE_REVIEW':'1'}),patch('task_scope.extract',return_value=({'tasks':[self.task('parent'),self.task('explain')]},{})):
   self.assertEqual(guard('读上级并解释',p,trace),p)
  self.assertEqual(trace['task_scope']['status'],'accepted')
 def test_scope_failure_cannot_fall_through_to_query(self):
  with patch.dict('os.environ',{'ICCM_TASK_SCOPE_REVIEW':'1'}),patch('task_scope.extract',side_effect=TimeoutError('test')):
   with self.assertRaises(RequestInvalid):guard('阈值',{'operation':'threshold'}, {})
 def test_final_verification_receipt_is_for_guarded_plan(self):
  import model
  from request_gateway import require_verified
  from types import SimpleNamespace
  store=SimpleNamespace(version='v1');p={'operation':'threshold','entity':None,'scope':'direct','clarification':''}
  model.TRACE.value={'engine':'legacy'}
  with patch.dict('os.environ',{'ICCM_TASK_SCOPE_REVIEW':'1'}),patch.object(model,'_bind_references',return_value=p),patch('task_scope.extract',return_value=({'tasks':[self.task('unsupported')]},{})):
   guarded=model.bind_references(store,'诊断',p)
  with self.assertRaises(RequestInvalid):require_verified(store,'诊断',p)
  require_verified(store,'诊断',guarded)
if __name__=='__main__':unittest.main()
