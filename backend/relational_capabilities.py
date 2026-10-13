"""从实际引用记录登记图能力，不提供数量或把候选计划当作事实。"""
from relational_query import Graph,CLASS_LEVELS,ROLES

def reference_capabilities(store,references):
    nodes={}
    for ref in references:
        tree=ref.get('domain');value=ref.get('value')
        if tree not in ('pbs','config','equipment_class','part_class'):continue
        for row in store.rows('SELECT * FROM objects WHERE tree=? AND (code=? OR name=?)',[tree,value,value]):nodes[(tree,row['code'])]=row
    if not nodes:return []
    graph=Graph(store);out=[]
    for (tree,code),row in list(nodes.items())[:24]:
        links=graph.links(row)
        item={'source':{k:row[k] for k in ('tree','code','name','level')},
              'relation':{'kind':'relation','population':'objects','root_tree':tree,'target_tree':None,
                'roles':{role:{k:links[role][k] for k in ('tree','code','name','level')} for role in sorted(ROLES) if links.get(role)}},'collections':[]}
        if tree in ('pbs','config'):
            item['collections'].append({'root_tree':tree,'target_tree':None,'population':['objects','devices','parts'],'depth':['self','direct','all']})
        if tree=='config' and row['level'] in CLASS_LEVELS|{'设备'}:
            item['collections'].append({'root_tree':'config','target_tree':'pbs','population':['devices','parts'],'match':'精确设备构型型号；真实分类父链，保留深度'})
        if tree=='equipment_class':
            if links.get('config'):
                item['collections'] += [{'root_tree':tree,'target_tree':'pbs','population':['devices','parts'],'match':'程序按已核实分类或设备型号匹配'},
                    {'root_tree':tree,'target_tree':'config','population':['objects','devices','parts'],'match':'同码核实构型根的真实下级；设备型号用devices'}]
            else:
                item['collections']=[{'root_tree':tree,'target_tree':target,'population':['devices','parts'],'prerequisite':'role_verified','blocked':True,'on_missing':'data_insufficient，未计算，不是零'} for target in ('pbs','config')]
                item['blocked_reason']=links.get('role_reason') or '没有经过核实的构型引用；不能统计为零'
        out.append(item)
    return out
