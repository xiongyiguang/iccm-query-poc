"""对预先冻结的输出范围场景执行集成验收。"""
import json,sys,time,uuid,hashlib,os
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'backend'),str(ROOT/'tests')]
from task_scope import compare
from replay_acceptance import Client
base=ROOT/'docs/.staging/task-scope-20260924'
raw=(base/'frozen.json').read_bytes();assert hashlib.sha256(raw).hexdigest()==(base/'frozen.sha256').read_text()
out=base/(os.environ.get('SCOPE_REPLAY_RUN','integration')+'.json');assert not out.exists()
client=Client('http://127.0.0.1:8769')
source={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for folder in ('backend','frontend','prompts','tests') for p in (ROOT/folder).rglob('*') if p.is_file() and p.suffix in ('.py','.txt','.json','.js','.cjs','.css','.html')}
evidence={'source_manifest':source,'frozen_sha256':hashlib.sha256(raw).hexdigest(),'scope_only_not_full_data_oracle':True,'results':[]}
def save():out.write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
def ask(sid,q):
 code,r=client.call('/api/query',{'session':sid,'question':q,'trace':True});preview=None
 if r.get('status')=='review':
  preview=r;code,r=client.call('/api/confirm',{'session':sid,'review':r['review']['id'],'tasks':[{k:t[k] for k in ('index','enabled','values')} for t in r['review']['tasks']],'trace':True})
 r.pop('continuation',None)
 if preview:preview.pop('continuation',None)
 return code,r,preview
save()
for n in range(1,3):
 for c in json.loads(raw)['cases']:
  sid='task-scope-'+uuid.uuid4().hex;setups=[]
  try:
   if c['id']=='S17':setups.append(ask(sid,'读取测量点名称41的测量值、单位和测量时间。'))
   if c['id']=='S18':setups.append(ask(sid,'分别读取测量点名称41的测量值和单位，以及测量点名称42的预测值和变化速率。'))
   start=time.monotonic();code,r,preview=ask(sid,c['question']);seconds=time.monotonic()-start
   plan=(r.get('trace') or {}).get('validated_intent') or {}
   try:verdict=compare({'tasks':c['expected']},plan);passed=code==200 and verdict['matches'] and r.get('status') not in ('error','review')
   except (KeyError,ValueError,TypeError) as e:verdict={'error':str(e)};passed=False
   # 受支持请求被校验器拒绝，即使安全，也不能判为成功。
   if any(t['kind'] not in ('unsupported','explain','conversation') for t in c['expected']) and r.get('status') in ('clarify','conversation'):passed=False
   evidence['results'].append({**c,'round':n,'seconds':seconds,'http':code,'passed':passed,'verdict':verdict,'setups':setups,'preview':preview,'response':r});save()
   print(c['id'],n,passed,round(seconds,3),r.get('status',r.get('error')),flush=True)
  finally:client.call('/api/reset',{'session':sid})
assert all(hashlib.sha256((ROOT/k).read_bytes()).hexdigest()==v for k,v in source.items())
print('Passed',sum(x['passed'] for x in evidence['results']),'/',len(evidence['results']))

