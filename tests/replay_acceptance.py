"""针对本机或鉴权云端运行时，回放不可变语义测试集。

保留历史预期，补充精确投影和完整行集合校验。
分页核验耗时与答案响应耗时分开记录。"""
import argparse,collections,copy,hashlib,http.cookiejar,json,math,statistics,sys,time,urllib.error,urllib.request,uuid
from pathlib import Path
import replay_semantic_holdout as h

ROOT=h.ROOT
STAGING=ROOT/'docs/.staging'


def read(path):return json.loads(path.read_text(encoding='utf-8'))
def sha(raw):return hashlib.sha256(raw).hexdigest()
def row_key(row):return json.dumps(row,ensure_ascii=False,sort_keys=True,separators=(',',':'))
def rows_hash(rows):return sha(json.dumps(sorted(row_key(x) for x in rows),ensure_ascii=False).encode())


def load_suite(letter):
    folder='semantic-holdout-20260924' if letter in 'ABCDE' else 'request-state-20260924' if letter in 'FGHIJ' else 'request-checklist-20260924' if letter in 'KLM' else 'request-unification-20260924'
    path=STAGING/folder/('frozen.json' if letter in 'AB' else 'frozen-'+letter+'.json')
    raw=path.read_bytes();digest=sha(raw);assert digest==path.with_suffix('.sha256').read_text(encoding='ascii').strip()
    frozen=json.loads(raw);cases=frozen['suites'][letter] if 'suites' in frozen else frozen['cases']
    correction=None
    if letter=='C':
        correction=read(path.parent/'C-oracle-correction.json');assert correction['original_frozen_sha256']==digest
        for c in cases:
            if c['id'] in correction['case_ids']:c['expect']={**c['expect'],'kind':'missing_parent'}
    return cases,{'path':str(path.relative_to(ROOT)),'sha256':digest,'version':frozen['version'],'correction':correction}


def projection(e,r):
    if e['kind']=='batch':
        items=r.get('items',[])
        return len(items)==len(e['items']) and all(projection(a,b) for a,b in zip(e['items'],items))
    if e['kind']=='attributes':return set(r.get('requested_properties') or r.get('requested_thresholds') or [])==set(e['properties'])
    if e['kind'] in ('search','object_search'):return (r.get('trace') or {}).get('validated_intent',{}).get('operation')=='search'
    return True


class Client:
    def __init__(self,url):
        self.url=url.rstrip('/');self.meta={}
        self.op=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        if not self.url.startswith('http://127.0.0.1'):
            creds={k.strip():v.strip() for line in (ROOT/'.local/cloud-8899-access.txt').read_text(encoding='utf-8-sig').splitlines() if ':' in line for k,v in [line.split(':',1)]}
            code,_=self.call('/api/auth/login',{'username':creds['Username'],'password':creds['Password']});creds.clear();assert code==200
        self.meta=json.load(self.op.open(self.url+'/api/meta',timeout=30))
    def call(self,path,body):
        headers={'Content-Type':'application/json','Origin':self.url}
        if self.meta:headers['X-Demo-Token']=self.meta['token']
        req=urllib.request.Request(self.url+path,data=json.dumps(body).encode(),headers=headers)
        try:
            with self.op.open(req,timeout=120) as response:return response.status,json.load(response)
        except urllib.error.HTTPError as error:
            with error:return error.code,json.load(error)


def verify_rows(client,sid,e,r,data):
    if e['kind'] not in ('search','object_search'):return {'applicable':False,'passed':True}
    fields=h.FIELDS if e['kind']=='search' else {'name':'对象描述中文','code':'对象代码'}
    source=data['points' if e['kind']=='search' else e['target']]
    expected=[row for row in source if all(h.match(row.get(fields[f['field']],''),f) for f in e['filters'])]
    # 断言原冻结预期未随新代码漂移。
    assert len(expected)==e['total']
    assert sha(json.dumps(expected,ensure_ascii=False,sort_keys=True).encode())==e['row_hash']
    actual=list(r.get('records',[]));pages=1 if actual else 0
    for page in range(1,math.ceil(r.get('total',0)/20)):
        status,reply=client.call('/api/page',{'session':sid,'result':r['result'],'page':page})
        if status!=200:return {'applicable':True,'passed':False,'page_error':status,'page':page}
        actual.extend(reply['records']);pages+=1
    raw=[row.get('evidence',{}).get('fields',{}) for row in actual]
    actual_hash=rows_hash(raw);expected_hash=rows_hash(expected)
    return {'applicable':True,'passed':len(raw)==len(expected) and actual_hash==expected_hash,
            'records':len(raw),'pages':pages,'actual_multiset_sha256':actual_hash,'expected_multiset_sha256':expected_hash}


def summarize(rows):
    times=sorted(x['seconds'] for x in rows)
    return {'total':len(rows),'passed':sum(x['passed'] for x in rows),
            'failures':[{'suite':x['suite'],'id':x['id'],'round':x['round'],'checks':x['checks'],
                         'answer':x['response'].get('answer',x['response'].get('error'))} for x in rows if not x['passed']],
            'latency':{'p50':statistics.median(times),'p95':times[math.ceil(len(times)*.95)-1],'max':max(times),
                       'over5':sum(t>5 for t in times)},
            'engines':dict(collections.Counter((x['response'].get('trace') or {}).get('engine','unknown') for x in rows))}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--url',default='http://127.0.0.1:8769');parser.add_argument('--suites',default='ABCDEFGHIJKLMN');parser.add_argument('--rounds',type=int,default=2);parser.add_argument('--output-dir',type=Path,required=True);parser.add_argument('--confirm-complex',action='store_true');args=parser.parse_args()
    out=args.output_dir;out.mkdir(parents=True,exist_ok=True);path=out/'results.json';assert not path.exists()
    cases={};manifests={}
    for letter in args.suites:cases[letter],manifests[letter]=load_suite(letter)
    sys.path.insert(0,str(ROOT/'backend'));from importer import Imports
    store=Imports().load();data={x['kind']:x['rows'] for x in store.dataset};version=store.version;store.db.close()
    client=Client(args.url);assert client.meta['version']==version
    assert all(m['version']==version for m in manifests.values())
    source_manifest={str(p.relative_to(ROOT)):sha(p.read_bytes()) for folder in ('backend','frontend','prompts','tests') for p in (ROOT/folder).rglob('*') if p.is_file() and p.suffix in ('.py','.txt','.json','.cjs','.js','.css','.html')}
    result={'url':args.url,'manifests':manifests,'source_manifest':source_manifest,'confirm_complex_unchanged':args.confirm_complex,'results':[]};sessions=set()
    def save():path.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    save()
    try:
        for n in range(1,args.rounds+1):
            for letter in args.suites:
                prefix='acceptance-'+uuid.uuid4().hex[:12]
                for c in cases[letter]:
                    sid=prefix+'-'+c['group'];sessions.add(sid);start=time.monotonic()
                    status,response=client.call('/api/query',{'session':sid,'question':c['question'],'version':version,'trace':True})
                    preview=None;preview_valid=True
                    if args.confirm_complex and response.get('status')=='review':
                        preview=copy.deepcopy(response);preview.pop('continuation',None)
                        preview_valid=response['timings_ms']['execution']==0 and not response['records'] and not response.get('result')
                        edits=[{k:copy.deepcopy(t[k]) for k in ('index','enabled','values')} for t in response['review']['tasks']]
                        status,response=client.call('/api/confirm',{'session':sid,'review':response['review']['id'],'tasks':edits,'version':version,'trace':True})
                    response.pop('continuation',None)
                    elapsed=round(time.monotonic()-start,3);checks={}
                    # 即使断言或审计失败，也保留原始响应。
                    entry={**c,'suite':letter,'round':n,'http':status,'seconds':elapsed,'checks':{'validation_complete':False},'passed':False,'preview':preview,'confirmed_unchanged':preview is not None,'response':response}
                    result['results'].append(entry);save()
                    try:
                        checks=h.check(c['expect'],response);checks['exact_projection_and_form']=projection(c['expect'],response)
                    except (KeyError,ValueError,TypeError,IndexError) as error:checks={'understanding':False,'conditions':False,'result':False,'error':str(error)}
                    verify_start=time.monotonic()
                    try:paging=verify_rows(client,sid,c['expect'],response,data)
                    except (KeyError,ValueError,TypeError,IndexError,AssertionError) as error:paging={'passed':False,'error':str(error)}
                    checks['complete_rows']=paging['passed']
                    if c.get('require_compiler',letter not in 'ABCDE') and c['expect']['kind'] not in ('clarify','unsupported','count','missing_parent'):
                        checks['compiler_path']=(response.get('trace') or {}).get('engine')=='business_request'
                        checks['committed_request']=bool(response.get('context',{}).get('business_request'))
                    checks['http_success']=status==200
                    if args.confirm_complex:checks['preview_zero_execution']=preview_valid
                    entry.update({**c,'suite':letter,'round':n,'http':status,'seconds':elapsed,'checks':checks,
                           'paging':paging,'verification_seconds':round(time.monotonic()-verify_start,3),'passed':all(v for k,v in checks.items() if k!='needs_review'),'response':response})
                    save()
                    print(letter,c['id'],n,entry['passed'],elapsed,checks,flush=True)
                for sid in sessions:client.call('/api/reset',{'session':sid})
                sessions.clear()
        result['summary']=summarize(result['results']);save();print(json.dumps(result['summary'],ensure_ascii=False),flush=True)
    finally:
        for sid in sessions:client.call('/api/reset',{'session':sid})

if __name__=='__main__':main()
