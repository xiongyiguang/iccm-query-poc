"""超限草稿仅保存用户原话；改数量后仍重新核验完整范围。"""
import copy,json,sys,unittest
from pathlib import Path
from unittest.mock import patch,MagicMock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from clarification_state import quantity_pending,resolve_quantity
from business_request import commit_state
import test_goal_state as goal_fixtures
from data import Store
import model

class QuantityPending(unittest.TestCase):
 def request(self,n=101):return goal_fixtures.GoalStateTests().sort_request_fixture(n)[1]
 def context(self,q='全部测点按测量时间降序返回前101条',previous=None):
  pending=quantity_pending(q,self.request(),previous);ctx={'pending_constraint_request':pending}
  if previous:ctx['business_request']=copy.deepcopy(previous)
  return ctx
 def reply(self,n):
  r=MagicMock();r.__enter__.return_value.read.return_value=json.dumps({'choices':[{'finish_reason':'stop','message':{'content':json.dumps({'business_request':self.request(n),'legacy':None})}}]}).encode();return r
 def test_quantity_edit_preserves_all_other_original_text(self):
  q='源系统1的全部测点按测量时间从晚到早排序，返回前101条'
  r=resolve_quantity('改为前99条，其他条件和排序不变',self.context(q));self.assertEqual(r['resolved_question'],q.replace('101条','99条'));self.assertTrue(r['valid'])
 def test_quoted_identifier_or_multiple_quantity_occurrences_are_not_a_unique_slot(self):
  for q in ('读取名为“前101条”的对象','读取名称为前101条的对象','前101条与前101条分别交付'):
   self.assertIsNone(quantity_pending(q,self.request(),None))
 def test_quantity_only_answer_cannot_discard_an_additional_source_edit(self):
  for q in ('前99条，来源改为源系统2','另查99号对象'):
   self.assertIsNone(resolve_quantity(q,self.context()))
 def test_stale_state_or_invalid_span_cannot_resume_another_request(self):
  ctx=self.context();ctx['business_request']={'version':1,'tasks':[]};self.assertIsNone(resolve_quantity('99',ctx))
  ctx=self.context();ctx['pending_constraint_request']['span']=[-1,3];self.assertIsNone(resolve_quantity('99',ctx))
  q='测量值大于101的记录返回前101条';ctx=self.context(q);start=q.index('101');ctx['pending_constraint_request']['span']=[start,start+3];self.assertIsNone(resolve_quantity('99',ctx))
 def test_constraint_draft_is_not_a_confirmed_business_identity(self):
  q='全部测点按测量时间降序返回前101条'
  with patch.dict(model.os.environ,{'DEEPSEEK_API_KEY':'synthetic','ICCM_REQUEST_ENGINE':'contract'}),patch('urllib.request.build_opener') as net:
   net.return_value.open.return_value=self.reply(101);plan=model.interpret(q,{},None);trace=copy.deepcopy(model.get_trace())
  ctx=commit_state({},trace,{'status':'clarify'},{});self.assertIn('pending_constraint_request',ctx);self.assertNotIn('business_request',ctx);self.assertNotIn('pending_business_request',ctx);self.assertNotIn('query',plan)
 def test_resumed_complete_question_still_runs_normal_gate_and_current_question_seal(self):
  ctx=self.context();q='改为前99条，其他条件和排序不变';store=Store();old=model.get_trace()
  try:
   with patch.dict(model.os.environ,{'DEEPSEEK_API_KEY':'synthetic','ICCM_REQUEST_ENGINE':'contract','ICCM_PARALLEL_CHECKLIST':'0'}),patch('urllib.request.build_opener') as net:
    declined=MagicMock();declined.__enter__.return_value.read.return_value=json.dumps({'choices':[{'finish_reason':'stop','message':{'content':json.dumps({'version':2,'handled':False})}}]}).encode()
    net.return_value.open.side_effect=[declined,self.reply(99)];plan=model.interpret(q,ctx,None,store)
   self.assertEqual(plan['result_goal']['limit'],99);self.assertEqual(model.get_trace()['constraint_resolution']['resolved_question'],'全部测点按测量时间降序返回前99条')
   with patch('request_checklist.gate',return_value={'decision':'accept','choice':'candidate'}) as gate:
    bound=model.bind_references(store,q,plan,ctx)
   self.assertEqual(gate.call_args.args[0],'全部测点按测量时间降序返回前99条')
   from request_gateway import require_verified
   require_verified(store,q,bound)
   with self.assertRaises(ValueError):require_verified(store,q,bound)
   done=commit_state({},model.get_trace(),{'status':'ok'},ctx);self.assertNotIn('pending_constraint_request',done)
  finally:store.db.close();model.TRACE.value=old
 def test_repeated_out_of_range_answer_keeps_original_draft_without_model_call(self):
  ctx=self.context();before=copy.deepcopy(ctx)
  with patch('urllib.request.build_opener') as net:
   plan=model.interpret('改为前0条，其他条件不变',ctx,None)
   net.assert_not_called()
  self.assertEqual(plan['operation'],'clarify');self.assertEqual(ctx,before);self.assertEqual(model.get_trace()['pending_constraint_request'],ctx['pending_constraint_request'])
 def test_quantity_resume_cannot_seal_a_changed_numeric_parameter(self):
  ctx=self.context();q='改为前99条，其他条件和排序不变';store=Store();old=model.get_trace()
  try:
   resolved=resolve_quantity(q,ctx);wrong={'operation':'search','entity':None,'scope':'direct','clarification':'','query':{'target':'points','filters':[]},'result_goal':goal_fixtures.GoalStateTests().sort_request_fixture(100)[0]}
   model.TRACE.value={'engine':'business_request','constraint_resolution':resolved,'validated_intent':wrong}
   with patch('model._bind_references',return_value=wrong),self.assertRaises(model.PlanInvalid):model.bind_references(store,q,wrong,ctx)
   from request_gateway import require_verified
   with self.assertRaises(ValueError):require_verified(store,q,wrong)
  finally:store.db.close();model.TRACE.value=old

if __name__=='__main__':unittest.main()
