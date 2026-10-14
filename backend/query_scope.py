"""目录级全表计数契约；仅处理明确表范围的无条件计数，不定位树节点。"""
import re

TABLES={'config':('构型树','构型表'),'pbs':('PBS树','PBS表'),'equipment_class':('设备类表','设备类字典'),'part_class':('部件类表','部件类字典'),'points':('监测表','测点表','测量点表')}

def table_count(question,store):
    if store is None:return None
    hits=[(target,alias) for target,aliases in TABLES.items() for alias in aliases if alias.casefold() in question.casefold()]
    if len(hits)!=1:return None
    target,alias=hits[0];text=re.sub(re.escape(alias),'',question,flags=re.I)
    if not re.search(r'多少|几[个条]|数量|总数|总量',text):return None
    # 完整覆盖剩余语义才应用确定性契约，含节点、日期、过滤、否定的输入仍走模型。
    tokens=('对象代码','对象编码','不同编码','对象','记录','数据','测点','编码','代码','总共有','共有','一共','合计','总数','总量','数量','多少','几个','几条','全部','所有','统计','查询','请问','请','里面','里边','当中','之中','中','内','里','有','个','条')
    text=re.sub('|'.join(map(re.escape,sorted(tokens,key=len,reverse=True))),'',text)
    if text.strip(' \t\n？?。！!，,：:'):return None
    if target=='points' and any(x in question for x in ('编码','代码')):return None
    from result_goal import default_goal
    return {'operation':'search','entity':None,'scope':'direct','clarification':'','query':{'target':target,'filters':[]},'result_goal':{**default_goal('search'),'kind':'count'}}

def domain_clarification(question,context,store):
    if store is None or not re.search(r'(?:对应|所属).*?(?:设备类|部件类)',question):return None
    from request_checklist import literal_references
    from identifier_aliases import complete_literal_pattern
    from relational_state import TREE_HINTS
    refs=literal_references(question,store);values={r['value'] for r in refs if r['field'] in ('name','code')}
    if len(values)!=1:return None
    value=next(iter(values));domains={r['domain'] for r in refs if r['value']==value}
    if len(domains)<2:return None
    for m in re.finditer(complete_literal_pattern(value),question):
        prefix=re.split(r'[，。；;！？!?]',question[:m.start()])[-1]
        if any(w.lower() in prefix.lower() for tree in domains for w in TREE_HINTS.get(tree,())):return None
    entity=context.get('entity') or {}
    if entity.get('tree') in domains and entity.get('code')==value:return None
    labels={'config':'构型树','pbs':'PBS树','equipment_class':'设备类表','part_class':'部件类表','points':'测点表'}
    return {'operation':'clarify','entity':None,'scope':'direct','clarification':'该标识在多个数据表中存在，请确认您指的是'+ '、'.join(labels.get(d,d) for d in sorted(domains))+'中的哪个对象。尚未执行查询。'}

def public_request(question,context,store):
    if not context.get('pending_business_request') and question.strip().strip('。！？!?') in ('直接下级','直属','全部下级','所有下级'):
        receipt=context.get('query_receipt') or {};query=receipt.get('query') or {}
        if receipt.get('operation')=='search' and receipt.get('resolved_entity') is None and query.get('target') in TABLES and query.get('filters')==[]:
            return {'operation':'clarify','entity':None,'scope':'direct','clarification':'刚才查询的是整张数据表。请指定要查看下级的根对象；尚未执行新的查询。'}
    return table_count(question,store) or domain_clarification(question,context,store)
