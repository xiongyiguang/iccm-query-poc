"""关系语义候选与独立清单分别抽取，完整语义相同才允许执行。"""
import copy
import json
import os
import urllib.request
import threading
from pathlib import Path
from attributes import CATALOG
from relational_query import canonical, validate_plan

PROMPT=Path(__file__).resolve().parents[1]/'prompts/system/relational-request-v18.txt'

INDEPENDENT_PROMPT=PROMPT.with_name('relational-semantic-v14.txt')
ENTRY_TRACE=threading.local()

def required_relation(question,context):
    """目录里已实现的图分布/分类连接不能交旧模板统计路径。"""
    if __import__('re').search(r'差值|相减|相加|乘以|除以|比例|极值|按(?:测量值|阈值).*(?:排序|排名)',question):return False
    if __import__('re').search(r'如何判断|怎么判断|你是如何|解释.*依据|按[^，。；]*(?:测量时间|更新时间|插入时间|变化速率|预测值)[^，。；]*(?:排序|排名)|最早|最新|最小|最大',question):return False
    if context.get('relational_state') and __import__('re').fullmatch(r'\s*设备类(?:表|字典)?(?:呢)?[？?。]?\s*',question):return True
    graph_goal=__import__('re').search(r'下级|直属|直接(?:部件|设备|对象)|后代|现场部件|现场设备|真实父|精确关联|对应.*(?:构型|设备类|部件类)|所属.*(?:设备类|部件类)|原记录|原行',question)
    if graph_goal and (__import__('re').search(r'PBS|构型|设备类|部件类|源系统|完整编码',question) or context.get('relational_state')):return True
    patterns=(r'(?:按|部件)(?:对象类型|部件类|部件类别|类别|类型|来源|源系统|功能位置).*(?:分组|分布|统计|分别.*多少|各.*数量)',
              r'部件类别.*(?:数量|前[0-9一二三四五六])',r'设备类.*(?:现场设备|现场部件)',
              r'(?:现场设备|现场部件).*(?:设备类|部件类).*(?:分布|统计)',
              r'(?:原行|原记录|CSV行号).*(?:排序|升序|排列)',r'同码.*(?:原表|构型|字典)')
    if any(__import__('re').search(p,question) for p in patterns):return True
    if context.get('relational_state') and __import__('re').search(r'刚才|沿用|保留|仍|这些|其中|第一项|第二项|本组|完整编码',question):
        return bool(__import__('re').search(r'原行|原记录|明细|分组|分布|限定|来源|源系统|现场部件|现场设备|父记录|分类|报警',question))
    return False

def normalized(value):
    if not isinstance(value,dict) or type(value.get('handled')) is not bool:raise ValueError('关系语义路由格式无效。')
    if value['handled'] is False:
        if set(value)!={'handled'}:raise ValueError('未处理关系路由含额外槽位。')
        return value
    if set(value)!={'handled','tasks'}:raise ValueError('关系语义路由含未知字段。')
    plan=validate_plan({'operation':'relational','entity':None,'scope':'direct','clarification':'','relational_tasks':value['tasks']})
    return {'handled':True,'tasks':sorted(plan['relational_tasks'],key=lambda t:t['id'])}


def extract(question,context,key,model,record,_repair=False,_independent=False,_store=None):
    from model import NoRedirect,ENDPOINT
    # JSON响应格式的接口要求属于请求构造，不依赖某版业务Prompt
    # 恰好包含该标识；模型输出仍须经过同一个严格状态编译器。
    body={'model':model,'messages':[{'role':'system','content':'仅输出 JSON 对象。\n'+(INDEPENDENT_PROMPT if _independent else PROMPT).read_text()+'\n字段目录：'+json.dumps(CATALOG,ensure_ascii=False)},
        {'role':'user','content':json.dumps({'question':question,'previous':context.get('relational_state'),
            'registered_entry':{'required':bool(context.get('relational_required')),'scope':'程序已登记的只读图关联能力'},
            'condition_catalog':__import__('relational_state').condition_catalog(context),
            'old_context':{k:context[k] for k in ('entity','query','scope','operation','branches') if k in context},
            'executed_history':context.get('relational_history',[]),
            'pending_unexecuted_questions':context.get('relational_pending_questions') or ([context['relational_pending_question']] if context.get('relational_pending_question') else []),
            'review_fields':context.get('relational_review_fields'),
            'schema_error':context.get('relational_schema_error'),
            'registered_condition_values':context.get('relational_condition_values'),
            'reference_context':context.get('verified_references'),
            'relational_literal_references':context.get('relational_literal_references',[])},ensure_ascii=False)}],
        'temperature':0,'thinking':{'type':'disabled'},'response_format':{'type':'json_object'},'max_tokens':2600,'stream':False}
    request=urllib.request.Request(ENDPOINT,data=json.dumps(body,ensure_ascii=False).encode(),headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'},method='POST')
    with urllib.request.build_opener(NoRedirect).open(request,timeout=30) as response:raw=json.load(response)
    candidate=json.loads(raw['choices'][0]['message']['content'])
    record.update(model=raw.get('model'),response_id=raw.get('id'),usage=raw.get('usage'),extracted=copy.deepcopy(candidate))
    try:
        from relational_state import compile_delta,RelationalHandoff
        if not isinstance(candidate,dict):raise ValueError('关系变更输出必须为JSON对象。')
        from relational_delta_codec import normalize_delta
        adapted,adaptation=normalize_delta(candidate,question,context,_store)
        if candidate.get('handled') is True:
            answer,audit=compile_delta(adapted,question,context,_store)
            record['representation_adaptation']=adaptation
            record['state_compilation']=audit
        else:
            answer=normalized(adapted)
            if context.get('relational_required'):
                raise ValueError('当前目标属于已实现的真实图关联/分类分布/原行交付；按V2提取，不得交旧构型模板统计路径。分组数量降序和Top是分组显示，不是测量值数值排序。')
        if answer.get('handled'):
            answer,control=retain_unchanged_tasks(answer,question,context)
            if control:record['retained_task_control']=control
            ground(answer['tasks'],question,context,_store)
        return answer
    except RelationalHandoff as error:
        record['programmatic_handoff']=str(error)
        return {'handled':False}
    except ValueError as error:
        if not _repair:
            first=copy.deepcopy(record);record.clear()
            result=extract(question,{**context,'relational_schema_error':str(error)},key,model,record,True,_independent,_store)
            record['schema_repair']={'original':first,'error':str(error)}
            return result
        error.extraction_trace={'schema_failure':copy.deepcopy(record)}
        raise


def ground(tasks,question,context,store=None):
    """标识不能由模型补造；已执行关系身份也能成为明确追问根。"""
    previous=context.get('relational_state') or {};known=set()
    def visit(value):
        if isinstance(value,dict):
            for k,v in value.items():
                if k in ('value','code','name') and isinstance(v,str):known.add(v)
                visit(v)
        elif isinstance(value,list):
            for item in value:visit(item)
    visit(previous);visit(context.get('entity'));visit(context.get('query'));visit(context.get('verified_references'))
    visit(context.get('relational_history'))
    # 类别条件是已执行任务的组成部分，不能因为槽位键不是code
    # 而丢失其引用证明；未执行的模型草稿不进入此目录。
    for state in [previous]+[h.get('state',{}) for h in context.get('relational_history',[]) if isinstance(h,dict)]:
        for task in state.get('tasks',[]):
            for value in (task.get('spec') or {}).get('classes',{}).values():
                if isinstance(value,str):known.add(value)
    from identifier_aliases import complete_literal_pattern
    import re
    pending=context.get('relational_pending_questions') or ([context['relational_pending_question']] if context.get('relational_pending_question') else [])
    quotes=[question]+pending
    def mentioned(value):return value in known or any(re.search(complete_literal_pattern(value),text) for text in quotes)
    for t in tasks:
        q=t['spec']
        values=[(r['tree'],r['value'],False) for r in (q['root'],q['compare_root']) if r]+[(tree,value,True) for tree,value in q['classes'].items()]
        for tree,value,is_class in values:
            found=[]
            if store is not None:
                table='points' if tree=='points' else 'objects';clause='(code=? OR name=?)';params=[value,value]
                if table=='objects':clause='tree=? AND '+clause;params=[tree]+params
                found=store.rows('SELECT DISTINCT code,name FROM '+table+' WHERE '+clause,params)
                if is_class and not found:raise ValueError('分类引用必须使用完整登记编码或名称；不能把名称编号截为编码。未找到的分类不能计算为零。')
            # 经唯一精确名称/编码查表证明同一身份的两个标识等价，
            # 不采用数值答案或字段条件结果来推断等价。
            proven=len({r['code'] for r in found})==1 and any(mentioned(r['code']) or mentioned(r['name']) for r in found)
            if not mentioned(value) and not proven:raise ValueError('关系标识缺少当前原话或已执行上下文依据。')


def bound_semantics(value,store):
    """只把唯一精确身份归一到同一个实际对象；不以相同结果等价筛选。"""
    value=copy.deepcopy(value)
    if not value.get('handled') or store is None:return value
    for task in value['tasks']:
        q=task['spec']
        for key in ('root','compare_root'):
            root=q[key]
            if not root:continue
            tree,field,literal=root['tree'],root['field'],root['value']
            table='points' if tree=='points' else 'objects'
            clause='(code=? OR name=?)' if field=='identity' else field+'=?'
            params=[literal,literal] if field=='identity' else [literal]
            if table=='objects':clause='tree=? AND '+clause;params=[tree]+params
            matches=store.rows('SELECT code'+(',line' if table=='points' else '')+' FROM '+table+' WHERE '+clause,params)
            codes={r['code'] for r in matches}
            if len(codes)==1:
                code=next(iter(codes))
                # 监测名称可能只定位同码的部分原行；唯一编码不等于
                # 原行集合相同，不能将名称条件扩成所有同码来源。
                complete=table!='points' or {r['line'] for r in matches}=={r['line'] for r in store.rows('SELECT line FROM points WHERE code=?',[code])}
                if complete:q[key]={'tree':tree,'field':'code','value':code}
        for tree,literal in q['classes'].items():
            codes={r['code'] for r in store.rows('SELECT code FROM objects WHERE tree=? AND (code=? OR name=?)',[tree,literal,literal])}
            if len(codes)==1:q['classes'][tree]=next(iter(codes))
        root=q['root']
        if q['kind']=='collection' and root and root['tree'] in ('equipment_class','part_class') and q['population'] in ('devices','parts','points'):
            tree,literal=root['tree'],root['value']
            if tree in q['classes'] and q['classes'][tree]!=literal:raise ValueError('实际分类锚与分类条件不一致，未替换范围。')
            q['classes']={**q['classes'],tree:literal};q['root']=None;q['depth']='all'
            task['spec']=canonical(q)
    # 同码说明来自已核对的原表身份，不是影响查询的条件。
    # 一项改根后，旧同码注释失效；不能让遗留注释拒绝另一项查询。
    relation=[t for t in value['tasks'] if t['spec']['kind']=='relation' and t['spec']['root']]
    if len(relation)>=2:
        for task in relation:
            q=task['spec'];root=q['root']
            proven=root['field']=='code' and any(other['spec']['root']['field']=='code' and
                other['spec']['root']['tree']!=root['tree'] and other['spec']['root']['value']==root['value'] for other in relation if other is not task)
            if proven:q['boundary']='same_record'
            elif q['boundary']=='same_record':q['boundary']=None
    return value


def retain_unchanged_tasks(value,question,context):
    """明确的任务保留约束由实际旧任务编译，不允许模型重解释旧根。"""
    import re
    previous={t['id']:t for t in (context.get('relational_state') or {}).get('tasks',[])}
    if len(previous)<2:return value,{}
    numbers={c:i for i,c in enumerate('一二三四',1)}
    text=re.sub(r'“[^”]*”|「[^」]*」|『[^』]*』|\"[^\"]*\"|`[^`]*`',lambda m:' '*len(m.group()),question)
    # 未加引号但明确作为名称/编码值的文本，同样不是任务控制指令。
    text=re.sub(r'(?:名字(?:叫|为)|名称(?:为|是)|名为|编码(?:为|是))[^，。；：:]*',lambda m:' '*len(m.group()),text)
    marker=r'(?:第([一二三四1-4])项|任务\s*([1-4])(?![0-9]))'
    def ident(m):
        raw=m.group(1) or m.group(2);return numbers.get(raw,int(raw) if raw.isdigit() else None)
    exclusive=[]
    for m in re.finditer(marker,text):
        before=text[max(0,m.start()-8):m.start()]
        if re.search(r'(?:只|仅)(?:修改|调整|变更)?\s*$',before):exclusive.append((ident(m),question[max(0,m.start()-8):m.end()]))
    ids={i for i,_ in exclusive}
    if len(ids)>1:raise ValueError('同时声明仅修改多个任务，任务修改范围不明确。')
    if ids and not ids<=set(previous):raise ValueError('指定的已有任务编号不存在。')
    protected=set(previous)-ids if ids else set()
    spans={i:quote for i,quote in exclusive}
    matches=list(re.finditer(marker,text))
    changes=r'增加|追加|改为|改成|改查|换成|更换|调整|重新|撤掉|撤销|去掉|取消|恢复|限定|只看|但|再'
    for n,m in enumerate(matches):
        tid=ident(m);end=matches[n+1].start() if n+1<len(matches) else len(text);part=text[m.end():end].strip(' ：:，,。；;')
        whole=(part.startswith('保持') or part.endswith('保持') or part.endswith('不变')) and not re.search(changes,part)
        if whole and tid in previous:protected.add(tid);spans[tid]=question[m.start():end]
    if not protected:return value,{}
    proposed={t['id']:t for t in value['tasks']}
    if ids and (not ids<=set(proposed) or set(proposed)-set(previous)):raise ValueError('仅修改已有任务时，必须交付指定任务且不得新增其他编号。')
    corrected=copy.deepcopy(value);replaced=[]
    for tid in sorted(protected):
        old={'id':tid,'spec':copy.deepcopy(previous[tid]['spec'])}
        if proposed.get(tid)!=old:replaced.append(tid)
        proposed[tid]=old
    corrected['tasks']=sorted(proposed.values(),key=lambda t:t['id'])
    return corrected,{'retained_ids':sorted(protected),'restored_ids':replaced,'literal_controls':spans,'source':'本轮明确保留/仅修改约束及实际旧任务目录'}


def remember_context(previous,current,question):
    """保存有限的实际执行目录，供跨轮引用；不把未执行草稿变成事实。"""
    history=copy.deepcopy(previous.get('relational_history',[]))
    state=current.get('relational_state')
    if state and (not history or history[-1]['state']!=state):
        history.append({'question':question,'state':copy.deepcopy(state)})
    if history:current['relational_history']=history[-6:]
    return current


def interpret(question,context,key,store=None):
    from model import MODEL
    context=copy.deepcopy(context)
    ENTRY_TRACE.value=None
    context['relational_required']=required_relation(question,context)
    if store is not None:
        from request_checklist import literal_references
        # 当前原话完整引用的跨树命中一并交给独立提取，不用旧根
        # 代替新编码，也不把候选计划当作目录依据。
        context['relational_literal_references']=literal_references(question,store)
        context['relational_condition_values']={field:[r['value'] for r in store.rows('SELECT DISTINCT '+column+' AS value FROM points WHERE '+column+"!='' ORDER BY "+column)] for field,column in [('source','system'),('switch','switch'),('status','status')]}
    if not context.get('relational_state') and (context.get('business_request') or context.get('pending_business_request')) and not context['relational_required'] and __import__('re').search(r'取消|撤销|撤掉|保留|仍|再限定|只看|这些|其余',question):
        ENTRY_TRACE.value={'reason':'existing_business_owner','basis':'实际普通查询任务持有旧条件；未引入新的图关联目标，本轮续改由该任务状态机处理'}
        return None
    candidate_trace={};candidate=extract(question,context,key,MODEL,candidate_trace,_store=store)
    if not candidate['handled']:
        ENTRY_TRACE.value={'reason':'main_not_handled','candidate':copy.deepcopy(candidate_trace)}
        return None
    # 单个精确测点的原字段投影交回既有属性入口，含关联查询后的追问。
    # 仅覆盖没有分类、筛选、分组或显示限制的标量投影；原入口仍独立核验。
    if len(candidate['tasks'])==1:
        q=candidate['tasks'][0]['spec']
        raw_tasks=(candidate_trace.get('extracted') or {}).get('tasks',[])
        raw_properties=(raw_tasks[0].get('spec') or raw_tasks[0].get('set') or {}).get('properties',[]) if len(raw_tasks)==1 else []
        # 原行号或显式原行排序属于记录交付，不能因为基础列在规范化
        # 时已归入默认输出，就误转成单对象属性而丢掉名称/原行。
        record_delivery='line' in raw_properties or q['sort'] not in ([],['pbs_part','code'])
        if (q['kind'] in ('relation','collection') and q['root'] and q['root']['tree']=='points'
                and q['properties'] and not record_delivery
                and not any(q[k] for k in ('classes','filters','group_by','limit','only','boundary'))):return None
    independent_trace={};independent=extract(question,context,key,os.environ.get('DEEPSEEK_CHECKLIST_MODEL','deepseek-v4-pro'),independent_trace,_independent=True,_store=store)
    # 独立核验确认范围有歧义时，整句交回既有入口重新抽取；
    # 不能执行关系候选，也不能把另一方候选提供给旧入口。
    if not independent['handled']:
        ENTRY_TRACE.value={'reason':'independent_not_handled','candidate':copy.deepcopy(candidate_trace),'independent':copy.deepcopy(independent_trace)}
        return None
    ground(candidate['tasks'],question,context,store);ground(independent['tasks'],question,context,store)
    candidate=bound_semantics(candidate,store);independent=bound_semantics(independent,store)
    attempts=[]
    if candidate!=independent:
        # 只传不一致槽位名称，不传另一方取值、计划或建议答案。
        # 最多重新独立抽取一对，第二对仍不一致就拒绝执行。
        attempts.append({'candidate':copy.deepcopy(candidate_trace),'independent':copy.deepcopy(independent_trace)})
        def diff(a,b,path=''):
            if type(a)!=type(b):return [path]
            if isinstance(a,dict):return [p for k in sorted(set(a)|set(b)) for p in diff(a.get(k),b.get(k),path+'.'+k)]
            if isinstance(a,list):
                if len(a)!=len(b):return [path+'.length']
                return [p for n,(x,y) in enumerate(zip(a,b)) for p in diff(x,y,path+'['+str(n)+']')]
            return [path] if a!=b else []
        context['relational_review_fields']=diff(candidate,independent)
        candidate_trace={};independent_trace={}
        candidate=extract(question,context,key,MODEL,candidate_trace,_store=store)
        independent=extract(question,context,key,os.environ.get('DEEPSEEK_CHECKLIST_MODEL','deepseek-v4-pro'),independent_trace,_independent=True,_store=store)
    if not independent.get('handled'):return None
    if candidate.get('handled'):ground(candidate['tasks'],question,context,store)
    ground(independent['tasks'],question,context,store)
    candidate=bound_semantics(candidate,store);independent=bound_semantics(independent,store)
    if candidate!=independent:
        error=ValueError('关系候选与独立语义清单不一致；未执行，完整范围仍待核验。')
        error.extraction_trace={'attempts':attempts,'candidate':candidate_trace,'independent':independent_trace}
        raise error
    if store is not None:
        for t in candidate['tasks']:
            for f in t['spec']['filters']:
                values=context['relational_condition_values'].get(f['field'],[])
                mentioned=[v for v in values if v in question]
                if f['operator']=='equals' and mentioned and f['value'] not in mentioned:
                    raise ValueError('完整字段值引用不一致；不能截短字段值后把未匹配当作零。')
    plan={'operation':'relational','entity':None,'scope':'direct','clarification':'','relational_tasks':candidate['tasks']}
    trace={'engine':'relational_request','source_question':question,'attempts':attempts,'candidate':candidate_trace,'independent':independent_trace,
           'previous_relational_state':copy.deepcopy(context.get('relational_state')),'validated_intent':copy.deepcopy(plan),
           'context_route':{'decision':{'needs_history':bool(context.get('relational_state'))}}}
    return plan,trace


def bind(store,question,plan,context,trace):
    from request_gateway import seal
    if trace.get('engine')!='relational_request' or trace.get('source_question')!=question or trace.get('validated_intent')!=plan:raise ValueError('关系计划在独立核验后改变，未执行。')
    from relational_state import compile_delta
    def compiled(raw):
        if raw.get('version')==2:
            from relational_delta_codec import normalize_delta
            return compile_delta(normalize_delta(raw,question,context or {},store)[0],question,context or {},store)[0]
        return normalized(raw)
    c=compiled(trace['candidate']['extracted']);i=compiled(trace['independent']['extracted'])
    c,_=retain_unchanged_tasks(c,question,context or {});i,_=retain_unchanged_tasks(i,question,context or {})
    ground(c['tasks'],question,context or {},store);ground(i['tasks'],question,context or {},store)
    c=bound_semantics(c,store);i=bound_semantics(i,store)
    if c!=i or c.get('tasks')!=plan['relational_tasks']:raise ValueError('关系清单核验不完整。')
    validate_plan(plan);seal(store,question,plan)
    trace['gateway']={'status':'verified','entry':'relational_request','independent_complete_match':True}
    return plan
