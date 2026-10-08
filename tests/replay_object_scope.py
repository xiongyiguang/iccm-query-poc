"""冻结范围来源对照场景，并核对原始对象记录。"""
import sys,json,copy,hashlib,time,uuid,argparse,statistics
from pathlib import Path
import replay_acceptance as a
BASE=a.ROOT/'docs/.staging/object-scope-20260924'
COLUMNS={'pbs':('对象代码','对象描述中文'),'config':('对象代码','对象描述中文'),'equipment_class':('对象编码','描述'),'part_class':('对象编码','对象描述中文')}
def freeze():
 sys.path.insert(0,str(a.ROOT/'backend'));from importer import Imports
 store=Imports().load();data={x['kind']:x['rows'] for x in store.dataset};store.db.close()
 raw=[
 ('intro','请讲讲XXXX2的基本情况。','clarify','XXXX2',None),
 ('intro','PBS树。','identity','XXXX2','pbs'),
 ('new','XXXX3具体是什么对象？','identity','XXXX3','pbs'),
 ('context','请介绍设备类MOHB的基本情况。','identity','MOHB','equipment_class'),
 ('context','接着再说说MOHB这个设备。','identity','MOHB','equipment_class'),
 ('context','MOHB01是什么对象？','ambiguous','MOHB01',None),
 ('context','跨各个对象树看看MOHB到底有哪些对应项。','ambiguous','MOHB',None),
 ('embedded','想了解设备类描述1859的基本情况。','clarify','设备类描述1859',None),
 ('embedded','就看设备类这棵树。','identity','设备类描述1859','equipment_class'),
 ('replace','构型中的MOHB是什么对象？','identity','MOHB','config'),
 ('replace','换成MOH的基本情况。','clarify','MOH',None),
 ('replace','构型树。','identity','MOH','config')]
 cs=[]
 for i,(g,q,k,value,tree) in enumerate(raw,1):
  matches=[dict(tree=t,code=r[cols[0]],name=r[cols[1]],row=r) for t,cols in COLUMNS.items() for r in data[t] if value in (r[cols[0]],r[cols[1]]) and (not tree or t==tree)]
  if k=='identity':assert len(matches)==1,(q,len(matches))
  if k=='ambiguous':assert len(matches)>1,(q,len(matches))
  cs.append(dict(id='S'+str(i).zfill(2),group=g,question=q,expect=dict(kind=k,value=value,tree=tree,matches=matches)))
 BASE.mkdir(parents=True,exist_ok=True);p=BASE/'frozen.json';assert not p.exists();p.write_text(json.dumps({'version':store.version,'cases':cs,'projection_scope':'Basic identity name/code required; allowed basic identity fields only. Other suites verify explicit projections.'},ensure_ascii=False,indent=2),encoding='utf8');p.with_suffix('.sha256').write_text(a.sha(p.read_bytes()),encoding='ascii');print('Frozen',len(cs),'scope cases before calls')
def check(e,r):
 if e['kind']=='clarify':
  draft=r.get('context',{}).get('pending_business_request',{});return {'domain_clarification':r.get('status')=='clarify' and not r.get('records'),'preserved_domain_draft':draft.get('pending_reason')=='domain' and any(f['value']==e['value'] for t in draft.get('tasks',[]) for f in t['filters'])}
 if e['kind']=='ambiguous':
  records=r.get('records',[]);wanted={(m['tree'],m['code']) for m in e['matches']}
  return {'status':r.get('status')=='ambiguous','complete_candidates':{(x['tree'],x['code']) for x in records}==wanted,'raw_evidence':all(any(x.get('evidence',{}).get('fields')==m['row'] for m in e['matches']) for x in records)}
 m=e['matches'][0];attrs=r.get('attributes',[]);vals={x['property']:x['value'] for x in attrs};basic={'name','code','type','level','parent'}
 return {'status':r.get('status')=='ok','entity':r.get('entity')=={'tree':m['tree'],'code':m['code']},'identity_values':vals.get('name')==m['name'] and vals.get('code')==m['code'],'basic_only':{'name','code'}<=set(r.get('requested_properties',[]))<=basic,'raw_evidence':all(any(x.get('fields')==m['row'] for x in v.get('evidence',[])) for v in attrs if v['property'] in ('name','code'))}
def run(label):
 raw=(BASE/'frozen-v2.json').read_bytes();assert a.sha(raw)==(BASE/'frozen-v2.sha256').read_text();f=json.loads(raw);out=BASE/(label+'.json');assert not out.exists();client=a.Client('http://127.0.0.1:8769');assert client.meta['version']==f['version']
 manifest={str(p.relative_to(a.ROOT)):a.sha(p.read_bytes()) for folder in ('backend','frontend','prompts','tests') for p in (a.ROOT/folder).rglob('*') if p.is_file() and p.suffix in ('.py','.js','.cjs','.txt','.json','.html','.css')};d={'frozen_sha256':a.sha(raw),'source_manifest':manifest,'results':[]}
 def save():out.write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding='utf8')
 for n in (1,2):
  sessions={}
  try:
   for c in f['cases']:
    sid=sessions.setdefault(c['group'],'scope-'+uuid.uuid4().hex);start=time.monotonic();status,r=client.call('/api/query',{'session':sid,'question':c['question'],'trace':True});preview=None
    if r.get('status')=='review':
     preview=copy.deepcopy(r);status,r=client.call('/api/confirm',{'session':sid,'review':r['review']['id'],'tasks':[{k:t[k] for k in ('index','enabled','values')} for t in r['review']['tasks']],'trace':True})
    seconds=time.monotonic()-start;r.pop('continuation',None)
    if preview:preview.pop('continuation',None)
    checks=check(c['expect'],r);checks['http_success']=status==200;checks['preview_zero_execution']=not preview or preview['timings_ms']['execution']==0 and not preview['records'];checks['compiler_entry']=r.get('trace',{}).get('engine')=='business_request'
    d['results'].append({**c,'round':n,'seconds':seconds,'http':status,'checks':checks,'passed':all(checks.values()),'preview':preview,'response':r});save();print(c['id'],n,all(checks.values()),round(seconds,3),[k for k,v in checks.items() if not v],flush=True)
  finally:
   for sid in sessions.values():client.call('/api/reset',{'session':sid})
 assert all(a.sha((a.ROOT/k).read_bytes())==v for k,v in manifest.items());times=[x['seconds'] for x in d['results']];d['summary']={'total':len(times),'passed':sum(x['passed'] for x in d['results']),'p50':statistics.median(times),'max':max(times),'over5':sum(t>5 for t in times)};save();print(json.dumps(d['summary']),flush=True)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--freeze',action='store_true');p.add_argument('--run',default='first');x=p.parse_args();freeze() if x.freeze else run(x.run)
