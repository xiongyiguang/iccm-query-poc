"""受限跨表查询：模型选择槽位，真实父边、粒度和缺失规则由程序执行。"""
import copy
import json
from collections import Counter, defaultdict
from attributes import CATALOG
from data import QueryError
from query_filters import validate_query, POINT_FIELDS, POINT_RAW_FIELDS
from typed_fields import compare, NUMERIC_OPS

TREES={'pbs','config','equipment_class','part_class','points'}
ROLES={'subject','pbs','pbs_parent','pbs_part','pbs_device','config','equipment_config','equipment_class','part_class','parent'}
ROLE_LABELS={'subject':'查询对象','pbs':'精确PBS对象','pbs_parent':'PBS直接父对象','pbs_part':'最近现场部件','pbs_device':'最近现场设备','config':'该结构对象的精确构型','equipment_config':'所属设备构型','equipment_class':'所属设备类','part_class':'所属部件类','parent':'同树直接父对象'}
TREE_LABELS={'pbs':'PBS树','config':'构型树','equipment_class':'设备类表','part_class':'部件类表','points':'监测表'}
DEFAULTS={'root':None,'kind':'relation','population':'objects','depth':'all','classes':{},'filters':[],
          'group_by':None,'properties':[],'limit':None,'sort':[],'only':None,'boundary':None,'compare_root':None}


def canonical(spec):
    if not isinstance(spec,dict) or set(spec)-set(DEFAULTS):raise ValueError('关系查询含未知槽位。')
    q={**copy.deepcopy(DEFAULTS),**copy.deepcopy(spec)}
    # 关系视图只读取一个精确对象；显式集合目标/分组不能被单对象
    # 默认值吞掉。两种等价集合写法归一化后保留所有范围槽位。
    if q['kind']=='relation' and (q['group_by'] is not None or q['root'] is None or q['population']!='objects' and q['depth']!='self' and q['root']['tree']!='points'):
        q['kind']='collection'
    if q['kind'] not in ('relation','collection','compare','boundary'):raise ValueError('未知关系操作。')
    if q['population'] not in ('objects','parts','devices','points') or q['depth'] not in ('self','direct','all'):raise ValueError('集合粒度无效。')
    for key in ('root','compare_root'):
        r=q[key]
        if r is not None and (not isinstance(r,dict) or set(r)!={'tree','field','value'} or r['tree'] not in TREES or r['field'] not in ('code','name','identity') or not isinstance(r['value'],str) or not 0<len(r['value'])<=200):raise ValueError('关系根必须是精确对象标识。')
    if q['kind']=='relation' and not q['root']:raise ValueError('关系查询缺少根对象。')
    if not isinstance(q['classes'],dict) or set(q['classes'])-{'equipment_class','part_class'} or any(not isinstance(v,str) or not v for v in q['classes'].values()):raise ValueError('分类引用无效。')
    if not isinstance(q['filters'],list):raise ValueError('筛选条件必须为列表。')
    point_query=q['population']=='points' or (q['root'] or {}).get('tree')=='points'
    for f in q['filters']:
        if isinstance(f,dict) and not point_query and f.get('field')=='type':f['field']='level'
    # 对象类型等值筛选与受限集合是同一语义，不能因为两种写法而
    # 丢弃子设备或把原始层级数字当作对象类型。
    types=[f.get('value') for f in q['filters'] if isinstance(f,dict) and f.get('field')=='level' and f.get('operator')=='equals']
    if not point_query and q['population']=='objects' and len(types)==1 and types[0] in ('部件','设备'):
        q['population']='parts' if types[0]=='部件' else 'devices'
    fixed='部件' if q['population']=='parts' else '设备' if q['population']=='devices' else None
    if fixed:q['filters']=[f for f in q['filters'] if f!={'field':'level','operator':'equals','value':fixed}]
    validate_query({'target':'points' if point_query else 'pbs','filters':q['filters']})
    if q['group_by'] not in (None,'class','type','source','location'):raise ValueError('分组字段无效。')
    if q['only'] not in (None,'missing_class','unmatched'):raise ValueError('关联缺失筛选无效。')
    if (q['group_by'],q['only']) in (('location','unmatched'),('class','missing_class')):raise ValueError('完整分组已包含缺失组；仅选缺失者是另一种记录视图，不能同时表达。')
    if q['boundary'] not in (None,'health','duration','classification','same_record'):raise ValueError('结论边界无效。')
    if q['limit'] is not None and (type(q['limit']) is not int or not 1<=q['limit']<=100):raise ValueError('展示限制无效。')
    if not isinstance(q['properties'],list) or len(q['properties'])>30 or any(p not in CATALOG and p not in ('line','pbs_part','location') for p in q['properties']):raise ValueError('关系投影不在字段目录。')
    if not isinstance(q['sort'],list) or any(p not in ('code','pbs_part','name','source','line') for p in q['sort']):raise ValueError('排序字段无效。')
    q['filters']=sorted(q['filters'],key=lambda f:(f['field'],f['operator'],f['value']))
    q['properties']=sorted(set(q['properties']))
    if q['kind']=='relation':
        if q['classes'] or q['filters'] or q['group_by'] or q['limit'] or q['sort'] or q['only']:raise ValueError('单对象关系不能丢弃集合条件。')
        # 这些基础属性及关系编码始终交付，显式再选与默认展示等价。
        q['properties']=[p for p in q['properties'] if p not in ('code','name','type','level','parent','class_code','pbs_part')]
        q.update(population='objects',depth='all')
    elif q['kind'] in ('collection','compare','boundary'):
        if q['group_by']=='type' and q['population'] in ('parts','devices'):q['group_by']=None
        base={'code','name'}|({'source','line','status','pbs_part','location'} if q['population']=='points' else set())
        q['properties']=[p for p in q['properties'] if p not in base]
        if q['group_by']=='class':q['properties']=[p for p in q['properties'] if p!='class_code']
        if q['group_by']:q['sort']=[]
        elif not q['sort']:q['sort']=['pbs_part','code'] if q['population']=='points' else ['code']
        # 测点快照的健康边界是所有集合结果的固定说明，不改变筛选。
        if q['kind']=='collection' and q['boundary']=='health':q['boundary']=None
    if q['root'] is None:q['depth']='all'
    if q['kind']=='compare':q['properties']=[p for p in q['properties'] if p not in ('code','name','type','level','parent')]
    if q['kind']=='boundary' and not q['boundary']:raise ValueError('结论缺少边界类型。')
    if q['kind']=='compare' and (not q['root'] or q['root']['tree']!='pbs' or not q['compare_root'] or q['compare_root']['tree']!='config' or q['population']!='parts' or q['depth']!='all'):
        raise ValueError('compare仅支持PBS全部部件与精确构型根核对；同码跨表记录请用分别指定原表的relation任务。')
    if q['boundary']=='same_record' and q['kind']!='relation':raise ValueError('same_record只能附于各原表的relation任务，不新增解释任务。')
    if q['population']=='points' and q['root'] and q['root']['tree']=='points' and q['kind']=='collection':q['depth']='self'
    if q['kind']=='boundary' and q['boundary']=='health':
        if not q['root'] or q['root']['tree']!='pbs':raise ValueError('健康证据检查需保留明确PBS范围。')
        # 健康诊断固定交付完整监测覆盖及当前有效报警两个维度，
        # 不用某个报警子集冒充整个监测范围。
        q.update(population='points',depth='all',group_by=None,properties=[],limit=None,only=None,sort=['pbs_part','code'])
        q['filters']=[f for f in q['filters'] if f['field'] not in ('status','switch')]
    if q['kind']=='boundary' and q['boundary']=='classification':q.update(population='parts',only='missing_class',group_by=None,properties=[],limit=None,sort=['code'])
    if q['kind']=='boundary' and q['boundary']=='duration':q.update(population='points',depth='all',filters=[],group_by=None,properties=[],limit=None,only=None,sort=['pbs_part','code'])
    return q


def validate_plan(plan):
    if not isinstance(plan,dict) or set(plan)!={'operation','entity','scope','clarification','relational_tasks'} or plan['operation']!='relational' or plan['entity'] is not None or plan['scope']!='direct' or plan['clarification']!='':raise ValueError('关系任务外层无效。')
    tasks=plan['relational_tasks']
    if not isinstance(tasks,list) or not 1<=len(tasks)<=4:raise ValueError('关系任务数量无效。')
    for t in tasks:
        if not isinstance(t,dict) or set(t)!={'id','spec'} or type(t['id']) is not int or not 1<=t['id']<=4:raise ValueError('关系任务身份无效。')
        t['spec']=canonical(t['spec'])
    if len({t['id'] for t in tasks})!=len(tasks):raise ValueError('关系任务身份重复。')
    same=[t for t in tasks if t['spec']['boundary']=='same_record']
    if same and (len(same)<2 or len({t['spec']['root']['tree'] for t in same})<2):raise ValueError('same_record需要至少两个不同原表的relation任务；单监测对象关联缺失使用boundary:null。')
    return plan


class Graph:
    def __init__(self,store):
        self.store=store
        self.objects={(r['tree'],r['code']):r for r in store.rows('SELECT * FROM objects')}
        self.parents={}
        self.link_cache={}
    def chain(self,row):
        if not row or row.get('tree')=='points':return []
        key=(row['tree'],row['code'])
        if key not in self.parents:
            out=[];seen=set();r=row
            while r and r['code'] not in seen and len(out)<=64:
                seen.add(r['code']);out.append(r);r=self.objects.get((r['tree'],r['parent']))
            self.parents[key]=out
        return self.parents[key]
    def config(self,row):
        if not row:return None
        if row['tree']=='config':return row
        if row['tree']!='pbs' or row['level'] not in ('设备','子设备','部件') or '&' not in row['code']:return None
        c=self.objects.get(('config',row['code'].split('&',1)[1]))
        return c if c and c['level']==row['level'] else None
    def links(self,row):
        key=(row.get('tree','points'),row.get('code'),row.get('line'))
        if key in self.link_cache:return self.link_cache[key]
        pbs=row if row.get('tree')=='pbs' else self.objects.get(('pbs',row['code'])) if row.get('tree','points')=='points' else None
        chain=self.chain(pbs);own=self.chain(row) if row.get('tree')=='config' else []
        part=next((r for r in chain+own if r['level']=='部件'),None)
        device=next((r for r in chain+own if r['level']=='设备'),None)
        structural=next((r for r in chain if r['level'] in ('设备','子设备','部件')),None)
        config=self.config(structural) if pbs else self.config(row)
        dc=self.config(device);pc=self.config(part)
        out={'subject':row,'pbs':pbs,'pbs_parent':self.objects.get(('pbs',pbs['parent'])) if pbs else None,
             'pbs_part':part if part and part['tree']=='pbs' else None,'pbs_device':device if device and device['tree']=='pbs' else None,
             'config':config,'equipment_config':dc,
             'equipment_class':self.objects.get(('equipment_class',dc['parent'])) if dc else None,
             'part_class':self.objects.get(('part_class',pc['class_code'])) if pc and pc['class_code'] else None,
             'parent':self.objects.get((row['tree'],row['parent'])) if row.get('tree') in TREES-{'points'} else None}
        out['location']=next((r for r in chain if r['level']=='功能位置'),None)
        if part:
            out['classification_reason']=('缺少精确构型记录或对象类型不一致' if not pc else '所属部件类字段未提供' if not pc['class_code'] else '分类字典缺少引用编码' if not out['part_class'] else '')
        elif row.get('tree')=='config' and row['level']=='部件':
            out['classification_reason']='所属部件类字段未提供' if not row['class_code'] else '分类字典缺少引用编码'
        else:out['classification_reason']='没有实际部件父关系'
        self.link_cache[key]=out
        return out
    def resolve(self,root):
        if not root:return None
        field=root['field'];value=root['value'];tree=root['tree']
        if tree=='points':
            clause='(code=? OR name=?)' if field=='identity' else field+'=?'
            return [{**r,'tree':'points'} for r in self.store.rows('SELECT * FROM points WHERE '+clause,[value,value] if field=='identity' else [value])]
        found=[r for (t,_),r in self.objects.items() if t==tree and (r['code']==value or r['name']==value if field=='identity' else r[field]==value)]
        if len(found)!=1:raise QueryError('精确根对象未找到或名称不唯一，未计算集合数量。')
        return found[0]
    def desc(self,root,depth):
        if depth=='self':return [root]
        if depth=='direct':return [r for (t,_),r in self.objects.items() if t==root['tree'] and r['parent']==root['code']]
        codes={r['child'] for r in self.store.rows('SELECT child FROM ancestors WHERE tree=? AND ancestor=?',(root['tree'],root['code']))}
        return [self.objects[(root['tree'],c)] for c in codes]
    def value(self,row,key):
        if key=='line':return self.store.ref(row)['line']
        if key in ('pbs_part','location'):
            related=self.links(row).get(key);return related['code'] if related else '未匹配'
        if key=='source' and row.get('tree')=='points':return row['system']
        spec=CATALOG.get(key,{})
        field=spec.get('fields',{}).get(row.get('tree','points'))
        raw=json.loads(row['raw'])
        return raw.get(field,'') if field else row.get(key,'')
    def sort_rows(self,rows,fields):
        return sorted(rows,key=lambda r:tuple(self.store.ref(r)['line'] if p=='line' else str(self.value(r,p)) for p in fields)+(r['code'],r['line']))
    def matches(self,row,filters):
        for f in filters:
            value=str(row[f['field']] if row.get('tree')!='points' and f['field'] in ('name','code','level','parent','class_code') else self.value(row,f['field'])) if f['field']!='identity' else None
            expected=f['value'];op=f['operator']
            if f['field']=='identity':ok=expected in (row['code'],row['name']) if op=='equals' else any(expected in row[k] for k in ('code','name'))
            elif op in NUMERIC_OPS:ok=bool(compare(value,op,expected))
            elif op=='equals':ok=value==expected
            elif op=='contains':ok=expected in value
            elif op=='not_contains':ok=expected not in value
            elif op=='starts_with':ok=value.startswith(expected)
            elif op=='is_blank':ok=not value.strip()
            elif op=='not_blank':ok=bool(value.strip())
            else:raise QueryError('关系入口暂不支持该标量条件，请使用单表查询。')
            if not ok:return False
        return True
    def classify(self,classes):
        out={}
        for tree,value in classes.items():
            found=[r for (t,_),r in self.objects.items() if t==tree and value in (r['code'],r['name'])]
            if len(found)!=1:raise QueryError('分类描述或编码未唯一对应字典记录，未把缺失当作零。')
            out[tree]=found[0]['code']
        return out
    def population(self,q,root):
        wanted=q['population'];classes=self.classify(q['classes'])
        if wanted=='points':
            rows=[{**r,'tree':'points'} for r in self.store.rows('SELECT * FROM points')]
            if isinstance(root,list):allowed={r['line'] for r in root};rows=[r for r in rows if r['line'] in allowed]
            elif root:
                if root['tree']!='pbs':raise QueryError('测点范围必须是实际PBS对象，不能把构型反向猜作实例。')
                codes={root['code'],*(r['code'] for r in self.desc(root,q['depth']))}
                rows=[r for r in rows if r['code'] in codes]
        else:
            if isinstance(root,list):raise QueryError('监测记录不能作为结构集合根。')
            rows=self.desc(root,q['depth']) if root else [r for r in self.objects.values() if r['tree']=='pbs']
            if wanted in ('parts','devices'):rows=[r for r in rows if r['level']==('部件' if wanted=='parts' else '设备')]
        out=[]
        for r in rows:
            links=self.links(r)
            if any(not links[k] or links[k]['code']!=v for k,v in classes.items()):continue
            if q['only']=='missing_class' and not links['classification_reason']:continue
            if q['only']=='unmatched' and links['location']:continue
            if self.matches(r,q['filters']):out.append(r)
        return sorted(out,key=lambda r:(r['code'],r['line']))


def public_object(graph,row):
    if row is None:return None
    out={k:row.get(k) for k in ('tree','code','name','parent','level','class_code')}
    out['source']=graph.store.ref(row)
    return out


def execute_task(graph,q):
    root=graph.resolve(q['root']);evidence=[];record_rows=[];resolved={};missing=[]
    result={'answer':'','status':'ok','records':record_rows,'metrics':[],'evidence':evidence,'path':[],'entity':q['root'] and {'tree':q['root']['tree'],'code':(root[0] if isinstance(root,list) and root else root or {}).get('code',q['root']['value'])},'scope':q['depth'],'note':'真实父关系和精确引用；不同对象树及原测点记录分别保留。'}
    if q['kind']=='boundary' and q['boundary']=='duration':
        if root and not isinstance(root,list):evidence.append(graph.store.ref(root))
        return {**result,'status':'data_insufficient','answer':'当前表没有报警开始时间、恢复时间及完整历史事件，无法计算所问累计报警时长。当前报警为零也不能作为历史时长零。','relational_resolved':{},'duration_computed':False}
    if q['kind']=='boundary' and q['boundary']=='health':
        monitored=graph.population(q,root)
        alarms=[r for r in monitored if r['switch']=='开启' and r['status']=='已报警']
        m,d=len(monitored),len({r['code'] for r in monitored})
        result.update(answer=f'当前开启且已报警 {len(alarms)} 条；完整监测范围 {m} 条、{d} 个不同完整编码。当前报警为零也不能证明全部部件健康；监测覆盖、历史状态和完整诊断依据不足。',
            metrics=[{'label':'原记录/对象数量','value':len(alarms)},{'label':'不同完整编码数','value':len({r['code'] for r in alarms})},{'label':'监测覆盖原记录数','value':m},{'label':'监测覆盖不同完整编码数','value':d}],
            records=[{'tree':'points','code':r['code'],'name':r['name'],'source':r['system'],'state':r['status'],'evidence':graph.store.ref(r)} for r in alarms],
            evidence=[graph.store.ref(r) for r in monitored],health_snapshot={'monitored_records':m,'monitored_codes':d,'active_alarm_records':len(alarms),'healthy_proven':False},relational_resolved={})
        return result
    if q['kind']=='relation':
        subjects=root if isinstance(root,list) else [root]
        result['columns']=['关系/字段','对象编码','对象描述或字段','类型/层级或字段值','父编码','说明']
        projected=[]
        for subject in subjects:
            links=graph.links(subject)
            for role in sorted(ROLES):
                row=links.get(role)
                resolved.setdefault(role,[])
                if row:
                    fact=public_object(graph,row);resolved[role].append(fact);evidence.append(fact['source'])
                    record_rows.append({'cells':[ROLE_LABELS[role]+' / '+TREE_LABELS[row.get('tree','points')],row['code'],row['name'],row.get('level','未提供'),row.get('parent','未提供'),links.get('classification_reason','') if role=='part_class' else '']})
                elif (role=='pbs' and subject.get('tree')=='points' or
                      role=='config' and links.get('pbs') and links['pbs']['level'] in ('设备','子设备','部件','时序测点') or
                      role=='part_class' and (links.get('pbs_part') or subject.get('tree')=='config' and subject.get('level')=='部件') or
                      role=='equipment_class' and links.get('equipment_config')):
                    missing.append({'role':role,'subject':subject['code'],'reason':links.get('classification_reason') if role=='part_class' else '没有精确关联记录'})
                    reason=links.get('classification_reason') if role=='part_class' else '没有精确关联记录'
                    record_rows.append({'cells':[ROLE_LABELS[role],'未提供','未提供','未提供','未提供',reason+'；不能用上级或编码前缀代替']})
            if subject.get('tree')=='config':
                record_rows.append({'cells':['原字段',subject['code'],'所属部件类编码',subject['class_code'] or '未提供','','原构型记录字段，空值不能解释为没有类别']})
            if q['properties']:
                vals={p:graph.value(subject,p) or '未提供' for p in q['properties']}
                projected.append({'code':subject['code'],'name':subject['name'],'values':vals,'line':graph.store.ref(subject)['line']})
                for p,v in vals.items():record_rows.append({'cells':['原字段',subject['code'],CATALOG.get(p,{}).get('label',{'line':'原CSV行号','pbs_part':'现场部件编码','location':'功能位置编码'}.get(p,p)),v,'','']})
        result.update(relation_facts=resolved,field_projection=projected,missing_links=missing)
        if missing:result['note']+='部分关联资料不足；已知原对象仍保留。'
        result['answer']='已分别列出原对象与实际关联记录。'+('缺失关系写未提供，不能据此认定对象不存在或没有类别。' if missing else '设备类取实际设备构型父编码；部件类取精确部件构型分类引用。')
        if q['boundary']=='same_record':result['answer']+='同码位于不同表，属于不同记录，不能合并。'
    else:
        rows=graph.population(q,root);full_total=len(rows);distinct=len({r['code'] for r in rows})
        class_groups=Counter();unresolved=[]
        if q['population']=='parts':
            for row in rows:
                link=graph.links(row);c=link['part_class']
                if c:class_groups[(c['code'],c['name'])]+=1
                else:unresolved.append({'code':row['code'],'name':row['name'],'reason':link['classification_reason'],'source':graph.store.ref(row)})
        result['population_facts']={'record_count':full_total,'distinct_code_count':distinct,'part_total':full_total if q['population']=='parts' else None,
            'resolved_part_total':full_total-len(unresolved) if q['population']=='parts' else None,'distinct_resolved_classes':len(class_groups),'unresolved_parts':unresolved}
        result['classification_coverage']={'complete':not unresolved,'total':full_total,'resolved':full_total-len(unresolved),'unresolved':len(unresolved)} if q['population']=='parts' else None
        result['metrics']=[{'label':'原记录/对象数量','value':full_total},{'label':'不同完整编码数','value':distinct}]
        if q['population']=='parts':result['metrics'] += [{'label':'已匹配部件','value':full_total-len(unresolved)},{'label':'不同部件类','value':len(class_groups)},{'label':'未完成分类部件','value':len(unresolved)}]
        if q['kind']=='compare':
            if not root or isinstance(root,list) or root['tree']!='pbs' or q['population']!='parts':raise QueryError('关联核对需要实际PBS部件集合。')
            other=graph.resolve(q['compare_root'])
            if not other or isinstance(other,list) or other['tree']!='config':raise QueryError('核对缺少构型根。')
            config_parts=[r for r in graph.desc(other,'all') if r['level']=='部件'];allowed={r['code'] for r in graph.desc(other,'all')}
            comparisons=[];compatible=set()
            for r in rows:
                code=r['code'].split('&',1)[1] if '&' in r['code'] else '';c=graph.objects.get(('config',code))
                issues=[]
                if not c:issues.append('构型缺失')
                else:
                    if c['level']!=r['level']:issues.append('对象类型不一致')
                    if c['code'] not in allowed:issues.append('构型不在真实下级')
                    if not issues:compatible.add(c['code'])
                if issues:comparisons.append({'pbs':public_object(graph,r),'config':public_object(graph,c),'issues':issues})
            absent=[public_object(graph,r) for r in config_parts if r['code'] not in compatible]
            result['comparison']={'pbs_count':full_total,'config_count':len(config_parts),'issues':comparisons,'config_parts_without_type_compatible_pbs_instance':absent}
            result['columns']=['PBS编码','PBS类型','PBS父编码','构型编码','构型类型','构型父编码','问题']
            for item in comparisons:
                r=item['pbs'];c=item['config'] or {};record_rows.append({'cells':[r['code'],r['level'],r['parent'],c.get('code','未提供'),c.get('level','未提供'),c.get('parent','未提供'),'；'.join(item['issues'])]});evidence.append(r['source'])
                if c:evidence.append(c['source'])
            result['answer']=f'现场部件 {full_total} 个；构型部件 {len(config_parts)} 个。逐条核对发现 {len(comparisons)} 个现场对象有关联问题；{len(absent)} 个构型部件没有类型兼容的现场实例。'
            if absent:result['answer']+='反向核对未对应构型：'+'、'.join(r['code'] for r in absent)+'。'
        elif q['group_by']:
            groups=[]
            if q['group_by']=='class':groups=[{'code':c,'name':n,'count':v} for (c,n),v in class_groups.items()]
            else:
                buckets=defaultdict(list)
                for r in rows:
                    link=graph.links(r)
                    key=r.get('level','未提供') if q['group_by']=='type' else r['system'] if q['group_by']=='source' else link['location']['code'] if link['location'] else '未匹配'
                    buckets[key].append(r)
                groups=[{'code':k,'name':k,'count':len(v),'distinct_code_count':len({r['code'] for r in v})} for k,v in buckets.items()]
            groups.sort(key=lambda g:(-g['count'],g['code']))
            shown=groups[:q['limit']] if q['limit'] else groups
            result.update(groups=groups,shown_groups=shown,full_group_count=len(groups),display_subtotal=sum(g['count'] for g in shown))
            result['aggregation']=True
            result['chart']={'kind':'bars','items':[{'label':g['name']+' ('+g['code']+')','value':g['count']} for g in shown],'total_groups':len(groups)}
            result['columns']=['描述','分组编码','原记录/对象数','不同完整编码数']
            record_rows.extend({'cells':[g['name'],g['code'],g['count'],g.get('distinct_code_count','不适用')]} for g in shown)
            if q['group_by']=='class':
                result['columns'].append('关联说明')
                for row in record_rows:row['cells'].append('')
            for u in unresolved:record_rows.append({'cells':[u['name'],u['code'],1,1,u['reason']]})
            result['answer']=f'完整范围共 {full_total} 条/个，{distinct} 个不同完整编码；共 {len(groups)} 组，当前展示 {len(shown)} 组，展示小计 {sum(g["count"] for g in shown)}。'
            # 来源分组仍交付所有原监测行，不能只有分组汇总。
            if q['group_by']=='source':
                result['columns']=['源系统/原记录','描述/完整编码','记录数/原行号','不同编码数/名称','来源']
                for row in record_rows:row['cells'].append('')
                for r in rows:record_rows.append({'cells':['原记录',r['code'],graph.store.ref(r)['line'],r['name'],r['system']]})
        else:
            props=list(dict.fromkeys(['code','name']+(['source','line','status'] if q['population']=='points' else [])+q['properties']))
            ordered=graph.sort_rows(rows,q['sort']) if q['sort'] else rows
            shown=ordered[:q['limit']] if q['limit'] else ordered
            result['columns']=[CATALOG.get(p,{}).get('label',{'line':'原CSV行号','pbs_part':'现场部件编码','location':'功能位置编码'}.get(p,p)) for p in props]+(['关联说明'] if q['only']=='missing_class' else [])
            for r in shown:
                business={k:r.get(k) for k in ('tree','code','name','parent','level')}
                business['evidence']=graph.store.ref(r)
                if r['tree']=='points':business.update(source=r['system'],value=r['value'] or '未提供',unit=r['unit'] or '未提供',state=r['status'] or '未提供',switch=r['switch'] or '未提供',time=r['time'] or '未提供')
                record_rows.append({**business,'cells':[graph.value(r,p) or '未提供' for p in props]+([graph.links(r)['classification_reason']] if q['only']=='missing_class' else [])})
            result['answer']=f'完整范围共 {full_total} 条/个，{distinct} 个不同完整编码；列出 {len(shown)} 条。'
        result['record_facts']=[{'code':r['code'],'name':r['name'],'line':graph.store.ref(r)['line'],'values':{p:graph.value(r,p) or '未提供' for p in dict.fromkeys(['source','status','switch','pbs_part','location']+q['properties'])}} for r in rows]
        if q['population']=='points' and not q['group_by'] and q['kind']!='boundary':
            result['columns']+=['精确PBS对象','所属设备类','最近现场部件','最近功能位置']
            ordered=graph.sort_rows(rows,q['sort'])
            shown=ordered[:q['limit']] if q['limit'] else ordered
            # 与已有记录逐行保持同序；关联列来自真实边，缺失明确标注。
            for visible,row in zip(record_rows,shown):
                link=graph.links(row);eq=link['equipment_class']
                visible['cells'] += [link['pbs']['code'] if link['pbs'] else '未匹配',eq['code']+' / '+eq['name'] if eq else '未提供',graph.value(row,'pbs_part'),graph.value(row,'location')]
            result['note']+='未匹配表示没有精确PBS或真实父关系，不能凭编码前缀补归属；当前报警快照不能证明全部部件健康。'
        for r in rows:evidence.append(graph.store.ref(r))
        if unresolved:
            result['note']+='完整分类未完成：缺失对象仍计入总数并单列；已匹配分布仅代表其中有依据的部分。'
            result['answer']+=f'其中 {len(unresolved)} 个部件分类关联资料不足，完整分类统计未完成。'
            if q['group_by']=='class':result['outcome']={'kind':'incomplete','subject':q['root'],'count_computed':True,'classification_complete':False}
        if q['kind']=='boundary':
            if q['boundary']=='duration':
                result.update(status='data_insufficient',answer='当前表没有报警开始时间、恢复时间及完整历史事件，无法计算最近一个月累计报警时长。当前报警为零也不能作为历史时长零。',records=[],metrics=[])
            elif q['boundary']=='health':
                alarms=[r for r in rows if r['switch']=='开启' and r['status']=='已报警']
                result['metrics'] += [{'label':'开启且已报警原记录数','value':len(alarms)},{'label':'开启且已报警不同完整编码数','value':len({r['code'] for r in alarms})}]
                result['answer']+=f'当前开启且已报警 {len(alarms)} 条，完整监测范围 {full_total} 条、{distinct} 个不同完整编码。当前监测与报警快照不能证明全部部件健康；监测覆盖、历史状态和完整诊断依据不足。'
                result['health_snapshot']={'monitored_records':full_total,'monitored_codes':distinct,'active_alarm_records':len(alarms),'healthy_proven':False}
            elif q['boundary']=='classification':result['answer']+='不能据此认定没有类别，也不能用上级类别替代；缺少的是该部件自身的构型或分类依据。'
    anchors={k:[{'tree':r['tree'],'code':r['code'],'name':r['name']} for r in vals if r] for k,vals in resolved.items()}
    result['relational_resolved']=anchors
    return result


def legacy_context(item,state,spec):
    """把测点身份存为精确测点查询，避免写入仅支持对象树的旧entity槽位。"""
    c={'entity':item['entity'],'scope':item['scope'],'operation':'relational','relational_state':state}
    root=spec.get('root')
    if root and root['tree']=='points':
        field=root['field'];c.update(entity=None,scope='direct',query={'target':'points','filters':[
            {'field':field,'operator':'equals','value':root['value']}]+copy.deepcopy(spec['filters'])})
    return c


def execute(store,plan):
    graph=Graph(store);items=[];tasks=plan['relational_tasks']
    for t in tasks:
        item=execute_task(graph,t['spec']);item['task_number']=t['id'];item['task_question']='任务 '+str(t['id']);items.append(item)
    state={'tasks':[{'id':t['id'],'spec':copy.deepcopy(t['spec']),'resolved':item['relational_resolved']} for t,item in zip(tasks,items)]}
    result=items[0] if len(items)==1 else {'status':'batch','answer':'已分别交付 '+str(len(items))+' 个独立任务。','records':[],'metrics':[],'evidence':[],'path':[],'entity':None,'scope':'direct','note':'','items':items}
    for item,t in zip(items,tasks):item['task_context']=legacy_context(item,state,t['spec'])
    result['relational_state']=state
    if len(tasks)==1 and items[0]['task_context'].get('query'):result['query']=copy.deepcopy(items[0]['task_context']['query'])
    result['query_receipt']={'operation':'relational','grain':'per_task','tasks':copy.deepcopy(tasks),'completed':all(i['status']=='ok' and not i.get('outcome') and not i.get('missing_links') for i in items)}
    if len(tasks)==1 and tasks[0]['spec']['kind']=='collection':
        q=tasks[0]['spec'];root=q['root'];target='points' if q['population']=='points' else 'parts' if q['population']=='parts' and root and root['tree']=='config' else root['tree'] if root else 'pbs'
        filters=copy.deepcopy(q['filters'])
        if root and root['tree']=='points':filters.insert(0,{'field':root['field'],'operator':'equals','value':root['value']})
        result['query_receipt'].update(operation='search',requested_entity=result['entity'],resolved_entity=result['entity'],scope=q['depth'],query={'target':target,'filters':filters},grain='measurement_record' if target=='points' else 'pbs_object' if root and root['tree']=='pbs' else 'config_object')
        result['query']={'target':target,'filters':filters}
    return result
