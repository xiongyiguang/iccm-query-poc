"""智能体的有据任务协议；复用公共状态与计算规则，不解释自然语言。"""
import copy


def object_schema(properties, required):
    return {'type': 'object', 'properties': properties, 'required': required,
            'additionalProperties': False}


GOAL_SCHEMA = object_schema({
    'kind': {'type': 'string', 'enum': ['records', 'count', 'attributes', 'extreme', 'sort', 'difference', 'unsupported']},
    'field': {'type': ['string', 'null'], 'enum': [None, 'value', 'time', 'thresholds']},
    'direction': {'type': ['string', 'null'], 'enum': [None, 'asc', 'desc', 'absolute']},
    'limit': {'type': ['integer', 'null'], 'description': '前N的N；程序校验1至100；极值必须null，保留全部并列。'},
    'ties': {'type': 'string', 'enum': ['all']},
    'operands': {'type': 'array', 'maxItems': 2, 'items': object_schema({
        'field': {'type': 'string', 'enum': ['name', 'code', 'identity']},
        'value': {'type': 'string'}}, ['field', 'value'])},
    'basis': {'type': 'string', 'enum': ['measurement', 'raw_numbers'],
              'description': 'raw_numbers只在用户明确同意纯数值运算/排序时使用；单位相同不证明物理量可比。'}
}, ['kind', 'field', 'direction', 'limit', 'ties', 'operands', 'basis'])


def request_schema(intent_schema):
    from query_filters import OPERATORS
    from data_context import STATIC_TOPICS
    condition = copy.deepcopy(intent_schema['properties']['query']['anyOf'][1]['properties']['filters']['items'])
    condition['properties']['operator']['enum'] = sorted(OPERATORS)
    props = copy.deepcopy(intent_schema['properties']['properties'])
    # 属性清单无需null：未修改时省略该字段。
    props = next(x for x in props['anyOf'] if x.get('type') == 'array')
    # search合法地不选属性；attributes仍由业务编译器要求非空。
    props['minItems'] = 0
    props['description'] = '指定目录属性ID；全部属性只用星号。全部阈值须列目录18个具体ID，thresholds只是goal.field，不是property。'
    edit = object_schema({
        'action': {'type': 'string', 'enum': ['add', 'replace', 'remove']},
        'ids': {'type': 'array', 'items': {'type': 'string'}, 'description': '已有稳定条件编号；add为空数组。'},
        'conditions': {'type': 'array', 'items': condition, 'description': 'remove为空；其他动作至少一项。'},
        'quote': {'type': 'string', 'description': '本轮用户原文中的逐字片段，不能改写。'}
    }, ['action', 'ids', 'conditions', 'quote'])
    settings = object_schema({
        'operation': {'type': 'string', 'enum': ['search', 'attributes', 'explain', 'unsupported']},
        'target': {'type': 'string', 'enum': ['points', 'pbs', 'config', 'equipment_class', 'part_class', 'objects', 'parts', 'equipment']},
        'scope': {'type': 'string', 'enum': ['direct']},
        'properties': props,
        'topics': {'type': 'array', 'items': {'type': 'string', 'enum': sorted(STATIC_TOPICS)}},
        'result_goal': GOAL_SCHEMA,
    }, [])
    patch = object_schema({
        'base': {'type': ['string', 'null'], 'description': 'new用null；update用task_directory中的t1等，不按顺序猜测。'},
        'quote': {'type': 'string', 'minLength': 1, 'maxLength': 500},
        'set': settings,
        'subject': {'anyOf': [{'type': 'null'}, object_schema({
            'field': {'type': 'string', 'enum': ['name', 'code', 'identity']},
            'value': {'type': 'string', 'minLength': 1, 'maxLength': 300}}, ['field', 'value'])],
            'description': '新建单对象属性任务必须在此声明标识；新建集合查询与update填null。引用需来自本轮原文或已核验历史。'},
        'filters': {'type': 'array', 'items': edit, 'maxItems': 8,
                    'description': '追加、替换或删除的筛选条件；集合范围、来源、状态、数值及日期都在这里声明，不能只写在quote里。'},
        'parent_range': {'anyOf': [{'type':'string','enum':['all_imported','inherit']}, object_schema({'tree':{'type':'string','enum':['pbs']},'field':{'type':'string','enum':['name','code','identity']},'value':{'type':'string','minLength':1,'maxLength':300},'quote':{'type':'string','minLength':1,'maxLength':500}}, ['tree','field','value','quote'])], 'description':'PBS父对象范围与测点自身筛选分开：对象自身及全部后代关联测点。新全表用all_imported；续改原范围用inherit；改根需完整有据对象。'},
        'unit': object_schema({'state': {'type': 'string', 'enum': ['none', 'ambiguous', 'specified']},
                               'value': {'type': 'string','description':'none与ambiguous必须空串；specified才填明确单位。'}}, ['state', 'value']),
        'purpose': {'type': 'string', 'enum': ['data', 'identity', 'introduction']},
        'subject_scope': {'type': 'string', 'enum': ['none', 'explicit', 'confirmed', 'unspecified', 'cross_tree']},
        'replace_task': {'type': 'boolean'},
        'retain_filters': {'type': 'array', 'items': {'type': 'string'}},
        'execute': {'type': 'boolean', 'description': '必须显式声明本轮是否交付；只保留另一个任务不变时false，不修改状态；本轮重查或修改交付时true。'},
    }, ['base', 'quote', 'set', 'filters', 'subject', 'execute', 'parent_range'])
    return object_schema({'mode': {'type': 'string', 'enum': ['new', 'update']},
                          'tasks': {'type': 'array', 'minItems': 1, 'maxItems': 4, 'items': patch}}, ['mode', 'tasks'])


def execute_request(data, session, proposal, clarification=None):
    """来源核验→应用增量→独立编译分支→执行→按真实结果提交任务状态。"""
    from business_request import (apply_delta, ground_identifiers, compile_task,
                                  RequestAmbiguous, commit_state, extraction_context)
    from request_gateway import reference_context
    from result_goal import GoalConstraintError
    from query_plan import execute_plan, task_context
    from query_filters import validate_query
    previous = copy.deepcopy(data.turn_contexts.get(session, data.contexts.get(session) or {}))
    question = data.questions.get(session)
    if not isinstance(question, str):
        raise ValueError('业务请求必须属于当前用户轮次。')
    if not isinstance(proposal, dict) or set(proposal) != {'mode', 'tasks'}:
        raise ValueError('请求必须完整声明mode和tasks。')
    from protocol_diagnostics import prepare_request
    prepared, ignored = prepare_request(proposal, data.request_schema)
    delta = {'version': 1, **prepared}
    old_state = previous.get('pending_business_request') or previous.get('business_request')
    if not isinstance(delta['tasks'], list):raise ValueError('tasks必须是任务数组。')
    range_specs = []
    for patch in delta.get('tasks', []):
        if not isinstance(patch, dict) or not {'base', 'quote', 'set', 'filters', 'subject', 'execute'} <= set(patch):
            raise ValueError('任务必须完整声明base、quote、set、filters、subject和execute。')
        if clarification is not None and patch['execute'] is False and (
                delta['mode'] == 'new' or patch.get('set') or patch.get('filters') or patch.get('subject') is not None):
            # 澄清工具只写内存草稿，绝不执行数据查询。
            # 内部V1的execute表示应用本轮请求动作，不是查询授权；
            # 不能把新草稿误判为“保留一个尚不存在的旧任务”。
            patch['execute'] = True
        fields = patch.get('set', {})
        range_spec = patch.pop('parent_range', 'inherit' if delta['mode']=='update' else 'all_imported')
        if fields.get('operation') in ('explain','unsupported'):
            if range_spec not in ('inherit','all_imported'):
                raise ValueError('说明任务不能携带父对象范围；只声明operation与合法topics。')
            # 兼容已暴露的中性元数据；不删除任何实际对象、单位或筛选。
            if patch.get('purpose')=='data' and patch.get('subject_scope')=='none':
                patch.pop('purpose');patch.pop('subject_scope')
            if patch.get('unit')=={'state':'none','value':''}:patch.pop('unit')
        elif 'topics' in fields:
            raise ValueError('topics仅属于说明任务；按字段分组计数请用iccm_query analyze，不能把问句放进topics。')
        range_specs.append(range_spec)
        subject = patch.pop('subject', None)
        if subject is not None:
            if not isinstance(subject, dict) or set(subject) != {'field', 'value'} or subject['field'] not in ('identity', 'name', 'code'):
                raise ValueError('subject须为有据标识field/value。')
            if fields.get('operation')!='attributes':
                raise ValueError('subject只用于新单对象属性；集合条件放filters，PBS父范围放parent_range，不能把父对象当测点自身名称或编码。')
            if delta['mode'] != 'new' and not patch.get('replace_task'):
                raise ValueError('更新任务的subject必须null；改对象需按旧过滤ID显式replace，不能暗中追加互斥标识。')
            if any(c.get('field') in ('identity', 'name', 'code') for e in patch.get('filters', []) for c in e.get('conditions', [])):
                raise ValueError('subject与filters不能重复声明对象身份；其他筛选条件仍保留。')
            patch.setdefault('filters', []).insert(0, {'action': 'add', 'ids': [], 'quote': patch.get('quote'),
                'conditions': [{'field': subject['field'], 'operator': 'equals', 'value': subject['value']}]})
        old_task = next((t for t in (old_state or {}).get('tasks', []) if t['id'] == patch.get('base')), {})
        operation = fields.get('operation', old_task.get('operation'))
        if operation == 'attributes' and delta['mode'] == 'new' and not any(
                c.get('field') in ('name', 'code', 'identity') and c.get('operator') == 'equals'
                for e in patch.get('filters', []) for c in e.get('conditions', [])):
            raise ValueError('属性任务缺少对象：请在subject={field:identity/name/code,value:原文完整标识}声明；只写quote或target不足以定位。')
        if operation in ('search', 'attributes') and patch.get('execute', True):
            if 'result_goal' not in fields and (delta['mode'] == 'new' or patch.get('replace_task') or 'result_goal' not in old_task):
                raise ValueError('请完整声明七字段result_goal；不能用普通列表冒充排序、极值或差值。')
            if delta['mode'] == 'new' or patch.get('replace_task'):
                if not {'purpose', 'subject_scope'} <= set(patch):
                    raise ValueError('新任务须说明purpose和subject_scope，不能猜测对象树。')
        for edit in patch.get('filters', []):
            # 公共校验器再验证合取；此处也限制无效的字段结构。
            for condition in edit.get('conditions', []):
                validate_query({'target': fields.get('target', old_task.get('target', 'points')), 'filters': [condition]})
    refs = reference_context(previous, None, data.store, question)
    try:
        try:
            _, state, changed = apply_delta(delta, old_state, question, refs)
        except RequestAmbiguous as error:
            if not error.state:
                raise
            state = error.state
            changed = state['last_executed_tasks']
        active_ranges=[r for p,r in zip(delta['tasks'],range_specs) if p.get('execute',True)]
        for tid,spec in zip(changed,active_ranges):
            task=next(t for t in state['tasks'] if t['id']==tid)
            apply_parent_range(data,task,spec,question,refs,state['revision'],delta['mode'])
        state = ground_identifiers(data.store, state, changed)
        quotes = [p['quote'] for p in delta['tasks'] if p.get('execute', True)]
        plans = []
        for tid, quote in zip(changed, quotes):
            task = next(t for t in state['tasks'] if t['id'] == tid)
            try:
                if tid in state.get('pending_tasks', []) and state.get('pending_reason') == 'domain':
                    raise RequestAmbiguous('请说明对象所属域：PBS、构型、设备类还是部件类；已有条件已保留。')
                intent = compile_task(task)
                parent=(task['sources'].get('parent_range') or {}).get('entity')
                if parent:
                    intent['entity']=copy.deepcopy(parent)
                elif (task['sources'].get('parent_range') or {}).get('resolution'):
                    intent=copy.deepcopy(task['sources']['parent_range']['resolution'])
            except RequestAmbiguous as error:
                intent = {'operation': 'clarify', 'entity': None, 'scope': 'direct', 'clarification': str(error)}
            plans.append({'question': quote, 'intent': intent})
        plan = (plans[0]['intent'] if len(plans) == 1 else
                {'operation': 'batch', 'entity': None, 'scope': 'direct', 'clarification': '', 'tasks': plans}) if plans else {
                    'operation': 'conversation', 'entity': None, 'scope': 'direct', 'clarification': '', 'message': '已保留任务，本轮未执行。'}
        result = ({'status': 'clarify', 'answer': clarification, 'records': [], 'metrics': [], 'evidence': [],
                   'entity': None, 'scope': 'direct', 'request_executed': False} if clarification is not None else execute_plan(data.store, plan))
        items=result.get('items') if result.get('status')=='batch' else [result]
        for tid,item in zip(changed,items):
            if item.get('status')=='clarify' and state.get('pending_reason')=='domain' and tid in state.get('pending_tasks',[]):
                attach_domain_candidates(data,next(t for t in state['tasks'] if t['id']==tid),item)
        trace = {'engine': 'business_request', 'business_request_state': state,
                 'changed_tasks': changed, 'business_request_delta': delta}
        context = {**previous, **task_context(plan, result)}
        commit_state(context, trace, result, previous)
        if context.get('pending_business_request'):
            context['pending_question'] = question
        else:
            context.pop('pending_question', None)
        data.contexts[session] = context
        result['request_state'] = request_context(context)
        result['task_ids'] = changed
        if ignored:
            result['protocol_adjustments'] = ignored
        return data.save_result(session, result)
    except GoalConstraintError as error:
        # 无效边界不是已执行任务；保留原权威状态及失败提案，便于用户改N。
        data.contexts[session] = {**previous, 'rejected_request': {'proposal': copy.deepcopy(proposal), 'question': question,
                                                                 'business_constraint': error.business_constraint}}
        result = {'status': 'clarify', 'answer': str(error), 'records': [], 'metrics': [], 'evidence': [],
                  'business_constraint': error.business_constraint, 'request_executed': False}
        if ignored:
            result['protocol_adjustments'] = ignored
        return data.save_result(session, result)


def adopt_attribute_request(data, session, intent, result, context, previous):
    """兼容属性工具保留已声明参数；不从原话猜测新的查询目标。"""
    from business_request import apply_delta, RequestAmbiguous, commit_state, ground_identifiers
    from request_gateway import reference_context
    from result_goal import default_goal
    if intent.get('operation') != 'attributes' or intent.get('entity') or not intent.get('query'):
        return
    question = data.questions.get(session)
    if not question or len(question) > 500:
        return
    old = previous.get('pending_business_request') or previous.get('business_request')
    if old and old.get('origin') not in ('executed_legacy_receipt', 'agent_legacy_tool'):
        return
    original = copy.deepcopy(intent)
    query = original['query']
    patch = {'base': None, 'quote': question, 'set': {'operation': 'attributes', 'target': query['target'],
             'properties': original['properties'], 'result_goal': original.get('result_goal') or default_goal('attributes')},
             'filters': [{'action': 'add', 'ids': [], 'conditions': query['filters'], 'quote': question}],
             'purpose': 'data', 'subject_scope': 'none'}
    identities = [f for f in query['filters'] if f['field'] in ('name', 'code', 'identity') and f['operator'] == 'equals']
    if len(identities) == 1 and identities[0]['value'] in data.unscoped_names.get(session, []):
        patch['set']['target'] = 'objects'
        patch.update(purpose='introduction', subject_scope='unspecified')
    delta = {'version': 1, 'mode': 'new', 'tasks': [patch]}
    try:
        try:
            _, state, changed = apply_delta(delta, None, question, reference_context(previous, None, data.store, question))
        except RequestAmbiguous as error:
            if not error.state:raise
            state, changed = error.state, error.state['last_executed_tasks']
        state = ground_identifiers(data.store, state, changed)
        state['origin'] = 'agent_legacy_tool'
        commit_state(context, {'engine': 'business_request', 'business_request_state': state, 'changed_tasks': changed,
                               'business_request_delta': delta}, result, previous)
        if context.get('pending_business_request'):context['pending_question'] = question
    except ValueError:
        # 无法证明来源的旧参数仍由原工具报告，不能生成假的有据状态。
        return


def request_context(context):
    """展示同一任务状态中的父范围，不建立第二份会话状态。"""
    from business_request import extraction_context
    out=copy.deepcopy(extraction_context(context))
    state=out.get('business_request') or {}
    by_id={t['id']:t for t in state.get('tasks',[])}
    for task in out.get('task_directory',[]):
        task['parent_range']=copy.deepcopy(by_id[task['id']]['sources'].get('parent_range') or {'requested':None})
    return out


def apply_parent_range(data,task,spec,question,refs,revision,mode):
    """仅编译显式声明的PBS父范围；来源/精确定位/真实父链分别核验。"""
    from identifier_aliases import complete_literal_pattern
    import re
    if spec=='inherit':
        if mode!='update':raise ValueError('新任务不能继承父范围；请声明all_imported或PBS根对象。')
        return
    if spec=='all_imported':
        task['sources']['parent_range']={'kind':'agent_parent_range','requested':None,'turn':revision}
        return
    if task['operation']!='search' or task['target']!='points':
        raise ValueError('当前结构化父范围仅支持PBS自身及全部后代关联的测点记录；其他关系仍用原工具。')
    if not isinstance(spec,dict) or set(spec)!={'tree','field','value','quote'} or spec['tree']!='pbs' or spec['field'] not in ('name','code','identity'):
        raise ValueError('父范围须声明PBS树、完整标识字段/值和本轮quote。')
    value,quote=spec['value'],spec['quote']
    if not isinstance(value,str) or not 0<len(value)<=300 or not isinstance(quote,str) or not 0<len(quote)<=500 or quote not in question:
        raise ValueError('父范围缺少本轮原话依据。')
    present=bool(re.search(complete_literal_pattern(value),quote))
    verified=[r for r in refs.get('references',[]) if r.get('value')==value and r.get('domain')=='pbs' and r.get('field') in ('identity',spec['field'])]
    if not present and not verified:raise ValueError('父对象标识缺少原话或同域已核验引用。')
    previous=task['sources'].get('parent_range') or {}
    text=quote.replace(value,'')
    if not re.search('PBS',text,re.I) and not (mode=='update' and (previous.get('requested') or {}).get('tree')=='pbs'):
        raise ValueError('新父范围须明确属于PBS，不能按数据命中猜测对象树。')
    if any(w in text for w in ('构型','设备类','部件类')):raise ValueError('父对象域与PBS声明不一致。')
    identifier=value
    clause='(code=? OR name=?)' if spec['field']=='identity' else spec['field']+'=?'
    args=[identifier,identifier] if spec['field']=='identity' else [identifier]
    rows=data.store.rows('SELECT * FROM objects WHERE tree=? AND '+clause+' ORDER BY code',['pbs']+args)
    source={'kind':'agent_parent_range','requested':copy.deepcopy(spec),'turn':revision,'quote':quote}
    if len(rows)==1:source['entity']={'tree':'pbs','code':rows[0]['code']}
    else:source['resolution']={'operation':'clarify','entity':None,'scope':'direct','clarification':'父对象未找到或不唯一，请明确PBS根对象。'}
    task['sources']['parent_range']=source


def attach_domain_candidates(data,task,result):
    """返回实际精确身份候选辅助选树，未读取所问属性或完成计算。"""
    filters=task['filters']
    if task['operation']!='attributes' or task['target']!='objects' or len(filters)!=1:return
    f=filters[0]
    if f['field'] not in ('identity','name','code') or f['operator']!='equals':return
    clause='(code=? OR name=?)' if f['field']=='identity' else f['field']+'=?'
    args=[f['value'],f['value']] if f['field']=='identity' else [f['value']]
    total=data.store.rows('SELECT count(*) n FROM objects WHERE '+clause,args)[0]['n']
    if total<2:return
    rows=data.store.rows('SELECT * FROM objects WHERE '+clause+' ORDER BY tree,code LIMIT 20',args)
    result.update(status='ambiguous',candidate_only=True,record_total=total,identity_lookup_only=True,request_executed=False,
        candidate_count=total,count_computed=False,
        records=[{**{k:r[k] for k in ('tree','code','name','level')},'evidence':data.store.ref(r)} for r in rows])
    # 不添加outcome，保留domain待补槽位，不能把选树改成已确认任务。
