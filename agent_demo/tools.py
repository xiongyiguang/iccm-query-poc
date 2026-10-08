"""复用普通问数执行器的只读适配层，不承担自然语言路由。"""
import copy
import json
import re
import sys
import threading
import uuid
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from importer import Imports, counts
from query_plan import execute_plan, task_context
from model import validate, SCHEMA
from request_checklist import literal_references
from result_explanation import explain_result
from bindings import bindings, bind_lookup, unqualified_names
from typed_fields import NUMERIC_FIELDS, UNIT_ALIASES, AMBIGUOUS_UNITS
from request_contract import ground_unit
from attributes import planner_catalog
from analytics import planner_groups
from query_filters import POINT_FIELDS, POINT_RAW_FIELDS, OBJECT_FIELDS, OPERATORS


def spec(name, description, properties, required):
    return {'type': 'function', 'name': name, 'description': description, 'deferLoading': False,
            'inputSchema': {'type': 'object', 'properties': properties,
                            'required': required, 'additionalProperties': False}}


ALLOWED = {'search', 'attributes', 'object', 'equipment', 'equipment_class', 'parts', 'part_class',
           'parent', 'measurements', 'alarms', 'measurement', 'threshold', 'duration', 'analyze',
           'data_overview', 'explain', 'relation_check', 'batch', 'clarify'}
INTENT_SCHEMA = json.loads(SCHEMA.read_text(encoding='utf-8-sig'))
INTENT_SCHEMA['properties']['operation']['enum'] = sorted(ALLOWED)
INTENT_SCHEMA['properties']['tasks']['items']['properties']['intent']['properties']['operation']['enum'] = sorted(ALLOWED - {'batch'})

TOOLS = [
    spec('iccm_catalog', '读取本项目概念、完整查询协议、合法字段及统计维度。首次查数据前调用。', {}, []),
    spec('iccm_find', '按完整名称或编码查找对象；无精确命中时返回包含候选，候选不等于已选定对象。',
         {'identifier': {'type': 'string'}, 'tree': {'type': 'string', 'enum': ['objects', 'pbs', 'config', 'equipment_class', 'part_class', 'points']}}, ['identifier', 'tree']),
    spec('iccm_attributes', '读取一个对象的属性：介绍/是什么对象/名称/数值/温度/阈值/全部属性均优先使用此工具。target是用户指定或同一对象已确定的域；不明时objects跨树定位。测点记录用points。',
         {'target': {'type': 'string', 'enum': ['objects', 'pbs', 'config', 'equipment_class', 'part_class', 'points']},
          'identifier': {'type': 'string', 'minLength': 1, 'maxLength': 300},
          'properties': {'type': 'array', 'minItems': 1, 'items': {'type': 'string', 'enum':
              INTENT_SCHEMA['properties']['properties']['anyOf'][1]['items']['enum']}}},
         ['target', 'identifier', 'properties']),
    spec('iccm_children', '查询构型或PBS下级，自动返回完整对象类型分布；问各类型各多少也用本工具，kind=objects，不能用原始数字层级分组代替。必须分别确定深度和对象类型；用户没说明用unspecified，程序返回澄清。类型objects是所有下级对象，parts仅部件，equipment仅设备。',
         {'tree': {'type': 'string', 'enum': ['pbs', 'config']},
          'identifier': {'type': 'string', 'minLength': 1, 'maxLength': 300},
          'depth': {'type': 'string', 'enum': ['direct', 'all', 'unspecified']},
          'kind': {'type': 'string', 'enum': ['objects', 'parts', 'equipment', 'unspecified']}},
         ['tree', 'identifier', 'depth', 'kind']),
    spec('iccm_query', '执行只读查询或统计。使用catalog中的完整intent协议，不接受SQL或自然语言代替计划。每次返回真实回执、原始依据和第一页；统计针对完整集合。',
         {'intent': INTENT_SCHEMA}, ['intent']),
    spec('iccm_explain', '解释本对话已执行结果的真实查询依据，不能用来猜测未执行的流程。',
         {'result_id': {'type': 'string'}}, ['result_id']),
    spec('iccm_clarify', '记录当前缺少的对象域、范围或单位；不执行数据查询。只追问缺失项，保留已知条件。',
         {'question': {'type': 'string', 'minLength': 1, 'maxLength': 2000}}, ['question']),
    spec('iccm_page', '读取本对话已有结果的下一页或原始依据。不得把第一页当成完整集合。',
         {'result_id': {'type': 'string'}, 'page': {'type': 'integer', 'minimum': 1}}, ['result_id', 'page']),
]


class DataTools:
    def __init__(self):
        self.store = Imports().load()
        self.lock = threading.RLock()
        self.results = {}
        self.contexts = {}
        self.turn_bindings = {}
        self.questions = {}
        self.unscoped_names = {}

    def begin_turn(self, session, question):
        """提供经过核验的引用和回执，不能把它们标成用户批准。"""
        with self.lock:
            refs = literal_references(question, self.store)
            self.questions[session] = question
            self.turn_bindings[session] = bindings(question, refs, self.contexts.get(session))
            self.unscoped_names[session] = unqualified_names(question, refs, self.contexts.get(session))
            return {'snapshot_version': self.store.version, 'lookup_bindings': self.turn_bindings[session],
                    'names_requiring_domain': self.unscoped_names[session],
                    'literal_references': refs,
                    'previous_query': copy.deepcopy(self.contexts.get(session)),
                    'policy': '当前原文优先；新标识重新定位；previous_query仅证明曾执行，不证明本轮沿用。'}

    def meta(self):
        return {'version': self.store.version, 'counts': counts(self.store)}

    def call(self, session, name, args):
        with self.lock:
            if name == 'iccm_catalog':
                return {'snapshot': self.meta(),
                        'knowledge': (ROOT / 'agent_demo/knowledge.txt').read_text(encoding='utf-8'),
                        'query_protocol': (ROOT / 'agent_demo/query-guide.txt').read_text(encoding='utf-8'),
                        'attributes': planner_catalog(), 'grouping': planner_groups(),
                        'fields': {'points': list({**POINT_FIELDS, **POINT_RAW_FIELDS}), 'objects': list(OBJECT_FIELDS), 'operators': sorted(OPERATORS)}}
            if name in ('iccm_page', 'iccm_explain'):
                item = self.results.get((session, args.get('result_id')))
                if item is None:
                    raise ValueError('结果不属于本对话或已经失效，请重新查询。')
                if name == 'iccm_explain':
                    explanation = explain_result(item)
                    receipt = item.get('query_receipt') or {}
                    root = receipt.get('requested_entity')
                    if root and (receipt.get('query') or {}).get('target') in ('pbs', 'config'):
                        explanation['answer'] += ('按真实父对象编码等于根对象编码筛选直接下级；' if receipt.get('scope') == 'direct'
                                                  else '沿真实父引用逐层遍历全部下级；') + '不根据编码前缀判断关系。'
                    return explanation
                return self.page(item, args['result_id'], args.get('page', 1))
            if name == 'iccm_attributes':
                target, identifier = args.get('target'), args.get('identifier')
                if target not in ('objects', 'pbs', 'config', 'equipment_class', 'part_class', 'points'):
                    raise ValueError('属性目标域无效。')
                intent = {'operation': 'attributes', 'entity': None, 'scope': 'direct', 'clarification': '',
                          'query': {'target': target, 'filters': [
                              {'field': 'identity', 'operator': 'equals', 'value': identifier}]},
                          'properties': args.get('properties')}
                return self.call(session, 'iccm_query', {'intent': intent})
            if name == 'iccm_clarify':
                return self.call(session, 'iccm_query', {'intent': {'operation': 'clarify',
                    'entity': None, 'scope': 'direct', 'clarification': args.get('question')}})
            if name == 'iccm_children':
                tree, identifier, depth, kind = (args.get(k) for k in ('tree', 'identifier', 'depth', 'kind'))
                if tree not in ('pbs', 'config') or depth not in ('direct', 'all', 'unspecified') or kind not in ('objects', 'parts', 'equipment', 'unspecified') or not isinstance(identifier, str) or not 0 < len(identifier) <= 300:
                    raise ValueError('请提供合法对象域、完整标识、深度和对象类型。')
                if depth == 'unspecified' or kind == 'unspecified':
                    missing = ([] if depth != 'unspecified' else ['直接下级还是全部下级']) + ([] if kind != 'unspecified' else ['所有对象、仅部件还是仅设备'])
                    intent = {'operation': 'clarify', 'entity': None, 'scope': 'direct',
                              'clarification': '请明确' + '，以及'.join(missing) + '。'}
                else:
                    effective, binding = bind_lookup(tree, identifier, self.turn_bindings.get(session))
                    if effective == 'objects':
                        return self.call(session, 'iccm_attributes', {'target': 'objects', 'identifier': identifier, 'properties': ['name', 'code', 'type']})
                    if effective not in ('pbs', 'config'):
                        raise ValueError('当前标识属于分类字典或测点记录，不能把它改作PBS/构型的下级根。请明确需要的关系。')
                    tree = effective
                    query = {'target': tree, 'filters': [] if kind == 'objects' else [
                        {'field': 'level', 'operator': 'equals', 'value': {'parts': '部件', 'equipment': '设备'}[kind]}]}
                    # 单独解析根对象，避免把根对象误作为后代筛选条件。
                    lookup = execute_plan(self.store, {'operation': 'attributes', 'entity': None,
                        'scope': 'direct', 'clarification': '', 'properties': ['code'],
                        'query': {'target': tree, 'filters': [{'field': 'identity', 'operator': 'equals', 'value': identifier}]}})
                    if lookup.get('status') != 'ok' or not lookup.get('entity'):
                        return self.call(session, 'iccm_attributes', {'target': tree, 'identifier': identifier, 'properties': ['code']})
                    intent = {'operation': 'search', 'entity': lookup['entity'], 'scope': depth,
                              'clarification': '', 'query': query}
                return self.call(session, 'iccm_query', {'intent': intent})
            pending_intent, unit_source = None, ''
            if name == 'iccm_find':
                value, tree = args.get('identifier'), args.get('tree')
                if not isinstance(value, str) or not 0 < len(value) <= 300 or tree not in ['objects', 'pbs', 'config', 'equipment_class', 'part_class', 'points']:
                    raise ValueError('请提供完整标识和合法对象树。')
                if value in self.unscoped_names.get(session, []):
                    return self.call(session, 'iccm_attributes', {'target': tree, 'identifier': value, 'properties': ['name', 'code']})
                tree, applied_binding = bind_lookup(tree, value, self.turn_bindings.get(session))
                intent = {'operation': 'search', 'entity': None, 'scope': 'direct', 'clarification': '',
                          'query': {'target': tree, 'filters': [{'field': 'identity', 'operator': 'equals', 'value': value}]}}
                result = execute_plan(self.store, intent)
                exact = bool(result.get('records'))
                if not exact:
                    intent['query']['filters'][0]['operator'] = 'contains'
                    result = execute_plan(self.store, intent)
                result['match_type'] = 'exact' if exact else 'candidates_only'
                if applied_binding:
                    result['lookup_binding'] = applied_binding
            elif name == 'iccm_query':
                intent, pending_intent, applied_bindings, unit_source = self.prepare(session, args.get('intent'))
                result = execute_plan(self.store, intent)
                if result.get('items'):
                    for i, item in enumerate(result['items']):
                        if applied_bindings[i]: item['lookup_binding'] = applied_bindings[i]
                        if item.get('status') == 'clarify':
                            item['task_context']['pending_request'] = pending_intent['tasks'][i]['intent']
                elif applied_bindings[0]:
                    result['lookup_binding'] = applied_bindings[0]
            else:
                raise ValueError('未知工具。')
            rid = uuid.uuid4().hex
            self.results[session, rid] = result
            if result.get('status') == 'ok' and result.get('match_type') != 'candidates_only':
                self.contexts[session] = {'result_id': rid, **task_context(intent, result),
                                          'unit_source': unit_source}
            elif result.get('status') == 'batch':
                self.contexts[session] = {'result_id': rid, 'branches': [
                    {'question': item['task_question'], 'status': item['status'], **item['task_context']}
                    for item in result['items']]}
            else:
                # 出现歧义或未匹配结果后，不继续沿用更早的成功对象。
                self.contexts[session] = {'result_id': rid, 'status': result.get('status'),
                                          'pending_request': pending_intent or intent, 'answer': result.get('answer')}
            owned = [key for key in self.results if key[0] == session]
            for key in owned[:-20]:
                self.results.pop(key)
            return self.page(result, rid, 1)

    def prepare(self, session, candidate):
        intent = copy.deepcopy(candidate)
        if isinstance(intent, dict) and intent.get('operation') == 'clarify':
            # 尚未执行的草稿可以保留未确定的范围或条件；
            # 它只是待补充草稿，不是执行这些条件的授权。
            question = intent.get('clarification')
            if set(intent) - set(INTENT_SCHEMA['properties']) or not isinstance(question, str) or not 0 < len(question) <= 2000:
                raise ValueError('请提供具体、有效的澄清问题。')
            return ({'operation': 'clarify', 'entity': None, 'scope': 'direct', 'clarification': question},
                    intent, [None], '')
        validate(intent)
        original = copy.deepcopy(intent)
        leaves = [t['intent'] for t in intent['tasks']] if intent['operation'] == 'batch' else [intent]
        if not leaves or any(p['operation'] not in ALLOWED - {'batch'} for p in leaves):
            raise ValueError('此工具仅执行现有只读业务查询。')
        applied, unit_source = [], ''
        for plan in leaves:
            q = plan.get('query') or {}
            entity = plan.get('entity')
            if plan['operation'] == 'attributes' and entity and q:
                raise ValueError('属性查询请使用iccm_attributes；有来源筛选时entity=null，完整标识和source均放入query.filters，不能把目标对象当父范围。')
            binding = None
            identifiers = [f['value'] for f in q.get('filters', []) if f['field'] in ('identity', 'name', 'code') and f['operator'] == 'equals']
            if entity: identifiers.append(entity.get('name', entity.get('code', entity.get('identity'))))
            missing = [v for v in identifiers if v in self.unscoped_names.get(session, [])]
            if missing:
                plan.clear()
                plan.update(operation='clarify', entity=None, scope='direct',
                            clarification='请确认名称“' + '、'.join(missing) + '”所属对象域：PBS、构型、设备类或部件类。已保留原名称，确认后继续读取。')
                applied.append(None)
                continue
            if plan['operation'] in ('attributes', 'object', 'measurement', 'threshold', 'search'):
                identities = [f for f in q.get('filters', []) if f['field'] in ('identity', 'name', 'code') and f['operator'] == 'equals']
                if not entity and len(identities) == 1:
                    q['target'], binding = bind_lookup(q['target'], identities[0]['value'], self.turn_bindings.get(session))
                elif entity and not q and plan['operation'] != 'search':
                    identifier = entity.get('code', entity.get('name', entity.get('identity')))
                    target, binding = bind_lookup(entity['tree'], identifier, self.turn_bindings.get(session))
                    if binding:
                        plan['entity'] = None
                        plan['query'] = {'target': target, 'filters': [{'field': 'identity', 'operator': 'equals', 'value': identifier}]}
            applied.append(binding)
            if plan['operation'] in ('equipment', 'equipment_class') and (entity or {}).get('tree') in ('equipment_class', 'part_class'):
                raise ValueError('关系操作起点须为PBS或构型对象。介绍分类字典自身请用iccm_attributes；参数错误不代表不支持读取该对象。')
            scoped_objects = entity and (plan['operation'] == 'parts' or plan['operation'] in ('search', 'analyze') and q.get('target') in ('pbs', 'config', 'parts', 'equipment'))
            if scoped_objects and not q.get('equipment_class') and session in self.questions:
                question = self.questions[session]
                previous = self.contexts.get(session) or {}
                inherited = previous.get('entity') == entity and previous.get('scope') == plan['scope'] and bool(previous.get('query_receipt'))
                explicit_depth = any(word in question for word in ('直接', '一级', '全部', '所有', '各级', '递归'))
                if not inherited and not explicit_depth:
                    plan.clear()
                    plan.update(operation='clarify', entity=None, scope='direct',
                                clarification='已保留根对象和对象类型，请明确统计直接下级还是全部下级；尚未执行数量统计。')
                    continue
            filters = q.get('filters', []) + (plan.get('analysis') or {}).get('numerator', [])
            numeric = any(f['field'] in NUMERIC_FIELDS and f['operator'] in ('gt', 'gte', 'lt', 'lte', 'eq_num') for f in filters)
            if numeric and session in self.questions:
                question = self.questions[session]
                units = [f['value'] for f in filters if f['field'] == 'unit' and f['operator'] == 'equals']
                previous = self.contexts.get(session) or {}
                same_query = previous.get('query') == q and previous.get('entity') == plan.get('entity') and previous.get('scope') == plan.get('scope')
                current_unit = any(alias in question for alias in UNIT_ALIASES)
                source = question + (' ' + previous.get('unit_source', '') if same_query and not current_unit else '')
                guessed = any(u in AMBIGUOUS_UNITS or ground_unit({'unit': {'state': 'specified', 'value': u}}, source, {})['unit']['state'] != 'specified' for u in units)
                bare_degree = bool(re.search(r'(?:\d|\.)\s*度', question)) and not current_unit
                if guessed or bare_degree:
                    plan.clear()
                    plan.update(operation='clarify', entity=None, scope='direct',
                                clarification='请明确数值条件的单位，例如摄氏度或华氏度；未执行筛选，也没有把“度”默认当摄氏度。')
                else:
                    unit_source = ' '.join(sorted({alias for alias in UNIT_ALIASES if alias in source} | {u for u in units if u and u in source}))
        validate(intent)
        return intent, original, applied, unit_source

    @staticmethod
    def page(result, rid, page):
        if type(page) is not int or not 1 <= page <= 10000:
            raise ValueError('页码无效。')
        value = copy.deepcopy(result)
        records = value.get('records', [])
        value.update(result_id=rid, page=page, page_size=20, record_total=len(records),
                     has_more=page * 20 < len(records))
        value['records'] = records[(page - 1) * 20:page * 20]
        value['returned_record_count'] = len(value['records'])
        # 在分页前计算；只有对象记录具有对象树和层级语义。
        if records and all('tree' in row and 'level' in row for row in records):
            grouped = Counter((row['tree'], str(row['level'])) for row in records)
            value['full_record_summary'] = {'basis': '全部返回对象记录，非当前页',
                'record_total': len(records), 'by_tree_and_level': [
                    {'tree': tree, 'level': level, 'count': count}
                    for (tree, level), count in sorted(grouped.items())]}
        value['answer_contract'] = {'numbers': '使用answer与metrics；records仅分页示例，不作全量推断。',
                                    'attributes': '展示display_value；缺失按status，原始value仅供溯源。'}
        # 依据随本页记录展示，完整结果仍保存在会话缓存中。
        evidence = value.get('evidence', [])
        value['evidence_total'] = len(evidence)
        value['evidence'] = evidence[(page - 1) * 20:page * 20]
        if value.get('items'):
            value['items'] = [DataTools.page(item, rid, page) for item in value['items']]
        return value
