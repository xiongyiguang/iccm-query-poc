"""根据原话来源管理对象用途和范围，不依赖自由生成的执行计划。"""
import copy,re
from query_filters import TARGETS
DOMAIN_NAMES={'pbs':('PBS',),'config':('构型',),'equipment_class':('设备类',),'part_class':('部件类',),'points':('测点','测量点','监测点')}
PURPOSES={'data','identity','introduction'}
SCOPES={'none','explicit','confirmed','unspecified','cross_tree'}

def is_domain_draft(previous,task):
    # 缺失对象域属于草稿待补槽位，不是已执行查询的范围。
    if not task:return False
    fs=task.get('filters',[])
    return bool(previous and previous.get('pending_reason')=='domain'
        and task.get('id') in previous.get('pending_tasks',[])
        and task.get('target')=='objects' and task.get('operation')=='attributes'
        and task.get('sources',{}).get('purpose',{}).get('value')=='introduction'
        and task.get('sources',{}).get('subject_scope',{}).get('value')=='unspecified'
        and len(fs)==1 and fs[0].get('field') in ('identity','name','code')
        and fs[0].get('operator')=='equals')

def apply_scope(task,patch,source,references=None):
    from business_request import require
    old=task['sources'].get('purpose',{})
    if 'purpose' not in patch and not old:return False
    purpose=patch.get('purpose',old.get('value'));scope=patch.get('subject_scope',task['sources'].get('subject_scope',{}).get('value'))
    require(purpose in PURPOSES and scope in SCOPES,'查询用途或对象树依据无效。')
    require(('purpose' in patch)==('subject_scope' in patch),'用途与对象树依据须一起声明。')
    if 'purpose' in patch:
        task['sources']['purpose']={**copy.deepcopy(source),'value':purpose}
        task['sources']['subject_scope']={**copy.deepcopy(source),'value':scope}
    if purpose=='data':
        require(scope=='none','普通数据查询的subject_scope只能none。');return False
    require(task['operation']=='attributes','身份或介绍必须是单对象属性任务。')
    fs=[f for f in task['filters'] if f['field'] in ('identity','name','code') and f['operator']=='equals']
    require(len(fs)==1 and len(task['filters'])==1,'身份或介绍只允许一个完整对象标识，不能夹带普通列表筛选。')
    identity=fs[0];value=identity['value'];target=task['target']
    # 历史回执只能证明对象存在，不能证明当前请求指向它。
    # 只核对本任务的输出原话，排除其他任务或背景片段。
    if scope=='confirmed':
        quote=patch.get('request_quote') or source['quote']
        current={r['value'] for r in (references or {}).get('references',[])
                 if r.get('kind')=='current_literal' and r.get('value') and
                 re.search(r'(?<![A-Za-z0-9_&.#-])'+re.escape(r['value'])+r'(?![A-Za-z0-9_&.#-])',quote)}
        aliases={value}
        for subject in (references or {}).get('confirmed_subjects',[]):
            if value in (subject['code'],subject['name']):aliases.update((subject['code'],subject['name']))
        if current and not current.intersection(aliases):
            require(False,'本任务当前完整标识为'+ '、'.join(sorted(current))+'，继承对象却是'+value+
                    '。必须按本轮请求重新确定主体；新标识未指明对象树时跨树精确定位，不能用历史回执替代当前引用。')
    if scope in ('unspecified','explicit'):
        # 当前原话包含已由服务端确认对象的完整别名时，可以核验其身份；
        # 此事实独立于模型对新建或续改会话的判断。
        request_quote=patch.get('request_quote') or source['quote']
        current=[r for r in (references or {}).get('references',[]) if r.get('kind')=='current_literal'
                 and r.get('value')==value and re.search(r'(?<![A-Za-z0-9_&.#-])'+re.escape(value)+r'(?![A-Za-z0-9_&.#-])',request_quote)]
        matches=[s for s in (references or {}).get('confirmed_subjects',[]) if value in (s['code'],s['name'])]
        selected=[s for s in matches if s.get('kind')=='user_selection'];matches=selected or matches
        identities={(s['tree'],s['code']) for s in matches}
        if current and len(identities)==1:
            tree=next(iter(identities))[0]
            text=request_quote
            for token in sorted({value}|{r.get('value','') for r in (references or {}).get('references',[]) if r.get('kind')=='current_literal'},key=len,reverse=True):
                if token:text=text.replace(token,'')
            conflicting=any(re.search(re.escape(label),text,re.I) for domain,labels in DOMAIN_NAMES.items() if domain!=tree for label in labels)
            any_label=any(re.search(re.escape(label),text,re.I) for labels in DOMAIN_NAMES.values() for label in labels)
            if target in ('objects',tree) and not conflicting and (scope=='unspecified' or not any_label):
                previous_scope=copy.deepcopy(task['sources']['subject_scope']);scope='confirmed'
                task['sources']['subject_scope']={**copy.deepcopy(source),'value':'confirmed',
                    'kind':'inherited_confirmed_alias','previous':previous_scope}
    def unresolved(reason):
        task['sources']['unverified_subject_scope']={'claim':copy.deepcopy(task['sources']['subject_scope']),
            'claimed_target':target,'reason':reason}
        task['sources']['subject_scope']={**copy.deepcopy(source),'kind':'unresolved','value':'unspecified'}
        task['target']='objects'
        task['sources']['target']={**copy.deepcopy(source),'kind':'unresolved','value':'objects'}
        return True
    if 'purpose' not in patch and scope=='explicit':
        # 复用已核验主体，不代表当前原话重新声明了对象树；
        # 只接受完整核验别名，不接受前缀。
        domain=TARGETS.get(target,(None,None))[0]
        matches=[s for s in (references or {}).get('confirmed_subjects',[])
                 if value in (s['code'],s['name']) and s['tree']==domain]
        if matches:
            previous_scope=copy.deepcopy(task['sources']['subject_scope'])
            scope='confirmed'
            task['sources']['subject_scope']={**copy.deepcopy(source),'value':'confirmed',
                'kind':'inherited_confirmed_subject','previous':previous_scope}
    if scope=='explicit':
        domain=TARGETS.get(target,(None,None))[0]
        if target=='points':domain='points'
        # 对象树标签是封闭业务词汇，不是自然语言问句模板；
        # 标识内部出现标签文字不能作为对象域依据。
        text=source['quote']
        for token in sorted({value}|{r.get('value','') for r in (references or {}).get('references',[]) if r.get('kind')=='current_literal'},key=len,reverse=True):
            if token:text=text.replace(token,'')
        require(domain in DOMAIN_NAMES,'显式对象树目标无效。')
        if not any(re.search(re.escape(n),text,re.I) for n in DOMAIN_NAMES[domain]):
            if purpose=='introduction':return unresolved('显式对象树缺少当前任务原话依据。')
            require(False,'显式对象树缺少本任务原话依据，数据命中不能当作用户选树。')
        return False
    if scope=='confirmed':
        matches=[s for s in (references or {}).get('confirmed_subjects',[]) if value in (s['code'],s['name'])]
        selected=[s for s in matches if s.get('kind')=='user_selection'];matches=selected or matches
        trees={s['tree'] for s in matches}
        if len(trees)!=1:
            require(target in TARGETS or target=='points','对象树目标无效。')
            if purpose=='introduction':return unresolved('没有与当前完整标识一致的已确认对象树。')
            require(False,'没有与本任务完整标识一致的已确认对象树，不能借用旧对象。')
        tree=next(iter(trees));task['target']=tree
        task['sources']['target']={'kind':'confirmed_subject','value':tree,'subjects':copy.deepcopy(matches),'requested_by':copy.deepcopy(source)}
        return False
    require(scope in ('unspecified','cross_tree'),'身份/介绍缺少有效的对象树依据。')
    task['target']='objects';task['sources']['target']={**copy.deepcopy(source),'kind':scope,'value':'objects'}
    return purpose=='introduction' and scope=='unspecified'


def reviewable_domain_draft(candidate,changed,draft,draft_ids,store):
    """用户可以确认可见的对象域或属性投影，不能确认未知主体。

两种解释必须引用同一个完整标识。此处不会按数据库命中情况
自动选择对象域，也不会自动执行候选方案。"""
    from business_request import compile_task,RequestInvalid
    from request_checklist import canonical_tasks
    from request_gateway import validate_categories
    if not draft or draft.get('pending_reason')!='domain' or changed!=draft_ids:return False
    if set(draft.get('pending_tasks',[]))-set(changed):return False
    if {t['id'] for t in candidate['tasks']}!={t['id'] for t in draft['tasks']}:return False
    normalized=copy.deepcopy(draft);filled=False
    try:
        validate_categories(candidate,changed,store)
        for task in normalized['tasks']:
            other=next(t for t in candidate['tasks'] if t['id']==task['id'])
            if task['id'] not in draft.get('pending_tasks',[]):continue
            if not is_domain_draft(draft,task) or task['sources'].get('unverified_subject_scope'):return False
            if other['operation']!='attributes' or other['target'] not in {*DOMAIN_NAMES}:return False
            if len(other['filters'])!=1 or not other['properties']:return False
            if task['unit']!={'state':'none','value':''} or other['unit']!=task['unit']:return False
            if task['scope']!=other['scope']:return False
            root=task['filters'][0];proposed=other['filters'][0]
            if proposed['operator']!='equals' or proposed['field'] not in ('identity','name','code'):return False
            if root['value']!=proposed['value']:return False
            if root['field']!=proposed['field'] and 'identity' not in (root['field'],proposed['field']):return False
            compile_task(other)
            # 仅这些可见业务选项允许不同；其余任务和约束必须逐一比较，
            # 包括本轮尚不执行的未来任务。
            task['target']=other['target'];task['properties']=copy.deepcopy(other['properties'])
            task['filters']=copy.deepcopy(other['filters'])
            task['sources']['purpose']=copy.deepcopy(other['sources'].get('purpose',{}))
            task['sources']['subject_scope']=copy.deepcopy(other['sources'].get('subject_scope',{}))
            filled=True
        ids=[t['id'] for t in candidate['tasks']]
        return filled and canonical_tasks(candidate,ids,store)==canonical_tasks(normalized,ids,store)
    except (RequestInvalid,ValueError,TypeError,KeyError):return False


def explicit_domain(question,target,references=None):
    """仅使用字面名称和编码外部的封闭对象域词汇，不按数据命中猜测。"""
    text=question
    for value in sorted({r.get('value','') for r in (references or {}).get('references',[]) if r.get('kind')=='current_literal'},key=len,reverse=True):
        if value:text=text.replace(value,'')
    domains={domain for domain,labels in DOMAIN_NAMES.items() if any(re.search(re.escape(label),text,re.I) for label in labels)}
    return domains=={target}
