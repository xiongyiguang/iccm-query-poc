"""针对有限数值条件分歧，通过边界反例辅助核验。

模型只看到原始条件片段和边界值，不看到候选方案或预期操作符。
程序只能选择已有的完整请求。"""
import json
import os
import time
import urllib.request
from pathlib import Path
from business_request import RequestInvalid
from typed_fields import decimal_value

ROOT=Path(__file__).resolve().parents[1]
SIDES={'gt':'lower','gte':'lower','lt':'upper','lte':'upper'}


def prepare(question,comparison,requests):
    """只有分歧全部属于同一数值上的 gt/gte 或 lt/lte 时才继续，否则返回 None。"""
    a,b=comparison['candidate'],comparison['independent']
    if len(a)!=len(b):return None
    items=[];vectors={'candidate':[],'independent':[]}
    def index(filters):
        out={}
        for field,op,value in filters:
            key=(field,SIDES.get(op,op),value)
            if key in out:return None
            out[key]=op
        return out
    for left,right in zip(a,b):
        if {k:v for k,v in left.items() if k!='filters'}!={k:v for k,v in right.items() if k!='filters'}:return None
        lf,rf=index(left['filters']),index(right['filters'])
        if lf is None or rf is None or lf.keys()!=rf.keys():return None
        for key,op in lf.items():
            other=rf[key]
            if op==other:continue
            field,side,value=key
            if {op,other} not in ({'gt','gte'},{'lt','lte'}):return None
            quotes=[]
            for source in ('candidate','independent'):
                task=next((t for t in requests[source] if t['id']==left['task_id']),None)
                if task is None:return None
                for f in task['filters']:
                    if f['field']==field and SIDES.get(f['operator'])==side and decimal_value(f['value'])==decimal_value(value):
                        quote=f.get('source',{}).get('quote')
                        if quote and quote in question:quotes.append(quote)
            if not quotes:return None
            items.append({'id':len(items)+1,'field':field,'boundary':side,'value':format(decimal_value(value),'f'),'quote':min(quotes,key=lambda q:(len(q),q))})
            vectors['candidate'].append(op in ('gte','lte'));vectors['independent'].append(other in ('gte','lte'))
    return {'boundaries':items,'vectors':vectors} if items else None


def select(prepared,answer,question):
    if not isinstance(answer,dict) or set(answer)!={'decisions'} or not isinstance(answer['decisions'],list):raise RequestInvalid('端点核验结构无效。')
    expected={item['id']:item for item in prepared['boundaries']};actual={}
    for row in answer['decisions']:
        if not isinstance(row,dict) or set(row)!={'id','included','source'}:raise RequestInvalid('端点核验字段无效。')
        i=row['id'];value=row['included'];quote=row['source']
        if type(i)!=int or i not in expected or i in actual:raise RequestInvalid('端点核验编号缺失或重复。')
        if value is not None and type(value)!=bool:raise RequestInvalid('端点核验只允许真、假或不确定。')
        if not isinstance(quote,str) or not quote or quote not in question:raise RequestInvalid('端点核验缺少原话依据。')
        actual[i]=value
    if actual.keys()!=expected.keys():raise RequestInvalid('端点核验未完整结束。')
    values=[actual[i] for i in expected]
    if any(v is None for v in values):return 'clarify'
    choices=[name for name,vector in prepared['vectors'].items() if vector==values]
    return choices[0] if len(choices)==1 else 'clarify'


def adjudicate(question,prepared,model):
    from model import NoRedirect,ENDPOINT
    payload={'question':question,'boundaries':prepared['boundaries']}
    body={'model':model,'messages':[{'role':'system','content':(ROOT/'prompts/system/endpoint-membership-v1.txt').read_text(encoding='utf-8')},{'role':'user','content':json.dumps(payload,ensure_ascii=False)}],
          'response_format':{'type':'json_object'},'thinking':{'type':'enabled'},'reasoning_effort':'low','max_tokens':4096,'stream':False}
    req=urllib.request.Request(ENDPOINT,data=json.dumps(body,ensure_ascii=False).encode(),headers={'Authorization':'Bearer '+os.environ.get('DEEPSEEK_API_KEY',''),'Content-Type':'application/json'},method='POST')
    start=time.monotonic()
    with urllib.request.build_opener(NoRedirect).open(req,timeout=30) as response:raw=json.load(response)
    reply=raw['choices'][0]
    if reply.get('finish_reason')!='stop':raise RequestInvalid('端点核验未完整结束；未执行。')
    answer=json.loads(reply['message']['content']);choice=select(prepared,answer,question)
    return {'choice':choice,'reason':'按原话核验争议端点是否包含；仅选择整份一致请求。' if choice!='clarify' else '两份请求的端点含义仍无法确定，请明确是否包含边界值。',
            'method':'endpoint_membership','input':payload,'answer':answer,'model':raw.get('model'),'thinking':'enabled','effort':'low','usage':raw.get('usage'),'seconds':round(time.monotonic()-start,3)}
