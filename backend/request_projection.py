"""用原话字段和同一真实测点证明单字段交付，保留其他任务和全部条件。"""
import json,re
from attributes import CATALOG

def explicit_scalar_projection_choice(question,a,b,future_a,future_b,store):
    if store is None or a.get('target')!='points' or b.get('target')!='points':return None
    if {a.get('result_goal',{}).get('kind'),b.get('result_goal',{}).get('kind')}!={'records','attributes'}:return None
    rows=[t for t in (a,b) if t.get('operation')=='search' and not t.get('properties')]
    attrs=[t for t in (a,b) if t.get('operation')=='attributes' and t.get('properties')]
    strip=lambda t:{k:v for k,v in t.items() if k not in ('operation','properties','result_goal')}
    if len(rows)!=1 or len(attrs)!=1 or strip(a)!=strip(b):return None
    filters=a.get('filters',[])
    if len(filters)!=1 or filters[0][0:2] not in (('resolved_identity','equals'),['resolved_identity','equals']):return None
    identities=json.loads(filters[0][2])
    if len(identities)!=1:return None
    from request_checklist import literal_references
    references=literal_references(question,store);actual=set();text=question
    for ref in references:
        if ref['domain']!='points' or ref['field'] not in ('name','code'):return None
        found=store.rows('SELECT line,code FROM points WHERE '+ref['field']+'=?',[ref['value']])
        actual.update((row['line'],row['code']) for row in found)
        text=text.replace(ref['value'],' ')
    if actual!={tuple(identities[0])}:return None
    if re.search(r'排序|排名|分组|统计|数量|多少|总数|求和|平均|差值|相减|相加|相乘|比例|最大|最小|最高|最低|最早|最新|大于|小于|超过|至少|最多|等于|[<>]|前\s*[0-9一二三四五六]',text):return None
    if not re.search(r'读取|查询|查看|显示|给出|返回|告诉',text):return None
    properties=set()
    for key,spec in CATALOG.items():
        if key in ('code','name','type','level','parent') or 'points' not in spec['fields']:continue
        aliases={spec['label'],spec['fields']['points']}
        if any(re.search(r'(?:的|读取|查询|查看|显示|给出|返回)\s*[^，。；;！？!?]{0,8}'+re.escape(alias),text) for alias in aliases):properties.add(key)
    if properties!=set(attrs[0]['properties']):return None
    # 去掉当前任务的交付差异后，完整未来状态必须相同；其他任务不豁免。
    tid=a['task_id']
    normalize=lambda tasks:[strip(t) if t['task_id']==tid else t for t in tasks]
    if normalize(future_a)!=normalize(future_b):return None
    return 'candidate' if a['operation']=='attributes' else 'independent'
