"""分歧澄清契约；--serve 启动确定性界面测试数据，不调用真实模型。"""
import copy,sys,unittest,json
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from business_request import apply_delta,compile_selected
from request_checklist import gate
from semantic_review import describe_disagreement
from data import Store
import query_review,model
from test_business_request import delta as raw_delta,patch as task_patch,edit,condition
from test_object_scope import delta
from test_query_review import edits
import test_filters

def states():
 q='MOHB 那个设备是什么？'
 a=apply_delta(delta(q,name='MOHB',purpose='identity',scope='unspecified',target='objects'),None,q)
 oldq='构型MOHB01是什么对象？'
 b=apply_delta(delta(oldq,name='MOHB01',purpose='identity',scope='explicit',target='config'),None,oldq)
 return q,a,b
def disagreement(store):
 q,a,b=states()
 with patch('request_checklist.extract',return_value=({'status':'ready','mode':'new'},{})),patch('request_checklist.compile_checklist',return_value=(*b,{})),patch('request_checklist.adjudicate',side_effect=AssertionError('free vote forbidden')):
  checked=gate(q,None,a[1],a[2],'new',store)
 return q,a,b,checked

class SemanticReviewTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.store=Store()
 @classmethod
 def tearDownClass(cls):cls.store.db.close()
 def test_correct_literal_is_not_overridden_by_wrong_prefix(self):
  q,a,b,checked=disagreement(self.store)
  self.assertEqual(checked['decision'],'clarify');self.assertEqual(checked['choice'],'clarify');self.assertEqual(checked['reason'].count('？'),1)
  self.assertNotIn('plan',checked);self.assertNotIn('adjudication',checked)
  self.assertIn('「MOHB」',checked['semantic_review']['current'][0])
  self.assertIn('「MOHB01」',checked['semantic_review']['alternative'][0])
  self.assertEqual(a[1]['tasks'][0]['filters'][0]['value'],'MOHB')
 def test_preview_deep_copy_and_confirmation_records_resolution(self):
  q,a,b,checked=disagreement(self.store);session={'context':{}}
  trace={'checklist_review':checked,'business_request_state':a[1],'changed_tasks':a[2],'business_request_delta':{'mode':'new'}}
  preview=query_review.issue(session,'test','v',q,a[0],trace)
  preview['review']['semantic_review']['alternative'][0]='changed UI copy'
  self.assertIn('MOHB01',session['pending_review']['trace']['checklist_review']['semantic_review']['alternative'][0])
  changes=edits(preview);changes[0]['values']['query']['target']='equipment_class'
  with patch.object(model,'interpret',side_effect=AssertionError('must not reinterpret')):
   p,t,_=query_review.confirm(session,'test','v',preview['review']['id'],changes)
  self.assertEqual(p['query']['target'],'equipment_class')
  self.assertEqual(t['semantic_review_resolution'],{'kind':'user_confirmation','candidate_edited':True})
  self.assertEqual(t['business_request_state']['tasks'][0]['filters'][0]['value'],'MOHB')
 def test_unchanged_confirmation_keeps_original_not_alternative(self):
  q,a,b,checked=disagreement(self.store);session={'context':{}}
  trace={'checklist_review':checked,'business_request_state':a[1],'changed_tasks':a[2],'business_request_delta':{'mode':'new'}}
  preview=query_review.issue(session,'test','v',q,a[0],trace)
  p,t,_=query_review.confirm(session,'test','v',preview['review']['id'],edits(preview))
  self.assertEqual(p,a[0]);self.assertFalse(t['semantic_review_resolution']['candidate_edited'])
 def test_simple_query_requires_review_only_when_disputed(self):
  p={'operation':'search','entity':None,'scope':'direct','clarification':'','query':{'target':'parts','filters':[condition('name','contains','1')]}}
  self.assertFalse(query_review.required(p,{}))
  self.assertTrue(query_review.required(p,{}, {'checklist_review':{'needs_review':True}}))
 def test_summary_exposes_endpoint_projection_and_future_state(self):
  q,a,b,_=disagreement(self.store);x=copy.deepcopy(a[1]['tasks'][0]);x.update(operation='search',target='points',properties=[],filters=[condition('value','lt','80')])
  y=copy.deepcopy(x);y['filters'][0]['operator']='lte'
  d=describe_disagreement([x],[y],'update','new',False)
  self.assertNotEqual(d['current'],d['alternative']);self.assertIn('后续对话',d['state_warning'])
 def test_nonquery_disagreement_cannot_create_unconfirmable_query(self):
  t={'id':'t1','operation':'explain','target':None,'scope':'direct','properties':[],'filters':[],'sources':{},'unit':{'state':'none','value':''},'topics':['counts']}
  a={'version':1,'revision':1,'next_filter_id':1,'tasks':[t]}
  b=copy.deepcopy(a);b['tasks'][0]['topics']=['relationships']
  with patch('request_checklist.extract',return_value=({'status':'ready','mode':'new'},{})),patch('request_checklist.compile_checklist',return_value=({'operation':'explain'},b,['t1'],{})),patch('request_checklist.adjudicate',side_effect=AssertionError('free vote forbidden')):
   checked=gate('说明',None,a,['t1'],'new',self.store)
  self.assertEqual(checked['decision'],'clarify');self.assertNotIn('needs_review',checked)

class SemanticReviewHttpTests(unittest.TestCase):
 setUpClass=classmethod(test_filters.FilterHttpTests.setUpClass.__func__)
 tearDownClass=classmethod(test_filters.FilterHttpTests.tearDownClass.__func__)
 request=test_filters.FilterHttpTests.request
 def test_simple_disagreement_must_not_execute_until_confirmation(self):
  import app
  q='名称包含1的部件';d=raw_delta([task_patch(None,{'operation':'search','target':'parts'},[edit('add',[],[condition('name','contains','1')],q)],q)])
  p,state,changed=apply_delta(d,None,q)
  notice={'title':'分歧','message':'核对','current':['名称包含1'],'alternative':['名称包含2'],'state_warning':''}
  checked={'decision':'accept','choice':'candidate','needs_review':True,'semantic_review':notice}
  def interpret(*args):
   model.TRACE.value={'engine':'business_request','business_request_state':state,'changed_tasks':changed,'business_request_delta':d}
   return copy.deepcopy(p)
  with patch.object(app,'interpret',side_effect=interpret),patch('request_checklist.gate',return_value=checked),patch.object(app.STORE,'execute',wraps=app.STORE.execute) as execute:
   r=self.request('/api/query',{'session':'disputed-http','question':q,'trace':True})
  self.assertEqual(r['status'],'clarify');self.assertNotIn('review',r)
  self.assertEqual([x.args[0]['operation'] for x in execute.call_args_list],['clarify'])
  self.assertNotIn('business_request',r['context'])


def serve_fixture():
 # 模型边界是确定性模拟；HTTP、确认、状态和数据使用真实实现。
 import app,request_checklist
 app.STORE=app.IMPORTS.load()
 q,a,b,checked=disagreement(app.STORE)
 def interpret(question,context,selection):
  model.TRACE.value={'engine':'business_request','business_request_state':copy.deepcopy(a[1]),'changed_tasks':a[2],
   'business_request_delta':{'mode':'new','tasks':[{'quote':q}]}}
  return copy.deepcopy(a[0])
 app.interpret=interpret
 request_checklist.gate=lambda *args,**kwargs:copy.deepcopy(checked)
 model.adjudicate=lambda *args,**kwargs:(_ for _ in ()).throw(AssertionError('not a real model test'))
 print('Deterministic semantic-review UI fixture on 8771; no real model calls',flush=True)
 app.ThreadingHTTPServer(('127.0.0.1',8771),app.Handler).serve_forever()
if __name__=='__main__':
 if '--serve' in sys.argv:serve_fixture()
 else:unittest.main()
