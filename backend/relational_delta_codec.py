"""模型变更接入：仅兼容可证明等价的表示，业务状态仍由严格编译器维护。"""
import copy,re
from attributes import CATALOG
from relational_state import previous_tasks,condition_id,SET_FIELDS

def identity(store,root):
    if store is None or not root:return set()
    tree=root.get('tree');field=root.get('field');value=root.get('value')
    if field not in ('code','name','identity'):return set()
    table='points' if tree=='points' else 'objects';clause='(code=? OR name=?)' if field=='identity' else field+'=?';args=[value,value] if field=='identity' else [value]
    if table=='objects':clause='tree=? AND '+clause;args=[tree]+args
    return {(tree,row['code'],row.get('line') if table=='points' else None) for row in store.rows('SELECT code'+(',line' if table=='points' else '')+' FROM '+table+' WHERE '+clause,args)}

def control_text(text):
    return re.sub(r'(?:名字(?:叫|为)|名称(?:为|是)|名为|编码(?:为|是))[^，。；：:]*','',re.sub(r'“[^”]*”|「[^」]*」|『[^』]*』|\"[^\"]*\"|`[^`]*`','',text))

def explicit_removals(text,old):
    """有限撤销操作只定位已存在条件，不能因字段相同删除整个范围。"""
    result=[]
    aliases={'source':('源系统','来源'),'switch':('开关','开启','关闭'),'status':('报警状态','已报警','未报警')}
    operator_words={'gt':('大于','超过'), 'gte':('大于等于','不小于'),'lt':('小于','低于'),'lte':('小于等于','不大于')}
    for match in re.finditer(r'(?:撤掉|撤销|取消|去掉|解除|不再限定)([^，。；;！？!?]*)',text):
        body=match.group(1)
        stop=re.search(r'再限定|增加|加上|追加|改为|改成|换成|然后|并再',body)
        if stop:body=body[:stop.start()]
        source=match.group(0)[:len(match.group(0))-len(match.group(1))+len(body)]
        if re.search(r'分组|汇总|统计|排序|展示|排名',body) and not re.search(r'条件|筛选|过滤|范围限制',body):continue
        for f in old:
            field=f['field'];words=aliases.get(field,tuple([CATALOG[field]['label']]) if field in CATALOG else (field,))
            if not any(w in body for w in words):
                # 只有一个数值字段时，可用明确的旧运算符和精确端点定位省略字段名的撤销。
                from typed_fields import NUMERIC_FIELDS
                numeric_fields={x['field'] for x in old if x['field'] in NUMERIC_FIELDS}
                matches=[]
                if field in NUMERIC_FIELDS and numeric_fields=={field}:
                    for word in operator_words.get(f['operator'],()):
                        for token in re.findall(re.escape(word)+r'\s*([+-]?[0-9]+(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?)',body):
                            if condition_id({**f,'value':token})==condition_id(f):matches.append(token)
                if not matches:continue
            same=[x for x in old if x['field']==field]
            if len(same)>1:
                val=str(f['value']);op=f['operator'];markers=operator_words.get(op,())
                if not markers or not any(w+val in body.replace(' ','') for w in markers):continue
                if op=='gt' and '大于等于' in body or op=='lt' and '小于等于' in body:continue
            result.append({'action':'remove','selector':{'id':condition_id(f)},'quote':source})
    return result

def class_removal_sources(text,old,replaced_device_collection=False):
    """类别撤销必须指向实际旧类别；统计/分组转换不等于删除条件。"""
    aliases={'equipment_class':('设备类','设备类别'),'part_class':('部件类','部件类别')};found={}
    if replaced_device_collection and 'equipment_class' in old:
        class_term=r'设备类|设备类别'+(r'|这个类|该类|原类' if len(old)==1 else '')
        m=re.search(r'不再(?:统计|查询|查|取|选取|提取|读取)[^，。；;]{0,12}(?:'+class_term+r')[^，。；;]{0,12}(?:所有|全部|全表)设备',text)
        if m:found['equipment_class']=m.group(0)
    for m in re.finditer(r'(?:撤掉|撤销|取消|去掉|解除|不再限定)([^，。；;！？!?]*)',text):
        body=m.group(1);stop=re.search(r'再限定|增加|加上|追加|改为|改成|换成|然后|并再',body)
        if stop:body=body[:stop.start()]
        if re.search(r'分组|汇总|统计|排序|展示|排名',body) and not re.search(r'条件|筛选|过滤|范围限制|限定|限制',body):continue
        source=m.group(0)[:len(m.group(0))-len(m.group(1))+len(body)]
        targets=[t for t in old if any(w in body for w in aliases.get(t,()))]
        if not targets and re.search(r'(?:分类|类别)(?:条件|筛选|限定|限制)',body):
            if len(old)==1 or re.search(r'所有|全部',body):targets=list(old)
        for t in targets:found[t]=source
    return found

def normalize_delta(raw,question,context,store=None):
    """省略空操作=不变；未声明的新值、未知键、冲突写法仍拒绝。"""
    value=copy.deepcopy(raw);audit=[]
    if isinstance(value,dict) and value=={'version':2,'handled':False}:
        return {'handled':False},['false接口版本标识不携带任何业务槽位']
    if not isinstance(value,dict) or value.get('version')!=2 or value.get('handled') is not True:return value,audit
    if not isinstance(value.get('tasks'),list):return value,audit
    old=previous_tasks(context)
    independent_association=False
    controls=control_text(question)
    if value.get('mode') in ('new','update') and re.search(r'所属.*(?:究竟|应该).*(?:还是|或)',controls) and not re.search(r'分别|各自|第[一二三四1-4](?:项|个)|保持|保留|另查|另外|再查|同时|并查|只修改|仅修改',controls):
        from relational_state import reference,exact_literal
        subject=question.split('所属',1)[0]
        def actual_root(p):
            if not isinstance(p,dict) or type(p.get('id')) is not int:return None
            ref=p.get('root')
            if ref is None:return copy.deepcopy((old.get(p.get('id')) or {}).get('spec',{}).get('root'))
            try:return reference(ref,question,context,store)
            except ValueError:return None
        roots={id(p):actual_root(p) for p in value['tasks']}
        primary=[]
        for p in value['tasks']:
            if not isinstance(p,dict) or type(p.get('id')) is not int or not 1<=p['id']<=4 or p.get('action') not in ('new','update') or not isinstance(p.get('set'),dict) or p['set'].get('kind')!='relation':continue
            root=roots[id(p)]
            if not root or root.get('tree') not in ('pbs','config'):continue
            try:
                proven=exact_literal(root['tree'],root['field'],root['value'],subject,question,context,store)
            except ValueError:continue
            if store is not None and not identity(store,proven):continue
            primary.append((p,proven))
        if not primary and re.search(r'PBS|构型|模板|现场设备|功能位置',subject,re.I):
            from request_checklist import literal_references
            explicit=bool(literal_references(subject,store)) or bool(re.search(r'(?:PBS|构型|模板|现场设备|功能位置)(?:编码)?\s*[:：]?\s*[A-Za-z0-9_&.#-]+',subject,re.I))
            if explicit:
                from relational_state import RelationalHandoff
                raise RelationalHandoff('当前完整归属主体未与实际原表身份一致，不能用旧根或后面的类别候选补充主体。')
        if len(primary)==1:
            selected,root=primary[0]
            def unused_choice(p):
                if not isinstance(p,dict) or p.get('filters') or p.get('classes'):return False
                if p is selected or p.get('action')=='retain':return True
                return isinstance(p.get('set'),dict) and p['set'].get('kind')=='relation' and (roots[id(p)] or {}).get('tree')=='equipment_class'
            if all(unused_choice(p) for p in value['tasks']):
                # 角色、省略重复根与字面根都须先证明当前完整主体；不能用旧值猜新对象。
                selected.update(id=1,action='new',quote=question,root={'type':'literal',**root,'quote':subject})
                value['mode']='new';value['tasks']=[selected];independent_association=True
                audit.append('当前完整主体经原表核验后建立一项新归属任务；角色/省略/字面表示一致，不带入未要求的旧核对分支')
    if old:
        from relational_planner import retain_unchanged_tasks
        _,control=retain_unchanged_tasks({'handled':True,'tasks':[{'id':t['id'],'spec':copy.deepcopy(t['spec'])} for t in old.values()]},question,context)
        protected=set(control.get('retained_ids',[]))
        if protected:
            value['mode']='update'
            # 用原列表身份构造受保护分支；候选字段不参与解析、绑定或执行。
            patches=raw['tasks'];value['tasks']=[{'id':p['id'],'action':'retain'} if isinstance(p,dict) and type(p.get('id')) is int and p['id'] in protected else copy.deepcopy(p) for p in patches]
            for p in value['tasks']:
                if isinstance(p,dict) and p.get('action')=='new':p['action']='update'
            audit.append('明确保持/仅修改规则先于候选字段校验；未授权分支直接保持实际旧任务')
    def check_ref(ref):
        if not isinstance(ref,dict):raise ValueError('身份引用必须是对象。')
        shapes={'literal':({'type','tree','field','value','quote'},set()),'role':({'type','task','role','quote'},{'history'}),'class':({'type','task','tree','quote'},{'history'}),'global':({'type','quote'},set())}
        if ref.get('type') not in shapes:raise ValueError('身份引用类型不在登记契约。')
        required,optional=shapes[ref['type']]
        if not required<=set(ref) or set(ref)-(required|optional):raise ValueError('身份引用结构不完整或含未登记字段。')
        if not isinstance(ref['quote'],str) or not ref['quote'] or ref['quote'] not in question:raise ValueError('身份引用没有当前原话来源。')
    # 一个字典/构型原对象及其直接父记录已经由同一relation回执交付。
    # 只合并这种可查表证明的重复拆项，不把新任务草稿升级为执行历史。
    if value.get('mode')=='new' and len(value['tasks'])==2 and store is not None and not re.search(r'第[一二三四1-4](?:项|个任务)|两项|两件|分成|分别(?:查|查询)',controls):
        first,second=value['tasks']
        allowed={'id','action','quote','set','root','filters','classes'}
        base_fields={'code','name','parent','type','level'}
        def plain_relation(item):
            if not isinstance(item,dict) or set(item)-allowed or item.get('action')!='new' or type(item.get('id')) is not int:return False
            fields=item.get('set',{})
            return (isinstance(fields,dict) and not set(fields)-{'kind','population','depth','group_by','properties','limit','sort','only','boundary'} and fields.get('kind')=='relation' and fields.get('population','objects')=='objects' and fields.get('depth','self') in ('self','all') and not any(fields.get(k) for k in ('group_by','limit','sort','only','boundary')) and isinstance(fields.get('properties',[]),list) and all(isinstance(p,str) for p in fields.get('properties',[])) and not set(fields.get('properties',[]))-base_fields and item.get('filters',[])==[] and item.get('classes',[])==[] and isinstance(item.get('quote'),str) and item['quote'] in question)
        if plain_relation(first) and plain_relation(second):
            root=first.get('root',{});parent=second.get('root',{})
            if isinstance(root,dict) and isinstance(parent,dict) and root.get('type')=='literal' and root.get('tree') in ('equipment_class','part_class','config') and parent.get('type')=='role' and parent.get('task')==first.get('id') and parent.get('role')=='parent' and 'history' not in parent and re.search(r'直接父|父记录|父对象',second['quote']):
                check_ref(root);check_ref(parent)
                from relational_state import reference
                actual=reference(root,question,{},store)
                clause=actual['field']+'=?' if actual['field'] in ('code','name') else '(code=? OR name=?)'
                params=[actual['tree'],actual['value']]+([actual['value']] if actual['field']=='identity' else [])
                records=store.rows('SELECT code,parent FROM objects WHERE tree=? AND '+clause,params)
                if len(records)==1 and records[0]['parent'] and store.rows('SELECT code FROM objects WHERE tree=? AND code=?',[actual['tree'],records[0]['parent']]):
                    first['quote']=question
                    first['set']['properties']=sorted(set(first['set'].get('properties',[])+second['set'].get('properties',[])))
                    value['tasks']=[first];audit.append('实际同树原对象和直接父记录由同一关系回执交付；重复拆项合并，不建立未执行角色历史')
    for item in value['tasks']:
        if not isinstance(item,dict):continue
        before=(old.get(item.get('id')) or {}).get('spec',{})
        fields=item.get('set',{});ref=item.get('root')
        task_quote=item.get('quote','')
        # 明确反查全表现场实例时，分类节点是类别锚而不是构型子树范围。
        # 仅当前类别来源、真实分类节点及同码字典身份三者均证明时归一；
        # 有真实PBS根、不同类别或设备构型根则保持原声明并继续严格核验。
        class_edits=item.get('classes',[])
        if value.get('mode')=='new' and store is not None and isinstance(fields,dict) and fields.get('population') in ('devices','parts','points') and isinstance(ref,dict) and ref.get('type')=='literal' and ref.get('tree')=='config' and ref.get('field')=='code' and isinstance(task_quote,str) and task_quote in question and re.search(r'(?:反查|筛选|查找|查询|查出|找出|读取)[^，。；;]{0,16}(?:全部|所有|全表|整个)(?:PBS|现场)',task_quote) and isinstance(class_edits,list) and len(class_edits)==1:
            edit=class_edits[0]
            if isinstance(edit,dict) and set(edit)=={'action','tree','reference'} and edit.get('action')=='set' and edit.get('tree')=='equipment_class' and isinstance(edit.get('reference'),dict) and edit['reference'].get('type')=='literal':
                check_ref(ref);check_ref(edit['reference'])
                from relational_state import reference
                from request_checklist import literal_references
                actual=reference(edit['reference'],question,{},store)
                structural=store.rows('SELECT level FROM objects WHERE tree=? AND code=?',['config',ref['value']])
                def physical_pbs_anchor(hit):
                    if hit.get('domain')!='pbs':return False
                    name=hit.get('value','')
                    if hit.get('field')!='name' or name not in {'设备','部件','测点','对象','功能位置','构型','模板','分类'}:return True
                    return any(token in task_quote for token in ('“'+name+'”','"'+name+'"','名称为'+name,'名为'+name))
                if len(structural)==1 and structural[0]['level'] in ('类组','大类','中类','小类','设备类') and identity(store,actual)=={('equipment_class',ref['value'],None)} and ref['value'] in ref['quote'] and not any(physical_pbs_anchor(x) for x in literal_references(task_quote,store)):
                    item['root']=ref=copy.deepcopy(edit['reference']);audit.append('明确全表现场反查以当前实际字典类别为锚；真实同码构型分类节点不作为现场子树根，原类别条件保持')
        if value.get('mode')=='new' and len(value['tasks'])>1 and isinstance(task_quote,str) and task_quote in question and re.search(r'同一(?:台|个)?(?:PBS|现场|构型)?(?:设备|对象|根)',task_quote):
            for target in (item,item.get('set',{})):
                if not isinstance(target,dict):continue
                shared=target.get('root')
                if not isinstance(shared,dict) or shared.get('type')!='literal' or isinstance(shared.get('quote'),str) and shared['quote']in question:continue
                sig={k:shared.get(k) for k in ('tree','field','value')};anchors=[]
                for other in value['tasks']:
                    if other is item or not isinstance(other,dict):continue
                    anchor=other.get('root',(other.get('set')or{}).get('root'))
                    if isinstance(anchor,dict) and anchor.get('type')=='literal' and {k:anchor.get(k)for k in sig}==sig and isinstance(anchor.get('quote'),str) and anchor['quote']in question and isinstance(sig['value'],str) and sig['value']in anchor['quote']:
                        from relational_state import exact_literal
                        exact_literal(sig['tree'],sig['field'],sig['value'],anchor['quote'],question,context,store);anchors.append(anchor['quote'])
                if len(set(anchors))==1:
                    shared['quote']=anchors[0];audit.append('同一消息明确共享主体，两任务使用同一真实完整根引文，不拼接代词与编码或借未执行结果')
        plain_relation=value.get('mode')=='new' and isinstance(fields,dict) and fields.get('kind')=='relation' and not item.get('filters') and not item.get('classes') and isinstance(ref,dict) and ref.get('type')=='literal'
        if plain_relation and isinstance(ref.get('value'),str) and ref['value'] in question:
            if not isinstance(item.get('quote'),str) or item['quote'] not in question:
                item['quote']=question;audit.append('独立精确原表关系任务使用真实完整本句来源；不接受模型拼接后的引文')
            if isinstance(ref.get('quote'),str) and ref['quote'] not in question and item.get('quote') in question:
                ref['quote']=item['quote'];audit.append('共享句中的同码原表引用回到当前真实句，不拼接词造引文')
        for source in (item,item.get('set',{})):
            if isinstance(source,dict):
                for key in ('root','compare_root'):
                    if key=='compare_root' and key in source and source[key] is None and (value.get('mode')=='new' or before.get(key) is None):
                        source.pop(key);audit.append('空的非比较副根就是省略字段，不清除实际旧比较对象');continue
                    ref=source.get(key)
                    if value.get('mode')=='update' and isinstance(ref,dict) and set(ref)=={'type','tree','field','value','quote'} and ref.get('type')=='literal':
                        signature={k:ref[k] for k in ('tree','field','value')}
                        if signature==before.get(key) and (not isinstance(ref.get('quote'),str) or ref['quote'] not in question):
                            source.pop(key);audit.append('原根完全未变，去掉模型重抄的历史引文；不把旧引文作为本轮改根证据');continue
                    if key in source:
                        ref=source[key];task_quote=item.get('quote')
                        if isinstance(ref,dict) and ref.get('type') in ('role','class') and 'quote' not in ref and isinstance(task_quote,str) and task_quote in question and re.search(r'前[一二两三四五六1-6]轮|第[一二三四五六1-6](?:轮|问)|刚才|之前|上(?:轮|一轮)|最开始|首(?:轮|问)',task_quote):
                            ref['quote']=task_quote;audit.append('同一历史引用动作使用已给出的真实任务引文，实际历史角色仍由程序核验')
                        check_ref(ref)
                edits=source.get('classes',[])
                if isinstance(edits,dict) and 'action' in edits:edits=[edits]
                if isinstance(edits,list):
                    for edit in edits:
                        if isinstance(edit,dict) and 'reference' in edit:
                            ref=edit['reference'];tree=edit.get('tree')
                            if isinstance(ref,dict) and ref.get('type')=='class' and tree in ('equipment_class','part_class'):
                                if 'tree' not in ref:
                                    ref['tree']=tree;audit.append('同一类别动作的已登记外层树名补齐重复的class引用树名，不猜对象身份')
                                elif ref['tree']!=tree:raise ValueError('类别引用树与外层条件树冲突，不能选择任一覆盖。')
                            check_ref(ref)
    if value.get('mode')=='new' and len(value['tasks'])==1:
        p=value['tasks'][0]
        if isinstance(p,dict):
            fields=p.get('set',{});a=p.get('root',{});b=p.get('compare_root',{})
            if fields.get('kind')=='compare' and fields.get('population')=='objects' and a.get('type')==b.get('type')=='literal' and a.get('value')==b.get('value') and a.get('tree')!=b.get('tree') and re.search(r'同一条记录|分别查|各自|区别',p.get('quote','')):
                one=copy.deepcopy(p);two=copy.deepcopy(p)
                for n,item,root in ((1,one,a),(2,two,b)):
                    item['id']=n;item.pop('compare_root',None);item['root']=copy.deepcopy(root);item['set'].update(kind='relation',population='objects',boundary='same_record')
                value['tasks']=[one,two];audit.append('同码原表核对按两条原表relation交付，不改成PBS/构型部件比较')
    text=control_text(question)
    continues=re.search(r'刚才|上(?:一轮|条|轮)|这些|其中|同样|同一|这个(?:结果|范围)|该范围|保留|仍|继续',text)
    if old and re.fullmatch(r'\s*设备类(?:表|字典)?(?:呢)?[？?。]?\s*',question):continues=True
    restarts=re.search(r'另查|另外(?:查|查询)|另一个问题|新问题|另起|回到|返回|重新开始',text)
    fresh=re.search(r'另查|另外(?:查|查询)|另一个问题|开始新问题|另起|重新开始',text)
    if value.get('mode')=='update' and fresh and old:
        from relational_planner import retain_unchanged_tasks
        _,protected=retain_unchanged_tasks({'handled':True,'tasks':[{'id':t['id'],'spec':copy.deepcopy(t['spec'])} for t in old.values()]},question,context)
        if not protected and not any(isinstance(p,dict) and p.get('action')=='retain' for p in value['tasks']):
            value['mode']='new';audit.append('明确独立新问题由程序清除旧任务/条件，不沿用update默认历史')
            for p in value['tasks']:
                if isinstance(p,dict) and p.get('action')=='update':
                    p['action']='new';before=(old.get(p.get('id')) or {}).get('spec',{});root=before.get('root');qt=p.get('quote','')
                    if 'root' not in p and root and isinstance(qt,str) and root['value'] in qt:
                        p['root']={'type':'literal',**copy.deepcopy(root),'quote':qt};audit.append('新问题当前完整引用与实际旧根一致时，只补有当前来源的同一根，不继承旧条件')
    if value.get('mode')=='new' and old and continues and not restarts and not independent_association:
        value['mode']='update';audit.append('明确承接实际旧状态，new表示改为update，不能清空旧条件')
        for p in value.get('tasks',[]):
            if isinstance(p,dict) and p.get('action')=='new':p['action']='update'
    for p in value.get('tasks',[]):
        if not isinstance(p,dict) or p.get('action')=='retain':continue
        before=(old.get(p.get('id')) or {}).get('spec',{});fields=p.setdefault('set',{})
        if not isinstance(fields,dict):continue
        if value.get('mode')=='update' and re.fullmatch(r'\s*设备类(?:表|字典)?(?:呢)?[？?。]?\s*',question):
            records=(old.get(p.get('id')) or {}).get('resolved',{}).get('equipment_class',[])
            if len(records)==1 and records[0].get('tree')=='equipment_class':
                p['root']={'type':'role','task':p['id'],'role':'equipment_class','quote':question};p['classes']=[];fields.update(kind='relation',population='objects');audit.append('明确单一分类角色焦点来自实际执行记录，不清根或自由复制编码')
        for key in SET_FIELDS.intersection(p):
            if key in fields and fields[key]!=p[key]:raise ValueError('设置字段在动作层与set内重复且不一致。')
            fields[key]=p.pop(key);audit.append('同一登记设置字段移入set:'+key)
        for key in ('root','compare_root','filters','classes'):
            if key in fields:
                nested=fields.pop(key)
                if key in p and p[key] not in ([],{}) and p[key]!=nested:raise ValueError('变更字段在set内外重复且不一致。')
                p[key]=nested;audit.append('同一已登记字段移到动作层:'+key)
        for key in ('filters','classes'):
            if key not in p:p[key]=[];audit.append('省略空变更保持旧值:'+key)
            if p[key]=={}:p[key]=[];audit.append('空变更对象与空列表等价:'+key)
        if isinstance(p.get('classes'),dict) and p['classes'].get('action') in ('set','remove'):
            p['classes']=[p['classes']];audit.append('单个登记分类变更对象转为单项列表')
        if isinstance(p.get('classes'),dict):
            edits=[]
            for tree,literal in p['classes'].items():
                edits.append({'action':'set','tree':tree,'reference':{'type':'literal','tree':tree,'field':'identity','value':literal,'quote':p.get('quote')}})
            p['classes']=edits;audit.append('显式分类字典转有来源的set动作；未列旧分类仍保留')
        if value.get('mode')=='update' and isinstance(p.get('filters'),list):
            inferred=explicit_removals(p.get('quote','') if isinstance(p.get('quote'),str) else '',before.get('filters',[]))
            supported={x['selector']['id']:x['quote'] for x in inferred}
            if before.get('filters'):
                from relational_state import select_condition
                kept=[]
                for edit in p['filters']:
                    if isinstance(edit,dict) and edit.get('action')=='remove' and set(edit)=={'action','selector','quote'} and isinstance(edit['quote'],str) and edit['quote'] in question:
                        old_condition=select_condition(before['filters'],edit['selector']);cid=condition_id(old_condition)
                        display_only=re.search(r'分组|汇总|统计|排序|展示|排名',edit['quote']) and not re.search(r'条件|筛选|过滤|范围限制',edit['quote'])
                        if cid in supported:edit['quote']=supported[cid]
                        elif not display_only:
                            audit.append('本轮未声明撤销该原字段条件，忽略模型无依据remove:'+cid);continue
                    kept.append(edit)
                p['filters']=kept
            for edit in inferred:
                f=next(x for x in before['filters'] if condition_id(x)==edit['selector']['id'])
                def targets(x):
                    if not isinstance(x,dict) or x.get('action') not in ('remove','replace'):return False
                    from relational_state import select_condition
                    try:return condition_id(select_condition(before['filters'],x.get('selector',{})))==edit['selector']['id']
                    except ValueError:return False
                if not any(targets(x) for x in p['filters'] if isinstance(x,dict)):
                    p['filters'].append(edit);audit.append('当前明确撤销实际条件:'+edit['selector']['id'])
        for key in ('root','compare_root'):
            ref=p.get(key)
            if not isinstance(ref,dict):continue
            task_quote=p.get('quote')
            if ref.get('type')=='global' and isinstance(task_quote,str) and ref.get('quote') in task_quote and task_quote in question:
                ref['quote']=task_quote;audit.append('全表来源使用同一任务完整原话，不以孤立树名丢失各层级范围')
            if ref.get('type')=='global' and set(ref)=={'type','quote'} and value.get('mode')=='update' and before.get(key) is None:
                p.pop(key);audit.append('已是全表，去掉无效重复清根');continue
            if ref.get('type')=='role' and 'history' not in ref:
                qt=ref.get('quote','')
                ordinal=re.search(r'第([一二三四五六1-6])(?:轮|问)|首(?:轮|问)|最开始',qt) if isinstance(qt,str) else None
                if ordinal:
                    token=ordinal.group(1);index=('一二三四五六'.index(token) if token in '一二三四五六' else int(token)-1) if token else 0
                    if index<len(context.get('relational_history',[])):
                        ref['history']=index;audit.append('明确历史序号定位程序已执行目录')
            if ref.get('type')!='literal' or set(ref)!={'type','tree','field','value','quote'}:continue
            literal=ref.get('value','');qt=ref.get('quote','')
            if not isinstance(literal,str) or not isinstance(qt,str):continue
            task_quote=p.get('quote')
            if literal and isinstance(task_quote,str) and literal in task_quote and qt in task_quote and task_quote in question:
                ref['quote']=task_quote;qt=task_quote;audit.append('身份来源使用同一任务的完整原话，保留实际树限定')
            if literal and literal not in qt:
                ids=identity(store,ref)
                if value.get('mode')=='update' and ids and ids==identity(store,before.get(key)):
                    p.pop(key);audit.append('实际同一旧根按程序保持，不重抄标识');continue
                ordinal=re.search(r'第([一二三四五六1-6])(?:轮|问)|首(?:轮|问)|最开始',qt)
                if ordinal:
                    raw_number=ordinal.group(1);n=('一二三四五六'.index(raw_number)+1 if raw_number in '一二三四五六' else int(raw_number)) if raw_number else 1
                    hist=context.get('relational_history',[]);index=n-1
                    if index<len(hist):
                        candidates=[t for t in hist[index]['state'].get('tasks',[]) if ids and ids==identity(store,t['spec'].get(key))]
                        if len(candidates)==1:
                            p[key]={'type':'role','task':candidates[0]['id'],'history':index,'role':'root','quote':qt};audit.append('明确历史序号按真实根引用，不接受自由旧标识')
        if isinstance(p.get('classes'),list):
            edits=[]
            for edit in p['classes']:
                ref=edit.get('reference') if isinstance(edit,dict) else None
                tree=edit.get('tree') if isinstance(edit,dict) else None
                class_words={'equipment_class':'设备类','part_class':'部件类'}
                qt=p.get('quote','') if isinstance(p.get('quote'),str) else ''
                if value.get('mode')=='update' and isinstance(edit,dict) and edit.get('action')=='remove' and set(edit)=={'action','tree','quote'} and tree in before.get('classes',{}) and isinstance(edit['quote'],str) and edit['quote'] in question:
                    replaced=False
                    if before.get('population')=='devices' and before.get('root') is None and p.get('root') and re.search(r'不再(?:统计|查询|查|取|选取|提取|读取)',qt):
                        from relational_state import reference
                        proven=reference(p['root'],question,context,store)
                        ids=identity(store,proven)
                        if len(ids)==1:
                            actual_tree,actual_code,_=next(iter(ids))
                            rows=store.rows('SELECT tree,level FROM objects WHERE tree=? AND code=?',[actual_tree,actual_code])
                            replaced=len(rows)==1 and rows[0]['tree']=='pbs'
                    removals=class_removal_sources(qt,before['classes'],replaced)
                    if tree not in removals:
                        audit.append('没有本轮明确类别撤销来源，实际旧类别条件由程序保持:'+tree);continue
                    edit['quote']=removals[tree]
                if value.get('mode')=='update' and tree in before.get('classes',{}) and tree in class_words and re.search(r'(?:保留|保持|沿用)[^，。；;]{0,24}'+class_words[tree],qt) and not re.search(r'(?:改为|换为|改成|换成|撤掉|取消|解除)[^，。；;]{0,24}'+class_words[tree],qt):
                    audit.append('明确保持的实际分类条件直接由程序保留，不再解析模型重抄引用:'+tree);continue
                if isinstance(ref,dict) and ref.get('type')=='literal' and isinstance(ref.get('quote'),str) and isinstance(p.get('quote'),str) and ref['quote'] in p['quote'] and p['quote'] in question:
                    ref['quote']=p['quote'];audit.append('分类来源使用同一任务完整原话以保留树限定')
                if isinstance(ref,dict) and set(ref)=={'type','tree','field','value','quote'} and ref.get('type')=='literal' and isinstance(ref.get('value'),str) and isinstance(ref.get('quote'),str) and ref['value'] not in ref['quote']:
                    tree=edit.get('tree');literal=ref.get('value');known=before.get('classes',{}).get(tree)
                    if known and identity(store,ref)==identity(store,{'tree':tree,'field':'identity','value':known}):
                        audit.append('当前真实分类不变，省略重抄');continue
                    task=old.get(p.get('id')) or {};roles=task.get('resolved',{})
                    for role in ('subject',tree):
                        records=roles.get(role,[]);matches=[r for r in records if r.get('tree')==tree and r.get('code')==literal]
                        if len({r['code'] for r in matches})==1:
                            edit['reference']={'type':'role','task':p['id'],'role':role,'quote':ref['quote']};audit.append('当前唯一实际分类角色代替抄旧编码');break
                edits.append(edit)
            p['classes']=edits
        kind=fields.get('kind',before.get('kind'));pop=fields.get('population',before.get('population'))
        root=p.get('root',before.get('root'));root_tree=root.get('tree') if isinstance(root,dict) else None
        if fields.get('group_by')=='level' and pop!='points' and (root is None or root_tree=='pbs' or isinstance(root,dict) and root.get('type')=='global'):
            fields['group_by']='type';audit.append('PBS原层级与对象类型同一原字段；只在该原表归一level/type，不将构型数字层级当类型')
        qt=p.get('quote','') if isinstance(p.get('quote'),str) else ''
        if value.get('mode')=='new' and kind=='collection' and pop!='points' and not fields.get('group_by') and re.search(r'(?:列|给|展示|读取)[^，。；;]{0,30}父(?:对象)?(?:编码|代码)',qt) and not re.search(r'(?:不|不要|无需|不用|不必)[^，。；;]{0,6}(?:列|给|展示|读取)[^，。；;]{0,30}父(?:对象)?(?:编码|代码)',qt) and isinstance(fields.get('properties',[]),list):
            fields['properties']=sorted(set(fields.get('properties',[])+['parent']));audit.append('当前明确逐行父编码列由登记字段契约补全，保持实际集合和其他投影')
        # PBS的原层级就是对象类型；明确逐层计数时，不接受模型换成分类字典分组。
        pbs_type_group=bool(re.search(r'PBS(?:各|每个|所有|全部)(?:层级|类型)',qt) and re.search(r'统计|数量|计数|多少',qt))
        competing_group=bool(re.search(r'按[^，。；;]{0,12}(?:设备类|部件类|类别|分类|来源|源系统|功能位置)[^，。；;]{0,12}(?:统计|分组|汇总)',qt))
        pbs_scope=root is None or root_tree=='pbs' or isinstance(root,dict) and root.get('type')=='global'
        if kind=='collection' and pop=='objects' and pbs_scope and pbs_type_group and not competing_group:
            fields['group_by']='type';audit.append('当前明确PBS各层级/类型数量按原对象类型分组，不由模型改成分类字典或无分组')
        exclusive=re.search(r'只(?:查看|看|查|列|要)(?:刚才|其中|那些|这些|当前|所有|的|\s)*(?:未匹配|未关联|缺失|没有|无精确)',qt)
        if exclusive and not re.search(r'是否|能否|有没有',exclusive.group(0)):
            location_missing=re.search(r'(?:未匹配|未关联|缺失|没有|无精确)[^，。；;]{0,12}(?:功能位置|位置归属)|(?:功能位置|位置归属)[^，。；;]{0,12}(?:未匹配|未关联|缺失|未提供)',qt)
            class_missing=re.search(r'(?:未匹配|未关联|缺失|没有)[^，。；;]{0,12}(?:分类|部件类)|(?:分类|部件类)[^，。；;]{0,12}(?:未匹配|未关联|缺失|未提供)',qt)
            if bool(location_missing)!=bool(class_missing):
                fields['only']='unmatched' if location_missing else 'missing_class';audit.append('只选缺失记录的谓词由当前明确关联字段类型确定，不把位置缺失换成分类缺失')
        missing_group={'class':'missing_class','location':'unmatched'}.get(fields.get('group_by'))
        missing_words=r'缺失|未匹配|未关联|无法分类|未提供分类|缺少分类'
        full_groups=bool(missing_group and re.search(r'分组|分布|统计',qt) and re.search(r'(?:'+missing_words+r')[^，。；;]{0,12}(?:单列|另列|单独)',qt) and not re.search(r'(?:只看|只查|只取|仅看|仅查|仅取)[^，。；;]{0,12}(?:'+missing_words+r')',qt))
        includes_missing=re.search(r'(?:缺失|缺少|未匹配|未关联|无法分类)[^，。；;]{0,20}(?:也不能漏|也(?:保留|包含|计入|列出)|不能(?:漏掉|删除)|一并列出)',qt)
        explicit_missing_only=re.search(r'(?:只看|只查|只取|仅看|仅查|仅取)[^，。；;]{0,12}(?:'+missing_words+r')',qt)
        if includes_missing and not explicit_missing_only and fields.get('only') in ('missing_class','unmatched') and fields.get('only')!=before.get('only'):
            fields['only']=before.get('only');audit.append('缺失者也保留是完整范围交付要求，不授权新加只选缺失的筛选')
        if full_groups and fields.get('only')==missing_group:
            fields['only']=None;audit.append('完整分布中的缺失单列属于固定分组交付，不等于只筛缺失记录')
        if fields.get('only',before.get('only'))=='missing_class' and isinstance(fields.get('properties'),list):
            fields['properties']=[k for k in fields['properties'] if k not in ('missing_reason','classification_reason')];audit.append('缺失关联原因是登记的固定交付列，不作为客户原字段重复投影')
        if value.get('mode')=='update' and before.get('only') and fields.get('only','absent') is None and kind!='boundary':
            cancel=re.search(r'(?:撤掉|撤销|取消|解除|不再)[^，。；;]{0,40}(?:未匹配|未关联|缺失|只看)|恢复(?:完整|全部)(?:范围|集合|记录)',qt)
            if not cancel and not full_groups:
                fields.pop('only');audit.append('未声明撤销的记录范围由程序保持；空默认值不是撤销依据')
        if value.get('mode')=='update' and 'depth' in fields and fields.get('depth')==before.get('depth'):
            fields.pop('depth');audit.append('未改变实际深度，按程序继承而非重新要求范围声明')
        if kind=='compare' and re.search(r'两套|两表|两组|两(?:个|份)集合|前[二两2](?:轮|问|次)',qt):
            sources=[]
            histories=context.get('relational_history',[])
            for index,h in list(enumerate(histories))[-2:]:
                for task in h.get('state',{}).get('tasks',[]):
                    r=task.get('spec',{}).get('root')
                    if r and task['spec'].get('population')=='parts':sources.append((r,task['id'],index))
            for key,tree in (('root','pbs'),('compare_root','config')):
                ref=p.get(key);matches=[x for x in sources if x[0]['tree']==tree]
                unique={str(x[0]) for x in matches}
                if ref is None and len(unique)==1:
                    _,tid,index=matches[-1];p[key]={'type':'role','task':tid,'history':index,'role':'root','quote':qt};audit.append('原话明确两套已执行集合，缺省比较操作数按唯一实际原表根补全:'+tree)
                if isinstance(ref,dict) and ref.get('type') in ('role','literal') and isinstance(ref.get('quote'),str) and len(unique)==1:
                    _,tid,index=matches[-1];p[key]={'type':'role','task':tid,'history':index,'role':'root','quote':ref['quote']};audit.append('两套实际部件集合按compare登记的两种原表根独立定位:'+tree)
        if value.get('mode')=='update' and isinstance(p.get('root'),dict) and p['root'].get('role') in ('parent','pbs_parent') and re.search(r'沿.*父.*查.*(?:设备类|部件类|分类)',qt) and not re.search(r'改查.*父|父.*本身',qt):
            p.pop('root');audit.append('沿真实父边读取分类不改变查询主体；直接保留实际原根')
        if kind=='relation' and fields.get('boundary')=='same_record' and not re.search(r'同码|同一条记录|是否.*同一',qt):
            fields['boundary']=None;audit.append('普通关联读取不沿用同码原表核对说明')
        group=fields.get('group_by');group_words={'class':r'部件类|类别|分类','type':r'类型|层级','source':r'来源|源系统','location':r'功能位置|归属位置'}
        grouping=re.search(r'分组|分布|统计|汇总|分别.*多少|各.*数量',qt)
        view_change=re.search(r'明细|逐行|逐条|取消.*分组|不再.*分组|只列|仅列|列出.*(?:编码|名称)|具体.*哪些.*(?:部件|设备|原记录)|(?:原记录|原行|原文件行号|CSV行号).*(?:排序|升序|降序)|(?:编码|名称).*(?:排序|升序|降序)',qt)
        if group in group_words and not (grouping and (re.search(group_words[group],qt) or group==before.get('group_by') and re.search(r'原分组|分组.*(?:保持|不变)|保留.*分组',qt))):
            if value.get('mode')=='new' or view_change:fields['group_by']=None
            else:fields.pop('group_by')
            audit.append('当前未要求该字段分组，不添加额外分布；已有分组仅在明确明细目标时取消')
        if value.get('mode')=='update' and fields.get('group_by','absent') is None and before.get('group_by') and not (grouping or view_change) and not any(k in fields and fields[k]!='keep' and fields[k]!=before.get(k) for k in ('kind','population')):
            fields.pop('group_by');audit.append('没有视图变更依据的空分组不能清掉实际旧分组')
        reselects=any(k in fields and fields[k]!='keep' and fields[k]!=before.get(k) for k in ('kind','population','group_by'))
        if value.get('mode')=='update' and not reselects:
            if fields.get('properties')==[] and not re.search(r'列|字段|属性|输出|明细',qt):fields.pop('properties');audit.append('无本轮字段变更，不让空默认投影清掉旧字段')
            if fields.get('limit','absent') is None and before.get('limit') and not re.search(r'取消|撤销|不再|完整(?:分布|统计)|全部(?:分组|类别)|Top|TOP|前[0-9一二三四五六七八九十]+',qt):fields.pop('limit');audit.append('无本轮排名变更，不清旧展示限制')
            if fields.get('group_by','absent') is None and before.get('group_by') and not (grouping or view_change):fields.pop('group_by');audit.append('只改条件不能清除已有分组')
        if reselects and fields.get('properties')=='keep' and not re.search(r'字段|属性|这些列|原列|列不变|输出不变|输出保持|其余(?:均|都)?不变',qt):
            fields.pop('properties');audit.append('保留计数指标不等于保留旧字段投影；新视图按固定默认列')
        aggregates=re.search(r'(?<!取消)(?<!不要)分组|统计|分布|汇总|各.+数量',qt)
        row_order=re.search(r'逐行|原行|原记录|明细|CSV行号',qt) and re.search(r'排序|升序|排列',qt)
        if row_order and not aggregates and fields.get('group_by') not in (None,'keep'):
            fields['group_by']=None;audit.append('明确原行排序不产生分组目标')
        collective=bool(re.search(r'下级|后代|反查|范围|全表|直属|下一层|(?:全部|所有|全)层级|直接(?:部件|设备|对象|子)|全部(?:现场|部件|设备)|所有(?:现场|部件|设备)',qt))
        record_delivery=bool(re.search(r'原行|原记录|逐行|逐条|CSV行号|原文件行号|明细',qt))
        if kind=='relation' and pop=='points' and (record_delivery or collective or fields.get('group_by') or any(x.get('action') in ('add','replace') for x in p.get('filters',[]) if isinstance(x,dict)) or fields.get('limit')):
            fields['kind']='collection';kind='collection';audit.append('监测原行交付规范为collection')
        if kind=='relation' and (fields.get('group_by') not in (None,'keep') or pop in ('objects','parts','devices') and collective or root and root.get('type')=='global'):
            fields['kind']='collection';kind='collection';audit.append('集合目标/分组明确使用collection，深度仍保留')
        if kind=='relation':
            fields.pop('depth',None);audit.append('单对象关系不依赖集合深度')
            fields['population']='objects'
            if isinstance(fields.get('properties'),list):
                from relational_query import ROLES
                fixed=ROLES|({'source','line','status','pbs_part','location'} if root_tree=='points' else set())
                properties=[]
                for k in fields['properties']:
                    if not isinstance(k,str):raise ValueError('关系字段名必须是登记字符串，不能携带任意结构。')
                    # 关联卡片固定提供真实编码和名称；派生角色不是可自由查询的原字段。
                    base,suffix=k.rsplit('_',1) if isinstance(k,str) and '_' in k else (k,None)
                    if k not in CATALOG and base in ROLES and suffix in ('code','name'):
                        k=base;audit.append('登记关联角色的编码/名称由真实关系卡片交付:'+base)
                    if k not in fixed:properties.append(k)
                fields['properties']=properties
                audit.append('登记关联角色始终由关系视图交付，不重复当原字段投影')
        elif root_tree=='points' and 'depth' in fields:fields.pop('depth');audit.append('精确测点原行固定self由编译器确定')
        elif value.get('mode')=='new' and fields.get('depth')=='all':fields.pop('depth');audit.append('新集合默认完整深度无需重复来源词')
        gb=fields.get('group_by',before.get('group_by'))
        if gb=='keep':gb=before.get('group_by')
        if fields.get('sort')==['count'] and gb:
            if re.search(r'数量升序|由少到多|数量从小到大',qt):raise ValueError('当前分组能力只支持数量降序，不能将升序需求改写为默认排序。')
            fields['sort']=[];audit.append('分组数量降序属于固定分组规则')
        order=fields.get('sort')
        if isinstance(order,list) and all(k in ('code','name','source','line','pbs_part') for k in order) and not re.search(r'排序|升序|降序|排列|顺序|由小到大|由大到小|从小到大|从大到小',qt):
            fields.pop('sort');audit.append('未声明修改排序，旧行序继承/新视图使用登记默认，不接受额外行序变化')
    # 先将字面、角色和缺省序号统一到实际历史身份，再决定是否结束旧集合目标。
    if value.get('mode')=='update' and restarts and re.search(r'不(?:再|继续)查(?:询)?(?:实例|集合)',text) and len(value['tasks'])==1:
        p=value['tasks'][0];ref=p.get('root') if isinstance(p,dict) else None
        if isinstance(p,dict) and p.get('set',{}).get('kind')=='relation' and isinstance(ref,dict) and ref.get('type')=='role' and ref.get('role') in ('root','subject') and type(ref.get('history')) is int:
            from relational_state import reference
            from relational_planner import retain_unchanged_tasks
            proven=reference(ref,question,context,store)
            source_tasks={t['id']:t for t in context['relational_history'][ref['history']]['state']['tasks']}
            source_root=source_tasks[ref['task']]['spec'].get('root')
            if not identity(store,proven) or identity(store,proven)!=identity(store,source_root):
                raise ValueError('返回原记录必须与该实际历史根的完整原行身份一致，不能换成关联对象或扩大同码记录。')
            _,protected=retain_unchanged_tasks({'handled':True,'tasks':[{'id':t['id'],'spec':copy.deepcopy(t['spec'])} for t in old.values()]},question,context)
            if not protected and p.get('action')!='retain':
                value['mode']='new';p['action']='new';audit.append('明确结束实例集合并返回实际历史原记录，统一表示后清除旧实例分类/过滤，不推广未执行身份')
    return value,audit
