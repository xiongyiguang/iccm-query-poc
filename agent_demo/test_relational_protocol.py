"""用与客户不同的结构核验公共接入、状态、重复原行及最终事实交付。"""
import copy
import threading
import unittest
from tools import DataTools
from data import Store
from answers import receipt_answer, delivery_receipts
from presentation import tool_view
from server import Demo


def obj(code, parent, name, kind, cls=None, config=False):
    r = {'对象代码': code, '父对象代码': parent, '对象描述中文': name, '对象层级': kind}
    if config:
        r.update(对象层级='7', 对象层级描述=kind, 所属部件类代码=cls or '')
    return r


class RelationalProtocol(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rows = {'pbs': [obj('SITE', '', '机房', '功能位置'), obj('SITE&DEV', 'SITE', '设备甲', '设备'),
                       obj('SITE&DEV#A', 'SITE&DEV', '轴承甲', '部件'), obj('SITE&DEV#B', 'SITE&DEV', '轴承乙', '部件'),
                       obj('SITE&DEV#C', 'SITE&DEV', '轴承丙', '部件'), obj('OBS', 'SITE&DEV#A', '测点结构', '时序测点')],
                'config': [obj('EC', '', '模板根', '设备类', config=True), obj('DEV', 'EC', '设备模板', '设备', config=True),
                           obj('DEV#A', 'DEV', '轴承模板', '部件', 'PC', True), obj('DEV#B', 'DEV', '空类模板', '部件', None, True)],
                'equipment_class': [{'对象编码': 'EC', '父对象编码': '', '描述': '电机类', '层级': '3'}],
                'part_class': [{'对象编码': 'PC', '父对象编码': '', '对象描述中文': '机械类', '对象层级': '4'}],
                'points': [{'测量点编码': 'OBS', '测量点名称': '温度一', '源系统': '来源甲', '开关': '开启', '状态': '已报警',
                            '真实值报警阈值-高2': '23', '估计值报警阈值-高2': '45'},
                           {'测量点编码': 'OBS', '测量点名称': '温度二', '源系统': '来源甲', '开关': '开启', '状态': '',
                            '真实值报警阈值-高2': '24', '估计值报警阈值-高2': '46'},
                           {'测量点编码': 'SITE.FAKE', '测量点名称': '无精确结构', '源系统': '来源乙', '开关': '开启', '状态': ''}]}
        cls.store = Store(dataset=[{'kind': k, 'file': k + '.csv', 'sha256': k, 'rows': v, 'seed': True} for k, v in rows.items()])

    def setUp(self):
        self.data = DataTools.__new__(DataTools)
        self.data.store = self.store
        self.data.lock = threading.RLock()
        for k in ('results', 'contexts', 'turn_bindings', 'questions', 'unscoped_names', 'turn_contexts'):
            setattr(self.data, k, {})

    def call(self, question, specs, mode='new'):
        self.data.begin_turn('s', question)
        request = {'mode': mode, 'tasks': [{'id': tid, 'quote': question, 'set': spec} for tid, spec in specs]}
        return self.data.call('s', 'iccm_relational', {'request': request})

    def q(self, **kw):
        return {'kind': 'collection', 'root': {'tree': 'pbs', 'field': 'code', 'value': 'SITE&DEV'},
                'population': 'parts', 'depth': 'all', **kw}

    def test_reverse_class_at_actual_instance_grain(self):
        r = self.call('SITE中电机类的现场设备', [(1, self.q(root={'tree': 'pbs', 'field': 'code', 'value': 'SITE'}, population='devices', classes={'equipment_class': '电机类'}))])
        self.assertEqual(r['record_total'], 1)
        self.assertEqual(r['records'][0]['code'], 'SITE&DEV')

    def test_five_table_keeps_duplicate_rows(self):
        r = self.call('SITE中电机类和机械类关联的测点', [(1, self.q(root={'tree': 'pbs', 'field': 'code', 'value': 'SITE'}, population='points', classes={'equipment_class': '电机类', 'part_class': '机械类'}))])
        self.assertEqual(r['record_total'], 2)
        self.assertEqual([m['value'] for m in r['metrics'][:2]], [2, 1])
        self.assertEqual([row['name'] for row in r['records']], ['温度一', '温度二'])

    def test_source_group_delivers_both_counts_and_original_lines(self):
        r = self.call('OBS全部原记录按来源分组并列原CSV行号', [(1, self.q(root={'tree': 'points', 'field': 'code', 'value': 'OBS'}, population='points', group_by='source'))])
        text = receipt_answer([('iccm_relational', r)])
        for word in ('记录数/原行号', '不同编码数/名称', '温度一', '温度二', '原CSV行号'):
            self.assertIn(word, text)
        self.assertEqual(r['groups'][0]['distinct_code_count'], 1)

    def test_missing_pbs_never_uses_prefix(self):
        r = self.call('SITE.FAKE的实际PBS关联', [(1, self.q(root={'tree': 'points', 'field': 'code', 'value': 'SITE.FAKE'}, kind='relation', population='objects'))])
        text = receipt_answer([('iccm_relational', r)])
        self.assertIn('无精确结构', text)
        self.assertIn('不能', text)
        self.assertTrue(r['missing_links'])

    def test_partial_classification_is_not_complete(self):
        r = self.call('SITE&DEV全部现场部件的完整分类', [(1, self.q(group_by='class'))])
        self.assertEqual(r['classification_coverage'], {'complete': False, 'total': 3, 'resolved': 1, 'unresolved': 2})
        text = receipt_answer([('iccm_relational', r)])
        for word in ('SITE&DEV#B', 'SITE&DEV#C', '未完成'):
            self.assertIn(word, text)
        self.assertFalse(r['relation_delivery']['completed'])

    def test_health_note_reaches_final_without_model_draft(self):
        r = self.call('SITE&DEV是否全部健康', [(1, self.q(kind='boundary', boundary='health'))])
        text = receipt_answer([('iccm_relational', r)])
        self.assertIn('不能证明', text)
        self.assertIn('健康', text)
        self.assertEqual(r['health_snapshot']['monitored_records'], 2)
        self.assertEqual(r['health_snapshot']['active_alarm_records'], 1)

    def test_duration_missing_history_is_not_zero(self):
        r = self.call('SITE&DEV累计报警时长', [(1, self.q(kind='boundary', boundary='duration'))])
        self.assertEqual(r['status'], 'data_insufficient')
        self.assertEqual(r['metrics'], [])
        text = receipt_answer([('iccm_relational', r)])
        for word in ('报警开始时间', '恢复时间', '不能'):
            self.assertIn(word, text)

    def test_update_one_task_preserves_other_task_and_result(self):
        r = self.call('SITE&DEV的关系；DEV的全部构型部件分类', [(1, self.q(kind='relation', population='objects')),
                      (2, self.q(root={'tree': 'config', 'field': 'code', 'value': 'DEV'}, group_by='class'))])
        old = copy.deepcopy(r['agent_relational_request']['tasks'][1])
        r = self.call('仅把第一项改为SITE&DEV#A，第二项保留', [(1, {'root': {'tree': 'pbs', 'field': 'code', 'value': 'SITE&DEV#A'}})], 'update')
        self.assertEqual(len(r['items']), 2)
        self.assertEqual(r['agent_relational_request']['tasks'][1], old)
        self.assertEqual(r['items'][1]['population_facts']['record_count'], 2)
        self.assertIn('轴承甲', receipt_answer([('iccm_relational', r)]))

    def test_missing_root_keeps_other_success_and_does_not_count_zero(self):
        r = self.call('UNKNOWN的关系和SITE&DEV全部部件', [(1, self.q(kind='relation', population='objects', root={'tree': 'config', 'field': 'code', 'value': 'UNKNOWN'})), (2, self.q())])
        self.assertEqual(r['items'][0]['status'], 'error')
        self.assertEqual(r['items'][0]['metrics'], [])
        self.assertEqual(r['items'][1]['population_facts']['record_count'], 3)
        self.assertIn('不能视作零', receipt_answer([('iccm_relational', r)]))

    def test_scalar_properties_are_strict_and_keep_point_focus(self):
        r = self.call('OBS只给真实高2、估计高2和测量时间', [(1, self.q(kind='relation', population='objects', root={'tree': 'points', 'field': 'code', 'value': 'OBS'}, properties=['actual_high2', 'estimate_high2', 'time']))])
        self.assertEqual(set(r['requested_properties']), {'actual_high2', 'estimate_high2', 'time'})
        self.assertEqual(self.data.contexts['s']['query']['filters'][0]['value'], 'OBS')
        self.assertIsNone(self.data.contexts['s']['entity'])

    def test_unregistered_literal_class_keeps_independent_success(self):
        r = self.call('SITE&DEV中UNKNOWN_CLASS的部件和SITE&DEV的真实关系', [(1, self.q(classes={'part_class': 'UNKNOWN_CLASS'})),
                       (2, self.q(kind='relation', population='objects'))])
        self.assertEqual(r['items'][0]['status'], 'error')
        self.assertEqual(r['items'][1]['status'], 'ok')
        self.assertEqual(r['items'][0]['metrics'], [])

    def test_unknown_keys_or_task_identity_do_not_execute(self):
        self.call('SITE&DEV全部部件', [(1, self.q())])
        old = copy.deepcopy(self.data.contexts['s']['agent_relational_request'])
        for specs in ([(2, {'depth': 'direct'})], [(1, {'sql': 'SELECT 1'})]):
            with self.assertRaises(ValueError):
                self.call('改为直接下级', specs, 'update')
            self.assertEqual(self.data.contexts['s']['agent_relational_request'], old)

    def test_invented_reference_or_quote_rejected(self):
        with self.assertRaises(ValueError):
            self.call('设备全部部件', [(1, self.q())])
        self.data.begin_turn('s', 'SITE&DEV全部部件')
        with self.assertRaises(ValueError):
            self.data.call('s', 'iccm_relational', {'request': {'mode': 'new', 'tasks': [{'id': 1, 'quote': '虚构原话', 'set': self.q()}]}})

    def test_final_manifest_uses_complete_directory_not_intermediate_probe(self):
        first = {'result_id': 'probe', 'status': 'ok', 'answer': '中间试查', 'records': []}
        last = {'result_id': 'directory', 'status': 'batch', 'answer': '两项', 'items': [
            {'status': 'ok', 'answer': '第一项成功', 'records': []},
            {'status': 'data_insufficient', 'answer': '第二项缺资料，不能算零', 'records': []}]}
        receipts = [('iccm_relational', first), ('iccm_relational', last)]
        self.assertEqual(delivery_receipts(receipts), [last])
        d = Demo.__new__(Demo)
        d.lock = threading.RLock()
        s = {'id': 's', 'thread': 't', 'events': [], 'receipts': receipts, 'business_calls': 2}
        d.sessions = {'s': s}
        d.notify('item/completed', {'threadId': 't', 'item': {'type': 'agentMessage', 'id': 'm', 'phase': 'final_answer', 'text': '虚构全完成999'}})
        e = s['events'][-1]
        self.assertEqual(e['delivery_result_ids'], ['directory'])
        for word in ('第一项成功', '第二项缺资料'):
            self.assertIn(word, e['text'])
        self.assertNotIn('999', e['text'])

    def test_relation_tool_has_business_labels(self):
        r = self.call('SITE&DEV全部现场部件', [(1, self.q())])
        view = tool_view('iccm_relational', {}, r)
        self.assertEqual(view['title'], '跨表关系查询')
        self.assertTrue(view['executed'])
        self.assertIn('SITE&DEV', str(view['rows']))

    def test_reference_role_reads_class_and_one_parent_edge(self):
        self.call('SITE&DEV的设备类', [(1, self.q(kind='relation', population='objects'))])
        r = self.call('刚才这个设备类的上级', [(1, {'kind':'relation','root':{'task':1,'role':'equipment_class'}})])
        self.assertEqual(r['entity'], {'tree':'equipment_class','code':'EC'})
        self.assertIn('电机类', receipt_answer([('iccm_relational',r)]))

    def test_missing_reference_role_cannot_borrow_another(self):
        self.call('SITE&DEV#C的部件类', [(1, self.q(kind='relation',population='objects',root={'tree':'pbs','field':'code','value':'SITE&DEV#C'}))])
        with self.assertRaises(ValueError):
            self.call('该部件类的上级', [(1, {'kind':'relation','root':{'task':1,'role':'part_class'}})])

    def test_same_code_two_domains_keep_each_explicit_read(self):
        self.data.begin_turn('s','分别查构型EC和设备类EC的名称')
        a = self.data.call('s','iccm_attributes',{'target':'config','identifier':'EC','properties':['code','name']})
        b = self.data.call('s','iccm_attributes',{'target':'equipment_class','identifier':'EC','properties':['code','name']})
        self.assertEqual(a['entity']['tree'],'config')
        self.assertEqual(b['entity']['tree'],'equipment_class')
        self.assertIn('不能合并',b['note'])

    def test_successful_update_cannot_be_overwritten_by_new_in_same_turn(self):
        self.call('SITE&DEV全部部件',[(1,self.q())])
        self.data.begin_turn('s','列出这些结果的名称')
        self.data.call('s','iccm_relational',{'request':{'mode':'update','tasks':[{'id':1,'quote':'列出这些结果的名称','set':{'properties':['name']}}]}})
        with self.assertRaises(ValueError):
            self.data.call('s','iccm_relational',{'request':{'mode':'new','tasks':[{'id':1,'quote':'这些结果','set':self.q(kind='relation',population='objects')} ]}})

    def test_mixed_tool_final_delivery_keeps_independent_proven_subject(self):
        a={'status':'ok','result_id':'a','entity':{'tree':'config','code':'EC'},'answer':'模板根'}
        b={'status':'ok','result_id':'b','entity':{'tree':'equipment_class','code':'EC'},'answer':'电机类'}
        self.assertEqual(delivery_receipts([('iccm_attributes',a),('iccm_relational',b)]),[a,b])

    def test_classification_and_its_missing_facet_are_one_task(self):
        with self.assertRaises(ValueError):
            self.call('SITE&DEV完整分类并说明缺失部件',[(1,self.q(group_by='class')),(2,self.q(only='missing_class'))])
        r=self.call('SITE&DEV完整分类并说明缺失部件',[(1,self.q(group_by='class'))])
        self.assertEqual(r['classification_coverage']['unresolved'],2)
        r=self.call('具体哪些缺失',[(1,{'group_by':None,'only':'missing_class'})],'update')
        self.assertEqual(r['record_total'],2)

    def test_compare_prior_two_scopes_keeps_verified_history_reference(self):
        self.call('SITE&DEV全部现场部件',[(1,self.q())])
        self.call('DEV全部构型部件',[(1,self.q(root={'tree':'config','field':'code','value':'DEV'}))])
        r=self.call('对照刚才两套部件集合',[(1,self.q(kind='compare',compare_root={'tree':'config','field':'code','value':'DEV'}))])
        self.assertEqual(r['status'],'ok')
        self.assertEqual(r['entity']['code'],'SITE&DEV')

    def test_scalar_projection_history_keeps_prior_verified_goal(self):
        self.data.begin_turn('s','OBS真实高2是多少')
        self.data.call('s','iccm_attributes',{'target':'points','identifier':'OBS','properties':['actual_high2']})
        self.data.begin_turn('s','名称')
        self.data.call('s','iccm_attributes',{'target':'points','identifier':'OBS','properties':['name']})
        c=self.data.begin_turn('s','回顾之前的字段')
        self.assertEqual(c['completed_request_history'][0]['tasks'][0]['properties'],['actual_high2'])
        self.assertEqual(c['completed_request_history'][-1]['tasks'][0]['properties'],['name'])
        self.assertEqual(c['task_state']['task_directory'][0]['properties'],['name'])
        self.assertEqual(self.data.begin_turn('other','之前的字段')['completed_request_history'],[])

    def test_repeated_same_role_identity_is_unique_not_two_classes(self):
        self.call('OBS实际关联',[(1,self.q(kind='relation',population='objects',root={'tree':'points','field':'code','value':'OBS'}))])
        r=self.call('刚才设备类上级',[(1,{'kind':'relation','root':{'task':1,'role':'equipment_class'}})])
        self.assertEqual(r['entity'],{'tree':'equipment_class','code':'EC'})

    def test_pending_branch_is_not_recorded_as_completed_goal(self):
        self.data.begin_turn('s','设备类EC的名称')
        self.data.call('s','iccm_attributes',{'target':'equipment_class','identifier':'EC','properties':['name']})
        context=self.data.contexts['s'];state=context['business_request']
        other=copy.deepcopy(state['tasks'][0]);other['id']='t2';state['tasks'].append(other)
        state['last_executed_tasks']=['t1','t2']
        actual=self.data.results['s',context['result_id']]
        self.data.results['s',context['result_id']]={'status':'batch','items':[
            {**actual,'task_number':1},{'status':'clarify','task_number':2,'answer':'待补对象'}]}
        c=self.data.begin_turn('s','之前执行了什么')
        self.assertEqual([t['id'] for t in c['completed_request_history'][0]['tasks']],['t1'])


if __name__ == '__main__':
    unittest.main()
