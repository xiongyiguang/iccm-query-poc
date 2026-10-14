"""公共槽位和控制来源的合成反例，避免依赖客户问句/编码。"""
import copy, sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'backend'))
from data import Store
from test_equipment_node_roles import dataset
from query_scope import public_transition
from request_turn import planning_context, depth_control, independent
from relational_query import canonical
from relational_delta_codec import normalize_delta
from relational_state import compile_delta


class QueryTurnSlots(unittest.TestCase):
    def setUp(self): self.store=Store(dataset=[{'kind':k,'file':k+'.csv','sha256':k,'rows':v,'seed':True} for k,v in dataset().items()])
    def tearDown(self): self.store.db.close()
    def focus(self):
        return {'entity':{'tree':'config','code':'D'},'relational_state':{'tasks':[{'id':1,'spec':canonical({'root':{'tree':'config','field':'code','value':'D'},'kind':'collection','population':'parts','depth':'direct'})}]}}
    def test_domain_clarification_restores_the_unexecuted_original_identity(self):
        first=public_transition('D对应设备类是什么？',{},self.store)
        self.assertEqual(first['plan']['operation'],'clarify')
        second=public_transition('构型树里的那个对象',{'pending_public_query':first['pending']},self.store)
        self.assertEqual(second['plan']['relational_tasks'][0]['spec']['root'],{'tree':'config','field':'code','value':'D'})
    def test_missing_root_preserves_requested_depth_until_identity_is_given(self):
        first=public_transition('请列出直属部件列表',{},self.store)
        self.assertEqual(first['pending']['depth'],'direct')
        second=public_transition('构型树 D',{'pending_public_query':first['pending']},self.store)
        self.assertEqual(second['plan']['relational_tasks'][0]['spec']['depth'],'direct')
    def test_slot_key_labels_do_not_turn_identity_supply_into_a_new_task(self):
        first=public_transition('直属部件，根待补充',{},self.store)
        for answer in ('根对象是构型树 D','主体：构型 D','对象树：构型，编码：D'):
            with self.subTest(answer=answer):
                second=public_transition(answer,{'pending_public_query':first['pending']},self.store)
                self.assertEqual(second['plan']['relational_tasks'][0]['spec']['depth'],'direct')
    def test_known_output_and_depth_need_no_query_verb_for_a_missing_root_draft(self):
        first=public_transition('要直属部件，根对象待补充',{},self.store)
        self.assertEqual(first['plan']['operation'],'clarify');self.assertEqual(first['pending']['root'],None)
    def test_explanation_does_not_become_an_unexecuted_collection(self):
        self.assertIsNone(public_transition('解释直属部件的定义',{},self.store))
    def test_global_class_collection_keeps_its_actual_owner(self):
        ctx={'relational_state':{'tasks':[{'id':1,'spec':canonical({'kind':'collection','population':'devices','root':None,'classes':{'equipment_class':'C'}})}]}}
        self.assertIsNone(public_transition('接着查这些设备的全部下级部件，按类别分布统计',ctx,self.store))
    def test_actual_history_is_not_treated_as_a_missing_root(self):
        ctx={'relational_history':[{'question':'old','state':self.focus()['relational_state']}]}
        self.assertIsNone(public_transition('回到首轮那台设备，只查全部下级部件',ctx,self.store))
    def class_filter(self,tree='equipment_class',value='C',operator='equals',mode='new'):
        q='全表监测，所属设备类'+value
        return q,{'version':2,'handled':True,'mode':mode,'tasks':[{'id':1,'action':mode,'quote':q,'set':{'kind':'collection','population':'points'},'root':{'type':'global','quote':'全表监测'},'filters':[{'action':'add','condition':{'field':tree,'operator':operator,'value':value},'quote':'所属设备类'+value}],'classes':[]}]}
    def test_current_exact_class_predicate_can_use_the_registered_class_contract(self):
        q,raw=self.class_filter();normalized,_=normalize_delta(raw,q,{},self.store)
        plan,_=compile_delta(normalized,q,{},self.store)
        self.assertEqual(plan['tasks'][0]['spec']['classes'],{'equipment_class':'C'})
        self.assertEqual(plan['tasks'][0]['spec']['filters'],[])
    def test_partial_or_unknown_class_predicate_is_not_guessed(self):
        for value,operator in [('C','starts_with'),('MISSING','equals')]:
            q,raw=self.class_filter(value=value,operator=operator)
            with self.subTest(value=value),self.assertRaises(ValueError):compile_delta(normalize_delta(raw,q,{},self.store)[0],q,{},self.store)
    def test_add_class_predicate_cannot_replace_an_existing_different_class(self):
        q,raw=self.class_filter(value='D',mode='update');raw['tasks'][0].pop('root')
        ctx={'relational_state':{'tasks':[{'id':1,'spec':canonical({'kind':'collection','population':'points','root':None,'classes':{'equipment_class':'C'}})}]}}
        with self.assertRaises(ValueError):compile_delta(normalize_delta(raw,q,ctx,self.store)[0],q,ctx,self.store)
    def test_new_task_does_not_silently_complete_an_old_slot(self):
        first=public_transition('D对应设备类是什么？',{},self.store)
        self.assertIsNone(public_transition('构型E的全部下级部件有哪些？',{'pending_public_query':first['pending']},self.store))
    def test_slot_cannot_select_a_table_without_original_record(self):
        first=public_transition('请列出直属部件列表',{},self.store)
        second=public_transition('PBS D',{'pending_public_query':first['pending']},self.store)
        self.assertEqual(second['plan']['operation'],'clarify')
    def test_stale_data_version_cannot_resume_a_slot(self):
        first=public_transition('D对应设备类是什么？',{},self.store);first['pending']['version']='other-version'
        self.assertIsNone(public_transition('构型树',{'pending_public_query':first['pending']},self.store))
    def test_negative_history_is_not_positive_all_depth(self):
        self.assertEqual(depth_control('这次独立查直属部件，不沿用以前全部后代范围'),'direct')
        self.assertEqual(depth_control('不要直接部件，查所有后代部件'),'all')
    def test_name_and_quoted_text_are_not_control_actions(self):
        self.assertIsNone(depth_control('读取名为全部后代的对象'))
        self.assertFalse(independent('查名称为独立查询的对象'))
        self.assertFalse(independent('查“新问题”对象'))
    def test_independent_request_clears_only_the_planning_owner(self):
        ctx=self.focus();ctx['pending_public_query']={'question':'old'};ctx['dialogue']=[{'question':'old'}]
        before=copy.deepcopy(ctx);new=planning_context('另开独立问题：直接部件有哪些？',ctx,self.store)
        self.assertNotIn('entity',new);self.assertNotIn('relational_state',new);self.assertNotIn('pending_public_query',new)
        self.assertEqual(ctx,before)
    def test_literal_root_replacement_inherits_depth_from_single_collection(self):
        q='将主体替为 E，其他查询要求不动';raw={'version':2,'handled':True,'mode':'new','tasks':[{'id':1,'action':'new','quote':q,'root':{'type':'literal','tree':'config','field':'code','value':'E','quote':'E'},'set':{'kind':'collection','population':'parts','depth':'all'},'filters':[],'classes':[]}]}
        p,_=compile_delta(normalize_delta(raw,q,self.focus(),self.store)[0],q,self.focus(),self.store)
        self.assertEqual(p['tasks'][0]['spec']['root']['value'],'E');self.assertEqual(p['tasks'][0]['spec']['depth'],'direct')
    def test_no_execution_command_is_not_turned_into_scope_execution(self):
        q='只保留直接部件条件，不查询';raw={'version':2,'handled':True,'mode':'update','tasks':[{'id':1,'action':'retain'}]}
        new,_=normalize_delta(raw,q,self.focus(),self.store);self.assertEqual(new['tasks'][0]['action'],'retain')


if __name__=='__main__': unittest.main()
