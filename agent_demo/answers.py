"""依据实际执行回执发布事实答案，不采用模型自行计算的数字。"""
TREES = {'pbs': 'PBS', 'config': '构型', 'equipment_class': '设备类', 'part_class': '部件类', 'points': '测点记录'}


def unique_receipts(results):
    """同一轮完全相同的执行回执只交付最近一份，任务与范围差异全部保留。"""
    selected, seen = [], []
    for result in reversed(results):
        # 缓存编号不同不代表不同业务结果；其余查询、任务、字段和事实必须逐项完全相同。
        content = {key: value for key, value in result.items() if key != 'result_id'}
        if content not in seen:
            seen.append(content)
            selected.append(result)
    return list(reversed(selected))


def render_result(result):
    if result.get('items'):
        return '\n\n'.join((item.get('task_question', '') + '\n' + render_result(item)).strip()
                           for item in result['items'])
    parts = [result.get('answer', '')]
    if (result.get('goal_receipt') or {}).get('goal', {}).get('field') == 'thresholds':
        for fact in result.get('attributes', []):
            parts.append(str(fact.get('label', fact.get('property', ''))) + '：' + str(
                fact.get('display_value', fact.get('value', '未提供')) if fact.get('status') == 'known' else '未提供'))
    records = result.get('records', [])
    candidate = result.get('status') in ('ambiguous', 'not_found') or result.get('match_type') == 'candidates_only'
    if candidate or result.get('match_type') == 'exact':
        for row in records[:20]:
            parts.append(' · '.join(str(x) for x in (TREES.get(row.get('tree'), row.get('tree')),
                         row.get('name'), row.get('code'), row.get('level')) if x not in (None, '')))
        if candidate or len(records) > 1:
            parts.append('以上为候选，尚未选定对象；请指定对象域或完整编码。')
    elif records and 'cells' in records[0]:
        columns = [str(c if isinstance(c, str) else c.get('label', c.get('key', '')))
                   for c in result.get('columns', [])]
        for row in records:
            parts.append('；'.join((columns[i] + '：' if i < len(columns) else '') + str(cell)
                                  for i, cell in enumerate(row['cells'])))
    elif records and any('value' in row or 'time' in row for row in records):
        # 直接展示执行器返回的顺序与原始字段，不由模型重排或口算。
        labels = {'name': '名称', 'code': '编码', 'value': '测量值', 'unit': '单位', 'time': '测量时间',
                  'source': '来源', 'state': '报警状态', 'switch': '开关'}
        for row in records[:20]:
            parts.append('；'.join(label + '：' + str(row[key]) for key, label in labels.items()
                                  if row.get(key) not in (None, '')))
    summary = result.get('full_record_summary') or {}
    if summary and not candidate and not result.get('match_type'):
        parts.append('全部结果的类型分布：' + '；'.join(
            f"{TREES.get(g['tree'], g['tree'])} / {g['level']}：{g['count']} 个"
            for g in summary['by_tree_and_level']) + '。')
    if result.get('has_more'):
        parts.append(f"明细共 {result['record_total']} 条，本页显示 {result['returned_record_count']} 条；数量按完整结果计算。")
    if result.get('candidate_preview_only'):
        parts.append(f"共 {result['record_total']} 个候选，本页仅展示 {result['returned_record_count']} 个。" + result.get('candidate_preview_note', ''))
    if result.get('note'):
        parts.append(result['note'])
    return '\n'.join(p for p in parts if p)


def delivery_receipts(receipts):
    """返回本次最终交付的完整任务回执；中间试查仍保留在工具事件中。"""
    if not receipts:
        return []
    # 有据任务回执已经包含本轮所有分支，不能混入先前尝试的不同口径。
    structured = [result for name, result in receipts if name in ('iccm_request', 'iccm_relational')]
    if structured:
        final = structured[-1]
        def identities(result):
            if result.get('items'):
                return set().union(*(identities(item) for item in result['items']))
            entity = result.get('entity') or (result.get('query_receipt') or {}).get('resolved_entity') or {}
            return {(entity['tree'], entity['code'])} if entity.get('tree') and entity.get('code') else set()
        covered = identities(final)
        selected = []
        # 混用兼容属性和关系入口时，只替换同一已执行主体；其他独立主体不能随最后一次补查丢失。
        for name, result in reversed(receipts):
            if result is final or name in ('iccm_catalog', 'iccm_find', 'iccm_page'):
                continue
            subjects = identities(result)
            if subjects and subjects.isdisjoint(covered):
                selected.append(result)
                covered.update(subjects)
        return unique_receipts(list(reversed(selected)) + [final])
    # 后续未解决的结果不能被此前成功定位的结果遮蔽。
    last = receipts[-1][1]
    if last.get('status') in ('clarify', 'ambiguous', 'not_found', 'error'):
        return [last]
    business = [(name, result) for name, result in receipts if name not in ('iccm_find', 'iccm_page')]
    if not business:
        business = receipts[-1:]
    return unique_receipts([result for _, result in business])


def receipt_answer(receipts):
    seen, answers = set(), []
    for result in delivery_receipts(receipts):
        text = render_result(result)
        if text and text not in seen:
            seen.add(text);answers.append(text)
    return '\n\n'.join(answers) or None


def has_delivery(receipts):
    """仅核对回执完成性；不能证明模型正确理解了开放式自然语言。"""
    business = [(name, r) for name, r in receipts if name not in ('iccm_catalog', 'iccm_page', 'iccm_find')]
    if not business:
        # 候选的歧义可以交付待选择问题，精确定位仍只是后续读取的准备。
        return bool(receipts and (receipts[-1][1].get('status') in ('clarify', 'ambiguous', 'not_found')
                                  or receipts[-1][1].get('match_type') == 'candidates_only'))
    result = business[-1][1]
    if result.get('items'):
        return all(has_delivery([('iccm_request', item)]) for item in result['items'])
    if result.get('status') in ('clarify', 'ambiguous', 'not_found', 'data_insufficient', 'conversation'):
        return bool(result.get('answer'))
    receipt = result.get('query_receipt') or {}
    goal = receipt.get('result_goal')
    if goal:
        return result.get('status') == 'ok' and bool(result.get('goal_receipt', {}).get('completed'))
    # 原有关系、概览和解释工具仍由其真实回执证明完成。
    return result.get('status') == 'ok' and bool(receipt or result.get('answer'))
