"""依据原话来源保存业务请求，先应用变更再确定性编译。

此模块不解释自然语言、不调用模型、不编造结果。
更新时按结构保留未被提及的字段和筛选条件。"""
import copy
import json
import re
from attributes import CATALOG
from query_filters import TARGETS, validate_query
from typed_fields import NUMERIC_OPS,canonical_unit,UNIT_ALIASES,AMBIGUOUS_UNITS

NOTE_OPERATIONS={'explain','unsupported'}


class RequestInvalid(ValueError):
    pass

class RequestAmbiguous(RequestInvalid):
    def __init__(self,message,state=None):
        super().__init__(message);self.state=state


def require_keys(value, required, path):
    """诊断协议结构，不丢弃字段，也不回显字段值。"""
    if not isinstance(value, dict):
        raise RequestInvalid(path+'必须是JSON对象。')
    missing=sorted(set(required)-set(value));extra=sorted(set(value)-set(required))
    if missing or extra:
        raise RequestInvalid(path+'结构错误；缺少字段='+json.dumps(missing,ensure_ascii=False)+'；多余字段='+json.dumps(extra,ensure_ascii=False)+'；允许字段='+json.dumps(sorted(required),ensure_ascii=False))


def source_segments(question):
    """返回当前原话中的稳定位置偏移，不采用模型改写文字。"""
    return [{'id':i,'start':m.start(),'end':m.end(),'text':m.group()} for i,m in enumerate(re.finditer(r'[^、，,。；;！？!?]+[、，,。；;！？!?]?',question),1)]


def resolve_request_actions(payload,question,id_key):
    """核对话语动作的来源，并转换互斥动作类型。

动作角色由模型判断，不能据此证明自然语言理解正确。
retain 不重建状态，也不能授权任何输出。"""
    out=copy.deepcopy(payload);segments={s['id']:s for s in source_segments(question)}
    roles=out.pop('roles',None)
    modern=out.get('version') in (6,8,9,10,11,12,13) or id_key=='base' and out.get('version')==7
    require_keys(roles,{'background','output','control'} if modern else {'background','request','context'},'roles')
    requested=roles['output' if modern else 'request']
    seen=set()
    for ids in roles.values():
        require(isinstance(ids,list) and all(type(i) is int and i in segments for i in ids) and len(set(ids))==len(ids), '语句角色片段编号无效。')
        require(not seen.intersection(ids),'同一片段不能同时属于背景、请求与上下文。');seen.update(ids)
    require(seen==set(segments),'语句角色必须覆盖所有本轮片段。')
    require(isinstance(out.get('tasks'),list),'请求动作tasks必须是数组。')
    covered=set()
    for task in out['tasks']:
        require(isinstance(task,dict),'请求动作必须是对象。')
        action=task.get('action')
        if action=='retain':
            require_keys(task,{id_key,'action'},'retain')
            require(out.get('mode')=='update' and isinstance(task[id_key],str) and task[id_key], 'retain只能引用已有任务，不能新建。')
            task.pop('action');task['execute']=False
            # 此占位值仅在确认已有任务编号以及完全不修改状态的结构后，
            # 于来源校验前消除。
            task['quote']=None
            if id_key=='base':task.update(set={},filters=[])
            else:task['operation']='retain'
            continue
        require(action=='request' and 'execute' not in task and 'quote' not in task and 'request_quote' not in task,'本轮交付使用action=request，不能另带execute或重写原话。')
        ids=task.pop('request_spans',None);spans=task.get('spans')
        require(isinstance(ids,list) and ids and all(type(i) is int and i in requested for i in ids) and len(set(ids))==len(ids),'交付任务必须引用输出动作，不能仅以背景或控制指令作为交付依据。')
        require(isinstance(spans,list) and all(i in spans for i in ids),'任务spans必须包含其请求动作片段。')
        covered.update(ids);task.pop('action');task['execute']=True
        task['request_quote']=question[min(segments[i]['start'] for i in ids):max(segments[i]['end'] for i in ids)]
    require(covered==set(requested) or out.get('status')=='unsupported' and out['tasks']==[],
            '以下输出动作尚未对应request任务：'+json.dumps(sorted(set(requested)-covered))+'。若只限定条件或保留状态，应归control而非output；若确需输出，必须完整列出任务，不能漏做。')
    return out


def resolve_delta_sources(delta,question):
    if not isinstance(delta,dict) or delta.get('version') not in (2,3,4,5,6,7,8,9,10):return delta
    explicit_execution=delta['version'] in (3,4,5,6,7,8,9,10)
    out=resolve_request_actions(delta,question,'base') if delta['version'] in (5,6,7,8,9,10) else copy.deepcopy(delta)
    segments={s['id']:s for s in source_segments(question)}
    def resolve(item):
        require(isinstance(item,dict) and 'quote' not in item,'片段协议不能重写原话。')
        ids=item.pop('spans',None)
        require(isinstance(ids,list) and ids and all(type(i)==int and i in segments for i in ids) and len(set(ids))==len(ids),'原话片段编号不存在或重复。')
        item['quote']=question[min(segments[i]['start'] for i in ids):max(segments[i]['end'] for i in ids)]
    require(isinstance(out.get('tasks'),list),'业务请求缺少任务。')
    for task in out['tasks']:
        if explicit_execution:
            require(isinstance(task,dict) and type(task.get('execute')) is bool,'V3任务必须明确execute布尔值。')
        if delta['version'] in (5,6,7,8,9,10) and task['execute'] is False:continue
        if delta['version'] in (7,8,9,10):task['_purpose_required']=True
        if delta['version']==10:task['_goal_required']=True
        if delta['version']==10 and 'result_goal' in task:
            goal=task.pop('result_goal');fields=task.get('set')
            require(isinstance(fields,dict) and ('result_goal' not in fields or fields['result_goal']==goal),'结果目标重复且冲突，未执行。')
            fields['result_goal']=goal
        resolve(task)
        require(isinstance(task.get('filters'),list),'业务请求缺少条件变更。')
        for edit in task['filters']:resolve(edit)
    out['version']=1
    return out

def extraction_context(context):
    """维护唯一权威任务状态，不建立与旧单对象焦点竞争的状态源。"""
    state=context.get('pending_business_request') or context.get('business_request')
    if not state:return context
    return {'business_request':state,
            'request_status':('awaiting_'+state['pending_reason'] if state.get('pending_reason') else 'awaiting_unit' if any(t.get('unit',{}).get('state')=='ambiguous' for t in state.get('tasks',[])) else 'awaiting_clarification') if context.get('pending_business_request') else 'confirmed',
            'task_directory':[{'number':i,'id':t['id'],'operation':t['operation'],'target':t['target'],'scope':t['scope'],**({'population':t['population']} if t['operation']=='descendants' else {}),'filters':t['filters'],'properties':t['properties'],**({'result_goal':t['result_goal']} if 'result_goal' in t else {}),**({'topics':t['topics']} if t['operation'] in NOTE_OPERATIONS else {})} for i,t in enumerate(state['tasks'],1)],
            'last_executed_tasks':state.get('last_executed_tasks',[]),
            'pending_question':context.get('pending_question'),
            'pending_slot':copy.deepcopy(context.get('pending_slot')),
            'legacy_context':{k:v for k,v in context.items() if k not in ('business_request','pending_business_request','dialogue')}}


def unpack_route(envelope,normalize_inactive=False,require_current=False):
    # 受限修复可能仍遗漏未启用的联合类型分支；只补 null 不改变语义，
    # 不能编造启用的请求或替用户选择两个请求之一。
    if normalize_inactive and isinstance(envelope,dict) and len(envelope)==1:
        active=next(iter(envelope))
        if active in ('business_request','legacy') and isinstance(envelope[active],dict):
            envelope={**envelope,('legacy' if active=='business_request' else 'business_request'):None}
    require(isinstance(envelope,dict) and set(envelope)=={'business_request','legacy'}, '必须明确采用业务请求或兼容路径，不能省略协议字段。')
    request=envelope['business_request'];legacy=envelope['legacy']
    if request is None:
        require(isinstance(legacy,dict), '兼容路径必须提供完整语义槽位。')
        return {**legacy,'business_request':None}
    if require_current:require(isinstance(request,dict) and request.get('version')==10,'当前语义入口必须使用V10完整结果目标契约，不能降级到旧协议。')
    require(isinstance(request,dict) and legacy is None, '业务请求不能同时附带另一套自由规划。')
    return {'needs_history':request.get('mode')=='update','identifier_field':None,'resolved_question':None,
            'domain':None,'thresholds':None,'comparisons':[],'unit':{'state':'none','value':''},
            'reference':None,'projection':'specified','scope':None,'properties':[],
            'context_mode':'followup' if request.get('mode')=='update' else 'new','request_kind':'other','business_request':request}


def ground_identifiers(store,state,changed):
    """依据每项任务自己的原话片段，补全被截断的字面引用。"""
    import re
    from identifier_aliases import complete_literal_pattern
    out=copy.deepcopy(state)
    for task in out['tasks']:
        if task['id'] not in changed:continue
        target=task['target']
        for f in task['filters']:
            if f['operator']!='equals' or f['field'] not in ('name','code','identity','source'):continue
            if target=='points':
                table='points';columns=['name','code'] if f['field']=='identity' else [{'source':'system'}.get(f['field'],f['field'])];where='';args=[]
            else:
                if f['field']=='source':continue
                table='objects';columns=['name','code'] if f['field']=='identity' else [f['field']]
                tree=TARGETS[target][0];where='' if tree=='*' else ' AND tree=?';args=[] if tree=='*' else [tree]
            exact=[];candidates=set();value=f['value'];quote=f['source']['quote']
            for column in columns:
                exact+=store.rows(f'SELECT {column} AS value FROM {table} WHERE {column}=?'+where+' LIMIT 1',[value]+args)
                rows=store.rows(f'SELECT DISTINCT {column} AS value FROM {table} WHERE {column}<>\'\' AND instr(?,{column})>0 AND instr({column},?)>0'+where+' LIMIT 20',[quote,value]+args)
                for row in rows:
                    full=row['value']
                    if re.search(complete_literal_pattern(full),quote):candidates.add(full)
            # 脱敏名称的字段简称只在目录和原文共同核验、且无同字面精确对象时展开。
            if not exact and f['field'] in ('name','identity'):
                from identifier_aliases import schema_name_aliases
                aliases=[r for r in schema_name_aliases(quote,store) if r['quote']==value and (r['domain']==target or target=='objects' and r['domain']!='points')]
                require(len({r['value'] for r in aliases})<=1,'该名称简称对应多个对象，请明确完整名称。')
                if aliases:
                    f['value']=aliases[0]['value'];f['resolution']={'kind':'schema_alias','before':value,'raw_field_label':aliases[0]['raw_field_label'],'quote':value}
                    continue
            if exact and f['field'] in ('name','identity'):
                from identifier_aliases import schema_name_aliases
                verified=[r for r in schema_name_aliases(quote,store) if r['value']==value and (r['domain']==target or target=='objects' and r['domain']!='points')]
                if verified:
                    f['resolution']={'kind':'schema_alias','before':verified[0]['quote'],'raw_field_label':verified[0]['raw_field_label'],'quote':verified[0]['quote']}
                    continue
            # 继承点选条件时原话只是续问，身份来自服务器已经核验的候选点选。
            selection=f['source'].get('selection',{})
            selected=(f['source'].get('kind')=='user_selection' and f['field']=='code' and
                      selection.get('code')==value and selection.get('tree')==('pbs' if target=='points' else TARGETS[target][0]))
            if exact and (value in candidates or f['source'].get('kind')=='executed_receipt' or selected):continue
            require(len(candidates)<=1,'原话片段匹配多个完整对象标识，请明确对象；未执行。')
            if candidates:
                f['value']=next(iter(candidates));f['resolution']={'kind':'exact_literal_data','before':value}
            elif exact:
                raise RequestInvalid('对象标识不是原话中的完整名称或编码，请明确对象；未执行。')
    return out


def review_semantics(state,changed):
    """描述可执行条件，不从用户措辞推断新增条件。"""
    from typed_fields import NUMERIC_LABELS,decimal_value,compare
    summaries=[]
    for task in state['tasks']:
        if task['id'] not in changed:continue
        numeric=[f for f in task['filters'] if f['operator'] in NUMERIC_OPS]
        intervals=[]
        for field in sorted({f['field'] for f in numeric}):
            fs=[f for f in numeric if f['field']==field]
            lower=[f for f in fs if f['operator'] in ('gt','gte')];upper=[f for f in fs if f['operator'] in ('lt','lte')]
            if not lower or not upper:continue
            lo=max(lower,key=lambda f:decimal_value(f['value']))['value'];hi=min(upper,key=lambda f:decimal_value(f['value']))['value']
            included=[all(compare(endpoint,f['operator'],f['value']) for f in fs) for endpoint in (lo,hi)]
            intervals.append({'field':field,'lower':lo,'upper':hi,'lower_included':included[0],'upper_included':included[1],'included_boundary_count':sum(included),'both_endpoints_included':all(included)})
        summaries.append({'task_id':task['id'],'relation':'AND','numeric_predicates':[{'id':f['id'],'meaning':CATALOG.get(f['field'],{}).get('label',f['field'])+NUMERIC_LABELS[f['operator']]+f['value']} for f in numeric],'intervals':intervals})
    return summaries


def execution_quotes(delta):
    return [p['quote'] for p in delta['tasks'] if p.get('execute',True)]


def no_execution_plan():
    return {'operation':'conversation','entity':None,'scope':'direct','clarification':'',
            'message':'已保留原查询状态，本轮未执行查询。'}


def compile_selected(state,changed,questions):
    require(len(changed)==len(questions),'执行任务和原话依据数量不一致。')
    if not changed:return no_execution_plan()
    plans=[{'question':q,'intent':compile_task(next(t for t in state['tasks'] if t['id']==tid))} for tid,q in zip(changed,questions)]
    return plans[0]['intent'] if len(plans)==1 else {'operation':'batch','entity':None,'scope':'direct','clarification':'','tasks':plans}


def require(ok, message):
    if not ok:
        raise RequestInvalid(message)


def evidence(quote, question, revision):
    require(isinstance(quote, str) and 0 < len(quote) <= 500 and quote in question,
            '请求变更缺少本轮原话依据；原条件未修改。')
    return {'turn': revision, 'quote': quote}


def compile_task(task,allow_ambiguous=False):
    if task.get('operation') in NOTE_OPERATIONS:
        from data_context import STATIC_TOPICS,DOMAIN_FACTS
        require(set(task)=={'id','operation','target','scope','properties','filters','sources','unit','topics'},'说明任务结构无效。')
        require(task['target'] is None and task['scope']=='direct' and task['properties']==[] and task['filters']==[] and task['unit']=={'state':'none','value':''},'说明任务不能携带对象、属性、筛选或单位。')
        topics=task['topics']
        require(isinstance(topics,list) and 1<=len(topics)<=5 and all(isinstance(t,str) and t in STATIC_TOPICS for t in topics) and len(set(topics))==len(topics),'说明主题必须来自已核实的静态说明目录。')
        if task['operation']=='unsupported':
            require(topics==['limits'],'不支持任务只能说明能力边界，不能附加查询或其他说明。')
            return {'operation':'conversation','entity':None,'scope':'direct','clarification':'','message':DOMAIN_FACTS['limits']}
        return {'operation':'explain','entity':None,'scope':'direct','clarification':'','topics':copy.deepcopy(topics)}
    require(set(task) == {'id','operation','target','scope','properties','filters','sources','unit'} | ({'result_goal'} if 'result_goal' in task else set()) | ({'population'} if task['operation']=='descendants' else set()), '业务任务结构无效。')
    if task['operation']=='descendants':
        from relationship_request import compile_relationship
        return compile_relationship(task,allow_ambiguous)
    if task['operation']=='parts':
        from parts_request import compile_parts
        return compile_parts(task)
    require(task['operation'] in ('search','attributes'), '该任务不属于已迁移的查询类型。')
    require(task['target'] in TARGETS, '查询目标无效。')
    require(task['scope'] == 'direct', '关系范围查询仍需明确的关系规划。')
    props = task['properties']
    require(isinstance(props,list) and len(props) <= len(CATALOG) and all(isinstance(p,str) and (p in CATALOG or p == '*') for p in props), '属性目录无效。')
    require(len(set(props)) == len(props) and ('*' not in props or props == ['*']), '属性清单重复或混用全部属性。')
    require(bool(props) if task['operation'] == 'attributes' else not props, '列表任务和属性投影必须明确分开。')
    filters = [{k:f[k] for k in ('field','operator','value')} for f in task['filters']]
    if not allow_ambiguous and any(f['operator'] in NUMERIC_OPS for f in filters) and task['unit']['state']=='ambiguous':
        raise RequestAmbiguous('请明确数值条件的单位，例如摄氏度或华氏度；尚未执行查询。')
    if task['unit']['state']=='specified' and any(f['operator'] in NUMERIC_OPS for f in filters):
        require(any(f['field']=='unit' and f['operator']=='equals' and canonical_unit(f['value'])==task['unit']['value'] for f in filters), '数值比较缺少已明确的单位筛选。')
    query = {'target':task['target'], 'filters':filters}
    validate_query(query)
    if task['operation'] == 'attributes':
        identities = [f for f in filters if f['field'] in ('name','code','identity') and f['operator'] == 'equals']
        require(len(identities) == 1, '属性查询需要一个精确对象标识；未执行宽泛属性查询。')
    plan = {'operation':task['operation'], 'entity':None, 'scope':'direct', 'clarification':'', 'query':query}
    if 'result_goal' in task:
        from result_goal import validate_plan_goal
        plan['result_goal']=copy.deepcopy(task['result_goal'])
        validate_plan_goal(plan)
    if props:
        plan['properties'] = copy.deepcopy(props)
    if task.get('result_goal',{}).get('kind')=='unsupported':
        return {'operation':'clarify','entity':None,'scope':'direct','clarification':'此结果目标尚不支持，未执行替代查询。'}
    return plan


def apply_delta(delta, previous, question, reference_context=None):
    delta=resolve_delta_sources(delta,question)
    require(isinstance(delta,dict) and set(delta) == {'version','mode','tasks'} and delta['version'] == 1, '业务请求版本或结构无效。')
    require(delta['mode'] in ('new','update'), '请求必须明确新建或更新。')
    patches = delta['tasks']
    require(isinstance(patches,list) and 1 <= len(patches) <= 4, '业务任务数必须为1至4。')
    previous = copy.deepcopy(previous or {})
    if delta['mode'] == 'update':
        require(previous.get('version') == 1 and previous.get('tasks'), '没有可继承的已确认业务请求；请明确完整问题。')
    revision = previous.get('revision',0) + 1
    state = {'version':1,'revision':revision,'next_filter_id':previous.get('next_filter_id',1),
             'tasks':copy.deepcopy(previous.get('tasks',[])) if delta['mode'] == 'update' else []}
    touched = set(); plans = []; changed = []; missing_domains=[]; missing_relationships=[]
    def fresh_task(tid):
        return {'id':tid,'operation':None,'target':None,'scope':'direct','properties':[], 'filters':[],
                'sources':{'scope':{'kind':'default','value':'direct'},'properties':{'kind':'default','value':[]}},'unit':{'state':'none','value':''}}
    for index, patch in enumerate(patches,1):
        require(isinstance(patch,dict) and {'base','quote','set','filters'}<=set(patch) and not set(patch)-{'base','quote','set','filters','unit','replace_task','retain_filters','execute','request_quote','purpose','subject_scope','_purpose_required','_goal_required'}, '任务变更结构无效。')
        execute=patch.get('execute',True)
        require(type(execute) is bool,'execute必须是布尔值。')
        require(execute or delta['mode']=='update','新任务不能仅保留而不执行。')
        replacing=patch.get('replace_task',False)
        require(type(replacing)==bool and (not replacing or delta['mode']=='update'), '任务替换只适用于已有任务。')
        retained_assertions=patch.get('retain_filters',[]) if not replacing else []
        require(isinstance(retained_assertions,list) and all(isinstance(fid,str) for fid in retained_assertions)
                and len(set(retained_assertions))==len(retained_assertions),'保留条件断言须为不重复的条件编号列表。')
        require(not retained_assertions or delta['mode']=='update' and execute,'新建或不执行任务不能声明局部条件保留。')
        protected_filters={}

        task_source = evidence(patch['quote'],question,revision) if execute or patch['quote'] is not None else None
        fields = patch['set']; edits = patch['filters']
        require(isinstance(fields,dict) and not set(fields)-{'operation','target','scope','properties','topics','population','result_goal'}, '任务设置字段无效。')
        require(isinstance(edits,list) and len(edits) <= 8, '筛选变更数量无效。')
        requested_operation=fields.get('operation')
        if isinstance(requested_operation,dict):requested_operation=requested_operation.get('value')
        if delta['mode'] == 'new':
            require(patch['base'] is None and 'operation' in fields and (requested_operation in NOTE_OPERATIONS or 'target' in fields), '新任务必须声明操作和目标，不能继承旧任务。')
            task = fresh_task(f't{index}')
            if requested_operation in NOTE_OPERATIONS:task['topics']=[]
            state['tasks'].append(task)
        else:
            require(isinstance(patch['base'],str) and patch['base'] not in touched, '不能重复或模糊地修改同一任务。')
            matches = [t for t in state['tasks'] if t['id'] == patch['base']]
            require(len(matches) == 1, '被修改的任务编号不存在；未改动其他任务。')
            task = matches[0]
            if not execute:
                require(not fields and not edits and not replacing and 'unit' not in patch and 'purpose' not in patch and 'subject_scope' not in patch,
                        '不执行的任务必须完整保留原状态，不能同时修改字段、条件或单位。')
                require('request_quote' not in patch,'原样保留不能附带本轮交付来源。')
                touched.add(task['id'])
                continue
            destination=requested_operation or task['operation']
            require(replacing or (destination in NOTE_OPERATIONS)==(task['operation'] in NOTE_OPERATIONS),'查询与说明类型切换必须显式replace_task=true。')
            require(replacing or (destination in ('parts','descendants'))==(task['operation'] in ('parts','descendants')),'部件关系与普通查询切换必须显式replace_task=true。')
            if destination=='descendants' and task['operation']=='parts' and not replacing:
                task['population']='parts';task['sources']['population']={'kind':'legacy_parts_contract','value':'parts'}
            if destination=='parts' and task['operation']=='descendants' and not replacing:
                require(False,'已有显式对象集合不能退回隐含部件协议，请沿用descendants任务。')
            if replacing:
                note=destination in NOTE_OPERATIONS
                require(({'operation','topics'} if note else {'operation','target','properties'})<=set(fields), '替换任务必须完整声明对应查询或说明字段。')
                retained=patch.get('retain_filters',[])
                require(isinstance(retained,list) and all(isinstance(fid,str) for fid in retained) and len(set(retained))==len(retained), '保留条件编号无效或重复。')
                require(not note or not retained,'替换为说明不能保留查询条件。')
                originals={f['id']:f for f in task['filters']}
                require(set(retained)<=set(originals), '保留条件不存在或属于其他任务。')
                require(all(isinstance(e,dict) and e.get('action')=='add' and e.get('ids')==[] for e in edits), '替换任务的旧条件只能通过retain_filters保留；新条件必须add。')
                old=copy.deepcopy(task);new=fresh_task(task['id'])
                if note:new['topics']=[]
                new['filters']=[copy.deepcopy(originals[fid]) for fid in retained]
                new['sources']['replacement']={**task_source,'previous_target':old['target'],'retained_filter_ids':retained}
                for f in new['filters']:
                    if f['field']=='unit' and f['operator']=='equals':
                        new['unit']={'state':'specified','value':canonical_unit(f['value'])};new['sources']['unit']=copy.deepcopy(f['source'])
                task.clear();task.update(new)
        if retained_assertions:
            require(task['operation'] not in NOTE_OPERATIONS and requested_operation not in NOTE_OPERATIONS,
                    '说明任务不能声明查询条件保留。')
            by_id={f['id']:f for f in task['filters']}
            require(set(retained_assertions)<=set(by_id),'保留条件不存在或属于其他任务。')
            require(all(not set(e.get('ids',[])) & set(retained_assertions) for e in edits if isinstance(e,dict)),
                    '同一条件不能同时声明保留与修改或删除。')
            protected_filters={fid:copy.deepcopy(by_id[fid]) for fid in retained_assertions}
        from object_scope import is_domain_draft
        completing_domain=(delta['mode']=='update' and not replacing and is_domain_draft(previous,task)
                           and patch.get('purpose')=='introduction' and patch.get('subject_scope')=='explicit')
        if completing_domain:
            # 此例外只补充尚未确定的对象域，不能把不同对象、
            # 属性投影或数值条件夹带进草稿。
            require(not edits and ('unit' not in patch or patch['unit']==task['unit']),
                    '补充对象树只能填补待确认域，不能同时修改对象或单位。')
            for key,spec in fields.items():
                value=spec.get('value') if isinstance(spec,dict) and key!='result_goal' else spec
                require(key=='target' or value==task.get(key),'补充对象树必须保留原操作和返回字段。')
        touched.add(task['id']); consumed = set()
        if 'request_quote' in patch:task['sources']['request']=evidence(patch['request_quote'],question,revision)
        note=(requested_operation or task['operation']) in NOTE_OPERATIONS
        require(not note or not edits and 'unit' not in patch and 'purpose' not in patch and 'subject_scope' not in patch and not set(fields)-{'operation','topics'},'说明任务不能修改查询对象、筛选、字段或单位。')
        for name, spec in fields.items():
            if isinstance(spec,dict) and name!='result_goal':
                require(set(spec) == {'value','quote'}, '字段设置缺少值或来源。')
                source = evidence(spec['quote'],question,revision);value=spec['value']
            else:source=task_source;value=spec
            if name == 'target' and delta['mode'] == 'update' and not replacing:
                scoped_identity=patch.get('purpose') in ('identity','introduction') and patch.get('subject_scope') in ('confirmed','unspecified','cross_tree')
                require(value == task['target'] or scoped_identity or completing_domain, '更换已有任务的target必须replace_task=true，完整声明operation/target/properties，用retain_filters列出明确保留的本任务旧条件，filters只允许add新条件；其他任务保留。')
            task[name] = copy.deepcopy(value); task['sources'][name] = source
        if note:
            plan=compile_task(task)
            plans.append({'question':patch['quote'],'intent':plan});changed.append(task['id'])
            continue
        for operand in task.get('result_goal',{}).get('operands',[]):
            val=operand.get('value');field=operand.get('field')
            require(isinstance(val,str) and (val in question or any(ref.get('value')==val and ref.get('field') in (field,'identity') and ref.get('domain') in (None,task['target']) for ref in (reference_context or {}).get('references',[]))),'计算对象缺少原话或经过核验的引用，未计算。')
        if patch.get('_goal_required') and task['operation'] in ('search','attributes'):
            require('result_goal' in task,'当前协议必须完整保存结果目标；不能降级为记录列表。')
        if patch.get('_purpose_required'):
            require('purpose' in patch and 'subject_scope' in patch,'V7查询任务须声明purpose和subject_scope。')
        if 'unit' in patch:
            u=patch['unit'];require(isinstance(u,dict) and set(u)=={'state','value'} and u['state'] in ('none','ambiguous','specified') and isinstance(u['value'],str), '单位语义必须明确none/ambiguous/specified。')
            require(bool(u['value']) == (u['state']=='specified'), '单位值与语义状态不一致。')
            retained_unit=next((f for f in task['filters'] if replacing and f['field']=='unit' and f['operator']=='equals' and canonical_unit(f['value'])==canonical_unit(u['value'])),None)
            task['unit']={'state':u['state'],'value':canonical_unit(u['value'])};task['sources']['unit']=task_source
            if u['state']=='specified':
                aliases={u['value'],canonical_unit(u['value'])}|{a for a,v in UNIT_ALIASES.items() if v==canonical_unit(u['value'])}
                require(any(a in question for a in aliases) or retained_unit is not None,'单位归一缺少本轮原话依据。')
                if retained_unit and not any(a in question for a in aliases):task['sources']['unit']=copy.deepcopy(retained_unit['source'])
        original_ids = {f['id'] for f in task['filters']}
        for edit in edits:
            require(isinstance(edit,dict) and set(edit) == {'action','ids','conditions','quote'}, '筛选变更必须明确动作、条件编号和来源。')
            source = evidence(edit['quote'],question,revision)
            action = edit['action']; ids = edit['ids']; conditions = edit['conditions']
            require(action in ('add','replace','remove') and isinstance(ids,list) and all(isinstance(i,str) for i in ids)
                    and len(ids) == len(set(ids)) and isinstance(conditions,list), '筛选变更动作无效。')
            require((not ids if action == 'add' else bool(ids)) and (not conditions if action == 'remove' else bool(conditions)), '筛选动作与内容不一致。')
            require(set(ids) <= original_ids and not set(ids)&consumed, '条件编号不存在、跨任务或被重复修改；未执行。')
            consumed.update(ids)
            removed = [f for f in task['filters'] if f['id'] in ids]
            if action=='remove' and any(f['field']=='unit' for f in removed):task['unit']={'state':'none','value':''};task['sources']['unit']=source
            task['filters'] = [f for f in task['filters'] if f['id'] not in ids]
            for condition in conditions:
                require_keys(condition,{'field','operator','value'},'tasks[].filters[].conditions[]（来源spans放在filters动作层）')
                f = copy.deepcopy(condition);filter_source=source
                # 完整标识须有原话或已核验引用，不能由模型自由拼接。
                if f['field'] in ('source','name','code','identity') and f['operator'] == 'equals':
                    require(isinstance(f['value'],str), '精确标识必须为文字。')
                    if f['value'] not in source['quote']:
                        refs=[r for r in (reference_context or {}).get('references',[])
                              if r['value']==f['value'] and (f['field']=='identity' or r['field'] in ('identity',f['field']))
                              and (r['domain'] is None or task['target']=='objects' and r['domain']!='points' or
                                   r['domain']==('config' if task['target'] in ('equipment','parts') else task['target']))]
                        require(bool(refs),'精确标识缺少本轮原话或可信历史引用依据。')
                        chosen=next((r for r in refs if r['kind']=='user_selection'),refs[-1])
                        filter_source={'kind':chosen['kind'],'turn':revision,'quote':chosen['quote'],
                                       'reference':{k:chosen[k] for k in ('field','value','domain')},'requested_by':source}
                if f['field']=='unit' and f['operator']=='equals':
                    canonical=canonical_unit(f['value']);aliases={f['value'],canonical}|{a for a,v in UNIT_ALIASES.items() if v==canonical}
                    if not any(alias in source['quote'] for alias in aliases):
                        matches=sorted((alias for alias in aliases if alias and alias in task_source['quote']),key=lambda x:(-len(x),x))
                        require(bool(matches),'单位筛选值缺少原话中的明确单位；不能把模糊单位补为摄氏度。')
                        filter_source=evidence(matches[0],question,revision)
                    # 每一处单位输入都通过来源校验后，重复单位合取才是幂等操作；
                    # 保留首次出现的条件编号。
                    f['value']=canonical
                    if any(old['field']=='unit' and old['operator']=='equals' and canonical_unit(old['value'])==canonical for old in task['filters']):
                        continue
                f.update(id=f'f{state["next_filter_id"]}',source=filter_source)
                if f['field']=='unit' and f['operator']=='equals':
                    # 有原话依据的精确单位具有确定性；无需模型同步修改
                    # 另一个重复的歧义标记。
                    task['unit']={'state':'specified','value':canonical_unit(f['value'])}
                    task['sources']['unit']=copy.deepcopy(filter_source)
                state['next_filter_id'] += 1
                # 只替换同字段的一个区间端点时，保留该条件的稳定编号。
                if len(removed) == len(conditions) == 1 and removed[0]['field'] == f['field']:
                    f['id'] = removed[0]['id']
                task['filters'].append(f)
        if replacing:
            retained_units=[f for f in task['filters'] if f['id'] in patch.get('retain_filters',[]) and f['field']=='unit' and f['operator']=='equals']
            if retained_units and len({canonical_unit(f['value']) for f in retained_units})==1:
                task['unit']={'state':'specified','value':canonical_unit(retained_units[0]['value'])}
                task['sources']['unit']=copy.deepcopy(retained_units[0]['source'])
        if (delta['mode']=='new' or replacing) and any(f['operator'] in NUMERIC_OPS for f in task['filters']):
            require('unit' in patch or task['unit']['state']=='specified','新建数值查询必须声明单位是否明确，不能把单位歧义当成无单位。')
        if any(f['operator'] in NUMERIC_OPS for f in task['filters']):
            exact_units={canonical_unit(f['value']) for f in task['filters'] if f['field']=='unit' and f['operator']=='equals' and f['value'] not in AMBIGUOUS_UNITS}
            require(len(exact_units)<=1,'同一数值任务包含冲突单位，不能选择其中一个执行。')
            unclear=[f for f in task['filters'] if f['field']=='unit' and f['operator']=='equals' and f['value'] in AMBIGUOUS_UNITS]
            if unclear or task['unit']['value'] in AMBIGUOUS_UNITS:
                if unclear:task['sources']['unit']=copy.deepcopy(unclear[0]['source'])
                task['unit']={'state':'ambiguous','value':''}
                # 保留数值条件草稿，不保存不可能成立的筛选条件，
                # 避免用户随后明确摄氏度或华氏度后仍受错误条件影响。
                task['filters']=[f for f in task['filters'] if f not in unclear]
        require(len(task['filters']) <= 8, '单任务筛选条件超过8项。')
        signatures = [(f['field'],f['operator'],f['value']) for f in task['filters']]
        require(len(signatures) == len(set(signatures)), '同一条件重复添加；请明确替换原条件。')
        for fid,original in protected_filters.items():
            require(next((f for f in task['filters'] if f['id']==fid),None)==original,
                    '声明保留的旧条件在本次修改中发生变化。')
        from object_scope import apply_scope
        if apply_scope(task,patch,task_source,reference_context):missing_domains.append(task['id'])
        plan = compile_task(task,allow_ambiguous=True)
        if task['operation']=='descendants' and plan['operation']=='clarify':missing_relationships.append(task['id'])
        plans.append({'question':patch['quote'],'intent':plan}); changed.append(task['id'])
    require(len(json.dumps(state,ensure_ascii=False).encode()) <= 20000, '请求状态过长，请新建对话。')
    state['last_executed_tasks']=changed
    if missing_relationships:
        state['pending_reason']='relationship';state['pending_tasks']=missing_relationships
        from relationship_request import clarification_question
        raise RequestAmbiguous(clarification_question(next(t for t in state['tasks'] if t['id']==missing_relationships[0])),state)
    if missing_domains:
        state['pending_reason']='domain';state['pending_tasks']=missing_domains
        raise RequestAmbiguous('请说明要介绍的对象属于PBS、构型、设备类还是部件类；已有对象标识与其他条件已保留，尚未查询。',state)
    if any(t['id'] in changed and t['unit']['state']=='ambiguous' and any(f['operator'] in NUMERIC_OPS for f in t['filters']) for t in state['tasks']):
        raise RequestAmbiguous('请明确数值条件的单位，例如摄氏度或华氏度；尚未执行查询。',state)
    plan = (plans[0]['intent'] if len(plans) == 1 else {'operation':'batch','entity':None,'scope':'direct','clarification':'','tasks':plans}) if plans else no_execution_plan()
    return plan, state, changed


def commit_state(context, trace, result, previous=None):
    """成功回执和未完成草稿分开提交；只完成本轮实际交付的任务。"""
    if (trace or {}).get('engine')=='relational_request':
        if result.get('relational_state'):context['relational_state']=copy.deepcopy(result['relational_state'])
        return context
    trace=trace or {};state=trace.get('business_request_state')
    success=result.get('status')=='ok' or (result.get('status')=='batch' and all(i.get('status')=='ok' for i in result.get('items',[])))
    pending=[]
    if state and trace.get('changed_tasks'):
        ids=trace['changed_tasks'];items=result.get('items',[]) if result.get('status')=='batch' else [result]
        by_id={t['id']:t for t in state['tasks']}
        # 新话题不能因任务编号恰好相同而继承上一组未完成任务。
        mode=(trace.get('business_request_delta') or {}).get('mode')
        old_draft=(previous or {}).get('pending_business_request') if mode!='new' else None
        pending=set((old_draft or {}).get('pending_tasks',(old_draft or {}).get('last_executed_tasks',[]))) & set(by_id)
        completed=set()
        for tid,item in zip(ids,items):
            expected='conversation' if by_id.get(tid,{}).get('operation') in NOTE_OPERATIONS else 'ok'
            if tid in by_id and item.get('status')==expected:completed.add(tid)
        pending=(pending-set(ids)) | (set(ids)-completed)
        pending=[t['id'] for t in state['tasks'] if t['id'] in pending]
        success=len(items)==len(ids) and len(completed)==len(ids)
    if state and success and not pending:
        confirmed=copy.deepcopy(state);confirmed.pop('pending_reason',None);confirmed.pop('pending_tasks',None)
        context['business_request']=confirmed;context.pop('pending_business_request',None)
    elif (state or trace.get('engine')=='business_request') and previous and previous.get('business_request'):
        context['business_request']=copy.deepcopy(previous['business_request'])
    elif success and trace.get('engine')=='legacy':
        # 迁移桥接层保存已执行的只读查询，不冒充模型语义核验。
        imported=import_receipt(result,trace.get('source_question',''),previous)
        if imported:context['business_request']=imported
    if result.get('status')=='clarify' and trace.get('pending_business_request'):
        context['pending_business_request']=copy.deepcopy(trace['pending_business_request'])
    elif state and pending and trace.get('engine')=='business_request':
        draft=copy.deepcopy(state);draft['pending_tasks']=pending
        draft['pending_reason']='object_resolution' if result.get('outcome') else (draft.get('pending_reason') or 'result_goal')
        context['pending_business_request']=draft
    elif success and not pending:
        context.pop('pending_business_request',None)
    pending_slot=trace.get('pending_slot')
    if result.get('status')=='clarify' and pending_slot:context['pending_slot']=copy.deepcopy(pending_slot)
    elif pending and (previous or {}).get('pending_slot',{}).get('task_id') in pending:
        context['pending_slot']=copy.deepcopy(previous['pending_slot'])
    elif success or result.get('outcome'):context.pop('pending_slot',None)
    return context


def import_receipt(result,question,previous=None):
    receipt=result.get('query_receipt') or {};query=receipt.get('query') or {}
    operation=receipt.get('operation')
    if operation not in ('search','attributes') or not query or receipt.get('requested_entity') or receipt.get('scope')!='direct' or set(query)!={'target','filters'}:return None
    props=result.get('requested_properties',[]) if operation=='attributes' else []
    revision=((previous or {}).get('business_request') or {}).get('revision',0)+1
    source={'kind':'executed_receipt','turn':revision,'quote':question[:500]}
    unit={'state':'none','value':''}
    filters=[]
    for i,f in enumerate(query['filters'],1):
        filters.append({**copy.deepcopy(f),'id':f'f{i}','source':source})
        if f['field']=='unit' and f['operator']=='equals':unit={'state':'specified','value':canonical_unit(f['value'])}
    task={'id':'t1','operation':operation,'target':query['target'],'scope':'direct','properties':copy.deepcopy(props),'filters':filters,'unit':unit,
          'sources':{key:source for key in ('operation','target','scope','properties','unit')}}
    if receipt.get('result_goal'):task['result_goal']=copy.deepcopy(receipt['result_goal'])
    try:compile_task(task)
    except (ValueError,TypeError,KeyError):return None
    return {'version':1,'revision':revision,'next_filter_id':len(filters)+1,'tasks':[task],'last_executed_tasks':['t1'],'origin':'executed_legacy_receipt'}
