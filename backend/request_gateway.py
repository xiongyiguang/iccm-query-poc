"""普通查询的执行边界，不依赖规划协议。

旧协议适配仅保留语义，不能补造来源。
执行核验凭据保存在模型可见跟踪数据之外。"""
import copy
import hashlib
import json
import threading
from business_request import RequestInvalid,apply_delta,compile_selected,ground_identifiers

_VERIFIED=threading.local()


def reference_context(context,selection,store,question=None,current_mentions=None):
    """绑定完整原文引用以及本轮开始前的已执行或已选对象。

当前引用来自经过数据核验的字面链接器，不来自候选计划。
执行时重新检查原文位置与输入一致。"""
    from request_checklist import literal_references
    utterances=[x['question'] for x in context.get('dialogue',[]) if isinstance(x.get('question'),str)][-6:]
    pending=context.get('pending_question')
    if pending and pending not in utterances:utterances.append(pending)
    refs=[]
    if question is not None:
        for ref in current_mentions if current_mentions is not None else literal_references(question,store):
            if (type(ref.get('start')) is int and type(ref.get('end')) is int and
                0<=ref['start']<ref['end']<=len(question) and question[ref['start']:ref['end']]==ref.get('value')):
                refs.append({**ref,'kind':'current_literal','quote':question[ref['start']:ref['end']]})
    for turn,text in enumerate(utterances,1):
        for ref in literal_references(text,store):
            refs.append({**ref,'kind':'history_literal','quote':text,'turn':turn})
    # 历史引用的标识不一定存在于数据库；保留原话证据，
    # 让短对象域补答可以得到真实的未找到结果。
    unresolved=context.get('pending_reference')
    if isinstance(unresolved,str) and unresolved and isinstance(pending,str):
        import re
        match=re.search(r'(?<![A-Za-z0-9_])'+re.escape(unresolved)+r'(?![A-Za-z0-9_])',pending)
        if match:refs.append({'field':'identity','value':unresolved,'domain':None,'kind':'history_literal','quote':pending,
                              'start':match.start(),'end':match.end(),'unresolved':True})
    subjects=[]
    bindings=[('user_selection',selection),('executed_entity',context.get('entity'))]
    receipt=context.get('query_receipt') or {};subject=receipt.get('confirmed_subject')
    if isinstance(subject,dict) and isinstance(subject.get('version'),str) and subject['version'] and subject['version']==getattr(store,'version',None):
        from query_plan import exact_lookup_subject
        probe=exact_lookup_subject({'operation':receipt.get('operation'),'entity':receipt.get('requested_entity'),
            'scope':receipt.get('scope'),'query':receipt.get('query')},
            {'status':'ok','records':[subject]},store.version)
        if probe==subject:
            actual=store.rows('SELECT tree,code,name FROM objects WHERE tree=? AND code=?',[subject['tree'],subject['code']])
            if len(actual)==1 and all(actual[0][k]==subject[k] for k in ('tree','code','name')):
                bindings.append(('exact_lookup',{'tree':subject['tree'],'code':subject['code']}))
    for kind,entity in bindings:
        if not isinstance(entity,dict):continue
        field='code' if 'code' in entity else 'name';value=entity.get(field);tree=entity.get('tree')
        if not isinstance(value,str) or not value:continue
        rows=store.rows('SELECT tree,code,name FROM objects WHERE tree=? AND '+field+'=?',[tree,value])
        for row in rows:
            subject={k:row[k] for k in ('tree','code','name')}
            subject['kind']=kind
            if subject not in subjects:subjects.append(subject)
        domains={x['tree'] for x in rows}
        if store.rows('SELECT 1 FROM points WHERE '+field+'=? LIMIT 1',[value]):domains.add('points')
        for domain in sorted(domains):refs.append({'field':field,'value':value,'domain':domain,'kind':kind,'quote':value})
    refs=[{**r,'id':i} for i,r in enumerate(refs,1)]
    pending_request=context.get('pending_request')
    return {'confirmed_subjects':subjects,
            'pending':({'question':pending or (utterances[-1] if utterances else None),'asked':context.get('clarification'),
                        'reference':unresolved,'request':copy.deepcopy(pending_request),
                        'outcome':copy.deepcopy(context.get('outcome'))} if pending or pending_request else None),
            'utterances':utterances,'pending_question':pending,'references':refs,
            'executed_subject':copy.deepcopy(context.get('entity')),'user_selection':copy.deepcopy(selection)}


def ordinary(plan):
    q=plan.get('query')
    return (plan.get('operation') in ('search','attributes') and not plan.get('entity')
            and plan.get('scope','direct')=='direct' and isinstance(q,dict)
            and set(q)=={'target','filters'})


def static_note(plan):
    from data_context import STATIC_TOPICS,DOMAIN_FACTS
    if plan.get('operation')=='explain' and plan.get('topics') and set(plan['topics'])<=set(STATIC_TOPICS):return 'explain'
    if plan.get('operation')=='conversation' and plan.get('message')==DOMAIN_FACTS['limits']:return 'unsupported'
    return None


def normalize_entity_attributes(store,plan,route=None):
    """两种属性入口共用同一精确定位契约。"""
    out=copy.deepcopy(plan)
    for p in leaves(out):
        e=p.get('entity')
        if p.get('operation')!='attributes' or not e or p.get('scope','direct')!='direct':continue
        if p.get('query'):
            query=p['query']
            # 测点范围已包含 PBS 根对象本身；若精确编码条件
            # 已指向同一根对象，就无需重复父范围约束。
            if query.get('target')=='points' and e.get('tree')=='pbs' and any(f=={'field':'code','operator':'equals','value':e.get('code')} for f in query.get('filters',[])):
                p['entity']=None
            continue
        field='code' if 'code' in e else 'name';target=e['tree'];value=e[field]
        if route and route.get('domain')==target and route.get('reference')==value:
            field=route.get('identifier_field') or 'identity'
        if field not in ('name','code','identity'):raise RequestInvalid('对象标识字段不合法。')
        clause='(code=? OR name=?)' if field=='identity' else field+'=?'
        values=[value,value] if field=='identity' else [value]
        if target=='pbs' and not store.rows('SELECT 1 FROM objects WHERE tree=? AND '+clause+' LIMIT 1',[target]+values):
            if store.rows('SELECT 1 FROM points WHERE '+clause+' LIMIT 1',values):target='points'
        p.update(entity=None,query={'target':target,'filters':[{'field':field,'operator':'equals','value':value}]})
    return out


def leaves(plan):
    if plan.get('operation')=='batch':
        for item in plan['tasks']:
            yield from leaves(item['intent'])
    else:yield plan


def clear_verification():
    _VERIFIED.receipt=None


def fingerprint(store,question,plan):
    raw=json.dumps({'question':question,'version':store.version,'plan':plan},ensure_ascii=False,sort_keys=True,separators=(',',':'))
    return hashlib.sha256(raw.encode()).hexdigest()


def seal(store,question,plan):
    _VERIFIED.receipt=(id(store),fingerprint(store,question,plan))


def require_verified(store,question,plan):
    if getattr(_VERIFIED,'receipt',None)!=(id(store),fingerprint(store,question,plan)):
        raise RequestInvalid('查询未经过当前请求的完整校验，或核验后发生变化；未执行。')
    # 核验凭据只能使用一次，后续请求不能重放旧计划的批准结果。
    clear_verification()


def adapt(plan,question,previous,mode,store,references=None):
    """对照原话和同任务继承事实，重新校验旧协议中的值。"""
    from request_checklist import to_delta
    children=plan['tasks'] if plan.get('operation')=='batch' else [{'question':question,'intent':plan}]
    tasks=[];used=set()
    for item in children:
        p=item['intent'];note=static_note(p);q=p.get('query');base=None
        if note:
            if mode=='update':
                available=[t for t in (previous or {}).get('tasks',[]) if t['id'] not in used and t['operation']==note]
                if len(available)!=1:raise RequestInvalid('说明不能唯一对应已有任务，请明确要修改的任务。')
                base=available[0];used.add(base['id'])
            tasks.append({'id':base['id'] if base else None,'quote':question,'operation':note,
                          'topics':p['topics'] if note=='explain' else ['limits'],'execute':True})
            continue
        if mode=='update':
            available=[t for t in (previous or {}).get('tasks',[]) if t['id'] not in used and t['target']==q['target']]
            if len(available)>1:
                identities=[f for f in q['filters'] if f['field'] in ('identity','name','code') and f['operator']=='equals']
                matched=[t for t in available if any(all(f[k]==g[k] for k in ('field','operator','value')) for f in identities for g in t['filters'])]
                if len(matched)==1:available=matched
            if len(available)!=1:raise RequestInvalid('旧查询不能唯一对应已有业务任务，请明确要修改的任务。')
            base=available[0];used.add(base['id'])
        quote=item.get('question') or question
        if quote not in question:quote=question
        conditions=[]
        for f in q['filters']:
            inherited=base and any(all(f[k]==old[k] for k in ('field','operator','value')) for old in base['filters'])
            conditions.append({**copy.deepcopy(f),'quote':None if inherited else quote})
        unit=copy.deepcopy(base['unit']) if base else {'state':'none','value':''}
        exact_unit=next((f['value'] for f in q['filters'] if f['field']=='unit' and f['operator']=='equals'),None)
        if exact_unit:
            from typed_fields import canonical_unit
            unit={'state':'specified','value':canonical_unit(exact_unit)}
        elif unit['state']=='specified':unit={'state':'none','value':''}
        tasks.append({'id':base['id'] if base else None,'quote':quote,'operation':p['operation'],'target':q['target'],
                      'properties':copy.deepcopy(p.get('properties',[])),'unit':unit,'conditions':conditions})
    delta=to_delta({'status':'ready','mode':mode,'tasks':tasks,'clarification':''},previous,question)
    _,state,changed=apply_delta(delta,previous,question,references)
    state=ground_identifiers(store,state,changed)
    compiled=compile_selected(state,changed,[p['quote'] for p in delta['tasks']])
    return compiled,state,changed,delta


def validate_categories(state,changed,store):
    """类别否定不等同于任意子串否定。

完整数据标签可作为文本条件；部分匹配必须有明确引用的字面值。
此规则不依赖具体问句措辞。"""
    if store is None:return
    for task in state['tasks']:
        if task['id'] not in changed or task['target']!='points':continue
        for f in task['filters']:
            if f['field'] not in ('status','switch') or f['operator'] not in ('contains','not_contains','starts_with'):continue
            value=f['value'];quote=f.get('source',{}).get('quote','')
            known=store.rows('SELECT 1 FROM points WHERE '+f['field']+'=? LIMIT 1',[value])
            quoted=any(a+value+b in quote for a,b in [('“','”'),('「','」'),('"','"'),("'","'")])
            if not known and not quoted:
                raise RequestInvalid('类别筛选不能自动拆成部分字词匹配；请使用完整类别或明确引用要匹配的文字。')


def migrate(store,question,plan,trace):
    """统一普通旧协议查询入口，专用关系任务仍单独处理。"""
    from request_checklist import gate
    from model import validate
    plan=normalize_entity_attributes(store,plan)
    items=list(leaves(plan));eligible=[p for p in items if ordinary(p) or static_note(p)]
    if len(items)==1 and descendant_plan(items[0]):
        return migrate_descendants(store,question,items[0],trace)
    if not eligible:
        trace['gateway']={'status':'verified','entry':'dedicated_domain_contract','operations':[p['operation'] for p in items]}
        return plan
    if len(eligible)!=len(items):
        # 只迁移部分子任务，不能授权其余旧协议子任务；
        # 拒绝整个计划，并保留完整原问题和状态。
        result={'operation':'clarify','entity':None,'scope':'direct','clarification':'本次混合任务尚未全部通过完整请求核验，未执行任何查询。请分别明确要查询的数据与需要的说明。'}
        trace['gateway']={'status':'mixed_batch_requires_separate_ordinary_request'}
        return result
    previous=trace.get('business_request_previous')
    route=(trace.get('context_route') or {}).get('decision',{})
    mode='update' if previous and route.get('needs_history') and all(any((t['operation']==static_note(p) if static_note(p) else t['target']==p['query']['target']) for t in previous['tasks']) for p in eligible) else 'new'
    refs=trace.get('reference_context')
    compiled,state,changed,delta=adapt(plan,question,previous,mode,store,refs)
    checked=gate(question,previous,state,changed,mode,store,reference_context=refs)
    trace['checklist_review']={k:v for k,v in checked.items() if k not in ('plan','state','changed','delta')}
    trace['original_engine']=trace.get('engine');trace['engine']='business_request'
    if checked['decision']!='accept' or checked.get('needs_review'):
        if checked.get('pending_state'):trace['pending_business_request']=checked['pending_state']
        return {'operation':'clarify','entity':None,'scope':'direct','clarification':checked.get('reason','查询条件尚未核对一致。')+' 尚未执行，原条件已保留。'}
    if checked['choice']=='independent':compiled,state,changed,delta=(checked[k] for k in ('plan','state','changed','delta'))
    validate_categories(state,changed,store)
    trace.update(business_request_state=state,business_request_delta=delta,changed_tasks=changed,
                 gateway={'status':'verified','entry':'legacy_ordinary_adapter'})
    return validate(compiled)


def descendant_plan(plan):
    """单根、无附加条件的构型后代查询，包含旧协议续问。"""
    e=plan.get('entity') or {};q=plan.get('query')
    return e.get('tree')=='config' and (plan['operation']=='parts' and not q or
        plan['operation']=='search' and q in ({'target':'config','filters':[]},{'target':'parts','filters':[]}))


def migrate_descendants(store,question,plan,trace):
    from request_checklist import gate
    from business_request import compile_selected
    e=plan['entity'];field=next(k for k in ('code','name','identity') if k in e)
    previous=trace.get('business_request_previous')
    following=bool(previous and ((trace.get('context_route') or {}).get('decision') or {}).get('needs_history'))
    if following and len(previous.get('tasks',[]))!=1:
        return {'operation':'clarify','entity':None,'scope':'direct','clarification':'本次要继续哪一个对象的下级查询？'}
    mode='update' if following else 'new'
    tid=previous['tasks'][0]['id'] if following else 't1'
    revision=previous.get('revision',0)+1 if previous else 1
    next_filter_id=previous.get('next_filter_id',1) if previous else 1
    source={'kind':'validated_legacy_relation','quote':question,'turn':revision}
    population='parts' if plan['operation']=='parts' or plan.get('query',{}).get('target')=='parts' else 'all_objects'
    root_field,root_value=field,e[field]
    root_source=copy.deepcopy(source)
    rows=store.rows('SELECT code,name FROM objects WHERE tree=? AND '+('code' if field=='code' else 'name')+'=?',['config',e[field]]) if field!='identity' else []
    if len(rows)==1:
        aliases=rows[0]
        matches=[r for r in (trace.get('reference_context') or {}).get('references',[])
                 if r.get('domain')=='config' and r.get('field') in ('code','name') and aliases.get(r['field'])==r.get('value')]
        if matches:
            ref=matches[0];root_field,root_value=ref['field'],ref['value']
            root_source={'kind':ref['kind'],'quote':ref['quote'],'reference':ref['id'],'turn':revision}
    task={'id':tid,'operation':'descendants','target':'config','scope':plan['scope'],
          'population':population,'properties':[],'unit':{'state':'none','value':''},
          'filters':[{'id':f'f{next_filter_id}','field':root_field,'operator':'equals','value':root_value,'source':root_source}],
          'sources':{k:copy.deepcopy(source) for k in ('scope','population','target','operation','properties','unit')}}
    candidate={'version':1,'revision':revision,'next_filter_id':next_filter_id+1,'tasks':[task],'last_executed_tasks':[tid]}
    checked=gate(question,previous,candidate,[tid],mode,store,reference_context=trace.get('reference_context'))
    trace['checklist_review']={k:v for k,v in checked.items() if k not in ('plan','state','changed','delta')}
    trace['original_engine']=trace.get('engine');trace['engine']='business_request'
    if checked['decision']!='accept' or checked.get('needs_review'):
        if checked.get('pending_state'):trace['pending_business_request']=checked['pending_state']
        return {'operation':'clarify','entity':None,'scope':'direct','clarification':checked.get('reason','您要查询直接下级，还是全部下级？')}
    state,ids,delta=candidate,[tid],{'mode':mode,'tasks':[{'quote':question}]}
    if checked['choice']=='independent':state,ids,delta=checked['state'],checked['changed'],checked['delta']
    trace.update(business_request_state=state,changed_tasks=ids,business_request_delta=delta,
                 gateway={'status':'verified','entry':'legacy_descendant_adapter'})
    return compile_selected(state,ids,[question])
