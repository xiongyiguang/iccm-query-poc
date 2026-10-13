"""实际输入绑定：原表身份与输出域分开，精确型号条件不依赖模型重抄。"""
import re
from relational_query import Graph,CLASS_LEVELS

def site_population(text):
    """现场与所问对象可以隔着关联动词，不要求两个词必须相邻。"""
    for word,population in (('部件','parts'),('设备','devices')):
        if re.search(r'现场[^，。；;！？!?]{0,16}'+word,text):return population
    return None

def complete_task_source(value,question,audit):
    """单个集合任务的句首对象域声明是本轮原话的一部分，不能被引文裁掉。"""
    if value.get('mode')!='new' or len(value.get('tasks',[]))!=1:return
    item=value['tasks'][0]
    if not isinstance(item,dict) or not isinstance(item.get('set'),dict):return
    text=item.get('quote')
    if item.get('action')!='new' or item['set'].get('kind')!='collection' or not isinstance(text,str) or not text or text==question or not question.endswith(text):return
    prefix=question[:-len(text)]
    if re.fullmatch(r'\s*(?:请)?(?:按|按照|依据|在|从)\s*(?:构型树|PBS(?:树|表)?|现场台账|设备类表|部件类表)(?:的(?:父子关系|层级关系|真实父关系)|中|里|内)?\s*[，,:：]?\s*',prefix,re.I):
        item['quote']=question;audit.append('独立集合保留当前句首已明确的查询对象域来源，不用目标字段替代或拼造原话')

def explicit_relation_read(value,question,context,store,audit):
    """有当前完整身份的再次读取不是仅保存；只复用唯一实际单对象请求。"""
    if store is None or set(value)!={'version','handled','mode','tasks'} or value.get('mode')!='update' or len(value['tasks'])!=1:return
    item=value['tasks'][0]
    if not isinstance(item,dict) or set(item)!={'id','action'} or item['action']!='retain' or type(item['id']) is not int:return
    from relational_state import previous_tasks,exact_literal
    old=previous_tasks(context)
    if len(old)!=1 or item['id'] not in old:return
    spec=old[item['id']].get('spec',{});root=spec.get('root')
    if spec.get('kind')!='relation' or not root or root.get('tree') not in ('pbs','config','equipment_class','part_class') or spec.get('properties') or spec.get('compare_root') or spec.get('boundary'):return
    try:
        actual=Graph(store).resolve(root)
        exact_literal(root['tree'],root['field'],root['value'],question,question,context,store)
    except ValueError:return
    # 去除真实标识里的字面词，避免名称内含“是什么”等字样被当成读取动作。
    text=question
    for literal in sorted({actual['code'],actual['name']},key=len,reverse=True):
        if literal:text=text.replace(literal,' ')
    if not re.search(r'是什么|是啥|叫什么|介绍|详情|详细(?:信息|情况)',text):return
    if re.search(r'不要|不用|无需|不必|别|不执行|不查询|不再查|只保留|仅保留|取消|撤销|改为|改成|换成|对应|所属|关联|下级|上级|直属|数量|多少|筛选|排序|比较',text):return
    from request_checklist import literal_references
    if any(ref['value'] not in (actual['code'],actual['name']) for ref in literal_references(question,store)):return
    value['tasks']=[{'id':item['id'],'action':'update','quote':question,'set':{},'filters':[],'classes':[]}]
    audit.append('当前明确重新读取且完整身份与唯一已执行单对象一致；空字段update由程序保持原根并重新交付，不把仅保留解释成查询')

def classification_boundary_request(question,context,store):
    """已执行缺类明细的结论边界由登记规则负责，不随机交不支持入口。"""
    if store is None or context.get('pending_business_request'):return None
    from relational_state import previous_tasks
    tasks=previous_tasks(context)
    if len(tasks)!=1:return None
    task=next(iter(tasks.values()));spec=task.get('spec',{})
    if spec.get('kind') not in ('collection','boundary') or spec.get('population')!='parts' or spec.get('only')!='missing_class' or spec.get('group_by') or spec.get('limit') or spec.get('target_tree') or spec.get('properties'):return None
    normative=bool(re.search(r'是否|可否|能否|能不能|可以|能证明|能认定|意味着|是不是',question))
    missing=bool(re.search(r'没有(?:部件)?(?:类|类别|分类)|无(?:类别|分类)|缺(?:少|失)?(?:分类|类别|部件类)',question))
    replace_parent=bool(re.search(r'(?:上级|父级|父对象)[^，。；;！？!?]{0,12}(?:类别|分类|部件类)[^，。；;！？!?]{0,12}(?:替代|代替)|(?:替代|代替)[^，。；;！？!?]{0,12}(?:上级|父级)',question))
    if not normative or not (missing or replace_parent):return None
    if re.search(r'改为|改成|换成|另查|新问题|增加|删除|数量|多少|排序|前\d+|健康|报警|时长|阈值|故障|预测|维修',question):return None
    from request_checklist import literal_references
    generic={'类别','分类','部件','部件类','上级','父级','设备','构型'}
    if any(ref['value'] not in generic for ref in literal_references(question,store)):return None
    from relational_query import canonical,validate_plan
    query=canonical({**spec,'kind':'boundary','boundary':'classification'})
    return validate_plan({'operation':'relational','entity':None,'scope':'direct','clarification':'','relational_tasks':[{'id':task['id'],'spec':query}]})

def exact_model_selector(store,root):
    """只有一对一同码、同父且真实角色为设备构型时兼容字典选择接口。"""
    if store is None or not root or root.get('tree')!='config':return None
    graph=Graph(store)
    actual=graph.resolve(root)
    if isinstance(actual,list) or actual.get('level')!='设备':return None
    code=actual['code']
    try:roles=graph.classify({'equipment_class':code})
    except ValueError:return None
    return code if roles=={'equipment_config':code} else None

def bind_explicit_inputs(item,question,context,store,audit):
    """仅绑定当前独立集合中可由原话和原表唯一证明的输入，不继承或猜测条件。"""
    if store is None or item.get('action')!='new':return
    fields=item.get('set',{});ref=item.get('root');text=item.get('quote')
    if not isinstance(fields,dict) or fields.get('kind')!='collection' or not isinstance(ref,dict) or ref.get('type')!='literal' or not isinstance(text,str) or text not in question:return
    from relational_state import reference,exact_literal
    graph=Graph(store)
    # 构型目标字段不能改变原话已明确的设备类输入。
    if fields.get('target_tree')=='config' and ref.get('tree')=='config':
        try:reference(ref,question,context,store)
        except ValueError:
            try:source=exact_literal('equipment_class',ref.get('field'),ref.get('value'),text,question,context,store)
            except ValueError:return
            node=graph.resolve(source);linked=graph.links(node).get('config')
            if not isinstance(node,list) and linked and linked.get('code')==node['code'] and linked.get('level') in CLASS_LEVELS and graph.classify({'equipment_class':node['code']})=={'equipment_class':node['code']}:
                item['root']={'type':'literal',**source,'quote':text}
                audit.append('当前原话设备类输入与真实同码分类构型已核实；保持字典起点及构型输出域，不借目标字段换原表')
        return
    if ref.get('tree')!='pbs' or fields.get('population') not in ('devices','parts') or fields.get('target_tree') not in (None,'pbs') or not isinstance(item.get('classes'),list):return
    anchor=reference(ref,question,context,store);node=graph.resolve(anchor)
    if isinstance(node,list) or node.get('tree')!='pbs':return
    # 明确采用/使用关系的受限绑定。排除、未采用、比较等表达不推断为包含。
    if re.search(r'(?:排除|除去|不含|不包括|未采用|未使用|(?<!有)没有采用|(?<!有)没有使用|不采用|不使用|对比|比较)',text):return
    from relational_planner import literal_relation_inputs
    from identifier_aliases import complete_literal_pattern
    models={}
    for literal in literal_relation_inputs(text,store):
        if literal['tree']!='config':continue
        pattern=r'(?:采用|使用|选用|装配|配置|对应)(?:的)?(?:设备)?(?:构型|模板|型号)[^，。；;！？!?]{0,24}?'+complete_literal_pattern(literal['value'])
        if not re.search(pattern,text):continue
        actual=graph.resolve(literal)
        if not isinstance(actual,list) and actual.get('level')=='设备':models[actual['code']]=literal
    if len(models)!=1:return
    # 已有选择条件交严格编译核对；不覆盖不同型号或其他真实条件。
    code,literal=next(iter(models.items()))
    if exact_model_selector(store,literal)!=code:return
    edits=[edit for edit in item['classes'] if isinstance(edit,dict) and edit.get('tree')=='equipment_class']
    if not edits:
        item['classes'].append({'action':'set','tree':'equipment_class','reference':{'type':'literal',**literal,'quote':text}})
        audit.append('当前明确采用关系及唯一真实构型由程序绑定精确型号选择；保留现场根、深度、其他筛选，不补查询答案')
    elif len(edits)!=1 or edits[0].get('action')!='set':return
    else:
        selected=reference(edits[0].get('reference'),question,context,store)
        if selected and selected.get('tree')=='config':selected_code=exact_model_selector(store,selected)
        elif selected and selected.get('tree')=='equipment_class':
            roles=graph.classify({'equipment_class':selected['value']});selected_code=roles.get('equipment_config')
        else:return
        if selected_code!=code:return
    comparison=item.get('compare_root')
    if isinstance(comparison,dict) and comparison.get('type')=='literal':
        actual=reference(comparison,question,context,store)
        if exact_model_selector(store,actual)==code:
            item.pop('compare_root');audit.append('非比较集合的副根与已核实精确型号条件指向同一原构型；按当前采用关系绑定选择，不保留重复比较对象')
