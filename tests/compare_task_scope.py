"""冻结的输出范围语义实验，不属于端到端查询验收。"""
import argparse,hashlib,json,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from task_scope import extract
from typed_fields import THRESHOLDS
OUT=ROOT/'docs/.staging/task-scope-20260924'
def cases():
 a=[]
 def add(q,expected,prior=None,known=False):a.append({'id':'S'+str(len(a)+1).zfill(2),'question':q,'expected':[{'kind':k,'properties':sorted(p)} for k,p in expected],'prior':prior or {},'known_failure':known})
 add('测量点名称19的测量时间显示1970年，据此判断设备今天是否故障。',[('unsupported',[])],known=True)
 add('测量点名称19的时间显示1970年。请读取它的测量值，并判断设备今天有没有故障。',[('read',['value']),('unsupported',[])])
 add('不需要重新查询，解释一下为什么导入时间1970年不能代表今天的设备状态。',[('explain',[])])
 add('测量点名称11的真实值高2阈值是多少？',[('read',['actual_high2'])])
 add('已知真实值高2阈值80、读数81，直接告诉我设备损坏的根本原因。',[('unsupported',[])])
 add('读取测量点名称11的真实值高2阈值，再解释阈值和故障诊断的区别。',[('read',['actual_high2']),('explain',[])])
 add('分别给我测量点名称41和测量点名称42的测量值。',[('read',['value']),('read',['value'])])
 add('测量点名称41只要测量值和单位。',[('read',['value','unit'])])
 add('列出构型MOHB01的全部下级部件。',[('parts',[])])
 add('构型MOHB01的上级对象是哪一个？',[('parent',[])])
 add('列出构型MOHB01的直接部件，同时诊断它今天的故障根因。',[('parts',[]),('unsupported',[])])
 add('高2阈值已知是80，这次只读取测量点名称11的测量时间。',[('read',['time'])])
 add('按源系统统计测点记录数量。',[('analyze',[])])
 add('读取测量点名称4的全部报警阈值档位。',[('read',list(THRESHOLDS))])
 add('不要读取任何测量值或阈值，只解释原始报警原因字段的含义。',[('explain',[])])
 add('别诊断故障，只读测量点名称11的真实值高2。',[('read',['actual_high2'])])
 add('仍要这三项，对象改为测量点名称42。',[('read',['value','unit','time'])],{'last_confirmed':{'subject':'测量点名称41','properties':['value','unit','time']}})
 add('第一项改成只返回测量值，第二项保持状态但这次不要重查。',[('read',['value'])],{'tasks':[{'subject':'测量点名称41','properties':['value','unit']},{'subject':'测量点名称42','properties':['prediction','rate']}]})
 add('核对构型MOHB01和MOHB之间是否存在直接父子关系。',[('relation_check',[])])
 add('我应该怎么向你提问？',[('conversation',[])])
 return a
def signature(tasks):return sorted(json.dumps({'kind':t['kind'],'properties':sorted(t['properties'])},sort_keys=True) for t in tasks)
def main():
 p=argparse.ArgumentParser();p.add_argument('--freeze',action='store_true');p.add_argument('--rounds',type=int,default=2);p.add_argument('--run',default='first');args=p.parse_args();OUT.mkdir(parents=True,exist_ok=True)
 frozen=OUT/'frozen.json'
 if args.freeze:
  assert not frozen.exists();raw=json.dumps({'design':'same-author frozen output-scope holdout; no query results measured','cases':cases()},ensure_ascii=False,indent=2).encode()
  frozen.write_bytes(raw);frozen.with_suffix('.sha256').write_text(hashlib.sha256(raw).hexdigest(),encoding='ascii');print('Frozen',len(cases()));return
 raw=frozen.read_bytes();assert hashlib.sha256(raw).hexdigest()==frozen.with_suffix('.sha256').read_text()
 path=OUT/(args.run+'.json');assert not path.exists()
 evidence={'frozen_sha256':hashlib.sha256(raw).hexdigest(),'source_sha256':{n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in ('backend/task_scope.py','prompts/system/task-scope-v1.txt','tests/compare_task_scope.py')},'results':[]}
 for n in range(1,args.rounds+1):
  for c in json.loads(raw)['cases']:
   start=time.monotonic()
   try:
    answer,trace=extract(c['question'],c['prior']);passed=signature(answer['tasks'])==signature(c['expected']);error=None
   except Exception as e:answer=None;trace=getattr(e,'extraction_trace',{});passed=False;error=type(e).__name__+': '+str(e)
   row={**c,'round':n,'answer':answer,'trace':trace,'passed':passed,'error':error,'seconds':time.monotonic()-start};evidence['results'].append(row)
   path.write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8');print(c['id'],n,passed,round(row['seconds'],3),flush=True)
 print('Passed',sum(x['passed'] for x in evidence['results']),'/',len(evidence['results']),flush=True)
if __name__=='__main__':main()

