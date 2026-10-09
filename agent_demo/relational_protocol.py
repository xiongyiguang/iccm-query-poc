"""智能体关系任务接入；复用共享关系执行器，不解释自然语言或计算模型答案。"""
import copy
from attributes import CATALOG
from relational_query import canonical, execute, validate_plan, legacy_context, DEFAULTS
from relational_planner import ground, bound_semantics
from query_plan import execute_plan
from query_filters import POINT_FIELDS, POINT_RAW_FIELDS, OBJECT_FIELDS, OPERATORS
from data import QueryError


def nullable(schema):
    return {'anyOf': [{'type': 'null'}, schema]}


LITERAL_ROOT_SCHEMA = {'type': 'object', 'additionalProperties': False, 'required': ['tree', 'field', 'value'],
               'properties': {'tree': {'type': 'string', 'enum': ['pbs', 'config', 'equipment_class', 'part_class', 'points']},
                              'field': {'type': 'string', 'enum': ['code', 'name', 'identity']},
                              'value': {'type': 'string', 'minLength': 1, 'maxLength': 200}}}
ROOT_SCHEMA = {'anyOf': [LITERAL_ROOT_SCHEMA, {'type': 'object', 'additionalProperties': False,
    'required': ['task', 'role'], 'properties': {'task': {'type': 'integer', 'minimum': 1, 'maximum': 4},
    'role': {'type': 'string', 'enum': ['subject', 'pbs', 'pbs_parent', 'pbs_part', 'pbs_device', 'config',
                                     'equipment_config', 'equipment_class', 'part_class', 'parent']}}}]}
SPEC_SCHEMA = {'type': 'object', 'additionalProperties': False, 'properties': {
    'root': nullable(ROOT_SCHEMA),
    'kind': {'type': 'string', 'enum': ['relation', 'collection', 'compare', 'boundary']},
    'population': {'type': 'string', 'enum': ['objects', 'parts', 'devices', 'points']},
    'depth': {'type': 'string', 'enum': ['self', 'direct', 'all']},
    'classes': {'type': 'object', 'additionalProperties': False,
                'properties': {k: {'type': 'string', 'minLength': 1} for k in ('equipment_class', 'part_class')}},
    'filters': {'type': 'array', 'maxItems': 30, 'items': {'type': 'object', 'additionalProperties': False,
                'required': ['field', 'operator', 'value'], 'properties': {
                    'field': {'type': 'string', 'enum': sorted(set(POINT_FIELDS) | set(POINT_RAW_FIELDS) | set(OBJECT_FIELDS) | {'type', 'identity'})},
                    'operator': {'type': 'string', 'enum': sorted(OPERATORS)}, 'value': {'type': 'string'}}}},
    'group_by': nullable({'type': 'string', 'enum': ['class', 'type', 'source', 'location']}),
    'properties': {'type': 'array', 'maxItems': 30, 'items': {'type': 'string', 'enum': sorted(set(CATALOG) | {'line', 'pbs_part', 'location'})}},
    'limit': nullable({'type': 'integer', 'minimum': 1, 'maximum': 100}),
    'sort': {'type': 'array', 'items': {'type': 'string', 'enum': ['code', 'pbs_part', 'name', 'source', 'line']}},
    'only': nullable({'type': 'string', 'enum': ['missing_class', 'unmatched']}),
    'boundary': nullable({'type': 'string', 'enum': ['health', 'duration', 'classification', 'same_record']}),
    'compare_root': nullable(ROOT_SCHEMA)}}
REQUEST_SCHEMA = {'type': 'object', 'additionalProperties': False, 'required': ['mode', 'tasks'],
    'properties': {'mode': {'type': 'string', 'enum': ['new', 'update']}, 'tasks': {'type': 'array', 'minItems': 1, 'maxItems': 4,
        'items': {'type': 'object', 'additionalProperties': False, 'required': ['id', 'quote', 'set'], 'properties': {
            'id': {'type': 'integer', 'minimum': 1, 'maximum': 4},
            'quote': {'type': 'string', 'minLength': 1, 'maxLength': 2000}, 'set': SPEC_SCHEMA}}}}}


def request_context(context):
    return copy.deepcopy(context.get('agent_relational_request'))


def execute_request(data, session, request):
    from protocol_diagnostics import check_structure
    check_structure(REQUEST_SCHEMA, request)
    question = data.questions.get(session, '')
    previous = copy.deepcopy(data.contexts.get(session) or {})
    before = previous.get('agent_relational_request')
    if request['mode'] == 'new' and getattr(data, 'relational_turns', {}).get(session):
        raise ValueError('本轮已有实际关系任务目录；补查或纠正请update已有编号，不能new覆盖本轮已交付目标及其他任务。')
    if request['mode'] == 'update' and not before:
        raise ValueError('尚无关系任务目录，请用new完整声明本轮关系任务。')
    tasks = {} if request['mode'] == 'new' else {t['id']: copy.deepcopy(t) for t in before['tasks']}
    ids = set()
    for patch in request['tasks']:
        tid = patch['id']
        if tid in ids:
            raise ValueError('同一任务本轮不能重复更新。')
        ids.add(tid)
        if patch['quote'] not in question:
            raise ValueError('关系任务quote必须是本轮原话逐字片段，不得引用模型解释。')
        if request['mode'] == 'update' and tid not in tasks:
            raise ValueError('任务编号不属于已有关系目录，不能凭空追加或替换其他任务。')
        if request['mode'] == 'new' and 'kind' not in patch['set']:
            raise ValueError('新关系任务必须明确kind与实际查询目标。')
        raw = {**copy.deepcopy(tasks.get(tid, {}).get('spec') or {}), **copy.deepcopy(patch['set'])}
        # 名称简称只采用目录证明，分类和根分别按实际域核验。
        for key in ('root', 'compare_root'):
            root = raw.get(key)
            if root:
                if 'role' in root:
                    anchors = [t for t in (previous.get('relational_state') or {}).get('tasks', []) if t['id'] == root['task']]
                    values = anchors[0].get('resolved', {}).get(root['role'], []) if len(anchors) == 1 else []
                    values = list({(v['tree'], v['code']): v for v in values}.values())
                    if len(values) != 1:
                        raise ValueError('该关系角色没有唯一已执行身份，不能猜测或跳过一层；请明确完整标识。')
                    identity = values[0]
                    root = {'tree': identity['tree'], 'field': 'code', 'value': identity['code']}
                    raw[key] = root
                root['value'] = data.canonical_identifier(session, root['tree'], root['value'])
        for tree, value in (raw.get('classes') or {}).items():
            raw['classes'][tree] = data.canonical_identifier(session, tree, value)
        tasks[tid] = {'id': tid, 'spec': raw, 'quote': patch['quote']}
    plan = {'operation': 'relational', 'entity': None, 'scope': 'direct', 'clarification': '',
            'relational_tasks': [{'id': t['id'], 'spec': canonical(t['spec'])} for t in sorted(tasks.values(), key=lambda x: x['id'])]}
    validate_plan(plan)
    # 与普通版复用标识来源核验；查表只证明唯一精确身份，不能以相同数量证明语义等价。
    reference = copy.deepcopy(previous)
    reference.setdefault('verified_references', [])
    from request_gateway import reference_context
    reference['verified_references'] += reference_context(previous, None, data.store, question)['references']
    for old in (before or {}).get('tasks', []):
        reference['verified_references'] += [{'value': v} for v in old['spec'].get('classes', {}).values()]
    for task in plan['relational_tasks']:
        checked = copy.deepcopy(task)
        missing = {tree: value for tree, value in checked['spec']['classes'].items()
                   if not data.store.rows('SELECT code FROM objects WHERE tree=? AND (code=? OR name=?)', [tree, value, value])}
        checked['spec']['classes'] = {k: v for k, v in checked['spec']['classes'].items() if k not in missing}
        ground([checked], question, reference, data.store)
        if missing:
            # 用户有据地指定未登记类别属于该任务资料不足；不能拖掉其他独立任务。
            ground([{'spec': {'root': None, 'compare_root': None, 'classes': missing}}], question, reference)
    plan['relational_tasks'] = bound_semantics({'handled': True, 'tasks': plan['relational_tasks']}, data.store)['tasks']
    # 完整分类已包含未关联原对象；把同一集合的两个展示面拆成独立任务会在续问重复交付。
    for a in plan['relational_tasks']:
        for b in plan['relational_tasks']:
            qa, qb = a['spec'], b['spec']
            if qa['group_by'] == 'class' and qb['only'] == 'missing_class' and all(
                    qa[k] == qb[k] for k in ('root', 'population', 'depth', 'classes', 'filters')):
                raise ValueError('同一集合完整分类已交付未关联明细，两者是同一目标的展示面，不是独立任务；请保留一个分类任务，续问缺失明细用update group_by=null、only=missing_class。')
    items, anchors = [], []
    for task in plan['relational_tasks']:
        tid, q = task['id'], task['spec']
        try:
            item = execute(data.store, {**plan, 'relational_tasks': [task]})
            state = item['relational_state']['tasks'][0]
            root, props = q['root'], tasks[tid]['spec'].get('properties', [])
            if (root and root['tree'] == 'points' and props and set(props) <= set(CATALOG)
                    and not set(props) & {'parent', 'class_code', 'pbs_part', 'location'}
                    and q['kind'] in ('relation', 'collection')
                    and not any(q[k] for k in ('classes', 'filters', 'group_by', 'limit', 'only', 'boundary'))):
                # 精确测点原字段严格投影交回既有属性执行器，身份和关联状态仍保留。
                item = execute_plan(data.store, {'operation': 'attributes', 'entity': None, 'scope': 'direct', 'clarification': '',
                    'query': {'target': 'points', 'filters': [{'field': root['field'], 'operator': 'equals', 'value': root['value']}]},
                    'properties': props})
        except QueryError as error:
            state = {**copy.deepcopy(task), 'resolved': {}}
            item = {'status': 'error', 'answer': str(error) + '；该任务未完成，不能视作零。', 'records': [],
                    'metrics': [], 'evidence': [], 'path': [], 'entity': None, 'scope': q['depth'],
                    'note': '已保留此任务的原目标，其他独立任务分别交付。'}
        anchors.append(state)
        if q['population'] == 'points' and q['group_by'] == 'source':
            item['note'] += '原行号取原CSV行号；同码及同来源的原始行分别保留，记录数与不同完整编码数分开计算。'
        item.update(task_number=tid, task_question='任务 ' + str(tid))
        items.append(item)
    state = {'tasks': anchors}
    for item, task in zip(items, plan['relational_tasks']):
        item['task_context'] = legacy_context(item, state, task['spec'])
    result = items[0] if len(items) == 1 else {'status': 'batch', 'answer': '已分别交付 ' + str(len(items)) + ' 个独立任务。',
        'items': items, 'records': [], 'metrics': [], 'evidence': [], 'path': [], 'entity': None, 'scope': 'direct', 'note': ''}
    result['relational_state'] = state
    result['agent_relational_request'] = {'version': 1, 'revision': (before or {}).get('revision', 0) + 1,
        'tasks': [tasks[k] for k in sorted(tasks)]}
    result['relation_delivery'] = {'task_ids': [t['id'] for t in plan['relational_tasks']],
        'completed': all(i['status'] == 'ok' and not i.get('missing_links') and not i.get('outcome') for i in items),
        'partial_or_insufficient': any(i['status'] != 'ok' or i.get('missing_links') or i.get('outcome') for i in items)}
    context = {'relational_state': state, 'agent_relational_request': result['agent_relational_request'],
               'dialogue': previous.get('dialogue', []), 'completed_request_history': previous.get('completed_request_history', [])}
    if len(items) == 1:
        context.update(items[0]['task_context'])
    else:
        context['branches'] = [copy.deepcopy(i['task_context']) for i in items]
    data.contexts[session] = context
    if not hasattr(data, 'relational_turns'):
        data.relational_turns = {}
    data.relational_turns[session] = True
    return data.save_result(session, result)
