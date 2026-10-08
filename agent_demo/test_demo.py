"""独立演示的离线契约测试，不请求模型或网络。"""
import copy
import unittest
from tools import DataTools


class DemoContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = DataTools()

    def plan(self):
        return {'operation': 'analyze', 'entity': {'tree': 'pbs', 'code': 'XJ3ABC002RR'},
                'scope': 'all', 'clarification': '',
                'query': {'target': 'parts', 'filters': [], 'equipment_class':
                          {'field': 'name', 'operator': 'equals', 'value': '设备类描述3727'}},
                'analysis': {'kind': 'group_count', 'group_by': 'class_code', 'order': 'desc', 'limit': 100, 'numerator': []}}

    def test_cross_tree_counts_and_paging(self):
        result = self.data.call('one', 'iccm_query', {'intent': self.plan()})
        self.assertEqual([m['value'] for m in result['metrics']], [90, 23])
        self.assertEqual(len(result['records']), 20)
        self.assertTrue(result['has_more'])
        tail = self.data.call('one', 'iccm_page', {'result_id': result['result_id'], 'page': 2})
        self.assertEqual(len(tail['records']), 3)
        self.assertEqual(result['metrics'], tail['metrics'])
        with self.assertRaises(ValueError):
            self.data.call('another', 'iccm_page', {'result_id': result['result_id'], 'page': 1})

    def test_changed_subject(self):
        plan = self.plan()
        plan['entity']['code'] = 'XJ2ABC001MO'
        result = self.data.call('two', 'iccm_query', {'intent': plan})
        self.assertEqual([m['value'] for m in result['metrics']], [0, 0])

    def test_invalid_operations_and_tools(self):
        for name, args in [('shell', {'command': 'anything'}),
                           ('iccm_query', {'intent': {'operation': 'delete'}}),
                           ('iccm_query', {'intent': None})]:
            with self.subTest(name=name, args=args), self.assertRaises(Exception):
                self.data.call('one', name, args)

    def test_exact_identity(self):
        result = self.data.call('find', 'iccm_find', {'identifier': 'XJ3ABC002RR', 'tree': 'pbs'})
        self.assertEqual(result['match_type'], 'exact')
        self.assertEqual(len(result['records']), 1)

    def test_unknown_identity_does_not_select(self):
        result = self.data.call('find', 'iccm_find', {'identifier': '不存在的设备987654321', 'tree': 'objects'})
        self.assertEqual(result['match_type'], 'candidates_only')
        self.assertFalse(result['records'])

    def test_page_invalid(self):
        for page in [0, -1, True, '1']:
            with self.subTest(page=page), self.assertRaises(ValueError):
                self.data.page({}, 'test', page)


if __name__ == '__main__':
    unittest.main(verbosity=2)
