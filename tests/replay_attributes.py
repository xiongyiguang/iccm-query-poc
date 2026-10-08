"""有限范围的真实模型回归，保存响应但不保存凭据。"""
import json,sys,uuid,urllib.request,urllib.error,time
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')
url=sys.argv[1] if len(sys.argv)>1 else 'http://127.0.0.1:8767'
output=Path(__file__).resolve().parents[1]/'docs/.staging'/ (sys.argv[2] if len(sys.argv)>2 else 'attributes-v11-live.json')
if output.exists():raise SystemExit('Evidence exists; choose a new filename.')
meta=json.load(urllib.request.urlopen(url+'/api/meta'));sessions={};results=[]
cases=[
 ('original','这个 PBS对象名称：XXXX2834 是什么类型的对象','property',{'type':'时序测点'}),
 ('original','什么类型的','property',{'type':'时序测点'}),
 ('original','我不是问名字，我想知道它属于哪种对象','property',{'type':'时序测点'}),
 ('original','它叫什么名字','property',{'name':'XXXX2834'}),
 ('original','那它具体测什么物理量','unsupported',None),
 ('original','它的父对象编码是什么','property',{'parent':'XJ2ABC002MO'}),
 ('new','构型MOHB01的类型和层级分别是什么','property',{'type':'设备','level':'4'}),
 ('new','改查PBS对象XXXX2834，告诉我名称、编码和类型','property',{'name':'XXXX2834','code':'XJ2ABC002MO.MDI.2ABC002MM.Axi_X','type':'时序测点'}),
 ('point','测量点名称5属于哪种PBS对象','property',{'type':'时序测点'}),
 ('missing','测量点名称5的预测值是多少','missing','prediction'),
 ('absent','PBS名称不存在XYZ的对象类型是什么','clarify',None),
 ('many','名称包含XXXX28的PBS对象是什么类型','clarify',None),
 ('conflict','XJ2ABC001PO.MFB.2ABC029MV.LBe_Y的测量值是多少','values',{'6','0'}),
 ('conflict','只看源系统3，它的来源和时间是什么','property',{'source':'源系统3','time':'2024/3/20 9:19'}),
 ('historic','测量点名称11的数值和阈值是多少','threshold',None),
 ('historic','它叫什么','property',{'name':'测量点名称11'}),
 ('count','所有已报警测点有多少条记录','count',48),
 ('structure','构型MOHB01有哪些直接部件','count',51),
 ('structure','它是什么类型','property',{'type':'设备'}),
 ('batch','PBS对象XXXX2834是什么类型？另外构型MOHB01有哪些直接部件？','batch',None),
 ('duration','所有报警的平均持续时长是多少','insufficient',None),
]
def request(path,body):
 req=urllib.request.Request(url+path,data=json.dumps(body,ensure_ascii=False).encode(),headers={'Content-Type':'application/json','X-Demo-Token':meta['token'],'Origin':url})
 try:return json.load(urllib.request.urlopen(req,timeout=45))
 except urllib.error.HTTPError as e:return json.load(e)
for group,q,kind,expected in cases:
 start=time.perf_counter();r=request('/api/query',dict(session=sessions.setdefault(group,str(uuid.uuid4())),question=q,trace=True))
 facts=r.get('attributes',[]);passed=False
 if kind=='property':passed=r.get('status')=='ok' and all(any(f['property']==k and f['value']==v and f['status']=='known' for f in facts) for k,v in expected.items()) and r.get('coverage',{}).get('complete') is True
 elif kind=='unsupported':passed=any(f['property']=='physical_quantity' and f['status']=='unsupported' for f in facts)
 elif kind=='missing':passed=any(f['property']==expected and f['status']=='missing' for f in facts)
 elif kind=='clarify':passed=r.get('status')=='clarify'
 elif kind=='values':passed=({f['value'] for f in facts if f['property']=='value'}==expected or {x['value'] for x in r.get('records',[])}==expected)
 elif kind=='threshold':passed=r.get('status')=='ok' and len(r.get('threshold_details',[]))==1 and r['metrics'][2]['value']=='6.69898987'
 elif kind=='count':passed=r.get('status')=='ok' and r.get('total')==expected
 elif kind=='insufficient':passed=r.get('status')=='data_insufficient' and '缺少报警开始时间和恢复时间' in r['answer']
 elif kind=='batch':passed=r.get('status')=='batch' and len(r['items'])==2 and any(f['property']=='type' and f['value']=='时序测点' for f in r['items'][0].get('attributes',[])) and r['items'][1]['total']==51
 results.append(dict(question=q,kind=kind,expected=sorted(expected) if isinstance(expected,set) else expected,passed=bool(passed),elapsed_seconds=round(time.perf_counter()-start,3),response=r))
 output.write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps({k:results[-1][k] for k in ['question','passed','elapsed_seconds']},ensure_ascii=False),r.get('answer',r.get('error')),flush=True)
for session in sessions.values():request('/api/reset',{'session':session})
print('PASSED',sum(x['passed'] for x in results),'/',len(results))
sys.exit(0 if all(x['passed'] for x in results) else 1)
