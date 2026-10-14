"""冻结新题重复实测；CSV判据仅本机使用，组内原顺序，无重试挑分。"""
import argparse, concurrent.futures, csv, hashlib, json, threading, time
from pathlib import Path
from replay_engine_comparison import Service, clean
from replay_customer_onsite import expand

ROOT = Path(__file__).resolve().parents[1]
with (ROOT.parent/'中广核iCCM项目智能问数DEMO脱敏数据/构型树.csv').open(encoding='gb18030', newline='') as stream:
    CSV_OBJECTS = {r['对象代码']: r for r in csv.DictReader(stream)}


def grade(case, row):
    r = row.get('response', {}); e = case['expected']; kind = e['kind']
    checks = {'http': row.get('http') == 200}
    tasks = (r.get('context', {}).get('relational_state') or {}).get('tasks', [])
    spec = tasks[0]['spec'] if len(tasks) == 1 else {}
    receipt = r.get('query_receipt') or {}
    root = spec.get('root')
    resolved = receipt.get('resolved_entity') or r.get('entity') or {}
    root_ok = (root and root.get('tree') == e.get('tree') and root.get('value') == e.get('code')) or (resolved.get('tree') == e.get('tree') and resolved.get('code') == e.get('code'))
    if kind == 'clarify':
        checks.update(clarify=r.get('status') in ('clarify', 'conversation', 'ambiguous'),
                      no_execution=not r.get('records') and not (r.get('goal_receipt') or {}).get('completed'))
    elif kind == 'table':
        query = r.get('query') or receipt.get('query') or {}
        checks.update(status=r.get('status') == 'ok', target=query.get('target') == e['target'],
                      no_root=query.get('filters') == [], total=r.get('total') == e['total'])
    elif kind == 'identity':
        checks.update(status=r.get('status') == 'ok', identity=(r.get('entity') or {}) == {'tree': e['tree'], 'code': e['code']})
    elif kind == 'relation':
        # 设备构型的设备类取原CSV设备节点父编码；关联输出有独立角色回执，
        # 不把输入构型编码当作设备类编码，也不要求一次关联隐藏其他实际角色。
        node = CSV_OBJECTS[e['code']]
        while node['对象层级描述'] != '设备' and node['父对象代码'] in CSV_OBJECTS:
            node = CSV_OBJECTS[node['父对象代码']]
        class_code = node['父对象代码']
        facts = r.get('relation_facts', {}).get('equipment_class', [])
        checks.update(status=r.get('status') == 'ok', source_root=bool(root_ok),
                      class_result=[x.get('code') for x in facts] == [class_code],
                      class_target=bool(facts) and all(x.get('tree') == 'equipment_class' for x in facts))
    else:
        codes = sorted(x.get('code') for x in r.get('records', []) if x.get('code') is not None)
        metrics = {x['label']: x['value'] for x in r.get('metrics', [])}
        depth = spec.get('depth') or receipt.get('scope') or r.get('scope')
        actual_classes = {x.get('code'): (x.get('evidence', {}).get('fields', {}).get('所属部件类代码')
                          if '所属部件类代码' in x.get('evidence', {}).get('fields', {}) else x.get('class_code'))
                          for x in r.get('records', [])}
        expected_classes = {c: CSV_OBJECTS[c]['所属部件类代码'] for c in e['codes']}
        checks.update(status=r.get('status') == 'ok', root=bool(root_ok), depth=depth == e['depth'],
                      complete_codes=codes == e['codes'], total=r.get('total') == e['total'],
                      classes=actual_classes == expected_classes and len(set(actual_classes.values())) == e['classes']
                      and ('不同部件类' not in metrics or metrics['不同部件类'] == e['classes']))
    return {'passed': all(checks.values()), 'checks': checks,
            'failed_checks': [k for k, v in checks.items() if not v]}


def signature(r):
    tasks = (r.get('context', {}).get('relational_state') or {}).get('tasks', [])
    specs = [t['spec'] for t in tasks]
    return {'status': r.get('status'), 'entity': r.get('entity'), 'specs': specs,
            'total': r.get('total'), 'record_codes': sorted(x.get('code', '') for x in r.get('records', [])),
            'metrics': sorted(r.get('metrics', []), key=lambda x: x['label'])}


def main():
    p = argparse.ArgumentParser(); p.add_argument('--pack', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True); p.add_argument('--repeat', type=int, default=3)
    p.add_argument('--workers', type=int, default=2); p.add_argument('--port', type=int, default=19276)
    a = p.parse_args(); assert 1 <= a.workers <= 2 and a.repeat >= 3
    pack = a.pack.resolve(); freeze = json.loads((pack.parent/'freeze.json').read_text())
    assert hashlib.sha256(pack.read_bytes()).hexdigest() == freeze['packs'][pack.name]
    data = ROOT.parent/'中广核iCCM项目智能问数DEMO脱敏数据'
    assert all(hashlib.sha256((data/n).read_bytes()).hexdigest() == h for n, h in freeze['csv'].items())
    out = a.out.resolve(); out.mkdir(exist_ok=False); receipts = out/'receipts'; receipts.mkdir()
    cases = json.loads(pack.read_text()); groups = {}
    for c in cases: groups.setdefault(c['group'], []).append(c)
    source = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
              for d in ('backend', 'frontend', 'prompts/system') for p in (ROOT/d).glob('*') if p.is_file()}
    rows = []; lock = threading.Lock(); svc = Service('ordinary', out, a.port)
    result = {'source': source, 'pack_sha256': freeze['packs'][pack.name], 'repeat': a.repeat, 'judge_version': 2,
              'rows': rows, 'complete': False, 'workers': a.workers, 'model_never_receives_oracle': True}

    def save():
        result['summary'] = {'attempted': len(rows), 'passed': sum(x['passed'] for x in rows),
                             'total': len(cases)*a.repeat,
                             'rounds': {str(n): {'attempted': sum(x['round'] == n for x in rows),
                                                 'passed': sum(x['round'] == n and x['passed'] for x in rows),
                                                 'total': len(cases)} for n in range(1, a.repeat+1)}}
        (out/'results.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')

    def run_group(n, cc):
        sid, _ = svc.new()
        try:
            for c in cc:
                start = time.monotonic()
                try:
                    row, _ = svc.ask(sid, c)
                    if row['http'] == 200: row['response'] = clean(expand(svc, row['response'], sid))
                    row.update(grade(c, row)); row['signature'] = signature(row['response'])
                except Exception as err:
                    row = {'id': c['id'], 'question': c['question'], 'passed': False, 'error': str(err), 'failed_checks': ['exception']}
                row['round'] = n
                f = receipts/(f'R{n}-'+c['id']+'.json'); f.write_text(json.dumps(clean(row), ensure_ascii=False, indent=2)+'\n')
                brief = {'id': c['id'], 'group': c['group'], 'round': n, 'passed': row['passed'],
                         'failed_checks': row['failed_checks'], 'seconds': round(time.monotonic()-start, 3),
                         'status': row.get('response', {}).get('status'), 'receipt': str(f.relative_to(out))}
                with lock: rows.append(brief); save()
                print(json.dumps(brief, ensure_ascii=False), flush=True)
        finally: svc.call('/api/reset', {'session': sid})

    try:
        svc.start(); result['meta'] = svc.meta; save()
        for n in range(1, a.repeat+1):
            keys = list(groups)
            if n % 2 == 0: keys.reverse()
            elif n > 1: keys = keys[3:]+keys[:3]
            with concurrent.futures.ThreadPoolExecutor(max_workers=a.workers) as pool:
                for f in concurrent.futures.as_completed([pool.submit(run_group, n, groups[k]) for k in keys]): f.result()
        result['complete'] = True
    finally:
        svc.close(); result['service_closed'] = svc.process is not None and svc.process.poll() is not None
        result['source_unchanged'] = source == {n: hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in source}; save()
    print(json.dumps(result['summary'], ensure_ascii=False), flush=True)
    return 0 if result['complete'] and result['source_unchanged'] and all(x['passed'] for x in rows) else 1


if __name__ == '__main__': raise SystemExit(main())
