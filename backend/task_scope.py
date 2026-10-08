"""实验性输出范围契约，不授权对象或筛选条件。"""
import json,os,time,urllib.request
from pathlib import Path
from attributes import CATALOG
from typed_fields import THRESHOLDS
from business_request import source_segments,RequestInvalid

KINDS={'read','search','analyze','equipment','equipment_class','part_class','parent','parts','measurements','alarms','relation_check','data_overview','explain','conversation','unsupported'}
def validate(answer,question):
    if not isinstance(answer,dict) or set(answer)!={'tasks'} or not isinstance(answer['tasks'],list) or not 1<=len(answer['tasks'])<=8:
        raise RequestInvalid('输出清单必须包含1至8项任务。')
    segments={x['id'] for x in source_segments(question)}
    for t in answer['tasks']:
        if not isinstance(t,dict) or set(t)!={'kind','properties','spans'} or t['kind'] not in KINDS:
            raise RequestInvalid('输出任务类别或结构非法。')
        props=t['properties'];spans=t['spans']
        if not isinstance(props,list) or any(not isinstance(x,str) or x not in CATALOG and x!='*' for x in props) or len(set(props))!=len(props):
            raise RequestInvalid('返回属性非法。')
        if (t['kind']=='read') != bool(props) or '*' in props and props!=['*']:
            raise RequestInvalid('只有读取任务携带完整返回属性。')
        if not isinstance(spans,list) or not spans or any(type(i)!=int or i not in segments for i in spans) or len(set(spans))!=len(spans):
            raise RequestInvalid('任务必须引用当前原话片段。')
    return answer

def extract(question,context=None):
    from model import ENDPOINT,NoRedirect
    prompt=(Path(__file__).resolve().parents[1]/'prompts/system/task-scope-v1.txt').read_text(encoding='utf-8')
    from request_checklist import business_catalog
    body={'model':os.environ.get('ICCM_SCOPE_MODEL','deepseek-v4-pro'),'messages':[
        {'role':'system','content':prompt+'\n字段与业务目录：'+json.dumps(business_catalog(),ensure_ascii=False)},
        {'role':'user','content':json.dumps({'question':question,'segments':source_segments(question),'prior':context or {}},ensure_ascii=False)}],
        'response_format':{'type':'json_object'},'thinking':{'type':'disabled'},'temperature':0,'max_tokens':1400,'stream':False}
    start=time.monotonic()
    req=urllib.request.Request(ENDPOINT,data=json.dumps(body,ensure_ascii=False).encode(),headers={'Authorization':'Bearer '+os.environ.get('DEEPSEEK_API_KEY',''),'Content-Type':'application/json'})
    with urllib.request.build_opener(NoRedirect).open(req,timeout=15) as r:envelope=json.load(r)
    choice=envelope['choices'][0];content=choice['message']['content']
    trace={'seconds':time.monotonic()-start,'model':envelope.get('model'),'usage':envelope.get('usage'),'raw_output':content}
    try:
        if choice.get('finish_reason')!='stop':raise RequestInvalid('输出清单未完整生成。')
        answer=validate(json.loads(content),question)
    except (ValueError,TypeError,KeyError) as e:
        e.extraction_trace=trace
        raise
    return answer,trace

def outputs(plan):
    if plan.get('operation')=='batch':
        return [s for item in plan['tasks'] for s in outputs(item['intent'])]
    op=plan['operation'];props=[]
    if op=='attributes':kind='read';props=plan['properties']
    elif op=='threshold':kind='read';props=plan.get('thresholds') or list(THRESHOLDS)
    elif op=='measurement':kind='read';props=['value','unit','source','time','physical_quantity']
    elif op=='object':kind='read';props=['name','code','type','level','parent']
    elif op=='duration':kind='read';props=['time']
    elif op in ('clarify','explain_result'):kind='explain'
    else:kind=op
    return [{'kind':kind,'properties':sorted(props)}]

def compare(answer,plan):
    wanted=[{'kind':t['kind'],'properties':sorted(t['properties'])} for t in answer['tasks']]
    actual=outputs(plan)
    def matches(w,a):
        return w==a or w['kind']=='unsupported' and a['kind'] in ('explain','conversation')
    # 对完整计划作一对一任务匹配，保留重复请求及精确投影。
    def assign(index,used):
        if index==len(actual):return len(used)==len(wanted)
        return any(assign(index+1,used|{i}) for i,w in enumerate(wanted) if i not in used and matches(w,actual[index]))
    return {'matches':assign(0,set()),'requested':wanted,'planned':actual}

def guard(question,plan,trace):
    """实验性执行前否决检查，不能编造或删除单个任务。"""
    from request_gateway import leaves,ordinary
    items=list(leaves(plan))
    if os.environ.get('ICCM_TASK_SCOPE_REVIEW','0')!='1' or all(ordinary(p) or p['operation'] in ('clarify','conversation','explain','explain_result') for p in items):
        return plan
    context={'references':trace.get('reference_context') or {},'business_request':trace.get('business_request_previous')}
    try:
        answer,evidence=extract(question,context)
        verdict=compare(answer,plan)
    except (ValueError,TypeError,KeyError,TimeoutError,urllib.error.URLError) as error:
        trace['task_scope']={'status':'failed','error_type':type(error).__name__,'error':str(error),'extraction':getattr(error,'extraction_trace',None)}
        raise RequestInvalid('请求输出范围核对未完成；未执行查询。') from None
    trace['task_scope']={'status':'accepted' if verdict['matches'] else 'rejected','extraction':evidence,**verdict}
    if verdict['matches']:return plan
    if all(t['kind']=='unsupported' for t in answer['tasks']):
        return {'operation':'conversation','entity':None,'scope':'direct','clarification':'','message':'这项要求超出现有导入数据和查询能力支持的范围，未执行或代为增加其他查询。'}
    return {'operation':'clarify','entity':None,'scope':'direct','clarification':'原请求与生成的查询输出不一致，已停止执行。请明确要读取的字段或分别列出要完成的任务；原条件仍保留。'}
