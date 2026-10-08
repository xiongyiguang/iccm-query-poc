"""冻结两份数据开发团队反馈中的问句转录，执行真实云端回放。

截图原问句与补建前文、补充测试分别标注。
此脚本不改变应用代码或原始数据。"""
import argparse, collections, http.cookiejar, json, sys, time, uuid, urllib.request, urllib.error
from decimal import Decimal, InvalidOperation
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'docs/.staging/zhou-two-rounds-retest-20260923'
POINT='XJ2ABC001MO.TMP.2ABC109MT.BBe'
POINT4='XJ3ABC002MO.TMP.3ABC112MT.U_Win_H1'
CASES=[]
def case(id,feedback,group,question,expect,source='原图问句',selection=None):
    CASES.append(dict(id=id,feedback=feedback,group=group,question=question,expect=expect,source=source,selection=selection))

case('A01a','一-1','context','介绍下XXXX1','clarify')
case('A01b','一-1','context','PBS','xxxx1')
case('A01c','一-1','context','介绍下PBS的XXXX1','xxxx1')
case('A03','一-3','rate','查询测点 XJ1ABC001PO.JVD.1ABC029MV.LBe_Y 的全部属性','rate','原图仅有结果，按截图对象补建查询')
case('A04a','一-4','groups','按对象层级统计对象编码','clarify')
case('A04b','一-4','groups','按PBS','pbs_groups')
case('A04c','一-4','groups','统计PBS各层级对象数量','pbs_groups')
case('A05a','一-5','spoken','构型 MOHB01 是什么对象？','config')
case('A05b','一-5','spoken','构型对象代码 MOHB01 是什么对象？','config')
case('A06a','一-6','partial','2ABC109MT 这个测点现在多少度？','candidate')
case('A06b','一-6','partial','就这个，继续刚才的问题','point_value','补充：点选原图完整测点后继续',{'tree':'pbs','code':POINT})
case('A06c','一-6','partial','XJ2ABC001MO.TMP.2ABC109MT.BBe 这个测点现在多少度？','point_value')
case('B01','二-1','high2','测量点名称11 的高2阈值是多少？','high2')
case('B02a','二-2','explain','构型 MOHB01 的直接部件有哪些','parts','原图可见焦点MOHB01；完整前文缺失，补建前置')
case('B02b','二-2','explain','你是如何判断它的下级部件的','explain')
case('B03a','二-3','fresh','MOHB 那个设备是什么？','mohb_candidates')
case('B03b','二-3','old','构型 MOHB01 是什么对象？','config','旧会话完整前文缺失，补建构型前文对照')
case('B03c','二-3','old','MOHB 那个设备是什么？','mohb_candidates','原图问句；补建旧会话对照')
case('B03d','二-3','old','设备类描述1860 对应哪个设备类？','class','补充：变换到设备类前文')
case('B03e','二-3','old','MOHB 那个设备是什么？','mohb_candidates','原图问句；补建设备类前文对照')
case('B05','二-5','class','设备类描述1860 对应哪个设备类？','class')
case('B06','二-6','location','哪些功能位置测点最多，前3','top3')
case('B07a','二-7','colloquial','MOHB01 下面有多少东西？','count_clarify')
case('B07b','二-7','colloquial','我指的是构型树MOHB01的全部下级对象，总共有多少个？','descendants','补充：明确对象域与统计范围')
case('B07c','二-7','numeric','哪些点的测量值超过了60度','numeric_ambiguous')
case('B07d','二-7','numeric','单位是摄氏度','numeric_celsius','补充：明确单位')
case('B07e','二-7','typo','测量点名称11的高2阀值是多少','high2','补充错字样本；原件未提供具体错字原句')
case('B08a','二-8','thresholds','监测点XJ3ABC002MO.TMP.3ABC112MT.U_Win_H1的情况','point4')
case('B08b','二-8','thresholds','阈值是多少','all_thresholds')

def oracle():
    sys.path.insert(0,str(ROOT/'backend'))
    from importer import Imports
    s=Imports().load();data={f['kind']:f['rows'] for f in s.dataset}
    # 独立遍历原始记录，不复用应用查询或聚合实现。
    pbs={r['对象代码']:r for r in data['pbs']};cfg={r['对象代码']:r for r in data['config']}
    loc=collections.Counter();desc=[]
    for row in data['points']:
        key=row['测量点编码'];seen=set()
        while key in pbs and pbs[key]['对象层级']!='功能位置' and key not in seen:
            seen.add(key);key=pbs[key]['父对象代码']
        loc[key if key in pbs and pbs[key]['对象层级']=='功能位置' else '']+=1
    for key in cfg:
        code=cfg[key]['父对象代码'];seen=set()
        while code in cfg and code not in seen:
            if code=='MOHB01':desc.append(key);break
            seen.add(code);code=cfg[code]['父对象代码']
    celsius=0
    for row in data['points']:
        try:valid=Decimal(row['测量值']).is_finite() and Decimal(row['测量值'])>60
        except InvalidOperation:valid=False
        if valid and row['单位'] in ('℃','°C','摄氏度'):celsius+=1
    threshold_rows=[{k:v.strip() or '未提供' for k,v in r.items() if '报警阈值-' in k} for r in data['points'] if r['测量点编码']==POINT4]
    result={'version':s.version,'pbs_levels':dict(collections.Counter(r['对象层级'] for r in data['pbs'])),
            'top3':sorted(loc.items(),key=lambda x:(-x[1],x[0]))[:3],
            'descendant_count':len(desc),'celsius_over60':celsius,'point4_thresholds':threshold_rows,
            'high2':[r['真实值报警阈值-高2'] for r in data['points'] if r['测量点编码']==POINT],
            'rate':[r['变化速率'] for r in data['points'] if r['测量点编码']=='XJ1ABC001PO.JVD.1ABC029MV.LBe_Y']}
    s.db.close();return result

def check(c,r,o):
    kind=c['expect'];ok=r.get('status')=='ok';e=r.get('entity') or {};records=r.get('records',[])
    attr={a['property']:a for a in r.get('attributes',[])};q=r.get('query') or {};filters=q.get('filters',[])
    if kind=='clarify':return r.get('status')=='clarify'
    if kind=='xxxx1':return ok and e=={'tree':'pbs','code':'XJ3ABC002RR&RRGA02.Zaf.IDS'}
    if kind=='rate':return ok and attr.get('rate',{}).get('display_value')==format(Decimal(o['rate'][0]),'f') and {family+'_'+side+str(n) for family in ('actual','estimate','rate_deviation') for side in ('low','high') for n in (1,2,3)}<=set(attr)
    if kind=='pbs_groups':return ok and {str(x['cells'][0]):x['cells'][-1] for x in records}==o['pbs_levels']
    if kind=='config':return ok and e=={'tree':'config','code':'MOHB01'} and '设备' in r['answer']
    if kind=='candidate':return r.get('status')=='ambiguous' and r.get('candidate_only') and any(x['code']==POINT for x in records) and all('value' not in x for x in records)
    if kind=='point_value':return ok and e.get('code')==POINT and attr.get('value',{}).get('display_value')=='40.69898987' and attr.get('unit',{}).get('status')=='missing' and attr.get('unit',{}).get('value')=='' and any(ref.get('fields',{}).get('单位')=='' for ref in attr['unit'].get('evidence',[]))
    if kind=='high2':
        if r.get('attributes'):
            return ok and r.get('requested_properties')==['actual_high2'] and attr['actual_high2']['value']==o['high2'][0] and any(ref.get('fields',{}).get('真实值报警阈值-高2')==o['high2'][0] for ref in attr['actual_high2'].get('evidence',[]))
        return ok and r.get('requested_thresholds')==['actual_high2'] and list(r['threshold_details'][0]['thresholds'].values())==o['high2']
    if kind=='parts':return ok and e=={'tree':'config','code':'MOHB01'} and all(x.get('parent')=='MOHB01' for x in records)
    if kind=='explain':return r.get('status')=='conversation' and 'MOHB01' in r['answer'] and ('父编码' in r['answer'] or '父引用' in r['answer']) and bool(r.get('evidence'))
    if kind=='mohb_candidates' and c['id']=='B03e':return ok and e=={'tree':'equipment_class','code':'MOHB'}  # 同一已明确建立的主体，当前契约保留其对象域。
    if kind=='mohb_candidates':return r.get('status')=='ambiguous' and {(x['tree'],x['code']) for x in records}=={('config','MOHB'),('equipment_class','MOHB')}
    if kind=='class':return ok and e=={'tree':'equipment_class','code':'MOHB'}
    if kind=='top3':return ok and [(x['cells'][1],x['cells'][2]) for x in records]==[tuple(x) for x in o['top3']] and r['evidence_total']==12985
    if kind=='count_clarify':return r.get('status')=='clarify' and ('下级' in r['answer'] or '部件' in r['answer'])
    if kind=='descendants':return ok and (r.get('total')==o['descendant_count'] or any(str(m.get('value'))==str(o['descendant_count']) for m in r.get('metrics',[])))
    if kind=='numeric_ambiguous':return r.get('status')=='clarify'  # V23 中含糊的“度”必须澄清，不能静默丢弃单位条件。
    if kind=='numeric_celsius':return ok and r.get('total')==o['celsius_over60'] and {'field':'value','operator':'gt','value':'60'} in filters and any(f['field']=='unit' and f['value']=='℃' for f in filters)
    if kind=='point4':return ok and e.get('code')==POINT4
    if kind=='all_thresholds':
        if r.get('attributes'):
            facts=[a for a in r['attributes'] if '报警阈值-' in a.get('field','')]
            values={a['field']:a['value'] or '未提供' for a in facts}
            return ok and [values]==o['point4_thresholds'] and len(facts)==18 and '128' in r['answer'] and all(a.get('evidence') for a in facts)
        return ok and [x['thresholds'] for x in r.get('threshold_details',[])]==o['point4_thresholds'] and '128' in r['answer']
    raise ValueError(kind)

def main():
    global OUT
    p=argparse.ArgumentParser();p.add_argument('--rounds',type=int,default=3);p.add_argument('--prepare',action='store_true');p.add_argument('--url',default='http://106.53.130.181:8899');p.add_argument('--output-dir',type=Path,default=OUT);args=p.parse_args();OUT=args.output_dir
    if (OUT/'api-results.json').exists():raise SystemExit('Evidence exists; choose a new --output-dir to preserve the frozen run.')
    OUT.mkdir(parents=True,exist_ok=True);o=oracle()
    (OUT/'oracle.json').write_text(json.dumps(o,ensure_ascii=False,indent=2),encoding='utf-8')
    (OUT/'cases.json').write_text(json.dumps(CASES,ensure_ascii=False,indent=2),encoding='utf-8')
    if args.prepare:return
    base=args.url;opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()));meta={}
    def post(path,body):
        h={'Content-Type':'application/json','Origin':base}
        if meta:h['X-Demo-Token']=meta['token']
        try:
            with opener.open(urllib.request.Request(base+path,data=json.dumps(body).encode(),headers=h),timeout=180) as res:return res.status,json.load(res)
        except urllib.error.HTTPError as error:return error.code,json.load(error)
    creds={k.strip():v.strip() for line in (ROOT/'.local/cloud-8899-access.txt').read_text(encoding='utf-8-sig').splitlines() if ':' in line for k,v in [line.split(':',1)]}
    if not base.startswith('http://127.0.0.1'):assert post('/api/auth/login',{'username':creds['Username'],'password':creds['Password']})[0]==200
    creds.clear()
    meta=json.load(opener.open(base+'/api/meta'));assert meta['version']==o['version'];results=[];sessions=set()
    try:
        for n in range(1,args.rounds+1):
            prefix='zhou-original-'+uuid.uuid4().hex[:10]
            for c in CASES:
                sid=prefix+'-'+c['group'];sessions.add(sid);start=time.perf_counter()
                code,r=post('/api/query',{'session':sid,'question':c['question'],'selection':c['selection'],'version':meta['version'],'trace':True})
                try:passed=bool(check(c,r,o))
                except (ValueError,KeyError,TypeError,IndexError):passed=False
                entry={**c,'round':n,'http_status':code,'passed':passed,'seconds':round(time.perf_counter()-start,3),'response':r};results.append(entry)
                (OUT/'api-results.json').write_text(json.dumps({'version':meta['version'],'results':results},ensure_ascii=False,indent=2),encoding='utf-8')
                print(json.dumps({k:entry[k] for k in ('id','round','passed','seconds')},ensure_ascii=False),flush=True)
                if not passed:print(json.dumps({'answer':r.get('answer',r.get('error')),'query':r.get('query'),'entity':r.get('entity')},ensure_ascii=False),flush=True)
            for sid in sessions:post('/api/reset',{'session':sid})
            sessions.clear()
    finally:
        for sid in sessions:post('/api/reset',{'session':sid})
        if not base.startswith('http://127.0.0.1'):post('/api/auth/logout',{})
    print('Passed',sum(x['passed'] for x in results),'/',len(results))
if __name__=='__main__':main()
