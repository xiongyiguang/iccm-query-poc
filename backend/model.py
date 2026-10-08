"""DeepSeek 官方接口的意图适配层；凭据只保存在进程环境中。"""
import json
import copy
import os
import socket
import threading
TRACE=threading.local()
def get_trace():
    return getattr(TRACE,"value",None)
import urllib.request
import urllib.error
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
LEGACY_SCHEMA=ROOT/'prompts/system/query-intent-v24.schema.json'
SCHEMA=ROOT/'prompts/system/query-intent-v26.schema.json'
PROMPT=ROOT/'prompts/system/query-intent-v26.txt'
MODEL=os.environ.get('DEEPSEEK_MODEL','deepseek-v4-flash')
ENDPOINT='https://api.deepseek.com/chat/completions'

class ModelUnavailable(RuntimeError):
    pass

class PlanInvalid(ModelUnavailable):
    """模型响应已完成但违反计划契约；这不等于模型服务不可用。"""
    pass

def prepare_plan(candidate):
    """仅在独立任务外层结构明确时，隔离子任务失败。"""
    plan=copy.deepcopy(candidate)
    if not isinstance(plan,dict) or plan.get('operation')!='batch':
        return validate(plan)
    # 空的可选槽位不携带约束；不能丢弃非空或未知字段。
    for field in ('query','analysis','properties','message'):
        if field in plan and plan[field] is None: plan.pop(field)
    tasks=plan.get('tasks')
    if (set(plan)!={'operation','entity','scope','clarification','tasks'} or
        plan['entity'] is not None or plan['scope']!='direct' or plan['clarification']!='' or
        not isinstance(tasks,list) or not 2<=len(tasks)<=4):
        raise PlanInvalid('无法确定多任务的完整范围，本次未执行查询。')
    for task in tasks:
        if (not isinstance(task,dict) or set(task)!={'question','intent'} or
            not isinstance(task['question'],str) or not 0<len(task['question'].strip())<=500 or
            not isinstance(task['intent'],dict) or task['intent'].get('operation')=='batch'):
            raise PlanInvalid('无法确定独立子任务边界，本次未执行查询。')
    for n,task in enumerate(tasks,1):
        try: task['intent']=validate(task['intent'])
        except ModelUnavailable as e:
            if get_trace() is not None:
                TRACE.value.setdefault('task_errors',[]).append({'task_number':n,'reason':str(e)})
            task['intent']={'operation':'clarify','entity':None,'scope':'direct',
                'clarification':'这一项未能生成符合查询约定的完整计划，未执行。其他独立问题继续处理；请单独重问这一项。'}
    return validate(plan)

def merge_review(candidate,reviewed):
    """以程序维护的编号锚定复核任务，不能靠文字描述判断任务身份。"""
    if not isinstance(candidate,dict) or candidate.get('operation')!='batch': return reviewed
    before=candidate.get('tasks');after=reviewed.get('tasks') if isinstance(reviewed,dict) else None
    if (not isinstance(before,list) or not isinstance(after,list) or
        set(reviewed)!={'tasks'} or len(before)!=len(after) or
        any(not isinstance(t,dict) or set(t)!={'task_number','intent'} or type(t['task_number']) is not int for t in after) or
        {t['task_number'] for t in after}!=set(range(1,len(before)+1))):
        raise PlanInvalid('复核未保留完整子任务编号，本次未执行查询。')
    by_id={t['task_number']:t['intent'] for t in after}
    merged=copy.deepcopy(candidate)
    for n,t in enumerate(merged['tasks'],1): t['intent']=by_id[n]
    return merged

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        return None

def status():
    ready=bool(os.environ.get('DEEPSEEK_API_KEY','').strip())
    return {'available':ready,'provider':'DeepSeek','model':MODEL,
            'message':f'DeepSeek · {MODEL} · 密钥已配置，连接待实测' if ready else 'DeepSeek 待配置密钥；可先体验引导查询'}

def validate(parsed):
    if isinstance(parsed,dict) and 'navigate' in parsed and (parsed.get('operation')!='parent' or type(parsed['navigate']) is not bool):
        raise ModelUnavailable('导航标识仅适用于父关系，且须为布尔值。')
    if isinstance(parsed,dict) and parsed.get('operation')=='batch':
        if set(parsed)-{'operation','entity','scope','clarification','tasks','query','message'} or parsed.get('entity') is not None or parsed.get('query') is not None or parsed.get('message') or parsed.get('scope')!='direct' or parsed.get('clarification')!='':
            raise ModelUnavailable('多任务计划结构无效。')
        tasks=parsed.get('tasks')
        if not isinstance(tasks,list) or not 2<=len(tasks)<=4: raise ModelUnavailable('多任务数量须为2至4项。')
        for task in tasks:
            if not isinstance(task,dict) or set(task)!={'question','intent'} or not isinstance(task['question'],str) or not 0<len(task['question'])<=500 or not isinstance(task['intent'],dict) or task['intent'].get('operation')=='batch': raise ModelUnavailable('子任务格式无效，不允许嵌套。')
            task['intent']=validate(task['intent'])
        # 同一主体的阈值响应已经包含其测量值。
        if len(tasks)==2 and {t['intent']['operation'] for t in tasks}=={'measurement','threshold'}:
            left,right=[{k:v for k,v in t['intent'].items() if k!='operation'} for t in tasks]
            if left==right:
                return next(t['intent'] for t in tasks if t['intent']['operation']=='threshold')
        if len(tasks)==2 and {t['intent']['operation'] for t in tasks}=={'attributes','threshold'}:
            attr=next(t['intent'] for t in tasks if t['intent']['operation']=='attributes')
            threshold=next(t['intent'] for t in tasks if t['intent']['operation']=='threshold')
            if attr.get('properties')==['value'] and all(attr.get(k)==threshold.get(k) for k in ('entity','scope','query')):
                return threshold
        return parsed
    if isinstance(parsed,dict) and 'tasks' in parsed: raise ModelUnavailable('单任务不能附带未执行的子任务。')
    schema=json.loads(SCHEMA.read_text(encoding='utf-8-sig'))
    valid=isinstance(parsed,dict) and set(schema['required'])<=set(parsed)<=set(schema['properties'])
    if valid:
        valid=(parsed['operation'] in schema['properties']['operation']['enum'] and
               parsed['scope'] in schema['properties']['scope']['enum'] and
               isinstance(parsed['clarification'],str))
    if valid and parsed['entity'] is not None:
        e=parsed['entity']
        valid=(isinstance(e,dict) and (set(e) in ({'tree','code'},{'tree','name'}) or set(e)=={'tree','identity'} and e['tree']=='config' and (parsed['operation']=='parts' or parsed['operation']=='search' and parsed.get('query')=={'target':'config','filters':[]})) and
               e['tree'] in ('pbs','config','equipment_class','part_class') and
               isinstance(e.get('code',e.get('name',e.get('identity'))),str) and 0<len(e.get('code',e.get('name',e.get('identity'))))<=300)
    if not valid:
        raise ModelUnavailable('模型输出结构不符合查询契约；未执行查询。')
    from typed_fields import validate_thresholds
    try:validate_thresholds(parsed)
    except ValueError as e:raise ModelUnavailable(str(e)) from None
    from relation_check import validate_subjects
    try:validate_subjects(parsed)
    except ValueError as e:raise ModelUnavailable(str(e)) from None
    from data_context import validate_topics
    try:validate_topics(parsed)
    except ValueError as e:raise ModelUnavailable(str(e)) from None
    from attributes import validate_properties
    try: validate_properties(parsed)
    except ValueError as e: raise ModelUnavailable(str(e)) from None
    if parsed['operation']=='explain_result':
        if parsed['entity'] is not None or set(parsed)-{'operation','entity','scope','clarification'}:raise ModelUnavailable('结果解释只能引用当前会话结果。')
        return parsed
    from query_filters import validate_query
    if parsed['operation']=='parts' and isinstance(parsed.get('query'),dict) and parsed['query'].get('target')=='parts' and parsed.get('analysis') is None:
        parsed={**parsed,'operation':'search'}
    if parsed['operation']=='analyze':
        from analytics import validate_analysis
        try: validate_analysis(parsed)
        except ValueError as e: raise ModelUnavailable(str(e)) from None
    elif parsed.get('analysis') is not None:
        raise ModelUnavailable('分析条件不能被普通查询丢弃。')
    if parsed['operation'] in ('search','analyze'):
        try: validate_query(parsed.get('query'))
        except ValueError as e: raise ModelUnavailable(str(e)) from None
    elif parsed['operation']=='attributes':
        if parsed.get('query') is not None:
            try: validate_query(parsed['query'])
            except ValueError as e: raise ModelUnavailable(str(e)) from None
        elif parsed['entity'] is None: raise ModelUnavailable('属性查询缺少对象定位。')
    elif parsed.get('query') is not None:
        from query_filters import validate_detail_query
        try: validate_detail_query(parsed['operation'],parsed['query'])
        except ValueError as e: raise ModelUnavailable(str(e)) from None
    if parsed['operation']=='data_overview' and (parsed['entity'] is not None or parsed.get('query') is not None or parsed.get('properties') is not None):
        raise ModelUnavailable('数据概览不接受对象筛选。')
    if parsed['operation']=='conversation':
        if parsed['entity'] is not None or not isinstance(parsed.get('message'),str) or not 0<len(parsed['message'].strip())<=1200: raise ModelUnavailable('对话回复结构无效。')
    elif parsed.get('message'): raise ModelUnavailable('数据查询不能附带未经查询的回答。')
    return parsed

def has_statistics(plan):
    if not isinstance(plan,dict): return False
    tasks=plan.get('tasks')
    return (plan.get('operation')=='analyze' or plan.get('analysis') is not None or
            isinstance(tasks,list) and any(has_statistics(t.get('intent')) for t in tasks if isinstance(t,dict)))

def review_statistics(question,payload,candidate,key):
    schema=json.loads(SCHEMA.read_text(encoding='utf-8-sig'))
    review_candidate=copy.deepcopy(candidate)
    batch_review=isinstance(candidate,dict) and candidate.get('operation')=='batch'
    if batch_review:
        tasks=candidate.get('tasks')
        if not isinstance(tasks,list) or not 2<=len(tasks)<=4 or any(not isinstance(t,dict) or set(t)!={'question','intent'} for t in tasks):
            raise PlanInvalid('无法确定复核任务边界，本次未执行查询。')
        review_candidate={'tasks':[{'task_number':n,**t} for n,t in enumerate(tasks,1)]}
        item={'type':'object','additionalProperties':False,'required':['task_number','intent'],
              'properties':{'task_number':{'type':'integer','minimum':1,'maximum':len(tasks)},
              'intent':schema['properties']['tasks']['items']['properties']['intent']}}
        schema={'type':'object','required':['tasks'],'additionalProperties':False,
                'properties':{'tasks':{'type':'array','minItems':len(tasks),'maxItems':len(tasks),'items':item}}}
    body={'model':MODEL,'messages':[
        {'role':'system','content':(ROOT/'prompts/system/statistics-review-v3.txt').read_text(encoding='utf-8')+'\n查询意图语义契约：'+PROMPT.read_text(encoding='utf-8-sig')+'\n本次复核专用输出结构（优先于主规划外壳格式）：'+json.dumps(schema,ensure_ascii=False)},
        {'role':'user','content':json.dumps({'question':question,'context':payload,'candidate':review_candidate},ensure_ascii=False)}],
        'response_format':{'type':'json_object'},'thinking':{'type':'disabled'},'temperature':0,'max_tokens':2048,'stream':False}
    req=urllib.request.Request(ENDPOINT,data=json.dumps(body,ensure_ascii=False).encode('utf-8'),headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'},method='POST')
    with urllib.request.build_opener(NoRedirect).open(req,timeout=20) as response: envelope=json.load(response)
    choice=envelope['choices'][0]
    if choice.get('finish_reason')!='stop': raise ModelUnavailable('统计语义复核未完整结束；未执行查询。')
    TRACE.value['statistics_review_raw']={'raw_output':choice.get('message',{}).get('content'),'finish_reason':choice.get('finish_reason')}
    reviewed=json.loads(choice['message']['content'])
    TRACE.value['statistics_review']={'candidate':candidate,'reviewed':reviewed,'response_model':envelope.get('model'),'usage':envelope.get('usage')}
    return merge_review(candidate,reviewed)

def review_comparison_disagreement(question,context,candidate,route,key):
    """对两组提取出的比较条件执行一次受限裁决，不自由生成新条件。"""
    from typed_fields import NUMERIC_OPS,decimal_value
    if candidate.get('operation')!='search':return candidate,route
    filters=(candidate.get('query') or {}).get('filters',[])
    proposed=[f for f in filters if f.get('operator') in NUMERIC_OPS]
    expected=route.get('comparisons') or []
    def values(xs):return sorted((f['field'],decimal_value(f['value'])) for f in xs)
    def signatures(xs):return sorted((f['field'],f['operator'],decimal_value(f['value'])) for f in xs)
    if not proposed or not expected or signatures(proposed)==signatures(expected):return candidate,route
    payload={'question':question,'dialogue':context.get('dialogue',[]),'route':expected,'plan':proposed}
    body={'model':MODEL,'messages':[
        {'role':'system','content':(ROOT/'prompts/system/comparison-review-v1.txt').read_text(encoding='utf-8')},
        {'role':'user','content':json.dumps(payload,ensure_ascii=False)}],
        'response_format':{'type':'json_object'},'thinking':{'type':'disabled'},'temperature':0,'max_tokens':256,'stream':False}
    req=urllib.request.Request(ENDPOINT,data=json.dumps(body,ensure_ascii=False).encode(),headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'},method='POST')
    with urllib.request.build_opener(NoRedirect).open(req,timeout=12) as response:envelope=json.load(response)
    choice=envelope['choices'][0]
    if choice.get('finish_reason')!='stop':raise PlanInvalid('比较条件复核未完整返回，未执行。')
    verdict=json.loads(choice['message']['content'])
    if not isinstance(verdict,dict) or set(verdict)!={'choice','source'} or verdict['choice'] not in ('route','plan','clarify') or not isinstance(verdict['source'],str):raise PlanInvalid('比较条件复核格式无效，未执行。')
    sources=[question]+[x.get('question','') for x in context.get('dialogue',[])]
    if verdict['choice']!='clarify' and (not verdict['source'] or not any(verdict['source'] in s for s in sources)):raise PlanInvalid('比较条件复核缺少原话依据，未执行。')
    if get_trace() is not None:TRACE.value['comparison_review']={'before':payload,'verdict':verdict,'response_model':envelope.get('model')}
    if verdict['choice']=='clarify':return {'operation':'clarify','entity':None,'scope':'direct','clarification':'请确认数值区间两端是否包含边界值；当前理解存在分歧，尚未执行。'},route
    selected=expected if verdict['choice']=='route' else proposed
    p=copy.deepcopy(candidate);d=copy.deepcopy(route)
    p['query']['filters']=[f for f in filters if f.get('operator') not in NUMERIC_OPS]+copy.deepcopy(selected)
    d['comparisons']=copy.deepcopy(selected)
    return p,d


def interpret(question,context,selection,store=None):
    from request_gateway import clear_verification
    clear_verification()
    TRACE.value=None
    context=dict(context)
    knowledge=context.pop('verified_knowledge',None)
    verified_schema=context.pop('verified_schema',None)
    verified_references=context.pop('verified_references',None)
    key=os.environ.get('DEEPSEEK_API_KEY','').strip()
    if not key:
        raise ModelUnavailable('DeepSeek 尚未配置 API 密钥。请在本机启动窗口配置；引导查询仍可使用。')
    route=None
    request_engine=os.environ.get('ICCM_REQUEST_ENGINE','contract')!='legacy'
    original_context=copy.deepcopy(context)
    request_base=original_context.get('pending_business_request') or original_context.get('business_request')
    from request_checklist import prefetch
    prefetch(question,request_base,verified_schema,verified_references)
    from business_request import extraction_context
    extraction_input=extraction_context(context) if request_engine else context
    if True:
        from attributes import CATALOG
        from typed_fields import NUMERIC_FIELDS
        route_catalog={k:CATALOG[k] for k in sorted(CATALOG)}
        route_prompt='context-scope-v22.txt' if request_engine else 'context-scope-v7.txt'
        from query_filters import POINT_FIELDS,POINT_RAW_FIELDS,OBJECT_FIELDS,OPERATORS
        from request_checklist import business_catalog,literal_references
        from business_request import source_segments
        route_input={'question':question,'segments':source_segments(question),'context':extraction_input,'selection':selection}
        if verified_references:route_input['reference_context']=verified_references
        if verified_schema:route_input.update(verified_schema)
        if store is not None:
            route_input['business_catalog']=business_catalog(store)
            route_input['literal_references']=literal_references(question,store)
        route_body={'model':MODEL,'messages':[
            {'role':'system','content':(ROOT/'prompts/system'/route_prompt).read_text(encoding='utf-8')+'\n完整属性目录（其中value/rate/prediction和阈值字段可数值比较）：'+json.dumps(route_catalog,ensure_ascii=False)+'\n筛选目录：'+json.dumps({'points':list({**POINT_FIELDS,**POINT_RAW_FIELDS}),'objects':list(OBJECT_FIELDS)+['identity'],'operators':sorted(OPERATORS)},ensure_ascii=False)},
            {'role':'user','content':json.dumps(route_input,ensure_ascii=False)}], 'response_format':{'type':'json_object'},'thinking':{'type':'disabled'},'temperature':0,'max_tokens':4096 if request_engine else 1536,'stream':False}
        route_req=urllib.request.Request(ENDPOINT,data=json.dumps(route_body,ensure_ascii=False).encode('utf-8'),headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'},method='POST')
        try:
            with urllib.request.build_opener(NoRedirect).open(route_req,timeout=8) as response: route_raw=json.load(response)
            TRACE.value={'stage':'context_route','context_route_raw':route_raw['choices'][0]['message']['content']}
            decision=json.loads(route_raw['choices'][0]['message']['content'])
            if request_engine:
                from business_request import unpack_route
                if route_raw['choices'][0].get('finish_reason')!='stop':raise ValueError('incomplete extraction')
            from request_contract import validate_route
            repairs=0
            try:
                if request_engine:decision=unpack_route(decision)
                validate_route(decision,strict=True)
            except (ValueError,TypeError):
                repair_body={**route_body,'messages':route_body['messages']+[{'role':'assistant','content':route_raw['choices'][0]['message']['content']},{'role':'user','content':'输出结构不合法。请根据原问题与字段目录修正字段和类型，保留完整语义；只输出符合当前完整字段约定的JSON，不生成数据答案。'}]}
                repair_req=urllib.request.Request(ENDPOINT,data=json.dumps(repair_body,ensure_ascii=False).encode(),headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'},method='POST')
                with urllib.request.build_opener(NoRedirect).open(repair_req,timeout=8) as response:route_raw=json.load(response)
                TRACE.value['route_repair_raw']=route_raw['choices'][0]['message']['content']
                decision=json.loads(route_raw['choices'][0]['message']['content'])
                if request_engine:decision=unpack_route(decision,normalize_inactive=True)
                validate_route(decision,strict=True);repairs=1
            resolved=decision.get('resolved_question')
            if resolved is not None and (not isinstance(resolved,str) or not 0<len(resolved)<=2000):raise ValueError('route question')
            from request_contract import scope_context,ground_unit,ground_domain
            extracted=copy.deepcopy(decision)
            decision,context,selection=scope_context(decision,context,selection)
            decision=ground_domain(decision,question)
            decision=ground_unit(decision,question,context)
            route={'decision':decision,'extracted':extracted,'response_model':route_raw.get('model'),'repairs':repairs}
        except urllib.error.HTTPError as e:
            descriptions={401:'密钥无效',402:'账户余额不足',429:'请求达到服务限额'}
            raise ModelUnavailable('DeepSeek '+descriptions.get(e.code,f'接口错误（HTTP {e.code}）')+'；未执行查询。') from None
        except (ValueError,KeyError,IndexError,TypeError,urllib.error.URLError,TimeoutError):
            raise ModelUnavailable('暂未完成上下文范围判断，请重试；原查询条件已保留。') from None
    # 实验限制：独立建议能够编译，并不证明它完整覆盖原问题；
    # 真实关系和依据回放曾出现回退。
    pending_typed=bool(original_context.get('pending_business_request') and route['decision'].get('needs_history'))
    if request_engine and (pending_typed or os.environ.get('ICCM_TYPED_ENTRY_RETRY','0')=='1') and route['extracted'].get('business_request') is None:
        from request_checklist import prefetched_ready
        if pending_typed or prefetched_ready(question,request_base,verified_references):
            initial_route=copy.deepcopy(route)
            # 以类型化提取替换自由生成旧协议计划的调用。
            # 不向提取器提供独立任务建议、候选筛选字段或模型答案。
            retry_body={**route_body,'messages':route_body['messages']+[{'role':'assistant','content':route_raw['choices'][0]['message']['content']},
                {'role':'user','content':'统一入口检查要求重新核对协议选择：请仅根据原话、既有任务和业务目录提取完整business_request。普通查询、构型下级descendants草稿补充、目录静态说明及明确不支持能力的回应都已支持类型化表达；后者是unsupported任务，不要求查询对象。已有待澄清草稿时，补充其缺少的业务条件并保留根对象和其他条件。不可生成自由执行计划或legacy槽位；若确实无法表达则本次不执行。不要追加用户未要求的任务。只输出原协议JSON。'}]}
            req=urllib.request.Request(ENDPOINT,data=json.dumps(retry_body,ensure_ascii=False).encode(),headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'},method='POST')
            try:
                with urllib.request.build_opener(NoRedirect).open(req,timeout=12) as response:route_raw=json.load(response)
                if route_raw['choices'][0].get('finish_reason')!='stop':raise ValueError('incomplete typed retry')
                decision=unpack_route(json.loads(route_raw['choices'][0]['message']['content']),normalize_inactive=True)
                if decision.get('business_request') is None:raise ValueError('typed route unresolved')
                validate_route(decision,strict=True);extracted=copy.deepcopy(decision)
                decision,context,selection=scope_context(decision,original_context,selection)
                route={'decision':decision,'extracted':extracted,'response_model':route_raw.get('model'),'repairs':0,
                       'typed_entry_retry':{'initial_route':initial_route,'independent_proposal_shared':False}}
                route_body=retry_body
            except (ValueError,KeyError,IndexError,TypeError,urllib.error.URLError,TimeoutError):
                raise PlanInvalid('完整任务的协议入口尚未核对一致；未执行，请明确本轮需要的结果。') from None
    if request_engine and route['extracted'].get('business_request') is not None:
        from business_request import apply_delta,RequestInvalid,RequestAmbiguous,resolve_delta_sources
        TRACE.value={'stage':'business_request_compilation','context_route':route,'request':route_body,'response_model':route_raw.get('model'),'engine':'business_request','business_request_delta':route['extracted']['business_request'],'business_request_previous':request_base}
        if route_raw['choices'][0].get('finish_reason')!='stop':raise PlanInvalid('业务请求提取未完整结束；未执行。')
        def compile_request(request):
            TRACE.value['business_request_extracted']=copy.deepcopy(request)
            request=resolve_delta_sources(request,question)
            TRACE.value['business_request_delta']=copy.deepcopy(request)
            plan,state,changed=apply_delta(request,request_base,question,verified_references)
            return validate(plan),state,changed
        try:
            plan,state,changed=compile_request(route['extracted']['business_request'])
            # 存在歧义的物理单位不能变成无单位约束的数值查询。
            if route['extracted'].get('unit',{}).get('state')=='ambiguous' and route['extracted'].get('comparisons'):
                return {'operation':'clarify','entity':None,'scope':'direct','clarification':'请明确数值条件的单位；尚未执行查询。'}
        except RequestAmbiguous as error:
            TRACE.value['pending_business_request']=error.state
            return {'operation':'clarify','entity':None,'scope':'direct','clarification':str(error)}
        except (RequestInvalid,ValueError,TypeError,KeyError) as error:
            TRACE.value['business_request_validation_error']=str(error)
            repair_body={**route_body,'messages':route_body['messages']+[{'role':'assistant','content':route_raw['choices'][0]['message']['content']},{'role':'user','content':'业务请求未通过确定性校验：'+str(error)+' 请按同一原话及任务状态重新提取business_request，保持所有未修改条件；set可直接填类型化值，其来源由task.spans引用segments编号统一记录。不能重写quote。只能修正请求结构，不得改用legacy或生成执行计划。仅输出JSON。'}]}
            req=urllib.request.Request(ENDPOINT,data=json.dumps(repair_body,ensure_ascii=False).encode(),headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'},method='POST')
            try:
                with urllib.request.build_opener(NoRedirect).open(req,timeout=12) as response:repaired=json.load(response)
                choice=repaired['choices'][0]
                if choice.get('finish_reason')!='stop':raise ValueError('incomplete repair')
                repaired_route=unpack_route(json.loads(choice['message']['content']),normalize_inactive=True)
                if repaired_route['business_request'] is None:raise ValueError('cannot fall back')
                TRACE.value['business_request_repair_raw']=choice['message']['content']
                TRACE.value['business_request_delta']=repaired_route['business_request']
                plan,state,changed=compile_request(repaired_route['business_request'])
            except RequestAmbiguous as error:
                TRACE.value['pending_business_request']=error.state
                return {'operation':'clarify','entity':None,'scope':'direct','clarification':str(error)}
            except (urllib.error.URLError,TimeoutError,ValueError,TypeError,KeyError) as error:raise PlanInvalid('请求变更未通过校验；原条件未修改。'+str(error)) from None
        TRACE.value.update(stage='complete',business_request_state=state,changed_tasks=changed,compiled_intent=copy.deepcopy(plan),validated_intent=plan)
        TRACE.value['reference_context']=verified_references
        return plan
    if request_engine and original_context.get('pending_business_request') and route['decision'].get('needs_history'):
        raise PlanInvalid('待澄清业务请求尚未补全，未退回旧查询；请明确草稿中的缺失条件。')
    from attributes import planner_catalog
    from analytics import planner_groups
    from query_filters import POINT_FIELDS,POINT_RAW_FIELDS,OBJECT_FIELDS,OPERATORS
    filters={'points':list({**POINT_FIELDS,**POINT_RAW_FIELDS}),'objects':list(OBJECT_FIELDS),'operators':sorted(OPERATORS),'identity':'名称或编码联合字段，适用于各目标','group_count':planner_groups()}
    reference_context={k:route['decision'].get(k) for k in ('reference','domain','identifier_field')}
    payload={'context':context,'selection':selection,'verified_knowledge':knowledge,'reference_context':reference_context}
    effective_question=(route['decision'].get('resolved_question') if route and route['decision']['needs_history'] and context.get('pending_question') else None) or question
    continuation=''
    if context.get('pending_question'):
        continuation='当前有未完成的澄清任务：将context.pending_question作为原始请求，将历史补充及本轮问题作为槽位补全或修改。先恢复完整请求再规划。原请求已经给出的对象标识不可遗忘；用户只补充对象树也足以用identity定位，不必追问名称还是编码。缺信息才继续澄清，不能把补充的树名当成被查询对象或概念。\n'
    body={'model':MODEL,'messages':[
        {'role':'system','content':continuation+PROMPT.read_text(encoding='utf-8-sig')+'\n属性目录：'+planner_catalog()+'\n当前可执行筛选字段目录（以此为准）：'+json.dumps(filters,ensure_ascii=False)+'\n输出JSON必须满足：'+LEGACY_SCHEMA.read_text(encoding='utf-8-sig')},
        {'role':'user','content':'任务状态与已核实数据（历史用于续接，本轮明确修改优先）：'+json.dumps(payload,ensure_ascii=False)+'\n当前待执行请求：'+json.dumps(effective_question,ensure_ascii=False)+'\n本轮原话（仅用于核对补充来源）：'+json.dumps(question,ensure_ascii=False)}],
        'response_format':{'type':'json_object'},'thinking':{'type':'disabled'},
        'max_tokens':2048,'stream':False,'temperature':0}
    req=urllib.request.Request(ENDPOINT,data=json.dumps(body,ensure_ascii=False).encode('utf-8'),
        headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'},method='POST')
    try:
        with urllib.request.build_opener(NoRedirect).open(req,timeout=20) as response:
            raw=response.read(262145)
        if len(raw)>262144: raise ModelUnavailable('模型响应过大；未执行查询。')
        envelope=json.loads(raw)
        choice=envelope['choices'][0]
        TRACE.value={'engine':'legacy','source_question':question,'context_route':route,'request':body,'response_model':envelope.get('model'),'raw_output':choice.get('message',{}).get('content'),'finish_reason':choice.get('finish_reason'),'usage':envelope.get('usage')}
        TRACE.value['business_request_previous']=request_base
        TRACE.value['reference_context']=verified_references
        if choice.get('finish_reason')!='stop':
            raise ModelUnavailable('模型输出未完整结束；未执行查询。')
        candidate=json.loads(choice['message']['content'])
        if has_statistics(candidate):
            TRACE.value['stage']='statistics_review'
            candidate=review_statistics(effective_question,payload,candidate,key)
        TRACE.value['stage']='contract_compilation'
        from request_contract import complete_contract,reconcile_reference
        TRACE.value['candidate_intent']=copy.deepcopy(candidate)
        candidate,route['decision']=review_comparison_disagreement(question,context,candidate,route['decision'],key)
        reconciled=reconcile_reference(route['decision'],candidate,question,context)
        if reconciled!=route['decision']:
            TRACE.value['reference_route_before_reconciliation']=copy.deepcopy(route['decision'])
            route['decision'],context,selection=scope_context(reconciled,context,selection)
            route['decision']=ground_unit(route['decision'],question,context)
        try:candidate=complete_contract(candidate,route['decision'],context,selection)
        except ValueError as e:raise PlanInvalid(str(e)) from None
        TRACE.value['compiled_intent']=copy.deepcopy(candidate)
        TRACE.value['stage']='plan_validation'
        try: parsed=prepare_plan(candidate)
        except ModelUnavailable as e: raise PlanInvalid(str(e)) from None
        if route and parsed['operation']=='search' and route['decision']['identifier_field']:
            identifiers=[f for f in parsed['query']['filters'] if f['field'] in ('name','code','identity')]
            if len(identifiers)==1:
                identifiers[0]['field']=route['decision']['identifier_field'] or 'identity'
                parsed=validate(parsed)
        if route and route['decision']['identifier_field'] and parsed['operation'] in ('attributes','object','measurement','threshold','equipment','equipment_class','part_class','parent'):
            field=route['decision']['identifier_field']
            query=parsed.get('query')
            if query:
                identifiers=[f for f in query['filters'] if f['field'] in ('name','code','identity')]
                if len(identifiers)==1:identifiers[0]['field']=field
            elif parsed.get('entity'):
                e=parsed['entity']
                from attributes import CATALOG
                point_detail=parsed['operation'] in ('measurement','threshold') or (parsed['operation']=='attributes' and any(p!='*' and set(CATALOG[p]['fields'])=={'points'} for p in parsed['properties']))
                target='points' if e['tree']=='pbs' and point_detail else e['tree']
                parsed={**parsed,'entity':None,'query':{'target':target,'filters':[{'field':field,'operator':'equals','value':e.get('name',e.get('code'))}]}}
            parsed=validate(parsed)
        from request_contract import enforce
        try:enforce(parsed,route['decision'] if route else {})
        except ValueError as e:raise PlanInvalid(str(e)) from None
        TRACE.value['validated_intent']=parsed
        TRACE.value['stage']='complete'
        return parsed
    except urllib.error.HTTPError as e:
        descriptions={401:'密钥无效',402:'账户余额不足',429:'请求达到服务限额'}
        raise ModelUnavailable('DeepSeek '+descriptions.get(e.code,f'接口错误（HTTP {e.code}）')+'；未执行查询。') from None
    except (TimeoutError,socket.timeout):
        raise ModelUnavailable('DeepSeek 在20秒保护时限内未返回；本次五秒性能目标未达标。') from None
    except urllib.error.URLError:
        raise ModelUnavailable('DeepSeek 网络连接失败；请检查本机网络。') from None
    except (ValueError,KeyError,IndexError,TypeError):
        raise ModelUnavailable('DeepSeek 未返回有效结构化意图；未执行查询。') from None


def bind_references(store,question,plan,context=None):
    from request_gateway import clear_verification,migrate,seal,validate_categories
    clear_verification()
    try:
        bound=_bind_references(store,question,plan)
        trace=get_trace()
        if trace is None:
            # 其他规划协议也必须经过同一按能力划分的执行入口。
            TRACE.value={'engine':'external_planner','source_question':question}
            trace=TRACE.value
            if context:
                trace['reference_context']=context.get('verified_references')
                trace['business_request_previous']=context.get('pending_business_request') or context.get('business_request')
        if trace.get('engine')!='business_request':
            from task_scope import guard
            bound=guard(question,bound,trace)
            bound=migrate(store,question,bound,trace)
        elif bound.get('operation')!='clarify':
            validate_categories(trace['business_request_state'],trace['changed_tasks'],store)
            trace['gateway']={'status':'verified','entry':'business_request'}
        bound=validate({**bound,'clarification':bound.get('clarification','')})
        trace['validated_intent']=bound
        seal(store,question,bound)
        return bound
    except (ValueError,TypeError,KeyError,IndexError) as error:
        if get_trace() is not None and hasattr(error,'extraction_trace'):
            TRACE.value['checklist_failure']=error.extraction_trace
        raise PlanInvalid(str(error)) from None
    except (urllib.error.URLError,TimeoutError) as error:
        if get_trace() is not None:TRACE.value['gateway_error']={'type':type(error).__name__,'reason':str(error)}
        raise PlanInvalid('独立语义核验未完成；未执行查询，请重试。') from None
    finally:
        from request_checklist import discard_extraction
        discard_extraction()


def _bind_references(store,question,plan):
    from reference_binding import diagnose,apply_repairs
    from request_contract import bind_subject_identity,bind_categorical_values
    if (get_trace() or {}).get('engine')=='business_request':
        if plan.get('operation')=='clarify':return plan
        # 在业务请求状态和可执行计划中同时绑定已知字面值。
        # 第二个模型不能自由改写已经编译的业务请求。
        from business_request import ground_identifiers,compile_selected,execution_quotes
        try:
            grounded=ground_identifiers(store,TRACE.value['business_request_state'],TRACE.value['changed_tasks'])
            plan=validate(compile_selected(grounded,TRACE.value['changed_tasks'],execution_quotes(TRACE.value['business_request_delta'])))
        except ValueError as error:raise PlanInvalid(str(error)) from None
        TRACE.value['business_request_state']=grounded;TRACE.value['validated_intent']=plan
        bound=bind_categorical_values(store,plan,question)
        if bound!=plan:
            TRACE.value['before_categorical_binding']=copy.deepcopy(plan)
            if bound.get('operation')!='clarify':
                children=[x['intent'] for x in bound['tasks']] if bound.get('operation')=='batch' else [bound]
                for task_id,child in zip(TRACE.value['changed_tasks'],children):
                    if not child.get('query'):continue
                    task=next(t for t in TRACE.value['business_request_state']['tasks'] if t['id']==task_id)
                    for stored,executed in zip(task['filters'],child['query']['filters']):
                        if stored['value']!=executed['value']:
                            stored['resolution']={'kind':'literal_data_value','before':stored['value']}
                            stored['value']=executed['value']
            TRACE.value['validated_intent']=bound
        if bound.get('operation')=='clarify':return bound
        from request_checklist import gate
        try:
            checked=gate(question,TRACE.value.get('business_request_previous'),TRACE.value['business_request_state'],TRACE.value['changed_tasks'],TRACE.value['business_request_delta']['mode'],store,reference_context=TRACE.value.get('reference_context'))
        except (urllib.error.URLError,TimeoutError,ValueError,TypeError,KeyError,IndexError) as error:
            TRACE.value['checklist_error']={'type':type(error).__name__,'reason':str(error)}
            if hasattr(error,'extraction_trace'):TRACE.value['checklist_failure']=error.extraction_trace
            raise PlanInvalid('独立条件核对未完成；未执行查询，请重试。') from None
        TRACE.value['checklist_review']={k:v for k,v in checked.items() if k not in ('plan','state','changed','delta')}
        if checked['decision']!='accept' or checked.get('needs_review'):
            if checked.get('pending_state'):TRACE.value['pending_business_request']=checked['pending_state']
            result={'operation':'clarify','entity':None,'scope':'direct','clarification':checked.get('reason','两份条件理解不一致，请明确要查询的条件。')+' 尚未执行查询，原条件已保留。'}
            TRACE.value['validated_intent']=result
            return result
        if checked['choice']=='independent':
            TRACE.value['before_checklist_reconciliation']={'delta':TRACE.value['business_request_delta'],'state':TRACE.value['business_request_state']}
            bound=validate(checked['plan'])
            TRACE.value.update(business_request_state=checked['state'],business_request_delta=checked['delta'],changed_tasks=checked['changed'],validated_intent=bound)
        return bound
    route=((get_trace() or {}).get('context_route') or {}).get('decision',{})
    # 普通属性请求必须保留其字面定位来源；
    # 若先把名称解析成编码，会在迁移校验前丢失原话证据。
    from request_gateway import normalize_entity_attributes
    plan=normalize_entity_attributes(store,plan,route)
    bound=bind_subject_identity(store,plan,route)
    if bound!=plan:
        if get_trace() is not None:
            TRACE.value['before_identity_binding']=plan
            TRACE.value['validated_intent']=bound
        plan=bound
    bound=bind_categorical_values(store,plan,question)
    if bound!=plan:
        if get_trace() is not None:
            TRACE.value['before_categorical_binding']=plan
            TRACE.value['validated_intent']=bound
        plan=bound
    issues=diagnose(store,plan,question)
    if not issues:return plan
    key=os.environ.get('DEEPSEEK_API_KEY','').strip()
    if not key:raise ModelUnavailable('引用核验需要已配置模型；未执行疑似截断的引用。')
    body={'model':MODEL,'messages':[
      {'role':'system','content':(ROOT/'prompts/system/reference-review-v1.txt').read_text(encoding='utf-8')},
      {'role':'user','content':json.dumps({'question':question,'plan':plan,'reference_issues':issues},ensure_ascii=False)}],
      'response_format':{'type':'json_object'},'thinking':{'type':'disabled'},'temperature':0,'max_tokens':256,'stream':False}
    req=urllib.request.Request(ENDPOINT,data=json.dumps(body,ensure_ascii=False).encode(),headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'},method='POST')
    try:
        with urllib.request.build_opener(NoRedirect).open(req,timeout=20) as response:envelope=json.load(response)
        choice=envelope['choices'][0]
        if get_trace() is not None:TRACE.value['reference_review_raw']={'issues':issues,'choice':choice}
        if choice.get('finish_reason')!='stop':raise ValueError('incomplete')
        review=json.loads(choice['message']['content']);fixed=validate(apply_repairs(plan,issues,review))
        if get_trace() is not None:
            TRACE.value['reference_review']={'issues':issues,'review':review,'response_model':envelope.get('model')}
            TRACE.value['validated_intent']=fixed
        return fixed
    except (urllib.error.URLError,TimeoutError,ValueError,KeyError,IndexError,TypeError) as error:
        if get_trace() is not None:TRACE.value['reference_review_error']={'type':type(error).__name__,'reason':str(error)}
        raise ModelUnavailable('对象引用核验未完成；未执行疑似截断的查询，请重试。') from None


def review_request_coverage(question,previous,state,changed,mode='update'):
    """仅对语义不符作否决，复核器不能生成或修改计划。"""
    from business_request import review_semantics
    key=os.environ.get('DEEPSEEK_API_KEY','').strip()
    body={'model':MODEL,'messages':[
        {'role':'system','content':(ROOT/'prompts/system/request-coverage-v3.txt').read_text(encoding='utf-8')},
        {'role':'user','content':json.dumps({'question':question,'change_mode':mode,'previous_request':previous if mode=='update' else None,'complete_request':state,'executing_task_ids':changed,'program_semantics':review_semantics(state,changed)},ensure_ascii=False)}],
        'response_format':{'type':'json_object'},'thinking':{'type':'disabled'},'temperature':0,'max_tokens':512,'stream':False}
    req=urllib.request.Request(ENDPOINT,data=json.dumps(body,ensure_ascii=False).encode(),headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'},method='POST')
    try:
        with urllib.request.build_opener(NoRedirect).open(req,timeout=12) as response:envelope=json.load(response)
        choice=envelope['choices'][0]
        if choice.get('finish_reason')!='stop':raise ValueError('incomplete coverage review')
        verdict=json.loads(choice['message']['content'])
        if not isinstance(verdict,dict) or set(verdict)!={'decision','issues'} or verdict['decision'] not in ('accept','clarify') or not isinstance(verdict['issues'],list) or len(verdict['issues'])>4:raise ValueError('coverage format')
        if (verdict['decision']=='accept')!= (not verdict['issues']):raise ValueError('coverage decision')
        for issue in verdict['issues']:
            if not isinstance(issue,dict) or set(issue)!={'kind','quote'} or issue['kind'] not in ('unit','logic','task','coverage') or not isinstance(issue['quote'],str) or not issue['quote'] or issue['quote'] not in question:raise ValueError('coverage source')
        return {**verdict,'response_model':envelope.get('model')}
    except (urllib.error.URLError,TimeoutError,ValueError,TypeError,KeyError) as error:raise PlanInvalid('请求语义覆盖核验未完成；未执行查询。'+type(error).__name__) from None
