"""只有根对象完整一致时，才能确认独立提取器缺少的对象域。"""
import copy,sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from business_request import apply_delta,RequestAmbiguous,resolve_delta_sources
from object_scope import reviewable_domain_draft
from request_checklist import gate
from semantic_review import task_summary
from data import Store
from test_object_scope import delta
from test_query_review import edits
import model,query_review,test_filters

POINT='XJ3ABC002MO.TMP.3ABC112MT.U_Win_H1'

def inputs(value=POINT,target='points'):
 q='查看'+value+'的情况'
 d=delta(q,name=value,purpose='data',scope='none',target=target)
 d['tasks'][0]['set']['properties']=['value','unit'] if target=='points' else ['name','code']
 p,s,ids=apply_delta(d,None,q)
 try:apply_delta(delta(q,name=value,purpose='introduction'),None,q)
 except RequestAmbiguous as error:return q,p,s,ids,error,d
 raise AssertionError('Expected domain draft')

def checked(store):
 q,p,s,ids,error,d=inputs()
 with patch('request_checklist.extract',return_value=({'status':'ready','mode':'new'},{})),patch('request_checklist.compile_checklist',side_effect=error):
  result=gate(q,None,s,ids,'new',store)
 return q,p,s,ids,error,d,result

class ObjectReviewTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.store=Store()
 @classmethod
 def tearDownClass(cls):cls.store.db.close()
 def test_specific_domains_all_use_same_confirmable_contract(self):
  for target,value in [('points',POINT),('config','MOHB'),('equipment_class','MOHB'),('pbs','XJ3ABC002RR&RRGA02.Zaf.IDS'),('part_class','GATAA01')]:
   q,p,s,ids,e,d=inputs(value,target)
   self.assertTrue(reviewable_domain_draft(s,ids,e.state,ids,self.store),target)
 def test_full_identifier_and_prerequisites_cannot_be_waived(self):
  for change in ('root','name_code','extra_filter','unit','candidate_unit','scope','reason','unverified','unknown_target','extra_task','pending_id','ids'):
   q,p,s,ids,e,d=inputs();bad=copy.deepcopy(e.state);candidate=copy.deepcopy(s);other_ids=list(ids)
   a=bad['tasks'][0];b=candidate['tasks'][0]
   if change=='root':a['filters'][0]['value']=POINT[:-1]
   if change=='name_code':a['filters'][0]['field']='name';b['filters'][0]['field']='code'
   if change=='extra_filter':b['filters'].append({'id':'f2','field':'name','operator':'contains','value':'1','source':{}})
   if change=='unit':a['unit']={'state':'ambiguous','value':''}
   if change=='candidate_unit':b['unit']={'state':'specified','value':'℃'}
   if change=='scope':a['scope']='all'
   if change=='reason':bad['pending_reason']='unit'
   if change=='unverified':a['sources']['unverified_subject_scope']={'claim':{'value':'explicit'}}
   if change=='unknown_target':b['target']='objects'
   if change=='extra_task':bad['tasks'].append({**copy.deepcopy(a),'id':'t2'})
   if change=='pending_id':bad['pending_tasks']=['t2']
   if change=='ids':other_ids=['t2']
   with self.subTest(change=change):self.assertFalse(reviewable_domain_draft(candidate,ids,bad,other_ids,self.store))
 def test_known_name_and_code_cannot_be_reinterpreted_as_each_other(self):
  q,p,s,ids,e,d=inputs()
  for left,right,want in [('code','identity',True),('identity','name',True),('name','code',False),('code','name',False)]:
   s['tasks'][0]['filters'][0]['field']=left;e.state['tasks'][0]['filters'][0]['field']=right
   self.assertEqual(reviewable_domain_draft(s,ids,e.state,ids,self.store),want)
 def test_other_future_tasks_must_match_and_inputs_stay_immutable(self):
  q,p,s,ids,e,d=inputs();other=copy.deepcopy(s['tasks'][0]);other['id']='t2'
  s['tasks'].append(copy.deepcopy(other));e.state['tasks'].append(copy.deepcopy(other))
  saved=copy.deepcopy((s,e.state))
  self.assertTrue(reviewable_domain_draft(s,ids,e.state,ids,self.store));self.assertEqual((s,e.state),saved)
  e.state['tasks'][1]['properties']=['unit'];self.assertFalse(reviewable_domain_draft(s,ids,e.state,ids,self.store))
 def test_gate_requires_explicit_review_and_shows_missing_domain(self):
  q,p,s,ids,e,d,result=checked(self.store)
  self.assertEqual(result['decision'],'clarify');self.assertIn('pending_state',result)
  self.assertNotIn('plan',result);self.assertNotIn('needs_review',result)
  self.assertIn('对象域待明确',result['semantic_review']['alternative'][0])
 def test_mode_disagreement_does_not_overwrite_future_state(self):
  q,p,s,ids,e,d=inputs()
  with patch('request_checklist.extract',return_value=({'status':'ready','mode':'update'},{})),patch('request_checklist.compile_checklist',side_effect=e):
   result=gate(q,None,s,ids,'new',self.store)
  self.assertEqual(result['decision'],'clarify');self.assertNotIn('needs_review',result)
 def test_edited_projection_preserves_confirmed_state_without_another_model(self):
  q,p,s,ids,e,d,result=checked(self.store);session={'context':{}}
  t={'business_request_state':s,'changed_tasks':ids,'business_request_delta':d,'checklist_review':result}
  preview=query_review.issue(session,'s','v',q,p,t);change=edits(preview);change[0]['values']['properties']=['unit']
  with patch.object(model,'interpret',side_effect=AssertionError('no re-interpretation')):
   actual,trace,_=query_review.confirm(session,'s','v',preview['review']['id'],change)
  self.assertEqual(actual['properties'],['unit']);state=trace['business_request_state']
  self.assertNotIn('pending_reason',state);self.assertEqual(state['tasks'][0]['target'],'points')
  self.assertTrue(trace['semantic_review_resolution']['candidate_edited'])

class ObjectReviewHttpTests(unittest.TestCase):
 setUpClass=classmethod(test_filters.FilterHttpTests.setUpClass.__func__)
 tearDownClass=classmethod(test_filters.FilterHttpTests.tearDownClass.__func__)
 request=test_filters.FilterHttpTests.request
 def test_no_early_execution_and_no_wrong_domain_draft_after_confirm(self):
  import app
  q,p,s,ids,e,d,result=checked(app.STORE)
  def interpret(*args,**kwargs):
   model.TRACE.value={'engine':'business_request','business_request_state':copy.deepcopy(s),'changed_tasks':ids,'business_request_delta':resolve_delta_sources(d,q)}
   return copy.deepcopy(p)
  with patch.object(app,'interpret',side_effect=interpret),patch('request_checklist.gate',return_value=result),patch.object(app.STORE,'execute',wraps=app.STORE.execute) as execute:
   r=self.request('/api/query',{'session':'object-review-http','question':q,'trace':True})
  self.assertEqual(r['status'],'clarify');self.assertNotIn('review',r)
  self.assertEqual([x.args[0]['operation'] for x in execute.call_args_list],['clarify'])
  self.assertEqual(r['context']['pending_business_request']['pending_reason'],'domain')
  self.assertNotIn('business_request',r['context'])


def serve_fixture():
 import app,request_checklist
 app.STORE=app.IMPORTS.load();q,p,s,ids,e,d,result=checked(app.STORE)
 def interpret(*args,**kwargs):
  model.TRACE.value={'engine':'business_request','business_request_state':copy.deepcopy(s),'changed_tasks':ids,'business_request_delta':resolve_delta_sources(d,q)}
  return copy.deepcopy(p)
 app.interpret=interpret;request_checklist.gate=lambda *args,**kwargs:copy.deepcopy(result)
 print('Object-domain review fixture on 8771; model boundary fixed',flush=True)
 app.ThreadingHTTPServer(('127.0.0.1',8771),app.Handler).serve_forever()

if __name__=='__main__':
 if '--serve' in sys.argv:serve_fixture()
 else:unittest.main()
