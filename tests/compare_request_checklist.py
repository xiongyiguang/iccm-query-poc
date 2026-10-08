"""冻结并隔离的语义 A/B 实验，保留原始行预期和模型原输出。"""
import argparse,copy,hashlib,json,sys,concurrent.futures
from pathlib import Path
import replay_semantic_holdout as h
ROOT=h.ROOT;OUT=ROOT/'docs/.staging/request-checklist-20260924'
sys.path.insert(0,str(ROOT/'backend'))
from request_checklist import extract,compile_checklist
from business_request import RequestAmbiguous
from importer import Imports
from query_plan import execute_plan
from session_state import public_result

def prior(*specs,ambiguous=False):
    tasks=[];number=1
    for i,e in enumerate(specs,1):
        filters=e['filters'] if e['kind']=='search' else [h.f('identity','equals',e['name'])]
        unit={'state':'ambiguous' if ambiguous else 'none','value':''};fs=[]
        for f in filters:
            fs.append({**f,'id':f'f{number}','source':{'turn':1,'quote':'frozen correct prior'}});number+=1
            if f['field']=='unit' and f['operator']=='equals':unit={'state':'specified','value':f['value']}
        tasks.append({'id':f't{i}','operation':e['kind'],'target':'points','scope':'direct','properties':e.get('properties',[]),'filters':fs,'unit':unit,'sources':{k:{'turn':1,'quote':'frozen correct prior'} for k in ('operation','target','scope','properties','unit')}})
    return {'version':1,'revision':1,'next_filter_id':number,'tasks':tasks,'last_executed_tasks':['t1']}

def freeze():
    s=Imports().load();data={x['kind']:x['rows'] for x in s.dataset};cases=[]
    def add(id,q,expect,p=None,mode='new'):
        cases.append({'id':id,'question':q,'prior':p,'mode':mode,'expect':h.build_oracle(copy.deepcopy(expect),data)})
    f=h.f;search=h.search;attrs=h.attrs
    bounded=search([f('source','equals','源系统3'),f('unit','not_blank',''),f('value','gte','7'),f('value','lte','12')])
    add('R01','帮我筛出读数至少50、但还不到80摄氏度的测点。上下界别都算进去。',search([f('value','gte','50'),f('value','lt','80'),f('unit','equals','℃')]))
    add('R02','筛选源系统3的测点，单位已经填写，读数在7到12之间，两头都要包含。',bounded)
    no_upper=search(bounded['filters'][:-1]);add('R03','不设上限了，另外三条限制照旧。',no_upper,prior(bounded),'update')
    add('R04','最低值改到8，8本身也算。',search(bounded['filters'][:2]+[f('value','gte','8')]),prior(no_upper),'update')
    pair=[attrs('测量点名称81',['value','rate']),attrs('测量点名称82',['prediction','actual_low2'])]
    add('R05','第一组取测量点名称81的读数和变化速率，第二组取测量点名称82的预测值和真实值低2。',{'kind':'batch','items':pair})
    add('R06','第二组换到测量点名称83，查询字段保留。',attrs('测量点名称83',['prediction','actual_low2']),prior(*pair),'update')
    add('R07','另查温度超过65度的测点，不沿用之前的来源和开关。',{'kind':'clarify'},prior(search([f('source','equals','源系统1'),f('switch','equals','关闭')])))
    add('R08','这里明确按摄氏度计算。',search([f('value','gt','65'),f('unit','equals','℃')]),prior(search([f('value','gt','65')]),ambiguous=True),'update')
    add('R09','给我测量值小于0或者大于100的测点，满足任意一个条件就算。',{'kind':'unsupported'})
    add('R10','测量点名称11 的高2阈值是多少？',attrs('测量点名称11',['actual_high2']))
    fresh=search([f('source','equals','源系统2'),f('unit','not_blank',''),f('value','gt','11'),f('value','lte','23')])
    add('N01','只看来自源系统2的记录；单位栏得有内容，读数要比11大，最多到23。',fresh)
    fresh2=search(fresh['filters'][:2]+fresh['filters'][3:]);add('N02','现在低到多少都可以，最高值与另外两个要求继续有效。',fresh2,prior(fresh),'update')
    add('N03','单位栏填没填都接受，其余不变。',search([fresh['filters'][0],fresh['filters'][3]]),prior(fresh2),'update')
    add('N04','不接着筛刚才那批了，重新找预测值空着且开关开启的记录。',search([f('prediction','is_blank',''),f('switch','equals','开启')]),prior(fresh))
    pair2=[attrs('测量点名称101',['value','unit']),attrs('测量点名称102',['rate','estimate_high3'])]
    add('N05','测量点名称101给我读数和单位；另一个测量点名称102要变化速率和估计值高3阈值。',{'kind':'batch','items':pair2})
    add('N06','后一个不看那些了，只显示预测值。',attrs('测量点名称102',['prediction']),prior(*pair2),'update')
    add('N07','回头改第一项：同样的字段，用测量点名称103。',attrs('测量点名称103',['value','unit']),prior(*pair2),'update')
    add('N08','把已经报警但开关关着的测点找出来。',search([f('status','equals','已报警'),f('switch','equals','关闭')]))
    add('N09','源系统2里变化速率最多为负0.02的记录有哪些？',search([f('source','equals','源系统2'),f('rate','lte','-0.02')]))
    add('N10','找出读数高于37度的测点。',{'kind':'clarify'})
    add('N11','单位就用华氏度。',search([f('value','gt','37'),f('unit','equals','℉')]),prior(search([f('value','gt','37')]),ambiguous=True),'update')
    add('N12','读数不小于0，或者小于负3，这两种都要。',{'kind':'unsupported'})
    add('N13','按摄氏度查，从50起算，到70之前为止，50要、70不要。',search([f('unit','equals','℃'),f('value','gte','50'),f('value','lt','70')]))
    add('N14','不找预测值缺失的了，改为预测值等于零，来源仍不变。',search([f('source','equals','源系统2'),f('prediction','eq_num','0')]),prior(search([f('source','equals','源系统2'),f('prediction','is_blank','')])),'update')
    raw=json.dumps({'dataset':s.version,'design':'R regression; N frozen new isolated questions; same author; correct prior supplied; original-row oracle','cases':cases},ensure_ascii=False,indent=2).encode()
    OUT.mkdir(parents=True,exist_ok=True);p=OUT/'frozen.json';assert not p.exists();p.write_bytes(raw);p.with_suffix('.sha256').write_text(hashlib.sha256(raw).hexdigest(),encoding='ascii');s.db.close();print(len(cases),hashlib.sha256(raw).hexdigest())

def main():
    p=argparse.ArgumentParser();p.add_argument('--freeze',action='store_true');p.add_argument('--thinking',choices=['enabled','disabled'],default='disabled');p.add_argument('--model');p.add_argument('--effort',choices=['low','high'],default='high');p.add_argument('--rounds',type=int,default=2);p.add_argument('--run');a=p.parse_args()
    if a.freeze:return freeze()
    raw=(OUT/'frozen.json').read_bytes();assert hashlib.sha256(raw).hexdigest()==(OUT/'frozen.sha256').read_text();suite=json.loads(raw);s=Imports().load();assert s.version==suite['dataset'];out=OUT/(a.run+'.json');assert not out.exists();rows=[]
    def call(c,n):
        try:answer,trace=extract(c['question'],c['prior'],a.thinking,a.model,a.effort);return c,n,answer,trace,None
        except Exception as e:return c,n,None,None,type(e).__name__+': '+str(e)
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            futures=[pool.submit(call,c,n) for n in range(1,a.rounds+1) for c in suite['cases']]
            for future in concurrent.futures.as_completed(futures):
                c,n,answer,trace,error=future.result();checks={};response=None;plan=None
                if not error:
                    try:
                        plan,state,changed,delta=compile_checklist(answer,c['prior'],c['question'],s)
                        if plan is None:response={'status':'unsupported','answer':answer['clarification']}
                        else:response=public_result(execute_plan(s,plan));response['trace']={'validated_intent':plan}
                        checks=h.check(c['expect'],response);checks['mode']=answer['mode']==c['mode']
                    except RequestAmbiguous as e:
                        response={'status':'clarify','answer':str(e)};checks=h.check(c['expect'],response);checks['mode']=answer['mode']==c['mode']
                    except Exception as e:error=type(e).__name__+': '+str(e)
                entry={'id':c['id'],'round':n,'question':c['question'],'checks':checks,'passed':bool(checks) and all(checks.values()) and not error,'trace':trace,'plan':plan,'response':response,'error':error};rows.append(entry)
                out.write_text(json.dumps({'frozen_sha256':hashlib.sha256(raw).hexdigest(),'thinking':a.thinking,'model':a.model,'results':rows},ensure_ascii=False,indent=2),encoding='utf-8');print(c['id'],n,entry['passed'],error or checks,flush=True)
    finally:s.db.close()
    print('PASSED',sum(x['passed'] for x in rows),'/',len(rows),flush=True)
if __name__=='__main__':main()
