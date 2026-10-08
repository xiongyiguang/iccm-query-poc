"""对共享筛选后的完整记录集合执行确定性聚合。"""
from collections import Counter
from query_filters import validate_query

GROUP_FIELDS={'points':{'location','status','switch','source'},'parts':{'class_code'},
              'pbs':{'level','type'},'config':{'level','type'},'equipment':{'level','type'},
              'equipment_class':{'level'},'part_class':{'level'}}

def planner_groups():
    return {target:sorted(fields) for target,fields in GROUP_FIELDS.items()}

def validate_analysis(intent):
    validate_query(intent.get('query'))
    a=intent.get('analysis')
    if not isinstance(a,dict) or set(a)!={'kind','group_by','order','limit','numerator'}:
        raise ValueError('统计结构不完整，未执行。')
    if a['kind'] not in ('group_count','ratio') or a['order'] not in ('asc','desc') or type(a['limit']) is not int or not 1<=a['limit']<=100:
        raise ValueError('统计方式、排序或数量限制不支持。')
    target=intent['query']['target']
    allowed=GROUP_FIELDS
    if a['kind']=='group_count':
        if a['group_by'] not in allowed.get(target,set()) or a['numerator']!=[]:
            raise ValueError('该目标不支持指定分组。')
    else:
        if a['limit']!=100 or a['order']!='desc':
            raise ValueError('占比不支持排名数量或排序；请重新明确统计方式。')
        if target!='points' or a['group_by'] is not None or not a['numerator']:
            raise ValueError('占比需要测点记录分母及额外分子条件。')
        validate_query({'target':target,'filters':a['numerator']})
        validate_query({'target':target,'filters':intent['query']['filters']+a['numerator']})
    return a

def execute_analysis(store,intent):
    a=validate_analysis(intent)
    base=store.filtered(intent)
    records=base['records'];total=len(records)
    result={**base,'records':[],'metrics':[],'aggregation':True,'analysis':a,'columns':['分组名称','编码','记录数'],'evidence':base['evidence']+[r['evidence'] for r in records]}
    scope='全部目标记录' if not base['entity'] else base['entity']['code']+'（'+('全部下级' if intent['scope']=='all' else '直接下级')+'）'
    result['note']=base['note']+'统计单位：记录；所有分组均基于完整结果，非当前页。'
    if a['group_by']=='type':
        result['columns']=['对象类型','原始类型值','对象数']
        result['note']=base['note']+'统计单位：对象；按原始对象类型字段分组，缺失类型单独列出，不使用层级编号代替。'
    if a['group_by']=='level':
        result['columns']=['层级描述','原始层级值','对象数']
        result['note']=base['note']+'统计单位：对象；按原始层级字段分组，所有分组基于完整结果，非当前页。'
    if a['kind']=='ratio':
        q={'target':'points','filters':intent['query']['filters']+a['numerator']}
        n=len(store.filtered({**intent,'query':q})['records'])
        if n>total:raise ValueError('分子不能超过分母。')
        pct=f'{n/total*100:.2f}%' if total else '无法计算（分母为0）'
        result['answer']=f'符合附加条件 {n} 条 / 基础筛选 {total} 条，占比 {pct}。'
        result['metrics']=[{'label':'分子记录','value':n},{'label':'分母记录','value':total},{'label':'占比','value':pct}]
        result['columns']=['统计项','记录数']
        result['records']=[{'cells':['分子',n]},{'cells':['分母',total]}]
        from query_filters import describe
        result['note']+='分子附加条件：'+describe(q)
        result['chart']={'kind':'ratio','numerator':n,'denominator':total}
    else:
        counts=Counter();names={};verified_classes=set();unknown_codes=set();missing_records=0
        locations={}
        if a['group_by']=='location':
            for loc in store.rows("SELECT o.code child,o.code,o.name,0 depth FROM objects o WHERE o.tree='pbs' AND o.level='功能位置' UNION ALL SELECT a.child,o.code,o.name,a.depth FROM ancestors a JOIN objects o ON o.tree=a.tree AND o.code=a.ancestor WHERE a.tree='pbs' AND o.level='功能位置' ORDER BY depth,code"):
                locations.setdefault(loc['child'],loc)
        classes={r['code']:r for r in store.rows("SELECT * FROM objects WHERE tree='part_class'")} if a['group_by']=='class_code' else {}
        for row in records:
            key=row.get(a['group_by']) or ''
            name=key or '未提供'
            if a['group_by'] in ('level','type'):
                from attributes import CATALOG
                field=CATALOG[a['group_by']]['fields'][row['tree']]
                key=row['evidence']['fields'].get(field) or ''
                name=key or '未提供'
            elif a['group_by']=='class_code':
                found=[classes[key]] if key in classes else []
                name=found[0]['name'] if found else ('未匹配部件类' if key else '未提供部件类')
                if found:
                    verified_classes.add(key)
                    result['evidence'].append(store.ref(found[0]))
                elif key:unknown_codes.add(key)
                else:missing_records+=1
            elif a['group_by']=='location':
                nearest=locations.get(row['code'])
                key=nearest['code'] if nearest else '';name=nearest['name'] if nearest else '未匹配功能位置'
            elif a['group_by']=='status':key=row.get('state') or '';name=key or '未提供'
            counts[key]+=1;names[key]=name
        assert sum(counts.values())==total
        groups=sorted(counts,key=lambda k:((-counts[k]) if a['order']=='desc' else counts[k],k))
        result['records']=[{'cells':[names[k],k or '—',counts[k]]} for k in groups[:a['limit']]]
        result['answer']=f'{scope}：共 {total} 条记录，分为 {len(groups)} 组，按数量'+('降序' if a['order']=='desc' else '升序')+f'展示 {len(result["records"])} 组。'
        result['metrics']=[{'label':'参与统计记录','value':total},{'label':'分组总数','value':len(groups)}]
        result['note']+='同数按编码排列；未匹配归属单独成组。'
        if a['group_by']=='class_code':
            result['classification_coverage']={'verified_class_count':len(verified_classes),'unmatched_codes':sorted(unknown_codes),'missing_class_records':missing_records}
            unit='现场部件' if base.get('grain')=='pbs_object' else '部件构型'
            result['answer']=f'{scope}：共 {total} 个{unit}，已确认 {len(verified_classes)} 类部件。'
            if unknown_codes or missing_records:
                result['answer']+=f'另有 {len(unknown_codes)} 个类别编码未匹配字典、{missing_records} 个部件未提供类别，不能据此确认完整类别数。'
            result['answer']+=f'当前展示 {len(result["records"])} 个分组（共 {len(groups)} 组）。'
        result['chart']={'kind':'bars','items':[{'label':names[k] if a['group_by']=='level' else names[k]+' ('+(k or '未匹配')+')','value':counts[k]} for k in groups[:a['limit']]],'total_groups':len(groups)}
    return result
