"""本机真实模型回放：未完成状态、任务分支、范围和分页恢复。需当轮授权。"""
from pathlib import Path
import argparse,csv,json,urllib.request,urllib.error,urllib.parse,uuid,time,hashlib
from decimal import Decimal,InvalidOperation
from datetime import datetime
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--url',required=True);parser.add_argument('--output-dir',required=True)
args=parser.parse_args();url=args.url.rstrip('/')
if urllib.parse.urlparse(url).hostname not in ('localhost','127.0.0.1'):parser.error('只允许本机隔离服务。')
root=Path(__file__).resolve().parents[1];out=Path(args.output_dir).resolve();out.mkdir(parents=True,exist_ok=False)
with (root.parent/'中广核iCCM项目智能问数DEMO脱敏数据/测量点数据分析.csv').open(encoding='gb18030') as f:raw=list(csv.DictReader(f))
with (root.parent/'中广核iCCM项目智能问数DEMO脱敏数据/pbs.csv').open(encoding='gb18030') as f:pbs=list(csv.DictReader(f))
meta=json.load(urllib.request.urlopen(url+'/api/meta'));entries=[]
def numeric(r):
 try:
  v=Decimal(r['测量值']);return v if v.is_finite() else None
 except InvalidOperation:return None
def ranked(rows,field,limit):
 valid=[r for r in rows if (numeric(r) is not None if field=='value' else bool(r['测量时间']))]
 valid.sort(key=lambda r:r['测量点编码'])
 valid.sort(key=(numeric if field=='value' else lambda r:datetime.strptime(r['测量时间'],'%Y/%m/%d %H:%M')),reverse=True)
 return [(r['测量点编码'],r['测量值'] if field=='value' else r['测量时间']) for r in valid[:limit]]
latest=ranked(raw,'time',2);max3=ranked(raw,'value',3);max100=ranked(raw,'value',100)
children={}
for r in pbs:children.setdefault(r['父对象代码'],[]).append(r['对象代码'])
rootcode='XJ2ABC002MO&MOHB01';desc={rootcode};todo=[rootcode]
while todo:
 for code in children.get(todo.pop(),[]):
  if code not in desc:desc.add(code);todo.append(code)
rootcount=sum(r['测量点编码'] in desc for r in raw)
y25=sum(r['测量时间'].startswith('2025/') for r in raw)
system1=sum(r['源系统']=='源系统1' for r in raw)
def case(q,kind,**kwargs):return {'question':q,'expect':{'kind':kind,**kwargs}}
groups={
'missing':[
 case('仅按原始数值，测量值为空的测点记录按测量值从高到低排序，取前3条','missing',pending=['t1'],tasks=1),
 case('取消测量值为空的条件，排序口径和数量不变','sort',field='value',limit=3,rows=max3)],
'partial':[
 case('分别统计2026年5月的测点记录数量；另外仅按原始数值，对测量值为空的测点记录按测量值从高到低排序取前3条','partial',pending=['t2'],tasks=2),
 case('第一项改为2025年的记录数量，第二项不变','count',total=y25,pending=['t2'],tasks=2),
 case('第二项取消测量值为空的条件，其他不变','sort',field='value',limit=3,rows=max3,tasks=2)],
'date-missing':[
 case('全部测点记录按测量时间从晚到早排序，取前2条','sort',field='time',limit=2,rows=latest),
 case('只看2027年5月的记录，排序方向和数量不变','missing',pending=['t1'],tasks=1),
 case('取消所有时间条件，其他不变','sort',field='time',limit=2,rows=latest)],
'filtered':[
 case('已报警的测点记录共有多少条','count',total=sum(r['状态']=='已报警' for r in raw)),
 case('取消报警状态条件，只看源系统1的记录，仍统计记录数量','count',total=system1)],
'point-root':[case('统计PBS对象XJ2ABC002MO&MOHB01自身及所有后代关联的测点记录，共有多少条','root',total=rootcount)],
'branches':[
 case('分别查询测量点名称6和测量点名称7的测量值','attributes-batch',values=[('测量点名称6','0.526000023'),('测量点名称7','1.973999977')]),
 case('第二项改查测量点名称11的测量值，第一项不变','attribute',name='测量点名称11',property='value',value='40.69898987',tasks=2),
 case('第一项改为只查测量点名称6的名称，第二项不变','attribute',name='测量点名称6',property='name',value='测量点名称6',tasks=2),
 case('第二项恢复测量点名称7的测量值，第一项不变','attribute',name='测量点名称7',property='value',value='1.973999977',tasks=2)],
'candidate-filter':[
 case('源系统1中，2ABC109MT这个测点的测量值是多少','candidate',pending=['t1'],tasks=1),
 {**case('就这个，继续刚才的问题','attribute',name='测量点名称11',property='value',value='40.69898987',source_filter=True),'selection':{'tree':'pbs','code':'XJ2ABC001MO.TMP.2ABC109MT.BBe'}}],
'latest-ties':[case('全部测点记录中，测量时间最新的记录都返回，保留全部并列','latest',total=2)],
'pagination':[
 case('全部测点记录仅按原始数值从高到低排序，返回前100条','sort',field='value',limit=100,rows=max100,resume=True),
 case('改成前3条，其他不变','sort',field='value',limit=3,rows=max3)]}
def post(path,body):
 req=urllib.request.Request(url+path,data=json.dumps(body).encode(),headers={'Content-Type':'application/json','Origin':url,'X-Demo-Token':meta['token']})
 try:
  with urllib.request.urlopen(req,timeout=150) as r:return r.status,json.load(r)
 except urllib.error.HTTPError as e:return e.code,json.load(e)
def state(r):return r.get('context',{}).get('pending_business_request') or r.get('context',{}).get('business_request') or {}
def facts(r,prop,value):return any(x.get('property')==prop and x.get('status')=='known' and str(x.get('value'))==value for x in r.get('attributes',[]))
def check(e):
 r=e['response'];x=e['expect'];kind=x['kind'];g=r.get('goal_receipt',{}).get('goal',{});s=state(r);pending=r.get('context',{}).get('pending_business_request',{}).get('pending_tasks',[])
 if e['http']!=200:return False
 if 'pending' in x and pending!=x['pending']:return False
 if 'pending' not in x and pending:return False
 if 'tasks' in x and len(s.get('tasks',[]))!=x['tasks']:return False
 if kind=='missing':return r.get('status')=='data_insufficient' and not r.get('goal_receipt',{}).get('completed') and s.get('tasks',[{}])[-1].get('result_goal',{}).get('kind')=='sort'
 if kind=='partial':
  items=r.get('items',[])
  return r.get('status')=='batch' and len(items)==2 and items[0].get('status')=='ok' and items[0].get('total')==829 and items[1].get('status')=='data_insufficient' and pending==['t2'] and len(s.get('tasks',[]))==2
 if kind=='sort':return r.get('status')=='ok' and g.get('kind')=='sort' and g.get('field')==x['field'] and g.get('direction')=='desc' and g.get('limit')==x['limit'] and r.get('total')==x['limit'] and [(z['code'],z[x['field']]) for z in r.get('records',[])]==x['rows'][:20]
 if kind=='count':return r.get('status')=='ok' and g.get('kind')=='count' and r.get('total')==x['total']
 if kind=='root':return r.get('status')=='ok' and r.get('total')==x['total'] and '自身及全部后代' in r.get('business_scope','') and '直接下级' not in r.get('business_scope','')
 if kind=='attribute':
  okay=r.get('status')=='ok' and facts(r,x['property'],x['value'])
  if x.get('source_filter'):okay=okay and any(f['field']=='source' and f['value']=='源系统1' for f in r.get('query_receipt',{}).get('query',{}).get('filters',[]))
  return okay
 if kind=='attributes-batch':return r.get('status')=='batch' and len(r.get('items',[]))==2 and all(i.get('status')=='ok' and facts(i,'value',value) for i,(_,value) in zip(r['items'],x['values']))
 if kind=='candidate':return r.get('status')=='ambiguous' and r.get('candidate_only') is True and any(z['code']=='XJ2ABC001MO.TMP.2ABC109MT.BBe' for z in r.get('records',[]))
 if kind=='latest':return r.get('status')=='ok' and r.get('total')==2 and g.get('kind')=='extreme' and g.get('direction')=='desc' and all(z['time']=='2026/9/4 17:46' for z in r.get('records',[]))
 raise ValueError(kind)
manifest={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for d in ('backend','frontend','prompts') for p in (root/d).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.name!='.DS_Store'}
(out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2));(out/'cases.json').write_text(json.dumps(groups,ensure_ascii=False,indent=2))
for group,cases in groups.items():
 sid='state-'+uuid.uuid4().hex
 try:
  for n,c in enumerate(cases,1):
   start=time.monotonic();http,r=post('/api/query',{'session':sid,'question':c['question'],'selection':c.get('selection'),'version':meta['version'],'trace':True});e={'id':group+'-'+str(n),**c,'http':http,'seconds':round(time.monotonic()-start,3),'response':r};e['passed']=check(e)
   if c['expect'].get('resume') and e['passed']:
    code,page=post('/api/page',{'session':sid,'result':r['result'],'page':1});e['pagination_passed']=code==200 and [(z['code'],z['value']) for z in page.get('records',[])]==max100[20:40];e['passed'] &= e['pagination_passed']
    post('/api/reset',{'session':sid});code,resume=post('/api/resume',{'session':sid,'continuation':r['continuation'],'version':meta['version']});e['resume_passed']=code==200 and state(resume).get('tasks',[{}])[0].get('result_goal',{}).get('limit')==100;e['passed'] &= e['resume_passed']
   entries.append(e);(out/'results.json').write_text(json.dumps({'version':meta['version'],'results':entries},ensure_ascii=False,indent=2));print(json.dumps({'id':e['id'],'passed':e['passed'],'seconds':e['seconds'],'http':http,'status':r.get('status'),'answer':r.get('answer',r.get('error'))},ensure_ascii=False),flush=True)
 finally:post('/api/reset',{'session':sid})
print('Passed',sum(x['passed'] for x in entries),'/',len(entries))
if not all(x['passed'] for x in entries):raise SystemExit(1)
