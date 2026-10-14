"""公共覆盖门禁留出复测；复用冻结/分页/换序/三轮机制，CSV判据不发送模型。"""
import replay_continuity_holdout as runner

structure_grade = runner.grade


def grade(case, row):
    e = case['expected']
    if e['kind'] == 'clarify_or_all':
        kind = 'clarify' if row.get('response', {}).get('status') in ('clarify', 'conversation', 'ambiguous') else 'parts'
        return grade({**case, 'expected': {**e, 'kind': kind}}, row)
    if e['kind'] != 'points':
        verdict = structure_grade(case, row)
    else:
        r = row.get('response', {})
        tasks = (r.get('context', {}).get('relational_state') or {}).get('tasks', [])
        spec = tasks[0]['spec'] if len(tasks) == 1 else {}
        records = r.get('records', [])
        lines = sorted(x.get('evidence', {}).get('line') for x in records)
        root = spec.get('root') or {}
        entity = (r.get('query_receipt') or {}).get('resolved_entity') or r.get('entity') or {}
        checks = {'http': row.get('http') == 200, 'status': r.get('status') == 'ok',
                  'complete_original_rows': lines == e['lines'], 'total': r.get('total') == len(e['lines']),
                  'root': (root.get('tree') == e.get('tree') and root.get('value') == e.get('code')
                           or entity.get('tree') == e.get('tree') and entity.get('code') == e.get('code'))
                          if e.get('code') else not root and not r.get('entity')}
        raw = {x['evidence']['line']: x['evidence'].get('fields') for x in records if x.get('evidence')}
        checks['raw_record_fields'] = raw == {x['line']: x['fields'] for x in e['rows']}
        verdict = {'passed': all(checks.values()), 'checks': checks}
    # 真执行回执必须实际经过新入口；澄清没有SQL，不要求covered。
    if case['expected']['kind'] != 'clarify':
        verdict['checks']['public_coverage_receipt'] = row.get('response', {}).get('trace', {}).get('question_coverage', {}).get('status') == 'covered'
    verdict['passed'] = all(verdict['checks'].values())
    verdict['failed_checks'] = [k for k, v in verdict['checks'].items() if not v]
    return verdict


def signature(r):
    return {'status': r.get('status'), 'total': r.get('total'), 'entity': r.get('entity'),
            'specs': [t['spec'] for t in (r.get('context', {}).get('relational_state') or {}).get('tasks', [])],
            'records': sorted((x.get('code', ''), x.get('evidence', {}).get('line', 0)) for x in r.get('records', [])),
            'metrics': sorted(r.get('metrics', []), key=lambda x: x['label'])}


if __name__ == '__main__':
    runner.grade = grade
    runner.signature = signature
    raise SystemExit(runner.main())
