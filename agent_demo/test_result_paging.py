"""核验分页读取会话缓存，不新增模型调用或改写已执行任务。"""
import copy
import threading
import unittest
from unittest.mock import Mock
from tools import DataTools
from server import Demo


class ResultPaging(unittest.TestCase):
    def setUp(self):
        self.demo = Demo.__new__(Demo)
        self.demo.runtime = Mock()
        self.demo.sessions = {'one': {'events': [], 'busy': False}, 'two': {'events': [], 'busy': False}}
        self.demo.data = DataTools.__new__(DataTools)
        self.demo.data.lock = threading.RLock()
        self.demo.data.contexts = {'one': {'agent_relational_request': {'tasks': [{'id': 1}, {'id': 2}]}}}
        self.result = {'status': 'batch', 'items': [
            {'task_number': 1, 'status': 'ok', 'answer': '完整23原行', 'metrics': [{'label': '原记录数', 'value': 23}],
             'records': [{'cells': [i, '同编码', '同来源']} for i in range(23)]},
            {'task_number': 2, 'status': 'data_insufficient', 'answer': '缺分类不能补零', 'records': []}]}
        self.demo.data.results = {('one', 'result'): self.result}

    def test_page_reads_remaining_original_rows_and_keeps_task_context(self):
        before = copy.deepcopy(self.demo.data.contexts)
        r = self.demo.page('one', 'result', 2)
        self.assertEqual([x['cells'][0] for x in r['items'][0]['records']], [20, 21, 22])
        self.assertEqual(r['items'][0]['metrics'][0]['value'], 23)
        self.assertEqual(r['items'][1]['answer'], '缺分类不能补零')
        self.assertEqual(self.demo.data.contexts, before)
        self.assertEqual(len(self.result['items'][0]['records']), 23)
        self.assertEqual(self.demo.sessions['one']['events'], [])
        self.demo.runtime.call.assert_not_called()
        self.demo.runtime.new_thread.assert_not_called()

    def test_result_cannot_cross_session(self):
        for sid in ('two', 'missing'):
            with self.assertRaises(ValueError):
                self.demo.page(sid, 'result', 2)

    def test_invalid_page_rejected(self):
        for page in (0, True, '2', 10001):
            with self.assertRaises(ValueError):
                self.demo.page('one', 'result', page)

    def test_previous_page_preserves_full_counts(self):
        r = self.demo.page('one', 'result', 1)['items'][0]
        self.assertTrue(r['has_more'])
        self.assertEqual(r['record_total'], 23)
        self.assertEqual(r['returned_record_count'], 20)


if __name__ == '__main__':
    unittest.main()
