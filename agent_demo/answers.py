"""依据实际执行回执发布事实答案，不采用模型自行计算的数字。"""
TREES = {'pbs': 'PBS', 'config': '构型', 'equipment_class': '设备类', 'part_class': '部件类', 'points': '测点记录'}


def render_result(result):
    if result.get('items'):
        return '\n\n'.join((item.get('task_question', '') + '\n' + render_result(item)).strip()
                           for item in result['items'])
    parts = [result.get('answer', '')]
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
    summary = result.get('full_record_summary') or {}
    if summary and not candidate and not result.get('match_type'):
        parts.append('全部结果的类型分布：' + '；'.join(
            f"{TREES.get(g['tree'], g['tree'])} / {g['level']}：{g['count']} 个"
            for g in summary['by_tree_and_level']) + '。')
    if result.get('has_more'):
        parts.append(f"明细共 {result['record_total']} 条，本页显示 {result['returned_record_count']} 条；数量按完整结果计算。")
    if result.get('note'):
        parts.append(result['note'])
    return '\n'.join(p for p in parts if p)


def receipt_answer(receipts):
    if not receipts:
        return None
    # 后续未解决的结果不能被此前成功定位的结果遮蔽。
    last = receipts[-1][1]
    if last.get('status') in ('clarify', 'ambiguous', 'not_found', 'error'):
        return render_result(last)
    business = [(name, result) for name, result in receipts if name not in ('iccm_find', 'iccm_page')]
    if not business:
        business = receipts[-1:]
    seen, answers = set(), []
    for _, result in business:
        text = render_result(result)
        if text and text not in seen:
            seen.add(text);answers.append(text)
    return '\n\n'.join(answers) or None
