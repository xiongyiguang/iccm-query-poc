"""冻结混合输出预期，按原始 CSV 行核对真实响应。"""
import argparse,csv,hashlib,json,sys,time,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'tests'),str(ROOT/'backend')]
from replay_acceptance import Client
from data_context import DOMAIN_FACTS
BASE=ROOT/'docs/.staging/mixed-request-20260924'
FIELDS={'value':'测量值','unit':'单位','time':'测量时间','prediction':'预测值','rate':'变化速率'}
def read(n,props):return {'operation':'attributes','name':'测量点名称'+str(n),'properties':props}
def note(kind,topic):return {'operation':kind,'topics':[topic]}
def freeze():
    limit=note('unsupported','limits');quality=note('explain','quality');alarm=note('explain','alarm')
    a=read(61,['value','unit']);b=read(62,['prediction','rate']);a2=read(63,['value','unit'])
    cases=[
      ('M01','测量点名称19的测量时间显示1970年，据此判断设备今天是否故障。',[limit]),
      ('M02','测量点名称19的时间显示1970年。请读取它的测量值，并判断设备今天有没有故障。',[read(19,['value']),limit]),
      ('M03','已知真实值高2阈值80、读数81，直接告诉我设备损坏的根本原因。',[limit]),
      ('M04','我已经拿到一个异常时间，先不用查任何字段，只解释1970年时间为什么不能代表当前状态。',[quality]),
      ('M05','第一项，请解释报警阈值的含义；第二项，请读取测量点名称57的单位和测量时间。',[alarm,read(57,['unit','time'])]),
      ('M06','给我测量点名称58的预测值和变化速率，另外推断这个设备还能运行多少天。',[read(58,['prediction','rate']),limit]),
      ('M07','已知测量点名称59的时间异常。仅返回这个点的单位，不用查时间，也不需要诊断。',[read(59,['unit'])]),
      ('M08','分别读取测量点名称60的测量值与测量点名称61的单位，然后说明报警阈值的含义。',[read(60,['value']),read(61,['unit']),alarm])]
    sequence=[
      ('N01','第一项读取测量点名称61的测量值和单位；第二项读取测量点名称62的预测值和变化速率；第三项解释报警阈值的含义。',[a,b,alarm],[a,b,alarm]),
      ('N02','只将第一项对象换成测量点名称63并按原字段查询。第二、第三项仅保留，不执行。',[a2],[a2,b,alarm]),
      ('N03','第三项改为只解释1970年时间的数据质量问题，其他项不查询也不改。',[quality],[a2,b,quality]),
      ('N04','第二项不再读取数据，改成解释报警阈值的含义；其他项保留，不执行。',[alarm],[a2,alarm,quality]),
      ('N05','把第二项改成查询测量点名称64的测量时间，其他任务仅保留。',[read(64,['time'])],[a2,read(64,['time']),quality]),
      ('N06','现在只重新查询第一项，原对象与字段保持，另外两项不执行。',[a2],[a2,read(64,['time']),quality])]
    source=ROOT.parent/'中广核iCCM项目智能问数DEMO脱敏数据/测量点数据分析.csv'
    with source.open(encoding='gb18030',newline='') as f:rows=list(csv.DictReader(f))
    names={t['name'] for _,_,ts in cases for t in ts if 'name' in t}|{t['name'] for _,_,_,ts in sequence for t in ts if 'name' in t}
    data={'cases':cases,'sequence':sequence,'oracle':{name:[r for r in rows if r['测量点名称']==name] for name in sorted(names)},'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest()}
    assert all(len(v)==1 for v in data['oracle'].values())
    BASE.mkdir(parents=True,exist_ok=True);p=BASE/'frozen.json';assert not p.exists();p.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8');p.with_suffix('.sha256').write_text(hashlib.sha256(p.read_bytes()).hexdigest())
    print('Frozen',len(cases)+len(sequence),'cases before model calls')
def validate(response,expected,state,oracle):
    trace=response.get('trace',{});plan=trace.get('validated_intent',{})
    plans=[x['intent'] for x in plan.get('tasks',[])] if plan.get('operation')=='batch' else [plan]
    replies=response.get('items') if response.get('status')=='batch' else [response]
    errors=[]
    if len(plans)!=len(expected) or len(replies)!=len(expected):return ['output count']
    for e,p,r in zip(expected,plans,replies):
        if e['operation']=='attributes':
            row=oracle[e['name']][0]
            if p.get('operation')!='attributes' or r.get('status')!='ok':errors.append('query not delivered');continue
            if set(r.get('requested_properties',[]))!=set(e['properties']):errors.append('projection')
            attrs=r.get('attributes',[])
            if {a['property'] for a in attrs}!=set(e['properties']):errors.append('attribute set')
            for a in attrs:
                if a['property'] not in e['properties']:continue
                raw=row[FIELDS[a['property']]]
                if a.get('status')!=('known' if raw else 'missing') or raw and a.get('value')!=raw:errors.append('raw value/status')
                if not any(x.get('fields')==row for x in a.get('evidence',[])):errors.append('raw row evidence')
        else:
            if r.get('status')!='conversation' or r.get('records') or r.get('evidence'):errors.append('note not delivered without query')
            if e['operation']=='unsupported':
                if p.get('operation')!='conversation' or r.get('answer')!=DOMAIN_FACTS['limits']:errors.append('capability boundary')
            elif p.get('operation')!='explain' or set(p.get('topics',[]))!=set(e['topics']):errors.append('explanation topics')
    tasks=response.get('context',{}).get('business_request',{}).get('tasks',[])
    if len(tasks)!=len(state):errors.append('state count')
    for i,(t,e) in enumerate(zip(tasks,state),1):
        if t['id']!='t'+str(i) or t['operation']!=e['operation']:errors.append('stable task identity/type');continue
        if e['operation']=='attributes':
            row=oracle[e['name']][0];fs=t['filters']
            if t['target']!='points' or set(t['properties'])!=set(e['properties']):errors.append('state projection/domain')
            if len(fs)!=1 or fs[0]['operator']!='equals' or fs[0]['field'] not in ('identity','name','code') or fs[0]['value'] not in (e['name'],row['测量点编码']):errors.append('state object/filters')
        elif t['topics']!=e['topics'] or t['filters'] or t['target'] or t['properties']:errors.append('note state')
    return errors
def run(label):
    raw=(BASE/'frozen.json').read_bytes();assert hashlib.sha256(raw).hexdigest()==(BASE/'frozen.sha256').read_text();data=json.loads(raw)
    out=BASE/(label+'.json');assert not out.exists()
    manifest={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for folder in ('backend','frontend','prompts','tests') for p in (ROOT/folder).rglob('*') if p.is_file() and p.suffix in ('.py','.txt','.json','.js','.cjs','.css','.html')}
    evidence={'source_manifest':manifest,'frozen_sha256':hashlib.sha256(raw).hexdigest(),'results':[]};client=Client('http://127.0.0.1:8769')
    def save():out.write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
    def ask(n,sid,c):
        ident,q,expected,state=c;start=time.monotonic();code,r=client.call('/api/query',{'session':sid,'question':q,'trace':True});preview=None
        if r.get('status')=='review':
            preview=r;code,r=client.call('/api/confirm',{'session':sid,'review':r['review']['id'],'tasks':[{k:t[k] for k in ('index','enabled','values')} for t in r['review']['tasks']],'trace':True})
        seconds=time.monotonic()-start;r.pop('continuation',None)
        if preview:preview.pop('continuation',None)
        errors=validate(r,expected,state,data['oracle'])
        if code!=200:errors.append('HTTP '+str(code))
        evidence['results'].append({'id':ident,'round':n,'question':q,'seconds':seconds,'http':code,'passed':not errors,'errors':errors,'preview':preview,'response':r});save();print(ident,n,not errors,round(seconds,3),errors,flush=True)
    for n in (1,2):
        for ident,q,expected in data['cases']:
            sid='mixed-'+uuid.uuid4().hex
            try:ask(n,sid,(ident,q,expected,expected))
            finally:client.call('/api/reset',{'session':sid})
        sid='mixed-sequence-'+uuid.uuid4().hex
        try:
            for c in data['sequence']:ask(n,sid,c)
        finally:client.call('/api/reset',{'session':sid})
    assert all(hashlib.sha256((ROOT/k).read_bytes()).hexdigest()==v for k,v in manifest.items())
    print('Passed',sum(r['passed'] for r in evidence['results']),'/',len(evidence['results']))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--freeze',action='store_true');p.add_argument('--run',default='first');a=p.parse_args();freeze() if a.freeze else run(a.run)
