"""真实 HTTP 和模型回归，由调用者提供回环测试服务及输出目录。"""
import argparse,json,time,urllib.request,urllib.error,uuid
from pathlib import Path

def main():
 p=argparse.ArgumentParser();p.add_argument('--url',default='http://127.0.0.1:8766');p.add_argument('--output',required=True);args=p.parse_args()
 meta=json.load(urllib.request.urlopen(args.url+'/api/meta'));results=[];prefix='replay-'+uuid.uuid4().hex[:8]
 def ask(group,question,check,selection=None):
  body={'session':prefix+'-'+group,'question':question,'trace':True,'selection':selection}
  req=urllib.request.Request(args.url+'/api/query',data=json.dumps(body).encode(),headers={'Content-Type':'application/json','X-Demo-Token':meta['token']})
  start=time.perf_counter()
  try:
   with urllib.request.urlopen(req,timeout=90) as response:r=json.load(response)
  except urllib.error.HTTPError as e:r=json.load(e)
  try:passed=bool(check(r))
  except (KeyError,TypeError,IndexError):passed=False
  results.append({'question':question,'group':group,'passed':passed,'seconds':round(time.perf_counter()-start,2),'response':r})
  Path(args.output).write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
  print(json.dumps({'question':question,'status':r.get('status'),'passed':passed,'answer':r.get('answer',r.get('error'))},ensure_ascii=False),flush=True)
  return r
 ask('context','介绍XXXX1',lambda r:r['status'] in ('clarify','ok'))
 ask('context','PBS',lambda r:r['status']=='ok' and r['entity']['code']=='XJ3ABC002RR&RRGA02.Zaf.IDS')
 ask('groups','按对象层级统计对象编码',lambda r:r['status']=='clarify')
 ask('groups','按PBS',lambda r:r['status']=='ok' and r['analysis']['group_by']=='level' and sum(x['cells'][2] for x in r['records'])==16796)
 ask('groups','改成构型树',lambda r:r['status']=='ok' and r['query']['target']=='config' and r['analysis']['group_by']=='level')
 ask('groups','构型 MOHB01 是什么对象？',lambda r:r['status']=='ok' and r['entity']['code']=='MOHB01')
 ask('partial','2ABC109MT 这个测点现在多少度？',lambda r:r['status']=='ambiguous' and r.get('candidate_only'))
 ask('partial','就这个，继续刚才的问题',lambda r:r['status']=='ok' and r['entity']['code']=='XJ2ABC001MO.TMP.2ABC109MT.BBe' and any(f['property']=='value' for f in r.get('attributes',[])),{'tree':'pbs','code':'XJ2ABC001MO.TMP.2ABC109MT.BBe'})
 ask('rate','查询测点 XJ1ABC001PO.JVD.1ABC029MV.LBe_Y 的变化速率',lambda r:any(f.get('display_value')=='-0.000000000405' for f in r.get('attributes',[])))
 ask('colloquial','构型对象 MOHB01 叫啥名，属于哪种对象？',lambda r:r['status']=='ok' and r['entity']['code']=='MOHB01' and {'name','type'}<={f['property'] for f in r.get('attributes',[])})
 ask('boundary','名称等于 MOHB01 的构型是什么对象？',lambda r:r['status']=='not_found')
 print(f"Passed {sum(x['passed'] for x in results)}/{len(results)}")
 return 0 if all(x['passed'] for x in results) else 1
if __name__=='__main__':raise SystemExit(main())
