"""按独立 CSV 图关系预期，回放已冻结的集合和深度对话。"""
import argparse,copy,json,sys,time,uuid,math,statistics,hashlib
from pathlib import Path
import replay_acceptance as a
BASE=a.ROOT/'docs/.staging/relationship-population-20260924'

def rowhash(rows):
 return hashlib.sha256('\n'.join(sorted(json.dumps(r,ensure_ascii=False,sort_keys=True,separators=(',',':')) for r in rows)).encode()).hexdigest()

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--suite',choices=['diagnostic','heldout','all'],default='diagnostic')
 parser.add_argument('--rounds',type=int,default=2);parser.add_argument('--label',default='first');parser.add_argument('--url',default='http://127.0.0.1:8769');args=parser.parse_args()
 raw=(BASE/'frozen.json').read_bytes();assert a.sha(raw)==(BASE/'frozen.sha256').read_text()
 frozen=json.loads(raw);cases=[c for c in frozen['cases'] if args.suite=='all' or c['suite']==args.suite]
 client=a.Client(args.url);assert client.meta['version']==frozen['dataset_version']
 out=BASE/(args.label+'.json');assert not out.exists()
 manifest={str(p.relative_to(a.ROOT)):a.sha(p.read_bytes()) for folder in ('backend','frontend','prompts','tests') for p in (a.ROOT/folder).rglob('*') if p.is_file() and p.suffix in ('.py','.js','.cjs','.txt','.json','.html','.css')}
 d={'method':'Real model calls; previews confirmed unchanged; expected rows frozen before implementation. Same-author heldout, not external blind test.',
    'frozen_sha256':a.sha(raw),'source_manifest':manifest,'results':[]}
 def save():out.write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding='utf-8')
 save()
 for n in range(1,args.rounds+1):
  sessions={}
  try:
   for c in cases:
    sid=sessions.setdefault(c['suite']+'-'+c['group'],'population-'+uuid.uuid4().hex);start=time.monotonic()
    http,r=client.call('/api/query',{'session':sid,'question':c['question'],'trace':True});preview=None
    if r.get('status')=='review':
     preview=copy.deepcopy(r)
     http,r=client.call('/api/confirm',{'session':sid,'review':r['review']['id'],'tasks':[{k:t[k] for k in ('index','enabled','values')} for t in r['review']['tasks']],'trace':True})
    seconds=time.monotonic()-start;e=c['expect'];checks={'http':http==200,'status':r.get('status')==e['status'],
     'no_early_execution':not preview or preview['timings_ms']['execution']==0 and not preview['records'] and not preview.get('result')}
    pages=[];actual=list(r.get('records',[]))
    if e['status']=='ok':
     for page in range(1,math.ceil(r.get('total',0)/20)):
      code,result=client.call('/api/page',{'session':sid,'result':r['result'],'page':page});pages.append({'page':page,'http':code,'response':result});actual.extend(result.get('records',[]))
     state=r.get('context',{}).get('business_request',{});task=next((t for t in state.get('tasks',[]) if t['id'] in state.get('last_executed_tasks',[])),{})
     checks.update(typed_relationship=task.get('operation')=='descendants',population=task.get('population')==e['population'],
      root=r.get('entity')=={'tree':'config','code':e['root']},scope=r.get('scope')==e['scope'],total=r.get('total')==e['total'],
      all_raw_rows=len(actual)==e['total'] and rowhash([x.get('evidence',{}).get('fields',{}) for x in actual])==e['raw_rows_sha256'],pages_ok=all(x['http']==200 for x in pages))
    elif e['status']=='not_found':checks['not_fabricated_zero']=not r.get('metrics') and r.get('outcome',{}).get('count_computed') is False
    else:
     state=r.get('context',{}).get('pending_business_request',{});task=next(iter(state.get('tasks',[])),{})
     checks.update(no_query=not r.get('records') and not r.get('metrics'),root_draft=any(f.get('value')==e['root'] for f in task.get('filters',[])),pending_reason=state.get('pending_reason')=='relationship')
    r.pop('continuation',None)
    if preview:preview.pop('continuation',None)
    d['results'].append({**c,'round':n,'http_status':http,'seconds':seconds,'checks':checks,'passed':all(checks.values()),'response':r,'preview':preview,'pages':pages});save()
    print(c['id'],n,all(checks.values()),round(seconds,3),[k for k,v in checks.items() if not v],flush=True)
  finally:
   for sid in sessions.values():client.call('/api/reset',{'session':sid})
 assert all(a.sha((a.ROOT/p).read_bytes())==h for p,h in manifest.items())
 times=[x['seconds'] for x in d['results']];d['summary']={'total':len(times),'passed':sum(x['passed'] for x in d['results']),'p50':statistics.median(times),'max':max(times),'over5':sum(t>5 for t in times)}
 save();print(json.dumps(d['summary']),flush=True)

if __name__=='__main__':main()
