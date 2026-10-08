"""描述已校验的候选业务请求，不解释用户自然语言。"""
from query_filters import describe,TARGET_LABELS
from attributes import CATALOG
from business_request import NOTE_OPERATIONS

def task_summary(task,number):
    op=task['operation']
    prefix=f'任务{number}：'
    if op in NOTE_OPERATIONS:
        from data_context import STATIC_TOPICS
        return prefix+('说明能力边界' if op=='unsupported' else '说明：'+'、'.join(str(STATIC_TOPICS[k]) for k in task['topics']))
    if op in ('parts','descendants'):
        f=task['filters'][0]
        return prefix+'构型根对象'+{'identity':'名称或编码','name':'名称','code':'编码'}[f['field']]+'「'+f['value']+'」；'+({'direct':'直接下级','all':'全部后代','unspecified':'下级深度待明确；'}[task['scope']]+{'parts':'部件','all_objects':'对象（不限类型）','unspecified':'对象类型待明确'}[task.get('population','parts')])+'列表及数量'
    text=describe({'target':task['target'],'filters':task['filters']})
    if (task['target']=='objects' and task.get('sources',{}).get('purpose',{}).get('value')=='introduction'
            and task.get('sources',{}).get('subject_scope',{}).get('value')=='unspecified'):
        text='对象域待明确；'+text
    if task['properties']:
        text+='；返回：'+'、'.join('全部属性' if p=='*' else CATALOG[p]['label'] for p in task['properties'])
    else:text+='；返回记录列表'
    return prefix+text

def describe_disagreement(candidate,independent,candidate_mode,independent_mode,same_future):
    return {'title':'查询理解有分歧，请核对后再查询',
            'message':'下面显示的是待执行条件。另一种理解列在这里供对照；可修改下面的条件，确认后按修改结果查询。',
            'current':[task_summary(t,i) for i,t in enumerate(candidate,1)],
            'alternative':[task_summary(t,i) for i,t in enumerate(independent,1)],
            'state_warning':('当前按'+('继续修改已有任务' if candidate_mode=='update' else '开始新任务')+
                             '处理；另一种理解为'+('继续修改已有任务' if independent_mode=='update' else '开始新任务')+
                             '，会影响后续对话保留的任务。') if candidate_mode!=independent_mode and not same_future else ''}


def business_question(candidate, independent, candidate_mode, independent_mode, comparison=None):
    """每次只询问一个存在分歧的业务条件，不暴露可编辑查询 DSL。"""
    scopes={'direct':'直接下级','all':'全部下级','unspecified':'下级范围'}
    populations={'parts':'仅部件','all_objects':'所有对象','unspecified':'对象范围'}
    for index,(a,b) in enumerate(zip(candidate,independent)):
        same_filters=bool(comparison and comparison["candidate"][index].get("filters")==comparison["independent"][index].get("filters"))
        if a.get('target')!=b.get('target'):
            names=[TARGET_LABELS.get(t.get('target'), '对象') for t in (a,b)]
            return f'您要查询{names[0]}，还是{names[1]}？'
        if a.get('scope')!=b.get('scope'):
            return '您要查询直接下级，还是全部下级？'
        if a.get('population')!=b.get('population'):
            return '您要统计所有下级对象，还是仅统计部件？'
        af=a.get('filters',[]);bf=b.get('filters',[])
        identities=lambda fs:[f['value'] for f in fs if f['field'] in ('identity','code','name') and f['operator']=='equals']
        av,bv=identities(af),identities(bf)
        if not same_filters and av!=bv and len(av)==len(bv)==1:
            return f'本次要查询「{av[0]}」，还是「{bv[0]}」？'
        if a.get('unit')!=b.get('unit'):
            return '这个数值条件使用什么单位？'
        if not same_filters and af!=bf:
            # 去除来源和编号元数据，它们不是不同的业务条件。
            semantic=lambda fs:[{k:f[k] for k in ('field','operator','value')} for f in fs]
            if semantic(af)!=semantic(bf):
                left=describe({'target':a['target'],'filters':semantic(af)})
                right=describe({'target':b['target'],'filters':semantic(bf)})
                return f'您需要哪种查询范围：「{left}」还是「{right}」？'
        if a.get('properties')!=b.get('properties'):
            from typed_fields import THRESHOLDS
            labels=lambda t:'报警阈值' if set(t.get('properties',[]))==set(THRESHOLDS) else '、'.join('全部属性' if p=='*' else CATALOG[p]['label'] for p in t.get('properties',[])) or '对象列表'
            return f'您要查看{labels(a)}，还是{labels(b)}？'
    if candidate_mode!=independent_mode:return '这是继续修改刚才的问题，还是开始一个新查询？'
    return '本次最先需要查询哪一项业务结果？'
