"""冻结完整别名续接及双向主体切换测试。"""
import argparse,copy,json,statistics,time,uuid
from pathlib import Path
import replay_acceptance as a
BASE=a.ROOT/'docs/.staging/confirmed-alias-20260924'

def check(e,r):
 records=r.get('records',[]);checks={'status':r.get('status')==e['status']}
 if e['status']=='ambiguous':
  checks['complete_candidates']={(x.get('tree'),x.get('code')) for x in records}=={(x['tree'],x['code']) for x in e['objects']}
  checks['raw_rows']={a.row_key(x.get('evidence',{}).get('fields',{})) for x in records}=={a.row_key(x['raw']) for x in e['objects']}
 else:
  want={'tree':e['tree'],'code':e['code']};checks['entity']=r.get('entity')==want or len(records)==1 and all(records[0].get(k)==v for k,v in want.items())
  evidence=r.get('evidence',[])+[x.get('evidence',{}) for x in records]
  checks['raw_row']=all(x['raw'] in [y.get('fields') for y in evidence] for x in e['objects'])
  state=r.get('context',{}).get('business_request',{});tasks=[t for t in state.get('tasks',[]) if t['id'] in state.get('last_executed_tasks',[])]
  checks['saved_domain']=len(tasks)==1 and tasks[0]['target']==e['tree']
 return checks

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--suite',choices=['diagnostic','heldout','all'],default='all');parser.add_argument('--rounds',type=int,default=2);parser.add_argument('--label',default='first');parser.add_argument('--url',default='http://127.0.0.1:8769');args=parser.parse_args()
 raw=(BASE/'frozen.json').read_bytes();assert a.sha(raw)==(BASE/'frozen.sha256').read_text().strip();f=json.loads(raw);client=a.Client(args.url);assert client.meta['version']==f['version']
 out=BASE/(args.label+'.json');assert not out.exists()
 manifest={str(p.relative_to(a.ROOT)):a.sha(p.read_bytes()) for folder in ('backend','frontend','prompts','tests') for p in (a.ROOT/folder).rglob('*') if p.is_file() and p.suffix in ('.py','.js','.cjs','.txt','.json','.html','.css')}
 result={'method':'Real model; confirm unchanged; independent raw CSV identities; same-author heldout','frozen_sha256':a.sha(raw),'source_manifest':manifest,'results':[]}
 def save():out.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
 save()
 for n in range(1,args.rounds+1):
  sessions={}
  try:
   for c in f['cases']:
    if args.suite!='all' and c['suite']!=args.suite:continue
    sid=sessions.setdefault(c['group'],'confirmed-alias-'+uuid.uuid4().hex);start=time.monotonic();http,r=client.call('/api/query',{'session':sid,'question':c['question'],'trace':True});preview=None
    if r.get('status')=='review':
     preview=copy.deepcopy(r);http,r=client.call('/api/confirm',{'session':sid,'review':r['review']['id'],'tasks':[{k:t[k] for k in ('index','enabled','values')} for t in r['review']['tasks']],'trace':True})
    elapsed=time.monotonic()-start;checks=check(c['expect'],r);checks.update(http=http==200,no_early_execution=not preview or preview['timings_ms']['execution']==0 and not preview['records'])
    r.pop('continuation',None)
    if preview:preview.pop('continuation',None)
    result['results'].append({**c,'round':n,'http_status':http,'seconds':elapsed,'checks':checks,'passed':all(checks.values()),'response':r,'preview':preview});save()
    print(c['id'],n,all(checks.values()),round(elapsed,3),[k for k,v in checks.items() if not v],flush=True)
  finally:
   for sid in sessions.values():client.call('/api/reset',{'session':sid})
 assert all(a.sha((a.ROOT/k).read_bytes())==v for k,v in manifest.items())
 times=[x['seconds'] for x in result['results']];result['summary']={'total':len(times),'passed':sum(x['passed'] for x in result['results']),'p50':statistics.median(times),'max':max(times),'over5':sum(t>5 for t in times)};save();print(result['summary'],flush=True)

if __name__=='__main__':main()
