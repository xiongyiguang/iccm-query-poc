"""跨表契约用不同结构的合成数据验证，预期不由被测查询生成。"""
import copy
import sys
import unittest
from unittest.mock import patch
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from data import Store,QueryError
from relational_query import Graph,canonical,execute_task,execute,validate_plan
from relational_planner import ground,normalized


def obj(code,parent,name,kind,cls=None,config=False):
    r={'对象代码':code,'父对象代码':parent,'对象描述中文':name,'对象层级':kind}
    if config:r.update(对象层级='7',对象层级描述=kind,所属部件类代码=cls or '')
    return r


class Relations(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rows={'pbs':[obj('L','','位置','功能位置'),obj('L&D','L','设备','设备'),
            obj('L&D#p1','L&D','部件一','部件'),obj('L&D#p2','L&D#p1','缺构型','部件'),
            obj('L&D#p3','L&D','错类型','部件'),obj('L&D#p4','L&D','空分类','部件'),
            obj('UNRELATED','L&D#p1','点结构','时序测点')],
            'config':[obj('EC','','构型根','设备类',config=True),obj('D','EC','设备模板','设备',config=True),
                obj('D#p1','D','模板一','部件','BC',True),obj('D#p3','D','子设备模板','子设备','BC',True),
                obj('D#p4','D','空分类模板','部件',None,True)],
            'equipment_class':[{'对象编码':'EC','父对象编码':'TOP','描述':'设备分类','层级':'3'},{'对象编码':'TOP','父对象编码':'','描述':'上级分类','层级':'2'}],
            'part_class':[{'对象编码':'BC','父对象编码':'','对象描述中文':'部件分类','对象层级':'4'}],
            'points':[{'测量点编码':'UNRELATED','测量点名称':'点一','源系统':'S','开关':'开启','状态':'','真实值报警阈值-高2':'1','估计值报警阈值-高2':'300'},
                {'测量点编码':'UNRELATED','测量点名称':'点二','源系统':'S','开关':'开启','状态':'已报警'},
                {'测量点编码':'L.FAKE','测量点名称':'没有PBS','源系统':'S','开关':'开启','状态':'已报警'}]}
        cls.s=Store(dataset=[{'kind':k,'file':k+'.csv','sha256':k,'rows':v,'seed':True} for k,v in rows.items()])
    def setUp(self):self.g=Graph(self.s)
    def q(self,**kw):
        return canonical({'root':{'tree':'pbs','field':'code','value':'L&D'},'kind':'collection','population':'objects' if kw.get('kind')=='relation' else 'parts',**kw})
    def runq(self,**kw):return execute_task(self.g,self.q(**kw))
    def test_pbs_grain_includes_missing_and_mismatched(self):
        r=self.runq(group_by='class');self.assertEqual(r['population_facts']['part_total'],4);self.assertEqual(r['classification_coverage'],{'complete':False,'total':4,'resolved':1,'unresolved':3})
    def test_direct_is_real_edge(self):self.assertEqual(self.runq(depth='direct')['population_facts']['record_count'],3)
    def test_config_grain_is_separate(self):
        r=self.runq(root={'tree':'config','field':'code','value':'D'});self.assertEqual(r['population_facts']['record_count'],2)
    def test_missing_part_never_inherits_parent_class(self):
        r=self.g.objects[('pbs','L&D#p2')];links=self.g.links(r);self.assertIsNone(links['config']);self.assertIsNone(links['part_class']);self.assertEqual(links['equipment_class']['code'],'EC')
    def test_existing_entry_missing_config_fails_closed(self):
        with self.assertRaises(QueryError):self.s.config({'tree':'pbs','code':'L&D#p2'},[])
    def test_mismatch_not_compatible(self):self.assertIsNone(self.g.config(self.g.objects[('pbs','L&D#p3')]))
    def test_blank_class_is_unknown(self):self.assertIn('未提供',self.g.links(self.g.objects[('pbs','L&D#p4')])['classification_reason'])
    def test_class_name_resolved_dictionary(self):self.assertEqual(self.runq(classes={'part_class':'部件分类'})['population_facts']['record_count'],1)
    def test_unknown_class_is_not_zero(self):
        with self.assertRaises(QueryError):self.runq(classes={'part_class':'不存在'})
    def test_reverse_device_class(self):self.assertEqual(self.runq(population='devices',root={'tree':'pbs','field':'code','value':'L'},classes={'equipment_class':'设备分类'})['population_facts']['record_count'],1)
    def test_five_table_points(self):self.assertEqual(self.runq(population='points',classes={'equipment_class':'EC','part_class':'BC'})['population_facts']['record_count'],2)
    def test_duplicate_records_preserved(self):
        r=self.runq(population='points',root={'tree':'points','field':'code','value':'UNRELATED'},group_by='source');self.assertEqual((r['population_facts']['record_count'],r['population_facts']['distinct_code_count']),(2,1));self.assertEqual([r['line'] for r in r['record_facts']],[2,3]);self.assertEqual(r['groups'][0]['distinct_code_count'],1)
    def test_exact_point_link_ignores_prefix(self):
        r=self.runq(population='points',root=None,only='unmatched');self.assertEqual([r['code'] for r in r['record_facts']],['L.FAKE'])
    def test_point_scope_retains_root_and_alarm(self):
        r=self.runq(population='points',filters=[{'field':'switch','operator':'equals','value':'开启'},{'field':'status','operator':'equals','value':'已报警'},{'field':'source','operator':'equals','value':'S'}]);self.assertEqual([r['name'] for r in r['record_facts']],['点二'])
    def test_threshold_families_and_blank(self):
        q=self.q(root={'tree':'points','field':'name','value':'点一'},kind='relation',properties=['actual_high2','estimate_high2','time']);r=execute_task(self.g,q);self.assertEqual(r['field_projection'][0]['values'],{'actual_high2':'1','estimate_high2':'300','time':'未提供'})
    def test_top_is_display_only(self):
        r=self.runq(group_by='class',limit=1);self.assertEqual(r['population_facts']['part_total'],4);self.assertEqual(len(r['population_facts']['unresolved_parts']),3)
    def test_compare_both_types_and_missing(self):
        r=self.runq(kind='compare',compare_root={'tree':'config','field':'code','value':'D'});self.assertEqual(len(r['comparison']['issues']),2);self.assertEqual(r['comparison']['pbs_count'],4)
    def test_same_code_two_trees_distinct(self):
        a=self.g.resolve({'tree':'config','field':'code','value':'EC'});b=self.g.resolve({'tree':'equipment_class','field':'code','value':'EC'});self.assertNotEqual(a['name'],b['name'])
    def test_health_zero_not_diagnosis(self):self.assertIn('不能证明',self.runq(kind='boundary',population='points',boundary='health',filters=[{'field':'status','operator':'equals','value':'不存在'}])['answer'])
    def test_duration_not_zero(self):
        r=self.runq(kind='boundary',population='points',boundary='duration');self.assertEqual(r['status'],'data_insufficient');self.assertEqual(r['metrics'],[])
    def test_health_covers_all_records_and_active_alarms(self):
        r=self.runq(kind='boundary',population='points',boundary='health',filters=[{'field':'status','operator':'equals','value':'已报警'}])
        self.assertEqual(r['health_snapshot'],{'monitored_records':2,'monitored_codes':1,'active_alarm_records':1,'healthy_proven':False})
    def test_health_preserves_source_and_root(self):
        q=self.q(kind='boundary',population='points',boundary='health',filters=[{'field':'source','operator':'equals','value':'S'},{'field':'switch','operator':'equals','value':'开启'}])
        self.assertEqual(q['root']['value'],'L&D');self.assertEqual(q['filters'],[{'field':'source','operator':'equals','value':'S'}])
    def test_invalid_comparison_not_silently_executed(self):
        with self.assertRaises(ValueError):self.q(root={'tree':'config','field':'code','value':'EC'},kind='compare',compare_root={'tree':'equipment_class','field':'code','value':'EC'})
    def test_same_record_cannot_be_unimplemented_boundary(self):
        with self.assertRaises(ValueError):self.q(kind='boundary',boundary='same_record')
    def test_exact_point_collection_depth_equivalent(self):
        a=self.q(root={'tree':'points','field':'code','value':'UNRELATED'},population='points',depth='all')
        b=self.q(root={'tree':'points','field':'code','value':'UNRELATED'},population='points',depth='self')
        self.assertEqual(a,b)
    def test_independent_ambiguity_delegates_without_executing_candidate(self):
        import relational_planner
        a={'handled':True,'tasks':[{'id':1,'spec':self.q()}]}
        with patch('relational_planner.extract',side_effect=[a,{'handled':False}]) as call:
            self.assertIsNone(relational_planner.interpret('L&D下面有多少东西',{},'synthetic-key',self.s))
        self.assertEqual(call.call_count,2);self.assertTrue(call.call_args.kwargs['_independent'])
    def test_group_record_shape_keeps_public_contract(self):
        r=self.runq(population='points',root=None,group_by='location')
        self.assertEqual(r['columns'][:2],['描述','分组编码']);self.assertEqual(r['records'][0]['cells'][1],'L')
    def test_business_headers_are_chinese(self):
        r=self.runq(population='points');self.assertIn('原CSV行号',r['columns']);self.assertNotIn('line',r['columns'])
    def test_unrooted_depth_has_no_tree_scope_meaning(self):
        self.assertEqual(self.q(root=None,population='points',depth='self'),self.q(root=None,population='points',depth='all'))
    def test_classification_boundary_always_retains_missing_objects(self):
        q=self.q(kind='boundary',boundary='classification');r=execute_task(self.g,q)
        self.assertEqual(q['only'],'missing_class');self.assertEqual(len(r['records']),3)
    def test_exact_name_and_code_bind_same_object(self):
        from relational_planner import bound_semantics
        a={'handled':True,'tasks':[{'id':1,'spec':self.q(root={'tree':'points','field':'name','value':'点一'},population='points')}]}
        b=copy.deepcopy(a);b['tasks'][0]['spec']['root']={'tree':'points','field':'code','value':'UNRELATED'}
        self.assertEqual(bound_semantics(a,self.s),bound_semantics(b,self.s));self.assertEqual(a['tasks'][0]['spec']['root']['field'],'name')
    def test_binding_does_not_equate_filters_with_same_current_results(self):
        from relational_planner import bound_semantics
        a={'handled':True,'tasks':[{'id':1,'spec':self.q(population='points',filters=[{'field':'source','operator':'equals','value':'S'}])}]}
        b=copy.deepcopy(a);b['tasks'][0]['spec']['filters']=[]
        self.assertNotEqual(bound_semantics(a,self.s),bound_semantics(b,self.s))
    def test_bound_plan_rechecked_against_both_raw_extractions(self):
        from relational_planner import bound_semantics,bind
        a={'handled':True,'tasks':[{'id':1,'spec':self.q(root={'tree':'pbs','field':'name','value':'设备'})}]}
        b=copy.deepcopy(a);b['tasks'][0]['spec']['root']={'tree':'pbs','field':'code','value':'L&D'}
        plan={'operation':'relational','entity':None,'scope':'direct','clarification':'','relational_tasks':bound_semantics(a,self.s)['tasks']}
        context={'entity':{'tree':'pbs','code':'L&D'}}
        trace={'engine':'relational_request','source_question':'设备的部件','validated_intent':copy.deepcopy(plan),'candidate':{'extracted':a},'independent':{'extracted':b}}
        self.assertEqual(bind(self.s,'设备的部件',plan,context,trace),plan)
        plan['relational_tasks'][0]['spec']['depth']='direct'
        with self.assertRaises(ValueError):bind(self.s,'设备的部件',plan,context,trace)
    def test_ground_unique_catalog_name_to_code_without_inventing_identity(self):
        ground([{'spec':self.q(classes={'part_class':'BC'})}],'该范围仅查部件分类',{'entity':{'code':'L&D'}},self.s)
        ground([{'spec':self.q(root={'tree':'points','field':'code','value':'UNRELATED'},kind='relation')}],'点一的实际父对象',{},self.s)
    def test_ground_rejects_truncated_point_name(self):
        with self.assertRaises(ValueError):ground([{'spec':self.q(root={'tree':'points','field':'name','value':'测点3'},kind='relation')}],'查测点30',{},self.s)
    def test_ground_unknown_numeric_class_is_not_an_alias(self):
        with self.assertRaises(ValueError):ground([{'spec':self.q(classes={'part_class':'123'})}],'部件类描述123',{'entity':{'code':'L&D'}},self.s)
    def test_missing_class_rows_have_explicit_reason_column(self):
        r=self.runq(group_by='class');self.assertEqual(r['columns'][-1],'关联说明');self.assertTrue(all(len(x['cells'])==len(r['columns']) for x in r['records']))
    def test_same_record_flag_needs_distinct_original_tables(self):
        p={'operation':'relational','entity':None,'scope':'direct','clarification':'','relational_tasks':[{'id':1,'spec':self.q(kind='relation',boundary='same_record')}]}
        with self.assertRaises(ValueError):validate_plan(p)
    def test_unknown_slot_rejected(self):
        with self.assertRaises(ValueError):canonical({'sql':'SELECT *'})
    def test_invented_root_rejected(self):
        with self.assertRaises(ValueError):ground([{'spec':self.q()}],'查询设备',{})
    def test_confirmed_role_can_be_followup_root(self):
        tasks=[{'spec':self.q(root={'tree':'equipment_class','field':'code','value':'EC'},kind='relation')}];ground(tasks,'上一级',{'relational_state':{'tasks':[{'resolved':{'equipment_class':[{'tree':'equipment_class','code':'EC','name':'设备分类'}]}}]}})
    def test_two_tasks_keep_identity(self):
        tasks=[{'id':1,'spec':self.q(kind='relation')},{'id':2,'spec':self.q(root={'tree':'config','field':'code','value':'D'})}];r=execute(self.s,{'relational_tasks':tasks});self.assertEqual([t['id'] for t in r['relational_state']['tasks']],[1,2]);self.assertEqual(r['items'][1]['population_facts']['record_count'],2)
    def test_type_alias_is_population_equivalent(self):
        self.assertEqual(self.q(population='objects',filters=[{'field':'type','operator':'equals','value':'部件'}]),self.q(population='parts'))
    def test_default_sort_equals_explicit_code(self):self.assertEqual(self.q(),self.q(sort=['code']))
    def test_class_projection_already_delivered(self):self.assertEqual(self.q(group_by='class'),self.q(group_by='class',properties=['code','name','class_code']))
    def test_point_relation_preserves_identity_despite_population_alias(self):
        a=canonical({'root':{'tree':'points','field':'name','value':'点一'},'kind':'relation','population':'points'});b=canonical({'root':{'tree':'points','field':'name','value':'点一'},'kind':'relation'});self.assertEqual(a,b)
    def test_collection_alias_does_not_discard_scope(self):
        q=canonical({'root':{'tree':'pbs','field':'code','value':'L'},'kind':'relation','population':'points','classes':{'part_class':'BC'}});self.assertEqual(q['kind'],'collection');self.assertEqual(q['classes'],{'part_class':'BC'});self.assertEqual(q['root']['value'],'L')
    def test_relation_must_not_swallow_filters(self):
        with self.assertRaises(ValueError):canonical({'root':{'tree':'pbs','field':'code','value':'L'},'kind':'relation','filters':[{'field':'name','operator':'equals','value':'设备'}]})
    def test_numeric_line_sort_not_lexicographic(self):
        rows=[{**self.s.rows('SELECT * FROM points')[0],'tree':'points'}];row=rows[0];a={**row,'line':3};b={**row,'line':13};self.s.point_refs[13]=('points.csv',13)
        self.assertEqual([r['line'] for r in self.g.sort_rows([b,a],['line'])],[3,13])
    def test_independent_mismatch_never_executes(self):
        import relational_planner
        a={'handled':True,'tasks':[{'id':1,'spec':self.q()}]};b=copy.deepcopy(a);b['tasks'][0]['spec']['depth']='direct'
        with patch('relational_planner.extract',side_effect=[a,b,a,b]) as call,self.assertRaises(ValueError):
            relational_planner.interpret('L&D的部件',{},'synthetic-key',self.s)
        self.assertEqual(call.call_count,4)
        self.assertNotIn('candidate',call.call_args.args[1]);self.assertNotIn('independent',call.call_args.args[1])
    def test_point_default_sort_equals_owner_and_code(self):
        self.assertEqual(self.q(population='points'),self.q(population='points',sort=['pbs_part','code']))
    def test_nonrelational_fallback_needs_one_route_only(self):
        import relational_planner
        with patch('relational_planner.extract',return_value={'handled':False}) as call:self.assertIsNone(relational_planner.interpret('你好',{},'synthetic-key',self.s));self.assertEqual(call.call_count,1)
    def test_grounded_filter_label_cannot_be_truncated(self):
        import relational_planner
        q=self.q(population='points',root=None,filters=[{'field':'source','operator':'equals','value':'bad'}]);a={'handled':True,'tasks':[{'id':1,'spec':q}]}
        with patch('relational_planner.extract',return_value=a),self.assertRaises(ValueError):relational_planner.interpret('源系统 S 的测点',{},'synthetic-key',self.s)


    def test_point_followup_keeps_exact_query_without_illegal_entity(self):
        from query_plan import task_context
        for kind in ('relation','collection'):
            q=self.q(kind=kind,population='points',root={'tree':'points','field':'name','value':'点一'})
            p={'operation':'relational','relational_tasks':[{'id':1,'spec':q}]};r=execute(self.s,p);c=task_context(p,r)
            self.assertIsNone(c['entity']);self.assertEqual(c['scope'],'direct')
            self.assertEqual(c['query'],{'target':'points','filters':[{'field':'name','operator':'equals','value':'点一'}]})
            self.assertEqual(c['relational_state']['tasks'][0]['spec']['root']['value'],'点一')
    def test_batch_point_focus_is_safe_and_preserves_other_task(self):
        tasks=[{'id':1,'spec':self.q(kind='relation',root={'tree':'points','field':'code','value':'UNRELATED'})},{'id':2,'spec':self.q()}]
        r=execute(self.s,{'relational_tasks':tasks});c=r['items'][0]['task_context']
        self.assertIsNone(c['entity']);self.assertEqual(c['query']['filters'][0]['value'],'UNRELATED');self.assertEqual(len(c['relational_state']['tasks']),2)
    def test_scalar_point_projection_delegates_with_prior_relation(self):
        import relational_planner
        for kind in ('relation','collection'):
            q=self.q(kind=kind,population='points',root={'tree':'points','field':'name','value':'点一'},properties=['actual_high2','estimate_high2','time'])
            with patch('relational_planner.extract',return_value={'handled':True,'tasks':[{'id':1,'spec':q}]}) as call:
                self.assertIsNone(relational_planner.interpret('只给它的原字段',{'relational_state':{'tasks':[]}},'synthetic-key',self.s));self.assertEqual(call.call_count,1)
    def test_point_filter_collection_remains_relational(self):
        import relational_planner
        q=self.q(population='points',root={'tree':'points','field':'code','value':'UNRELATED'},properties=['actual_high2'],filters=[{'field':'status','operator':'equals','value':'已报警'}])
        with patch('relational_planner.extract',return_value={'handled':True,'tasks':[{'id':1,'spec':q}]}) as call:
            plan,_=relational_planner.interpret('UNRELATED只看已报警的高2',{},'synthetic-key',self.s)
            self.assertEqual(plan['operation'],'relational');self.assertEqual(call.call_count,2)
        r=execute(self.s,plan);self.assertEqual(len(r['query']['filters']),2);self.assertEqual(r['query']['filters'][0]['value'],'UNRELATED')


if __name__=='__main__':unittest.main()
