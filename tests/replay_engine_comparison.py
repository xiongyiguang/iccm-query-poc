"""冻结版本下的真实双引擎对照；只改测试文件，不修改应用或重试挑分。"""
import argparse,copy,csv,hashlib,json,os,socket,statistics,subprocess,sys,time,urllib.request,urllib.error,uuid
from collections import OrderedDict,Counter
from datetime import datetime
from decimal import Decimal
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tests'))
import replay_zhou_originals as history


def clean(x):
 if isinstance(x,dict):return {k:clean(v) for k,v in x.items() if k not in ('token','continuation')}
 if isinstance(x,list):return [clean(v) for v in x]
 return x

class Service:
 def __init__(self,engine,out,port,agent_model=None):
  self.engine,self.out,self.port=engine,out,port;self.agent_model=agent_model;self.url=f'http://127.0.0.1:{port}';self.process=None;self.token='';self.groups=0;self.starts=[]
 def call(self,path,body=None):
  h={'Content-Type':'application/json','Origin':self.url}
  if self.token:h['X-Demo-Token' if self.engine=='ordinary' else 'X-Local-Token']=self.token
  req=urllib.request.Request(self.url+path,data=None if body is None else json.dumps(body,ensure_ascii=False).encode(),headers=h)
  try:
   with urllib.request.urlopen(req,timeout=200) as r:return r.status,json.load(r)
  except urllib.error.HTTPError as e:return e.code,json.load(e)
 def start(self):
  s=socket.socket();s.settimeout(.4);used=s.connect_ex(('127.0.0.1',self.port))==0;s.close()
  if used:raise RuntimeError('临时端口已占用，未启停占用服务')
  env=os.environ.copy();env['PYTHONDONTWRITEBYTECODE']='1'
  if self.engine=='ordinary':env.update(DEEPSEEK_API_KEY=(ROOT/'.local/deepseek-macos.key').read_text().strip(),ICCM_AUTH_REQUIRED='0')
  cmd=[sys.executable,'backend/app.py' if self.engine=='ordinary' else 'agent_demo/server.py','--port',str(self.port)]
  self.log=(self.out/(self.engine+f'-server-{len(self.starts)+1}.log')).open('w')
  self.process=subprocess.Popen(cmd,cwd=ROOT,env=env,stdout=self.log,stderr=self.log)
  start=time.monotonic()
  while time.monotonic()-start<65:
   if self.process.poll() is not None:raise RuntimeError('隔离服务启动失败，详见独立日志')
   try:
    code,meta=self.call('/api/meta')
    if code==200:
     self.token=meta['token'];self.meta=clean(meta);assert meta['version']=='70abf31549af'
     if self.engine=='agent':assert meta['ready']
     self.starts.append({'pid':self.process.pid,'meta':clean(meta),'startup_seconds':round(time.monotonic()-start,3)});self.groups=0;return
   except (OSError,urllib.error.URLError):pass
   time.sleep(.25)
  raise TimeoutError('隔离服务初始化超时')
 def close(self):
  if self.process and self.process.poll() is None:
   if self.engine=='agent':
    try:self.call('/api/shutdown',{})
    except Exception:pass
   else:self.process.terminate()
   try:self.process.wait(timeout=12)
   except subprocess.TimeoutExpired:self.process.terminate();self.process.wait(timeout=12)
  if hasattr(self,'log'):self.log.close()
 def new(self):
  if self.engine=='agent' and self.groups>=18:self.close();self.start()
  self.groups+=1;t=time.monotonic()
  if self.engine=='ordinary':return 'comparison-'+uuid.uuid4().hex,0
  code,x=self.call('/api/new',{'model':self.agent_model} if self.agent_model else {})
  if code!=200:raise RuntimeError(x.get('error','会话建立失败'))
  if self.agent_model and x.get('model')!=self.agent_model:raise RuntimeError('实际会话模型不符；停止测试，不接受自动替代')
  self.starts[-1].setdefault('created_models',[]).append(x.get('model'))
  return x['id'],round(time.monotonic()-t,3)
 def ask(self,sid,c,cursor=0):
  start=time.monotonic();row={'engine':self.engine,'suite':c['suite'],'id':c['id'],'question':c['question'],'group':c['group']}
  if self.engine=='ordinary':
   code,r=self.call('/api/query',{'session':sid,'question':c['question'],'selection':c.get('selection'),'version':self.meta['version'],'trace':True})
   row.update(http=code,response=clean(r),delivered_answer=r.get('answer',r.get('error','')),actual_question=c['question'])
  else:
   q=c['question']
   if c.get('selection'):
    q='我选择完整编码 '+c['selection']['code']+'。'+q;row['adaptation']='候选选择用完整编码文字表达，接口差异单独标记'
   row['actual_question']=q;code,ack=self.call('/api/ask',{'session':sid,'question':q});row['http']=code
   if code!=200:row.update(response=ack,delivered_answer=ack.get('error',''));row['seconds']=round(time.monotonic()-start,3);return row,cursor
   deadline=time.monotonic()+205
   while True:
    _,v=self.call('/api/events?session='+sid+'&after='+str(cursor))
    if not v.get('busy'):break
    if time.monotonic()>deadline:
     self.call('/api/stop',{'session':sid});row['timeout']=True;break
    time.sleep(.2)
   row['actual_model']=v.get('model');ev=v.get('events',[]);row['events']=clean(ev);cursor=ev[-1]['seq'] if ev else cursor
   row['delivered_answer']='\n'.join(e.get('text','') for e in ev if e['kind']=='message' and e.get('phase')!='commentary')
   receipts=[(e.get('tool'),e['result']) for e in ev if e['kind']=='tool_result' and e.get('tool') not in ('iccm_catalog','iccm_page')]
   if receipts:
    last=receipts[-1][1]
    delivered=receipts[-1:] if last.get('status') in ('clarify','ambiguous','not_found','error') else [x for x in receipts if x[0]!='iccm_find'] or receipts[-1:]
    row['delivery_receipts']=clean([x[1] for x in delivered]);row['response']=clean(last)
    if (c.get('expect') or {}).get('kind') in ('partial','attributes-batch') if isinstance(c.get('expect'),dict) else False:
     if last.get('status')!='batch' and len(delivered)>1:row['response']={'status':'batch','items':clean([x[1] for x in delivered]),'answer':row['delivered_answer']}
   else:row['response']={'status':'no_receipt','answer':row['delivered_answer']}
   row['errors']=[clean(e) for e in ev if e['kind'] in ('error','tool_error')]
   row['tool_calls']=sum(e['kind']=='tool_start' for e in ev)
   for k,kind in [('first_preparation_seconds','process'),('first_model_text_seconds','delta')]:
    found=next((e for e in ev if e['kind']==kind),None)
    if found:row[k]=round(found['time']-next((e['time'] for e in ev if e['kind']=='user'),found['time']),3)
  row['seconds']=round(time.monotonic()-start,3);return row,cursor

class Judge:
 def __init__(self):
  data=ROOT.parent/'中广核iCCM项目智能问数DEMO脱敏数据'
  self.raw=list(csv.DictReader((data/'测量点数据分析.csv').open(encoding='gb18030')))
  self.byname={r['测量点名称']:r for r in self.raw};self.hist=history.oracle()
  self.thresholds={k:v for k,v in self.byname['测量点名称11'].items() if '报警阈值-' in k};self.values=sorted([Decimal(v) for v in self.thresholds.values() if v],reverse=True)
  self.latest=sorted(self.raw,key=lambda r:r['测量点编码']);self.latest.sort(key=lambda r:datetime.strptime(r['测量时间'],'%Y/%m/%d %H:%M') if r['测量时间'] else datetime.min,reverse=True)
 def normalize(self,r):
  r=copy.deepcopy(r);rows=r.get('records',[])
  if r.get('match_type')=='candidates_only' or r.get('match_type')=='exact' and len(rows)>1:
   r.update(status='ambiguous',candidate_only=True)
  if r.get('match_type')=='exact' and len(rows)==1 and not r.get('entity'):
   r['entity']={k:rows[0][k] for k in ('tree','code') if k in rows[0]}
  if not r.get('query') and r.get('query_receipt',{}).get('query'):r['query']=r['query_receipt']['query']
  if r.get('status')=='ok' and not r.get('total') and r.get('record_total'):r['total']=r['record_total']
  if r.get('items'):r['items']=[self.normalize(i) for i in r['items']]
  return r
 def fact(self,r,prop,value):return any(a.get('property')==prop and a.get('status')=='known' and str(a.get('value'))==str(value) for a in r.get('attributes',[]))
 def goal(self,r):return r.get('goal_receipt',{}).get('goal',{})
 def check(self,c,row):
  r=self.normalize(row.get('response',{}));status=r.get('status');ok=row.get('http')==200;g=self.goal(r);suite=c['suite'];id=c['id']
  if not ok:return False
  if suite=='history':
   try:return bool(history.check(c,r,self.hist))
   except (KeyError,ValueError,TypeError,IndexError):return False
  if suite=='scope':
   if id=='point-identity':return status=='ok' and self.fact(r,'value','40.69898987') and (r.get('entity') or {}).get('code')=='XJ2ABC001MO.TMP.2ABC109MT.BBe'
   return status=='ok' and r.get('total')==c['total'] and (r.get('entity') or {}).get('code')=='XJ2ABC002MO&MOHB01'
  if suite=='limits':
   if id=='limit-1':return status in ('clarify','conversation') and '100' in row['delivered_answer'] and not r.get('records') and not r.get('goal_receipt',{}).get('completed')
   return status=='ok' and r.get('total')==99 and g.get('kind')=='sort' and g.get('limit')==99 and g.get('direction')=='desc'
  if suite=='round3':
   if id.startswith('threshold-') or id.startswith('sort-explicit-'):
    if status!='ok' or (r.get('entity') or {}).get('code')!='XJ2ABC001MO.TMP.2ABC109MT.BBe':return False
    if id=='threshold-2':return r.get('requested_properties')==['name']
    if id in ('threshold-3','sort-explicit-2'):
     facts=r.get('attributes',[]);return len(facts)==18 and [Decimal(a['value']) for a in facts if a['status']=='known']==self.values and all((a['value'] or '')==self.thresholds.get(a['field'],'') for a in facts)
    return len(r.get('attributes',[]))==18
   if id.startswith('earliest'):return status=='ok' and r.get('total')==1461 and g.get('kind')=='extreme' and g.get('field')=='time' and all(z['time'].startswith('1970') for z in r.get('records',[]))
   if id.startswith('month') or id.startswith('date-explicit'):return status=='ok' and r.get('total')==829
   if id=='identity-1':return status=='clarify' and not r.get('records') and not r.get('goal_receipt',{}).get('completed')
   if id=='identity-2':return status=='ambiguous' and r.get('record_total',r.get('outcome',{}).get('candidate_count'))==8029 and not r.get('goal_receipt',{}).get('completed')
   if id in ('identity-3','identity-4'):return status=='ok' and r.get('entity')=={'tree':'config' if id.endswith('3') else 'equipment_class','code':'MOHB'}
   if id in ('difference-1','max-1','sum-limit-1'):return status in ('clarify','conversation') and not r.get('goal_receipt',{}).get('completed') and not r.get('records')
   if id in ('difference-2','reverse-difference-1'):return status=='ok' and r.get('metrics',[{}])[0].get('value')==('1.447999954' if id=='difference-2' else '-1.447999954') and r.get('evidence_total')==2 and g.get('basis')=='raw_numbers'
   if id in ('TMP-1','code-TMP-1'):return status=='ok' and r.get('total')==(0 if id=='TMP-1' else 737)
   if id=='max-2':return status=='ok' and g.get('kind')=='extreme' and r.get('records',[{}])[0].get('value')=='70.80151367'
   if id=='top-time-1':return status=='ok' and g.get('kind')=='sort' and g.get('limit')==3 and r.get('total')==3 and [(z['code'],z['time']) for z in r.get('records',[])]==[(z['测量点编码'],z['测量时间']) for z in self.latest[:3]]
   if id.startswith('1970-'):return status=='ok' and r.get('total')==1461
   raise ValueError(id)
  x=c['expect'];kind=x['kind']
  if kind=='count':return status=='ok' and r.get('total')==x['total']
  if kind=='sort':
   field=x.get('field','time');want=[tuple(v) for v in x['rows']][:20]
   return status=='ok' and g.get('kind')=='sort' and g.get('direction')==x.get('direction','desc') and g.get('limit')==x['limit'] and g.get('field')==field and r.get('total')==x['limit'] and [(z['code'],z[field]) for z in r.get('records',[])]==want
  if kind in ('extreme','raw_extreme','latest'):
   good=status=='ok' and g.get('kind')=='extreme' and g.get('direction')==x.get('direction','desc')
   if kind=='raw_extreme':return good and g.get('basis')=='raw_numbers' and bool(r.get('records')) and all(Decimal(z['value'])==Decimal(str(x['value'])) for z in r['records'])
   return good and r.get('total')==x['total'] and bool(r.get('records')) and all(z['time']=='2026/9/4 17:46' for z in r['records'])
  if kind=='difference':return status=='ok' and g.get('kind')=='difference' and g.get('direction')==x.get('direction') and g.get('basis')=='raw_numbers' and r.get('metrics',[{}])[0].get('value')==x['value'] and r.get('evidence_total')==2
  if kind=='attribute':
   prop=x['property'];name=x['name'];value=x.get('value',self.byname[name][{'value':'测量值','name':'测量点名称','actual_high2':'真实值报警阈值-高2'}[prop]])
   good=status=='ok' and self.fact(r,prop,value) and (r.get('entity') or {}).get('code')==self.byname[name]['测量点编码'] and r.get('requested_properties')==[prop]
   if x.get('source_filter'):good=good and any(f['field']=='source' and f['value']=='源系统1' for f in (r.get('query') or {}).get('filters',[]))
   return good
  if kind=='entity':return status=='ok' and r.get('entity')=={'tree':x['tree'],'code':x['code']}
  if kind in ('empty_compute','missing'):return status in ('data_insufficient','not_found') and not r.get('records') and not r.get('goal_receipt',{}).get('completed')
  if kind=='refuse':return status in ('clarify','conversation','data_insufficient') and not r.get('goal_receipt',{}).get('completed') and not r.get('records')
  if kind=='threshold_sort':
   expected=[Decimal(v) for f,v in self.thresholds.items() if v and (x['family']=='all' or f.startswith(x['family']))];expected.sort(reverse=x['direction']=='desc');limit=x.get('limit');expected=expected[:limit]
   facts=r.get('attributes',[]);return status=='ok' and [Decimal(a['value']) for a in facts if a['status']=='known']==expected and len(facts)==(limit if limit else 6)
  if kind=='root':return status=='ok' and r.get('total')==x['total'] and (r.get('entity') or {}).get('code')=='XJ2ABC002MO&MOHB01'
  if kind=='partial':return status=='batch' and len(r.get('items',[]))==2 and r['items'][0].get('status')=='ok' and r['items'][0].get('total')==829 and r['items'][1].get('status')=='data_insufficient'
  if kind=='attributes-batch':return status=='batch' and len(r.get('items',[]))==2 and all(i.get('status')=='ok' and self.fact(i,'value',value) and (i.get('entity') or {}).get('code')==self.byname[name]['测量点编码'] for i,(name,value) in zip(r['items'],x['values']))
  if kind=='candidate':return status=='ambiguous' and any(z['code']=='XJ2ABC001MO.TMP.2ABC109MT.BBe' for z in r.get('records',[]))
  raise ValueError(kind)
 def classify(self,c,row):
  if row.get('passed'):return '符合预期'
  if row.get('exception') or row.get('timeout') or any(e.get('kind')=='error' for e in row.get('errors',[])):return '运行或接入失败'
  r=self.normalize(row.get('response',{}));status=r.get('status');kind=c.get('expect',{}).get('kind') if isinstance(c.get('expect'),dict) else c.get('expect')
  if status in ('clarify','ambiguous','no_receipt') and kind not in ('refuse','candidate','clarify','numeric_ambiguous','count_clarify','mohb_candidates'):return '多余澄清或未交付'
  if row.get('errors'):return '工具错误后未完成目标'
  return '业务结果或范围不符'

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--evidence-dir',type=Path,required=True);p.add_argument('--engine',choices=['ordinary','agent','both'],default='both');p.add_argument('--agent-model',choices=['gpt-6-luna','gpt-6-sol','gpt-6-astra']);args=p.parse_args();out=args.evidence_dir.resolve();result_path=out/('results.json' if args.engine=='both' else 'results-'+args.engine+'.json');assert (out/'cases.json').exists() and not result_path.exists()
 cases=json.loads((out/'cases.json').read_text());groups=OrderedDict()
 for c in cases:groups.setdefault(c['group'],[]).append(c)
 judge=Judge();engines=('ordinary','agent') if args.engine=='both' else (args.engine,);services={k:Service(k,out,8784 if k=='ordinary' else 8785,args.agent_model) for k in engines};result={'method':'固定版本首次回放；各引擎串行独立会话','execution_scope':args.engine,'requested_agent_model':args.agent_model,'version':'70abf31549af','results':[],'complete':False,'started_at':datetime.now().isoformat()}
 def save():
  result['service_starts']={k:v.starts for k,v in services.items()};result_path.write_text(json.dumps(clean(result),ensure_ascii=False,indent=2))
 try:
  for service in services.values():service.start()
  # 各引擎自身串行，两个引擎用不同模型服务；两版等待时延仍不是受控容量基准。
  import concurrent.futures
  def run_engine(engine):
   service=services[engine]
   for group,cc in groups.items():
    sid,creation=service.new();cursor=0;prior_failed=False
    for n,c in enumerate(cc):
     try:
      row,cursor=service.ask(sid,c,cursor);row['session_creation_seconds']=creation if n==0 else None
      try:row['passed']=bool(judge.check(c,row))
      except (KeyError,ValueError,TypeError,IndexError) as e:row['passed']=False;row['judge_error']=str(e)
     except Exception as e:row={'engine':engine,'suite':c['suite'],'id':c['id'],'question':c['question'],'group':group,'exception':str(e),'passed':False}
     row['classification']=judge.classify(c,row);row['prior_step_failed']=prior_failed;prior_failed=prior_failed or not row['passed']
     with lock:result['results'].append(row);save()
     print(json.dumps({k:row.get(k) for k in ('engine','suite','id','passed','seconds','classification','prior_step_failed')},ensure_ascii=False),flush=True)
    if engine=='ordinary':service.call('/api/reset',{'session':sid})
  import threading
  lock=threading.Lock()
  with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
   for f in concurrent.futures.as_completed([pool.submit(run_engine,k) for k in services]):f.result()
  result['complete']=True
 finally:
  for service in services.values():service.close()
  result['cleanup']={k:{'port':v.port,'owned_server_stopped':v.process is None or v.process.poll() is not None} for k,v in services.items()};result['ended_at']=datetime.now().isoformat();save()
  manifest=json.loads((out/'source-manifest.json').read_text());result['application_unchanged']=all(hashlib.sha256((ROOT/k).read_bytes()).hexdigest()==v for k,v in manifest.items());save()
 if len(result['results'])!=117*len(services):raise SystemExit('回放不完整，不能发布全量结论')
 print('Completed '+str(len(result['results']))+' engine cases; failed business checks are retained, not retried.',flush=True)

if __name__=='__main__':main()
