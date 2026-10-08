"""已执行的精确单对象定位与属性查询共享主体事实。"""
import copy,sys,unittest
from pathlib import Path
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'backend'),str(Path(__file__).resolve().parent)]
from data import Store
from query_plan import execute_plan,task_context,exact_lookup_subject
from request_gateway import reference_context
from business_request import apply_delta,RequestInvalid
from test_object_scope import delta
from session_state import snapshot,restore

def plan(target='equipment_class',field='name',value='设备类描述1147'):
 return {'operation':'search','entity':None,'scope':'direct','clarification':'','query':{'target':target,'filters':[{'field':field,'operator':'equals','value':value}]}}

class ConfirmedSubjectTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.store=Store()
 @classmethod
 def tearDownClass(cls):cls.store.db.close()
 def lookup(self):
  p=plan();r=execute_plan(self.store,p);return p,r,task_context(p,r)
 def test_exact_lookup_records_subject_without_changing_list_display(self):
  p,r,c=self.lookup();self.assertIsNone(r['entity']);self.assertEqual(len(r['records']),1)
  self.assertEqual(c['query_receipt']['confirmed_subject'],{'tree':'equipment_class','code':'AMCC','name':'设备类描述1147','version':self.store.version})
  refs=reference_context(c,None,self.store,'AMCC是什么')
  self.assertEqual(refs['confirmed_subjects'],[{'tree':'equipment_class','code':'AMCC','name':'设备类描述1147','kind':'exact_lookup'}])
 def test_actual_receipt_binds_full_code_after_exact_name_query(self):
  p,r,c=self.lookup();q='AMCC这个设备是什么';refs=reference_context(c,None,self.store,q)
  p,s,_=apply_delta(delta(q,name='AMCC',scope='unspecified',target='objects'),None,q,refs)
  self.assertEqual(p['query']['target'],'equipment_class');self.assertEqual(s['tasks'][0]['sources']['subject_scope']['kind'],'inherited_confirmed_alias')
 def test_name_domain_word_is_not_new_domain_if_alias_already_confirmed(self):
  p=plan('config','code','AMCC');r=execute_plan(self.store,p);c=task_context(p,r)
  q='构型对象描述8904这个对象再介绍一下';refs=reference_context(c,None,self.store,q)
  p,s,_=apply_delta(delta(q,name='构型对象描述8904',purpose='introduction',scope='explicit',target='config'),None,q,refs)
  self.assertEqual(p['query']['target'],'config');self.assertEqual(s['tasks'][0]['sources']['subject_scope']['kind'],'inherited_confirmed_alias')
 def test_name_word_without_prior_subject_still_does_not_select_tree(self):
  q='设备类描述1147是什么';refs=reference_context({},None,self.store,q)
  with self.assertRaises(RequestInvalid):apply_delta(delta(q,name='设备类描述1147',scope='explicit',target='equipment_class'),None,q,refs)
 def test_separate_explicit_domain_keeps_explicit_provenance(self):
  _,_,c=self.lookup();q='构型AMCC是什么';refs=reference_context(c,None,self.store,q)
  p,s,_=apply_delta(delta(q,name='AMCC',scope='explicit',target='config'),None,q,refs)
  self.assertEqual(p['query']['target'],'config');self.assertNotEqual(s['tasks'][0]['sources']['subject_scope'].get('kind'),'inherited_confirmed_alias')
 def test_metadata_not_created_for_nonexact_or_incomplete_results(self):
  original,result,_=self.lookup()
  for change in ('contains','extra_filter','objects','points','root','depth','zero','multi','page','not_ok','wrong_field','mismatched_row'):
   p=copy.deepcopy(original);r=copy.deepcopy(result)
   if change=='contains':p['query']['filters'][0]['operator']='contains'
   if change=='extra_filter':p['query']['filters'].append({'field':'code','operator':'equals','value':'AMCC'})
   if change in ('objects','points'):p['query']['target']=change
   if change=='root':p['entity']={'tree':'config','code':'AMCC'}
   if change=='depth':p['scope']='all'
   if change=='zero':r['records']=[]
   if change=='multi':r['records']*=2
   if change=='page':r['total']=2
   if change=='not_ok':r['status']='clarify'
   if change=='wrong_field':p['query']['filters'][0]['field']='parent'
   if change=='mismatched_row':r['records'][0]['name']='another'
   with self.subTest(change=change):self.assertIsNone(exact_lookup_subject(p,r,self.store.version))
 def test_receipt_version_and_current_identity_revalidated(self):
  _,_,context=self.lookup()
  for change in ('version','name','query','scope','root','operation'):
   c=copy.deepcopy(context);receipt=c['query_receipt']
   if change=='version':receipt['confirmed_subject']['version']='stale'
   if change=='name':receipt['confirmed_subject']['name']='invented'
   if change=='query':receipt['query']['filters'][0]['operator']='contains'
   if change=='scope':receipt['scope']='all'
   if change=='root':receipt['requested_entity']={'tree':'config','code':'AMCC'}
   if change=='operation':receipt['operation']='analyze'
   with self.subTest(change=change):self.assertEqual(reference_context(c,None,self.store,'AMCC是什么')['confirmed_subjects'],[])
 def test_old_receipt_without_new_metadata_remains_compatible(self):
  _,_,c=self.lookup();c['query_receipt'].pop('confirmed_subject')
  self.assertEqual(reference_context(c,None,self.store,'AMCC是什么')['confirmed_subjects'],[])
 def test_selected_new_tree_takes_precedence_over_lookup_receipt(self):
  _,_,c=self.lookup();q='AMCC是什么';refs=reference_context(c,{'tree':'config','code':'AMCC'},self.store,q)
  p,_,_=apply_delta(delta(q,name='AMCC',target='objects'),None,q,refs);self.assertEqual(p['query']['target'],'config')
 def test_signed_restore_keeps_proof_and_rejects_other_snapshot(self):
  p,r,c=self.lookup();session={'context':c,'dialogue':[],'last_success':r}
  token=snapshot('proof',session,self.store.version);restored=restore(token,'proof',self.store.version)
  refs=reference_context(restored['context'],None,self.store,'AMCC是什么');self.assertEqual(refs['confirmed_subjects'][0]['code'],'AMCC')
  with self.assertRaises(ValueError):restore(token,'proof','different-version')
 def test_new_full_code_does_not_inherit_previous_receipt_domain(self):
  _,_,c=self.lookup();q='AMCC01是什么';refs=reference_context(c,None,self.store,q)
  p,_,_=apply_delta(delta(q,name='AMCC01',target='objects'),None,q,refs);self.assertEqual(p['query']['target'],'objects')

if __name__=='__main__':unittest.main()
