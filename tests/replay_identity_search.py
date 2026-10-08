import json,urllib.request,uuid
from pathlib import Path
url='http://127.0.0.1:8765'
m=json.load(urllib.request.urlopen(url+'/api/meta'));out=[]
cases=[('包含 MOHB 的构型有哪些',792,'identity'),('MOHB 的构型有哪些',792,'identity'),('名称包含 MOHB 的构型有哪些',0,'name'),('编码包含 MOHB 的构型有哪些',792,'code'),('包含 构型对象描述14477 的构型有哪些',1,'identity'),('包含 TEST-NOT-EXIST-999 的构型有哪些',0,'identity')]
for q,total,field in cases:
 req=urllib.request.Request(url+'/api/query',data=json.dumps({'session':str(uuid.uuid4()),'question':q,'trace':True}).encode(),headers={'Content-Type':'application/json','X-Demo-Token':m['token'],'Origin':url})
 r=json.load(urllib.request.urlopen(req,timeout=35))
 filters=r.get('context',{}).get('query',{}).get('filters',[])
 ok=r.get('status')=='ok' and r.get('total')==total and any(f['field']==field for f in filters)
 out.append({'question':q,'expected_total':total,'expected_field':field,'passed':ok,'response':r})
 print(json.dumps({'question':q,'total':r.get('total'),'filters':filters,'passed':ok},ensure_ascii=True),flush=True)
 Path(__file__).resolve().parents[1].joinpath('docs/.staging/identity-search-live.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
assert all(x['passed'] for x in out)
