"""真实模型回放中原样接受预览，不能静默纠正模型错误。"""
import argparse,copy,hashlib,json,statistics,sys,time,uuid
from pathlib import Path
import replay_acceptance as a
import replay_semantic_holdout as h
import replay_zhou_originals as z

def main():
 p=argparse.ArgumentParser();p.add_argument('--url',default='http://127.0.0.1:8769');p.add_argument('--rounds',type=int,default=2);p.add_argument('--output-dir',type=Path,required=True);args=p.parse_args()
 out=args.output_dir;out.mkdir(parents=True,exist_ok=True);path=out/'results.json';assert not path.exists()
 originals=a.ROOT/'docs/.staging/task-replacement-20260924/originals-final'
 cases=a.read(originals/'cases.json');oracle=a.read(originals/'oracle.json');acases,manifest=a.load_suite('A')
 sys.path.insert(0,str(a.ROOT/'backend'));from importer import Imports
 store=Imports().load();data={x['kind']:x['rows'] for x in store.dataset};store.db.close()
 client=a.Client(args.url);assert client.meta['version']==oracle['version']==manifest['version']
 evidence={'method':'model previews accepted unchanged by test driver; edited-browser tests reported separately','inputs':{'original_cases_sha256':a.sha((originals/'cases.json').read_bytes()),'original_oracle_sha256':a.sha((originals/'oracle.json').read_bytes()),'A':manifest},'results':[]}
 source={str(f.relative_to(a.ROOT)):a.sha(f.read_bytes()) for folder in ('backend','frontend','prompts','tests') for f in (a.ROOT/folder).rglob('*') if f.is_file() and f.suffix in ('.py','.js','.cjs','.css','.html','.json','.txt')}
 evidence['source_manifest']=source;sessions=set()
 def clean(r):r=copy.deepcopy(r);r.pop('continuation',None);return r
 def save():path.write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
 save()
 try:
  for round in range(1,args.rounds+1):
   for suite,items in [('originals',cases),('A',acases)]:
    prefix='review-replay-'+uuid.uuid4().hex[:12]
    for case in items:
     sid=prefix+'-'+case['group'];sessions.add(sid);start=time.monotonic()
     status,raw=client.call('/api/query',{'session':sid,'question':case['question'],'selection':case.get('selection'),'version':client.meta['version'],'trace':True})
     r=raw;confirmation=None;preview_valid=True
     if raw.get('status')=='review':
      preview_valid=raw['timings_ms']['execution']==0 and not raw['records'] and not raw.get('result')
      tasks=[{k:copy.deepcopy(t[k]) for k in ('index','enabled','values')} for t in raw['review']['tasks']]
      status,r=client.call('/api/confirm',{'session':sid,'review':raw['review']['id'],'tasks':tasks,'version':client.meta['version'],'trace':True})
      confirmation=clean(r)
     seconds=round_time=time.monotonic()-start
     entry={**case,'suite':suite,'round':round,'seconds':round_time,'http_status':status,'preview':clean(raw) if confirmation else None,'response':clean(r),'confirmed_unchanged':confirmation is not None,'passed':False}
     evidence['results'].append(entry);save()
     try:
      if suite=='originals':checks={'original_assertion':bool(z.check(case,r,oracle))}
      else:
       checks=h.check(case['expect'],r);checks['exact_projection_and_form']=a.projection(case['expect'],r)
       paging=a.verify_rows(client,sid,case['expect'],r,data);checks['complete_rows']=paging['passed'];entry['paging']=paging
      checks['preview_zero_execution']=preview_valid;checks['http_success']=status==200
     except (KeyError,TypeError,ValueError,IndexError,AssertionError) as e:checks={'exception':False};entry['error']=str(e)
     entry['checks']=checks;entry['passed']=all(v for k,v in checks.items() if k!='needs_review');save()
     print(suite,case['id'],round,entry['passed'],format(seconds,'.3f'),flush=True)
    for sid in sessions:client.call('/api/reset',{'session':sid})
    sessions.clear()
  current={k:a.sha((a.ROOT/k).read_bytes()) for k in source};assert current==source
  evidence['summary']={}
  for suite in ('originals','A'):
   rows=[r for r in evidence['results'] if r['suite']==suite];times=sorted(r['seconds'] for r in rows)
   evidence['summary'][suite]={'total':len(rows),'passed':sum(r['passed'] for r in rows),'reviews':sum(r['confirmed_unchanged'] for r in rows),'failed':[dict(id=r['id'],round=r['round'],checks=r['checks']) for r in rows if not r['passed']],'p50':statistics.median(times),'max':max(times),'over5':sum(t>5 for t in times)}
  save();print(json.dumps(evidence['summary'],ensure_ascii=False),flush=True)
 finally:
  for sid in sessions:client.call('/api/reset',{'session':sid})
if __name__=='__main__':main()

