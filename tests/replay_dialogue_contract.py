"""预先声明的多轮对话场景，预期来自原始导入记录。"""
import argparse,hashlib,json,math,statistics,sys,time,uuid
from pathlib import Path
from replay_acceptance import Client
ROOT=Path(__file__).resolve().parents[1]
BASIC=['name','code','type','level','parent']
PAIR=['name','code']
RAW={
    'pbs':{'name':'对象描述中文','code':'对象代码','level':'对象层级','parent':'父对象代码','type':'对象层级'},
    'config':{'name':'对象描述中文','code':'对象代码','level':'对象层级','parent':'父对象代码','type':'对象层级描述'},
    'equipment_class':{'name':'描述','code':'对象编码','level':'层级','parent':'父对象编码'},
    'part_class':{'name':'对象描述中文','code':'对象编码','level':'对象层级','parent':'父对象编码'}}
def cases():
    a=[]
    def add(group,q,kind,tree=None,code=None,props=None,selection=None):
        a.append(dict(id='D'+str(len(a)+1).zfill(2),group=group,question=q,
                      expect=dict(kind=kind,tree=tree,code=code,properties=props),selection=selection))
    add('intro','先给我介绍一下XXXX1。','clarify')
    add('intro','在PBS树。','attributes','pbs','XJ3ABC002RR&RRGA02.Zaf.IDS',BASIC)
    add('intro','只看刚才对象的名称和编码。','attributes','pbs','XJ3ABC002RR&RRGA02.Zaf.IDS',PAIR)
    add('switch','设备类的设备类描述3510是什么对象，只看名称和编码。','attributes','equipment_class','MOHB01',PAIR)
    add('switch','MOHB01那个设备的名称和编码再给我看下。','attributes','equipment_class','MOHB01',PAIR)
    add('switch','换到构型树，查同一编码的名称和编码。','attributes','config','MOHB01',PAIR)
    add('switch','MOHB现在对应哪一个对象？只给名称和编码。','ambiguous',code='MOHB',props=PAIR)
    add('switch','就选择这个对象，继续刚才两个字段。','attributes','equipment_class','MOHB',PAIR,{'tree':'equipment_class','code':'MOHB'})
    add('switch','它的名称和编码。','attributes','equipment_class','MOHB',PAIR)
    add('switch','另起一个查询：构型KOHA30的名称和编码。','attributes','config','KOHA30',PAIR)
    add('switch','现在在所有对象树里找MOHB01，显示名称和编码。','ambiguous',code='MOHB01',props=PAIR)
    add('missing','请介绍PBS里的NO_SUCH_OBJECT_82946。','not_found','pbs','NO_SUCH_OBJECT_82946',BASIC)
    add('explicit','给我介绍一下设备类描述1860，范围是设备类树。','attributes','equipment_class','MOHB',BASIC)
    add('explicit','改看构型里的MOHB，仍然只介绍它的基本信息。','attributes','config','MOHB',BASIC)
    return a

def replacement_cases():
    a=[]
    def obj(tree,code,props):return dict(kind='attributes',tree=tree,code=code,properties=props)
    def add(q,e,unchanged=()):a.append(dict(id='R'+str(len(a)+1).zfill(2),group='branches',question=q,expect=e,selection=None,unchanged_tasks=list(unchanged)))
    add('分别查构型MOHB01的名称与编码，以及设备类MOHB的名称与编码。',{'kind':'batch','items':[obj('config','MOHB01',PAIR),obj('equipment_class','MOHB',PAIR)]})
    add('第一项换成设备类树，编码和字段都沿用；第二项别动。',obj('equipment_class','MOHB01',PAIR),(2,))
    add('再把第二项改到构型树，仍用那一项的编码；第一项保持。',obj('config','MOHB',PAIR),(1,))
    add('回到第一项，只返回名称。',obj('equipment_class','MOHB01',['name']),(2,))
    add('第二项只要编码。',obj('config','MOHB',['code']),(1,))
    add('第一项回构型树，保留现在的字段。',obj('config','MOHB01',['name']),(2,))
    add('新开一组：分别查构型MOHB01的编码和设备类MOHB的编码。',{'kind':'batch','items':[obj('config','MOHB01',['code']),obj('equipment_class','MOHB',['code'])]})
    add('只把第一项改为设备类树，保留编码；另一项别改。',obj('equipment_class','MOHB01',['code']),(2,))
    add('第二项现在改查设备类MOHB01的名称。',obj('equipment_class','MOHB01',['name']),(1,))
    add('第一项只要父对象编码。',obj('equipment_class','MOHB01',['parent']),(2,))
    return a

def freeze(path,suite='base'):
    sys.path.insert(0,str(ROOT/'backend'))
    from importer import Imports
    s=Imports().load()
    data={item['kind']:item['rows'] for item in s.dataset}
    result={'version':s.version,'cases':replacement_cases() if suite=='replacement' else cases(),'oracle_source':'original imported rows; exact object identities and field values'}
    def expected(e):
        if e['kind']=='batch':
            for item in e['items']:expected(item)
        if e['kind']=='attributes':
            rows=[r for r in data[e['tree']] if r[RAW[e['tree']]['code']]==e['code']]
            assert len(rows)==1
            e['source_row']=rows[0]
        elif e['kind']=='ambiguous':
            e['candidates']=[{'tree':tree,'code':r[RAW[tree]['code']],'name':r[RAW[tree]['name']]} for tree in RAW for r in data[tree] if r[RAW[tree]['code']]==e['code']]
            assert len(e['candidates'])>1
        elif e['kind']=='not_found':
            assert not any(r[RAW[e['tree']]['code']]==e['code'] or r[RAW[e['tree']]['name']]==e['code'] for r in data[e['tree']])
    for c in result['cases']:expected(c['expect'])
    s.db.close()
    assert not path.exists()
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    path.with_suffix('.sha256').write_text(hashlib.sha256(path.read_bytes()).hexdigest(),encoding='ascii')
    return result

def check(e,r,status,root_trace=None):
    checks={'http':status==200}
    kind=e['kind']
    if kind=='batch':
        items=r.get('items',[]);checks['batch']=r.get('status')=='batch' and len(items)==len(e['items'])
        for n,(expected,item) in enumerate(zip(e['items'],items),1):
            checks.update({str(n)+'_'+k:v for k,v in check(expected,item,status,r.get('trace')).items()})
        return checks
    if kind=='clarify':checks['status']=r.get('status')=='clarify';return checks
    if kind=='not_found':checks['status']=r.get('status')=='not_found';checks['no_records']=not r.get('records');return checks
    if kind=='ambiguous':
        checks['status']=r.get('status')=='ambiguous'
        checks['candidates']=sorted((x.get('tree'),x.get('code'),x.get('name')) for x in r.get('records',[]))==sorted((x['tree'],x['code'],x['name']) for x in e['candidates'])
        return checks
    checks['status']=r.get('status')=='ok'
    checks['entity']=r.get('entity')=={'tree':e['tree'],'code':e['code']}
    checks['projection']=set(r.get('requested_properties',[]))==set(e['properties'])
    attrs={x['property']:x for x in r.get('attributes',[])}
    fields=RAW[e['tree']]
    for prop in e['properties']:
        if prop not in fields:
            checks[prop+'_unsupported']=prop in attrs and attrs[prop].get('status')=='unsupported'
            continue
        expected=e['source_row'][fields[prop]]
        checks[prop]=prop in attrs and attrs[prop].get('value')==expected
        if expected:
            checks[prop+'_evidence']=any(x.get('fields',{}).get(fields[prop])==expected for x in attrs.get(prop,{}).get('evidence',[]))
    checks['compiler']=(r.get('trace') or root_trace or {}).get('engine')=='business_request'
    return checks

def main():
    p=argparse.ArgumentParser();p.add_argument('--freeze',type=Path,required=True);p.add_argument('--prepare-only',action='store_true');p.add_argument('--suite',choices=['base','replacement'],default='base');p.add_argument('--output-dir',type=Path);p.add_argument('--rounds',type=int,default=2);p.add_argument('--url',default='http://127.0.0.1:8769');args=p.parse_args()
    if args.prepare_only:prepared=freeze(args.freeze,args.suite);print('Frozen',len(prepared['cases']),'scenarios');return
    digest=hashlib.sha256(args.freeze.read_bytes()).hexdigest();assert digest==args.freeze.with_suffix('.sha256').read_text().strip()
    frozen=json.loads(args.freeze.read_text(encoding='utf-8'));client=Client(args.url);assert client.meta['version']==frozen['version']
    assert args.output_dir is not None
    args.output_dir.mkdir(parents=True,exist_ok=True);path=args.output_dir/'results.json';assert not path.exists()
    manifest={str(x.relative_to(ROOT)):hashlib.sha256(x.read_bytes()).hexdigest() for folder in ('backend','prompts','tests') for x in (ROOT/folder).rglob('*') if x.is_file() and x.suffix in ('.py','.txt','.json','.cjs')}
    d={'frozen_sha256':digest,'version':frozen['version'],'source_manifest':manifest,'results':[]}
    def save():path.write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding='utf-8')
    save()
    for n in range(1,args.rounds+1):
        prefix='dialogue-'+uuid.uuid4().hex[:12];sessions=set();contexts={}
        try:
            for c in frozen['cases']:
                sid=prefix+'-'+c['group'];sessions.add(sid);start=time.monotonic()
                status,r=client.call('/api/query',{'session':sid,'question':c['question'],'version':frozen['version'],'trace':True,**({'selection':c['selection']} if c['selection'] else {})})
                x={**c,'round':n,'http':status,'seconds':round(time.monotonic()-start,3),'response':r,'passed':False};d['results'].append(x);save()
                try:
                    checks=check(c['expect'],r,status)
                    old_tasks=contexts.get(sid,{}).get('business_request',{}).get('tasks',[])
                    new_tasks=(r.get('context') or {}).get('business_request',{}).get('tasks',[])
                    for task_number in c.get('unchanged_tasks',[]):
                        before=old_tasks[task_number-1] if len(old_tasks)>=task_number else None
                        checks['unchanged_task_'+str(task_number)]=before is not None and next((t for t in new_tasks if t['id']==before['id']),None)==before
                except (ValueError,TypeError,KeyError,IndexError) as err:checks={'validation_error':str(err)}
                if 'context' in r:contexts[sid]=r['context']
                x.update(checks=checks,passed=all(v is True for v in checks.values()));save()
                print(c['id'],n,x['passed'],x['seconds'],checks,flush=True)
        finally:
            for sid in sessions:client.call('/api/reset',{'session':sid})
    times=sorted(x['seconds'] for x in d['results'])
    d['summary']={'passed':sum(x['passed'] for x in d['results']),'total':len(times),'p50':statistics.median(times),'p95':times[math.ceil(len(times)*.95)-1],'max':max(times),'over5':sum(x>5 for x in times)}
    save();print(json.dumps(d['summary']),flush=True)

if __name__=='__main__':main()
