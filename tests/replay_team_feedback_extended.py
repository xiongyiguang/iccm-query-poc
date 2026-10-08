"""冻结语义变体，执行三轮新会话测试并保留完整响应。"""
import argparse, json, time, uuid, urllib.request, urllib.error
from pathlib import Path

def entity(code):
 return lambda r:r.get('status')=='ok' and r.get('entity',{}).get('code')==code
def grouped(tree,total):
 return lambda r:r.get('status')=='ok' and r.get('query',{}).get('target')==tree and r.get('analysis',{}).get('group_by')=='level' and sum(x['cells'][2] for x in r['records'])==total
def attrs(*names):
 return lambda r:r.get('status')=='ok' and set(names)<={x['property'] for x in r.get('attributes',[])}
def rate(r):
 return any(x.get('value')=='-4.05E-10' and x.get('display_value')=='-0.000000000405' and any(e.get('fields',{}).get('变化速率')=='-4.05E-10' for e in x.get('evidence',[])) for x in r.get('attributes',[]))

# 元组依次为独立会话、原问句、不变量、断言条件及可选对象选择。
CASES=[
 ('clarify','介绍XXXX1','请求澄清来源',lambda r:r.get('status')=='clarify'),
 ('clarify','我说的是PBS里的那个','补充来源后恢复原对象介绍',entity('XJ3ABC002RR&RRGA02.Zaf.IDS')),
 ('interrupt','介绍XXXX1','请求澄清来源',lambda r:r.get('status')=='clarify'),
 ('interrupt','先不查这个了，构型树中MOHB01的名称是什么？','独立问题取消待澄清任务',entity('MOHB01')),
 ('groups','分别数一下PBS每个层级有多少对象','PBS分组总数16796',grouped('pbs',16796)),
 ('groups','同样的统计换成构型树','换树保留统计意图，总数24025',grouped('config',24025)),
 ('groups','再换成设备类','换设备类总数3748',grouped('equipment_class',3748)),
 ('groups','部件类也按层级来一份','换部件类总数1631',grouped('part_class',1631)),
 ('groups','另外，构型MOHB01叫什么名字？','独立详情不继承统计',entity('MOHB01')),
 ('id1','帮我看看构型树里的MOHB01是什么','字段中性定位',entity('MOHB01')),
 ('id2','构型对象编码为MOHB01，告诉我名称和类型','明确编码及两个属性',lambda r:entity('MOHB01')(r) and attrs('name','type')(r)),
 ('id3','只按名称精确查找构型MOHB01，不要按编码查','不得偷偷改成编码定位',lambda r:r.get('status')=='not_found'),
 ('id4','构型树里编码为ZZZ-NO-SUCH-20260923的对象叫什么','不存在不得编造',lambda r:r.get('status')=='not_found'),
 ('partial','查一下测点2ABC109MT的监测值','简写只返回候选且不泄露候选测量值',lambda r:r.get('status')=='ambiguous' and r.get('candidate_only') and all('value' not in x for x in r.get('records',[]))),
 ('partial','选这个，告诉我数值和单位','确认后恢复数值任务',lambda r:entity('XJ2ABC001MO.TMP.2ABC109MT.BBe')(r) and attrs('value','unit')(r),{'tree':'pbs','code':'XJ2ABC001MO.TMP.2ABC109MT.BBe'}),
 ('partial','它的变化速率呢？','已选对象后续属性',lambda r:entity('XJ2ABC001MO.TMP.2ABC109MT.BBe')(r) and attrs('rate')(r)),
 ('exact','查测点XJ2ABC001MO.TMP.2ABC109MT.BBe的监测值和单位','完整编码直接定位',lambda r:entity('XJ2ABC001MO.TMP.2ABC109MT.BBe')(r) and attrs('value','unit')(r)),
 ('rate1','测点XJ1ABC001PO.JVD.1ABC029MV.LBe_Y变化有多快？请给出变化速率','数值展示与原始证据一致',rate),
 ('rate2','读取XJ1ABC001PO.JVD.1ABC029MV.LBe_Y这个测点的变化速率','另一问法保留原值和小数显示',rate),
 ('isolation','它的变化速率呢？','新会话不能串入另一会话对象',lambda r:r.get('status')=='clarify'),
 ('cancel','介绍XXXX1','待澄清起点',lambda r:r.get('status')=='clarify'),
 ('cancel','不查了。请按层级统计所有PBS对象数量','取消旧任务转统计',grouped('pbs',16796)),
]

def main():
 p=argparse.ArgumentParser();p.add_argument('--url',default='http://127.0.0.1:8766');p.add_argument('--output-dir',required=True);p.add_argument('--rounds',type=int,default=3);args=p.parse_args()
 meta=json.load(urllib.request.urlopen(args.url+'/api/meta'));failed=0
 for n in range(1,args.rounds+1):
  prefix='extended-'+uuid.uuid4().hex; rows=[];dest=Path(args.output_dir)/f'extended-round-{n}.json'
  if dest.exists():raise RuntimeError(f'Preserve existing evidence: {dest}')
  for i,(group,q,expected,check,*selection) in enumerate(CASES,1):
   start=time.perf_counter();error=None
   try:
    req=urllib.request.Request(args.url+'/api/query',data=json.dumps({'session':prefix+'-'+group,'question':q,'trace':True,'selection':selection[0] if selection else None}).encode(),headers={'Content-Type':'application/json','X-Demo-Token':meta['token']})
    with urllib.request.urlopen(req,timeout=90) as response:r=json.load(response)
    passed=bool(check(r))
   except urllib.error.HTTPError as exc:
    r=json.load(exc);passed=False;error=f'HTTP {exc.code}'
   except Exception as exc:r={};passed=False;error=str(exc)
   row={'case':i,'session':prefix+'-'+group,'group':group,'question':q,'expected':expected,'passed':passed,'seconds':round(time.perf_counter()-start,2),'error':error,'response':r};rows.append(row)
   dest.write_text(json.dumps({'round':n,'model':meta.get('model'),'results':rows},ensure_ascii=False,indent=2),encoding='utf-8')
   print(json.dumps({'round':n,'case':i,'passed':passed,'status':r.get('status'),'answer':r.get('answer'),'error':error},ensure_ascii=False),flush=True)
   failed+=not passed
 print(f'TOTAL {len(CASES)*args.rounds-failed}/{len(CASES)*args.rounds}',flush=True)
 return bool(failed)
if __name__=='__main__':raise SystemExit(main())
