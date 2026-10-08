"""冻结对象域对话序列；使用真实模型、不修改确认条件，以 CSV 独立计算预期。"""
import argparse,copy,json,hashlib,statistics,time,uuid
from pathlib import Path
import replay_acceptance as a
BASE=a.ROOT/'docs/.staging/object-review-20260924'

def check(e,r):
 if e['kind']=='clarify':return {'status':r.get('status')=='clarify','no_query':not r.get('records') and not r.get('metrics')}
 if e['kind']=='config_mohb':return {'status':r.get('status')=='ok','entity':r.get('entity')=={'tree':'config','code':'MOHB'}}
 attrs={x['property']:x for x in r.get('attributes',[])};expected=set(e['fields'])
 checks={'status':r.get('status')=='ok','entity':(r.get('entity') or {}).get('code')==e['code'],
  'projection':set(attrs)==expected if e['exact_projection'] else expected<=set(attrs)<=expected|{'physical_quantity'},
  'no_wrong_domain_draft':'pending_business_request' not in r.get('context',{})}
 for key,field in e['fields'].items():
  actual=attrs.get(key,{});values={row[field].strip() for row in e['rows']}
  checks['value_'+key]=len(values)==1 and actual.get('value')==next(iter(values))
  checks['status_'+key]=actual.get('status')==('missing' if values=={''} else 'known')
  evidence=[x.get('fields') for x in actual.get('evidence',[])]
  checks['source_'+key]=all(row in evidence for row in e['rows'])
 if 'physical_quantity' in attrs:checks['no_invented_quantity']=attrs['physical_quantity'].get('status') not in ('known',None)
 return checks

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--suite',choices=['diagnostic','heldout','all'],default='all');parser.add_argument('--rounds',type=int,default=2);parser.add_argument('--label',default='first');parser.add_argument('--url',default='http://127.0.0.1:8769');args=parser.parse_args()
 raw=(BASE/'frozen.json').read_bytes();assert a.sha(raw)==(BASE/'frozen.sha256').read_text().strip();f=json.loads(raw)
 client=a.Client(args.url);assert client.meta['version']==f['version']
 out=BASE/(args.label+'.json');assert not out.exists()
 manifest={str(p.relative_to(a.ROOT)):a.sha(p.read_bytes()) for folder in ('backend','frontend','prompts','tests') for p in (a.ROOT/folder).rglob('*') if p.is_file() and p.suffix in ('.py','.js','.cjs','.txt','.json','.html','.css')}
 result={'method':'Real model; confirm unchanged; no oracle-driven edits; same-author heldout','frozen_sha256':a.sha(raw),'source_manifest':manifest,'results':[]}
 def save():out.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
 save()
 for n in range(1,args.rounds+1):
  sessions={}
  try:
   for c in f['cases']:
    if args.suite!='all' and c['suite']!=args.suite:continue
    sid=sessions.setdefault(c['group'],'object-review-'+uuid.uuid4().hex);start=time.monotonic();http,r=client.call('/api/query',{'session':sid,'question':c['question'],'trace':True});preview=None
    if r.get('status')=='review':
     preview=copy.deepcopy(r);http,r=client.call('/api/confirm',{'session':sid,'review':r['review']['id'],'tasks':[{k:t[k] for k in ('index','enabled','values')} for t in r['review']['tasks']],'trace':True})
    elapsed=time.monotonic()-start;checks=check(c['expect'],r)
    checks.update(http=http==200,no_early_execution=not preview or preview['timings_ms']['execution']==0 and not preview['records'])
    r.pop('continuation',None)
    if preview:preview.pop('continuation',None)
    result['results'].append({**c,'round':n,'http_status':http,'seconds':elapsed,'checks':checks,'passed':all(checks.values()),'response':r,'preview':preview});save()
    print(c['id'],n,all(checks.values()),round(elapsed,3),[k for k,v in checks.items() if not v],flush=True)
  finally:
   for sid in sessions.values():client.call('/api/reset',{'session':sid})
 assert all(a.sha((a.ROOT/k).read_bytes())==v for k,v in manifest.items())
 times=[x['seconds'] for x in result['results']];result['summary']={'total':len(times),'passed':sum(x['passed'] for x in result['results']),'p50':statistics.median(times),'max':max(times),'over5':sum(t>5 for t in times)};save();print(result['summary'],flush=True)

if __name__=='__main__':main()
