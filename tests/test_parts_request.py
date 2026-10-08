"""关系契约测试，包含独立于 SQL 实现的图关系预期。"""
import sys,copy,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from business_request import apply_delta,compile_task,RequestInvalid,extraction_context
from request_checklist import compile_checklist,canonical_tasks,prior_view
from importer import Imports
from data import Store,QueryError,BusinessOutcome
from query_plan import execute_plan
import model,query_review

def delta(value='MOHB01',scope='direct',field='identity'):
 return {'version':8,'mode':'new','roles':{'background':[],'output':[1],'control':[]},'tasks':[{
 'base':None,'action':'request','request_spans':[1],'spans':[1],'purpose':'data','subject_scope':'none',
 'set':{'operation':'parts','target':'config','scope':scope,'properties':[]},
 'filters':[{'action':'add','ids':[],'spans':[1],'conditions':[{'field':field,'operator':'equals','value':value}]}]}]}
def seed(value='MOHB01',scope='direct',field='identity'):
 q='构型'+value+'的部件'
 return apply_delta(delta(value,scope,field),None,q)
def update(state,fields=None,edits=None,q='更新范围或对象'):
 d=delta();d['mode']='update';d['tasks'][0].update(base='t1',set=fields or {},filters=edits or [])
 return apply_delta(d,state,q)
def edits(preview):
 return [{k:copy.deepcopy(t[k]) for k in ('index','enabled','values')} for t in preview['review']['tasks']]

class PartsTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.store=Imports().load()
  cls.raw=next(d['rows'] for d in cls.store.dataset if d['kind']=='config')
 @classmethod
 def tearDownClass(cls):cls.store.db.close()
 def oracle(self,root,scope):
  children={}
  for r in self.raw:children.setdefault(r['父对象代码'],[]).append(r)
  seen={root};found=[];queue=list(children.get(root,[]))
  while queue:
   r=queue.pop(0);code=r['对象代码']
   if code in seen:continue
   seen.add(code)
   if r['对象层级描述']=='部件':found.append(r)
   if scope=='all':queue.extend(children.get(code,[]))
  return {r['对象代码']:r for r in found}
 def test_exact_graph_rows_and_counts_for_both_scopes_and_identifiers(self):
  name=next(r['对象描述中文'] for r in self.raw if r['对象代码']=='MOHB01')
  for scope in ('direct','all'):
   for field,value in [('identity','MOHB01'),('identity',name),('name',name),('code','MOHB01')]:
    with self.subTest(scope=scope,field=field,value=value):
     p,_,_=seed(value,scope,field);model.validate(p);r=self.store.execute(p)
     expected=self.oracle('MOHB01',scope)
     self.assertEqual({x['code']:x['evidence']['fields'] for x in r['records']},expected)
     self.assertEqual({m['label']:m['value'] for m in r['metrics']},{'直接部件':len(self.oracle('MOHB01','direct')),'全部下级部件':len(self.oracle('MOHB01','all'))})
 def test_unknown_root_is_not_a_zero_count(self):
  for field,value in [('identity','DOES_NOT_EXIST'),('name','MOHB01')]:
   p,_,_=seed(value,field=field)
   with self.assertRaises(BusinessOutcome):self.store.execute(p)
 def test_leaf_root_has_valid_zero_count(self):
  parents={r['父对象代码'] for r in self.raw}
  leaf=next(r['对象代码'] for r in self.raw if r['对象代码'] not in parents)
  r=self.store.execute(seed(leaf,'all')[0])
  self.assertEqual(r['records'],[]);self.assertTrue(all(m['value']==0 for m in r['metrics']))
 def test_ambiguous_identity_stops_before_traversal(self):
  p,_,_=seed()
  with patch.object(self.store,'rows',return_value=[{'tree':'config','code':'a','name':'MOHB01'},{'tree':'config','code':'MOHB01','name':'b'}]),patch.object(self.store,'obj',side_effect=AssertionError('must not traverse')):
   with self.assertRaises(BusinessOutcome):self.store.execute(p)
 def test_scope_edit_preserves_root_and_source(self):
  _,s,_=seed();p,new,_=update(s,{'scope':'all'})
  self.assertEqual(p['scope'],'all');self.assertEqual(new['tasks'][0]['filters'],s['tasks'][0]['filters'])
  self.assertNotEqual(canonical_tasks(s,['t1'],self.store),canonical_tasks(new,['t1'],self.store))
  self.assertEqual(prior_view(new)[0]['scope'],'all')
  self.assertEqual(extraction_context({'business_request':new})['task_directory'][0]['scope'],'all')
 def test_root_edit_preserves_range_and_siblings(self):
  d=delta(scope='all');d['tasks'].append(copy.deepcopy(d['tasks'][0]))
  _,s,_=apply_delta(d,None,'MOHB01')
  e={'action':'replace','ids':[s['tasks'][0]['filters'][0]['id']],'spans':[1],'conditions':[{'field':'identity','operator':'equals','value':'MOHB02'}]}
  p,new,_=update(s,edits=[e],q='根对象换成MOHB02');self.assertEqual(p['scope'],'all');self.assertEqual(p['entity']['identity'],'MOHB02')
  self.assertEqual(new['tasks'][1],s['tasks'][1])
 def test_reject_incomplete_scope_and_invalid_domain_properties_unit_filters(self):
  for mode in ('no_scope','target','props','unit','extra','contains'):
   d=delta()
   if mode=='no_scope':d['tasks'][0]['set'].pop('scope')
   if mode=='target':d['tasks'][0]['set']['target']='pbs'
   if mode=='props':d['tasks'][0]['set']['properties']=['name']
   if mode=='unit':d['tasks'][0]['unit']={'state':'ambiguous','value':''}
   if mode=='extra':d['tasks'][0]['filters'][0]['conditions'].append({'field':'parent','operator':'equals','value':'x'})
   if mode=='contains':d['tasks'][0]['filters'][0]['conditions'][0]['operator']='contains'
   with self.subTest(mode=mode),self.assertRaises(RequestInvalid):apply_delta(d,None,'MOHB01')
 def test_type_switch_requires_full_replacement(self):
  _,s,_=seed()
  with self.assertRaises(RequestInvalid):update(s,{'operation':'search'})
 def test_internal_identity_is_only_for_config_parts(self):
  p,_,_=seed()
  for op,tree in [('equipment','config'),('parts','pbs'),('parent','config')]:
   bad=copy.deepcopy(p);bad['operation']=op;bad['entity']['tree']=tree
   with self.assertRaises(model.ModelUnavailable):model.validate(bad)
 def test_independent_v11_compiles_same_contract(self):
  q='构型MOHB01的全部下级部件'
  c={'version':11,'roles':{'background':[],'output':[1],'control':[]},'status':'ready','mode':'new','clarification':'','tasks':[{
   'id':None,'action':'request','request_spans':[1],'spans':[1],'kind':'parts','purpose':'data','subject_scope':'none',
   'target':'config','scope':'all','properties':[],'unit':{'state':'none','value':''},
   'conditions':[{'field':'identity','operator':'equals','value':'MOHB01','spans':[1],'reference':None}]}]}
  a=seed(scope='all');b=compile_checklist(c,None,q,self.store)
  self.assertEqual(a[0],b[0]);self.assertEqual(canonical_tasks(a[1],a[2],self.store),canonical_tasks(b[1],b[2],self.store))
 def test_confirmation_preserves_or_records_edited_root_without_model(self):
  for change in (False,True):
   p,s,changed=seed(scope='all');session={'context':{}}
   preview=query_review.issue(session,'sid','v1','构型MOHB01的部件',p,{'business_request_state':s,'changed_tasks':changed,'business_request_delta':{'mode':'new'}})
   self.assertEqual(preview['review']['tasks'][0]['entity_trees'],{'config':'构型树'})
   e=edits(preview)
   if change:e[0]['values'].update(entity={'tree':'config','identity':'MOHB02'},scope='direct')
   with patch.object(model,'interpret',side_effect=AssertionError('no model')):
    actual,trace,_=query_review.confirm(session,'sid','v1',preview['review']['id'],e)
   t=trace['business_request_state']['tasks'][0];self.assertEqual(compile_task(t),actual)
   if change:
    self.assertNotEqual(t['filters'][0]['id'],s['tasks'][0]['filters'][0]['id'])
    self.assertEqual(t['filters'][0]['source']['kind'],'user_confirmation')
   else:self.assertEqual(t,s['tasks'][0])
 def test_invalid_tree_edit_keeps_review_editable(self):
  p,s,changed=seed(scope='all');session={'context':{}}
  preview=query_review.issue(session,'sid','v1','MOHB01',p,{'business_request_state':s,'changed_tasks':changed})
  e=edits(preview);e[0]['values']['entity']={'tree':'pbs','code':'x'}
  with self.assertRaises(QueryError):query_review.confirm(session,'sid','v1',preview['review']['id'],e)
  self.assertIn('pending_review',session)
if __name__=='__main__':unittest.main()
