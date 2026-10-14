"""复用冻结历史题包和原判据，仅将执行环境改为本机隔离服务。"""
from pathlib import Path
import json,sys,importlib.util,hashlib,time,argparse,threading,concurrent.futures
r=Path(__file__).resolve().parents[1];b=r/'docs/.staging/object-roles-20261013';sys.path.insert(0,str(r/'tests'))
from replay_engine_comparison import Service,Judge,clean
from replay_customer_onsite import expand,grade as customer_grade
p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);p.add_argument('--full',action='store_true');p.add_argument('--workers',type=int,default=1);a=p.parse_args();assert 1<=a.workers<=3;out=a.out.resolve();out.mkdir(exist_ok=False);receipts=out/'receipts';receipts.mkdir()
sources={str(x.relative_to(r)):hashlib.sha256(x.read_bytes()).hexdigest() for folder in ['backend','frontend','prompts/system','tests','agent_demo'] for x in (r/folder).glob('*') if x.is_file()}
(out/'source-before.json').write_text(json.dumps(sources,indent=2));rows=[];service=Service('ordinary',out,19275);judges={};original_path=list(sys.path)
def load(name,path):
 spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
fixed=json.loads((r/'tests/fixtures/customer_onsite.json').read_text());customer=[{**c,'id':c['id']+'-R'+str(attempt),'fixed_id':c['id'],'group':c['id']+'-R'+str(attempt)} for attempt in (1,2) for c in fixed]
suites=[('customer',customer,None),('roles',json.loads((b/'role-cases.json').read_text()),None)]
if a.full:
 cases=[('new48',r/'docs/.staging/cloud-complex-blind-20261012/questions-only.json',r/'docs/.staging/cloud-complex-blind-20261012/judge_v2.py'),('old48',r/'docs/.staging/multi-table-blind-20261009/questions-only.json',r/'docs/.staging/multi-table-repair-20261009/grade-v2.py'),('history117',r/'docs/.staging/deepseek-release-20261009/local-real-117-active/cases.json',None),('foundation20',r/'docs/.staging/state-convergence-20261012/foundation-unseen-20261013/questions-holdout.json',r/'docs/.staging/state-convergence-20261012/foundation-unseen-20261013/judge_holdout_v2.py'),('foundation6',r/'docs/.staging/state-convergence-20261012/foundation-next-20261013/questions-holdout.json',r/'docs/.staging/state-convergence-20261012/foundation-next-20261013/judge_holdout_v2.py')]
 for name,path,jpath in cases:
  cc=json.loads(path.read_text());suites.append((name,cc,jpath));(out/(name+'-freeze.json')).write_text(json.dumps({'questions':str(path.relative_to(r)),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'judge_sha256':hashlib.sha256(jpath.read_bytes()).hexdigest() if jpath else None}))
result={'method':'各组保持原顺序；独立组可并行，不重试或挑分','workers':a.workers,'complete':False,'source':sources,'rows':rows,'model_receives_question_selection_only':True}
def save():
 result['summary']={name:{'attempted':sum(x['suite']==name for x in rows),'passed':sum(x['suite']==name and x['passed'] for x in rows),'total':len(cc),'failed':[x['id'] for x in rows if x['suite']==name and not x['passed']]} for name,cc,_ in suites}
 (out/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
lock=threading.Lock()
try:
 service.start();result['meta']=service.meta;save();history_judge=Judge() if a.full else None
 for name,cases,jpath in suites:
  judge=load('grade_'+name,jpath) if jpath else None
  sys.path[:]=([str(jpath.parent)] if jpath else [])+original_path;sys.modules.pop('oracle_data_v2',None)
  groups={}
  for case in cases:groups.setdefault(case['group'],[]).append(case)
  def group_run(cc):
   sid,_=service.new()
   try:
    for c in cc:run_case(c,sid)
   finally:service.call('/api/reset',{'session':sid})
  def run_case(c,sid):
   start=time.monotonic()
   try:
    row,_=service.ask(sid,{**c,'suite':c.get('suite',name)});response=row['response']
    if name!='history117':response=clean(expand(service,response,sid))
    row['full_result']=response
    if name=='customer':
     row['response']=response;verdict=customer_grade(next(x for x in fixed if x['id']==c['fixed_id']),row)
    elif name=='roles':
     e=c['expected'];metrics={x['label']:x['value'] for x in response.get('metrics',[])};specs=[x['spec'] for x in response.get('context',{}).get('relational_state',{}).get('tasks',[])];root=specs[0]['root'] if len(specs)==1 else None
     codes=sorted(x['code'] for x in response.get('record_facts',[]));checks={'成功':row['http']==200 and response.get('status')=='ok','完整数量':metrics.get('原记录/对象数量')==e['total'],'完整明细':codes==e['codes'],'现场范围':root and root['tree']=='pbs' and root['value']==e['root'],'集合类型':len(specs)==1 and specs[0]['population']==e['population'],'全部下级':len(specs)==1 and specs[0]['depth']=='all'}
     if e['population']=='parts':checks['部件类别']=metrics.get('不同部件类')==e['classes']
     verdict={'passed':all(checks.values()),'checks':checks}
    elif name=='history117':verdict={'passed':bool(history_judge.check(c,row))}
    elif name=='old48':verdict=judge.grade(c['id'],response,judge.ORACLE[c['id']]['facts'])
    else:verdict=judge.grade({**row,'full_result':response})
    row.update(verdict)
   except Exception as error:row={'id':c['id'],'question':c['question'],'passed':False,'error':str(error)}
   receipt=receipts/(name+'-'+c['id']+'.json');receipt.write_text(json.dumps(clean(row),ensure_ascii=False,indent=2))
   brief={'suite':name,'id':c['id'],'passed':row['passed'],'seconds':round(time.monotonic()-start,3),'receipt':str(receipt.relative_to(out)),'failed_checks':row.get('failed_checks',[k for k,v in row.get('checks',{}).items() if not v]),'error':row.get('error')};
   with lock:rows.append(brief);save()
   print(json.dumps(brief,ensure_ascii=False),flush=True)
  with concurrent.futures.ThreadPoolExecutor(max_workers=a.workers) as pool:
   for future in concurrent.futures.as_completed([pool.submit(group_run,cc) for cc in groups.values()]):future.result()
 result['complete']=True
finally:
 service.close();result['service_closed']=service.process and service.process.poll() is not None
 result['source_unchanged']=sources=={n:hashlib.sha256((r/n).read_bytes()).hexdigest() for n in sources};save()
print(json.dumps(result['summary'],ensure_ascii=False),flush=True)
assert result['complete'] and result['source_unchanged'] and all(x['passed'] for x in rows),'存在未通过，保留全部原始失败'
