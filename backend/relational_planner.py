"""关系语义候选与独立清单分别抽取，完整语义相同才允许执行。"""
import copy
import json
import os
import urllib.request
from pathlib import Path
from attributes import CATALOG
from relational_query import canonical, validate_plan

PROMPT=Path(__file__).resolve().parents[1]/'prompts/system/relational-request-v8.txt'

INDEPENDENT_PROMPT=PROMPT.with_name('relational-semantic-v3.txt')

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
    body={'model':model,'messages':[{'role':'system','content':(INDEPENDENT_PROMPT if _independent else PROMPT).read_text()+'\n字段目录：'+json.dumps(CATALOG,ensure_ascii=False)},
        {'role':'user','content':json.dumps({'question':question,'previous':context.get('relational_state'),
            'old_context':{k:context[k] for k in ('entity','query','scope','operation','branches') if k in context},
            'pending_unexecuted_questions':context.get('relational_pending_questions') or ([context['relational_pending_question']] if context.get('relational_pending_question') else []),
            'review_fields':context.get('relational_review_fields'),
            'schema_error':context.get('relational_schema_error'),
            'registered_condition_values':context.get('relational_condition_values'),
            'reference_context':context.get('verified_references')},ensure_ascii=False)}],
        'temperature':0,'thinking':{'type':'disabled'},'response_format':{'type':'json_object'},'max_tokens':2600,'stream':False}
    request=urllib.request.Request(ENDPOINT,data=json.dumps(body,ensure_ascii=False).encode(),headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'},method='POST')
    with urllib.request.build_opener(NoRedirect).open(request,timeout=14) as response:raw=json.load(response)
    candidate=json.loads(raw['choices'][0]['message']['content'])
    record.update(model=raw.get('model'),response_id=raw.get('id'),usage=raw.get('usage'),extracted=copy.deepcopy(candidate))
    try:
        answer=normalized(candidate)
        if answer.get('handled'):ground(answer['tasks'],question,context,_store)
        return answer
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
            codes={r['code'] for r in store.rows('SELECT code FROM '+table+' WHERE '+clause,params)}
            if len(codes)==1:q[key]={'tree':tree,'field':'code','value':next(iter(codes))}
        for tree,literal in q['classes'].items():
            codes={r['code'] for r in store.rows('SELECT code FROM objects WHERE tree=? AND (code=? OR name=?)',[tree,literal,literal])}
            if len(codes)==1:q['classes'][tree]=next(iter(codes))
    return value


def interpret(question,context,key,store=None):
    from model import MODEL
    context=copy.deepcopy(context)
    if store is not None:
        context['relational_condition_values']={field:[r['value'] for r in store.rows('SELECT DISTINCT '+column+' AS value FROM points WHERE '+column+"!='' ORDER BY "+column)] for field,column in [('source','system'),('switch','switch'),('status','status')]}
    candidate_trace={};candidate=extract(question,context,key,MODEL,candidate_trace,_store=store)
    if not candidate['handled']:return None
    # 单个精确测点的原字段投影交回既有属性入口，含关联查询后的追问。
    # 仅覆盖没有分类、筛选、分组或显示限制的标量投影；原入口仍独立核验。
    if len(candidate['tasks'])==1:
        q=candidate['tasks'][0]['spec']
        if (q['kind'] in ('relation','collection') and q['root'] and q['root']['tree']=='points'
                and q['properties'] and not any(q[k] for k in ('classes','filters','group_by','limit','only','boundary'))):return None
    independent_trace={};independent=extract(question,context,key,os.environ.get('DEEPSEEK_CHECKLIST_MODEL','deepseek-v4-pro'),independent_trace,_independent=True,_store=store)
    # 独立核验确认范围有歧义时，整句交回既有入口重新抽取；
    # 不能执行关系候选，也不能把另一方候选提供给旧入口。
    if not independent['handled']:return None
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
    c=normalized(trace['candidate']['extracted']);i=normalized(trace['independent']['extracted'])
    ground(c['tasks'],question,context or {},store);ground(i['tasks'],question,context or {},store)
    c=bound_semantics(c,store);i=bound_semantics(i,store)
    if c!=i or c.get('tasks')!=plan['relational_tasks']:raise ValueError('关系清单核验不完整。')
    validate_plan(plan);seal(store,question,plan)
    trace['gateway']={'status':'verified','entry':'relational_request','independent_complete_match':True}
    return plan
