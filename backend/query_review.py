"""一次性、绑定会话的查询确认；此处不调用模型或查询结果。"""
import copy
import hashlib
import json
import secrets
import time
from data import QueryError
from query_filters import filter_fields, TARGET_LABELS
from attributes import CATALOG
from typed_fields import NUMERIC_OPS, AMBIGUOUS_UNITS, canonical_unit

TTL = 900
NON_QUERY = {'clarify', 'conversation', 'explain_result', 'explain'}
EDITABLE = {'entity', 'scope', 'query', 'properties', 'analysis', 'thresholds', 'subjects', 'topics'}


def leaves(plan, question=''):
    return plan['tasks'] if plan['operation'] == 'batch' else [{'question':question, 'intent':plan}]


def relationship_task(trace,index):
    state=(trace or {}).get('business_request_state') or {};changed=(trace or {}).get('changed_tasks',[])
    if index>=len(changed):return None
    return next((t for t in state.get('tasks',[]) if t['id']==changed[index] and t['operation']=='descendants'),None)


def required(plan, context, trace=None):
    items = leaves(plan)
    executable = [x['intent'] for x in items if x['intent']['operation'] not in NON_QUERY]
    if not executable:
        return False
    if ((trace or {}).get('checklist_review') or {}).get('needs_review') is True:
        return True
    if any(relationship_task(trace,i) for i in range(len(items))):return True
    if len(items) > 1:
        return True
    delta = (trace or {}).get('business_request_delta') or {}
    following = context.get('business_request') and (trace is None or delta.get('mode')=='update' or
        (not delta and ((trace or {}).get('context_route') or {}).get('decision',{}).get('needs_history') is True))
    for p in executable:
        q = p.get('query') or {}
        fs = q.get('filters', [])
        if (p['operation'] in ('analyze', 'relation_check') or len(p.get('properties') or []) > 1 or p['scope'] == 'all' or q.get('equipment_class') or
            len(fs) > 1 or any(f['operator'] in NUMERIC_OPS for f in fs) or
            (p.get('entity') and q) or following):
            return True
    return False


def fingerprint(context):
    return hashlib.sha256(json.dumps(context, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def issue(session, sid, version, question, plan, trace):
    plan = copy.deepcopy(plan)
    from typed_fields import THRESHOLDS
    for item in leaves(plan, question):
        if item['intent']['operation'] == 'threshold' and not item['intent'].get('thresholds'):
            item['intent']['thresholds'] = list(THRESHOLDS)
    review = {'id':secrets.token_urlsafe(24), 'session':sid, 'version':version,
              'expires':time.monotonic()+TTL, 'context':fingerprint(session['context']),
              'question':question, 'plan':copy.deepcopy(plan), 'trace':copy.deepcopy(trace or {})}
    session['pending_review'] = review
    tasks = []
    for index, item in enumerate(leaves(plan, question)):
        p = item['intent']
        message=p.get('clarification') or p.get('message') or ''
        if p['operation']=='explain':
            from data_context import TOPICS
            message='说明：'+'、'.join(TOPICS[t] for t in p['topics'])+'。按已核实业务口径说明，不代为增加数据查询。'
        tasks.append({'index':index, 'question':item['question'], 'operation':p['operation'],
                      'enabled':p['operation'] not in NON_QUERY,
                      'values':{k:copy.deepcopy(p[k]) for k in EDITABLE if k in p},
                      'message':message})
        if relationship_task(trace,index):
            from relationship_request import review_values
            tasks[-1].update(operation='descendants',values=review_values(p),entity_trees={'config':'构型树'},
                query_targets={'config':'所有下级对象（不限类型）','parts':'仅下级部件'},fixed_population=True)
        if p['operation']=='parts' and (trace or {}).get('business_request_state'):
            tasks[-1]['entity_trees']={'config':'构型树'}
    return {'status':'review', 'answer':'请核对查询对象和条件，确认后再执行。',
            'records':[], 'evidence':[], 'metrics':[], 'path':[], 'entity':None, 'scope':'direct',
            'note':'尚未执行数据查询；所有筛选条件同时满足。',
            'review':{'id':review['id'], 'tasks':tasks, 'expires_in':TTL,
                      'semantic_review':copy.deepcopy((trace or {}).get('checklist_review',{}).get('semantic_review')),
                      'catalog':{'targets':TARGET_LABELS, 'fields':{k:filter_fields(k) for k in TARGET_LABELS},
                                 'properties':{k:v['label'] for k,v in CATALOG.items()}}}}


def confirmed_state(review, plans, indices, context):
    """保留未编辑分支，将用户修改的条件记录为已确认事实。"""
    from business_request import compile_task
    trace = review['trace']
    candidate = trace.get('business_request_state')
    changed = trace.get('changed_tasks', [])
    if not candidate or len(changed) != len(leaves(review['plan'])):
        return None, []
    previous = (context or {}).get('business_request') or {}
    updating = (trace.get('business_request_delta') or {}).get('mode') == 'update'
    state = copy.deepcopy(previous if updating and previous else candidate)
    if not updating or not previous:
        state['tasks'] = []
    state.update(version=1, revision=candidate['revision'], next_filter_id=candidate['next_filter_id'])
    source = {'kind':'user_confirmation', 'review':review['id'], 'turn':state['revision'], 'quote':review['question'][:500]}
    executed = []
    for index, p in zip(indices, plans):
        tid=changed[index]
        original=next(t for t in candidate['tasks'] if t['id']==tid)
        if original['operation'] in ('explain','unsupported'):
            if compile_task(original)!=p:return None,[]
            task=copy.deepcopy(original)
            task['sources'].update(operation=copy.deepcopy(source),topics=copy.deepcopy(source))
            pos=next((i for i,t in enumerate(state['tasks']) if t['id']==tid),None)
            if pos is None:state['tasks'].append(task)
            else:state['tasks'][pos]=task
            executed.append(tid)
            continue
        if original['operation']=='descendants':
            from relationship_request import edit_task,population_of_plan,compile_relationship
            task,next_id=edit_task(original,p.get('entity'),p['scope'],population_of_plan(p),source,state['next_filter_id'])
            if compile_relationship(task)!=p:raise QueryError('层级关系确认含未支持的附加条件。')
            state['next_filter_id']=next_id
            pos=next((i for i,t in enumerate(state['tasks']) if t['id']==tid),None)
            if pos is None:state['tasks'].append(task)
            else:state['tasks'][pos]=task
            executed.append(tid)
            continue
        if original['operation']=='parts':
            from parts_request import compile_parts
            entity=p.get('entity') or {}
            if p['operation']!='parts' or entity.get('tree')!='config' or len(entity)!=2:
                raise QueryError('部件关系确认只能修改构型根对象和下级范围。')
            keys=set(entity)-{'tree'}
            if not keys <= {'identity','code','name'}:
                raise QueryError('部件根对象标识无效。')
            key=next(iter(keys))
            task=copy.deepcopy(original)
            task.update(scope=p['scope'])
            f={'field':key,'operator':'equals','value':entity[key]}
            old=task['filters'][0]
            if any(f[k]!=old[k] for k in f):
                task['filters']=[{**f,'id':f"f{state['next_filter_id']}",'source':copy.deepcopy(source)}]
                state['next_filter_id']+=1
            if task['scope']!=original['scope']:
                task['sources']['scope']=copy.deepcopy(source)
            if compile_parts(task)!=p:
                raise QueryError('部件关系确认含有未支持的附加条件。')
            pos=next((i for i,t in enumerate(state['tasks']) if t['id']==tid),None)
            if pos is None:state['tasks'].append(task)
            else:state['tasks'][pos]=task
            executed.append(tid)
            continue
        if p['operation'] not in ('search', 'attributes') or p.get('entity') or not p.get('query') or set(p['query']) != {'target','filters'}:
            return None, []
        tid = changed[index]
        task = copy.deepcopy(next(t for t in candidate['tasks'] if t['id'] == tid))
        old_filters = task['filters']
        task.update(operation=p['operation'], target=p['query']['target'], scope=p['scope'], properties=copy.deepcopy(p.get('properties', [])))
        semantic_sources={k:copy.deepcopy(task['sources'][k]) for k in ('purpose','subject_scope') if k in task['sources']}
        task['sources'] = {k:copy.deepcopy(source) for k in ('operation','target','scope','properties','unit')}
        if len(semantic_sources)==2:
            if p==leaves(review['plan'])[index]['intent']:
                # 确认未修改的计划时，不能丢弃原有语义历史。
                task['sources'].update(semantic_sources)
            else:
                # 用户编辑的明确字段具有确定性；查询改变后，不能继续套用
                # 旧模型对身份或介绍意图的理解。
                for key,value in (('purpose','data'),('subject_scope','none')):
                    task['sources'][key]={**copy.deepcopy(source),'value':value,
                                          'previous':semantic_sources[key]}
        task['filters'] = []
        used = set()
        for f in p['query']['filters']:
            existing = next((old for old in old_filters if old['id'] not in used and all(old[k] == f[k] for k in ('field','operator','value'))), None)
            if existing:
                new = copy.deepcopy(existing)
                used.add(existing['id'])
            else:
                new = {**copy.deepcopy(f), 'id':f"f{state['next_filter_id']}", 'source':copy.deepcopy(source)}
                state['next_filter_id'] += 1
            task['filters'].append(new)
        unit = next((f['value'] for f in task['filters'] if f['field']=='unit' and f['operator']=='equals'), None)
        task['unit'] = {'state':'specified' if unit else 'none', 'value':canonical_unit(unit) if unit else ''}
        compile_task(task)
        pos = next((i for i,t in enumerate(state['tasks']) if t['id']==tid), None)
        if pos is None:
            state['tasks'].append(task)
        else:
            state['tasks'][pos] = task
        executed.append(tid)
    state['last_executed_tasks'] = executed
    return state, executed


def confirm(session, sid, version, token, edits):
    from model import validate
    review = session.get('pending_review')
    if (not review or not isinstance(token, str) or not secrets.compare_digest(review['id'], token) or
        review['session'] != sid or review['version'] != version or review['expires'] < time.monotonic() or
        review['context'] != fingerprint(session['context'])):
        raise QueryError('确认单已失效，请重新提问生成新的确认单。')
    original = leaves(review['plan'], review['question'])
    if not isinstance(edits, list) or len(edits) != len(original):
        raise QueryError('确认任务不完整，请核对后重试。')
    plans, indices, questions = [], [], []
    for index, (edit, item) in enumerate(zip(edits, original)):
        if (not isinstance(edit,dict) or set(edit)!={'index','enabled','values'} or
            type(edit['index']) is not int or edit['index']!=index or type(edit['enabled']) is not bool or
            not isinstance(edit['values'],dict) or set(edit['values'])-EDITABLE):
            raise QueryError('确认内容格式无效；不能修改执行类型或任务编号。')
        p = copy.deepcopy(item['intent'])
        if p['operation'] in NON_QUERY:
            if edit['values']!={k:copy.deepcopy(p[k]) for k in EDITABLE if k in p}:
                raise QueryError('说明任务为只读，不能修改为其他主题或数据查询。')
            if edit['enabled']:
                raise QueryError('未明确或不支持的任务不能确认执行，请补充问题。')
            plans.append(p); indices.append(index); questions.append(item['question'])
            continue
        if not edit['enabled']:
            continue
        try:
            related=relationship_task(review['trace'],index)
            if related:
                from relationship_request import reviewed_plan
                p=reviewed_plan(related,edit['values'])
            else:
                allowed = {k for k in EDITABLE if k in p}
                if set(edit['values']) != allowed:
                    raise QueryError('确认单字段不完整或含额外字段。')
                p.update(copy.deepcopy(edit['values']))
            p = validate(p)
        except (ValueError, RuntimeError) as error:
            raise QueryError(str(error)) from None
        fs = (p.get('query') or {}).get('filters', []) + ((p.get('analysis') or {}).get('numerator') or [])
        if any(f['operator'] in NUMERIC_OPS for f in fs) and any(f['field']=='unit' and f['operator']=='equals' and f['value'] in AMBIGUOUS_UNITS for f in fs):
            raise QueryError('请将数值筛选单位明确为摄氏度、华氏度或其他实际单位。')
        plans.append(p); indices.append(index); questions.append(item['question'])
    if not any(p['operation'] not in NON_QUERY for p in plans):
        raise QueryError('请至少保留一个查询任务，或点击取消。')
    plan = plans[0] if len(plans)==1 else {'operation':'batch','entity':None,'scope':'direct','clarification':'','tasks':[{'question':q,'intent':p} for q,p in zip(questions,plans)]}
    state, changed = confirmed_state(review, plans, indices, session['context'])
    trace = {'engine':'business_request' if state else 'legacy', 'source_question':review['question'],
             'user_confirmed':True, 'review_id':token, 'validated_intent':copy.deepcopy(plan),
             'review_preparation_ms':review.get('preparation_ms',0),
             'context_route':{'decision':{'needs_history':True}}}
    if state:
        trace.update(business_request_state=state, changed_tasks=changed)
    if review['trace'].get('checklist_review',{}).get('semantic_review'):
        trace['semantic_review_resolution']={'kind':'user_confirmation','candidate_edited':
            indices!=list(range(len(original))) or plans!=[x['intent'] for x in original]}
    # 所有编辑校验通过后才消费确认单；格式错误时草稿仍可编辑。
    session.pop('pending_review')
    return plan, trace, review['question']
