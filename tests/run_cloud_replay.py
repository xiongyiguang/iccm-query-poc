"""通过鉴权公网 HTTP 接口运行冻结查询测试集。

只读取本地凭据，不记录其内容；只清理本脚本创建的会话。
原问句和断言保持不变，包含已知的 V1 误报。"""
import argparse,http.cookiejar,json,runpy,sys,urllib.request,urllib.error
from pathlib import Path

def main():
 p=argparse.ArgumentParser();p.add_argument('--url',required=True);p.add_argument('--output-dir',required=True);args=p.parse_args()
 root=Path(__file__).resolve().parents[1];out=Path(args.output_dir);out.mkdir(parents=True,exist_ok=True)
 credentials={k.strip():v.strip() for line in (root/'.local/cloud-8899-access.txt').read_text(encoding='utf-8-sig').splitlines() if ':' in line for k,v in [line.split(':',1)]}
 jar=http.cookiejar.CookieJar();opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
 def request(path,body,token=None):
  headers={'Content-Type':'application/json','Origin':args.url}
  if token:headers['X-Demo-Token']=token
  return urllib.request.Request(args.url+path,data=json.dumps(body).encode(),headers=headers)
 with opener.open(request('/api/auth/login',{'username':credentials['Username'],'password':credentials['Password']})) as response:
  if response.status!=200:raise RuntimeError('Login failed')
 credentials.clear();meta=json.load(opener.open(args.url+'/api/meta'));sessions=set();original=urllib.request.urlopen
 def authenticated(req,*pos,**kw):
  if isinstance(req,urllib.request.Request) and req.full_url.startswith(args.url+'/api/query'):
   sessions.add(json.loads(req.data)['session'])
  return opener.open(req,*pos,**kw)
 urllib.request.urlopen=authenticated
 summary=[]
 try:
  for name,extra in [('replay_team_feedback.py',['--output',str(out/'original.json')]),('replay_team_feedback_extended.py',['--output-dir',str(out/'extended')]),('replay_team_feedback_followup.py',['--output-dir',str(out/'followup')])]:
   for folder in [out/'extended',out/'followup']:folder.mkdir(exist_ok=True)
   sys.argv=[name,'--url',args.url]+extra
   try:runpy.run_path(str(root/'tests'/name),run_name='__main__');code=0
   except SystemExit as exc:code=exc.code
   summary.append({'suite':name,'exit':code});print(json.dumps(summary[-1]),flush=True)
   # 释放本脚本创建的测试会话，保留原始多轮顺序。
   for sid in sorted(sessions):opener.open(request('/api/reset',{'session':sid},meta['token'])).close()
   sessions.clear()
 finally:
  urllib.request.urlopen=original
  for sid in sorted(sessions):opener.open(request('/api/reset',{'session':sid},meta['token'])).close()
  opener.open(request('/api/auth/logout',{},meta['token'])).close()
  (out/'query-summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
if __name__=='__main__':main()
