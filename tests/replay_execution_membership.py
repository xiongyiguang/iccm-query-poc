"""真实模型调用前冻结对话执行结果和状态预期。"""
import argparse,csv,hashlib,json,sys,time,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'tests'))
from replay_acceptance import Client
BASE=ROOT/'docs/.staging/execution-membership-20260924'
FIELDS={'value':'测量值','unit':'单位','time':'测量时间','prediction':'预测值','rate':'变化速率'}
def task(n,props):return {'name':'测量点名称'+str(n),'properties':props}
def freeze():
    a=[task(41,['value','unit']),task(42,['prediction','rate'])]
    b=[task(41,['value']),a[1]]
    c=[task(43,['value']),a[1]]
    d=[task(19,['unit','time']),task(7,['value','rate'])]
    e=[d[0],task(7,['rate'])]
    suites={
      'E':[
       ('分别读取测量点名称41的测量值和单位，以及测量点名称42的预测值和变化速率。',a,a),
       ('第一项改成只返回测量值，第二项保持状态但这次不要重查。',[b[0]],b),
       ('现在只重新查询第二项，沿用它原来的两个返回字段。',[b[1]],b),
       ('两项的查询设置都原样保留，这一轮都不执行查询。',[],b),
       ('只把第一项原样再查一遍，第二项继续保留，不用查询。',[b[0]],b),
       ('第二项不执行也不改动；第一项的对象换成测量点名称43并查询，返回字段不变。',[c[0]],c)],
      'F':[
       ('建立两个查询：第一项读取测量点名称19的单位与测量时间；第二项读取测量点名称7的测量值与变化速率。',d,d),
       ('第二项只读变化速率并执行；第一项仅保留，不要查询。',[e[1]],e),
       ('第一项请原样重查一次，第二项不用动也不查询。',[e[0]],e),
       ('先不查了，两项的对象和返回字段都保留。',[],e),
       ('刚才保留的第二项再执行一遍，别查第一项。',[e[1]],e),
       ('两项现在都按各自保存的条件和字段重新查询。',e,e)]}
    source=ROOT.parent/'中广核iCCM项目智能问数DEMO脱敏数据/测量点数据分析.csv'
    with source.open(encoding='gb18030',newline='') as f:rows=list(csv.DictReader(f))
    names={t['name'] for seq in suites.values() for _,_,state in seq for t in state}
    oracle={n:[r for r in rows if r['测量点名称']==n] for n in sorted(names)}
    assert all(len(v)==1 for v in oracle.values())
    data={'suites':suites,'oracle':oracle,'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest()}
    path=BASE/'frozen.json';assert not path.exists();path.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    path.with_suffix('.sha256').write_text(hashlib.sha256(path.read_bytes()).hexdigest(),encoding='ascii')
    print('Frozen',sum(len(x) for x in suites.values()),'steps before calls')
def validate(response,outputs,state,oracle):
    if outputs:
        replies=response.get('items') if len(outputs)>1 else [response]
        if not isinstance(replies,list) or len(replies)!=len(outputs):return False,'output count'
        for expected,actual in zip(outputs,replies):
            row=oracle[expected['name']][0]
            if actual.get('status')!='ok':return False,'query did not execute'
            if set(actual.get('requested_properties',[]))!=set(expected['properties']):return False,'projection'
            attrs=actual.get('attributes',[])
            if {x['property'] for x in attrs}!=set(expected['properties']):return False,'attributes'
            for attr in attrs:
                raw=row[FIELDS[attr['property']]]
                if attr.get('status')!=('known' if raw else 'missing'):return False,'missing status'
                if raw and attr.get('value')!=raw:return False,'raw value'
                if not any(x.get('fields')==row for x in attr.get('evidence',[])):return False,'raw source row'
    else:
        trace=response.get('trace',{})
        if response.get('status')!='conversation' or trace.get('validated_intent',{}).get('operation')!='conversation' or trace.get('changed_tasks')!=[]:
            return False,'expected zero execution'
    current=response.get('context',{}).get('business_request',{}).get('tasks',[])
    if len(current)!=len(state):return False,'state count'
    for i,(actual,expected) in enumerate(zip(current,state),1):
        if actual['id']!='t'+str(i) or actual['target']!='points' or set(actual['properties'])!=set(expected['properties']):return False,'state identity/projection'
        fs=actual['filters'];row=oracle[expected['name']][0]
        if len(fs)!=1 or fs[0]['operator']!='equals' or fs[0]['field'] not in ('identity','name','code') or fs[0]['value'] not in (expected['name'],row['测量点编码']):return False,'state subject'
    return True,'objects, projection, values, missing status, source and retained state'
def run(label):
    frozen=BASE/'frozen.json';raw=frozen.read_bytes();digest=hashlib.sha256(raw).hexdigest();assert digest==frozen.with_suffix('.sha256').read_text()
    data=json.loads(raw);out=BASE/(label+'.json');assert not out.exists()
    manifest={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for folder in ('backend','frontend','prompts','tests') for p in (ROOT/folder).rglob('*') if p.is_file() and p.suffix in ('.py','.txt','.json','.js','.cjs','.css','.html')}
    result={'source_manifest':manifest,'frozen_sha256':digest,'results':[]}
    def save():out.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    client=Client('http://127.0.0.1:8769');save()
    for n in range(1,3):
        for name,steps in data['suites'].items():
            sid='execution-'+uuid.uuid4().hex
            try:
                for index,(question,expected,state) in enumerate(steps,1):
                    start=time.monotonic();code,response=client.call('/api/query',{'session':sid,'question':question,'trace':True});preview=None
                    if response.get('status')=='review':
                        preview=response
                        code,response=client.call('/api/confirm',{'session':sid,'review':preview['review']['id'],'tasks':[{k:t[k] for k in ('index','enabled','values')} for t in preview['review']['tasks']],'trace':True})
                    seconds=time.monotonic()-start;response.pop('continuation',None)
                    if preview:preview.pop('continuation',None)
                    passed,reason=validate(response,expected,state,data['oracle']);passed=passed and code==200
                    result['results'].append({'id':name+str(index),'round':n,'question':question,'seconds':seconds,'http':code,'passed':passed,'reason':reason,'preview':preview,'response':response});save()
                    print(name+str(index),n,passed,round(seconds,3),reason,flush=True)
            finally:client.call('/api/reset',{'session':sid})
    assert all(hashlib.sha256((ROOT/k).read_bytes()).hexdigest()==v for k,v in manifest.items())
    print('Passed',sum(x['passed'] for x in result['results']),'/',len(result['results']))
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--freeze',action='store_true');parser.add_argument('--run',default='first');args=parser.parse_args()
    freeze() if args.freeze else run(args.run)
