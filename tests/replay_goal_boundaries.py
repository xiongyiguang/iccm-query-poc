from pathlib import Path
import csv,json,urllib.request,urllib.error,urllib.parse,uuid,time,hashlib,sys
from datetime import datetime
from decimal import Decimal
# 本机真实模型回放，需单独授权；以原始CSV生成预期，不覆盖旧证据。
import argparse
parser=argparse.ArgumentParser(description='35项结果目标和连续对话边界回放，会调用目标服务配置的模型。')
parser.add_argument('--url',required=True);parser.add_argument('--output-dir',required=True)
args=parser.parse_args();url=args.url.rstrip('/')
if urllib.parse.urlparse(url).hostname not in ('127.0.0.1','localhost'):parser.error('本脚本仅允许本机隔离服务，不能直接用于腾讯云。')
root=Path(__file__).resolve().parents[1];out=Path(args.output_dir).resolve();out.mkdir(parents=True,exist_ok=False)
meta=json.load(urllib.request.urlopen(url+'/api/meta'))
raw=list(csv.DictReader((root.parent/'中广核iCCM项目智能问数DEMO脱敏数据/测量点数据分析.csv').open(encoding='gb18030')))
byname={r['测量点名称']:r for r in raw}
def date(row):
 try:return datetime.strptime(row['测量时间'],'%Y/%m/%d %H:%M')
 except ValueError:return None
may=[r for r in raw if date(r) and datetime(2026,5,1)<=date(r)<datetime(2026,6,1)]
year26=[r for r in raw if date(r) and date(r).year==2026];year25=[r for r in raw if date(r) and date(r).year==2025]
def ranked(rows,reverse,limit):
 ordered=sorted([r for r in rows if date(r)],key=lambda r:r['测量点编码']);ordered.sort(key=date,reverse=reverse)
 return [(r['测量点编码'],r['测量时间']) for r in ordered[:limit]]
def post(path,body):
 req=urllib.request.Request(url+path,data=json.dumps(body).encode(),headers={'Content-Type':'application/json','Origin':url,'X-Demo-Token':meta['token']})
 try:
  with urllib.request.urlopen(req,timeout=150) as res:return res.status,json.load(res)
 except urllib.error.HTTPError as err:return err.code,json.load(err)
def c(q,kind,**kw):return {'question':q,'expect':{'kind':kind,**kw}}
latest_time=max(date(x) for x in raw if date(x))
groups={
'ranking-transition':[
 c('全部测点记录按测量时间从早到晚排序，只返回前3条','sort',direction='asc',limit=3,rows=ranked(raw,False,3)),
 c('改为从晚到早，仍然只要3条','sort',direction='desc',limit=3,rows=ranked(raw,True,3)),
 c('不再排序，统计全部测点记录共有多少条','count',total=len(raw)),
 c('改为只统计2026年5月的测点记录条数','count',total=len(may)),
 c('把这些记录按测量时间从新到旧排序，只要前2条','sort',direction='desc',limit=2,rows=ranked(may,True,2))],
'calendar':[
 c('测量时间在2026年内的测点记录共有多少条','count',total=len(year26)),
 c('改为去年全年，统计测点记录条数','count',total=len(year25)),
 c('明确改为测量时间在2026年5月23日的记录，共多少条','count',total=sum(date(r) is not None and date(r).date()==datetime(2026,5,23).date() for r in raw)),
 c('改为2026年5月24日，其他不变','count',total=sum(date(r) is not None and date(r).date()==datetime(2026,5,24).date() for r in raw))],
'subject-transition':[
 c('查询测量点名称11的测量值','attribute',name='测量点名称11',property='value'),
 c('改查测量点名称6的测量值','attribute',name='测量点名称6',property='value'),
 c('名称','attribute',name='测量点名称6',property='name'),
 c('开始新问题，介绍构型树的MOHB','entity',tree='config',code='MOHB'),
 c('设备类呢','entity',tree='equipment_class',code='MOHB'),
 c('开始新问题，查询测量点名称7的测量值','attribute',name='测量点名称7',property='value')],
'difference-consent':[
 c('仅计算原始数值，测量点名称7减测量点名称6的测量值是多少','difference',value='1.447999954'),
 c('反过来，仅计算原始数值，测量点名称6减测量点名称7','difference',value='-1.447999954'),
 c('取消纯算术口径，按可比较的物理量判断这两个测点的测量差','refuse'),
 c('还是只计算原始数值，第一项减第二项','difference',value='-1.447999954')],
'zero-result':[
 c('名字包含ZXQ_NO_MATCH的测点记录有多少条','count',total=0),
 c('把这些记录按测量时间从新到旧排列','empty_compute'),
 c('新问题：全部测点记录里测量时间最晚的是哪些，保留并列','extreme',direction='desc',total=sum(date(r)==latest_time for r in raw))],
'raw-ranking':[
 c('所有已报警测点中，测量值最高的是哪个','refuse'),
 c('仅按原始数值比较，不认定物理量可比，取最高的全部并列记录','raw_extreme',direction='desc',value=max(Decimal(r['测量值']) for r in raw if r['状态']=='已报警' and r['测量值'])),
 c('取消仅按原始数值的口径，恢复按可比较的测量值找最高记录','refuse')],
'capability-negative':[
 c('仅按原始数值，测量点名称6和测量点名称7的绝对差是多少','difference',direction='absolute',value='1.447999954'),
 c('交换两点顺序，仅按原始数值，测量点名称7和测量点名称6的绝对差是多少','difference',direction='absolute',value='1.447999954'),
 c('把所有测点测量值求平均数','refuse'),
 c('根据现有测点数据预测明天设备是否故障','refuse')],
'unit-time-filter':[
 c('单位是摄氏度且测量时间在2026年5月的测点记录有多少条','count',total=sum(r['单位']=='℃' for r in may)),
 c('保留2026年5月条件，取消单位筛选，统计记录条数','count',total=len(may))],
'sort-projection':[
 c('测量点名称11的全部真实值报警阈值，按从低到高排序','threshold_sort',direction='asc',family='真实值'),
 c('不排序了，只读取高2阈值','attribute',name='测量点名称11',property='actual_high2'),
 c('改为所有报警阈值，按数值从高到低排序，只返回前2项','threshold_sort',direction='desc',family='all',limit=2)],
'unsupported-size':[c('全部测点按测量时间从晚到早排序，返回前101条','refuse')]
}
entries=[]
def check(e):
 r=e['response'];expect=e['expect'];kind=expect['kind'];g=(r.get('goal_receipt') or {}).get('goal',{});status=r.get('status');ok=e['http']==200
 if kind=='count':return ok and status=='ok' and g.get('kind')=='count' and r.get('total')==expect['total']
 if kind=='sort':return ok and status=='ok' and g.get('kind')=='sort' and g.get('direction')==expect['direction'] and g.get('limit')==expect['limit'] and [(x['code'],x['time']) for x in r.get('records',[])]==[tuple(x) for x in expect['rows']]
 if kind in ('extreme','raw_extreme'):
  return ok and status=='ok' and g.get('kind')=='extreme' and g.get('direction')==expect['direction'] and (r.get('total')==expect['total'] if 'total' in expect else g.get('basis')=='raw_numbers' and all(Decimal(x['value'])==Decimal(str(expect['value'])) for x in r.get('records',[])))
 if kind=='attribute':
  facts=[x for x in r.get('attributes',[]) if x.get('property')==expect['property']];src=byname[expect['name']];field={'value':'测量值','name':'测量点名称','actual_high2':'真实值报警阈值-高2'}[expect['property']]
  return ok and status=='ok' and g.get('kind')=='attributes' and r.get('entity',{}).get('code')==src['测量点编码'] and r.get('requested_properties')==[expect['property']] and len(facts)==1 and facts[0]['value']==src[field]
 if kind=='entity':return ok and status=='ok' and r.get('entity')=={'tree':expect['tree'],'code':expect['code']}
 if kind=='difference':return ok and status=='ok' and g.get('kind')=='difference' and g.get('direction')==expect.get('direction') and g.get('basis')=='raw_numbers' and r.get('metrics',[{}])[0].get('value')==expect['value'] and r.get('evidence_total')==2
 if kind=='empty_compute':return ok and status in ('data_insufficient','not_found') and not r.get('records') and not r.get('goal_receipt',{}).get('completed')
 if kind=='refuse':return (ok and status in ('clarify','conversation','data_insufficient') or e['http'] in (400,422)) and not r.get('goal_receipt',{}).get('completed') and not r.get('records')
 if kind=='threshold_sort':
  expected=[Decimal(v) for f,v in byname['测量点名称11'].items() if '报警阈值-' in f and v and (expect['family']=='all' or f.startswith(expect['family']))];expected.sort(reverse=expect['direction']=='desc');limit=expect.get('limit');expected=expected[:limit]
  facts=r.get('attributes',[]);known=[Decimal(x['value']) for x in facts if x['status']=='known']
  return ok and status=='ok' and g.get('kind')=='sort' and g.get('field')=='thresholds' and g.get('direction')==expect['direction'] and g.get('limit')==limit and known==expected and (len(facts)==limit if limit else len(facts)==6)
 raise ValueError(kind)
manifest={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for d in ('backend','frontend','prompts') for p in (root/d).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.name!='.DS_Store'}
(out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
(out/'cases.json').write_text(json.dumps(groups,ensure_ascii=False,indent=2,default=str))
for group,cases in groups.items():
 sid='expand-'+uuid.uuid4().hex
 try:
  for n,case in enumerate(cases,1):
   start=time.monotonic();http,r=post('/api/query',{'session':sid,'question':case['question'],'selection':None,'version':meta['version'],'trace':True})
   e={'id':group+'-'+str(n),**case,'http':http,'seconds':round(time.monotonic()-start,3),'response':r};e['passed']=check(e);entries.append(e)
   (out/'results.json').write_text(json.dumps({'version':meta['version'],'results':entries},ensure_ascii=False,indent=2,default=str))
   print(json.dumps({k:e[k] for k in ('id','http','seconds','passed')}|{'status':r.get('status'),'answer':r.get('answer',r.get('error',''))[:180]},ensure_ascii=False),flush=True)
 finally:post('/api/reset',{'session':sid})
print('Passed',sum(x['passed'] for x in entries),'/',len(entries),flush=True)

if not all(x["passed"] for x in entries):raise SystemExit(1)
