"""执行已授权的小范围真实模型冒烟测试，保存实际事件，不保存认证令牌。"""
import json
import time
import sys
import urllib.request
from pathlib import Path

URL = 'http://127.0.0.1:8771'
OUT = Path(__file__).resolve().parents[1] / 'docs/.staging/codex-agent-demo-20260924'
token = ''
sys.stdout.reconfigure(encoding='utf-8')


def api(path, body=None):
    data = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
    request = urllib.request.Request(URL + path, data=data, headers={'Content-Type': 'application/json', 'X-Local-Token': token})
    with urllib.request.urlopen(request, timeout=45) as response:
        return json.load(response)


def wait(sid, after=0):
    started = time.monotonic()
    while time.monotonic() - started < 220:
        result = api('/api/events?session=' + sid + '&after=' + str(after))
        if not result['busy']:
            return result
        time.sleep(2)
    raise TimeoutError('model smoke timeout')


def report(label, sid, after=0):
    result = wait(sid, after)
    (OUT / (label + '.json')).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    compact = [e for e in result['events'] if e['kind'] in ('message', 'error', 'done', 'tool_start', 'tool_error')]
    print(label, json.dumps(compact, ensure_ascii=False), flush=True)
    return result


if __name__ == '__main__':
    token = api('/api/meta')['token']
    sid = api('/api/new', {})['id']
    api('/api/ask', {'session': sid, 'question': 'XJ3ABC002RR 下的设备类描述3727下的部件有多少类？'})
    first = report('live-v2-cross-tree', sid)
    cursor = first['events'][-1]['seq'] if first['events'] else 0
    api('/api/ask', {'session': sid, 'question': '把范围换成 XJ2ABC001MO，设备类不变，有多少部件、多少类？'})
    report('live-v2-switch-subject', sid, cursor)
    sid = api('/api/new', {})['id']
    api('/api/ask', {'session': sid, 'question': '筛选测量值大于50且小于80摄氏度的测点，告诉我总数。'})
    report('live-v2-numeric-filter', sid)
