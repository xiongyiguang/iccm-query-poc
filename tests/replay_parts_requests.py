"""冻结原始 CSV 图关系预期，使用真实模型并保持确认条件不变。"""
import sys,json,copy,math,time,uuid,argparse,statistics
from pathlib import Path
import replay_acceptance as a
BASE=a.ROOT/'docs/.staging/parts-request-20260924'
def freeze():
 sys.path.insert(0,str(a.ROOT/'backend'));from importer import Imports
 store=Imports().load();rows=next(x['rows'] for x in store.dataset if x['kind']=='config')
 children={}
 for r in rows:children.setdefault(r['父对象代码'],[]).append(r)
 def oracle(root,scope):
  seen={root};out=[];queue=list(children.get(root,[]))
  while queue:
   r=queue.pop(0);code=r['对象代码']
   if code in seen:continue
   seen.add(code)
   if r['对象层级描述']=='部件':out.append(r)
   if scope=='all':queue.extend(children.get(code,[]))
  return out
 # 选择具有嵌套后代的根对象，确保直接与递归遍历结果不同。
 root=next(r for r in rows if len(oracle(r['对象代码'],'all'))>len(oracle(r['对象代码'],'direct'))>0 and len(oracle(r['对象代码'],'all'))<1000)
 code=root['对象代码'];name=root['对象描述中文']
 leaf=next(r for r in rows if r['对象代码'] not in children)
 raw=[
 ('chain',f'构型{code}下面直接挂着多少个部件？',code,'direct'),
 ('chain','把更深层的部件也算进去看看总量。',code,'all'),
 ('chain','还是这个构型，只看紧挨着的下一层部件。',code,'direct'),
 ('chain','范围不动，构型换成MOHB01。','MOHB01','direct'),
 ('chain','这次把它的所有下级部件都列出来。','MOHB01','all'),
 ('by_name',f'按名称查构型{name}的全部下级部件。',code,'all'),
 ('by_identity',f'请统计构型{name}的直接部件数量。',code,'direct'),
 ('leaf',f'构型{leaf["对象代码"]}的全部下级部件数量是多少？',leaf['对象代码'],'all'),
 ('missing','构型NO_SUCH_CONFIG_987654的直接部件有多少？',None,'direct'),
 ('exact_name','仅按名称找构型MOHB01，查询它的直接部件数量。',None,'direct'),
 ('scope','构型MOHB01的全部下级部件有多少？','MOHB01','all'),
 ('scope','不递归了，仅统计直接部件。','MOHB01','direct')]
 cases=[]
 for i,(g,q,root,scope) in enumerate(raw,1):
  e={'root':root,'scope':scope,'kind':'parts' if root else 'not_found'}
  if root:
   wanted=oracle(root,scope)
   e.update(rows=wanted,total=len(wanted),multiset_sha256=a.rows_hash(wanted),counts={k:len(oracle(root,k)) for k in ('direct','all')})
  cases.append({'id':f'P{i:02}','group':g,'question':q,'expect':e})
 p=BASE/'frozen.json';assert not p.exists()
 p.write_text(json.dumps({'version':store.version,'cases':cases,'method':'Original CSV parent graph frozen before model calls; same-author heldout, not external blind evaluation.'},ensure_ascii=False,indent=2),encoding='utf8')
 p.with_suffix('.sha256').write_text(a.sha(p.read_bytes()),encoding='ascii');store.db.close();print('Frozen',len(cases),flush=True)
def run(label):
 raw=(BASE/'frozen.json').read_bytes();assert a.sha(raw)==(BASE/'frozen.sha256').read_text()
 frozen=json.loads(raw);client=a.Client('http://127.0.0.1:8769');assert client.meta['version']==frozen['version']
 out=BASE/(label+'.json');assert not out.exists()
 manifest={str(p.relative_to(a.ROOT)):a.sha(p.read_bytes()) for folder in ('backend','frontend','prompts','tests') for p in (a.ROOT/folder).rglob('*') if p.is_file() and p.suffix in ('.py','.js','.cjs','.txt','.json','.html','.css')}
 d={'frozen_sha256':a.sha(raw),'source_manifest':manifest,'results':[]}
 def save():out.write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding='utf8')
 for n in (1,2):
  sessions={}
  try:
   for c in frozen['cases']:
    sid=sessions.setdefault(c['group'],'parts-'+uuid.uuid4().hex);start=time.monotonic()
    status,r=client.call('/api/query',{'session':sid,'question':c['question'],'trace':True});preview=None
    if r.get('status')=='review':
     preview=copy.deepcopy(r)
     status,r=client.call('/api/confirm',{'session':sid,'review':r['review']['id'],'tasks':[{k:t[k] for k in ('index','enabled','values')} for t in r['review']['tasks']],'trace':True})
    seconds=time.monotonic()-start;e=c['expect'];checks={'http':status==200,'typed_entry':r.get('trace',{}).get('engine')=='business_request','preview_no_execution':not preview or not preview['records'] and preview['timings_ms']['execution']==0}
    pages=[];actual=list(r.get('records',[]))
    if e['kind']=='not_found':
     checks.update(not_found=r.get('status')=='not_found',no_count=not r.get('metrics') and r.get('outcome',{}).get('count_computed') is False)
    else:
     for page in range(1,math.ceil(r.get('total',0)/20)):
      code,reply=client.call('/api/page',{'session':sid,'result':r['result'],'page':page});pages.append({'page':page,'http':code,'response':reply});actual.extend(reply.get('records',[]))
     metrics={m['label']:m['value'] for m in r.get('metrics',[])}
     checks.update(status=r.get('status')=='ok',entity=r.get('entity')=={'tree':'config','code':e['root']},scope=r.get('scope')==e['scope'],total=r.get('total')==e['total'],
      counts=metrics=={'直接部件':e['counts']['direct'],'全部下级部件':e['counts']['all']},
      all_raw_rows=len(actual)==e['total'] and a.rows_hash([x.get('evidence',{}).get('fields',{}) for x in actual])==e['multiset_sha256'],
      pages_ok=all(x['http']==200 for x in pages))
    r.pop('continuation',None)
    if preview:preview.pop('continuation',None)
    d['results'].append({**c,'round':n,'seconds':seconds,'checks':checks,'passed':all(checks.values()),'response':r,'preview':preview,'pages':pages});save()
    print(c['id'],n,all(checks.values()),round(seconds,3),[k for k,v in checks.items() if not v],flush=True)
  finally:
   for sid in sessions.values():client.call('/api/reset',{'session':sid})
 assert all(a.sha((a.ROOT/k).read_bytes())==v for k,v in manifest.items())
 times=[x['seconds'] for x in d['results']]
 d['summary']={'total':len(times),'passed':sum(x['passed'] for x in d['results']),'p50':statistics.median(times),'max':max(times),'over5':sum(t>5 for t in times)}
 save();print(json.dumps(d['summary']),flush=True)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--freeze',action='store_true');p.add_argument('--run',default='first');args=p.parse_args()
 freeze() if args.freeze else run(args.run)
