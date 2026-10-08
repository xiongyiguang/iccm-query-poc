#!/usr/bin/env python3
import os,subprocess,pathlib,urllib.request,json,time,sys
ROOT=pathlib.Path(__file__).resolve().parents[1]
PY=pathlib.Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3'
if not PY.is_file():
 PY=pathlib.Path(sys.executable)
URL='http://127.0.0.1:8765'
def ready():
 try:
  with urllib.request.urlopen(URL+'/api/meta',timeout=3) as r:return json.load(r)
 except Exception:return None
if __name__=='__main__':
 state=ready()
 if not state:
  key=ROOT/'.local/deepseek-macos.key'
  if not key.is_file() or not key.read_text().strip():raise SystemExit('本机模型凭据尚未配置')
  env=os.environ.copy();env['DEEPSEEK_API_KEY']=key.read_text().strip();env.setdefault('DEEPSEEK_MODEL','deepseek-v4-flash');env['PYTHONDONTWRITEBYTECODE']='1'
  with (ROOT/'.local/macos-server.log').open('ab') as log:p=subprocess.Popen([str(PY),str(ROOT/'backend/app.py'),'--port','8765'],cwd=ROOT,env=env,stdout=log,stderr=log,start_new_session=True)
  (ROOT/'.local/macos-server.pid').write_text(str(p.pid))
  for _ in range(60):
   state=ready()
   if state:break
   if p.poll() is not None:raise SystemExit('启动失败，请查看 .local/macos-server.log')
   time.sleep(.5)
  else:raise SystemExit('启动等待超时，请检查服务日志')
 print('iCCM 演示：'+URL)
 print('模型已配置：'+str(state.get('model',{}).get('available')))
