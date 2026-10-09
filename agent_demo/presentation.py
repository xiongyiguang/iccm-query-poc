"""把结构化计划和回执转换为业务标签，不解释用户问题。"""
from tools import ROOT  # 设置现有只读执行器的模块导入路径。
from attributes import CATALOG
from query_filters import TARGET_LABELS

TREES = {'pbs': 'PBS现场对象', 'config': '构型对象', 'equipment_class': '设备类',
         'part_class': '部件类', 'points': '测点记录', 'objects': '各对象树'}
OPS = {'search': '筛选记录', 'analyze': '统计分析', 'attributes': '读取属性',
       'object': '查看对象', 'equipment': '查找对应设备', 'equipment_class': '查找设备类',
       'parts': '查找部件', 'part_class': '查找部件类', 'parent': '查找上级对象',
       'measurements': '查找关联测点', 'alarms': '查找开启且已报警测点',
       'measurement': '读取测量记录', 'threshold': '读取数值与阈值',
       'duration': '核查报警时长依据', 'data_overview': '查看数据概况',
       'explain': '说明数据概念', 'relation_check': '核查对象关系'}
OPERATORS = {'equals': '等于', 'eq_num': '=', 'ne_num': '≠', 'gt': '>', 'gte': '≥',
             'lt': '<', 'lte': '≤', 'contains': '包含', 'not_contains': '不包含',
             'starts_with': '以此开头', 'is_blank': '为空', 'not_blank': '非空'}
OPERATORS.update(date_equals='日期属于', date_gte='时间不早于', date_lt='时间早于')


def label(field):
    return {'identity': '名称或编码', 'location': '最近功能位置', 'thresholds': '报警阈值'}.get(field, CATALOG.get(field, {}).get('label', field))


def condition(f):
    op = f.get('operator', '')
    value = '' if op in ('is_blank', 'not_blank') else '「' + str(f.get('value', '')) + '」'
    return f"{label(f.get('field', ''))} {OPERATORS.get(op, op)}{value}"


def plan_view(intent):
    if not isinstance(intent, dict):
        return {'title': '核对查询请求', 'rows': []}
    op = intent.get('operation')
    if op == 'batch':
        return {'title': '分别查询多个问题', 'rows': [], 'tasks': [
            {'question': t.get('question', ''), **plan_view(t.get('intent'))}
            for t in intent.get('tasks', []) if isinstance(t, dict)]}
    entity = intent.get('resolved_entity') or intent.get('entity') or intent.get('requested_entity')
    q = intent.get('query') or {}
    target = q.get('target')
    scoped_parts = target == 'parts' and isinstance(entity, dict) and entity.get('tree') == 'pbs'
    rows = []
    def row(k, v):
        if v: rows.append({'label': k, 'text': v})
    row('查询目标', '现场挂接部件' if scoped_parts else TARGET_LABELS.get(target))
    if entity:
        row('对象 / 范围', f"{TREES.get(entity.get('tree'), entity.get('tree', ''))} · {entity.get('code', '')}")
        # 测点范围始终包含 PBS 根对象及其后代，direct 不会缩小该范围。
        if (target == 'points' and op not in ('attributes', 'measurement', 'threshold')) or op in ('measurements', 'alarms'):
            row('查找范围', '该PBS对象自身及全部后代关联的测点记录')
        elif op in ('search', 'analyze', 'parts'):
            row('查找范围', {'all': '全部下级', 'direct': '直接下级'}.get(intent.get('scope'), intent.get('scope')))
    elif target:
        row('对象 / 范围', '本次导入快照 · 未限定父对象范围')
    if q.get('equipment_class'):
        row('设备类别', condition(q['equipment_class']))
    for f in q.get('filters', []):
        row('筛选条件（同时满足）', condition(f))
    if op == 'alarms':
        row('筛选条件（同时满足）', '开关等于「开启」；报警状态等于「已报警」')
    if intent.get('properties'):
        row('读取内容', '全部属性' if intent['properties'] == ['*'] else '、'.join(label(p) for p in intent['properties']))
    goal = intent.get('result_goal') or {}
    if goal:
        row('交付目标', {'records': '记录列表', 'count': '完整集合计数', 'attributes': '指定属性',
                       'sort': '排序', 'extreme': '极值及全部并列', 'difference': '两项差值', 'unsupported': '尚不支持'}.get(goal.get('kind')))
        row('排序 / 计算字段', label(goal.get('field')) if goal.get('field') else '')
        row('方向', {'asc': '升序 / 最小 / 最早', 'desc': '降序 / 最大 / 最新', 'absolute': '绝对差'}.get(goal.get('direction')))
        if goal.get('limit') is not None:row('展示数量', str(goal['limit']))
        if goal.get('kind') == 'difference':
            row('操作数顺序', ' → '.join(str(x.get('value', '')) for x in goal.get('operands', [])))
        row('运算口径', '仅原始数值，未认定物理量可比' if goal.get('basis') == 'raw_numbers' else '按数据与物理量证据核验')
    a = intent.get('analysis') or {}
    if a.get('kind') == 'ratio':
        row('统计口径', '按测点源记录计算占比；以上筛选为分母，以下附加条件为分子，不按编码去重')
        for f in a.get('numerator', []): row('分子附加条件', condition(f))
    elif a.get('kind') == 'group_count':
        row('统计口径', '按部件类编码分组；部件数量与类别数量分别统计，未匹配分类另列'
            if a.get('group_by') == 'class_code' else f"按{label(a.get('group_by', ''))}分组，统计完整筛选集合")
        row('排序 / 展示', f"数量{'从少到多' if a.get('order') == 'asc' else '从多到少'}，最多 {a.get('limit', 100)} 组；明细另分页")
    elif target == 'points':
        row('结果口径', '保留测点源记录；记录条数与不同编码数分别计算')
    if scoped_parts:
        route = 'PBS范围 → 对应设备构型及设备类 → 实际挂接部件'
    elif target == 'points' and op in ('attributes', 'measurement', 'threshold'):
        route = '定位测点记录 → 读取指定属性'
    elif target == 'points':
        route = '关联测点记录 → 按条件筛选' if entity else '测点记录 → 按条件筛选'
    else:
        route = OPS.get(op, '核对请求')
    if a.get('kind') == 'group_count': route += ' → 分组统计'
    elif a.get('kind') == 'ratio': route += ' → 分子 / 分母计算'
    return {'title': OPS.get(op, '核对查询请求'), 'rows': rows, 'route': route}


def tool_view(name, args, result=None):
    try:
        return _tool_view(name, args, result)
    except (TypeError, AttributeError, KeyError, ValueError):
        # 展示格式不能授权、修复或阻断查询计划，由校验器决定能否执行。
        return {'title': '核对查询请求', 'rows': [], 'route': '参数需要校验，尚不能确定查询口径'}


def _tool_view(name, args, result=None):
    if name == 'iccm_relational':
        if result and result.get('items'):
            return {'title': '分别交付跨表关系任务', 'rows': [], 'tasks': [
                dict(tool_view(name, {}, item), question=item.get('task_question', '')) for item in result['items']]}
        state = ((result or {}).get('task_context') or {}).get('relational_state') or (result or {}).get('relational_state') or {}
        tasks = state.get('tasks') or (args.get('request') or {}).get('tasks') or []
        tid = (result or {}).get('task_number')
        task = next((t for t in tasks if t.get('id') == tid), tasks[0] if tasks else {})
        q = task.get('spec') or task.get('set') or {}
        root = q.get('root')
        if root and 'role' in root:
            roles = {'subject':'原对象','equipment_class':'设备类','part_class':'部件类','parent':'直接父对象',
                     'pbs':'PBS对象','pbs_parent':'PBS直接父对象','pbs_part':'现场部件','pbs_device':'现场设备',
                     'config':'精确构型','equipment_config':'设备构型'}
            root_text = '任务 ' + str(root['task']) + ' 已查到的' + roles[root['role']] + '；等待核验唯一身份'
        else:
            root_text = (TREES.get(root['tree'], root['tree']) + ' · ' + root['value']) if root else '沿用关系任务目录或已明确全表'
        rows = [{'label': '对象 / 范围', 'text': root_text}]
        rows.append({'label': '交付目标', 'text': {'relation': '精确对象及实际关系', 'collection': '完整关联集合', 'compare': '现场与构型逐项核对', 'boundary': '核查资料与结论依据'}.get(q.get('kind'), '核对任务变更')})
        if q.get('kind') == 'collection':
            rows.append({'label': '集合范围', 'text': {'self': '对象自身', 'direct': '直接下级', 'all': '全部下级'}.get(q.get('depth'), '执行后核验')})
        return {'title': '跨表关系查询', 'rows': rows, 'route': (result or {}).get('note', '按真实父关系及精确引用执行；缺失不补造'), 'executed': bool(result and result.get('status') in ('ok', 'batch', 'data_insufficient'))}
    if name == 'iccm_request':
        if result:
            if result.get('items'):
                return {'title': '分别完成本轮任务', 'rows': [], 'tasks': [
                    dict(tool_view('iccm_request', {}, item), question=item.get('task_question', '')) for item in result['items']]}
            receipt = result.get('query_receipt')
            if receipt:
                return tool_view('iccm_query', {'intent': receipt}, result)
            return {'title': '保留任务，确认待补项', 'rows': [], 'route': result.get('answer', '本轮未执行数据查询'), 'executed': False}
        tasks = (args.get('request') or {}).get('tasks', [])
        return {'title': '核对本轮任务与条件变更', 'rows': [], 'tasks': [
            {'question': task.get('quote', ''), **request_plan_view(task)} for task in tasks]}
    if name == 'iccm_clarify':
        return {'title': '确认缺失的查询条件', 'rows': [], 'route': '保留已有条件，等待补充；尚未执行数据查询', 'executed': False}
    if name == 'iccm_attributes':
        intent = {'operation': 'attributes', 'entity': None, 'properties': args.get('properties'),
                  'query': {'target': args.get('target'), 'filters': [
                      {'field': 'identity', 'operator': 'equals', 'value': args.get('identifier')}]}}
        return _tool_view('iccm_query', {'intent': intent}, result)
    if name == 'iccm_children':
        intent = {'operation': 'search', 'entity': {'tree': args.get('tree'), 'code': args.get('identifier')},
                  'scope': args.get('depth'), 'query': {'target': args.get('tree'), 'filters': []}}
        if args.get('kind') in ('parts', 'equipment'):
            intent['query']['filters'] = [{'field': 'level', 'operator': 'equals',
                                         'value': {'parts': '部件', 'equipment': '设备'}[args['kind']]}]
        view = _tool_view('iccm_query', {'intent': intent}, result)
        if args.get('depth') == 'unspecified' or args.get('kind') == 'unspecified':
            view['route'] = '下级范围尚未明确，等待澄清'
        return view
    if name == 'iccm_explain':
        return {'title': '核对已执行查询的依据', 'rows': [], 'route': '读取本对话实际查询回执'}
    if name == 'iccm_query':
        # 执行后优先展示实际回执，包括规范化后的范围和筛选条件。
        receipt = (result or {}).get('query_receipt')
        intent = args.get('intent', {})
        if receipt:
            intent = {**intent, **receipt, 'entity': receipt.get('resolved_entity') or receipt.get('requested_entity')}
        view = plan_view(intent)
        if result is not None: view['executed'] = result.get('status') == 'ok'
        if (result or {}).get('items'):
            tasks = args.get('intent', {}).get('tasks', [])
            view['tasks'] = [dict(tool_view('iccm_query', {'intent': tasks[i].get('intent', {}) if i < len(tasks) else {}}, r),
                                  question=tasks[i].get('question', '') if i < len(tasks) else '')
                             for i, r in enumerate(result['items'])]
        return view
    if name == 'iccm_find':
        tree = ((result or {}).get('lookup_binding') or {}).get('effective_domain', args.get('tree'))
        return {'title': '定位名称或编码', 'rows': [
            {'label': '查找内容', 'text': str(args.get('identifier', ''))},
            {'label': '查找范围', 'text': TREES.get(tree, str(tree or ''))}],
            'route': '先核对完整标识；无精确匹配时仅列出候选，不自动选定'}
    if name == 'iccm_page':
        return {'title': '查看后续明细', 'rows': [{'label': '页码', 'text': str(args.get('page', 1))}],
                'route': '读取本对话已有查询结果，不重新扩大查询范围'}
    return {'title': '核对项目概念与数据关系', 'rows': []}


def request_plan_view(task):
    """待执行时展示声明的父范围与主体，不把它们伪装成已定位事实。"""
    view=plan_view(task.get('set',{}));parent=task.get('parent_range')
    if isinstance(parent,dict):
        view['rows']=[r for r in view['rows'] if r['label']!='对象 / 范围']
        view['rows'].append({'label':'父对象范围（待核验）','text':'PBS现场对象 · '+str(parent.get('value',''))+'；自身及全部后代关联测点'})
    elif parent=='inherit':
        view['rows']=[r for r in view['rows'] if r['label']!='对象 / 范围']
        view['rows'].append({'label':'对象 / 范围','text':'沿用原任务范围，执行后展示实际依据'})
    subject=task.get('subject')
    if isinstance(subject,dict):view['rows'].append({'label':'所问对象（待定位）','text':str(subject.get('value',''))})
    for edit in task.get('filters',[]):
        values='；'.join(condition(c) for c in edit.get('conditions',[]))
        view['rows'].append({'label':'条件变更（待核验）','text':{'add':'追加','replace':'替换','remove':'移除原条件'}.get(edit.get('action'),'核验')+('：'+values if values else '')})
    return view
