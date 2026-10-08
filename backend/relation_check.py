"""依据真实父字段比较已登记对象引用，不使用编码前缀。"""
def validate_subjects(intent):
    subjects=intent.get('subjects')
    if intent.get('operation')!='relation_check':
        if subjects is not None:raise ValueError('只有关系核验可携带对象集合。')
        return
    if intent.get('entity') is not None or intent.get('scope')!='direct' or any(intent.get(k) is not None for k in ('query','analysis','properties','message','navigate','topics')):
        raise ValueError('关系核验仅接受独立对象集合。')
    if not isinstance(subjects,list) or not 2<=len(subjects)<=8:raise ValueError('关系核验需要2至8个对象。')
    for s in subjects:
        if not isinstance(s,dict) or set(s)!={'tree','identifier'} or s['tree'] not in ('pbs','config','equipment_class','part_class') or not isinstance(s['identifier'],str) or not 0<len(s['identifier'])<=300:raise ValueError('关系核验对象格式无效。')
    if len({(s['tree'],s['identifier']) for s in subjects})!=len(subjects):raise ValueError('关系核验对象不能重复。')

def execute(store,intent):
    validate_subjects(intent);nodes=[];missing=[];records=[];evidence=[]
    for subject in intent['subjects']:
        rows=store.rows('SELECT * FROM objects WHERE tree=? AND (code=? OR name=?)',(subject['tree'],subject['identifier'],subject['identifier']))
        if len(rows)!=1:
            missing.append(subject['identifier']+('未找到' if not rows else '匹配多个对象，需明确编码'));continue
        row=rows[0];nodes.append(row);ref=store.ref(row);evidence.append(ref)
        records.append({'cells':[row['name'],row['code'],row['parent'] or '未提供'], 'evidence':ref})
    edges=[{'parent':p['code'],'child':c['code'],'tree':c['tree']} for p in nodes for c in nodes if p['tree']==c['tree'] and p['code']==c['parent'] and p['code']!=c['code']]
    answer=('根据父对象字段确认：'+'；'.join(e['child']+' 的父对象是 '+e['parent'] for e in edges)+'。') if edges else '已定位对象之间未找到直接父子关系。'
    if missing:answer+='尚未完成核验：'+'；'.join(missing)+'。'
    return dict(answer=answer,status='clarify' if missing else 'ok',entity=None,scope='direct',records=records,columns=['对象名称','对象编码','父对象编码'],evidence=evidence,metrics=[],path=[],relation_edges=edges,note='逐个读取父字段；仅核验所列对象之间的直接关系，不按编码前缀推断，不自动切换当前对象。')
