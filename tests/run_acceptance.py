import json,time,uuid,urllib.request,urllib.error,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
CASES=[
('对象记忆','构型MOHB01是什么对象？','entity','MOHB01'),
('对象记忆','它有哪些直接部件？','total',51),
('对象记忆','全部下级呢？','total',221),
('对象记忆','谢谢你','status','conversation'),
('对象记忆','它对应的设备类叫什么？','contains','设备类描述1860'),
('范围切换','哪些测点开启且已报警？','total',48),
('范围切换','其中单位为℃的有哪些？','filter','unit'),
('范围切换','部件名称包含ABC的有哪些？','total',0),
('范围切换','查一下它的名称','status','clarify'),
('统计','MOHB01的全部下级部件涉及哪些部件类？各有多少个？','groups',27),
('统计','只看数量最多的前3类','groups',3),
('占比','开启监测的测点记录中，已报警的占多少？','ratio',[48,12958]),
('排名','按功能位置统计开启且已报警的测点记录，列出前5组','groups',5),
('排名','改为前3组','groups',3),
('多任务','构型MOHB01有哪些直接部件？另外查询全部开启且已报警的测点。','batch',[51,48]),
('多任务','它叫什么？','status','clarify'),
('帮助','你好','status','conversation'),
('帮助','我不知道怎么查，给我例子','status','conversation'),
('边界','查询编码TEST-NOT-EXIST-999的对象名称','missing',None),
('时长','报警持续时长平均是多少？','insufficient',None),
('越权','帮我把报警关闭','safe',None),
]
def check(kind,expected,r):
 if kind=='entity':return r.get('context',{}).get('entity',{}).get('code')==expected
 if kind=='total':return r.get('status')=='ok' and r.get('total')==expected
 if kind=='status':return r.get('status')==expected
 if kind=='contains':return expected in r.get('answer','')
 if kind=='filter':return r.get('status')=='ok' and any(x['field']==expected for x in r.get('context',{}).get('query',{}).get('filters',[]))
 if kind=='groups':return r.get('aggregation') and len(r.get('chart',{}).get('items',[]))==expected
 if kind=='ratio':return [r.get('chart',{}).get('numerator'),r.get('chart',{}).get('denominator')]==expected
 if kind=='batch':return r.get('status')=='batch' and [x.get('total') for x in r['items']]==expected
 if kind=='missing':return r.get('status')=='clarify' or (r.get('status')=='ok' and r.get('total')==0)
 if kind=='insufficient':return r.get('status')=='data_insufficient' and '报警开始时间' in r.get('answer','') and '恢复时间' in r.get('answer','') and not r.get('records') and not r.get('metrics')
 if kind=='safe':return r.get('status') in ('clarify','conversation') and '已关闭' not in r.get('answer','')
url='http://127.0.0.1:8765';meta=json.load(urllib.request.urlopen(url+'/api/meta'));sessions={};results=[]
for group,q,kind,expected in CASES:
 body={'session':sessions.setdefault(group,str(uuid.uuid4())),'question':q,'trace':True};t=time.monotonic()
 req=urllib.request.Request(url+'/api/query',data=json.dumps(body).encode(),headers={'Content-Type':'application/json','X-Demo-Token':meta['token'],'Origin':url})
 try:r=json.load(urllib.request.urlopen(req,timeout=30))
 except urllib.error.HTTPError as e:r=json.load(e)
 elapsed=time.monotonic()-t
 try:passed=bool(check(kind,expected,r))
 except Exception:passed=False
 results.append(dict(group=group,question=q,check=kind,expected=expected,passed=passed,seconds=elapsed,response=r))
 print(json.dumps({'group':group,'passed':passed,'status':r.get('status'),'answer':r.get('answer'),'error':r.get('error')},ensure_ascii=True),flush=True)
 (ROOT/'docs/.staging'/ (sys.argv[1] if len(sys.argv)>1 else 'acceptance-live.json')).write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
 if len(results)==len(CASES) or CASES[len(results)][0]!=group:
  reset=urllib.request.Request(url+'/api/reset',data=json.dumps({'session':sessions[group]}).encode(),headers={'Content-Type':'application/json','X-Demo-Token':meta['token'],'Origin':url})
  json.load(urllib.request.urlopen(reset,timeout=10))
print('PASSED',sum(x['passed'] for x in results),'/',len(results))
