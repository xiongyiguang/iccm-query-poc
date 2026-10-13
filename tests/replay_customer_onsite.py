"""本机真实DeepSeek固定回归；只发送原题，不发送预期答案。"""
import argparse
import hashlib
import json
from pathlib import Path
from replay_engine_comparison import Service,clean

ROOT=Path(__file__).resolve().parents[1]
FIXTURE=Path(__file__).with_name('fixtures')/'customer_onsite.json'

def expand(service,result,session):
    result=dict(result)
    if result.get('status')=='batch':result['items']=[expand(service,x,session) for x in result['items']];return result
    if result.get('result') and 'records' in result:
        rows=[]
        for page in range(3000):
            http,data=service.call('/api/page',{'session':session,'result':result['result'],'page':page,'version':service.meta['version']})
            assert http==200,(http,data.get('error'))
            rows.extend(data['records'])
            if len(rows)>=data['total']:break
            assert data['records'],'分页提前为空'
        assert len(rows)==data['total'];result['records']=rows
    return result

def grade(case,row):
    r=row.get('response',{});e=case['expected'];metrics={m['label']:m['value'] for m in r.get('metrics',[])}
    specs=[t['spec'] for t in (r.get('context',{}).get('relational_state') or r.get('relational_state') or {}).get('tasks',[])]
    root=specs[0]['root'] if len(specs)==1 else None
    checks={'实际成功':row.get('http')==200 and r.get('status')=='ok','部件数量':metrics.get('原记录/对象数量')==e['parts'],
        '根范围':root is not None and (root['tree'],root['value'])==(e['root_tree'],e['root_code']),'遍历深度':len(specs)==1 and specs[0]['depth']==e['depth'],
        '答案数量':str(e['parts']) in r.get('answer','').replace(',','')}
    if 'classes' in e:checks.update({'部件类别数':metrics.get('不同部件类')==e['classes'],'答案类别数':str(e['classes']) in r.get('answer',''),
        '构型角色有说明':'设备构型' in r.get('note','') and e['selector_code'] in r.get('note','')})
    return {'passed':all(checks.values()),'checks':checks}

def main():
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);p.add_argument('--port',type=int,default=19273);p.add_argument('--repeat',type=int,default=2);a=p.parse_args()
    out=a.out.resolve();out.mkdir(exist_ok=False,parents=True)
    cases=json.loads(FIXTURE.read_text());service=Service('ordinary',out,a.port);rows=[]
    source={str(x.relative_to(ROOT)):hashlib.sha256(x.read_bytes()).hexdigest() for directory in ('backend','prompts/system') for x in (ROOT/directory).glob('*') if x.is_file()}
    def save():(out/'results.json').write_text(json.dumps({'rows':rows,'source':source,'model_payload_excludes_expected':True,'data_version':getattr(service,'meta',{}).get('version')},ensure_ascii=False,indent=2))
    try:
        service.start();save()
        for attempt in range(a.repeat):
            for c in cases:
                sid,_=service.new()
                try:
                    row,_=service.ask(sid,{'id':c['id'],'group':c['id'],'suite':'customer-onsite','question':c['question']})
                    row['response']=clean(expand(service,row['response'],sid));row.update(grade(c,row),attempt=attempt+1);rows.append(row);save()
                    print(json.dumps({'id':c['id'],'attempt':attempt+1,'passed':row['passed'],'answer':row['response'].get('answer'),'seconds':row['seconds']},ensure_ascii=False),flush=True)
                finally:service.call('/api/reset',{'session':sid})
    finally:service.close();save()
    assert source=={n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in source},'实测期间源码变化'
    summary={'passed':sum(x['passed'] for x in rows),'total':len(cases)*a.repeat,'attempted':len(rows),'service_closed':service.process.poll() is not None}
    (out/'summary.json').write_text(json.dumps(summary,indent=2));print(json.dumps(summary),flush=True)
    assert summary['passed']==summary['total'], '客户固定回归不通过'

if __name__=='__main__':main()
