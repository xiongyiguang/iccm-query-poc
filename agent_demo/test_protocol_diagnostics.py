"""验证协议边界不丢弃实际条件，错误路径可修正，并且失败不执行查询。"""
import copy
import unittest
from unittest.mock import patch as mocked
from tools import DataTools
from test_request_protocol import patch, condition, goal
from protocol_diagnostics import prepare_request


class ProtocolDiagnostics(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = DataTools()

    def call(self, sid, question, task):
        self.data.begin_turn(sid, question)
        return self.data.call(sid, 'iccm_request', {'request': {'mode': 'new', 'tasks': [task]}})

    def test_empty_task_ids_do_not_change_real_filters_or_goal(self):
        q = '源系统1测点按时间从晚到早取前2条'
        p = patch(q, filters=[condition('source', 'equals', '源系统1')],
                  result_goal=goal('sort', field='time', direction='desc', limit=2))
        first = self.call('clean-diagnostic', q, p)
        p['ids'] = []
        second = self.call('empty-ids-diagnostic', q, p)
        self.assertEqual(second['query'], first['query'])
        self.assertEqual(second['records'], first['records'])
        self.assertEqual(second['goal_receipt'], first['goal_receipt'])
        self.assertEqual(second['protocol_adjustments'][0]['path'], 'request.tasks[0].ids')
        self.assertIn('ids', p)  # 调用方参数保持原样，审计能复原。

    def test_nonempty_misplaced_ids_are_not_dropped(self):
        q = '统计全部测点记录'; p = patch(q, 'count'); p['ids'] = ['f1']
        with mocked.object(self.data.store, 'filtered', side_effect=AssertionError('无效参数不能查询')):
            with self.assertRaisesRegex(ValueError, r'tasks\[0\]\.ids.*filters'):
                self.call('nonempty-ids-diagnostic', q, p)
        self.assertNotIn('business_request', self.data.contexts.get('nonempty-ids-diagnostic', {}))

    def test_unknown_goal_key_has_exact_path(self):
        q = '统计全部测点记录'; p = patch(q, 'count'); p['set']['result_goal']['guess'] = True
        with self.assertRaisesRegex(ValueError, r'set\.result_goal\.guess'):
            self.call('bad-goal-diagnostic', q, p)

    def test_missing_required_range_does_not_default_to_all(self):
        q = '统计全部测点记录'; p = patch(q, 'count'); p.pop('parent_range')
        with self.assertRaisesRegex(ValueError, r'tasks\[0\]\.parent_range.*缺失'):
            self.call('missing-range-diagnostic', q, p)

    def test_range_in_wrong_layer_is_not_discarded(self):
        q = '统计全部测点记录'; request = {'mode': 'new', 'tasks': [patch(q, 'count')], 'parent_range': 'inherit'}
        with self.assertRaisesRegex(ValueError, r'request\.parent_range.*合法键'):
            prepare_request(request, self.data.request_schema)

    def test_boolean_is_not_an_integer_limit(self):
        q = '按时间取前2条'; p = patch(q, result_goal=goal('sort', field='time', direction='desc', limit=True))
        with self.assertRaisesRegex(ValueError, r'result_goal\.limit.*类型'):
            self.call('bool-limit-diagnostic', q, p)

    def test_empty_search_projection_is_legal_but_empty_attributes_are_not(self):
        q = '统计全部测点记录'; r = self.call('empty-search-diagnostic', q, patch(q, 'count'))
        self.assertTrue(r['goal_receipt']['completed'])
        q = '测量点名称11的属性'; p = patch(q, operation='attributes', result_goal=goal('attributes'))
        p['subject'] = {'field': 'name', 'value': '测量点名称11'}
        with self.assertRaises(ValueError):self.call('empty-attrs-diagnostic', q, p)

    def test_empty_task_ids_preserve_101_constraint_and_previous_state(self):
        q = '统计全部测点记录'; self.call('bound-diagnostic', q, patch(q, 'count'))
        old = copy.deepcopy(self.data.contexts['bound-diagnostic']['business_request'])
        q = '全部测点按时间从晚到早取前101条'
        p = patch(q, result_goal=goal('sort', field='time', direction='desc', limit=101)); p['ids'] = []
        r = self.call('bound-diagnostic', q, p)
        self.assertEqual(r['business_constraint']['maximum'], 100)
        self.assertFalse(r['request_executed']); self.assertFalse(r['records'])
        self.assertEqual(self.data.contexts['bound-diagnostic']['business_request'], old)
        self.assertTrue(r['protocol_adjustments'])

    def test_valid_topic_does_not_make_a_search_into_an_explanation(self):
        from data_context import STATIC_TOPICS
        q = '按层级分组计数'; p = patch(q, 'count'); p['set']['topics'] = [next(iter(STATIC_TOPICS))]
        with self.assertRaisesRegex(ValueError, '分组'):
            self.call('topic-operation-diagnostic', q, p)
