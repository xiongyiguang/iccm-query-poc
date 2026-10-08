"""未见过的话语动作对照及混合任务顺序，调用前冻结。"""
import argparse,csv,hashlib,json
from pathlib import Path
import replay_mixed_request as runner
from replay_mixed_request import read,note,ROOT
BASE=ROOT/'docs/.staging/request-actions-20260924'
def freeze():
    alarm=note('explain','alarm');quality=note('explain','quality');limits=note('unsupported','limits')
    cases=[
      ('K01','测量点名称65的读数是82。依据这条已知信息判断设备是否损坏。',[limits]),
      ('K02','测量点名称65的读数可能是82。我想核实数据，请重新读取这个点的测量值。',[read(65,['value'])]),
      ('K03','我看到某条记录的日期停留在1970年。暂不读取记录，请说明这样的日期是否可信。',[quality]),
      ('K04','测量点名称66的状态是已报警。此次只要它的单位，不需要重复查报警状态。',[read(66,['unit'])]),
      ('K05','先展示测量点名称67的测量时间与变化速率，然后解释已报警是否意味着已确定故障原因。',[read(67,['time','rate']),alarm]),
      ('K06','先判断测量点名称68所处设备还能用几天；另外把这个点的测量值和单位原样给我。',[limits,read(68,['value','unit'])]),
      ('K07','我知道文件里有预测值字段。这次不查任何数值，只介绍这些名称是否已经脱敏、导入时如何处理。',[note('explain','provenance')]),
      ('K08','记录里已经给出父编码，可是缺少父对象详细资料。请解释这种情况与没有填写父编码的差别。',[note('explain','references')])]
    a=alarm;b=read(66,['time','unit']);c=limits;d=read(67,['prediction','rate']);e=read(67,['value']);f=read(68,['time'])
    seq=[
      ('H01','建立三项：第一项解释报警状态的含义；第二项读取测量点名称66的测量时间和单位；第三项预测这个设备的剩余寿命。',[a,b,c],[a,b,c]),
      ('H02','第二、第三项先保留。把第一项换成读取测量点名称67的预测值和变化速率。',[d],[d,b,c]),
      ('H03','第一、第三项不动也不执行。第二项停止读记录，改为说明1970年时间的数据质量边界。',[quality],[d,quality,c]),
      ('H04','只重新做第一项，改成只返回测量值，仍用原对象。其余两项保留。',[e],[e,quality,c]),
      ('H05','第二项换为读取测量点名称68的测量时间。第一项和第三项保持原样，不做本轮输出。',[f],[e,f,c]),
      ('H06','现在把保存的三项都原样再做一遍。',[e,f,c],[e,f,c])]
    source=ROOT.parent/'中广核iCCM项目智能问数DEMO脱敏数据/测量点数据分析.csv'
    with source.open(encoding='gb18030',newline='') as stream:rows=list(csv.DictReader(stream))
    names={t['name'] for _,_,ts in cases for t in ts if 'name' in t}|{t['name'] for _,_,_,ts in seq for t in ts if 'name' in t}
    data={'cases':cases,'sequence':seq,'oracle':{name:[r for r in rows if r['测量点名称']==name] for name in sorted(names)},'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest()}
    assert all(len(v)==1 for v in data['oracle'].values());BASE.mkdir(parents=True,exist_ok=True)
    p=BASE/'frozen.json';assert not p.exists();p.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8');p.with_suffix('.sha256').write_text(hashlib.sha256(p.read_bytes()).hexdigest())
    print('Frozen',len(cases)+len(seq),'new cases before model calls')
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--freeze',action='store_true');p.add_argument('--run',default='first');a=p.parse_args()
    if a.freeze:freeze()
    else:runner.BASE=BASE;runner.run(a.run)
