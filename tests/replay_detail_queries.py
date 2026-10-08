import json,uuid,urllib.request,urllib.error,sys
from pathlib import Path
u='http://127.0.0.1:8765';m=json.load(urllib.request.urlopen(u+'/api/meta'));out=[];sessions={}
cases=[
 ('original','哪些测点开启且已报警？','count',48),
 ('original','测量点名称11 的数值和阈值是多少?','threshold',1),
 ('original','它叫什么？','entity','XJ2ABC001MO.TMP.2ABC109MT.BBe'),
 ('standalone','测量点名称11的阈值和测量值是多少？','threshold',1),
 ('standalone','它的数值是多少？','point',1),
 ('code','XJ2ABC001MO.TMP.2ABC109MT.BBe的高1阈值是多少？','threshold',1),
 ('multi','XJ2ABC001PO.ZRs.2ABC003KA.UGb的数值和阈值是多少？','threshold',4),
 ('multi','只看源系统3的阈值','source',None),
 ('source','测量点名称11的数值、来源和时间是什么？','point',1),
 ('ambiguous','名称包含测量点名称1的测点，其阈值是多少？','clarify',None),
 ('missing','测点名称ZZTEST-NONE的数值和阈值是多少？','clarify',None),
 ('condition','测量点名称11中开关为关闭的记录，数值和阈值是多少？','empty',0),
 ('relationship','构型对象描述14477对应的设备类叫什么？','contains','设备类描述1860'),
 ('relationship','它有哪些直接部件？','count',51),
 ('batch','构型MOHB01有哪些直接部件？另外测量点名称11的数值和阈值是多少？','batch',None),
]
for group,q,kind,expected in cases:
 req=urllib.request.Request(u+'/api/query',data=json.dumps(dict(session=sessions.setdefault(group,str(uuid.uuid4())),question=q,trace=True)).encode(),headers={'Content-Type':'application/json','X-Demo-Token':m['token'],'Origin':u})
 try:r=json.load(urllib.request.urlopen(req,timeout=40))
 except urllib.error.HTTPError as e:r=json.load(e)
 passed=False
 if kind=='count':passed=r.get('status')=='ok' and r.get('total')==expected
 if kind=='threshold':passed=r.get('status')=='ok' and len(r.get('threshold_details',[]))==expected and r.get('total')==expected and (expected!=1 or r['metrics'][2]['value']=='6.69898987')
 if kind=='entity':passed=r.get('status')=='ok' and r.get('context',{}).get('entity',{}).get('code')==expected
 if kind=='point':passed=r.get('status')=='ok' and r.get('total')==expected and r['records'][0]['code']=='XJ2ABC001MO.TMP.2ABC109MT.BBe'
 if kind=='source':passed=r.get('status')=='ok' and len(r.get('threshold_details',[]))>0 and all(x['source']=='源系统3' for x in r['records'])
 if kind=='clarify':passed=r.get('status')=='clarify'
 if kind=='empty':passed=r.get('status')=='clarify' and r.get('total')==0
 if kind=='contains':passed=r.get('status')=='ok' and expected in r.get('answer','')
 if kind=='batch':passed=r.get('status')=='batch' and len(r.get('items',[]))==2 and r['items'][0].get('total')==51 and len(r['items'][1].get('threshold_details',[]))==1
 out.append(dict(question=q,kind=kind,expected=expected,passed=passed,response=r))
 print(json.dumps(dict(question=q,passed=passed,answer=r.get('answer'),error=r.get('error')),ensure_ascii=True),flush=True)
 Path(__file__).resolve().parents[1].joinpath('docs/.staging',sys.argv[1]).write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
 if len(out)==len(cases) or cases[len(out)][0]!=group:
  reset=urllib.request.Request(u+'/api/reset',data=json.dumps({'session':sessions[group]}).encode(),headers={'Content-Type':'application/json','X-Demo-Token':m['token'],'Origin':u})
  json.load(urllib.request.urlopen(reset,timeout=10))
print('PASSED',sum(x['passed'] for x in out),'/',len(out))
