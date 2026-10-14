"""独立原话门禁反例：两份一致计划共同遗漏也不能获得执行许可。"""
import copy,json,sys,unittest,threading,urllib.request,urllib.error
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from question_coverage import audit,obligations,CoverageInvalid
from request_gateway import seal,require_verified
from business_request import RequestInvalid
from relational_query import canonical
import test_relational_query as fixture


def f(field,value,op='equals'):return {'field':field,'operator':op,'value':value}
def single(filters=(),**kw):
    return {'operation':'search','entity':None,'scope':'direct','clarification':'',
            'query':{'target':'points','filters':list(filters)},**kw}
def relation(filters=(),**kw):
    spec=canonical({'kind':'collection','population':'points','root':None,'filters':list(filters),**kw})
    return {'operation':'relational','entity':None,'scope':'direct','clarification':'','relational_tasks':[{'id':1,'spec':spec}]}


class Coverage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):fixture.Relations.setUpClass();cls.s=fixture.Relations.s
    def blocked(self,q,p,ctx=None,trace=None):
        with self.assertRaises(CoverageInvalid) as error:audit(self.s,q,p,ctx,trace)
        self.assertEqual(error.exception.report['status'],'blocked')
        return error.exception.report
    def test_two_identical_model_plans_omit_time_for_both_protocols(self):
        for make in (single,relation):
            candidate=make([f('source','S')]);independent=copy.deepcopy(candidate)
            self.assertEqual(candidate,independent)
            seal(self.s,'来源等于S，测量时间在2025年',candidate)
            with self.assertRaises(CoverageInvalid):require_verified(self.s,'来源等于S，测量时间在2025年',candidate)
    def test_actual_dual_extraction_convergence_cannot_bypass_raw_coverage(self):
        import relational_planner as planner
        q='查询全表监测原记录，来源等于S，测量时间在2025年';bad={'handled':True,'tasks':relation([f('source','S')])['relational_tasks']}
        def extract(question,context,key,model,record,**kw):
            record.update(extracted=copy.deepcopy(bad),model='synthetic-independent' if kw.get('_independent') else 'synthetic-candidate');return copy.deepcopy(bad)
        with patch.object(planner,'extract',side_effect=extract) as pair:
            plan,trace=planner.interpret(q,{},'not-sent',self.s)
        self.assertEqual(pair.call_count,2);self.assertEqual(trace['candidate']['extracted'],trace['independent']['extracted'])
        planner.bind(self.s,q,plan,{},trace)
        with self.assertRaises(CoverageInvalid):require_verified(self.s,q,plan,{},trace)
    def test_single_missing_source(self):self.blocked('来源等于S，测量值大于5',single([f('value','5','gt')]))
    def test_relational_missing_source(self):self.blocked('来源等于S，测量值大于5',relation([f('value','5','gt')]))
    def test_wrong_operator_rejected_for_both_protocols(self):
        for make in (single,relation):self.blocked('测量值不超过5',make([f('value','5','lt')]))
    def test_exact_numeric_boundary_is_covered(self):
        for make in (single,relation):self.assertEqual(audit(self.s,'测量值不超过5',make([f('value','5.0','lte')]))['status'],'covered')
    def test_scientific_notation_is_mathematical_not_text_equality(self):self.assertEqual(audit(self.s,'测量值大于5e0',single([f('value','5.000','gt')]))['status'],'covered')
    def test_year_equivalent_half_open_range(self):
        fs=[f('source','S'),f('time','2025-01-01','date_gte'),f('time','2026-01-01','date_lt')]
        for make in (single,relation):self.assertEqual(audit(self.s,'来源等于S，测量时间在2025年',make(fs))['status'],'covered')
    def test_year_wrong_end_does_not_cover(self):self.blocked('测量时间在2025年',single([f('time','2025-01-01','date_gte'),f('time','2025-12-31','date_lt')]))
    def test_month_is_not_instant(self):self.blocked('测量时间在2025年6月',single([f('time','2025-06-01','equals')]))
    def test_day_unpadded_text_matches_calendar_period(self):self.assertEqual(audit(self.s,'测量时间在2025年6月3日',single([f('time','2025-06-03','date_equals')]))['status'],'covered')
    def test_timestamp_cannot_expand_to_whole_day(self):self.blocked('测量时间等于2025/6/3 8:00',single([f('time','2025-06-03','date_equals')]))
    def test_explicit_unparsed_condition_stops_execution(self):self.blocked('测量时间在尚未确定的时间范围',single())
    def test_value_read_question_is_not_filter(self):self.assertEqual(obligations('测量值是多少，测量时间是什么'),[])
    def test_explanation_is_not_filter(self):self.assertEqual(obligations('解释测量值大于5是什么意思'),[])
    def test_quoted_name_does_not_create_depth(self):
        report=audit(self.s,'名称包含“全部后代”',single([f('name','全部后代','contains')]))
        self.assertEqual([o['kind'] for o in report['obligations']],['filter'])
    def test_background_not_constraint(self):self.assertEqual(obligations('上次测量值大于5，这次查所有测点'),[])
    def test_negative_history_does_not_provide_all_depth(self):
        p=relation(root={'tree':'config','field':'code','value':'D'},population='parts',depth='direct')
        self.assertEqual(audit(self.s,'直属部件，不沿用以前全部后代范围',p)['status'],'covered')
    def test_direct_does_not_cover_all(self):self.blocked('全部后代部件',relation(root={'tree':'config','field':'code','value':'D'},population='parts',depth='direct'))
    def test_all_does_not_cover_direct(self):self.blocked('直属部件',relation(root={'tree':'config','field':'code','value':'D'},population='parts',depth='all'))
    def test_group_is_required(self):self.blocked('按来源分组',single())
    def test_relational_group_covered(self):self.assertEqual(audit(self.s,'按来源分组',relation(group_by='source'))['status'],'covered')
    def test_limit_required(self):self.blocked('返回前10条',single())
    def test_sort_direction_required(self):self.blocked('按测量时间从新到旧',single(result_goal={'kind':'sort','field':'time','direction':'asc','limit':10}))
    def test_sort_and_limit_covered(self):self.assertEqual(audit(self.s,'按测量时间从新到旧，返回前10条',single(result_goal={'kind':'sort','field':'time','direction':'desc','limit':10}))['status'],'covered')
    def test_shared_omission_remove_old_filter(self):self.blocked('取消来源条件',single([f('source','S')]))
    def test_remove_predicate_keeps_other_same_field_conditions(self):self.assertEqual(audit(self.s,'撤掉“测量值大于0”',single([f('value','10','lt')]))['status'],'covered')
    def test_cancel_group_must_not_remove_source_filter(self):self.assertEqual(audit(self.s,'取消来源分组',single([f('source','S')]))['status'],'covered')
    def test_cancel_group_not_covered_by_retaining_group(self):self.blocked('取消来源分组',relation(group_by='source'))
    def test_class_name_is_dictionary_constraint(self):
        p=relation(root={'tree':'config','field':'code','value':'D'},population='parts',classes={'part_class':'BC'})
        self.assertEqual(audit(self.s,'部件类名称为“部件分类”',p)['status'],'covered')
    def test_blank_value_condition(self):
        for make in (single,relation):self.assertEqual(audit(self.s,'测量值为空的记录',make([f('value','','is_blank')]))['status'],'covered')
    def test_cancel_blank_value_condition(self):self.assertEqual(audit(self.s,'取消测量值为空的条件',single())['status'],'covered')
    def test_keep_depth_compares_actual_previous_state(self):
        p=relation(root={'tree':'config','field':'code','value':'D'},population='parts',depth='direct')
        self.blocked('换对象，范围照旧',p,{'scope':'all'})
        self.assertEqual(audit(self.s,'换对象，范围照旧',p,{'scope':'direct'})['status'],'covered')
    def test_conditions_cannot_be_split_across_tasks_even_after_comma(self):
        p={'operation':'batch','tasks':[{'question':'one','intent':single([f('source','S')])},{'question':'two','intent':single([f('value','5','gt')])}]}
        self.blocked('来源等于S，测量值大于5',p)
    def test_numbered_task_conditions_cannot_leak_to_other_task(self):
        p={'operation':'batch','tasks':[{'question':'one','intent':single([f('value','5','gt')])},{'question':'two','intent':single([f('source','S')])}]}
        self.blocked('第一项来源等于S，第二项测量值大于5',p)
    def test_numbered_conditions_on_correct_task(self):
        p={'operation':'batch','tasks':[{'question':'one','intent':single([f('source','S')])},{'question':'two','intent':single([f('value','5','gt')])}]}
        self.assertEqual(audit(self.s,'第一项来源等于S，第二项测量值大于5',p)['status'],'covered')
    def test_compiled_task_lineage_preserves_original_second_task_number(self):
        trace={'changed_tasks':['t2'],'business_request_state':{'tasks':[{'id':'t1'},{'id':'t2'}]}}
        self.assertEqual(audit(self.s,'第二项取消测量值为空的条件',single(),trace=trace)['status'],'covered')
    def test_clarification_never_claims_execution_is_covered(self):self.assertEqual(audit(self.s,'测量值大于5',{'operation':'clarify'})['status'],'not_executed')
    def test_failing_coverage_consumes_old_permission(self):
        p=single();q='测量值大于5';seal(self.s,q,p)
        with self.assertRaises(CoverageInvalid):require_verified(self.s,q,p)
        with self.assertRaises(RequestInvalid):require_verified(self.s,q,p)
    def test_explicit_input_tree_cannot_be_swapped_to_same_code_other_tree(self):
        self.blocked('查询构型树D的直属部件',relation(root={'tree':'equipment_class','field':'code','value':'D'},population='parts',depth='direct'))
    def test_explicit_input_tree_and_name_alias_are_covered(self):
        p=relation(root={'tree':'config','field':'code','value':'D'},population='parts',depth='direct')
        self.assertEqual(audit(self.s,'查询构型树设备模板的直属部件',p)['status'],'covered')
    def test_independent_request_cannot_copy_unmentioned_old_filter(self):
        self.blocked('独立问题，查询测点',single([f('source','S')]),{'query':{'target':'points','filters':[f('source','S')]}})
    def test_independent_explicit_repetition_is_current_requirement(self):
        self.assertEqual(audit(self.s,'独立问题，来源等于S',single([f('source','S')]),{'query':{'target':'points','filters':[f('source','S')]}})['status'],'covered')
    def test_independent_without_root_cannot_copy_old_root(self):
        self.blocked('独立问题，查询直属部件',relation(root={'tree':'config','field':'code','value':'D'},population='parts',depth='direct'),{'entity':{'tree':'config','code':'D'}})
    def test_unary_blank_condition_cannot_be_omitted(self):self.blocked('测量值不为空',single())
    def test_unary_blank_condition_correctly_covered(self):self.assertEqual(audit(self.s,'测量值不为空',single([f('value','','not_blank')]))['status'],'covered')
    def test_registered_value_selector_is_not_dropped(self):self.blocked('只看开启的测点',single())
    def test_missing_field_records_retention_is_not_old_filter_retention(self):self.assertEqual(audit(self.s,'未提供状态保留',single())['status'],'covered')
    def test_missing_field_records_cannot_be_silently_excluded(self):self.blocked('未提供状态保留',single([f('status','','not_blank')]))
    def test_registered_value_selector_has_exact_field(self):self.assertEqual(audit(self.s,'只看开启的测点',single([f('switch','开启')]))['status'],'covered')
    def test_quoted_name_can_contain_explanation_words(self):self.blocked('名称包含“为什么”',single())
    def test_explicit_unknown_field_is_not_silently_discarded(self):self.blocked('检修次数大于2',single())
    def test_quantity_scale_cannot_be_truncated(self):self.blocked('测量值大于5万',single([f('value','5','gt')]))
    def test_unparsed_interval_cannot_be_truncated(self):self.blocked('测量时间在2025年到2026年',single([f('time','2025','date_equals')]))
    def test_unknown_unit_cannot_be_discarded(self):self.blocked('测量值大于5someUnit',single([f('value','5','gt')]))
    def test_unknown_chinese_unit_cannot_be_discarded(self):self.blocked('测量值大于5安培',single([f('value','5','gt')]))
    def test_temporal_modifier_cannot_be_discarded(self):self.blocked('测量时间在2025年之后',single([f('time','2025','date_equals')]))
    def test_calendar_period_suffixes_preserve_precision(self):
        for text,value in [('测量时间在2025年内','2025'),('测量时间在2025年5月份','2025-05'),('测量时间在2025年5月3日当天','2025-05-03')]:self.assertEqual(audit(self.s,text,single([f('time',value,'date_equals')]))['status'],'covered')
    def test_bare_calendar_modifier_cannot_be_discarded(self):self.blocked('只看2025年及以后的测点',single([f('time','2025','date_equals')]))
    def test_unknown_text_field_condition_cannot_be_omitted(self):self.blocked('生产厂家等于甲',single())
    def test_known_unit_with_unrecognized_trailing_text_is_not_partial(self):self.blocked('测量值大于5摄氏度附近',single([f('value','5','gt'),f('unit','℃')]))
    def test_numeric_unit_is_part_of_same_requirement(self):self.blocked('测量值大于5摄氏度',single([f('value','5','gt')]))
    def test_unit_alias_is_covered(self):self.assertEqual(audit(self.s,'测量值大于5摄氏度',single([f('value','5','gt'),f('unit','℃')]))['status'],'covered')
    def test_symbolic_operator_cannot_be_omitted(self):self.blocked('测量值>=5',single())
    def test_symbolic_operator_is_covered(self):self.assertEqual(audit(self.s,'测量值>=5',single([f('value','5','gte')]))['status'],'covered')
    def test_do_not_execute_cannot_be_swallowed(self):self.blocked('只保存条件，不要执行查询',single())
    def test_stop_control_inside_name_is_not_action(self):self.assertEqual(audit(self.s,'名称等于“不要执行查询”',single([f('name','不要执行查询')]))['status'],'covered')
    def test_do_not_inherit_filter_is_remove_control(self):self.blocked('不要沿用来源条件',single([f('source','S')]))
    def test_condition_change_keeps_comparison_semantics(self):self.blocked('测量值条件改为小于1',single([f('value','1','lte')]))
    def test_assignment_change_cannot_be_omitted(self):self.blocked('来源条件改成S',single())
    def test_assignment_change_has_current_value_proof(self):self.assertEqual(audit(self.s,'来源条件改成S',single([f('source','S')]))['status'],'covered')
    def test_quoted_punctuation_keeps_literal_span(self):self.assertEqual(audit(self.s,'名称等于“甲，乙；丙”',single([f('name','甲，乙；丙')]))['status'],'covered')
    def test_unclosed_literal_is_not_partial_condition(self):self.blocked('名称等于“甲',single([f('name','甲')]))
    def test_bare_calendar_selector_cannot_be_omitted(self):self.blocked('只看2025年的测点记录',single())
    def test_bare_calendar_selector_is_covered(self):self.assertEqual(audit(self.s,'只看2025年的测点记录',single([f('time','2025','date_equals')]))['status'],'covered')
    def test_bare_calendar_with_wrong_year_is_not_covered(self):self.blocked('只看2025年的测点记录',single([f('time','2024','date_equals')]))


class CoverageHttp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import app
        fixture.Relations.setUpClass();cls.s=fixture.Relations.s;cls.app=app;cls.old=app.STORE;app.STORE=cls.s
        cls.server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler);cls.url=f'http://127.0.0.1:{cls.server.server_port}'
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
    @classmethod
    def tearDownClass(cls):cls.server.shutdown();cls.server.server_close();cls.app.STORE=cls.old;cls.s.db.close()
    def test_identical_missing_condition_never_executes_or_commits_on_actual_http(self):
        import model
        for make in (single,relation):
            p=make([f('source','S')]);q='来源等于S，测量时间在2025年';sid='coverage-'+make.__name__
            def bind(store,question,plan,context):seal(store,question,plan);return plan
            with patch.object(self.app,'interpret',return_value=p),patch.object(model,'bind_references',side_effect=bind),patch.object(self.app,'execute_plan') as execute:
                req=urllib.request.Request(self.url+'/api/query',data=json.dumps({'session':sid,'question':q,'trace':True}).encode(),headers={'X-Demo-Token':self.app.TOKEN,'Content-Type':'application/json'})
                with self.assertRaises(urllib.error.HTTPError) as error:urllib.request.urlopen(req)
                self.assertEqual(error.exception.code,400);response=json.load(error.exception)
                self.assertEqual(response['error_code'],'coverage_incomplete')
                self.assertEqual(response['question_coverage']['status'],'blocked')
                self.assertIn('尚未执行',response['error']);execute.assert_not_called()
                self.assertNotIn('relational_state',self.app.SESSIONS[sid]['context'])
                self.assertNotIn('business_request',self.app.SESSIONS[sid]['context'])
    def test_shared_omission_preserves_existing_successful_context(self):
        import model
        p=single();q='来源等于S';sid='coverage-keep-success';old={'entity':{'tree':'config','code':'D'},'scope':'all','query':{'target':'points','filters':[f('source','S')]}}
        self.app.SESSIONS[sid]={'context':copy.deepcopy(old),'results':{},'busy':False,'last_success':{'status':'ok'}}
        def bind(store,question,plan,context):seal(store,question,plan);return plan
        with patch.object(self.app,'interpret',return_value=p),patch.object(model,'bind_references',side_effect=bind),patch.object(self.app,'execute_plan') as execute:
            req=urllib.request.Request(self.url+'/api/query',data=json.dumps({'session':sid,'question':q}).encode(),headers={'X-Demo-Token':self.app.TOKEN,'Content-Type':'application/json'})
            with self.assertRaises(urllib.error.HTTPError):urllib.request.urlopen(req)
            execute.assert_not_called();self.assertEqual(self.app.SESSIONS[sid]['context'],old)
            self.assertEqual(self.app.SESSIONS[sid]['last_success'],{'status':'ok'})


if __name__=='__main__':unittest.main()
