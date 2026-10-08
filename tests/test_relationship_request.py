"""集合、深度和根对象在确认与执行过程中始终分别维护。"""
import copy,json,sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from business_request import apply_delta,compile_task,RequestInvalid,RequestAmbiguous,extraction_context
from request_checklist import compile_checklist,canonical_tasks,prior_view
from importer import Imports
from data import BusinessOutcome,QueryError
import model,query_review
import test_parts_request as old

def seed(value='MOHB01',scope='all',population='all_objects',field='identity'):
 d=old.delta(value,scope,field);d['version']=9
 d['tasks'][0]['set'].update(operation='descendants',population=population)
 return apply_delta(d,None,'构型'+value+'的下级对象')

def update(state,fields=None,edits=None,q='更新对象范围'):
 d=old.delta();d['version']=9;d['mode']='update'
 d['tasks'][0].update(base='t1',set=fields or {},filters=edits or [])
 return apply_delta(d,state,q)

def checklist(value='MOHB01',scope='all',population='all_objects'):
 return {'version':12,'roles':{'background':[],'output':[1],'control':[]},'status':'ready','mode':'new','clarification':'','tasks':[{
 'id':None,'action':'request','request_spans':[1],'spans':[1],'kind':'descendants','purpose':'data','subject_scope':'none',
 'target':'config','scope':scope,'population':population,'properties':[],'unit':{'state':'none','value':''},
 'conditions':[{'field':'identity','operator':'equals','value':value,'spans':[1],'reference':None}]}]}

class RelationshipTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.store=Imports().load()
  cls.raw=next(d['rows'] for d in cls.store.dataset if d['kind']=='config')
 @classmethod
 def tearDownClass(cls):cls.store.db.close()
 def test_graph_populations_and_depths_against_independent_raw_parent_graph(self):
  # 预期行只依据导入 CSV 的父引用计算，不复用查询辅助函数。
  for root in ('MOHB01','RRGA31','KOHA30#20-55'):
   for scope in ('direct','all'):
    codes={r['对象代码'] for r in self.raw if r['父对象代码']==root}
    if scope=='all':
     while True:
      expanded=codes|{r['对象代码'] for r in self.raw if r['父对象代码'] in codes}
      if expanded==codes:break
      codes=expanded
    for population in ('all_objects','parts'):
     with self.subTest(root=root,scope=scope,population=population):
      expected={r['对象代码']:r for r in self.raw if r['对象代码'] in codes and (population=='all_objects' or r['对象层级描述']=='部件')}
      p,_,_=seed(root,scope,population);model.validate(p);result=self.store.execute(p)
      actual={r['code']:r['evidence']['fields'] for r in result['records']}
      self.assertEqual(len(result['records']),len(expected))
      self.assertEqual(actual,expected)
 def test_population_only_changes_set_and_keeps_stable_root(self):
  p,s,ids=seed();original=copy.deepcopy(s);p2,s2,ids2=update(s,{'population':'parts'})
  self.assertEqual(s,original);self.assertEqual(s2['tasks'][0]['filters'],s['tasks'][0]['filters'])
  self.assertEqual(s2['tasks'][0]['scope'],'all')
  self.assertEqual(len(self.store.execute(p)['records']),222);self.assertEqual(len(self.store.execute(p2)['records']),221)
  self.assertNotEqual(canonical_tasks(s,ids,self.store),canonical_tasks(s2,ids2,self.store))
 def test_depth_and_root_edits_preserve_population(self):
  _,s,_=seed(population='parts');_,s2,_=update(s,{'scope':'direct'})
  self.assertEqual(s2['tasks'][0]['population'],'parts');self.assertEqual(s2['tasks'][0]['filters'],s['tasks'][0]['filters'])
  f=s2['tasks'][0]['filters'][0]
  p3,s3,_=update(s2,edits=[{'action':'replace','ids':[f['id']],'spans':[1],'conditions':[{'field':'identity','operator':'equals','value':'RRGA31'}]}],q='根换为构型RRGA31')
  self.assertEqual(s3['tasks'][0]['scope'],'direct');self.assertEqual(s3['tasks'][0]['population'],'parts')
  self.assertEqual(self.store.execute(p3)['entity']['code'],'RRGA31')
 def test_unresolved_slots_preserve_draft_and_complete_without_root_reentry(self):
  for scope,pop in [('all','unspecified'),('unspecified','parts'),('unspecified','unspecified')]:
   with self.subTest(scope=scope,pop=pop):
    with self.assertRaises(RequestAmbiguous) as caught:seed(scope=scope,population=pop)
    draft=caught.exception.state;self.assertEqual(draft['pending_reason'],'relationship')
    self.assertEqual(extraction_context({'pending_business_request':draft})['request_status'],'awaiting_relationship')
    with self.assertRaises(RequestAmbiguous):compile_task(draft['tasks'][0])
    p,state,_=update(draft,{'scope':'all','population':'all_objects'})
    self.assertNotIn('pending_reason',state);self.assertEqual(state['tasks'][0]['filters'],draft['tasks'][0]['filters'])
    self.assertEqual(len(self.store.execute(p)['records']),222)
 def test_independent_full_contract_and_directory_carry_population(self):
  q='构型MOHB01的所有下级对象';a=seed();b=compile_checklist(checklist(),None,q,self.store)
  self.assertEqual(a[0],b[0]);self.assertEqual(canonical_tasks(a[1],a[2],self.store),canonical_tasks(b[1],b[2],self.store))
  self.assertEqual(prior_view(a[1])[0]['population'],'all_objects')
  self.assertEqual(extraction_context({'business_request':a[1]})['task_directory'][0]['population'],'all_objects')
 def test_review_population_edit_is_compiled_and_persisted_without_model(self):
  for before,after in [('parts','config'),('all_objects','parts')]:
   p,s,ids=seed(population=before);session={'context':{}}
   trace={'business_request_state':s,'changed_tasks':ids,'business_request_delta':{'mode':'new'}}
   self.assertTrue(query_review.required(p,{},trace))
   preview=query_review.issue(session,'sid','v','构型MOHB01下级',p,trace);edits=old.edits(preview)
   self.assertTrue(preview['review']['tasks'][0]['fixed_population'])
   edits[0]['values']['query']['target']=after
   with patch.object(model,'interpret',side_effect=AssertionError('no new interpretation')):
    result,checked,_=query_review.confirm(session,'sid','v',preview['review']['id'],edits)
   want='parts' if after=='parts' else 'all_objects';task=checked['business_request_state']['tasks'][0]
   self.assertEqual(task['population'],want);self.assertEqual(task['sources']['population']['kind'],'user_confirmation')
   self.assertEqual(result,compile_task(task));self.assertEqual(len(self.store.execute(result)['records']),221 if want=='parts' else 222)
   _,continued,_=update(checked['business_request_state'],{'scope':'direct'})
   self.assertEqual(continued['tasks'][0]['population'],want)
 def test_review_rejects_hidden_filters_other_targets_and_roots(self):
  for change in ('filter','target','root','scope'):
   p,s,ids=seed();session={'context':{}};trace={'business_request_state':s,'changed_tasks':ids}
   preview=query_review.issue(session,'sid','v','构型MOHB01下级',p,trace);edits=old.edits(preview);v=edits[0]['values']
   if change=='filter':v['query']['filters']=[{'field':'name','operator':'contains','value':'1'}]
   if change=='target':v['query']['target']='points'
   if change=='root':v['entity']['tree']='pbs'
   if change=='scope':v['scope']='unspecified'
   with self.subTest(change=change),self.assertRaises((QueryError,RequestInvalid)):query_review.confirm(session,'sid','v',preview['review']['id'],edits)
   self.assertIn('pending_review',session)
 def test_not_found_is_not_empty_and_explicit_name_never_falls_back(self):
  for field,value in [('identity','UNKNOWN_ROOT_574269'),('name','MOHB01')]:
   p,_,_=seed(value=value,field=field)
   with self.assertRaises(BusinessOutcome) as caught:self.store.execute(p)
   self.assertEqual(caught.exception.status,'not_found')
  p,_,_=seed(value='KOHA30#20-55');self.assertEqual(self.store.execute(p)['records'],[])
 def test_illegal_shape_and_ordinary_transition_do_not_leak_constraints(self):
  _,s,_=seed()
  for changes in ({'population':'equipment'},{'target':'pbs'},{'properties':['name']}):
   with self.subTest(changes=changes),self.assertRaises(RequestInvalid):update(s,changes)
  with self.assertRaises(RequestInvalid):update(s,{'operation':'search'})
  _,parts,_=old.seed();p,new,_=update(parts,{'operation':'descendants','population':'all_objects'})
  self.assertEqual(new['tasks'][0]['filters'],parts['tasks'][0]['filters']);self.assertEqual(p['operation'],'search')
 def test_other_task_is_not_changed_by_population_update(self):
  _,s,_=seed();s['tasks'].append(copy.deepcopy(s['tasks'][0]));s['tasks'][1]['id']='t2'
  other=copy.deepcopy(s['tasks'][1]);_,new,_=update(s,{'population':'parts'})
  self.assertEqual(new['tasks'][1],other)
 def test_only_unresolved_relationship_slots_can_be_explicitly_confirmed(self):
  from relationship_request import reviewable_draft
  from request_checklist import gate
  from semantic_review import task_summary
  p,s,ids=seed()
  for scope,pop in [('unspecified','all_objects'),('all','unspecified'),('unspecified','unspecified')]:
   with self.assertRaises(RequestAmbiguous) as caught:seed(scope=scope,population=pop)
   error=caught.exception;draft=error.state
   self.assertTrue(reviewable_draft(s,ids,draft,ids,self.store))
   self.assertIn('待明确',task_summary(draft['tasks'][0],1))
   with patch('request_checklist.extract',return_value=({'status':'ready','mode':'new'},{})),patch('request_checklist.compile_checklist',side_effect=error):
    checked=gate('构型MOHB01的全部对象',None,s,ids,'new',self.store)
   self.assertEqual(checked['decision'],'clarify');self.assertIn('pending_state',checked);self.assertEqual(checked['reason'].count('？'),1);self.assertIn('下级',checked['reason'])
   self.assertNotIn('plan',checked);self.assertNotIn('needs_review',checked)
   for change in ('root','known_population','unit_reason','ids'):
    bad=copy.deepcopy(draft);bad_ids=list(ids)
    if change=='root':bad['tasks'][0]['filters'][0]['value']='MOHB'
    if change=='known_population':bad['tasks'][0]['population']='parts'
    if change=='unit_reason':bad['pending_reason']='unit'
    if change=='ids':bad_ids=[]
    self.assertFalse(reviewable_draft(s,ids,bad,bad_ids,self.store),change)

def serve_fixture():
 import app,request_checklist
 app.STORE=app.IMPORTS.load()
 def interpret(question,context,selection):
  p,state,changed=seed(population='parts')
  model.TRACE.value={'engine':'business_request','business_request_state':state,'changed_tasks':changed,
   'business_request_delta':{'mode':'new','tasks':[{'quote':question}]}}
  return p
 app.interpret=interpret;request_checklist.gate=lambda *args,**kwargs:{'decision':'accept','choice':'candidate'}
 print('Relationship UI fixture on 8771, no real model calls',flush=True)
 app.ThreadingHTTPServer(('127.0.0.1',8771),app.Handler).serve_forever()

if __name__=='__main__':
 if '--serve' in sys.argv:serve_fixture()
 else:unittest.main()
