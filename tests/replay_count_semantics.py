import json,time,uuid,urllib.request,urllib.error,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
url='http://127.0.0.1:8765'
meta=json.load(urllib.request.urlopen(url+'/api/meta'));out=[];sessions={}
cases=[
 ('device','有多少设备','compare',[42,2205,3748]),
 ('device','其中PBS那组有多少？','single',('pbs',42,'设备')),
 ('device2','设备总共有几台？','compare',[42,2205,3748]),
 ('explicit1','有多少PBS设备对象？','single',('pbs',42,'设备')),
 ('explicit2','设备构型总数是多少？','single',('equipment',2205,None)),
 ('explicit3','设备类有多少？','single',('equipment_class',3748,None)),
 ('parts','有多少部件？','compare',[3614,18692,1631]),
 ('parts2','部件类总数是多少？','single',('part_class',1631,None)),
 ('points','有多少测点？','compare',[12904,12985]),
 ('records','测点数据记录有多少条，涉及多少不同编码？','points',[12985,12981]),
 ('alarms','有多少已报警记录？','alarm',False),
 ('alarms2','有多少开启且已报警记录？','alarm',True),
 ('normal','未报警的测点记录有多少？','single',('points',2312,None)),
 ('blank','状态未提供的测点记录有多少？','single',('points',10625,None)),
 ('config','构型树总共有多少对象？','single',('config',24025,None)),
 ('scoped','构型MOHB01是什么对象？','entity','MOHB01'),
 ('scoped','有多少部件？','parts',51),
 ('scoped','全部下级呢？','parts',221),
 ('scoped','全局设备类有多少？','single',('equipment_class',3748,None)),
 ('ambiguous','构型MOHB01有哪些直接部件？另外查询全部开启且已报警的测点。','compare',[51,48]),
 ('ambiguous','它叫什么？','clarify',None),
]
def check(r,kind,e):
 if kind=='compare':return r.get('status')=='batch' and sorted(x['total'] for x in r['items'])==sorted(e)
 if kind=='entity':return (r.get('context',{}).get('entity') or {}).get('code')==e
 if kind=='clarify':return r.get('status')=='clarify'
 if kind=='parts':return r.get('status')=='ok' and r.get('total')==e and (r.get('context',{}).get('entity') or {}).get('code')=='MOHB01'
 if r.get('status')!='ok':return False
 q=r.get('query',{});filters=q.get('filters',[])
 if kind=='single':
  return r.get('total')==e[1] and q.get('target')==e[0] and (e[2] is None or {'field':'level','operator':'equals','value':e[2]} in filters)
 if kind=='points':return [m['value'] for m in r.get('metrics',[])]==e
 if kind=='alarm':
  return r.get('total')==48 and q.get('target')=='points' and {'field':'status','operator':'equals','value':'已报警'} in filters and (any(f['field']=='switch' for f in filters)==e)
for group,q,kind,e in cases:
 t=time.monotonic();req=urllib.request.Request(url+'/api/query',data=json.dumps({'session':sessions.setdefault(group,str(uuid.uuid4())),'question':q,'trace':True}).encode(),headers={'Content-Type':'application/json','X-Demo-Token':meta['token'],'Origin':url})
 try:r=json.load(urllib.request.urlopen(req,timeout=40))
 except urllib.error.HTTPError as err:r=json.load(err)
 try:ok=check(r,kind,e)
 except (KeyError,TypeError):ok=False
 out.append(dict(question=q,kind=kind,expected=e,passed=ok,seconds=time.monotonic()-t,response=r))
 print(json.dumps({'q':q,'pass':ok,'answer':r.get('answer'),'error':r.get('error')},ensure_ascii=True),flush=True)
 (ROOT/'docs/.staging'/sys.argv[1]).write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
 if len(out)==len(cases) or cases[len(out)][0]!=group:
  reset=urllib.request.Request(url+'/api/reset',data=json.dumps({'session':sessions[group]}).encode(),headers={'Content-Type':'application/json','X-Demo-Token':meta['token'],'Origin':url})
  json.load(urllib.request.urlopen(reset,timeout=10))
print('PASSED',sum(x['passed'] for x in out),'/',len(out))
assert all(x['passed'] for x in out)
