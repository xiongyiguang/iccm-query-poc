"""仅监听回环地址的 POC 服务，提供明确路由，不提供文件系统浏览。"""
import argparse
import copy
import os
import json
import secrets
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs,urlparse
from data import Store,ROOT,QueryError
from model import interpret,status,ModelUnavailable,PlanInvalid,get_trace
from query_plan import execute_plan,task_context
from web_auth import AUTH
from session_state import snapshot,restore,make_room,public_result,compact_evidence

from importer import Imports,SCHEMA,LABELS,counts
IMPORTS=Imports()
STORE=None
SESSIONS={}
LOCK=threading.RLock()
TOKEN=secrets.token_urlsafe(24)


class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args): pass

    def send(self,code,payload,ctype='application/json; charset=utf-8',extra_headers=None):
        body=json.dumps(payload,ensure_ascii=False).encode() if not isinstance(payload,bytes) else payload
        self.send_response(code)
        self.send_header('Content-Type',ctype)
        self.send_header('Content-Length',str(len(body)))
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'")
        for key,value in (extra_headers or {}).items():self.send_header(key,value)
        self.end_headers()
        try: self.wfile.write(body)
        except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError): pass

    def allowed_host(self):
        return self.headers.get('Host') in (f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}')

    def allowed_origin(self,origin):
        local=(f'http://127.0.0.1:{self.server.server_port}',f'http://localhost:{self.server.server_port}')
        public=os.environ.get('ICCM_PUBLIC_ORIGIN','').strip()
        return not origin or origin in local or bool(public and origin==public)

    def do_GET(self):
        if not self.allowed_host(): return self.send(403,{'error':'Host rejected'})
        url=urlparse(self.path); q=parse_qs(url.query)
        if url.path in ('/login','/login.css','/login.js'):
            name={'/login':'login.html','/login.css':'login.css','/login.js':'login.js'}[url.path]
            mime={'login.html':'text/html; charset=utf-8','login.css':'text/css; charset=utf-8','login.js':'text/javascript; charset=utf-8'}[name]
            return self.send(200,(ROOT/'frontend'/name).read_bytes(),mime)
        if not AUTH.valid(self.headers.get('Cookie')):
            if url.path.startswith('/api/'):return self.send(401,{'error':'登录已失效，请重新登录。'})
            return self.send(302,b'',extra_headers={'Location':'/login'})
        store=STORE
        if url.path in ('/','/app.js','/style.css'):
            name={'/':'index.html','/app.js':'app.js','/style.css':'style.css'}[url.path]
            mime={'index.html':'text/html; charset=utf-8','app.js':'text/javascript; charset=utf-8','style.css':'text/css; charset=utf-8'}[name]
            return self.send(200,(ROOT/'frontend'/name).read_bytes(),mime)
        try:
            if url.path=='/api/import/schema':return self.send(200,{'schemas':SCHEMA,'labels':LABELS,'history':IMPORTS.history()})
            if url.path=='/api/meta':
                counts={**{k:0 for k in LABELS},**{r['tree']:r['n'] for r in store.rows('SELECT tree,count(*) n FROM objects GROUP BY tree')}}
                counts['points']=store.rows('SELECT count(*) n FROM points')[0]['n']
                return self.send(200,{'token':TOKEN,'version':store.version,'sources':store.inputs,'sample_available':bool(store.rows("SELECT 1 FROM objects WHERE tree='pbs' AND code='XJ2ABC002MO&MOHB01'")),'model':status(),'counts':counts,'auth_required':AUTH.required(),'field_labels':{k:v['label'] for k,v in __import__('attributes').CATALOG.items()}})
            if url.path=='/api/operations':
                from operation_capabilities import operations_for
                return self.send(200,operations_for(store,{'tree':q.get('tree',[''])[0],'code':q.get('code',[''])[0]}))
            if url.path=='/api/browse':
                return self.send(200,store.browse(q.get('tree',['pbs'])[0],q.get('code',[None])[0],q.get('q',[''])[0][:200],int(q.get('page',['0'])[0])))
            if url.path=='/api/objects':
                return self.send(200,store.search(q.get('q',[''])[0][:200],q.get('tree',['pbs'])[0],q.get('parent',[None])[0]))
            return self.send(404,{'error':'未找到页面'})
        except (QueryError,ValueError) as e: return self.send(400,{'error':str(e)})

    def do_POST(self):
        global STORE
        if not self.allowed_host():return self.send(403,{'error':'请求来源无效。'})
        if self.path in ('/api/auth/login','/api/auth/logout'):
            if not self.headers.get('Origin') or not self.allowed_origin(self.headers.get('Origin')):
                return self.send(403,{'error':'跨来源请求已拒绝'})
            if self.path=='/api/auth/logout':
                return self.send(200,{'ok':True},extra_headers={'Set-Cookie':AUTH.logout(self.headers.get('Cookie'))})
            try:
                size=int(self.headers.get('Content-Length','0'))
                if not 0<size<=4096:raise ValueError()
                data=json.loads(self.rfile.read(size));user=data.get('username');password=data.get('password')
                if not isinstance(user,str) or not isinstance(password,str) or len(user)>100 or len(password)>512:raise ValueError()
            except (ValueError,AttributeError):return self.send(400,{'error':'请输入有效的账号和密码。'})
            code,result,cookie=AUTH.login(user,password,self.headers.get('X-Real-IP',self.client_address[0]))
            return self.send(code,result,extra_headers={'Set-Cookie':cookie} if cookie else None)
        if not AUTH.valid(self.headers.get('Cookie')):return self.send(401,{'error':'登录已失效，请重新登录。'})
        if self.headers.get('X-Demo-Token')!=TOKEN:
            return self.send(403,{'error':'请求来源无效，请刷新本机页面。'})
        origin=self.headers.get('Origin')
        if not self.allowed_origin(origin):
            return self.send(403,{'error':'跨来源请求已拒绝'})
        try:
            length=int(self.headers.get('Content-Length','0'))
            if not 0<length<=(48*1024*1024 if self.path=='/api/import/preview' else 128000 if self.path=='/api/resume' else 20000): raise QueryError('请求长度无效')
            body=json.loads(self.rfile.read(length)); sid=body.get('session','')
            if not isinstance(sid,str) or len(sid)>100: raise QueryError('会话无效')
            if self.path=='/api/import/preview':
                return self.send(200,IMPORTS.preview(STORE,body))
            if self.path=='/api/import/commit':
                with LOCK:
                    if any(s.get('busy') for s in SESSIONS.values()):raise QueryError('还有查询正在执行，请完成后再提交导入。')
                    STORE=IMPORTS.commit(STORE,body.get('preview'));SESSIONS.clear()
                return self.send(200,{'ok':True,'version':STORE.version,'counts':counts(STORE)})
            if body.get('version') and body['version']!=STORE.version:raise QueryError('数据已切换，请刷新页面后重新查询。')
            if self.path=='/api/resume':
                with LOCK:
                    restored=restore(body.get('continuation'),sid,STORE.version)
                    active=SESSIONS.get(sid)
                    if active and active.get('busy'):raise QueryError('该会话仍在查询，请稍后继续。')
                    if not active:
                        make_room(SESSIONS);SESSIONS[sid]=restored
                    session=SESSIONS[sid];session['touched']=time.monotonic();session.pop('pending_review',None)
                return self.send(200,{'context':session['context'],'version':STORE.version,'continuation':snapshot(sid,session,STORE.version)})
            if self.path=='/api/reset':
                with LOCK: SESSIONS.pop(sid,None)
                return self.send(200,{'ok':True})
            if self.path=='/api/context':
                with LOCK:
                    session=SESSIONS.get(sid)
                    if session:
                        if session['busy']: raise QueryError('请先等待或取消当前请求。')
                        session['context']={}
                        session['dialogue']=[]
                        session.pop('pending_review',None)
                return self.send(200,{'ok':True})
            if self.path=='/api/evidence':
                with LOCK:result=SESSIONS.get(sid,{}).get('results',{}).get(body.get('result'))
                if not result:raise QueryError('结果已失效，请重新查询后查看完整依据。')
                page=max(0,int(body.get('page',0)));refs=result.get('evidence',[])
                return self.send(200,{'evidence':refs[page*20:(page+1)*20],'total':len(refs)})
            if self.path=='/api/page':
                with LOCK:
                    session=SESSIONS.get(sid,{})
                    result=session.get('results',{}).get(body.get('result'))
                if not result: raise QueryError('结果已失效，请重新查询。')
                page=max(0,int(body.get('page',0)))
                return self.send(200,{'records':result['records'][page*20:(page+1)*20],'total':len(result['records'])})
            if self.path=='/api/review/cancel':
                with LOCK:
                    active=SESSIONS.get(sid)
                    if active and (body.get('review') is None or (active.get('pending_review') or {}).get('id')==body['review']):active.pop('pending_review',None)
                return self.send(200,{'ok':True})
            if self.path not in ('/api/query','/api/confirm'): return self.send(404,{'error':'未知接口'})
            confirming=self.path=='/api/confirm'
            start=time.perf_counter()
            with LOCK:
                if body.get('version') and body['version']!=STORE.version:raise QueryError('数据已切换，请刷新页面后重新查询。')
                if sid not in SESSIONS:
                    if confirming:raise QueryError('确认单已失效，请重新提问。')
                    make_room(SESSIONS)
                    SESSIONS[sid]={'context':{},'results':{},'busy':False}
                session=SESSIONS[sid]
                if session['busy']: raise QueryError('上一条请求尚未完成，请稍后再试。')
                request_owner=object()
                session['busy']=request_owner
                session['touched']=time.monotonic()
                context=copy.deepcopy(session['context'])
                if not confirming:session.pop('pending_review',None)
                store=STORE
            try:
                planning_trace={}
                guided=body.get('intent')
                if confirming:
                    from query_review import confirm
                    with LOCK:
                        if SESSIONS.get(sid) is not session:raise QueryError('确认单已取消。')
                        intent,planning_trace,question=confirm(session,sid,store.version,body.get('review'),body.get('tasks'))
                    mode='confirmed'
                elif guided is not None:
                    if not isinstance(guided,dict): raise QueryError('操作格式无效')
                    intent=guided
                    mode='guided'
                else:
                    question=body.get('question','')
                    if not isinstance(question,str) or not 0<len(question)<=2000: raise QueryError('请输入不超过2000字的问题。')
                    model_context=dict(context)
                    if session.get('dialogue'): model_context['dialogue']=session['dialogue']
                    from data_context import knowledge_context
                    model_context['verified_knowledge']=knowledge_context(store)
                    from request_checklist import business_catalog,literal_references
                    model_context['verified_schema']={'business_catalog':business_catalog(store),'literal_references':literal_references(question,store)}
                    from request_gateway import reference_context
                    model_context['verified_references']=reference_context(model_context,body.get('selection'),store,question,model_context['verified_schema']['literal_references'])
                    try:intent=interpret(question,model_context,body.get('selection'),store=store)
                    except ModelUnavailable:
                        if (get_trace() or {}).get('engine')=='relational_request':
                            # 失败原话是待核验输入，不是已确认结果；在本请求
                            # 仍持有会话标记时保存，防止迟到错误污染新请求。
                            with LOCK:
                                if SESSIONS.get(sid) is session and session.get('busy') is request_owner:
                                    session['context']['relational_pending_question']=question
                                    session['context']['relational_pending_questions']=(session['context'].get('relational_pending_questions',[])+[question])[-6:]
                                    session['context']['pending_question']=question
                        raise
                    with LOCK:
                        if SESSIONS.get(sid) is not session:return self.send(409,{'error':'会话已取消，未继续核验或执行查询。'})
                    from model import bind_references
                    intent=bind_references(store,question,intent,model_context)
                    mode='model'
                    planning_trace=copy.deepcopy(get_trace() or {})
                planning_done=time.perf_counter()
                execution_diagnostic={'question':body.get('question'),'version':store.version,'intent':intent,'stage':'execution'}
                if mode=='model':
                    from request_gateway import require_verified
                    require_verified(store,question,intent)
                if intent['operation']=='explain_result':
                    from result_explanation import explain_result
                    result=explain_result(session.get('last_success'))
                else:result=execute_plan(store,{**intent,'clarification':intent.get('clarification','')})
                from query_presentation import attach_basis
                attach_basis(result,intent)
                compact_evidence(store,result)
                execution_done=time.perf_counter()
                rid=uuid.uuid4().hex
                elapsed=round((time.perf_counter()-start)*1000)
                with LOCK:
                    if SESSIONS.get(sid) is not session:
                        return self.send(409,{'error':'会话已取消，结果未写入。'})
                    if result['status'] in ('ok','clarify','data_insufficient') or result.get('outcome'):
                        pending=task_context(intent,result)
                        route=(planning_trace.get('context_route') or {}) if mode in ('model','confirmed') else {}
                        prior={} if route.get('decision',{}).get('needs_history') is False else context
                        session['context']={**prior,**pending} if result['status'] in ('clarify','data_insufficient') else pending
                        if result['status'] in ('clarify','data_insufficient'):
                            continuing=mode in ('model','confirmed') and route.get('decision',{}).get('needs_history')
                            session['context']['pending_question']=(context.get('pending_question') if continuing else None) or body.get('question','')
                            session['context']['pending_reference']=route.get('decision',{}).get('reference') or (context.get('pending_reference') if continuing else None)
                    if intent['operation']!='explain_result' and result.get('status')!='conversation':session['last_success']=result if result.get('status')=='ok' else None
                    if len(session['results'])>=20: session['results'].pop(next(iter(session['results'])))
                    session['results'][rid]=result
                    if result['status']=='batch':
                        session['context']={'branches':[{'number':item['task_number'],'question':item['task_question'],'status':item['status'],**item['task_context']} for item in result['items']]}
                        published=[]
                        for item in result['items']:
                            item_id=uuid.uuid4().hex
                            session['results'][item_id]=item
                            published.append({**item,'records':item['records'][:20],'total':len(item['records']),'result':item_id,'mode':mode})
                        result={**result,'items':published}
                    while len(session['results'])>20:session['results'].pop(next(iter(session['results'])))
                    if mode in ('model','confirmed'):
                        from business_request import commit_state
                        session['context']=commit_state(session['context'],planning_trace,result,context)
                        session['dialogue']=(session.get('dialogue',[])+[{'question':question,'answer':('；'.join(item['task_question']+'：'+item['answer'] for item in result['items']) if result['status']=='batch' else result['answer'])[:600]}])[-6:]
                response_payload={**public_result(result),'result':rid,'mode':mode,'context':session['context'],'server_ms':elapsed,'timings_ms':{'planning':round((planning_done-start)*1000),'execution':round((execution_done-planning_done)*1000)},'continuation':snapshot(sid,session,store.version),'version':store.version,**({'trace':planning_trace} if mode in ('model','confirmed') and body.get('trace') is True else {}),**({'review_confirmation':{'id':planning_trace['review_id'],'question':question,'preparation_ms':planning_trace['review_preparation_ms'],'system_total_ms':planning_trace['review_preparation_ms']+elapsed}} if mode=='confirmed' else {})}
                # 状态和续问签名均已完成，发送前允许下一请求接续。
                with LOCK:
                    if session.get('busy') is request_owner:session['busy']=False
                return self.send(200,response_payload)
            finally:
                from request_checklist import discard_extraction
                discard_extraction()
                with LOCK:
                    # 迟到清理只能释放本请求，不能清掉下一请求的在途标记。
                    if session.get('busy') is request_owner:session['busy']=False
        except (QueryError,ValueError,TypeError,KeyError) as e:
            payload={'error':str(e),'error_code':'execution_invalid','request_id':uuid.uuid4().hex}
            if 'body' in locals() and body.get('trace') is True:
                payload['diagnostic']=locals().get('execution_diagnostic',{'stage':'request_validation'})
                if body.get('intent') is None and 'execution_diagnostic' in locals():payload['trace']=get_trace()
            return self.send(400,payload)
        except ModelUnavailable as e:
            invalid=isinstance(e,PlanInvalid)
            payload={'error':str(e),'model_unavailable':not invalid,
                     'error_code':'plan_invalid' if invalid else 'model_unavailable',
                     'request_id':uuid.uuid4().hex}
            # 按需启用的诊断信息与成功结果跟踪使用相同的鉴权接口。
            if body.get('intent') is None and body.get('trace') is True:
                payload['trace']=get_trace()
            return self.send(422 if invalid else 503,payload)
        except Exception:
            return self.send(500,{'error':'查询失败，未更新上下文。请检查本机运行状态。'})


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8765);args=parser.parse_args()
    STORE=IMPORTS.load()
    print(f'iCCM POC http://127.0.0.1:{args.port} data={STORE.version}',flush=True)
    ThreadingHTTPServer(('127.0.0.1',args.port),Handler).serve_forever()
