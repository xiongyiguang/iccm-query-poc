"""检查展示契约，适用时使用未改变的真实查询回执。"""
import copy
import json
import unittest
from presentation import tool_view
from tools import DataTools


class PresentationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = DataTools()

    def text(self, view):
        return json.dumps(view, ensure_ascii=False)

    def test_receipt_overrides_proposed_scope_and_filters(self):
        proposed = {'operation': 'search', 'entity': {'tree': 'pbs', 'code': 'OLD'},
                    'scope': 'direct', 'query': {'target': 'points', 'filters': []}}
        receipt = {'operation': 'search', 'resolved_entity': None, 'requested_entity': None,
                   'scope': 'all', 'query': {'target': 'points', 'filters': [
                       {'field': 'value', 'operator': 'gt', 'value': '50'},
                       {'field': 'value', 'operator': 'lt', 'value': '80'},
                       {'field': 'unit', 'operator': 'equals', 'value': '℃'}]}}
        text = self.text(tool_view('iccm_query', {'intent': proposed}, {'query_receipt': receipt}))
        self.assertNotIn('OLD', text)
        for expected in ['未限定父对象', '>「50」', '<「80」', '℃', '记录条数与不同编码数']:
            self.assertIn(expected, text)
        self.assertEqual(proposed['entity']['code'], 'OLD')

    def test_cross_tree_actual_receipt_and_class_grain(self):
        intent = {'operation': 'analyze', 'entity': {'tree': 'pbs', 'code': 'XJ3ABC002RR'}, 'scope': 'all',
                  'query': {'target': 'parts', 'filters': [], 'equipment_class':
                            {'field': 'name', 'operator': 'equals', 'value': '设备类描述3727'}},
                  'analysis': {'kind': 'group_count', 'group_by': 'class_code', 'order': 'desc', 'limit': 100, 'numerator': []}, 'clarification': ''}
        result = self.data.call('display-test', 'iccm_query', {'intent': intent})
        self.assertEqual([m['value'] for m in result['metrics']], [90, 23])
        text = self.text(tool_view('iccm_query', {'intent': intent}, result))
        for expected in ['现场挂接部件', '设备类描述3727', '全部下级', '按部件类编码分组', '实际挂接部件']:
            self.assertIn(expected, text)

    def test_points_scope_is_self_and_descendants_even_when_direct(self):
        view = tool_view('iccm_query', {'intent': {'operation': 'search', 'entity': {'tree': 'pbs', 'code': 'A'},
                                                'scope': 'direct', 'query': {'target': 'points', 'filters': []}}})
        self.assertIn('自身及全部后代', self.text(view))
        self.assertNotIn('直接下级', self.text(view))

    def test_ratio_denominator_numerator_and_no_silent_dedup(self):
        intent = {'operation': 'analyze', 'query': {'target': 'points', 'filters': [{'field': 'switch', 'operator': 'equals', 'value': '开启'}]},
                  'analysis': {'kind': 'ratio', 'numerator': [{'field': 'status', 'operator': 'equals', 'value': '已报警'}]}}
        rows = tool_view('iccm_query', {'intent': intent})['rows']
        self.assertTrue(any(r['label'].startswith('筛选条件') and '开启' in r['text'] for r in rows))
        self.assertTrue(any(r['label'] == '分子附加条件' and '已报警' in r['text'] for r in rows))
        self.assertIn('不按编码去重', self.text(rows))

    def test_batch_keeps_separate_scopes_and_properties(self):
        tasks = [{'question': code, 'intent': {'operation': 'attributes', 'entity': {'tree': 'config', 'code': code}, 'properties': ['name','parent']}} for code in ['A','B']]
        view = tool_view('iccm_query', {'intent': {'operation': 'batch', 'tasks': tasks}})
        self.assertEqual(len(view['tasks']), 2)
        self.assertIn('构型对象 · A', self.text(view['tasks'][0]))
        self.assertNotIn('构型对象 · B', self.text(view['tasks'][0]))
        self.assertIn('父对象编码', self.text(view))

    def test_malformed_plan_does_not_crash_formatter_or_mutate(self):
        args = {'intent': {'operation': 'search', 'query': {'filters': [None]}}}
        before = copy.deepcopy(args)
        self.assertIn('尚不能确定', self.text(tool_view('iccm_query', args)))
        self.assertEqual(args, before)

    def test_attribute_lookup_does_not_claim_descendant_scope(self):
        result = self.data.call('display-attr', 'iccm_attributes', {'target': 'points',
            'identifier': 'XJ1ABC001PO.JVD.1ABC029MV.LBe_Y', 'properties': ['rate']})
        view = tool_view('iccm_attributes', {'target': 'points',
            'identifier': 'XJ1ABC001PO.JVD.1ABC029MV.LBe_Y', 'properties': ['rate']}, result)
        self.assertNotIn('后代', self.text(view))
        self.assertIn('读取指定属性', self.text(view))


if __name__ == '__main__':
    unittest.main(verbosity=2)
