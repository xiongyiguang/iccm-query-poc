"""真实模型和 HTTP 回归，独立核对用户所要求的语义。"""
import argparse,json,time,uuid,urllib.request,urllib.error,http.cookiejar
from pathlib import Path

def main():
 p=argparse.ArgumentParser();p.add_argument('--url',default='http://127.0.0.1:8768');p.add_argument('--output',required=True);p.add_argument('--rounds',type=int,default=3);p.add_argument('--cloud',action='store_true');p.add_argument('--holdout',action='store_true');args=p.parse_args()
 opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()));meta={};out=[];sessions=set()
 def call(path,body):
  headers={'Content-Type':'application/json','Origin':args.url}
  if meta:headers['X-Demo-Token']=meta['token']
  try:
   with opener.open(urllib.request.Request(args.url+path,data=json.dumps(body).encode(),headers=headers),timeout=90) as response:return json.load(response)
  except urllib.error.HTTPError as error:return json.load(error)
 if args.cloud:
  credentials={k.strip():v.strip() for line in (Path(__file__).resolve().parents[1]/'.local/cloud-8899-access.txt').read_text(encoding='utf-8-sig').splitlines() if ':' in line for k,v in [line.split(':',1)]}
  assert call('/api/auth/login',{'username':credentials['Username'],'password':credentials['Password']}).get('ok');credentials.clear()
 meta=json.load(opener.open(args.url+'/api/meta'))
 def ask(group,question,check,selection=None):
  sid=prefix+group;sessions.add(sid);start=time.perf_counter()
  r=call('/api/query',{'session':sid,'question':question,'selection':selection,'version':meta['version'],'trace':True})
  try:passed=bool(check(r))
  except (KeyError,TypeError,IndexError,ValueError):passed=False
  entry={'round':n+1,'group':group,'question':question,'passed':passed,'seconds':round(time.perf_counter()-start,3),'response':r};out.append(entry)
  Path(args.output).write_text(json.dumps({'version':meta['version'],'results':out},ensure_ascii=False,indent=2),encoding='utf-8')
  print(json.dumps({k:entry[k] for k in ['round','question','passed','seconds']},ensure_ascii=False),flush=True)
  if not passed:print(json.dumps({'answer':r.get('answer',r.get('error')),'plan':(r.get('trace') or {}).get('validated_intent')},ensure_ascii=False),flush=True)
  return r
 def threshold(r,key,value):return r['status']=='ok' and r.get('requested_thresholds')==[key] and list(r['threshold_details'][0]['thresholds'].values())==[value]
 try:
  for n in range(args.rounds):
   prefix='refactor-'+uuid.uuid4().hex[:10]+'-'
   if args.holdout:
    ask('typo','测量点名称11的高2阀值是多少',lambda r:threshold(r,'actual_high2','80'))
    ask('classword','设备类描述1860，帮我找它的编码',lambda r:r.get('entity')=={'tree':'equipment_class','code':'MOHB'})
    ask('lowword','查测量点名称4，真实值的低二档报警阈值',lambda r:threshold(r,'actual_low2','128'))
    ask('numericstatus','列出测量值超过60℃并且已经报警的测点',lambda r:r.get('total')==2 and all(x['state']=='已报警' for x in r['records']))
    ask('twolevels','测量点名称11的真实值高2和高3都给我',lambda r:set(r.get('requested_thresholds',[]))=={'actual_high2','actual_high3'} and '80' in r['answer'] and '90' in r['answer'])
    ask('missing','查测量点名称11的估计值高2，没填就说没填',lambda r:threshold(r,'estimate_high2','未提供'))
    continue
   ask('high2','测量点名称11 的高2阈值是多少?',lambda r:threshold(r,'actual_high2','80'))
   ask('class','设备类描述1860 对应哪个设备类?',lambda r:r['status']=='ok' and r['entity']=={'tree':'equipment_class','code':'MOHB'})
   ask('domain','MOHB 那个设备是什么?',lambda r:r['status']=='ambiguous' and {(x['tree'],x['code']) for x in r['records']}=={('config','MOHB'),('equipment_class','MOHB')})
   ask('domain','看设备类那条',lambda r:r['status']=='ok' and r['entity']=={'tree':'equipment_class','code':'MOHB'})
   ask('numeric','哪些点的测量值超过了60度',lambda r:r['status']=='clarify' or r['status']=='ok' and any(f['field']=='value' and f['operator']=='gt' and f['value']=='60' for f in r['query']['filters']))
   ask('numeric','单位是摄氏度',lambda r:r['status']=='ok' and any(f['field']=='value' and f['operator']=='gt' and f['value']=='60' for f in r['query']['filters']) and any(f['field']=='unit' and f['value']=='℃' for f in r['query']['filters']))
   ask('allthreshold','监测点XJ3ABC002MO.TMP.3ABC112MT.U_Win_H1的情况',lambda r:r['status']=='ok' and r['entity']['code']=='XJ3ABC002MO.TMP.3ABC112MT.U_Win_H1')
   ask('allthreshold','阈值是多少',lambda r:r['status']=='ok' and r['threshold_details'][0]['thresholds']['真实值报警阈值-低2']=='128' and '128' in r['answer'])
   ask('explain','构型 MOHB01 的直接部件有哪些',lambda r:r['status']=='ok' and r['entity']['code']=='MOHB01')
   ask('explain','你是如何判断它的下级部件的',lambda r:r['status']=='conversation' and 'MOHB01' in r['answer'] and ('父编码' in r['answer'] or '父引用' in r['answer']))
   ask('stats','哪些功能位置测点最多，前3',lambda r:r['status']=='ok' and r['analysis']['group_by']=='location' and len(r['records'])==3 and r['evidence_total']==12985 and r['timings_ms']['execution']<5000)
   # 未见过的改述使用同一份有原始依据的预期。
   ask('variant','查一下测量点名称11，真实值报警上限第三档是多少？',lambda r:threshold(r,'actual_high3','90'))
   ask('explicit','名称等于 MOHB01 的构型叫什么名字',lambda r:r['status'] in ('not_found','ambiguous') and r.get('entity') is None)
 finally:
  for sid in sessions:call('/api/reset',{'session':sid})
  if args.cloud:call('/api/auth/logout',{})
 print(f"Passed {sum(x['passed'] for x in out)}/{len(out)}",flush=True)
 return 0 if all(x['passed'] for x in out) else 1
if __name__=='__main__':raise SystemExit(main())
