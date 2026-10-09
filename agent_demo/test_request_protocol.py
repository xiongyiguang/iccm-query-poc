"""智能体公共任务协议的离线回归；直接执行真实脱敏快照，不请求模型。"""
import copy
import csv
from decimal import Decimal
from pathlib import Path
import unittest
from tools import DataTools, TOOLS
from answers import has_delivery, receipt_answer
from presentation import tool_view


def goal(kind='records', **values):
    return {'kind':kind,'field':None,'direction':None,'limit':None,'ties':'all','operands':[],'basis':'measurement',**values}


def patch(q, kind='records', filters=None, **settings):
    return {'base':None,'quote':q,'subject':None,'execute':True,'parent_range':'all_imported','set':{'operation':'search','target':'points','properties':[],
            'result_goal':goal(kind),**settings},'filters':[] if not filters else [
            {'action':'add','ids':[],'conditions':filters,'quote':q}], 'purpose':'data','subject_scope':'none'}


def condition(field, op, value):return {'field':field,'operator':op,'value':value}


class RequestContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.data=DataTools()

    def run_request(self, sid, q, tasks, mode='new'):
        tasks=copy.deepcopy(tasks)
        for task in tasks:
            task.setdefault('subject',None);task.setdefault('execute',True)
            task.setdefault('parent_range','inherit' if mode=='update' else 'all_imported')
        self.data.begin_turn(sid,q)
        return self.data.call(sid,'iccm_request',{'request':{'mode':mode,'tasks':tasks}})

    def test_all_seven_goal_fields_are_exposed_in_both_tools(self):
        tools={t['name']:t for t in TOOLS}
        for schema in [tools['iccm_query']['inputSchema']['properties']['intent']['properties']['result_goal'],
                       tools['iccm_request']['inputSchema']['properties']['request']['properties']['tasks']['items']['properties']['set']['properties']['result_goal']]:
            self.assertEqual(set(schema['required']),set(goal()))

    def test_new_task_without_goal_is_rejected_without_execution(self):
        q='全部测点最新3条';p=patch(q);p['set'].pop('result_goal')
        with self.assertRaisesRegex(ValueError,'result_goal'):self.run_request('no-goal',q,[p])
        self.assertFalse(any(key[0]=='no-goal' for key in self.data.results))

    def test_sort_uses_whole_population_and_continuation_retains_goal(self):
        q='全部测点按时间从晚到早取前3条';p=patch(q,result_goal=goal('sort',field='time',direction='desc',limit=3))
        r=self.run_request('sort',q,[p]);self.assertEqual(r['record_total'],3)
        self.assertGreater(r['goal_receipt']['population'],20)
        q='改为前2条，其他不变';g=copy.deepcopy(p['set']['result_goal']);g['limit']=2
        r=self.run_request('sort',q,[{'base':'t1','quote':q,'set':{'result_goal':g},'filters':[]}],'update')
        self.assertEqual(r['record_total'],2);self.assertEqual(r['goal_receipt']['goal']['direction'],'desc')
        self.assertIn('测量时间',receipt_answer([('iccm_request',r)]))
        self.assertIn('排序',str(tool_view('iccm_request',{},r)))

    def test_extreme_keeps_all_ties(self):
        q='全部测点最新时间及并列';p=patch(q,result_goal=goal('extreme',field='time',direction='desc'))
        r=self.run_request('ties',q,[p]);self.assertGreater(len(r['records']),1)
        self.assertEqual(len({x['time'] for x in r['records']}),1)

    def test_one_filter_update_preserves_other_predicates(self):
        q='已报警测点的摄氏度数值大于60且小于90';p=patch(q,filters=[condition('status','equals','已报警'),condition('unit','equals','℃'),condition('value','gt','60'),condition('value','lt','90')]);p['unit']={'state':'specified','value':'℃'}
        self.run_request('filters',q,[p])
        state=self.data.contexts['filters']['business_request'];old=copy.deepcopy(state['tasks'][0]['filters'])
        fid=next(f['id'] for f in old if f['operator']=='lt')
        q='上限改为80';p={'base':'t1','quote':q,'set':{},'filters':[{'action':'replace','ids':[fid],'conditions':[condition('value','lt','80')],'quote':q}]}
        self.run_request('filters',q,[p],'update');new=self.data.contexts['filters']['business_request']['tasks'][0]['filters']
        self.assertEqual([f for f in new if f['id']!=fid],[f for f in old if f['id']!=fid])
        self.assertEqual(next(f['value'] for f in new if f['id']==fid),'80')

    def test_ambiguous_unit_preserves_draft_and_completes_only_missing_slot(self):
        q='哪些测点超过60度';p=patch(q,filters=[condition('value','gt','60')]);p['unit']={'state':'ambiguous','value':''}
        r=self.run_request('unit-state',q,[p]);self.assertEqual(r['status'],'clarify');self.assertNotIn('query_receipt',r)
        q='单位是摄氏度';p={'base':'t1','quote':q,'set':{},'filters':[{'action':'add','ids':[],'conditions':[condition('unit','equals','℃')],'quote':q}]}
        r=self.run_request('unit-state',q,[p],'update');self.assertEqual(r['record_total'],118)
        self.assertTrue(r['goal_receipt']['completed'])

    def test_partial_execution_preserves_success_and_pending_branch(self):
        q='统计2026年5月测点数量；仅按原始数值将测量值为空的记录降序取前3条'
        p1=patch(q,'count',filters=[condition('time','date_equals','2026-05')])
        p2=patch(q,filters=[condition('value','is_blank','')],result_goal=goal('sort',field='value',direction='desc',limit=3,basis='raw_numbers'))
        r=self.run_request('partial',q,[p1,p2]);self.assertEqual(r['status'],'batch')
        self.assertEqual([x['status'] for x in r['items']],['ok','data_insufficient'])
        self.assertEqual(self.data.contexts['partial']['pending_business_request']['pending_tasks'],['t2'])
        q='第二项取消测量值为空的条件，其他不变';p={'base':'t2','quote':q,'set':{},'filters':[{'action':'remove','ids':['f2'],'conditions':[],'quote':q}]}
        r=self.run_request('partial',q,[p],'update');self.assertEqual(r['record_total'],3)
        state=self.data.contexts['partial']['business_request'];self.assertEqual(len(state['tasks']),2)
        self.assertEqual(state['tasks'][0]['filters'][0]['value'],'2026-05')

    def test_partial_unit_does_not_block_valid_count(self):
        q='统计全部测点；另列数值超过60度的测点';p1=patch(q,'count');p2=patch(q,filters=[condition('value','gt','60')]);p2['unit']={'state':'ambiguous','value':''}
        r=self.run_request('partial-unit',q,[p1,p2]);self.assertEqual([x['status'] for x in r['items']],['ok','clarify'])
        self.assertEqual(self.data.contexts['partial-unit']['pending_business_request']['pending_tasks'],['t2'])
        self.assertTrue(has_delivery([('iccm_request',r)]))

    def test_failed_limit_is_business_feedback_not_confirmed_task(self):
        q='全部测点按时间降序前101条';p=patch(q,result_goal=goal('sort',field='time',direction='desc',limit=101))
        r=self.run_request('limit',q,[p]);self.assertEqual(r['business_constraint']['maximum'],100)
        self.assertFalse(r['request_executed']);self.assertNotIn('business_request',self.data.contexts['limit'])
        q='改为前99条';p=patch(q,result_goal=goal('sort',field='time',direction='desc',limit=99))
        r=self.run_request('limit',q,[p]);self.assertEqual(r['record_total'],99)

    def test_difference_requires_consent_and_preserves_operand_order(self):
        q='测量点名称7和测量点名称6的测量值相差多少';g=goal('difference',field='value',operands=[{'field':'name','value':'测量点名称7'},{'field':'name','value':'测量点名称6'}])
        r=self.run_request('difference',q,[patch(q,result_goal=g)]);self.assertEqual(r['status'],'clarify')
        q='仅计算原始数值，第一项减第二项';g['basis']='raw_numbers'
        r=self.run_request('difference',q,[{'base':'t1','quote':q,'set':{'result_goal':g},'filters':[]}],'update')
        with (Path(__file__).resolve().parents[2]/'中广核iCCM项目智能问数DEMO脱敏数据/测量点数据分析.csv').open(encoding='gb18030') as source:
            raw=list(csv.DictReader(source))
        values={row['测量点名称']:Decimal(row['测量值']) for row in raw if row['测量点名称'] in ('测量点名称7','测量点名称6')}
        self.assertEqual(r['status'],'ok');self.assertEqual(Decimal(r['metrics'][0]['value']),values['测量点名称7']-values['测量点名称6'])
        self.assertTrue(r['goal_receipt']['completed']);self.assertEqual(len(r['operands']),2)

    def test_unmentioned_goals_survive_lookup_preparation(self):
        q='全部测点最新2条';p=patch(q,result_goal=goal('sort',field='time',direction='desc',limit=2))
        self.run_request('prep',q,[p]);state=copy.deepcopy(self.data.contexts['prep']['business_request'])
        self.data.call('prep','iccm_find',{'identifier':'MOHB01','tree':'config'})
        self.assertEqual(state,self.data.contexts['prep']['business_request'])

    def test_new_topic_does_not_inherit_prior_filters(self):
        q='已报警测点数量';self.run_request('new-topic',q,[patch(q,'count',filters=[condition('status','equals','已报警')])])
        q='全部测点数量';r=self.run_request('new-topic',q,[patch(q,'count')])
        self.assertEqual(r['query_receipt']['query']['filters'],[])

    def test_quote_and_filter_id_failures_do_not_change_state(self):
        q='全部测点数量';self.run_request('invalid',q,[patch(q,'count')]);old=copy.deepcopy(self.data.contexts['invalid']['business_request'])
        for p in [{'base':'t1','quote':'用户没说的话','set':{},'filters':[]},
                  {'base':'t1','quote':'再查','set':{},'filters':[{'action':'remove','ids':['f999'],'conditions':[],'quote':'再查'}]}]:
            with self.assertRaises(ValueError):self.run_request('invalid','再查',[p],'update')
            self.assertEqual(old,self.data.contexts['invalid']['business_request'])

    def test_sort_limit_matrix(self):
        for n in (1,100,0,101):
            q=f'全部测点按时间降序前{n}条'
            r=self.run_request('limit-'+str(n),q,[patch(q,result_goal=goal('sort',field='time',direction='desc',limit=n))])
            self.assertEqual(r['status'],'ok' if n in (1,100) else 'clarify')
            if n in (1,100):self.assertEqual(r['record_total'],n)
            else:self.assertEqual(r['business_constraint']['code'],'sort_limit_bounds')

    def test_empty_computation_stays_pending(self):
        q='来源系统ZZNONE的测点按时间排序前2条'
        r=self.run_request('empty',q,[patch(q,filters=[condition('source','equals','系统ZZNONE')],result_goal=goal('sort',field='time',direction='desc',limit=2))])
        self.assertEqual(r['status'],'data_insufficient');self.assertFalse(r.get('goal_receipt',{}).get('completed'))
        self.assertEqual(self.data.contexts['empty']['pending_business_request']['pending_tasks'],['t1'])

    def test_schema_alias_preserves_point_namespace(self):
        q='测量点11的真实值报警阈值高2'
        p=patch(q,filters=[condition('name','equals','测量点11')],operation='attributes',properties=['actual_high2'],result_goal=goal('attributes'))
        r=self.run_request('alias',q,[p]);self.assertEqual(r['status'],'ok')
        self.assertEqual(r['query_receipt']['query']['filters'][0]['value'],'测量点名称11')
        self.assertEqual(r['requested_properties'],['actual_high2'])

    def test_point_candidate_retains_source_after_exact_selection(self):
        q='源系统1中2ABC109MT测点的测量值'
        p=patch(q,filters=[condition('source','equals','源系统1'),condition('identity','equals','2ABC109MT')],operation='attributes',properties=['value'],result_goal=goal('attributes'))
        r=self.run_request('candidate',q,[p]);self.assertEqual(r['status'],'ambiguous')
        q='选择完整编码XJ2ABC001MO.TMP.2ABC109MT.BBe，继续'
        p={'base':'t1','quote':q,'set':{},'filters':[{'action':'replace','ids':['f2'],'conditions':[condition('code','equals','XJ2ABC001MO.TMP.2ABC109MT.BBe')],'quote':q}]}
        r=self.run_request('candidate',q,[p],'update');self.assertEqual(r['status'],'ok')
        self.assertEqual(r['attributes'][0]['value'],'40.69898987')
        self.assertIn(condition('source','equals','源系统1'),r['query_receipt']['query']['filters'])

    def test_threshold_family_projection_and_order(self):
        q='测量点名称11真实值报警阈值从低到高排序'
        properties=['actual_low1','actual_low2','actual_low3','actual_high1','actual_high2','actual_high3']
        p=patch(q,filters=[condition('name','equals','测量点名称11')],operation='attributes',properties=properties,result_goal=goal('sort',field='thresholds',direction='asc'))
        r=self.run_request('thresholds',q,[p]);self.assertEqual(len(r['attributes']),6)
        values=[Decimal(a['value']) for a in r['attributes'] if a['status']=='known']
        self.assertEqual(values,sorted(values));self.assertTrue(r['goal_receipt']['completed'])

    def test_legacy_alias_and_property_followup_share_task_state(self):
        q='测量点11的阈值是多少';self.data.begin_turn('legacy-alias',q)
        r=self.data.call('legacy-alias','iccm_attributes',{'target':'points','identifier':'测量点11','properties':['actual_low1','actual_low2','actual_low3','actual_high1','actual_high2','actual_high3','estimate_low1','estimate_low2','estimate_low3','estimate_high1','estimate_high2','estimate_high3','rate_deviation_low1','rate_deviation_low2','rate_deviation_low3','rate_deviation_high1','rate_deviation_high2','rate_deviation_high3']})
        self.assertEqual(r['status'],'ok');self.assertEqual(len(r['attributes']),18)
        self.assertEqual(self.data.contexts['legacy-alias']['business_request']['tasks'][0]['filters'][0]['value'],'测量点名称11')
        q='名称';r=self.run_request('legacy-alias',q,[{'base':'t1','quote':q,'set':{'properties':['name']},'filters':[]}],'update')
        self.assertEqual(r['status'],'ok');self.assertEqual(r['attributes'][0]['value'],'测量点名称11')

    def test_compatibility_query_cannot_bypass_active_structured_conditions(self):
        q='源系统1测量点名称11的测量值';self.run_request('bypass',q,[patch(q,filters=[condition('source','equals','源系统1'),condition('name','equals','测量点名称11')],operation='attributes',properties=['value'],result_goal=goal('attributes'))])
        with self.assertRaisesRegex(ValueError,'iccm_request'):
            self.data.call('bypass','iccm_attributes',{'target':'points','identifier':'测量点名称11','properties':['value']})

    def test_execute_is_required_in_tool_contract(self):
        schema=next(t for t in TOOLS if t['name']=='iccm_request')['inputSchema']['properties']['request']['properties']['tasks']['items']
        self.assertIn('execute',schema['required']);self.assertIn('subject',schema['required'])
        p=patch('全部测点');p.pop('execute');self.data.begin_turn('missing-execute','全部测点')
        with self.assertRaisesRegex(ValueError,'execute'):
            self.data.call('missing-execute','iccm_request',{'request':{'mode':'new','tasks':[p]}})

    def test_candidate_preview_preserves_true_total_and_is_not_full_paging(self):
        r=self.data.call('candidate-preview','iccm_attributes',{'target':'objects','identifier':'XXXX','properties':['name']})
        self.assertEqual(r['status'],'ambiguous');self.assertEqual(r['record_total'],r['outcome']['candidate_count'])
        self.assertGreater(r['record_total'],r['returned_record_count']);self.assertTrue(r['candidate_preview_only'])
        self.assertFalse(r['has_more']);self.assertNotIn('full_record_summary',r)
        self.assertIn('未缓存其余候选',receipt_answer([('iccm_attributes',r)]))

    def test_schema_exposes_date_operators(self):
        schema=next(t for t in TOOLS if t['name']=='iccm_request')['inputSchema']
        operators=schema['properties']['request']['properties']['tasks']['items']['properties']['filters']['items']['properties']['conditions']['items']['properties']['operator']['enum']
        self.assertTrue({'date_equals','date_gte','date_lt'}<=set(operators))

    def test_explicit_subject_is_sourced_and_not_duplicated(self):
        q='测量点名称11的测量值'
        p=patch(q,operation='attributes',properties=['value'],result_goal=goal('attributes'));p['subject']={'field':'name','value':'测量点名称11'}
        r=self.run_request('subject',q,[p]);self.assertEqual(r['status'],'ok')
        self.assertEqual(r['query_receipt']['query']['filters'],[condition('name','equals','测量点名称11')])
        p['filters']=[{'action':'add','ids':[],'conditions':[condition('name','equals','测量点名称11')],'quote':q}]
        with self.assertRaisesRegex(ValueError,'重复'):self.run_request('subject-duplicate',q,[p])

    def test_clarify_with_draft_never_queries_and_domain_answer_reuses_subject(self):
        q='介绍下XXXX1';p=patch(q,operation='attributes',target='objects',properties=['name','code'],result_goal=goal('attributes'))
        p.update(subject={'field':'identity','value':'XXXX1'},purpose='introduction',subject_scope='unspecified')
        self.data.begin_turn('draft-domain',q)
        r=self.data.call('draft-domain','iccm_clarify',{'question':'请确认对象域','request':{'mode':'new','tasks':[p]}})
        self.assertEqual(r['status'],'clarify');self.assertNotIn('query_receipt',r)
        q='PBS';p={'base':'t1','quote':q,'set':{'target':'pbs'},'filters':[],'subject':None,'purpose':'introduction','subject_scope':'explicit'}
        r=self.run_request('draft-domain',q,[p],'update');self.assertEqual(r['status'],'ok')
        self.assertEqual(r['entity']['code'],self.data.store.rows("SELECT code FROM objects WHERE tree='pbs' AND name='XXXX1'")[0]['code'])

    def test_complete_clarification_draft_still_does_not_execute(self):
        q='测量点名称11的测量值';p=patch(q,operation='attributes',properties=['value'],result_goal=goal('attributes'));p['subject']={'field':'name','value':'测量点名称11'}
        self.data.begin_turn('no-exec-draft',q)
        r=self.data.call('no-exec-draft','iccm_clarify',{'question':'请确认所问内容','request':{'mode':'new','tasks':[p]}})
        self.assertEqual(r['status'],'clarify');self.assertNotIn('query_receipt',r)
        self.assertEqual(self.data.contexts['no-exec-draft']['pending_business_request']['pending_tasks'],['t1'])

    def test_threshold_sorted_facts_are_visible_in_final_answer(self):
        q='测量点名称11真实值阈值升序';p=patch(q,filters=[condition('name','equals','测量点名称11')],operation='attributes',properties=['actual_high1','actual_low1'],result_goal=goal('sort',field='thresholds',direction='asc'))
        r=self.run_request('threshold-answer',q,[p]);text=receipt_answer([('iccm_request',r)])
        for a in r['attributes']:self.assertIn(str(a['display_value']) if a['status']=='known' else '未提供',text)

    def test_new_clarification_with_execute_false_saves_draft_without_query(self):
        q='介绍下XXXX1';p=patch(q,operation='attributes',target='objects',properties=['name'],result_goal=goal('attributes'))
        p.update(subject={'field':'identity','value':'XXXX1'},purpose='introduction',subject_scope='unspecified',execute=False)
        self.data.begin_turn('false-draft',q)
        r=self.data.call('false-draft','iccm_clarify',{'question':'请确认对象域','request':{'mode':'new','tasks':[p]}})
        self.assertEqual(r['status'],'clarify');self.assertFalse(r['request_executed']);self.assertNotIn('query_receipt',r)
        self.assertEqual(self.data.contexts['false-draft']['pending_business_request']['tasks'][0]['filters'][0]['value'],'XXXX1')
        q='PBS';r=self.run_request('false-draft',q,[{'base':'t1','quote':q,'set':{'target':'pbs'},'filters':[],'purpose':'introduction','subject_scope':'explicit'}],'update')
        self.assertEqual(r['status'],'ok')

    def test_threshold_presentation_uses_business_label(self):
        view=tool_view('iccm_query',{'intent':{'operation':'attributes','query':{'target':'points','filters':[]},'result_goal':goal('sort',field='thresholds',direction='asc')}})
        self.assertIn({'label':'排序 / 计算字段','text':'报警阈值'},view['rows'])

    def test_calendar_month_returns_shared_count(self):
        q='统计2026年5月测点条数';r=self.run_request('month',q,[patch(q,'count',filters=[condition('time','date_equals','2026-05')])])
        self.assertEqual(r['status'],'ok');self.assertEqual(r['record_total'],829);self.assertEqual(r['metrics'][0]['value'],829)

    def test_exact_lookup_alone_is_not_completed_computation(self):
        r=self.data.call('delivery-find','iccm_find',{'identifier':'MOHB01','tree':'config'})
        self.assertFalse(has_delivery([('iccm_find',r)]))

    def test_structured_delivery_replaces_preliminary_attempts(self):
        q='全部测点最新2条';r=self.run_request('delivery',q,[patch(q,result_goal=goal('sort',field='time',direction='desc',limit=2))])
        text=receipt_answer([('iccm_query',{'status':'ok','answer':'错误尝试口径'}),('iccm_request',r)])
        self.assertNotIn('错误尝试口径',text);self.assertTrue(has_delivery([('iccm_request',r)]))

if __name__=='__main__':unittest.main(verbosity=2)
