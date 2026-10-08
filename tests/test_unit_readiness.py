"""单位是否明确由有原话来源的条件编译判断，不采用第二次模型投票。"""
import copy,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from business_request import apply_delta,RequestInvalid,RequestAmbiguous
from request_checklist import compile_checklist,to_delta
from data import Store
Q='筛选测量值大于50摄氏度、小于80摄氏度的测点。'
def delta(units=('℃',),question=Q):
    conditions=[{'field':'value','operator':'gt','value':'50'},{'field':'value','operator':'lt','value':'80'}]
    conditions += [{'field':'unit','operator':'equals','value':u} for u in units]
    return {'version':1,'mode':'new','tasks':[{'base':None,'quote':question,'set':{'operation':'search','target':'points','properties':[]},'unit':{'state':'none','value':''},'filters':[{'action':'add','ids':[],'conditions':conditions,'quote':question}]}]}
def checklist(unit='℃',state='specified',version=9,status='ready'):
    cs=[{'field':'value','operator':'gt','value':'50','spans':[1],'reference':None}]
    if unit:cs.append({'field':'unit','operator':'equals','value':unit,'spans':[1],'reference':None})
    return {'version':version,'roles':{'background':[],'output':[1],'control':[]},'status':status,'mode':'new','clarification':'',
            'tasks':[{'id':None,'action':'request','request_spans':[1],'spans':[1],'kind':'query','target':'points','properties':[],
                      'unit':{'state':state,'value':unit if state=='specified' else ''},'conditions':cs}]}
class UnitReadinessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.store=Store()
    @classmethod
    def tearDownClass(cls):cls.store.db.close()
    def test_source_validated_aliases_collapse_to_one_unit_and_stable_id(self):
        expected=apply_delta(delta(),None,Q)
        for units in [('℃','℃'),('℃','摄氏度'),('摄氏度','℃')]:
            with self.subTest(units=units):
                plan,state,ids=apply_delta(delta(units),None,Q)
                self.assertEqual(plan,expected[0]);self.assertEqual(state,expected[1]);self.assertEqual(ids,['t1'])
    def test_fahrenheit_works_without_celsius_assumption(self):
        q=Q.replace('摄氏度','华氏度');plan,state,_=apply_delta(delta(('℉','华氏度'),q),None,q)
        self.assertEqual(state['tasks'][0]['unit'],{'state':'specified','value':'℉'})
        self.assertEqual(sum(f['field']=='unit' for f in plan['query']['filters']),1)
    def test_conflicting_numeric_units_are_not_last_writer_wins(self):
        q='筛选测量值大于50摄氏度且小于80华氏度的测点。'
        with self.assertRaisesRegex(RequestInvalid,'冲突单位'):apply_delta(delta(('℃','℉'),q),None,q)
    def test_duplicate_cannot_skip_source_check(self):
        d=delta();d['tasks'][0]['filters'].append({'action':'add','ids':[],'conditions':[{'field':'unit','operator':'equals','value':'℉'}],'quote':'测点'})
        with self.assertRaises(RequestInvalid):apply_delta(d,None,Q)
    def test_nonunit_duplicate_still_rejected(self):
        d=delta();d['tasks'][0]['filters'][0]['conditions'].append({'field':'value','operator':'gt','value':'50'})
        with self.assertRaisesRegex(RequestInvalid,'重复'):apply_delta(d,None,Q)
    def test_same_unit_readdition_keeps_id_and_removal_preserves_numbers(self):
        _,old,_=apply_delta(delta(),None,Q);original=copy.deepcopy(old)
        d={'version':1,'mode':'update','tasks':[{'base':'t1','quote':'仍然按摄氏度','set':{},'filters':[{'action':'add','ids':[],'conditions':[{'field':'unit','operator':'equals','value':'℃'}],'quote':'摄氏度'}]}]}
        _,new,_=apply_delta(d,old,'仍然按摄氏度');self.assertEqual(new['tasks'][0]['filters'],old['tasks'][0]['filters']);self.assertEqual(new['next_filter_id'],old['next_filter_id'])
        unitid=old['tasks'][0]['filters'][-1]['id'];d['tasks'][0].update(quote='不限制单位',filters=[{'action':'remove','ids':[unitid],'conditions':[],'quote':'不限制单位'}])
        plan,new,_=apply_delta(d,old,'不限制单位');self.assertEqual(len(plan['query']['filters']),2);self.assertEqual(new['tasks'][0]['unit']['state'],'none');self.assertEqual(old,original)
    def test_v9_ready_is_not_permission_to_execute_ambiguous_unit(self):
        q='筛选测量值大于50度的测点'
        with self.assertRaises(RequestAmbiguous) as e:compile_checklist(checklist('',state='ambiguous'),None,q,self.store)
        self.assertEqual(e.exception.state['tasks'][0]['filters'][0]['value'],'50')
    def test_v9_compiled_explicit_unit_resolves_redundant_ambiguity(self):
        q='筛选测量值大于50摄氏度的测点';c=checklist(state='ambiguous')
        plan,state,_,_=compile_checklist(c,None,q,self.store)
        self.assertEqual(state['tasks'][0]['unit'],{'state':'specified','value':'℃'})
        self.assertIn({'field':'unit','operator':'equals','value':'℃'},plan['query']['filters'])
    def test_v9_forbids_global_clarify_but_keeps_legacy_contract(self):
        q='筛选测量值大于50摄氏度的测点'
        with self.assertRaisesRegex(RequestInvalid,'V9'):to_delta(checklist(status='clarify'),None,q)
        with self.assertRaises(RequestAmbiguous):compile_checklist(checklist(version=8,status='clarify'),None,q,self.store)
    def test_unsupported_cannot_smuggle_executable_tasks(self):
        q='筛选测量值大于50摄氏度的测点'
        c=checklist(status='unsupported');c['clarification']='缺少必要对象'
        with self.assertRaises(RequestInvalid):to_delta(c,None,q)
        c['tasks']=[];self.assertIsNone(to_delta(c,None,q))
if __name__=='__main__':unittest.main()
