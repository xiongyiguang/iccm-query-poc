"""提供数量受限的身份候选，不放宽实际执行查询的语义。"""
import copy
import hashlib,json

def suggestion_signature(store,target,field,value):
    """仅对属性未命中的同一原标识证明完整候选行相等，不认证实际查询。"""
    if field not in ('code','name','identity') or not isinstance(value,str) or not 3<=len(value)<=100:return None
    found=store.filtered({'operation':'search','entity':None,'scope':'direct','clarification':'','query':{'target':target,'filters':[{'field':field,'operator':'contains','value':value}]}})
    rows=sorted((r['tree'],r['code'],r['evidence']['line']) for r in found['records'])
    if not rows:return None
    return json.dumps({'literal':value,'rows':len(rows),'sha256':hashlib.sha256(json.dumps(rows,ensure_ascii=False).encode()).hexdigest()},ensure_ascii=False,sort_keys=True)

DETAILS={'attributes','object','measurement','threshold','parent','equipment','equipment_class','part_class'}

def suggest(store,intent,result):
    if intent.get('operation') not in DETAILS:return result
    query=copy.deepcopy(intent.get('query'))
    # 不改变显式 entity.name/code 契约；未限定字段的语言使用 identity，
    # 显式对象引用始终保持精确匹配。
    if not query:return result
    identifiers=[f for f in query['filters'] if f['field'] in ('identity','name','code')]
    if len(identifiers)!=1:return result
    ref=identifiers[0]
    if ref['operator']!='equals' or not 3<=len(ref['value'])<=100:return result
    ref['operator']='contains'
    found=store.filtered({**intent,'operation':'search','query':query})
    unique={}
    for row in found['records']:
        unique.setdefault((row['tree'],row['code']),row)
    if not unique:return result
    candidates=[{k:r[k] for k in ('tree','code','name','level','parent','evidence') if k in r} for r in list(unique.values())[:20]]
    return {**result,'status':'ambiguous','records':candidates,
            'answer':f'精确定位未命中，找到 {len(unique)} 个包含该标识的候选对象，展示前 {len(candidates)} 个。请点选完整名称或编码后继续原问题；尚未读取候选的属性或计算结果。',
            'note':'候选使用原范围及其他筛选条件，仅放宽标识为包含匹配；未自动选择。',
            'outcome':{**result['outcome'],'kind':'ambiguous','candidates':[{'tree':r['tree'],'code':r['code'],'name':r['name']} for r in candidates],'match_mode':'contains_suggestion','candidate_count':len(unique)},
            'candidate_only':True}
