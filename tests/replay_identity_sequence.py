import json,urllib.request,uuid,sys
from pathlib import Path
url='http://127.0.0.1:8765';m=json.load(urllib.request.urlopen(url+'/api/meta'));out=[]
for sequence in [
 ['名称包含 MOHB 的构型有哪些','MOHB 的构型有哪些','包含 MOHB 的构型有哪些','名称包含 MOHB 的构型有哪些'],
 ['编码包含 MOHB 的构型有哪些','名称包含 MOHB 的构型有哪些','MOHB 的构型有哪些','只查名称呢']]:
 sid=str(uuid.uuid4())
 for q in sequence:
  req=urllib.request.Request(url+'/api/query',data=json.dumps({'session':sid,'question':q,'trace':True}).encode(),headers={'Content-Type':'application/json','X-Demo-Token':m['token'],'Origin':url})
  r=json.load(urllib.request.urlopen(req,timeout=35));out.append({'q':q,'response':r})
  print(json.dumps({'q':q,'total':r.get('total'),'query':r.get('query'),'context':r.get('context')},ensure_ascii=True),flush=True)
  Path(__file__).resolve().parents[1].joinpath('docs/.staging',sys.argv[1]).write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
 req=urllib.request.Request(url+'/api/reset',data=json.dumps({'session':sid}).encode(),headers={'Content-Type':'application/json','X-Demo-Token':m['token'],'Origin':url})
 json.load(urllib.request.urlopen(req,timeout=10))
expected=[(0,'name'),(792,'identity'),(792,'identity'),(0,'name'),(792,'code'),(0,'name'),(792,'identity'),(0,'name')]
for item,(total,field) in zip(out,expected):
 r=item['response']
 assert r['status']=='ok' and r['total']==total,(item['q'],r['total'],total)
 assert r['query']==r['context']['query']
 assert r['query']['filters']==[{'field':field,'operator':'contains','value':'MOHB'}]
print('PASSED 8 / 8')
