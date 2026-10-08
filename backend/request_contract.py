"""用独立语义槽位核对可执行计划。"""
from typed_fields import THRESHOLDS,NUMERIC_OPS,NUMERIC_FIELDS,UNIT_ALIASES,decimal_value,canonical_unit
import copy

# 字面标签只核验已经提议的对象域，不据此选择操作。
DOMAIN_LABELS={'pbs':('PBS','pbs'),'config':('构型',),'equipment_class':('设备类',),'part_class':('部件类',)}

def validate_route(route,strict=False):
    allowed={'needs_history','identifier_field','resolved_question','domain','thresholds','comparisons','unit','reference','projection','scope','properties','context_mode','request_kind','business_request'}
    if not isinstance(route,dict) or set(route)-allowed or not {'needs_history','identifier_field'}<=set(route):raise ValueError('route')
    if type(route['needs_history']) is not bool or route['identifier_field'] not in (None,'name','code','identity'):raise ValueError('route')
    if route.get('domain') not in (None,'pbs','config','equipment_class','part_class','points'):raise ValueError('domain')
    if route.get('thresholds')==[]:route['thresholds']=None
    if route.get('comparisons') is None:route['comparisons']=[]
    thresholds=route.get('thresholds')
    if thresholds is not None and (not isinstance(thresholds,list) or not thresholds or len(thresholds)>18 or any(x not in THRESHOLDS for x in thresholds)):raise ValueError('thresholds')
    comparisons=route.get('comparisons',[])
    if not isinstance(comparisons,list) or len(comparisons)>8:raise ValueError('comparisons')
    for f in comparisons:
        if not isinstance(f,dict) or set(f)!={'field','operator','value'} or f['field'] not in NUMERIC_FIELDS or f['operator'] not in NUMERIC_OPS or decimal_value(f['value']) is None:raise ValueError('comparison')
    if strict and not {'unit','reference','projection','scope'}<=set(route):raise ValueError('missing semantic slots')
    if 'unit' in route:
        u=route['unit']
        if not isinstance(u,dict) or set(u)!={'state','value'} or u['state'] not in ('none','ambiguous','specified') or not isinstance(u['value'],str) or len(u['value'])>50:raise ValueError('unit')
        if (u['state']=='specified')!=bool(u['value']):raise ValueError('unit value')
    ref=route.get('reference')
    if ref is not None and (not isinstance(ref,str) or not 0<len(ref)<=300):raise ValueError('reference')
    from attributes import CATALOG
    if 'properties' in route:
        props=route['properties']
        if not isinstance(props,list) or len(props)>len(CATALOG) or any(not isinstance(x,str) or x not in CATALOG for x in props) or len(set(props))!=len(props):raise ValueError('properties')
    if route.get('request_kind','other') not in ('introduction','identity','other'):raise ValueError('request_kind')
    if route.get('context_mode','new') not in ('new','followup','replace_subject'):raise ValueError('context_mode')
    if route.get('context_mode')=='replace_subject' and (not route['needs_history'] or not route.get('reference')):raise ValueError('replace_subject')
    if route.get('projection') not in (None,'specified','all'):raise ValueError('projection')
    if route.get('scope') not in (None,'direct','all'):raise ValueError('scope')
    return route

def scope_context(route,context,selection):
    """精确身份决定是否继承，不能靠文字相似度选择对象树。"""
    d=copy.deepcopy(route);ref=d.get('reference');current=selection or context.get('entity') or {}
    if (d['needs_history'] and context.get('pending_reference') and d.get('identifier_field') is None
            and ref in DOMAIN_LABELS.get(d.get('domain'),())):
        # 类型明确的对象域补答只填域槽位，不改变对象身份。
        ref=context['pending_reference'];d['reference']=ref;d['resolved_question']=None
    if d.get('context_mode')=='replace_subject':
        # 保留任务投影，不继承旧主体、定位条件、候选或父对象。
        kept={k:copy.deepcopy(context[k]) for k in ('requested_properties','answered_properties','operation','scope') if k in context}
        if not d.get('properties') and kept.get('requested_properties'):d['properties']=copy.deepcopy(kept['requested_properties'])
        d['resolved_question']=None
        return d,kept,None
    if ref and ref in (current.get('code'),current.get('name')) and (not d.get('domain') or d['domain']==current.get('tree')):
        d['needs_history']=True;d['domain']=d.get('domain') or current.get('tree')
    if ref and d.get('context_mode')=='followup' and d['needs_history'] and context.get('operation')=='search' and context.get('query'):
        kept={'operation':'search','scope':context.get('scope','direct'),'query':copy.deepcopy(context['query'])}
        kept['query']['filters']=[f for f in kept['query']['filters'] if f['field'] not in ('name','code','identity')]
        d['resolved_question']=None
        return d,kept,None
    known={current.get('code'),current.get('name'),context.get('pending_reference')}
    for f in (context.get('lookup_query') or {}).get('filters',[]):
        if f['field'] in ('name','code','identity') and f['operator']=='equals':known.add(f['value'])
    pending=context.get('pending_request') or {}
    known.update((pending.get('entity') or {}).values())
    for f in (pending.get('query') or {}).get('filters',[]):
        if f['field'] in ('name','code','identity') and f['operator']=='equals':known.add(f['value'])
    for candidate in (context.get('outcome') or {}).get('candidates',[]):
        known.update((candidate.get('code'),candidate.get('name')))
    continuing=bool(context.get('pending_question') and d['needs_history'] and (not ref or ref in known))
    if ref and not continuing and ref not in known:
        d['needs_history']=False;d['resolved_question']=None
    if d.get('resolved_question') and not continuing:d['resolved_question']=None
    if not d['needs_history']:return d,{},None
    return d,context,selection


def ground_unit(route,question,context):
    """规范化单位必须有原话来源，不能由模型猜测。"""
    d=copy.deepcopy(route);unit=d.get('unit') or {}
    if unit.get('state')!='specified':return d
    canonical=canonical_unit(unit['value'])
    aliases={unit['value'],canonical}|{a for a,v in UNIT_ALIASES.items() if v==canonical}
    sources=[question]
    if d.get('needs_history'):
        sources.append(context.get('pending_question',''))
        sources.extend(x.get('question','') for x in context.get('dialogue',[]))
    if not any(alias in source for alias in aliases for source in sources):
        d['unit']={'state':'ambiguous','value':''}
    return d


def ground_domain(route,question):
    d=copy.deepcopy(route);domain=d.get('domain')
    if d.get('reference') and not d.get('needs_history') and domain in DOMAIN_LABELS:
        if not any(label in question for label in DOMAIN_LABELS[domain]):d['domain']=None
    return d


def reconcile_reference(route,candidate,question,context):
    """当前原话中的字面引用优先于过时的路由引用。

核对两份结构化提取及其来源；不按编码形状推断对象，
不截断名称，不替用户选择对象树。"""
    d=copy.deepcopy(route)
    if not isinstance(candidate,dict) or candidate.get('operation') not in ('attributes','object','equipment','equipment_class','part_class','parent'):return d
    refs=[f for f in (candidate.get('query') or {}).get('filters',[]) if f.get('field') in ('identity','name','code') and f.get('operator')=='equals']
    entity=candidate.get('entity') or {}
    if not refs and entity:
        refs=[{'field':d.get('identifier_field') or 'identity','operator':'equals','value':entity.get('name',entity.get('code'))}]
    old=d.get('reference')
    if len(refs)!=1 or not old or old in question:return d
    ref=refs[0].get('value')
    if not isinstance(ref,str) or not ref or ref==old or ref not in question:return d
    # 域标签只核验已提出的对象域，不负责查询路由。
    labels={**DOMAIN_LABELS,'points':('测点','测量点','监测点')}
    domain=d.get('domain')
    if domain and not any(label in question for label in labels[domain]):d['domain']=None
    d.update(reference=ref,identifier_field=refs[0]['field'],needs_history=False,resolved_question=None)
    return d

def bind_categorical_values(store,plan,question):
    """只恢复当前问题中完整出现且唯一的原始数据值。

不按尾号猜别名，不扩大包含或前缀筛选，不让旧轮覆盖本轮。
未知但明确的值仍保持精确查询。"""
    import re
    from query_filters import POINT_FIELDS
    p=copy.deepcopy(plan)
    children=[x['intent'] for x in p['tasks']] if p.get('operation')=='batch' else [p]
    for child in children:
        query=child.get('query') or {}
        if query.get('target')!='points':continue
        for f in query.get('filters',[]):
            if f['field'] not in ('source','status','switch') or f['operator']!='equals' or not f['value']:continue
            column=POINT_FIELDS[f['field']]
            values={r['value'] for r in store.rows(f'SELECT DISTINCT {column} AS value FROM points') if r['value']}
            if f['value'] in values:continue
            candidates=[v for v in values if f['value'] in v and re.search(r'(?<![A-Za-z0-9_])'+re.escape(v)+r'(?![A-Za-z0-9_])',question)]
            if len(candidates)>1:
                return {'operation':'clarify','entity':None,'scope':'direct','clarification':'原话包含多个可能的完整字段值，请明确要筛选哪一个；未按截断值执行。'}
            if len(candidates)==1:f['value']=candidates[0]
    return p


def complete_contract(candidate,route,context=None,selection=None):
    """编译明确语义槽位，同时保留规划器的操作和筛选条件。"""
    p=copy.deepcopy(candidate)
    if not isinstance(p,dict) or p.get('operation')=='batch':return p
    kind=route.get('request_kind');ref=route.get('reference');domain=route.get('domain')
    if kind=='introduction' and ref and not domain and not route.get('needs_history'):
        return {'operation':'clarify','entity':None,'scope':'direct','clarification':'请说明这个对象属于PBS、构型、设备类还是部件类；已有对象标识已保留。'}
    if kind=='identity' and ref and p.get('operation') in ('clarify','search'):
        p={'operation':'attributes','entity':None,'scope':'direct','clarification':'','properties':['name','code'],
           'query':{'target':domain or 'objects','filters':[{'field':route.get('identifier_field') or 'identity','operator':'equals','value':ref}]}}
    if p.get('operation')=='clarify':return p
    unit=route.get('unit') or {}
    if unit.get('state')=='ambiguous' and route.get('comparisons'):
        return {'operation':'clarify','entity':None,'scope':'direct','clarification':'请明确数值条件使用的单位，例如摄氏度或华氏度；单位缺失的记录不能按指定单位参与比较。'}
    domain=route.get('domain');ref=route.get('reference');q=p.get('query')
    props=route.get('properties') or []
    if p.get('operation')=='search' and ref and props and q and any(f['field'] in ('identity','name','code') and f['operator']=='equals' and f['value']==ref for f in q['filters']):
        p['operation']='attributes';p['properties']=list(props)
    details={'attributes','object','measurement','threshold','equipment','equipment_class','part_class','parent'}
    # 无对象域的新单对象引用，应跨对象域精确核验。
    if p.get('operation') in details and ref and not domain and route.get('needs_history') is False:
        if (q or {}).get('target')!='points' and p['operation'] not in ('measurement','threshold'):
            extra=[f for f in (q or {}).get('filters',[]) if f['field'] not in ('name','code','identity')]
            p['entity']=None;p['query']={'target':'objects','filters':[{'field':route.get('identifier_field') or 'identity','operator':'equals','value':ref}]+extra};q=p['query']
    if domain and q:
        from query_filters import TARGETS
        tree=TARGETS.get(q.get('target'),(None,None))[0]
        if q.get('target')=='objects' or (domain!='points' and tree!=domain and p.get('operation') in details):q['target']=domain
    if route.get('scope') and p.get('operation') in ('search','parts','analyze'):p['scope']=route['scope']
    if p.get('operation')=='attributes' and route.get('projection')=='all':p['properties']=['*']
    props=route.get('properties') or []
    if props and p.get('operation')=='attributes' and p.get('properties')!=['*']:
        p['properties']=list(dict.fromkeys((p.get('properties') or [])+props))
    if props and p.get('operation') in ('attributes','threshold'):
        # 阈值和值的混合投影仍属于一个类型化标量任务。
        if p['operation']=='threshold' and any(x not in THRESHOLDS for x in props):
            p['operation']='attributes';p.pop('thresholds',None);p['properties']=list(props)
    if unit.get('state')=='specified' and route.get('comparisons') and q and q.get('target')=='points':
        target=canonical_unit(unit['value']);existing=[f for f in q['filters'] if f['field']=='unit']
        if existing and not all(f['operator']=='equals' and canonical_unit(f['value'])==target for f in existing):raise ValueError('计划的单位与请求不一致，未执行查询。')
        if not existing:q['filters'].append({'field':'unit','operator':'equals','value':target})
    return p

def enforce(plan,route):
    """发现需求丢失就拒绝执行，不能编造替代查询。"""
    if plan['operation']=='clarify':return plan
    children=[x['intent'] for x in plan['tasks']] if plan['operation']=='batch' else [plan]
    expected=route.get('thresholds')
    answered=set()
    filters=[]
    for child in children:
        if child['operation']=='threshold':answered.update(child.get('thresholds') or THRESHOLDS)
        props=child.get('properties') or []
        answered.update(THRESHOLDS if props==['*'] else props)
        filters.extend((child.get('query') or {}).get('filters',[]))
    properties=route.get('properties') or []
    if plan['operation'] in ('attributes','threshold','measurement','object') and properties:
        required=set(properties);provided=set(plan.get('properties') or [])
        if '*' in provided:
            from attributes import CATALOG
            provided=set(CATALOG)
        if plan['operation']=='threshold':provided.update(plan.get('thresholds') or THRESHOLDS);provided.add('value')
        if not required<=provided:raise ValueError('计划未完整覆盖所问属性；未执行，请明确需要保留的字段。')
    if expected and not set(expected)<=answered:raise ValueError('计划未覆盖所问阈值档位；未执行，请重试。')
    for f in route.get('comparisons',[]):
        if not any(g['field']==f['field'] and g['operator']==f['operator'] and decimal_value(g['value'])==decimal_value(f['value']) for g in filters):raise ValueError('计划未完整保留数值比较条件；未执行，请重试。')
    unit=route.get('unit') or {}
    if unit.get('state')=='ambiguous' and route.get('comparisons'):raise ValueError('单位尚未明确；未执行查询。')
    if unit.get('state')=='specified' and route.get('comparisons'):
        if not any(f['field']=='unit' and f['operator']=='equals' and canonical_unit(f['value'])==canonical_unit(unit['value']) for f in filters):raise ValueError('计划未完整保留单位条件；未执行查询。')
    return plan


def bind_subject_identity(store,plan,route):
    """无字段限定的父对象引用由精确数据解析，不按编码形状猜测。

显式名称或编码限制保持精确，不尝试其他字段兜底。
在关系遍历前执行，因为父对象引用不是结果筛选条件。"""
    entity=plan.get('entity') or {}
    ref=route.get('reference')
    if (plan.get('operation')=='batch' or route.get('identifier_field') not in (None,'identity','name','code')
            or not entity or route.get('domain')!=entity.get('tree')
            or ref!=entity.get('name',entity.get('code'))):return plan
    field=route.get('identifier_field') or 'identity'
    clause={'identity':'(code=? OR name=?)','name':'name=?','code':'code=?'}[field]
    rows=store.rows('SELECT tree,code,name FROM objects WHERE tree=? AND '+clause,
                    (entity['tree'],ref,ref) if field=='identity' else (entity['tree'],ref))
    if len(rows)==1:
        return {**plan,'entity':{'tree':rows[0]['tree'],'code':rows[0]['code']}}
    if len(rows)>1:
        return {'operation':'clarify','entity':None,'scope':plan.get('scope','direct'),
                'clarification':'同一标识在该对象树匹配多个对象，请明确编码或名称：'+
                '；'.join(x['name']+'（'+x['code']+'）' for x in rows[:10])}
    return plan
