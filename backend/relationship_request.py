"""把类型化的后代对象集合编译到现有图关系查询。"""
import copy

POPULATIONS={'all_objects':'所有下级对象','parts':'仅下级部件','unspecified':'待明确对象类型'}

def compile_relationship(task,allow_ambiguous=False):
    from business_request import require,RequestAmbiguous
    from parts_request import compile_parts
    require(task['target']=='config','当前层级关系根对象必须属于构型树。')
    require(task.get('population') in POPULATIONS,'下级对象集合无效。')
    require(task['scope'] in ('direct','all','unspecified') and task['sources'].get('scope',{}).get('kind')!='default',
            '下级深度须明确声明，不能使用列表查询的默认范围。')
    # 即使某个槽位未解决，也必须校验根对象、投影和单位。
    draft=copy.deepcopy(task);draft.pop('population');draft['operation']='parts'
    goal=draft.pop('result_goal',None)
    if goal is not None:
        from result_goal import validate_goal
        validate_goal(goal,'parts','config')
        require(goal['kind'] in ('records','count'),'关系任务仅支持原生下级列表与计数，不能省略其他结果目标。')
    draft['scope']='direct' if task['scope']=='unspecified' else task['scope']
    plan=compile_parts(draft)
    if task['population']=='unspecified' or task['scope']=='unspecified':
        message=clarification_question(task)
        if not allow_ambiguous:raise RequestAmbiguous(message)
        return {'operation':'clarify','entity':None,'scope':'direct','clarification':message}
    if task['population']=='all_objects':
        plan.update(operation='search',query={'target':'config','filters':[]})
    if goal is not None:plan['result_goal']=copy.deepcopy(goal)
    return plan

def population_of_plan(plan):
    if plan['operation']=='parts' and not plan.get('query'):return 'parts'
    if plan['operation']=='search' and plan.get('query')=={'target':'config','filters':[]}:return 'all_objects'
    raise ValueError('层级关系确认不能增加其他筛选或修改查询种类。')

def edit_task(original,entity,scope,population,source,next_filter_id):
    from business_request import require
    require(isinstance(entity,dict) and entity.get('tree')=='config' and len(entity)==2,'层级关系只允许一个构型根对象。')
    keys=set(entity)-{'tree'}
    require(len(keys)==1 and keys<={'identity','code','name'},'根对象标识字段无效。')
    field=next(iter(keys));task=copy.deepcopy(original)
    f={'field':field,'operator':'equals','value':entity[field]};old=task['filters'][0]
    if any(old[k]!=v for k,v in f.items()):
        task['filters']=[{**f,'id':f'f{next_filter_id}','source':copy.deepcopy(source)}];next_filter_id+=1
    for key,value in [('scope',scope),('population',population)]:
        if task[key]!=value:task[key]=value;task['sources'][key]=copy.deepcopy(source)
    compile_relationship(task)
    return task,next_filter_id

def review_values(plan):
    return {'entity':copy.deepcopy(plan['entity']),'scope':plan['scope'],
            'query':{'target':'parts' if population_of_plan(plan)=='parts' else 'config','filters':[]}}

def reviewed_plan(task,values):
    from business_request import require
    require(set(values)=={'entity','scope','query'},'层级关系确认字段不完整。')
    q=values['query']
    require(isinstance(q,dict) and set(q)=={'target','filters'} and q['filters']==[] and q['target'] in ('config','parts'),
            '请通过对象类型选择所有对象或仅部件，不能附加隐藏条件。')
    updated,_=edit_task(task,values['entity'],values['scope'],'parts' if q['target']=='parts' else 'all_objects',{'kind':'review_validation'},1)
    return compile_relationship(updated)

def reviewable_draft(candidate,changed,draft,draft_ids,store):
    """确认只能补齐尚未确定、允许编辑的关系槽位。

不同根对象、额外任务或条件、已确定值不属于此例外。
单位和对象域前置条件仍须通过原有严格校验。"""
    from business_request import compile_task,RequestInvalid
    from request_checklist import canonical_tasks
    if not draft or draft.get('pending_reason')!='relationship' or changed!=draft_ids:return False
    if {t['id'] for t in candidate['tasks']}!={t['id'] for t in draft['tasks']}:return False
    normalized=copy.deepcopy(draft);filled=False
    try:
        for task in normalized['tasks']:
            other=next(t for t in candidate['tasks'] if t['id']==task['id'])
            if task['id'] not in changed:continue
            compile_task(other)
            if task['operation']!='descendants' or other['operation']!='descendants':continue
            for key in ('scope','population'):
                if task[key]=='unspecified':task[key]=other[key];filled=True
        ids=[t['id'] for t in candidate['tasks']]
        return filled and canonical_tasks(candidate,ids,store)==canonical_tasks(normalized,ids,store)
    except (RequestInvalid,ValueError,TypeError,KeyError):return False


def clarification_question(task):
    if task['scope']=='unspecified':return '您要统计直接下级，还是全部下级？'
    return '您要统计所有下级对象，还是仅统计部件？'
