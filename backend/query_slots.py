"""有界公共查询槽位：未决草稿与已执行对象分开，补答只填写缺失槽位。"""
import copy
import re
from request_turn import control_text, depth_control

LABELS = {'config': '构型树', 'pbs': 'PBS树', 'equipment_class': '设备类表', 'part_class': '部件类表'}
HINTS = {'config': ('构型树', '构型表', '构型'), 'pbs': ('PBS树', 'PBS表', 'PBS', '现场'),
         'equipment_class': ('设备类表', '设备类字典', '设备类'), 'part_class': ('部件类表', '部件类字典', '部件类')}
SLOT_LABELS = {'root': ('根对象', '查询对象', '主体', '对象', '根', '名称', '编码'),
               'tree': ('对象树', '所属树', '所属表'), 'depth': ('层级', '深度', '范围')}


def references(question, store):
    from request_checklist import literal_references
    return [x for x in literal_references(question, store) if x.get('field') in ('code', 'name')]


def domains(question):
    return {t for t, words in HINTS.items() if any(w.casefold() in question.casefold() for w in words)}


def clarify(frame, message):
    return {'plan': {'operation': 'clarify', 'entity': None, 'scope': 'direct', 'clarification': message},
            'pending': frame, 'resumed': False}


def frame_from_domain(question, store):
    refs = references(question, store); values = {x['value'] for x in refs}
    if len(values) != 1: return None
    value = next(iter(values)); candidates = sorted({x['domain'] for x in refs if x['value'] == value})
    return {'version': store.version, 'question': question, 'kind': 'relation', 'population': 'objects',
            'root': {'field': 'identity', 'value': value}, 'domains': candidates, 'tree': None, 'depth': 'all'}


def slot_answer(question, refs):
    # 完整覆盖本轮文本才作为纯槽位补答；新目标、比较、筛选等不能隐式续旧任务。
    text = question
    for ref in sorted(refs, key=lambda x: len(x['value']), reverse=True):
        text = text.replace(ref['value'], '')
    words = [w for values in HINTS.values() for w in values]
    words += [w for values in SLOT_LABELS.values() for w in values]
    words += ['直接下级', '全部下级', '所有下级', '全部后代', '所有后代', '全层级', '下一层', '直属', '直接',
              '里的', '中的', '里面', '我指', '我说', '是指', '指的是', '来自', '设为', '改为', '换成', '是', '那个', '这个', '的', '里', '中']
    text = re.sub('|'.join(map(re.escape, sorted(set(words), key=len, reverse=True))), '', text, flags=re.I)
    return not text.strip(' \t\n，,。；;！？!?：:')


def resume(question, context, store):
    old = context.get('pending_public_query')
    if not old or old.get('version') != store.version: return None
    refs = references(question, store)
    if not slot_answer(question, refs): return None
    frame = copy.deepcopy(old); values = {x['value'] for x in refs}
    if len(values) > 1: return None
    if values:
        value = next(iter(values)); frame['root'] = {'field': 'identity', 'value': value}
        frame['domains'] = sorted({x['domain'] for x in refs if x['value'] == value})
    current = domains(question)
    if len(current) == 1: frame['tree'] = next(iter(current))
    elif len(current) > 1: return None
    depth = depth_control(question)
    if depth: frame['depth'] = depth
    root = frame.get('root')
    if not root: return clarify(frame, '请指定要查询下级的根对象，已保留部件及层级范围；尚未执行。')
    possible = frame.get('domains', [])
    tree = frame.get('tree') or (possible[0] if len(possible) == 1 else None)
    if tree is None:
        return clarify(frame, '请确认根对象来自'+'、'.join(LABELS.get(t, t) for t in possible)+'；原请求和范围已保留，尚未执行。')
    if tree not in possible: return clarify(frame, '该对象在所选对象树中没有原记录，请更正对象或对象树；尚未执行。')
    from relational_query import Graph, canonical, validate_plan
    actual = {'tree': tree, **root}
    try: node = Graph(store).resolve(actual)
    except ValueError: return None
    if isinstance(node, list): return None
    if frame['kind'] == 'collection' and frame.get('depth') not in ('direct', 'all'):
        return clarify(frame, '请确认直接下级还是全部下级；根对象和部件目标已保留，尚未执行。')
    spec = canonical({'root': {'tree': tree, 'field': 'code', 'value': node['code']},
                      'kind': frame['kind'], 'population': frame['population'], 'depth': frame['depth']})
    plan = validate_plan({'operation': 'relational', 'entity': None, 'scope': 'direct', 'clarification': '',
                          'relational_tasks': [{'id': 1, 'spec': spec}]})
    return {'plan': plan, 'pending': None, 'resumed': True}


def missing_root(question, context, store):
    if context.get('entity') or context.get('pending_business_request') or context.get('pending_public_query'): return None
    # 全局分类集合、分支和真实历史也是已执行所有者；无唯一根并不等于无上下文。
    if ((context.get('relational_state') or {}).get('tasks') or context.get('relational_history')
            or context.get('branches') or (context.get('business_request') or {}).get('tasks')): return None
    text = control_text(question); depth = depth_control(question)
    if not depth or '部件' not in text: return None
    # 输出集合和范围已明确，缺根就是待完成草稿；不要求复述某种查询动词。
    if re.search(r'什么是|定义|意思|含义|解释|如何|怎么|步骤|原理', text): return None
    if re.search(r'比较|分别|同时|排序|筛选|过滤|数量大于|不查|不执行|不要执行', text): return None
    if references(question, store): return None
    # 未命中的标识应走原对象定位，不能被当作完全没有指定对象。
    if re.search(r'[A-Za-z][A-Za-z0-9_#&.\-]{2,}', text.replace('PBS', '')): return None
    target = domains(question)
    frame = {'version': store.version, 'question': question, 'kind': 'collection', 'population': 'parts',
             'root': None, 'domains': [], 'tree': next(iter(target)) if len(target) == 1 else None, 'depth': depth}
    return clarify(frame, '请指定要查看部件的根对象及所在对象树；已保留'+('直接下级' if depth == 'direct' else '全部下级')+'范围，尚未执行查询。')
