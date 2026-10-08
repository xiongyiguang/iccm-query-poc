"""只展示已执行查询的语义，不采用模型生成的结果声明。"""
import copy
from query_filters import describe,TARGET_LABELS


def attach_basis(result,intent):
    if result.get('status')=='batch':
        for item,task in zip(result.get('items',[]),intent.get('tasks',[])):
            attach_basis(item,task['intent'])
        return
    if result.get('status')!='ok':return
    q=result.get('query') or intent.get('query') or {}
    entity=result.get('entity') or intent.get('entity')
    scope=intent.get('scope','direct')
    op=intent['operation'];analysis=intent.get('analysis') or {}
    summary=[]
    if entity and (q.get('target')=='points' or op in ('measurements','alarms')) and op not in ('attributes','measurement','threshold'):
        summary.append('当前PBS对象自身及全部后代关联的测点记录')
    elif entity and op in ('parts','analyze','search'):
        summary.append('全部下级' if scope=='all' else '直接下级')
    if analysis.get('group_by')=='class_code':summary.append('按部件类别去重')
    elif analysis.get('group_by')=='type':summary.append('按对象类型分组')
    elif analysis.get('group_by')=='level':summary.append('按原始层级分组')
    if q.get('equipment_class'):summary.append('仅统计指定设备类下的现场部件')
    if op=='parts':summary.append('仅统计部件')
    if not summary and q:summary.append(TARGET_LABELS.get(q.get('target'),'对象')+' · 按所述条件查询')
    if not summary:summary.append('按当前导入数据查询')
    conditions=describe(q) if q else ''
    if result.get('grain')=='pbs_object' and q.get('target')=='parts':conditions=conditions.replace('部件构型','现场部件',1)
    result['business_scope']=' · '.join(summary)
    result['query_basis']={'summary':result['business_scope'],'note':result.get('note',''),
        'conditions':conditions,
        'plan':copy.deepcopy({k:v for k,v in intent.items() if k not in ('clarification','message')}),
        'resolved_entity':copy.deepcopy(entity)}
