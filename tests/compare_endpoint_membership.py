"""有限范围的语义实验，不执行查询，也不读取候选方案。"""
import argparse,hashlib,json,os,sys,time,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'backend'))
from model import NoRedirect,ENDPOINT
OUT=ROOT/'docs/.staging/request-unification-20260924'

CASES=[
 ('帮我筛出读数至少50、但还不到80摄氏度的测点。上下界别都算进去。','还不到80摄氏度','upper','80',False),
 ('帮我筛出读数至少50、但还不到80摄氏度的测点。上下界别都算进去。','读数至少50','lower','50',True),
 ('我想要超过19，不多于33的值。','不多于33','upper','33',True),
 ('我想要超过19，不多于33的值。','超过19','lower','19',False),
 ('负6到负2，两端都不要。','负6到负2，两端都不要。','lower','-6',False),
 ('负6到负2，两端都不要。','负6到负2，两端都不要。','upper','-2',False),
 ('从5起到9止，包含5但不包含9。','包含5但不包含9','lower','5',True),
 ('从5起到9止，包含5但不包含9。','包含5但不包含9','upper','9',False),
 ('不低于0.07，最大不能超过0.09。','不低于0.07','lower','0.07',True),
 ('不低于0.07，最大不能超过0.09。','最大不能超过0.09','upper','0.09',True),
 ('下界15也不包括了，上界28保持包含。','下界15也不包括了','lower','15',False),
 ('上限还是44，只把这个端点改成可以等于。','只把这个端点改成可以等于','upper','44',True),
 ('读数须低于21，但又要求21本身包括，按这两项同时处理。','低于21，但又要求21本身包括','upper','21',None),
 ('数值从3到7，左闭右开。','左闭右开','lower','3',True),
 ('数值从3到7，左闭右开。','左闭右开','upper','7',False),
 ('不能比负12更低，负12本身可以。','不能比负12更低，负12本身可以','lower','-12',True),
]

def main():
 p=argparse.ArgumentParser();p.add_argument('--freeze',action='store_true');p.add_argument('--rounds',type=int,default=2);p.add_argument('--run',default='endpoint-membership-first');p.add_argument('--model',default='deepseek-v4-pro');p.add_argument('--thinking',choices=['enabled','disabled'],default='disabled');p.add_argument('--effort',default='low');a=p.parse_args()
 frozen=OUT/'frozen-endpoints.json'
 if a.freeze:
  assert not frozen.exists();raw=json.dumps([dict(id=i+1,question=q,quote=quote,boundary=b,value=v,expected=e) for i,(q,quote,b,v,e) in enumerate(CASES)],ensure_ascii=False,indent=2).encode();frozen.write_bytes(raw);frozen.with_suffix('.sha256').write_text(hashlib.sha256(raw).hexdigest(),encoding='ascii');print('Frozen',len(CASES));return
 raw=frozen.read_bytes();assert hashlib.sha256(raw).hexdigest()==frozen.with_suffix('.sha256').read_text();cases=json.loads(raw)
 out=OUT/(a.run+'.json');assert not out.exists();rows=[];prompt=(ROOT/'prompts/system/endpoint-membership-v1.txt').read_text(encoding='utf-8')
 for n in range(1,a.rounds+1):
  for c in cases:
   task={k:c[k] for k in ('id','quote','boundary','value')};body={'model':a.model,'messages':[{'role':'system','content':prompt},{'role':'user','content':json.dumps({'question':c['question'],'boundaries':[task]},ensure_ascii=False)}],'response_format':{'type':'json_object'},'thinking':{'type':a.thinking},'max_tokens':4096 if a.thinking=='enabled' else 512,'stream':False}
   if a.thinking=='enabled':body['reasoning_effort']=a.effort
   else:body['temperature']=0
   req=urllib.request.Request(ENDPOINT,data=json.dumps(body,ensure_ascii=False).encode(),headers={'Authorization':'Bearer '+os.environ['DEEPSEEK_API_KEY'],'Content-Type':'application/json'},method='POST');start=time.monotonic()
   with urllib.request.build_opener(NoRedirect).open(req,timeout=60) as response:reply=json.load(response)
   choice=reply['choices'][0];content=choice['message']['content'];answer=json.loads(content);d=answer.get('decisions',[{}])[0]
   passed=choice.get('finish_reason')=='stop' and d.get('id')==c['id'] and d.get('included') is c['expected'] and bool(d.get('source')) and (d['source'] in c['question'] or d['source'] in c['quote'])
   rows.append({**c,'round':n,'seconds':round(time.monotonic()-start,3),'passed':passed,'response':answer,'response_model':reply.get('model'),'usage':reply.get('usage')});out.write_text(json.dumps({'frozen_sha256':hashlib.sha256(raw).hexdigest(),'model':a.model,'thinking':a.thinking,'effort':a.effort if a.thinking=='enabled' else None,'results':rows},ensure_ascii=False,indent=2),encoding='utf-8');print(c['id'],n,passed,rows[-1]['seconds'],answer,flush=True)
 print('PASSED',sum(x['passed'] for x in rows),'/',len(rows))

if __name__=='__main__':main()
