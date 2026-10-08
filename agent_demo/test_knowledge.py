"""基于保留的本地快照，回归验证有据上下文和查询回执。"""
import unittest
from tools import DataTools, INTENT_SCHEMA


class KnowledgeContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = DataTools()

    def query(self, sid, **changes):
        plan = {'operation': 'attributes', 'entity': None, 'scope': 'direct', 'clarification': '',
                'query': {'target': 'config', 'filters': [
                    {'field': 'identity', 'operator': 'equals', 'value': 'MOHB01'}]},
                'properties': ['name', 'code', 'type']}
        plan.update(changes)
        return self.data.call(sid, 'iccm_query', {'intent': plan})

    def test_pagination_counts_and_full_mixed_population(self):
        result = self.query('mixed', operation='search', properties=None,
                            entity={'tree': 'config', 'code': 'MOHB01'},
                            query={'target': 'config', 'filters': []})
        self.assertEqual(result['record_total'], 52)
        self.assertEqual(result['returned_record_count'], 20)
        groups = {g['level']: g['count'] for g in result['full_record_summary']['by_tree_and_level']}
        self.assertEqual(groups, {'部件': 51, '子设备': 1})
        tail = self.data.call('mixed', 'iccm_page', {'result_id': result['result_id'], 'page': 3})
        self.assertEqual(tail['returned_record_count'], 12)
        self.assertEqual(tail['full_record_summary'], result['full_record_summary'])
        empty = self.data.call('mixed', 'iccm_page', {'result_id': result['result_id'], 'page': 4})
        self.assertEqual(empty['returned_record_count'], 0)
        self.assertEqual(empty['record_total'], 52)

    def test_context_keeps_namespace_and_new_identifier_candidates(self):
        self.query('context')
        ctx = self.data.begin_turn('context', 'MOHB是什么？')
        self.assertEqual(ctx['previous_query']['lookup_query']['target'], 'config')
        self.assertEqual({r['domain'] for r in ctx['literal_references']}, {'config', 'equipment_class'})
        self.assertEqual({r['value'] for r in ctx['literal_references']}, {'MOHB'})
        self.assertIsNone(self.data.begin_turn('isolated', '它呢')['previous_query'])

    def test_ambiguous_lookup_does_not_leave_previous_focus(self):
        self.query('ambiguous')
        self.data.call('ambiguous', 'iccm_find', {'identifier': 'MOHB', 'tree': 'objects'})
        ctx = self.data.begin_turn('ambiguous', '它呢')['previous_query']
        self.assertIsNone(ctx.get('entity'))

    def test_format_preserves_raw_evidence_and_zero(self):
        result = self.query('number', query={'target': 'points', 'filters': [
            {'field': 'identity', 'operator': 'equals', 'value': 'XJ1ABC001PO.JVD.1ABC029MV.LBe_Y'}]},
            properties=['rate', 'value', 'unit'])
        attrs = {a['property']: a for a in result['attributes']}
        self.assertEqual(attrs['rate']['value'], '-4.05E-10')
        self.assertEqual(attrs['rate']['display_value'], '-0.000000000405')
        self.assertEqual(attrs['value']['display_value'], '0')
        self.assertEqual(attrs['unit']['status'], 'missing')

    def test_explanation_scoped_to_result_and_session(self):
        result = self.data.call('explain', 'iccm_query', {'intent': {
            'operation': 'parts', 'entity': {'tree': 'config', 'code': 'MOHB01'},
            'scope': 'direct', 'clarification': ''}})
        explanation = self.data.call('explain', 'iccm_explain', {'result_id': result['result_id']})
        self.assertIn('父编码直接等于', explanation['answer'])
        with self.assertRaises(ValueError):
            self.data.call('other', 'iccm_explain', {'result_id': result['result_id']})

    def test_classifier_is_not_relationship_origin(self):
        with self.assertRaisesRegex(ValueError, 'attributes'):
            self.data.call('invalid', 'iccm_query', {'intent': {'operation': 'equipment',
                'entity': {'tree': 'equipment_class', 'code': 'MOHB'}, 'scope': 'direct', 'clarification': ''}})

    def test_catalog_and_schema_only_offer_supported_operations(self):
        ops = INTENT_SCHEMA['properties']['operation']['enum']
        self.assertNotIn('conversation', ops)
        self.assertNotIn('explain_result', ops)
        self.assertIn('clarify', ops)
        guide = self.data.call('catalog', 'iccm_catalog', {})['query_protocol']
        self.assertIn('独立 Agent 工具协议 V4', guide)

    def test_clarification_accepts_unresolved_draft_without_execution(self):
        result=self.data.call('clarify-draft','iccm_query',{'intent':{'operation':'clarify',
            'entity':None,'scope':'unspecified','query':{'target':'pbs','filters':[]},'clarification':'请选择对象域'}})
        self.assertEqual(result['status'],'clarify');self.assertNotIn('query_receipt',result)
        context=self.data.begin_turn('clarify-draft','PBS')['previous_query']
        self.assertEqual(context['pending_request']['query']['target'],'pbs')
        self.assertEqual(self.data.call('clarify-flat','iccm_clarify',{'question':'请明确单位'})['status'],'clarify')

    def test_attribute_tool_resolves_names_and_namespace(self):
        for target, identifier, expected in [('pbs', 'XXXX1', 'XXXX1'),
                ('config', 'MOHB01', '构型对象描述14477'),
                ('points', 'XJ1ABC001PO.JVD.1ABC029MV.LBe_Y', '测量点名称1050')]:
            result = self.data.call('attrs', 'iccm_attributes', {
                'target': target, 'identifier': identifier, 'properties': ['name']})
            self.assertEqual(result['status'], 'ok')
            self.assertEqual(result['attributes'][0]['value'], expected)
        ambiguous = self.data.call('attrs', 'iccm_attributes', {
            'target': 'objects', 'identifier': 'MOHB', 'properties': ['name']})
        self.assertEqual(ambiguous['status'], 'ambiguous')

    def test_children_requires_both_scope_dimensions(self):
        for depth, kind in [('unspecified', 'objects'), ('all', 'unspecified'), ('unspecified', 'unspecified')]:
            result = self.data.call('child', 'iccm_children', {'tree': 'config',
                'identifier': 'MOHB01', 'depth': depth, 'kind': kind})
            self.assertEqual(result['status'], 'clarify')
            self.assertFalse(result['records'])
        for depth, kind, total in [('direct', 'objects', 52), ('direct', 'parts', 51), ('all', 'objects', 222)]:
            result = self.data.call('child', 'iccm_children', {'tree': 'config',
                'identifier': 'MOHB01', 'depth': depth, 'kind': kind})
            self.assertEqual(result['record_total'], total)

    def test_attribute_identity_must_not_be_parent_scope(self):
        with self.assertRaisesRegex(ValueError, 'iccm_attributes'):
            self.query('bad', entity={'tree': 'config', 'code': 'MOHB01'})

    def test_explicit_domain_overrides_cross_tree_lookup(self):
        self.data.begin_turn('bound', '构型 MOHB01 的直接下级有哪些？')
        result = self.data.call('bound', 'iccm_find', {'tree': 'objects', 'identifier': 'MOHB01'})
        self.assertEqual({r['tree'] for r in result['records']}, {'config'})
        self.assertEqual(result['lookup_binding']['quote'], '构型 MOHB01')

    def test_new_identifier_cannot_inherit_domain_but_same_one_can(self):
        self.data.begin_turn('identity', '构型 MOHB01 是什么？')
        self.data.call('identity', 'iccm_attributes', {'target': 'config', 'identifier': 'MOHB01', 'properties': ['name']})
        self.data.begin_turn('identity', 'MOHB 那个设备是什么？')
        result = self.data.call('identity', 'iccm_attributes', {'target': 'config', 'identifier': 'MOHB', 'properties': ['name']})
        self.assertEqual(result['status'], 'ambiguous')
        self.data.begin_turn('identity', '设备类 MOHB 是什么？')
        self.data.call('identity', 'iccm_attributes', {'target': 'equipment_class', 'identifier': 'MOHB', 'properties': ['name']})
        self.data.begin_turn('identity', 'MOHB 那个设备是什么？')
        result = self.data.call('identity', 'iccm_attributes', {'target': 'objects', 'identifier': 'MOHB', 'properties': ['name']})
        self.assertEqual(result['entity']['tree'], 'equipment_class')

    def test_negated_or_nonadjacent_domain_is_not_automatically_selected(self):
        from bindings import bindings
        refs = [{'domain': 'config', 'field': 'code', 'value': 'ABC', 'start': 5, 'end': 8}]
        self.assertEqual(bindings('不是构型 ABC', refs, {}), {})
        q = '在构型树中查询 ABC'
        refs[0].update(start=q.index('ABC'), end=len(q))
        self.assertEqual(bindings(q, refs, {}), {})

    def test_units_require_user_source_and_keep_pending_numeric_draft(self):
        plan = {'operation': 'search', 'entity': None, 'scope': 'direct', 'clarification': '',
                'query': {'target': 'points', 'filters': [
                    {'field': 'value', 'operator': 'gt', 'value': '60'},
                    {'field': 'unit', 'operator': 'equals', 'value': '℃'}]}}
        self.data.begin_turn('unit', '哪些点超过60度？')
        result = self.data.call('unit', 'iccm_query', {'intent': plan})
        self.assertEqual(result['status'], 'clarify')
        self.assertNotIn('query_receipt', result)
        ctx = self.data.begin_turn('unit', '单位是摄氏度')
        self.assertEqual(ctx['previous_query']['pending_request']['query']['filters'][0]['value'], '60')
        result = self.data.call('unit', 'iccm_query', {'intent': plan})
        self.assertEqual(result['record_total'], 118)
        for _ in range(2):
            self.data.begin_turn('unit', '再查一次')
            self.assertEqual(self.data.call('unit', 'iccm_query', {'intent': plan})['record_total'], 118)

    def test_batch_domain_binding_applies_to_each_task(self):
        self.data.begin_turn('batchbind', '构型 MOHB01 和设备类 MOHB 的名称')
        tasks = [{'question': value, 'intent': {'operation': 'attributes', 'entity': None,
                  'scope': 'direct', 'clarification': '', 'query': {'target': 'objects', 'filters': [
                  {'field': 'identity', 'operator': 'equals', 'value': value}]}, 'properties': ['name']}}
                 for value in ('MOHB01', 'MOHB')]
        result = self.data.call('batchbind', 'iccm_query', {'intent': {'operation': 'batch',
            'entity': None, 'scope': 'direct', 'clarification': '', 'tasks': tasks}})
        self.assertEqual([r['entity']['tree'] for r in result['items']], ['config', 'equipment_class'])

    def test_bare_name_requires_domain_then_continues(self):
        self.data.begin_turn('bare', '介绍下XXXX1')
        result = self.data.call('bare', 'iccm_find', {'tree': 'pbs', 'identifier': 'XXXX1'})
        self.assertEqual(result['status'], 'clarify')
        self.assertFalse(result['records'])
        self.data.begin_turn('bare', 'PBS')
        result = self.data.call('bare', 'iccm_attributes', {'target': 'pbs', 'identifier': 'XXXX1', 'properties': ['name']})
        self.assertEqual(result['status'], 'ok')

    def test_unspecified_depth_keeps_root_for_supplement(self):
        plan = {'operation': 'search', 'entity': {'tree': 'config', 'code': 'APAC01'},
                'scope': 'all', 'clarification': '', 'query': {'target': 'parts', 'filters': []}}
        self.data.begin_turn('depth', '构型对象描述10435下的构型部件有多少个')
        result = self.data.call('depth', 'iccm_query', {'intent': plan})
        self.assertEqual(result['status'], 'clarify')
        ctx = self.data.begin_turn('depth', '统计全部下级的构型部件')
        self.assertEqual(ctx['previous_query']['pending_request']['entity']['code'], 'APAC01')
        result = self.data.call('depth', 'iccm_query', {'intent': plan})
        self.assertEqual(result['record_total'], 5749)


if __name__ == '__main__':
    unittest.main(verbosity=2)
