"""受限关系变更编译：实际旧状态属于程序，模型只声明本轮修改。"""
import copy
import hashlib
import json
import re
from relational_query import canonical,canonical_condition,validate_plan,TREES
from business_request import require_keys
from request_checklist import literal_references

OUTPUT={'kind','population','group_by','properties','limit','sort','only','boundary'}
SET_FIELDS=OUTPUT|{'depth','target_tree'}
DEFAULT_OUTPUT={'group_by':None,'properties':[],'limit':None,'sort':[],'only':None,'boundary':None}
TREE_HINTS={'pbs':('PBS','现场','功能位置'),'config':('构型','模板'),'equipment_class':('设备类',),'part_class':('部件类',),'points':('测点','监测','测量点','点位')}

class RelationalHandoff(ValueError):
    """不能安全定位主体时交既有澄清入口，不将两模型一致当作身份事实。"""

def quote(value,question):
    if not isinstance(value,str) or not value.strip() or value not in question:
        raise ValueError('关系变更来源必须是本轮完整原话片段。')
    return value

def previous_tasks(context):
    return {t['id']:t for t in (context.get('relational_state') or {}).get('tasks',[])}

def exact_literal(tree,field,value,text,question,context,store):
    if tree not in TREES or field not in ('code','name','identity') or not isinstance(value,str) or not value:
        raise ValueError('新关系主体必须使用登记树与完整标识。')
    from identifier_aliases import complete_literal_pattern
    mentioned=bool(re.search(complete_literal_pattern(value),text))
    if not mentioned:
        proven=False
        if store is not None:
            table='points' if tree=='points' else 'objects';clause='(code=? OR name=?)';params=[value,value]
            if table=='objects':clause='tree=? AND '+clause;params=[tree]+params
            rows=store.rows('SELECT code,name'+(',line' if table=='points' else '')+' FROM '+table+' WHERE '+clause,params)
            generic={'设备','部件','测点','对象','功能位置','构型','模板','分类'}
            def named(r):
                name=r['name'];explicit=name not in generic or any(w+name in text for w in ('“','"','名称为','名字叫','名为'))
                return explicit and bool(re.search(complete_literal_pattern(name),text))
            aliases=[r for r in rows if re.search(complete_literal_pattern(r['code']),text) or named(r)]
            if aliases and len({r['code'] for r in rows})==1:
                proven=table!='points' or {r['line'] for r in aliases}=={r['line'] for r in rows}
        if not proven:raise ValueError('新对象不在本轮主体原话中；不能沿用旧编码、扩大名称原行或按前缀补全。')
    if store is not None:
        refs=literal_references(text,store)
        hits=[x for x in refs if x.get('value')==value and (field=='identity' or x.get('field')==field)]
        domains={x['domain'] for x in hits}
        explicit_domains=set()
        # 目录链接按原表/字段/值去重；源码定位须检查全部完整出现位置，
        # 否则同码第二张表会被第一次出现的限定错误覆盖。
        code_mention=field=='code' or field=='identity' and any(h.get('field')=='code' for h in hits)
        for occurrence in re.finditer(complete_literal_pattern(value),text) if code_mention else []:
            start=occurrence.start();prefix=re.split(r'[，。；;！？!?]',text[max(0,start-32):start])[-1]
            markers=[(m.end(),t) for t,words in TREE_HINTS.items() for word in words for m in re.finditer(re.escape(word),prefix,re.I)]
            if markers:
                nearest=max(end for end,_ in markers)
                explicit_domains.update(t for end,t in markers if end==nearest)
        if explicit_domains and tree not in explicit_domains:raise ValueError('完整身份前的明确对象树限定不一致，不能借目标字段名改换原表。')
        if not domains and not mentioned:domains={tree}
        if domains and tree not in domains:raise ValueError('本轮标识没有所声明对象树的原记录。')
        if len(domains)>1:
            explicit=text.replace(value,'')
            focused=[t['spec'].get('root') for t in previous_tasks(context).values()]
            same_focus=any(r and r['tree']==tree and r['value']==value for r in focused)
            ordinal=re.search(r'第([一二三四五六1-6])(?:轮|问)|首(?:轮|问)|最开始',text)
            if ordinal:
                token=ordinal.group(1);index=('一二三四五六'.index(token) if token in '一二三四五六' else int(token)-1) if token else 0
                history=context.get('relational_history',[])
                if index<len(history):
                    actual_roots=[t['spec'].get('root') for t in history[index]['state'].get('tasks',[])]
                    same_focus=same_focus or any(r and r=={'tree':tree,'field':field,'value':value} for r in actual_roots)
            entity=context.get('entity') or {}
            same_focus=same_focus or entity.get('tree')==tree and entity.get(field)==value
            from relational_continuity import continued_collection_tree
            same_focus=same_focus or continued_collection_tree(question,context,store,value)==tree
            if not same_focus and not any(h.lower() in explicit.lower() for h in TREE_HINTS[tree]):
                raise RelationalHandoff('本轮新标识跨树命中，旧对象不能替它选择对象域。')
    return {'tree':tree,'field':field,'value':value}

def reference(ref,question,context,store):
    """角色只引用实际执行目录，不接受模型写入任意旧对象标识。"""
    if not isinstance(ref,dict):raise ValueError('关系身份引用必须为对象。')
    kind=ref.get('type');text=quote(ref.get('quote'),question)
    if kind=='literal':
        require_keys(ref,{'type','tree','field','value','quote'},'literal')
        return exact_literal(ref['tree'],ref['field'],ref['value'],text,question,context,store)
    if kind=='global':
        require_keys(ref,{'type','quote'},'global')
        if not re.search(r'全PBS|整个PBS|全表|全监测|全量|(?:全部|所有)(?:PBS|构型树)?(?:现场|设备|部件|监测|数据)|全局|PBS(?:各|所有|全部)(?:层级|类型)|(?:^|[，。；;\s]|查|查询|读取)(?:整个(?:PBS|构型|监测)(?:原)?表|监测原表)',text):
            raise ValueError('清除根范围必须有本轮全表目标依据。')
        return None
    if kind not in ('role','class'):raise ValueError('未知实际身份引用类型。')
    allowed={'type','task','role' if kind=='role' else 'tree','quote'}
    if 'history' in ref:allowed.add('history')
    require_keys(ref,allowed,kind)
    state=context.get('relational_state') or {}
    if 'history' in ref:
        history=context.get('relational_history',[]);n=ref['history']
        if type(n) is not int or not 0<=n<len(history):raise ValueError('实际执行历史编号不存在。')
        state=history[n]['state']
    tasks={t['id']:t for t in state.get('tasks',[])};tid=ref['task']
    if type(tid) is not int or tid not in tasks:raise ValueError('身份引用任务不存在。')
    task=tasks[tid]
    if kind=='class':
        tree=ref['tree'];value=task['spec'].get('classes',{}).get(tree)
        if tree not in ('equipment_class','part_class'):raise ValueError('分类引用树未登记。')
        if value:return {'tree':tree,'field':'identity','value':value}
        root=task['spec'].get('root') or {}
        def same_subject(r):
            return root.get('value') in (r.get('code'),r.get('name')) if root.get('field')=='identity' else root.get('value')==r.get(root.get('field'))
        subjects={(r['tree'],r['code']) for r in task.get('resolved',{}).get('subject',[]) if r.get('tree')==tree and r.get('code') and same_subject(r)}
        if root.get('tree')==tree and len(subjects)==1 and not re.search(r'父|上级|上一级',text):
            _,code=next(iter(subjects));return {'tree':tree,'field':'code','value':code}
        raise ValueError('该已执行任务没有所指分类条件或唯一同表字典主体。')
    role=ref['role']
    if role=='root':
        root=task['spec'].get('root')
        if not root:raise RelationalHandoff('所引用任务没有唯一根对象。')
        return copy.deepcopy(root)
    roles=task.get('resolved') or {}
    if role not in ('subject','parent','pbs','pbs_parent','pbs_part','pbs_device','config','equipment_config','equipment_class','part_class'):
        raise ValueError('关系角色未登记。')
    records=roles.get(role,[])
    identities={(x['tree'],x['code']) for x in records if x.get('tree') in TREES and x.get('code')}
    if len(identities)!=1:raise RelationalHandoff('实际关联角色缺失或不唯一，不能猜一个对象。')
    tree,value=next(iter(identities));return {'tree':tree,'field':'code','value':value}

def condition_id(condition):
    encoded=json.dumps(canonical_condition(condition),ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
    return 'f'+hashlib.sha256(encoded).hexdigest()[:16]

def condition_catalog(context):
    return {str(tid):[{'id':condition_id(f),'condition':copy.deepcopy(f)} for f in t['spec'].get('filters',[])] for tid,t in previous_tasks(context).items()}

def select_condition(filters,selector):
    if not isinstance(selector,dict) or not selector or set(selector)-{'id','field','operator','value'}:
        raise ValueError('旧条件选择器必须使用实际条件编号或登记字段/运算符/值。')
    selector=copy.deepcopy(selector)
    if 'field' in selector and 'value' in selector:
        selector['value']=canonical_condition({'field':selector['field'],'operator':selector.get('operator','eq_num'),'value':selector['value']})['value']
    matches=[f for f in filters if all((condition_id(f) if k=='id' else canonical_condition(f).get(k))==v for k,v in selector.items())]
    if len(matches)!=1:raise ValueError('撤销或替换必须唯一定位一条实际旧条件，不能删除同字段其他条件。')
    return matches[0]

def apply_filters(q,edits,question):
    if not isinstance(edits,list) or len(edits)>12:raise ValueError('关系条件变更必须为有界列表。')
    touched=set()
    for edit in edits:
        if not isinstance(edit,dict):raise ValueError('条件变更必须为对象。')
        action=edit.get('action');text=quote(edit.get('quote'),question)
        if action=='remove' and re.search(r'分组|汇总|统计|排序|展示|排名',text) and not re.search(r'条件|筛选|过滤|范围限制',text):
            raise ValueError('取消输出分组/排序不等于撤销筛选条件。')
        if action=='remove':
            require_keys(edit,{'action','selector','quote'},'remove filter');old=select_condition(q['filters'],edit['selector']);cid=condition_id(old)
            if cid in touched:raise ValueError('同一旧条件不能重复删除或替换。')
            q['filters'].remove(old);touched.add(cid)
        elif action in ('add','replace'):
            require_keys(edit,{'action','condition','quote'}|({'selector'} if action=='replace' else set()),action+' filter')
            f=edit['condition'];require_keys(f,{'field','operator','value'},'condition');field=f['field']
            if action=='replace':
                old=select_condition(q['filters'],edit['selector']);cid=condition_id(old)
                if cid in touched:raise ValueError('同一旧条件不能重复删除或替换。')
                if old['field']!=field:raise ValueError('替换只改变该条件的运算符/值；换字段须明确remove再add。')
                q['filters'].remove(old);touched.add(cid)
            if f not in q['filters']:q['filters'].append(copy.deepcopy(f))
        else:raise ValueError('条件只允许add/replace/remove，不允许重写完整列表。')

def apply_classes(q,edits,question,context,store):
    if not isinstance(edits,list) or len(edits)>2:raise ValueError('分类变更必须为有界列表。')
    touched=set()
    for edit in edits:
        if not isinstance(edit,dict):raise ValueError('分类变更必须为对象。')
        tree=edit.get('tree');action=edit.get('action')
        if tree not in ('equipment_class','part_class') or tree in touched:raise ValueError('分类字段未知或重复修改。')
        if action=='remove':
            require_keys(edit,{'action','tree','quote'},'remove class');quote(edit['quote'],question)
            if tree not in q['classes']:raise ValueError('不能删除不存在的分类条件。')
            q['classes'].pop(tree)
        elif action=='set':
            require_keys(edit,{'action','tree','reference'},'set class')
            root=reference(edit['reference'],question,context,store)
            if root and tree=='equipment_class' and root['tree']=='config':
                from relational_input_bindings import exact_model_selector
                code=exact_model_selector(store,root)
                if code:
                    q['classes'][tree]=code;touched.add(tree);continue
            if not root or root['tree']!=tree:raise ValueError('分类引用必须来自该分类字典的实际身份。')
            q['classes'][tree]=root['value']
        else:raise ValueError('分类只允许set/remove。')
        touched.add(tree)

def check_current_literals(tasks,question,context,store):
    """当前明确的新跨树编码不能被旧主体静默吞掉。"""
    if store is None:return
    refs=literal_references(question,store);by_value={}
    for ref in refs:
        if ref.get('field')=='code':by_value.setdefault(ref['value'],set()).add(ref['domain'])
    used=set()
    for task in tasks:
        q=task['spec']
        used.update(r['value'] for r in (q['root'],q['compare_root']) if r)
        used.update(q['classes'].values());used.update(f['value'] for f in q['filters'])
        # 完整名称可和当前文字里的完整编码证明同一真实身份；只在
        # 查表唯一后补入，不能凭字符串前缀或当前数量来证明。
        roots=[r for r in (q['root'],q['compare_root']) if r]+[{'tree':tree,'field':'identity','value':v} for tree,v in q['classes'].items()]
        for root in roots:
            table='points' if root['tree']=='points' else 'objects'
            clause='(code=? OR name=?)' if root['field']=='identity' else root['field']+'=?'
            args=[root['value'],root['value']] if root['field']=='identity' else [root['value']]
            if table=='objects':clause='tree=? AND '+clause;args=[root['tree']]+args
            matches=store.rows('SELECT DISTINCT code,name FROM '+table+' WHERE '+clause,args)
            if len({r['code'] for r in matches})==1:
                used.update(r[k] for r in matches for k in ('code','name'))
    for value,domains in by_value.items():
        if domains and value not in used:
            # 所属关系的候选字典编码可以是核对对象；必须先证明主体
            # 来自所属前的明确原话，再只接受真实图边提供的编码。
            if store is not None and re.search(r'所属.*(?:究竟|应该|还是)',question):
                from relational_query import Graph
                graph=Graph(store);prefix=question.split('所属',1)[0]
                linked=set()
                for task in tasks:
                    root=task['spec'].get('root')
                    if root and root['value'] in prefix:
                        actual=graph.resolve(root)
                        for row in actual if isinstance(actual,list) else [actual]:
                            linked.update(r['code'] for r in graph.links(row).values() if isinstance(r,dict) and 'code' in r)
                if value in linked:continue
            raise RelationalHandoff('本轮新的完整对象编码未定位；不能交付之前的另一个对象。')

def compile_delta(payload,question,context,store=None):
    require_keys(payload,{'version','handled','mode','tasks'},'关系变更V2')
    if payload['version']!=2 or payload['handled'] is not True or payload['mode'] not in ('new','update'):
        raise ValueError('关系变更版本或模式无效。')
    patches=payload['tasks'];old=previous_tasks(context);mode=payload['mode']
    if not isinstance(patches,list) or not 1<=len(patches)<=4:raise ValueError('关系变更任务数量无效。')
    if mode=='update' and not old:raise ValueError('没有实际旧任务可更新，不能从未执行草稿继承。')
    if mode=='new' and old:
        from relational_planner import retain_unchanged_tasks
        _,control=retain_unchanged_tasks({'handled':True,'tasks':[{'id':t['id'],'spec':copy.deepcopy(t['spec'])} for t in old.values()]},question,context)
        if control:raise ValueError('本轮明确保持已有编号任务，必须用update而非整组new。')
        text=re.sub(r'“[^”]*”|「[^」]*」|『[^』]*』|\"[^\"]*\"|`[^`]*`','',question)
        text=re.sub(r'(?:名字(?:叫|为)|名称(?:为|是)|名为|编码(?:为|是))[^，。；：:]*','',text)
        continues=re.search(r'刚才|上(?:一轮|条|轮)|这些|其中|同样|同一|这个(?:结果|范围)|该范围|保留|仍|继续',text)
        from request_turn import independent
        restarts=independent(question) or re.search(r'另查|另外(?:查|查询)|另一个问题|新问题|另起|回到|返回|重新开始',text)
        if continues and not restarts:raise ValueError('本轮明确引用既有结果或保留条件，不能整组new清空历史；使用update变更。')
    tasks={tid:{'id':tid,'spec':copy.deepcopy(t['spec'])} for tid,t in old.items()} if mode=='update' else {}
    changed=[];seen=set();audit=[]
    for p in patches:
        if not isinstance(p,dict):raise ValueError('关系变更任务必须为对象。')
        tid=p.get('id');action=p.get('action')
        if type(tid) is not int or not 1<=tid<=4 or tid in seen:raise ValueError('任务编号未知、越界或重复。')
        seen.add(tid)
        if action=='retain':
            require_keys(p,{'id','action'},'retain')
            if mode!='update' or tid not in old:raise ValueError('retain只能保留实际旧任务。')
            continue
        if action!=mode:raise ValueError('任务动作必须与整轮new/update模式一致。')
        allowed={'id','action','quote','set','filters','classes'}|({'root'} if 'root' in p else set())|({'compare_root'} if 'compare_root' in p else set())
        require_keys(p,allowed,'关系任务变更');text=quote(p['quote'],question)
        fields=p['set']
        if not isinstance(fields,dict) or set(fields)-SET_FIELDS:raise ValueError('关系设置字段不在登记契约。')
        if mode=='new':
            if not {'kind','population'}<=set(fields):raise ValueError('新任务必须明确结果种类与粒度。')
            q={'root':None,'compare_root':None,'depth':'all','classes':{},'filters':[],**DEFAULT_OUTPUT}
        else:
            if tid not in old:raise ValueError('修改的实际旧任务不存在；未改变其他任务。')
            q=canonical(old[tid]['spec'])
        before=copy.deepcopy(q)
        # 输出目标属于一个独立视图。重新选择视图时清除旧分组、旧排名
        # 和旧列；根、深度、类别和筛选仍由原状态保持。
        if any(k in fields and fields[k]!='keep' and fields[k]!=before.get(k) for k in ('kind','population','group_by')):
            q.update(copy.deepcopy({k:v for k,v in DEFAULT_OUTPUT.items() if k!='only'}))
        for key,value in fields.items():
            if value=='keep':
                if mode!='update':raise ValueError('新任务不能使用keep。')
                q[key]=copy.deepcopy(before.get(key))
            else:q[key]=copy.deepcopy(value)
        if 'depth' in fields and fields['depth']!='keep':
            d=fields['depth'];markers={'self':('自身','本身','本对象'),'direct':('直属','直接下级','直接部件','直接设备','直接对象','下一层','直接子'),'all':('全部','所有','后代','深层','全层级')}
            if d not in markers or not any(w in text for w in markers[d]):raise ValueError('改变深度没有对应本轮范围原话依据。')
            from request_turn import positive_scope_text
            if d in ('self','direct') and re.search(r'全部(?:后代|下级)|所有(?:后代|下级)|自身及全部后代',positive_scope_text(text)):raise ValueError('不能把完整后代范围缩成自身或直属。')
        for key in ('root','compare_root'):
            if key in p:q[key]=reference(p[key],question,context,store)
        if 'target_tree' in fields and fields['target_tree'] not in (None,'keep'):
            target=fields['target_tree'];base=(q['root'] or {}).get('tree','pbs')
            if base in ('equipment_class','part_class') and q['population'] in ('devices','parts','points'):base='pbs'
            unchanged=mode=='update' and target==before.get('target_tree')
            words={'pbs':('现场','PBS'),'config':('构型','模板')}
            if target not in words or target!=base and not unchanged and not any(w.lower() in text.lower() for w in words[target]):raise ValueError('集合输出树没有本轮目标原话依据。')
        apply_classes(q,p['classes'],question,context,store);apply_filters(q,p['filters'],question)
        tasks[tid]={'id':tid,'spec':canonical(q)};changed.append(tid)
        audit.append({'id':tid,'source_quote':text,'set_fields':sorted(fields),'root_changed':'root' in p,'filter_actions':copy.deepcopy(p['filters']),'class_actions':copy.deepcopy(p['classes'])})
    if not changed:raise ValueError('纯保留不能冒充本轮查询交付。')
    ordered=sorted(tasks.values(),key=lambda t:t['id']);check_current_literals(ordered,question,context,store)
    plan=validate_plan({'operation':'relational','entity':None,'scope':'direct','clarification':'','relational_tasks':ordered})
    return {'handled':True,'tasks':plan['relational_tasks']},{'protocol':2,'mode':mode,'changed_ids':changed,'retained_ids':sorted(set(tasks)-set(changed)),'changes':audit,'source':'本轮变更及实际已执行状态；遗漏字段和任务由程序保持'}
