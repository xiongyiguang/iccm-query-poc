import json,urllib.request,urllib.error,uuid,sys
from pathlib import Path
url='http://127.0.0.1:8765';m=json.load(urllib.request.urlopen(url+'/api/meta'));sid=str(uuid.uuid4());out=[]
for q in ['构型MOHB01有哪些直接部件？','什么名称 有什么告警','什么名称']:
 req=urllib.request.Request(url+'/api/query',data=json.dumps({'session':sid,'question':q,'trace':True}).encode(),headers={'Content-Type':'application/json','X-Demo-Token':m['token'],'Origin':url})
 try:r=json.load(urllib.request.urlopen(req,timeout=30))
 except urllib.error.HTTPError as e:r=json.load(e)
 out.append({'q':q,'response':r});print(json.dumps({'q':q,'status':r.get('status'),'answer':r.get('answer'),'context':r.get('context'),'intent':r.get('trace',{}).get('raw_output')},ensure_ascii=True),flush=True)
Path(__file__).resolve().parents[1].joinpath('docs/.staging',sys.argv[1]).write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
