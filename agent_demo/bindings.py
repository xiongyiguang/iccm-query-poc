"""仅核验与标识相邻的对象域限定，不对任意自然语言分类。

保留限定词和标识的原文位置供检查；没有限定词就不推断对象域。
多个限定或否定限定都不能自动形成对象绑定。"""
import re

DOMAIN_LABELS = {'pbs': ('PBS',), 'config': ('构型', '构型树', '构型对象'),
                 'equipment_class': ('设备类', '设备类别'), 'part_class': ('部件类', '部件类别'),
                 'points': ('测点', '监测点', '测量点', '测点记录')}


def bindings(question, references, previous):
    explicit = {}
    # 字面目录会按值去重；同一编码在本句的不同位置仍可能分别指定原表。
    occurrences = [{**ref, 'start': m.start(), 'end': m.end()}
                   for ref in references for m in re.finditer(re.escape(ref['value']), question)
                   if ref['field'] != 'code' or not (
                       m.start() and re.fullmatch(r'[A-Za-z0-9_&.#-]', question[m.start()-1]) or
                       m.end() < len(question) and re.fullmatch(r'[A-Za-z0-9_&.#-]', question[m.end()]))]
    for ref in occurrences:
        prefix = question[:ref['start']]
        for domain, labels in DOMAIN_LABELS.items():
            pattern = '(' + '|'.join(sorted(map(re.escape, labels), key=len, reverse=True)) + r')(?:的)?(?:对象)?(?:编码|代码)?\s*[“「"\x27]?\s*$'
            match = re.search(pattern, prefix, flags=re.I)
            if not match:
                continue
            # 标识附近存在否定或比较时，不能视为肯定的对象选择。
            before = re.split(r'[，。；！？,;!?]', prefix[:match.start()])[-1]
            if any(word in before for word in ('不', '非', '排除', '而非', '区别', '比较', '对比')):
                continue
            explicit.setdefault(ref['value'], {})[domain] = question[match.start():ref['end']]
    result = {}
    for identifier, choices in explicit.items():
        if len(choices) == 1:
            domain, quote = next(iter(choices.items()))
            result[identifier] = {'domain': domain, 'source': 'current_qualified_literal', 'quote': quote}
    prior = previous or {}
    entity = prior.get('entity') or (prior.get('query_receipt') or {}).get('confirmed_subject') or {}
    lookup = prior.get('lookup_query') or {}
    prior_domain = lookup.get('target') or entity.get('tree')
    prior_identifiers = {entity.get('code'), entity.get('name')}
    prior_identifiers.update(f.get('value') for f in lookup.get('filters', [])
                             if f.get('field') in ('identity', 'code', 'name') and f.get('operator') == 'equals')
    grouped = {}
    for ref in references:
        grouped.setdefault(ref['value'], set()).add(ref['domain'])
    for identifier, domains in grouped.items():
        if identifier in explicit:
            continue
        has_domain_words = any(label.lower() in question.lower() for labels in DOMAIN_LABELS.values() for label in labels)
        if identifier in prior_identifiers and prior_domain in domains and not has_domain_words:
            result[identifier] = {'domain': prior_domain, 'source': 'same_identifier_executed_receipt'}
        elif len(domains) > 1 and not has_domain_words:
            result[identifier] = {'domain': 'objects', 'source': 'new_identifier_multiple_domains'}
    return result


def bind_lookup(target, identifier, current):
    binding = (current or {}).get(identifier)
    if not binding:
        return target, None
    return binding['domain'], {**binding, 'identifier': identifier,
                               'proposed_domain': target, 'effective_domain': binding['domain']}


def unqualified_names(question, references, previous):
    if any(label.lower() in question.lower() for labels in DOMAIN_LABELS.values() for label in labels):
        return []
    entity = (previous or {}).get('entity') or {}
    known = {entity.get('code'), entity.get('name')}
    known.update(f.get('value') for f in ((previous or {}).get('lookup_query') or {}).get('filters', [])
                 if f.get('operator') == 'equals')
    codes = {r['value'] for r in references if r['field'] == 'code'}
    return sorted({r['value'] for r in references if r['field'] == 'name' and r['value'] not in known | codes})
