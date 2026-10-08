import json, sys, uuid, urllib.request, urllib.error
from pathlib import Path

url='http://127.0.0.1:8765'
token=json.load(urllib.request.urlopen(url+'/api/meta'))['token']
out=[]
groups=[
 [('构型 MOHB 是什么对象？','object','MOHB'),('它的上级是什么？','parent','MOH')],
 [('构型 MOH 是什么对象？','object','MOH'),('它的上级是什么？','parent','MO')],
 [('构型 MO 是什么对象？','object','MO')],
 [('构型 AM 是什么对象？','object','AM')],
 [('MOHB 是什么对象？','object','MOHB')],
 [('包含 MOHB 的构型有哪些','search',792),('构型 MOHB 是什么对象？','object','MOHB')],
 [('MOHB 的构型有哪些','search',792)],
 [('构型 ZZTEST-NONE 是什么对象？','missing',None)],
]
def post(path,body):
 req=urllib.request.Request(url+path,data=json.dumps(body).encode(),headers={'Content-Type':'application/json','X-Demo-Token':token,'Origin':url})
 try: return json.load(urllib.request.urlopen(req,timeout=40))
 except urllib.error.HTTPError as error: return {**json.load(error),'http_status':error.code}
for cases in groups:
 sid=str(uuid.uuid4())
 try:
  for question,kind,expected in cases:
   r=post('/api/query',{'session':sid,'question':question,'trace':True})
   if kind=='object': ok=r.get('status')=='ok' and r.get('total')==1 and r['records'][0]['code']==expected and (r.get('context',{}).get('entity') or {}).get('code')==expected
   elif kind=='parent': ok=r.get('status')=='ok' and r.get('total')==1 and r['records'][0]['code']==expected
   elif kind=='search': ok=r.get('status')=='ok' and r.get('total')==expected and r.get('query',{}).get('filters')==[{'field':'identity','operator':'contains','value':'MOHB'}]
   else: ok=(r.get('status')=='clarify' and not r.get('total')) or (r.get('http_status')==400 and '未找到' in r.get('error',''))
   out.append({'question':question,'expected':expected,'passed':ok,'response':r})
   print(json.dumps({'question':question,'passed':ok,'answer':r.get('answer')},ensure_ascii=True),flush=True)
   (Path(__file__).resolve().parents[1]/'docs/.staging'/sys.argv[1]).write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
 finally: post('/api/reset',{'session':sid})
print('PASSED',sum(x['passed'] for x in out),'/',len(out))
assert all(x['passed'] for x in out)
