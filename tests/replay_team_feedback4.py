"""第四轮原连续问答回放；独立CSV判据不发送模型，只使用隔离本机服务。"""
import argparse, csv, hashlib, json, sys
from pathlib import Path
from replay_engine_comparison import Service, clean
from replay_customer_onsite import expand

ROOT=Path(__file__).resolve().parents[1]
GROUPS=[
 ('identity',['构型 MOHB01 是什么对象？','它有哪些直接部件？']),
 ('pending',['MOHB01#1 下面有哪些部件？','RRCB01 下面有哪些部件？','直接下级']),
 ('time',['测量时间为 1970/1/1 8:00 的测点有多少个？']),
 ('global',['构型树里一共有多少个对象？','直接下级','构型树里面有多少个对象代码？']),
 ('repeat',['构型 MOHB01 有哪些直接部件？','MOHB01#1 下面有哪些部件？','RRCB01 下面有哪些部件？','RRCB01 下有哪些直接部件？','RRCB01 下面有哪些部件？','RRCB01 下面有哪些部件？','RRCB01 下面有哪些部件？','MOHB01 对应的设备类是什么？']),
]

def cases():
 data=ROOT.parent/'中广核iCCM项目智能问数DEMO脱敏数据'
 with (data/'构型树.csv').open(encoding='gb18030',newline='') as f:config=list(csv.DictReader(f))
 with (data/'测量点数据分析.csv').open(encoding='gb18030',newline='') as f:points=list(csv.DictReader(f))
 expected={c:{'parts':len([r for r in config if r['父对象代码']==c and r['对象层级描述']=='部件']),
  'classes':len({r['所属部件类代码'] for r in config if r['父对象代码']==c and r['对象层级描述']=='部件'})} for c in ['MOHB01','MOHB01#1','RRCB01']}
 out=[]
 for group,questions in GROUPS:
  for n,q in enumerate(questions,1):
   e={}
   if group=='identity' and n==1:e={'kind':'identity','code':'MOHB01'}
   elif group=='identity':e={'kind':'parts','code':'MOHB01','depth':'direct',**expected['MOHB01']}
   elif group=='pending' and n<3:e={'kind':'parts_or_scope','code':'MOHB01#1' if n==1 else 'RRCB01',**expected['MOHB01#1' if n==1 else 'RRCB01']}
   elif group=='pending':e={'kind':'parts','code':'RRCB01','depth':'direct',**expected['RRCB01']}
   elif group=='time':e={'kind':'count','total':sum(r['测量时间']=='1970/1/1 8:00' for r in points)}
   elif group=='global':e={'kind':'scope_only'} if n==2 else {'kind':'count','total':len(config)}
   elif group=='repeat' and n<8:
    code='MOHB01' if n==1 else 'MOHB01#1' if n==2 else 'RRCB01';e={'kind':'parts','code':code,'depth':'direct',**expected[code]}
   else:e={'kind':'relation_or_domain','code':'MOHB01'}
   out.append({'id':f'{group}-{n}','group':group,'suite':'feedback4','question':q,'expected':e})
 return out

def grade(c,row):
 r=row['response'];e=c['expected'];answer=r.get('answer','');kind=e['kind'];checks={'http':row['http']==200}
 specs=[t['spec'] for t in r.get('context',{}).get('relational_state',{}).get('tasks',[])];spec=specs[0] if len(specs)==1 else {}
 if kind in ('parts','parts_or_scope'):
  if kind=='parts_or_scope' and r.get('status')=='clarify':
   checks['clarification']=bool(r.get('context',{}).get('pending_business_request') or r.get('context',{}).get('pending_question'))
  else:
   metrics={m['label']:m['value'] for m in r.get('metrics',[])}
   checks.update(status=r.get('status')=='ok',root=spec.get('root',{}).get('value')==e['code'],parts=metrics.get('原记录/对象数量')==e['parts'],classes=metrics.get('不同部件类')==e['classes'])
   if 'depth' in e:checks['depth']=spec.get('depth')==e['depth']
 elif kind=='count':checks.update(status=r.get('status')=='ok',count=str(e['total']) in answer.replace(',',''))
 elif kind=='identity':checks.update(status=r.get('status')=='ok',identity=(r.get('entity') or {}).get('code')==e['code'])
 elif kind=='scope_only':checks['safe']=r.get('status') in ('ok','clarify','conversation') and not r.get('outcome')
 elif kind=='relation_or_domain':checks['delivered']=r.get('status')=='ok' and e['code'] in answer or r.get('status')=='clarify' and any(x in answer for x in ('构型','设备类','对象域','哪种'))
 return {'passed':all(checks.values()),'checks':checks}

def main():
 p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);p.add_argument('--port',type=int,default=19274);a=p.parse_args();out=a.out.resolve();out.mkdir(parents=True,exist_ok=False)
 cs=cases();(out/'cases.json').write_text(json.dumps(cs,ensure_ascii=False,indent=2));rows=[]
 source={str(f.relative_to(ROOT)):hashlib.sha256(f.read_bytes()).hexdigest() for d in ('backend','frontend','prompts/system') for f in (ROOT/d).glob('*') if f.is_file()};(out/'source.json').write_text(json.dumps(source,indent=2))
 svc=Service('ordinary',out,a.port)
 def save():(out/'results.json').write_text(json.dumps({'rows':rows,'data_version':getattr(svc,'meta',{}).get('version')},ensure_ascii=False,indent=2))
 try:
  svc.start();group=None;sid=None
  for c in cs:
   if c['group']!=group:
    if sid:svc.call('/api/reset',{'session':sid})
    group=c['group'];sid,_=svc.new()
   row,_=svc.ask(sid,c)
   if row['http']==200:row['response']=clean(expand(svc,row['response'],sid))
   row.update(grade(c,row));rows.append(row);save();print(json.dumps({'id':c['id'],'passed':row['passed'],'checks':row['checks'],'answer':row['response'].get('answer',row['response'].get('error'))},ensure_ascii=False),flush=True)
 finally:svc.close();save()
 assert source=={n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in source},'实测期间源码变化'
 summary={'passed':sum(r['passed'] for r in rows),'total':len(cs),'attempted':len(rows),'closed':svc.process.poll() is not None};(out/'summary.json').write_text(json.dumps(summary,indent=2));print(summary,flush=True)
 return 0 if summary['passed']==summary['total'] else 1

if __name__=='__main__':sys.exit(main())
