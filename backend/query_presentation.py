"""只展示已执行查询的语义，不采用模型生成的结果声明。"""
import copy
from query_filters import describe,TARGET_LABELS


def attach_basis(result,intent):
    if intent.get('operation')=='relational':
        children=result.get('items') or [result]
        for item,task in zip(children,intent['relational_tasks']):
            q=task['spec'];root=q['root'];label=({'pbs':'现场PBS','config':'构型树','equipment_class':'设备类表','part_class':'部件类表','points':'监测表'}.get(root['tree']) if root else '全表')
            item['business_scope']=label+' · '+(root['value'] if root else '当前导入范围')+' · '+{'self':'对象自身','direct':'直接下级','all':'全部下级'}[q['depth']]+' · '+{'objects':'所有对象类型','parts':'部件','devices':'设备','points':'测点原记录'}[q['population']]
            item['query_basis']={'summary':item['business_scope'],'note':item.get('note',''),'conditions':json_description(q),'plan':copy.deepcopy(q),'resolved_entity':item.get('entity')}
        return
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


def json_description(spec):
    parts=[{'equipment_class':'设备类','part_class':'部件类'}[k]+' = '+v for k,v in spec['classes'].items()]
    parts += [describe({'target':'points' if spec['population']=='points' else 'pbs','filters':[f]}) for f in spec['filters']]
    if spec['only']:parts.append('关联检查：'+{'missing_class':'分类依据缺失','unmatched':'未匹配实际功能位置'}[spec['only']])
    return '；'.join(parts)
