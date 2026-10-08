"""解释实际执行回执，不返回泛化的产品介绍。"""
from query_filters import describe

def explain_result(previous):
    empty=dict(records=[],metrics=[],path=[],entity=None,scope='direct',evidence=[])
    if not previous or not previous.get('query_receipt'):
        return dict(**empty,status='clarify',answer='当前没有可解释的成功查询，请先完成查询；多项结果请明确要解释哪一项。',note='未推断查询过程。')
    receipt=previous['query_receipt'];subject=receipt.get('requested_entity') or receipt.get('resolved_entity')
    parts=['本次依据导入快照查询，结果按原始记录计算。']
    if subject:parts.append('查询对象：'+subject['tree']+' / '+subject['code']+'。')
    q=receipt.get('query')
    if q:parts.append('实际条件：'+describe(q)+'。')
    op=receipt['operation']
    if op=='parts' or q and q['target']=='parts':
        parts.append('先定位构型对象，再读取真实父对象引用；'+('只保留父编码直接等于当前构型编码的部件。' if receipt['scope']=='direct' else '沿父引用逐层遍历全部后代，再按部件层级筛选；不是通过编码前缀猜测。'))
    if previous.get('note'):parts.append(previous['note'])
    refs=previous.get('evidence',[])+[r['evidence'] for r in previous.get('records',[])[:10] if r.get('evidence')]
    refs=list({(e['file'],e['line']):e for e in refs}.values())
    return dict(**{**empty,'entity':previous.get('entity'),'scope':previous.get('scope','direct'),'evidence':refs},status='conversation',answer=''.join(parts),note='解释绑定上一次成功结果；可展开原始行核对。',explained_receipt=receipt)
