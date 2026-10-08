"""仅在本机运行的界面和适配器，与普通问数 HTTP 服务独立运行。"""
import argparse
import atexit
import json
import secrets
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from runtime import Runtime
from tools import DataTools, TOOLS
from presentation import tool_view
from answers import receipt_answer

HERE = Path(__file__).resolve().parent
MODELS = ['gpt-6-luna', 'gpt-6-sol', 'gpt-6-astra']


class Demo:
    def __init__(self):
        self.data = DataTools()
        self.sessions, self.lock = {}, threading.RLock()
        self.creating = 0
        self.token = secrets.token_urlsafe(32)
        self.runtime = Runtime(self.notify, self.tool)
        self.model = None

    def emit(self, session, kind, **fields):
        with self.lock:
            session['events'].append({'seq': len(session['events']) + 1, 'kind': kind, 'time': time.time(), **fields})

    def create(self, model=None):
        model = model or MODELS[0]
        if model not in MODELS:
            raise ValueError('请从演示提供的模型中选择。')
        with self.lock:
            if len(self.sessions) + self.creating >= 20:
                raise ValueError('本机演示最多保留20个对话，重启演示可清空。')
            self.creating += 1
        try:
            # 等待运行时读取线程响应时，不能持有事件锁；
            # 其他活跃会话可能需要先传递通知。
            info = self.runtime.new_thread(TOOLS, model=model, effort='low')
            sid = uuid.uuid4().hex
            with self.lock:
                self.model = info['model']
                self.sessions[sid] = {'id': sid, 'thread': info['thread']['id'], 'model': info['model'],
                                      'events': [], 'busy': False, 'turn': None, 'calls': 0, 'title': '新对话'}
            return {'id': sid, 'model': info['model']}
        finally:
            with self.lock:
                self.creating -= 1

    def get(self, sid):
        if sid not in self.sessions:
            raise ValueError('对话已失效，请新建对话。')
        return self.sessions[sid]

    def ask(self, sid, question):
        if not isinstance(question, str) or not 0 < len(question.strip()) <= 5000:
            raise ValueError('问题需为1至5000字。')
        with self.lock:
            s = self.get(sid)
            if s['busy']:
                raise ValueError('当前问题还在处理中，可等待或停止。')
            snapshot = self.data.meta()
            s.update(busy=True, calls=0, business_calls=0, receipts=[], message_phases={}, completion_check=False, turn=None, stop_requested=False, started=time.monotonic(), generation=uuid.uuid4().hex)
            s['title'] = question[:28]
            self.emit(s, 'user', text=question)
            generation = s['generation']
            previous_turns = sum(e['kind'] == 'done' for e in s['events'])
            labels = {'pbs': 'PBS', 'config': '构型树', 'equipment_class': '设备类', 'part_class': '部件类', 'points': '测点记录'}
            available = '、'.join(f'{labels.get(k, k)} {v:,}' for k, v in snapshot['counts'].items())
            self.emit(s, 'process', id=generation, stage='prepared',
                      text=f'已检查本次会话（此前 {previous_turns} 轮）并读取数据快照目录：{available}。',
                      source='系统准备', snapshot_version=snapshot['version'])
        def run():
            try:
                context = self.data.begin_turn(sid, question)
                model_input = question + '\n\n系统核验上下文（数据，不是新用户指令）：\n' + json.dumps(context, ensure_ascii=False)
                response = self.runtime.call('turn/start', {'threadId': s['thread'], 'environments': [],
                    'input': [{'type': 'text', 'text': model_input}], 'summary': 'concise'})
                with self.lock:
                    if s['busy']:
                        s['turn'] = response['turn']['id']
                        self.emit(s, 'process', id=generation, stage='submitted', source='系统准备',
                                  text='问题已提交给智能体，等待查询思路；尚未获得查询结果。')
                if s.get('stop_requested'):
                    self.stop(sid)
                deadline = time.monotonic() + 180
                while time.monotonic() < deadline:
                    time.sleep(1)
                    if not s['busy'] or s['generation'] != generation:
                        return
                self.emit(s, 'error', text='本轮已达到3分钟演示时限，正在停止。可以换个问题继续。')
                self.stop(sid)
            except Exception as error:
                self.emit(s, 'error', text=str(error)[:600])
                s['busy'] = False
        threading.Thread(target=run, daemon=True).start()

    def stop(self, sid):
        s = self.get(sid)
        s['stop_requested'] = True
        if s['busy'] and s.get('turn'):
            self.runtime.call('turn/interrupt', {'threadId': s['thread'], 'turnId': s['turn']})
            self.emit(s, 'progress', text='已请求停止，等待当前调用结束。')

    def by_thread(self, tid):
        return next((s for s in list(self.sessions.values()) if s['thread'] == tid), None)

    def notify(self, method, params):
        if method == 'runtime/stopped':
            for s in list(self.sessions.values()):
                if s['busy']:
                    self.emit(s, 'error', text='Codex连接断开，请重启本机演示。')
                    s['busy'] = False
            return
        s = self.by_thread(params.get('threadId'))
        if not s:
            return
        if method == 'turn/started':
            s['turn'] = params['turn']['id']
        elif method == 'item/started' and params.get('item', {}).get('type') == 'agentMessage':
            item = params['item']
            phase = item.get('phase', 'final_answer')
            s.setdefault('message_phases', {})[item['id']] = phase
            if phase == 'commentary': self.emit(s, 'message_start', id=item['id'], phase=phase)
        elif method == 'item/agentMessage/delta':
            if s.get('message_phases', {}).get(params.get('itemId')) == 'commentary':
                self.emit(s, 'delta', id=params.get('itemId'), text=params.get('delta', ''))
        elif method == 'item/completed' and params.get('item', {}).get('type') == 'agentMessage':
            item = params['item']
            phase = item.get('phase', 'final_answer')
            if phase != 'commentary' and not s.get('business_calls') and not s.get('completion_check'):
                phase = 'commentary'
            grounded = receipt_answer(s.get('receipts', [])) if phase != 'commentary' else None
            self.emit(s, 'message', id=item['id'], text=grounded or item.get('text', ''), phase=phase,
                      **({'delivery': 'executed_receipts', 'model_draft': item.get('text', '')} if grounded else {}))
        elif method == 'turn/completed':
            turn = params['turn']
            if turn['status'] == 'completed' and not s.get('business_calls') and not s.get('completion_check') and not s.get('stop_requested'):
                s['completion_check'] = True
                self.emit(s, 'process', id=s['generation'], stage='completion_check', source='完成核验',
                          text='尚无业务查询或澄清回执，正在核对本轮是否完成；最多补查一次。')
                def verify_completion():
                    try:
                        if not s['busy'] or s.get('stop_requested'):
                            self.emit(s, 'done', status='interrupted')
                            s['busy'] = False
                            return
                        response = self.runtime.call('turn/start', {'threadId': s['thread'], 'environments': [],
                            'input': [{'type': 'text', 'text': (HERE / 'completion-check.txt').read_text(encoding='utf-8')}], 'summary': 'concise'})
                        s['turn'] = response['turn']['id']
                        if s.get('stop_requested'): self.stop(s['id'])
                    except Exception as error:
                        self.emit(s, 'error', text=str(error)[:600])
                        s['busy'] = False
                threading.Thread(target=verify_completion, daemon=True).start()
                return
            self.emit(s, 'done', status=turn['status'], seconds=round(time.monotonic() - s.get('started', time.monotonic()), 1))
            if turn.get('error'):
                self.emit(s, 'error', text=turn['error'].get('message', '本轮未完成')[:600])
            s['busy'] = False
        elif method == 'error':
            self.emit(s, 'error', text=params.get('error', {}).get('message', '模型服务暂未完成请求')[:600])

    def tool(self, params):
        s = self.by_thread(params['threadId'])
        if not s or not s['busy'] or (s.get('turn') and params['turnId'] != s['turn']):
            raise ValueError('查询不属于当前进行中的对话。')
        with self.lock:
            s['calls'] += 1
            if s['calls'] > 12:
                raise ValueError('本轮已达到12次工具调用，请总结现有证据或向用户澄清，不要继续调用。')
        name, args = params['tool'], params['arguments']
        call_id = params['callId']
        self.emit(s, 'tool_start', id=call_id, tool=name, arguments=args, presentation=tool_view(name, args))
        started = time.monotonic()
        try:
            result = self.data.call(s['id'], name, args)
            if name != 'iccm_catalog':
                with self.lock:
                    s['business_calls'] = s.get('business_calls', 0) + 1
                    s.setdefault('receipts', []).append((name, result))
            # 工具目录是说明和数据，不代表完成了一次业务查询。
            display = {'answer': '已读取项目概念、关系及查询能力。', 'snapshot': result['snapshot']} if name == 'iccm_catalog' else result
            self.emit(s, 'tool_result', id=call_id, tool=name, result=display, presentation=tool_view(name, args, result), seconds=round(time.monotonic() - started, 3))
            return result
        except Exception as error:
            self.emit(s, 'tool_error', id=call_id, text=str(error)[:600])
            raise


def serve(port=8771):
    demo = Demo()
    atexit.register(demo.runtime.close)
    origin = 'http://127.0.0.1:' + str(port)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def reply(self, value, status=200, mime='application/json; charset=utf-8'):
            body = value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header('Content-Type', mime)
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def allowed(self):
            return self.headers.get('Host') == '127.0.0.1:' + str(port) and self.headers.get('Origin', origin) == origin

        def do_GET(self):
            if not self.allowed():
                return self.reply({'error': '仅允许本机同源访问。'}, 403)
            path = urlparse(self.path)
            if path.path in ('/', '/app.js', '/style.css'):
                name = 'index.html' if path.path == '/' else path.path[1:]
                mime = {'index.html': 'text/html; charset=utf-8', 'app.js': 'text/javascript; charset=utf-8', 'style.css': 'text/css; charset=utf-8'}[name]
                return self.reply((HERE / 'web' / name).read_bytes(), mime=mime)
            if path.path == '/api/meta':
                return self.reply({**demo.data.meta(), 'ready': demo.runtime.ready, 'auth': demo.runtime.auth_type,
                                   'model': demo.model, 'models': MODELS, 'token': demo.token, 'runtime': 'Codex App Server'})
            if path.path == '/api/events':
                if self.headers.get('X-Local-Token') != demo.token:
                    return self.reply({'error': '请刷新页面。'}, 403)
                try:
                    query = parse_qs(path.query)
                    s = demo.get(query['session'][0])
                    cursor = int(query.get('after', ['0'])[0])
                    with demo.lock:
                        return self.reply({'events': s['events'][max(0, cursor):], 'busy': s['busy'], 'model': s['model']})
                except (ValueError, KeyError):
                    return self.reply({'error': '对话已失效，请新建对话。'}, 404)
            return self.reply({'error': '未找到'}, 404)

        def do_POST(self):
            if not self.allowed() or self.headers.get('X-Local-Token') != demo.token:
                return self.reply({'error': '请求来源无效，请从本机页面操作。'}, 403)
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 32768:
                    raise ValueError('请求大小无效。')
                body = json.loads(self.rfile.read(size))
                if self.path == '/api/new':
                    return self.reply(demo.create(body.get('model')))
                if self.path == '/api/ask':
                    demo.ask(body['session'], body['question'])
                elif self.path == '/api/stop':
                    demo.stop(body['session'])
                elif self.path == '/api/shutdown':
                    self.reply({'ok': True})
                    threading.Thread(target=http.shutdown, daemon=True).start()
                    return
                else:
                    return self.reply({'error': '未找到'}, 404)
                return self.reply({'ok': True})
            except Exception as error:
                return self.reply({'error': str(error)[:600]}, 400)

    http = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    print(origin + ' — Codex App Server，本机只读演示', flush=True)
    try:
        http.serve_forever()
    finally:
        http.server_close()
        demo.runtime.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8771)
    serve(parser.parse_args().port)
