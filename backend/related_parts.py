"""在受限对象范围内解析类型明确的设备分类。"""
from query_filters import validate_query, predicates, describe

def execute_related_parts(store,intent):
    from data import QueryError,BusinessOutcome
    q=intent['query'];validate_query(q)
    entity=intent.get('entity')
    if not entity or entity['tree'] not in ('pbs','config'):
        raise QueryError('跨树部件查询需要明确PBS或构型范围；未扩大到全局。')
    root=store.obj(entity['tree'],entity['code']);evidence=[store.ref(root)]
    terms,args=predicates({'target':'equipment_class','filters':[q['equipment_class']]},'c')
    classes=store.rows("SELECT c.* FROM objects c WHERE c.tree='equipment_class' AND "+' AND '.join(terms),args)
    if len(classes)!=1:
        raise BusinessOutcome('not_found' if not classes else 'ambiguous', '本次导入的设备类数据中，未找到'+('名称' if q['equipment_class']['field']=='name' else '标识')+'为「'+q['equipment_class']['value']+'」的记录，因此无法继续统计其部件。请核对设备类名称或编码。' if not classes else '设备分类「'+q['equipment_class']['value']+'」对应多个编码，请指定分类编码。',q['equipment_class'],[{k:r[k] for k in ('tree','code','name')} for r in classes[:20]])
    cls=classes[0];evidence.append(store.ref(cls))
    tree=entity['tree']
    devices=store.rows("SELECT o.* FROM objects o WHERE o.tree=? AND o.level='设备' AND (o.code=? OR o.code IN (SELECT child FROM ancestors WHERE tree=? AND ancestor=?))",(tree,root['code'],tree,root['code']))
    def exact_config(obj):
        if tree=='config':return obj
        code=obj['code'].split('&',1)[1] if '&' in obj['code'] else ''
        found=store.rows("SELECT * FROM objects WHERE tree='config' AND code=? AND level=?",(code,obj['level']))
        if not found:raise BusinessOutcome('incomplete','对象 '+obj['code']+' 缺少经过校验的构型关联，无法完整统计。',{'tree':tree,'code':obj['code']})
        evidence.append(store.ref(found[0]));return found[0]
    selected=[]
    for device in devices:
        cfg=exact_config(device)
        matches=cfg['code']==cls['code'] or bool(store.rows("SELECT 1 FROM ancestors WHERE tree='config' AND child=? AND ancestor=?",(cfg['code'],cls['code'])))
        if matches:selected.append(device)
    parts={}
    terms,args=predicates({'target':'parts','filters':q['filters']},'c')
    for device in selected:
        if intent['scope']=='direct':
            found=store.rows("SELECT * FROM objects WHERE tree=? AND parent=? AND level='部件'",(tree,device['code']))
        else:
            found=store.rows("SELECT o.* FROM ancestors a JOIN objects o ON o.tree=a.tree AND o.code=a.child WHERE a.tree=? AND a.ancestor=? AND o.level='部件'",(tree,device['code']))
        evidence.append(store.ref(device))
        for part in found:
            cfg=exact_config(part)
            if terms and not store.rows("SELECT 1 FROM objects c WHERE c.tree='config' AND c.code=? AND "+' AND '.join(terms),[cfg['code']]+args):continue
            parts[part['code']]={'tree':tree,'code':part['code'],'name':part['name'],'level':part['level'],'parent':part['parent'],'class_code':cfg['class_code'],'evidence':store.ref(part)}
    records=sorted(parts.values(),key=lambda x:x['code'])
    note='查询口径：'+describe(q).replace('部件构型','现场部件' if tree=='pbs' else '部件构型')+'；范围：'+root['code']+'；按实际父子关系查找，部件对象按编码去重；设备数 '+str(len(selected))+'。'
    return dict(answer='符合条件的部件对象：'+str(len(records))+' 个。',status='ok',records=records,evidence=evidence,metrics=[{'label':'部件对象','value':len(records)}],entity=entity,scope=intent['scope'],path=[{k:root[k] for k in ('tree','code','name','level')}],query=q,note=note,grain='pbs_object' if tree=='pbs' else 'config_object')
