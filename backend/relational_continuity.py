"""把真实单对象回执、未决范围与关系变更接入同一个身份和范围契约。"""
import copy,re
from relational_query import Graph,canonical,validate_plan

def prepared_context(context,store):
    out=copy.deepcopy(context)
    if store is None or out.get('pending_business_request'):return out
    receipt=out.get('query_receipt') or {};entity=out.get('entity')
    owned=(out.get('business_request') or {}).get('tasks',[])
    if owned and len(owned)!=1:return out
    # 测点属性回执的物理定位也可能标成PBS；逻辑原表/粒度决定所有者，
    # 不能把一次测量记录读取或多任务的一个子结果变成全局单对象关系目录。
    if (receipt.get('query') or {}).get('target')=='points' or receipt.get('grain')=='measurement_record':return out
    if receipt.get('operation') not in ('attributes','object','parts') or not entity or receipt.get('resolved_entity')!=entity:return out
    if entity.get('tree') not in ('pbs','config','equipment_class','part_class'):return out
    root={'tree':entity['tree'],'field':'code','value':entity['code']}
    try:actual=Graph(store).resolve(root)
    except ValueError:return out
    if isinstance(actual,list):return out
    kind='collection' if receipt['operation']=='parts' else 'relation'
    spec=canonical({'root':root,'kind':kind,'population':'parts' if kind=='collection' else 'objects','depth':receipt.get('scope','all')})
    # 这是实际普通回执的身份/范围桥，不把未查询的关联角色登记为结果。
    out['relational_state']={'tasks':[{'id':1,'spec':spec,'resolved':{'subject':[entity]}}]}
    out['relational_focus_source']='成功普通单对象回执，关联角色仍按实际图查询'
    return out

def pending_scope(question,context,store):
    draft=context.get('pending_business_request') or {};tasks=draft.get('tasks',[])
    if len(tasks)!=1 or store is None:return None
    task=tasks[0]
    if task.get('operation')!='descendants' or task.get('target')!='config' or task.get('scope')!='unspecified' or task.get('population') not in ('parts','all_objects'):return None
    choice=question.strip().strip('。！？!?')
    scope={'直接下级':'direct','直接的':'direct','直属':'direct','全部下级':'all','所有下级':'all'}.get(choice)
    if scope is None:return None
    filters=task.get('filters',[])
    if len(filters)!=1 or filters[0].get('operator')!='equals' or filters[0].get('field') not in ('code','name','identity'):return None
    root={'tree':'config','field':filters[0]['field'],'value':filters[0]['value']}
    try:node=Graph(store).resolve(root)
    except ValueError:return None
    if isinstance(node,list):return None
    spec=canonical({'root':root,'kind':'collection','population':'parts' if task['population']=='parts' else 'objects','depth':scope})
    return validate_plan({'operation':'relational','entity':None,'scope':'direct','clarification':'','relational_tasks':[{'id':1,'spec':spec}]})

def scope_marked(text):
    from request_turn import positive_scope_text
    return bool(re.search(r'直接|直属|下一层|直接子|自身|本身|全部|所有|后代|深层|全层级',positive_scope_text(text)))

def continued_collection_tree(question,context,store,value):
    """连续同种简单集合的来源域是已执行查询参数；新身份仍须当前原话和原表证明。"""
    tasks=(context.get('relational_state') or {}).get('tasks',[])
    if len(tasks)!=1 or store is None or context.get('pending_business_request'):return None
    spec=tasks[0]['spec'];root=spec.get('root')
    if spec.get('kind')!='collection' or not root or spec.get('population') not in ('parts','devices','objects'):return None
    if any(spec.get(k) for k in ('classes','filters','group_by','properties','limit','only','boundary','compare_root','target_tree')):return None
    from request_turn import independent
    if independent(question) or re.search(r'另查|另外|重置|清空|不要|取消|比较|分别|同时|排序|筛选|限定|增加|撤销',question):return None
    noun={'parts':'部件','devices':'设备','objects':'对象'}[spec['population']]
    # 已执行的单一集合给出输出所有者；字面根给出新的实际身份。
    # 只换根/沿用要求不必重新复述“下有哪些”，关系目标另走独立域证明。
    control = re.search(r'换|切|改|沿用|保持|继续|相同|同样|不变|不动|接着',question)
    reread = noun in question and re.search(r'下|后代|列出|查|多少|几[个条类]|数量',question)
    if not (control or reread) or re.search(r'对应|所属|是什么|名称|父对象|上级',question):return None
    from request_checklist import literal_references
    values={r['value'] for r in literal_references(question,store) if r.get('field') in ('name','code')}
    if values!={value}:return None
    return root['tree']

def collection_continuity(value,question,context,store,audit):
    """简单集合连续替根保留深度；重读必须证明完整身份和同一输出意图。"""
    if store is None or len(value.get('tasks',[]))!=1:return
    tasks=(context.get('relational_state') or {}).get('tasks',[])
    if len(tasks)!=1:return
    previous=tasks[0];spec=previous['spec'];root=spec.get('root')
    if spec.get('kind')!='collection' or spec.get('population') not in ('parts','devices','objects') or not root:return
    if any(spec.get(k) for k in ('classes','filters','group_by','properties','limit','only','boundary','compare_root','target_tree')):return
    from relational_state import exact_literal,reference
    from request_checklist import literal_references
    p=value['tasks'][0];text=question
    if not isinstance(p,dict):return
    from request_turn import independent, depth_control
    if independent(text) or re.search(r'另查|另外|清空|重置|取消|不要|别|比较|分别|同时|排序|筛选|限定|增加|撤销|不查询|不执行',text):return
    if p.get('action')=='retain':
        if value.get('mode')!='update' or p.get('id')!=previous['id']:return
        depth = depth_control(text)
        refs = [r for r in literal_references(question,store) if r.get('field') in ('code','name')]
        if depth and not refs:
            value['tasks']=[{'id':previous['id'],'action':'update','quote':question,'set':{'depth':depth},'filters':[],'classes':[]}]
            audit.append('单集合肯定层级控制变更实际深度；其他查询槽位保持')
            return
        noun={'parts':'部件','devices':'设备','objects':'对象'}[spec['population']]
        if noun not in text or not re.search(r'下|后代|有哪些|有什么|列出|多少|几[个条类]|数量',text):return
        try:
            node=Graph(store).resolve(root)
            exact_literal(root['tree'],root['field'],root['value'],question,question,context,store)
        except ValueError:return
        if isinstance(node,list) or any(r['value'] not in (node['code'],node['name']) for r in literal_references(question,store)):return
        if scope_marked(text):return
        value['tasks']=[{'id':previous['id'],'action':'update','quote':question,'set':{},'filters':[],'classes':[]}]
        audit.append('当前明确重读同一完整集合；保持实际根和范围重新执行，不把保存指令当查询')
        return
    fields=p.get('set',{})
    if not isinstance(fields,dict) or fields.get('kind','collection')!='collection' or fields.get('population',spec['population'])!=spec['population'] or p.get('filters') or p.get('classes'):return
    if set(fields)-{'kind','population','depth','sort','properties','target_tree','group_by','limit','only','boundary'} or fields.get('properties') or fields.get('target_tree') or fields.get('sort') not in (None,[],['code']):return
    if any(fields.get(k) is not None for k in ('group_by','limit','only','boundary')):return
    if 'root' not in p and not (value.get('mode')=='update' and p.get('id')==previous['id']):return
    try:newroot=reference(p['root'],question,context,store) if 'root' in p else root
    except ValueError:return
    if not newroot or newroot['tree']!=root['tree']:return
    if value.get('mode')=='new':
        value['mode']='update';p['id']=previous['id'];p['action']='update'
        audit.append('同一简单集合的连续主体替换接入更新契约；独立问题、条件和多任务不继承')
    if value.get('mode')=='update' and not scope_marked(text):
        fields.pop('depth',None)
        audit.append('本轮未改变层级，连续集合继承程序保存的深度')
