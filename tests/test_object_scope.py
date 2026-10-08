"""类型化用途区分对象介绍与已确认身份范围。"""
import sys,copy,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from business_request import apply_delta,RequestAmbiguous,RequestInvalid,extraction_context
from request_checklist import compile_checklist,canonical_tasks
from data import Store

def delta(q,name='MOHB',purpose='identity',scope='unspecified',target='equipment_class'):
 return {'version':7,'mode':'new','roles':{'background':[],'output':[1],'control':[]},'tasks':[{'base':None,'action':'request','request_spans':[1],'spans':[1],'purpose':purpose,'subject_scope':scope,'set':{'operation':'attributes','target':target,'properties':['name','code']},'filters':[{'action':'add','ids':[],'spans':[1],'conditions':[{'field':'identity','operator':'equals','value':name}]}]}]}
def refs(code='MOHB',tree='equipment_class',name='设备类描述1860'):
 return {'confirmed_subjects':[{'code':code,'name':name,'tree':tree,'kind':'executed_entity'}],'references':[]}
class ObjectScopeTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.store=Store()
 @classmethod
 def tearDownClass(cls):cls.store.db.close()
 def test_unspecified_introduction_saves_domain_draft_not_unit_draft(self):
  q='介绍MOHB'
  with self.assertRaises(RequestAmbiguous) as e:apply_delta(delta(q,purpose='introduction'),None,q)
  state=e.exception.state;self.assertEqual(state['pending_reason'],'domain');self.assertEqual(state['tasks'][0]['target'],'objects');self.assertEqual(state['tasks'][0]['filters'][0]['value'],'MOHB')
  self.assertEqual(extraction_context({'pending_business_request':state})['request_status'],'awaiting_domain')
 def test_unknown_tree_identity_cannot_use_database_hit_as_user_scope(self):
  p,s,_=apply_delta(delta('MOHB是什么'),None,'MOHB是什么');self.assertEqual(p['query']['target'],'objects')
 def test_explicit_tree_requires_separate_business_label(self):
  for target,q in [('equipment_class','设备类MOHB的情况'),('config','构型MOHB的情况'),('pbs','PBS中的MOHB情况')]:
   p,_,_=apply_delta(delta(q,purpose='introduction',scope='explicit',target=target),None,q);self.assertEqual(p['query']['target'],target)
  with self.assertRaises(RequestInvalid):apply_delta(delta('MOHB是什么',scope='explicit'),None,'MOHB是什么')
 def test_tree_word_inside_name_is_not_explicit_tree(self):
  q='介绍设备类描述1860'
  with self.assertRaises(RequestInvalid):apply_delta(delta(q,name='设备类描述1860',purpose='introduction',scope='explicit'),None,q)
 def test_confirmed_full_code_or_name_uses_verified_tree(self):
  for value in ('MOHB','设备类描述1860'):
   q=value+'是什么';p,s,_=apply_delta(delta(q,name=value,scope='confirmed',target='objects'),None,q,refs());self.assertEqual(p['query']['target'],'equipment_class');self.assertEqual(s['tasks'][0]['sources']['target']['kind'],'confirmed_subject')
 def test_new_prefix_cannot_borrow_old_subject(self):
  with self.assertRaises(RequestInvalid):apply_delta(delta('MOH是什么',name='MOH',scope='confirmed'),None,'MOH是什么',refs())
 def test_explicit_other_tree_and_cross_tree_override_old_focus(self):
  q='构型MOHB是什么';p,_,_=apply_delta(delta(q,scope='explicit',target='config'),None,q,refs());self.assertEqual(p['query']['target'],'config')
  q='跨树介绍MOHB';p,_,_=apply_delta(delta(q,purpose='introduction',scope='cross_tree'),None,q,refs());self.assertEqual(p['query']['target'],'objects')
 def test_domain_reply_preserves_identity_filter(self):
  with self.assertRaises(RequestAmbiguous) as e:apply_delta(delta('介绍MOHB',purpose='introduction'),None,'介绍MOHB')
  old=e.exception.state;fid=old['tasks'][0]['filters'][0]['id'];d=delta('设备类',purpose='introduction',scope='explicit');d['mode']='update';t=d['tasks'][0];t.update(base='t1',replace_task=True,retain_filters=[fid],filters=[])
  p,s,_=apply_delta(d,old,'设备类');self.assertEqual(p['query']['filters'][0]['value'],'MOHB');self.assertEqual(p['query']['target'],'equipment_class');self.assertNotIn('pending_reason',s)
 def test_data_scope_not_constrained_by_identity_rules(self):
  q='读取MOHB的名称';p,_,_=apply_delta(delta(q,purpose='data',scope='none'),None,q);self.assertEqual(p['query']['target'],'equipment_class')
  with self.assertRaises(RequestInvalid):apply_delta(delta(q,purpose='data',scope='confirmed'),None,q,refs())
 def test_confirmed_narrowing_does_not_require_free_replacement(self):
  _,old,_=apply_delta(delta('MOHB是什么'),None,'MOHB是什么')
  q='继续了解MOHB';d=delta(q,scope='confirmed');d['mode']='update';d['tasks'][0].update(base='t1',filters=[])
  p,s,_=apply_delta(d,old,q,refs());self.assertEqual(p['query']['target'],'equipment_class');self.assertEqual(s['tasks'][0]['filters'],old['tasks'][0]['filters'])
 def test_identity_scope_cannot_bypass_other_filter_replacement(self):
  q='MOHB是什么';d=delta(q,scope='confirmed');d['tasks'][0]['filters'][0]['conditions'].append({'field':'level','operator':'equals','value':'3'})
  with self.assertRaises(RequestInvalid):apply_delta(d,None,q,refs())
 def test_mixed_domain_draft_keeps_all_tasks_unexecuted(self):
  q='介绍MOHB';d=delta(q,purpose='introduction');other=copy.deepcopy(d['tasks'][0]);other.update(purpose='data',subject_scope='none');d['tasks'].append(other)
  with self.assertRaises(RequestAmbiguous) as e:apply_delta(d,None,q)
  self.assertEqual(len(e.exception.state['tasks']),2);self.assertEqual(e.exception.state['pending_tasks'],['t1'])
 def test_independent_v10_has_same_scope_contract(self):
  q='MOHB是什么';c={'version':10,'roles':{'background':[],'output':[1],'control':[]},'status':'ready','mode':'new','clarification':'','tasks':[{'id':None,'action':'request','request_spans':[1],'spans':[1],'kind':'query','purpose':'identity','subject_scope':'confirmed','target':'objects','properties':['name','code'],'unit':{'state':'none','value':''},'conditions':[{'field':'identity','operator':'equals','value':'MOHB','spans':[1],'reference':None}]}]}
  a=apply_delta(delta(q,scope='confirmed'),None,q,refs());b=compile_checklist(c,None,q,self.store,refs());self.assertEqual(a[0],b[0]);self.assertEqual(canonical_tasks(a[1],a[2],self.store),canonical_tasks(b[1],b[2],self.store))

 def pending_intro(self):
  with self.assertRaises(RequestAmbiguous) as e:apply_delta(delta('介绍MOHB',purpose='introduction'),None,'介绍MOHB')
  return e.exception.state
 def completion(self):
  d=delta('设备类',purpose='introduction',scope='explicit');d['mode']='update';d['tasks'][0].update(base='t1',replace_task=False,retain_filters=[],filters=[],set={'target':'equipment_class'});return d
 def test_domain_slot_completion_is_not_whole_task_replacement(self):
  old=self.pending_intro();saved=copy.deepcopy(old)
  p,s,_=apply_delta(self.completion(),old,'设备类')
  self.assertEqual(old,saved);self.assertEqual(p['query']['target'],'equipment_class')
  self.assertEqual(s['tasks'][0]['filters'],old['tasks'][0]['filters']);self.assertEqual(s['tasks'][0]['properties'],old['tasks'][0]['properties'])
  self.assertNotIn('replacement',s['tasks'][0]['sources']);self.assertNotIn('pending_reason',s)
 def test_slot_exception_requires_matching_pending_task(self):
  for mutation in ('reason','id','purpose','scope'):
   old=self.pending_intro()
   if mutation=='reason':old.pop('pending_reason')
   elif mutation=='id':old['pending_tasks']=['t2']
   else:old['tasks'][0]['sources']['purpose' if mutation=='purpose' else 'subject_scope']['value']='identity' if mutation=='purpose' else 'cross_tree'
   with self.assertRaises(RequestInvalid):apply_delta(self.completion(),old,'设备类')
 def test_slot_completion_cannot_change_object_projection_or_unit(self):
  for mutation in ('object','properties','unit','operation'):
   old=self.pending_intro();saved=copy.deepcopy(old);d=self.completion();t=d['tasks'][0]
   if mutation=='object':t['filters']=[{'action':'replace','ids':[old['tasks'][0]['filters'][0]['id']],'spans':[1],'conditions':[{'field':'identity','operator':'equals','value':'MOH'}]}]
   elif mutation=='unit':t['unit']={'state':'specified','value':'℃'}
   else:t['set'][mutation]=['name'] if mutation=='properties' else 'search'
   with self.assertRaises(RequestInvalid):apply_delta(d,old,'设备类')
   self.assertEqual(old,saved)
 def test_slot_completion_still_requires_current_explicit_tree(self):
  d=self.completion()
  with self.assertRaises(RequestInvalid):apply_delta(d,self.pending_intro(),'就这个')
 def test_independent_slot_completion_retains_original_sources(self):
  old=self.pending_intro()
  c={'version':10,'roles':{'background':[],'output':[1],'control':[]},'status':'ready','mode':'update','clarification':'','tasks':[{'id':'t1','action':'request','request_spans':[1],'spans':[1],'kind':'query','purpose':'introduction','subject_scope':'explicit','target':'equipment_class','properties':['name','code'],'unit':{'state':'none','value':''},'conditions':[{'field':'identity','operator':'equals','value':'MOHB','spans':[],'reference':None}]}]}
  p,s,_,patch=compile_checklist(c,old,'设备类',self.store)
  self.assertEqual(p['query']['target'],'equipment_class');self.assertFalse(patch['tasks'][0].get('replace_task'))
  self.assertEqual(s['tasks'][0]['filters'],old['tasks'][0]['filters'])


 def test_unverified_introduction_scope_saves_new_subject_for_recovery(self):
  for claimed in ('explicit','confirmed'):
   _,old,_=apply_delta(delta('构型MOHB是什么',scope='explicit',target='config'),None,'构型MOHB是什么')
   saved=copy.deepcopy(old);d=delta('换成MOH的基本情况',name='MOH',purpose='introduction',scope=claimed,target='config')
   d['mode']='update';d['tasks'][0].update(base='t1',replace_task=True,retain_filters=[])
   with self.assertRaises(RequestAmbiguous) as e:apply_delta(d,old,'换成MOH的基本情况',refs(code='MOHB',tree='config'))
   pending=e.exception.state;t=pending['tasks'][0]
   self.assertEqual(old,saved);self.assertEqual(t['filters'][0]['value'],'MOH')
   self.assertEqual(t['target'],'objects');self.assertEqual(t['sources']['subject_scope']['value'],'unspecified')
   self.assertEqual(t['sources']['unverified_subject_scope']['claim']['value'],claimed)
   complete=self.completion();complete['tasks'][0]['set']['target']='config'
   p,state,_=apply_delta(complete,pending,'构型树')
   self.assertEqual(p['query']['target'],'config');self.assertEqual(p['query']['filters'][0]['value'],'MOH')
   self.assertNotIn('pending_reason',state)
 def test_unknown_domain_cannot_be_laundered_as_pending_introduction(self):
  for claimed in ('explicit','confirmed'):
   with self.assertRaises(RequestInvalid) as e:apply_delta(delta('介绍MOHB',purpose='introduction',scope=claimed,target='invented'),None,'介绍MOHB')
   self.assertNotIsInstance(e.exception,RequestAmbiguous)

class InheritedScopeTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.store=Store()
 @classmethod
 def tearDownClass(cls):cls.store.db.close()
 def previous(self):
  q='设备类描述1860对应哪个设备类'
  return apply_delta(delta(q,name='设备类描述1860',scope='explicit',target='equipment_class'),None,q)[1]
 def adapt(self,value,references):
  from request_gateway import adapt
  p={'operation':'attributes','entity':None,'scope':'direct','clarification':'','query':{'target':'equipment_class','filters':[{'field':'identity','operator':'equals','value':value}]},'properties':['name','code']}
  return adapt(p,value+'那个设备是什么',self.previous(),'update',self.store,references)
 def test_verified_full_alias_reuses_tree_without_new_tree_word(self):
  old=self.previous()
  for value in ('MOHB','设备类描述1860'):
   p,s,_,_=self.adapt(value,refs())
   self.assertEqual(p['query']['target'],'equipment_class')
   source=s['tasks'][0]['sources']['subject_scope']
   self.assertEqual(source['kind'],'inherited_confirmed_subject');self.assertEqual(source['value'],'confirmed')
   self.assertEqual(source['previous'],old['tasks'][0]['sources']['subject_scope'])
 def test_prefix_or_missing_verified_subject_cannot_borrow_tree(self):
  for value,reference in [('MOH',refs()),('MOHB',{}),('MOHB',refs(tree='config'))]:
   with self.subTest(value=value,reference=reference),self.assertRaises(RequestInvalid):self.adapt(value,reference)
 def test_new_explicit_claim_still_requires_current_tree_evidence(self):
  q='MOHB那个设备是什么';d=delta(q,scope='explicit',target='equipment_class')
  with self.assertRaises(RequestInvalid):apply_delta(d,None,q,refs())

class ConfirmedAliasTests(unittest.TestCase):
 def reference(self,value='MOHB',tree='equipment_class',code='MOHB',name='设备类描述1860'):
  r=refs(code,tree,name);r['references']=[{'kind':'current_literal','value':value,'domain':tree}];return r
 def run_request(self,value='MOHB',purpose='identity',scope='unspecified',target='objects',reference=None,q=None):
  q=q or value+'这个对象是什么'
  return apply_delta(delta(q,name=value,purpose=purpose,scope=scope,target=target),None,q,reference or self.reference(value))
 def test_full_code_or_name_retains_verified_domain(self):
  for value in ('MOHB','设备类描述1860'):
   for purpose in ('identity','introduction'):
    p,s,_=self.run_request(value,purpose)
    self.assertEqual(p['query']['target'],'equipment_class')
    proof=s['tasks'][0]['sources']['subject_scope'];self.assertEqual(proof['kind'],'inherited_confirmed_alias')
    self.assertEqual(proof['previous']['value'],'unspecified')
 def test_updated_task_also_retains_verified_alias(self):
  _,old,_=self.run_request();q='MOHB再确认一次';d=delta(q,scope='unspecified',target='objects');d['mode']='update';d['tasks'][0].update(base='t1',set={'properties':['name']},filters=[])
  _,s,_=apply_delta(d,old,q,self.reference());self.assertEqual(s['tasks'][0]['target'],'equipment_class')
  self.assertEqual(s['tasks'][0]['filters'],old['tasks'][0]['filters'])
 def test_different_prefix_or_unconfirmed_alias_does_not_inherit(self):
  for value,reference in [('MOH',self.reference('MOH')),('MOHB01',self.reference('MOHB01')),('MOHB',{'confirmed_subjects':[],'references':[{'kind':'current_literal','value':'MOHB'}]}),('MOHB',refs())]:
   p,_,_=self.run_request(value,reference=reference);self.assertEqual(p['query']['target'],'objects')
 def test_current_reference_in_another_clause_cannot_match_only_a_prefix(self):
  q='忽略MOHB，看看MOHB01';d=delta(q,name='MOHB',target='objects');d['roles']={'background':[],'output':[2],'control':[1]};d['tasks'][0].update(request_spans=[2],spans=[1,2]);d['tasks'][0]['filters'][0]['spans']=[1]
  p,s,_=apply_delta(d,None,q,self.reference());self.assertEqual(p['query']['target'],'objects')
  self.assertNotEqual(s['tasks'][0]['sources']['subject_scope'].get('kind'),'inherited_confirmed_alias')
 def test_explicit_domain_cross_tree_and_conflicting_labels_are_preserved(self):
  p,_,_=self.run_request(scope='cross_tree');self.assertEqual(p['query']['target'],'objects')
  p,_,_=self.run_request(scope='explicit',target='config',q='构型MOHB是什么');self.assertEqual(p['query']['target'],'config')
  for q,target in [('构型MOHB是什么','objects'),('MOHB是什么','config')]:
   p,_,_=self.run_request(q=q,target=target);self.assertEqual(p['query']['target'],'objects')
 def test_selected_subject_precedes_execution_but_ambiguous_selection_does_not(self):
  r=self.reference();r['confirmed_subjects'].append({'tree':'config','code':'MOHB','name':'构型对象描述','kind':'user_selection'})
  p,_,_=self.run_request(reference=r);self.assertEqual(p['query']['target'],'config')
  r['confirmed_subjects'].append({'tree':'equipment_class','code':'MOHB','name':'设备类描述1860','kind':'user_selection'})
  p,_,_=self.run_request(reference=r);self.assertEqual(p['query']['target'],'objects')
 def test_two_subjects_in_same_tree_with_shared_name_are_not_unique(self):
  r=self.reference('同名','config','A','同名');r['confirmed_subjects'].append({'tree':'config','code':'B','name':'同名','kind':'executed_entity'})
  p,_,_=self.run_request('同名',reference=r);self.assertEqual(p['query']['target'],'objects')
 def test_data_query_does_not_acquire_identity_scope(self):
  p,s,_=self.run_request(purpose='data',scope='none',target='config');self.assertEqual(p['query']['target'],'config')
  self.assertEqual(s['tasks'][0]['sources']['subject_scope']['value'],'none')

if __name__=='__main__':unittest.main()
