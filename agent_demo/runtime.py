"""通过 JSONL 与本机安装的官方 Codex App Server 通信。"""
import json
import os
import queue
import shutil
import subprocess
import threading
import tomllib
from pathlib import Path

HERE = Path(__file__).resolve().parent


def codex_binary():
    override = os.environ.get('ICCM_CODEX_BIN')
    if override:
        return override
    found = shutil.which('codex')
    if found:
        return found
    for app_root in (Path('/Applications'), Path.home() / 'Applications'):
        for app_name in ('Codex.app', 'ChatGPT.app'):
            for relative in ('Contents/Resources/codex', 'Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex'):
                candidate = app_root / app_name / relative
                if candidate.is_file() and os.access(candidate, os.X_OK):
                    return str(candidate)
    binaries = list((Path.home() / 'AppData/Local/OpenAI/Codex/bin').glob('*/codex.exe'))
    if not binaries:
        raise RuntimeError('未找到Codex。请安装并登录Codex桌面应用，再启动演示。')
    return str(max(binaries, key=lambda p: p.stat().st_mtime))


class Runtime:
    def __init__(self, notify, tool_call):
        self.notify, self.tool_call = notify, tool_call
        self.pending, self.counter, self.lock = {}, 0, threading.RLock()
        self.ready = False
        flags = ['shell_tool', 'unified_exec', 'apps', 'plugins', 'hooks', 'multi_agent', 'multi_agent_v2', 'code_mode', 'computer_use', 'browser_use', 'view_image', 'image_generation']
        self.config = {**{'features.' + k: False for k in flags}, 'web_search': 'disabled', 'project_doc_max_bytes': 0}
        # 当前安装的运行时需要此开关才能分发动态客户端工具。
        # 环境访问以及终端和文件工具仍保持禁用。
        self.config['features.code_mode_host'] = True
        config_file = Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex'))) / 'config.toml'
        if config_file.exists():
            config = tomllib.loads(config_file.read_text(encoding='utf-8-sig'))
            for key in config.get('mcp_servers', {}):
                self.config['mcp_servers.' + key + '.enabled'] = False
        cmd = [codex_binary(), 'app-server']
        for key, value in self.config.items():
            cmd.extend(['-c', key + '=' + json.dumps(value)])
        self.process = subprocess.Popen(cmd, cwd=HERE, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE, text=True, encoding='utf-8', bufsize=1,
                                        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        threading.Thread(target=self.read, daemon=True).start()
        # 运行时标准错误可能含环境或认证信息，禁止直接展示。
        def drain_stderr():
            for _ in self.process.stderr:
                pass
        threading.Thread(target=drain_stderr, daemon=True).start()
        self.call('initialize', {'clientInfo': {'name': 'iccm_local_demo', 'title': 'iCCM本机智能体', 'version': '0.1.0'},
                                 'capabilities': {'experimentalApi': True}})
        self.send({'method': 'initialized', 'params': {}})
        account = self.call('account/read', {'refreshToken': False})
        if not account.get('account'):
            self.close()
            raise RuntimeError('Codex尚未登录，请在桌面应用登录后重启演示。')
        self.auth_type = account['account'].get('type', '已登录')
        self.ready = True

    def send(self, value):
        with self.lock:
            self.process.stdin.write(json.dumps(value, ensure_ascii=False) + '\n')
            self.process.stdin.flush()

    def call(self, method, params, timeout=40):
        with self.lock:
            self.counter += 1
            ident = self.counter
            response = queue.Queue()
            self.pending[ident] = response
        self.send({'id': ident, 'method': method, 'params': params})
        try:
            data = response.get(timeout=timeout)
        except queue.Empty:
            raise RuntimeError('模型服务响应超时，本次操作尚未完成，请重试。') from None
        finally:
            self.pending.pop(ident, None)
        if 'error' in data:
            raise RuntimeError(data['error'].get('message', 'Codex请求失败'))
        return data.get('result', {})

    def read(self):
        try:
            for line in self.process.stdout:
                try:
                    message = json.loads(line)
                except ValueError:
                    continue
                if 'method' in message:
                    if 'id' in message:
                        threading.Thread(target=self.respond, args=(message,), daemon=True).start()
                    else:
                        self.notify(message['method'], message.get('params', {}))
                else:
                    waiter = self.pending.get(message.get('id'))
                    if waiter:
                        waiter.put(message)
        finally:
            self.ready = False
            for waiter in list(self.pending.values()):
                waiter.put({'error': {'message': 'Codex连接已结束，请重新启动演示。'}})
            self.notify('runtime/stopped', {})

    def respond(self, message):
        if message['method'] == 'item/tool/call':
            try:
                data = self.tool_call(message['params'])
                result = {'success': True, 'contentItems': [{'type': 'inputText', 'text': json.dumps(data, ensure_ascii=False)}]}
            except Exception as error:
                result = {'success': False, 'contentItems': [{'type': 'inputText', 'text': str(error)[:600]}]}
            self.send({'id': message['id'], 'result': result})
        else:
            # 此只读演示没有写文件或执行命令的审批通路。
            self.send({'id': message['id'], 'error': {'code': -32601, 'message': '本演示仅支持项目只读工具；请在对话中提出澄清。'}})

    def new_thread(self, tools, model=None, effort=None, service_tier=None):
        instructions = ('你是iCCM设备数据问答助手。使用提供的只读工具完成查询，而不是开发程序。'
                        '不要调用终端、修改文件、浏览网页或调用外部应用。只把真实工具回执当作数据事实。'
                        '首次查询先读取iccm_catalog。先简述将查询什么；遇到歧义向用户澄清。'
                        '不得给出编造的数字或实际未执行的查询过程。最终答复使用简洁中文；结果编号由界面保留在技术详情，不在正文罗列。\n' +
                        (HERE / 'knowledge.txt').read_text(encoding='utf-8'))
        options = {'model': model} if model else {}
        if service_tier is not None:
            options['serviceTier'] = service_tier
        config = {**self.config, **({'model_reasoning_effort': effort} if effort else {})}
        return self.call('thread/start', {'cwd': str(HERE), 'sandbox': 'read-only', 'approvalPolicy': 'never',
                                         'environments': [], 'ephemeral': True, 'baseInstructions': instructions,
                                         'dynamicTools': tools, 'config': config, 'serviceName': 'iccm-local-demo', **options})

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
