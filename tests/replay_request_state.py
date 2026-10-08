"""冻结新的对话顺序，原始行预期计算独立于请求编译器。"""
import argparse,hashlib,http.cookiejar,json,sys,time,urllib.request,urllib.error,uuid
from pathlib import Path
import replay_semantic_holdout as h
ROOT=h.ROOT;OUT=ROOT/'docs/.staging/request-state-20260924'

def freeze():
    sys.path.insert(0,str(ROOT/'backend'));from importer import Imports
    s=Imports().load();data={x['kind']:x['rows'] for x in s.dataset};cases=[]
    def add(group,q,e):cases.append(dict(id='F'+str(len(cases)+1).zfill(2),group=group,question=q,expect=h.build_oracle(e,data)))
    add('filters','源系统1的记录里，给我找单位为空且读数超过3的测点。',h.search([h.f('source','equals','源系统1'),h.f('unit','is_blank',''),h.f('value','gt','3')]))
    add('filters','来源改到源系统2，其余照旧。',h.search([h.f('source','equals','源系统2'),h.f('unit','is_blank',''),h.f('value','gt','3')]))
    add('filters','读数再增加一个上限，小于9。',h.search([h.f('source','equals','源系统2'),h.f('unit','is_blank',''),h.f('value','gt','3'),h.f('value','lt','9')]))
    add('filters','把下限从3改到4，上限和其他要求不动。',h.search([h.f('source','equals','源系统2'),h.f('unit','is_blank',''),h.f('value','gt','4'),h.f('value','lt','9')]))
    add('filters','单位要求取消，其他筛选保留。',h.search([h.f('source','equals','源系统2'),h.f('value','gt','4'),h.f('value','lt','9')]))
    add('filters','现在另查开关关闭的全部测点，不沿用刚才条件。',h.search([h.f('switch','equals','关闭')]))
    add('props','读取测量点名称41的变化速率、单位、预测值。',h.attrs('测量点名称41',['rate','unit','prediction']))
    add('props','仍看这三项，对象切到测量点名称42。',h.attrs('测量点名称42',['rate','unit','prediction']))
    add('props','字段改为真实值低1和测量值，对象保持。',h.attrs('测量点名称42',['actual_low1','value']))
    add('props','照这两项再查测量点名称43。',h.attrs('测量点名称43',['actual_low1','value']))
    add('branches','分别查测量点名称51的测量值和单位，以及测量点名称52的预测值和真实值高2。',dict(kind='batch',items=[h.attrs('测量点名称51',['value','unit']),h.attrs('测量点名称52',['prediction','actual_high2'])]))
    add('branches','只把第一项的对象换成测量点名称53，字段不变。',h.attrs('测量点名称53',['value','unit']))
    add('branches','第二项仍是原来的测量点名称52，这次只取变化速率。',h.attrs('测量点名称52',['rate']))
    raw=json.dumps({'version':s.version,'design':'same-author frozen holdout, source-row independent oracle','cases':cases},ensure_ascii=False,indent=2).encode()
    p=OUT/'frozen-F.json';assert not p.exists();p.write_bytes(raw);(OUT/'frozen-F.sha256').write_text(hashlib.sha256(raw).hexdigest(),encoding='ascii');s.db.close();print('Frozen',len(cases),hashlib.sha256(raw).hexdigest())

def main():
    p=argparse.ArgumentParser();p.add_argument('--freeze',action='store_true');p.add_argument('--url',default='http://127.0.0.1:8769');p.add_argument('--rounds',type=int,default=2);p.add_argument('--run');p.add_argument('--manifest',type=Path,default=OUT/'frozen-F.json');args=p.parse_args()
    if args.freeze:return freeze()
    raw=args.manifest.read_bytes();assert hashlib.sha256(raw).hexdigest()==args.manifest.with_suffix('.sha256').read_text();suite=json.loads(raw)
    path=OUT/(args.run+'.json');assert not path.exists()
    op=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()));meta=json.load(op.open(args.url+'/api/meta'));assert meta['version']==suite['version'];sessions=set();results=[]
    def call(endpoint,body):
        req=urllib.request.Request(args.url+endpoint,data=json.dumps(body).encode(),headers={'Content-Type':'application/json','Origin':args.url,'X-Demo-Token':meta['token']})
        try:
            with op.open(req,timeout=120) as x:return x.status,json.load(x)
        except urllib.error.HTTPError as x:return x.code,json.load(x)
    try:
        for n in range(args.rounds):
            prefix='request-'+uuid.uuid4().hex[:12]
            for c in suite['cases']:
                sid=prefix+'-'+c['group'];sessions.add(sid);t=time.perf_counter();status,r=call('/api/query',{'session':sid,'question':c['question'],'version':meta['version'],'trace':True})
                try:checks=h.check(c['expect'],r)
                except (KeyError,ValueError,TypeError) as error:checks={'understanding':False,'conditions':False,'result':False,'error':str(error)}
                if c.get('require_compiler',True):
                    checks['compiler_path']=(r.get('trace') or {}).get('engine')=='business_request'
                    checks['committed_request']=bool(r.get('context',{}).get('business_request'))
                entry={**c,'round':n+1,'http':status,'seconds':round(time.perf_counter()-t,3),'checks':checks,'passed':all(checks.values()),'response':r};results.append(entry)
                path.write_text(json.dumps({'frozen_sha256':hashlib.sha256(raw).hexdigest(),'results':results},ensure_ascii=False,indent=2),encoding='utf-8');print(c['id'],n+1,entry['passed'],checks,flush=True)
            for sid in sessions:call('/api/reset',{'session':sid})
            sessions.clear()
    finally:
        for sid in sessions:call('/api/reset',{'session':sid})
    print('PASSED',sum(x['passed'] for x in results),'/',len(results),flush=True)
if __name__=='__main__':main()
