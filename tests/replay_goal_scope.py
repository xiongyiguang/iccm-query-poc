"""本机真实模型范围回放；独立遍历原始PBS父链，不以执行器生成预期。"""
import argparse,csv,hashlib,json,time,urllib.request,urllib.error,urllib.parse,uuid
from pathlib import Path

parser=argparse.ArgumentParser()
parser.add_argument('--url',required=True);parser.add_argument('--output-dir',required=True)
args=parser.parse_args();url=args.url.rstrip('/')
if urllib.parse.urlparse(url).hostname not in ('127.0.0.1','localhost'):parser.error('仅允许本机隔离服务')
root=Path(__file__).resolve().parents[1];out=Path(args.output_dir).resolve();out.mkdir(parents=True,exist_ok=False)
data=root.parent/'中广核iCCM项目智能问数DEMO脱敏数据'
with (data/'pbs.csv').open(encoding='gb18030') as f:pbs=list(csv.DictReader(f))
with (data/'测量点数据分析.csv').open(encoding='gb18030') as f:points=list(csv.DictReader(f))
code='XJ2ABC002MO&MOHB01';name=next(r['对象描述中文'] for r in pbs if r['对象代码']==code)
children={}
for r in pbs:children.setdefault(r['父对象代码'],[]).append(r['对象代码'])
desc={code};todo=[code]
while todo:
 for child in children.get(todo.pop(),[]):
  if child not in desc:desc.add(child);todo.append(child)
scoped=[r for r in points if r['测量点编码'] in desc]
cases=[
 {'id':'scope-code','question':f'PBS对象{code}范围内的测点记录有多少条','total':len(scoped)},
 {'id':'scope-name','question':f'PBS对象名称{name}下面的测点记录共有多少条','total':len(scoped)},
 {'id':'scope-filter','question':f'PBS对象{code}范围内，源系统1的测点记录有多少条','total':sum(r['源系统']=='源系统1' for r in scoped)},
 {'id':'scope-status','question':f'PBS对象{code}范围内，状态为已报警的测点记录有多少条','total':sum(r['状态']=='已报警' for r in scoped)},
 {'id':'point-identity','question':'PBS测量点XJ2ABC001MO.TMP.2ABC109MT.BBe的测量值是多少','point':next(r for r in points if r['测量点编码']=='XJ2ABC001MO.TMP.2ABC109MT.BBe')}
]
meta=json.load(urllib.request.urlopen(url+'/api/meta'))
def post(path,body):
 req=urllib.request.Request(url+path,data=json.dumps(body).encode(),headers={'Content-Type':'application/json','Origin':url,'X-Demo-Token':meta['token']})
 try:
  with urllib.request.urlopen(req,timeout=150) as res:return res.status,json.load(res)
 except urllib.error.HTTPError as err:return err.code,json.load(err)
manifest={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for d in ('backend','frontend','prompts') for p in (root/d).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.name!='.DS_Store'}
(out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2));(out/'cases.json').write_text(json.dumps(cases,ensure_ascii=False,indent=2))
entries=[]
for c in cases:
 sid='scope-'+uuid.uuid4().hex
 try:
  started=time.monotonic();http,r=post('/api/query',{'session':sid,'question':c['question'],'version':meta['version'],'trace':True})
  ok=http==200 and r.get('status')=='ok'
  if 'total' in c:ok=ok and r.get('total')==c['total'] and r.get('entity')=={'tree':'pbs','code':code} and '自身及全部后代' in r.get('business_scope','')
  else:ok=ok and r.get('entity',{}).get('code')==c['point']['测量点编码'] and any(a.get('property')=='value' and a.get('value')==c['point']['测量值'] for a in r.get('attributes',[]))
  entry={**c,'http':http,'seconds':round(time.monotonic()-started,3),'passed':bool(ok),'response':r};entries.append(entry)
  (out/'results.json').write_text(json.dumps({'version':meta['version'],'results':entries},ensure_ascii=False,indent=2))
  print(json.dumps({'id':c['id'],'passed':bool(ok),'total':r.get('total'),'status':r.get('status'),'answer':r.get('answer'),'seconds':entry['seconds']},ensure_ascii=False),flush=True)
 finally:post('/api/reset',{'session':sid})
print('Passed',sum(e['passed'] for e in entries),'/',len(entries))
if not all(e['passed'] for e in entries):raise SystemExit(1)
