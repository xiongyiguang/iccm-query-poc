"""按原始依据投影属性，不对用户自然语言分类。"""
import json
from decimal import Decimal, InvalidOperation

NUMERIC_PROPERTIES={'value','rate','prediction'}

def display_value(prop,value):
    """无损展示数值属性的十进制值，保持原始值不变。"""
    if prop not in NUMERIC_PROPERTIES or not isinstance(value,str) or len(value)>128 or 'e' not in value.lower():return value
    try:
        number=Decimal(value)
        if not number.is_finite() or abs(number.as_tuple().exponent)>200:return value
        return format(number,'f')
    except (InvalidOperation,ValueError):return value

# 规划语义、输出标签和原始字段绑定共用一份属性目录。
CATALOG = {
 'name': {'label':'对象名称','fields':{'pbs':'对象描述中文','config':'对象描述中文','equipment_class':'描述','part_class':'对象描述中文','points':'测量点名称'}},
 'code': {'label':'对象编码','fields':{'pbs':'对象代码','config':'对象代码','equipment_class':'对象编码','part_class':'对象编码','points':'测量点编码'}},
 'type': {'label':'对象类型','fields':{'pbs':'对象层级','config':'对象层级描述'},'meaning':'对象在结构中的类型，不是设备类或所测物理量；分类字典只有层级数字时不能把数字解释成设备类型。'},
 'level': {'label':'层级','fields':{'pbs':'对象层级','config':'对象层级','equipment_class':'层级','part_class':'对象层级'}},
 'parent': {'label':'父对象编码','fields':{'pbs':'父对象代码','config':'父对象代码','equipment_class':'父对象编码','part_class':'父对象编码'}},
 'class_code': {'label':'所属部件类编码','fields':{'config':'所属部件类代码'}},
 'major_equipment': {'label':'所属重大设备','fields':{'pbs':'所属重大设备'}},
 'leaf': {'label':'是否叶子节点','fields':{'config':'是否叶子节点，否0， 是1'}},
 'value': {'label':'测量值','fields':{'points':'测量值'}},
 'unit': {'label':'单位','fields':{'points':'单位'}},
 'source': {'label':'源系统','fields':{'points':'源系统'}},
 'time': {'label':'测量时间','fields':{'points':'测量时间'}},
 'status': {'label':'报警状态','fields':{'points':'状态'}},
 'switch': {'label':'开关','fields':{'points':'开关'}},
 'alarm_reason': {'label':'原始报警原因','fields':{'points':'报警原因'},'meaning':'原系统文本，不等于设备故障根因。'},
 'rate': {'label':'变化速率','fields':{'points':'变化速率'}},
 'prediction': {'label':'预测值','fields':{'points':'预测值'}},
 'physical_quantity': {'label':'所测物理量','fields':{},'meaning':'现有数据无可靠物理量释义，不能从脱敏名称、代码或单位猜测温度/振动/位移。'},
}

from typed_fields import THRESHOLDS
CATALOG.update({key:{'label':field,'fields':{'points':field}} for key,field in THRESHOLDS.items()})

def planner_catalog():
    return json.dumps(CATALOG,ensure_ascii=False)

def validate_properties(intent):
    props=intent.get('properties')
    if intent.get('operation')!='attributes':
        if props is not None: raise ValueError('非属性操作不能丢弃所问属性。')
        return
    if props==['*']:return
    if not isinstance(props,list) or not 1<=len(props)<=len(CATALOG) or any(not isinstance(p,str) or p not in CATALOG for p in props) or len(set(props))!=len(props):
        raise ValueError('所问属性必须来自属性目录且不重复；全部属性请使用完整投影。')

def check_coverage(props, facts):
    if set(props)!={f['property'] for f in facts}:
        raise ValueError('回答未覆盖全部所问属性；未展示不完整答案。')
    for f in facts:
        if f['status']=='known':
            if not f['evidence'] or any(e['fields'].get(f['field'])!=f['value'] for e in f['evidence']):
                raise ValueError('属性答案与原始字段不一致。')
        elif f['status'] not in ('missing','unsupported'):
            raise ValueError('未知属性证据状态。')
    return {'complete':True,'requested':props,'answered':list(dict.fromkeys(f['property'] for f in facts))}

def execute_attributes(store,intent):
    from data import QueryError
    try: validate_properties(intent)
    except ValueError as e: raise QueryError(str(e)) from None
    props=intent['properties']; query=intent.get('query'); subject=intent.get('entity')
    if query is not None:
        found=store.filtered({**intent,'operation':'search'})
        keys={(r['tree'],r['code']) for r in found['records']}
        if len(keys)!=1:
            found.update(status='clarify',entity=None,requested_properties=props)
            found['answer']='未找到符合条件的对象。' if not keys else f'找到 {len(keys)} 个不同对象，请明确要查询哪一个的属性。'
            found['lookup_query']=found.pop('query')
            return found
        tree,code=next(iter(keys)); subject={'tree':tree,'code':code}
        target='points' if query['target']=='points' else tree
        # 保留来源条件，只去除已确定的身份候选。
        lookup={'target':target,'filters':[f for f in query['filters'] if f['field'] not in ('identity','name','code')]+[{'field':'code','operator':'equals','value':code}]}
    else:
        if not subject: raise QueryError('请明确要查询属性的对象。')
        tree,code=subject['tree'],subject['code'];target=tree;lookup=None
    objects=store.rows('SELECT * FROM objects WHERE tree=? AND code=?',(tree,code))
    points=[]
    if tree=='pbs':
        if target=='points':
            from query_filters import predicates
            clauses,args=predicates(lookup)
            points=store.rows('SELECT r.* FROM points r WHERE '+' AND '.join(clauses)+' ORDER BY r.line',args)
        else: points=store.rows('SELECT * FROM points WHERE code=? ORDER BY line',(code,))
    if not objects and not points: raise QueryError('未找到指定对象。')
    if props==['*']:
        origins={target,tree}|({'points'} if points else set())
        props=[key for key,spec in CATALOG.items() if origins.intersection(spec['fields']) or not spec['fields']]
    base=points[0] if target=='points' else (objects or points)[0]
    facts=[]
    for prop in props:
        spec=CATALOG[prop]
        origin=target if target in spec['fields'] else ('pbs' if target=='points' and 'pbs' in spec['fields'] else ('points' if tree=='pbs' and 'points' in spec['fields'] else target))
        field=spec['fields'].get(origin)
        rows=points if origin=='points' else objects
        if not field:
            facts.append(dict(property=prop,label=spec['label'],status='unsupported',value=None,field=None,evidence=[],explanation=spec.get('meaning','该对象的数据没有提供此属性定义。')))
            continue
        if not rows:
            facts.append(dict(property=prop,label=spec['label'],status='missing',value=None,field=field,evidence=[],explanation='没有匹配的来源记录。'))
            continue
        for row in rows:
            ref=store.ref(row); value=ref['fields'].get(field)
            facts.append(dict(property=prop,label=spec['label'],status='known' if value not in (None,'') else 'missing',value=value,field=field,evidence=[ref],source=row.get('system'),time=row.get('time')))
    try: coverage=check_coverage(props,facts)
    except ValueError as e: raise QueryError(str(e)) from None
    sentences=[]
    for f in facts:
        if f['status']=='known':f['display_value']=display_value(f['property'],f['value'])
        suffix=f"（{f['source']}，{f.get('time') or '时间未提供'}）" if f.get('source') else ''
        value=f['display_value'] if f['status']=='known' else ('未提供' if f['status']=='missing' else '无法可靠确定')
        sentences.append(f"{f['label']}：{value}{suffix}")
    answer=f"{base['name']}（{code}）："+'；'.join(sentences)+'。'
    if any(f['property']=='type' and f['value']=='时序测点' for f in facts):answer+='时序测点用于记录随时间变化的测量数据。'
    if any(f['property']=='physical_quantity' for f in facts):answer+='现有数据没有可靠的物理量释义，不能仅凭编码推断。'
    evidence=list({(e['file'],e['line']):e for f in facts for e in f['evidence']}.values())
    for row in objects:
        ref=store.ref(row)
        if not any((e['file'],e['line'])==(ref['file'],ref['line']) for e in evidence):evidence.append(ref)
    result=dict(answer=answer,status='ok',entity=subject,scope='direct',records=[],metrics=[],path=[dict(**subject,name=base['name'])],evidence=evidence,note='本次导入快照；按所问属性回答，缺失值不补零。',attributes=facts,requested_properties=props,coverage=coverage)
    if lookup:result['lookup_query']=lookup
    return result
