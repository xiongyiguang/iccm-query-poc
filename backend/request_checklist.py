"""独立提取需求，并执行确定性一致性核验。

提取器不接收候选计划、变更草稿或另一提取器的结论。"""
import copy
import json
import os
import time
import re
import threading
from concurrent.futures import ThreadPoolExecutor
import urllib.request
from pathlib import Path
from business_request import apply_delta,RequestInvalid,RequestAmbiguous,ground_identifiers,compile_selected,source_segments,execution_quotes,NOTE_OPERATIONS

ROOT=Path(__file__).resolve().parents[1]
_EXTRACTORS=ThreadPoolExecutor(max_workers=4,thread_name_prefix='independent-request')
_ASYNC=threading.local()


def extraction_key(question,previous,reference_context):
    return json.dumps([question,previous,reference_context],ensure_ascii=False,sort_keys=True)


def discard_extraction():
    pending=getattr(_ASYNC,'pending',None)
    if pending:pending[1].cancel()
    _ASYNC.pending=None


def prefetch(question,previous,verified_schema,reference_context):
    """仅使用本轮开始前的数据，不读取其他规划器的建议。"""
    discard_extraction()
    if not verified_schema or os.environ.get('ICCM_PARALLEL_CHECKLIST','1')!='1':return
    future=_EXTRACTORS.submit(extract,question,copy.deepcopy(previous),
        os.environ.get('ICCM_CHECKLIST_THINKING','disabled'),os.environ.get('ICCM_CHECKLIST_MODEL','deepseek-v4-pro'),
        reference_context=copy.deepcopy(reference_context),verified_schema=copy.deepcopy(verified_schema))
    _ASYNC.pending=(extraction_key(question,previous,reference_context),future)

def prefetched_ready(question,previous,reference_context):
    """只检查入口能力，把独立建议保留给执行前核验层。"""
    pending=getattr(_ASYNC,'pending',None)
    if not pending or pending[0]!=extraction_key(question,previous,reference_context):return False
    try:answer,trace=pending[1].result()
    except (ValueError,TypeError,KeyError,urllib.error.URLError,TimeoutError):return False
    # extract() 已校验类型化请求；重新提取入口时，不把
    # 独立提取器建议的字段提供给主提取器。
    trace['capability_checked_at_route']=True
    return answer.get('status')=='ready'


def business_catalog(store=None):
    from attributes import CATALOG
    from query_filters import POINT_FIELDS,POINT_RAW_FIELDS,OBJECT_FIELDS,OPERATORS,target_catalog,filter_fields
    from typed_fields import THRESHOLDS
    catalog={'task_execution_policy':{'state':'update中未执行的旧任务仍由程序完整保留；new才清除旧组。','execution':'当前协议每任务execute必填：true表示本轮执行，false表示已有任务原样保留且不执行；未提及的旧任务也自动保留。false不得修改字段、条件或单位；保持任务状态不表示读取status字段。旧协议没有execute时按列出的任务执行。','replay':'用户明确要求重查旧任务时，即使条件完全不变也应列入执行；不可按条件是否变化自动删任务。'},'targets':target_catalog(),'properties':CATALOG,'property_groups':{'thresholds':list(THRESHOLDS)},
            'query_forms':{'search':'返回符合筛选的记录列表，即使只匹配一条记录也仍是列表；空properties表示使用列表默认列，不表示无返回内容。',
                           'attributes':'读取一个对象的身份或具体属性；问它是什么对象、对应哪个对象，属于身份属性读取，不能只返回列表。未逐项列属性的身份问句采用identity_projection；仅明确要求全部属性才用[*]。'},
            'comparison_semantics':{'equals':'字段原值严格相等；类别值按业务目录，不拆成字面词语重新解释。',
                'not_contains':'原始文本不包含子串，包括空值。它不等于另一个已知类别，也不等于已知的否定状态。',
                'is_blank':'原始值未提供；不是数值零，也不是未报警或关闭。',
                'not_blank':'原始值已提供，不保证有明确物理单位或当前状态。',
                'unit':'读取已有读数时单位缺失应如实返回，不能因此拒绝读取；数值条件需要明确单位时才保存待澄清草稿。'},
            'point_conditions':filter_fields('points'),
            'object_conditions':filter_fields('objects'),'operators':sorted(OPERATORS),
            'property_availability':'properties中列出的所有键都是合法读取请求；fields为空表示执行时须报告原数据不支持该属性，不表示请求字段非法。读取原始值不要求推断物理量或填补单位。',
            'implicit_reading_projection':['value','unit','source','time','physical_quantity'],
            'overview_policy':'先按请求的业务对象与输出目的选择默认投影：测点/监测点概况读取现有快照，purpose=data、subject_scope=none、target=points，使用implicit_reading_projection；设备/PBS/构型/类别基本介绍才用introduction和identity_projection。测点身份确认仍identity；明确列字段时只返回指定字段。概况不授权实时健康诊断，也不能因字段省略把测点概况改成未指定树的身份介绍。',
            'identity_projection':['name','code','type','level','parent'],
            'introduction_policy':'本条针对设备/PBS/构型/类别等对象的基本身份介绍，不针对测点快照概况。对象基本介绍是身份属性读取，使用identity_projection，不是全部属性或不支持的功能。对象树未明确且没有已确认树的宽泛介绍先询问树；补充后承接pending原始对象，立即精确定位，不再索要已给出的标识。明确对象树的新介绍同样读取基本属性；零命中由数据库如实返回。',
            'identity_domain_policy':'对象身份查询：对象树未明确且没有同一对象的已确认树时，target=objects跨树精确核验，不能根据设备等日常业务称呼自动限定构型树或设备层级。同一标识跨树命中由程序返回实际候选；不同完整标识不能因为前缀相似就继承旧对象。当前明确指的是已确认的同一对象才沿用其树。',
            'context_identity_policy':'完整标识与已确认当前对象的实际编码或名称相同，且原话未要求换树时，沿用当前对象的树；日常称呼不能自行重置已确认域。完整标识发生变化（即使只是前缀相近）是另一个引用，不能假定为上一对象的简称；无新树时跨树精确核验。名称和实际编码是同一对象的两种标识，按程序给出的literal_references和executed_subject核对，不能凭外形猜测。',
            'projection_policy':'明确列出所需字段时只返回这些字段；泛问读数时允许附带单位、来源、快照时间与物理含义缺失说明。identity是合法的名称或编码联合匹配字段，不可因未限定name/code而拒绝。'}
    catalog['task_execution_policy']={'state':'update中未提及的旧任务由程序完整保留；new才清除旧组。',
        'delivery':'当前模型协议用action=request交付查询、解释或能力边界；是否需要SQL不影响request。',
        'retain':'原样保留用action=retain加已有编号，不重述字段/条件/来源，不允许修改或新建。',
        'replay':'明确重查旧任务即使未改字段仍request；内部execute仅兼容存储，不是当前模型输出字段。'}
    from data_context import STATIC_TOPICS,DOMAIN_FACTS
    catalog['explanation_topics']=STATIC_TOPICS
    catalog['explanation_facts']={k:DOMAIN_FACTS[k] for k in STATIC_TOPICS}
    catalog['capability_task_policy']='静态概念说明用explain任务及目录主题；不支持的诊断/实时状态/预测用unsupported任务、topics=[limits]。两者不添加数据查询。与读取混合时逐项表达，不能整份unsupported吞掉合法任务。构型根对象的下级列表与数量使用descendants任务：target=config仅表示根对象树，scope=direct/all/unspecified表示遍历深度，population=all_objects/parts/unspecified独立表示返回集合。所有下级对象包括部件与非部件，不加层级限制；只有明确要求部件才用parts。仅说下面有多少东西不授权默认类型或深度，使用unspecified保留完整根草稿并澄清。只允许一个根对象identity/name/code精确条件，不带返回属性或单位。parts旧任务仅用于兼容已存状态，新的关系请求优先descendants。其他关系/分组统计及特定结果说明仍走原专用业务处理。'
    # 两个提取器都能看到现有执行器能力，而非只看到新 DSL。
    from analytics import planner_groups
    from date_fields import business_clock
    catalog['business_clock']=business_clock()
    catalog['threshold_default_policy']='未明确阈值族但指定高/低1至3时，仅取真实值actual同级阈值，不额外加入估计值或变化速率偏差；未指定高低等级的泛问阈值返回18项。明确估计值/偏差族时按明确字段读取。'
    catalog['result_goal_capabilities']={'kinds':['records','count','attributes','extreme','sort','difference'],'fields':['time','value','thresholds'],'date_operators':['date_gte','date_lt','date_equals'],'ties':'all','difference_directions':[None,'absolute'],'difference_policy':'明确纯算术口径才计算；绝对差须direction=absolute，有向第一项减第二项为null；未确认物理量不混算。','basis_policy':'排序、极值、差值只按原始数值比较时basis=raw_numbers；未明确授权则measurement。basis独立于排序方向及数量，不因为返回100条或仅改TopK就默认回measurement；局部续改保留所有未改目标字段。'}
    catalog['result_goal_capabilities']['selection_policy']='极值集合extreme只返回字段达到同一最小/最大值的全部并列记录；有序列表sort按顺序返回全范围或前N。先判集合目的，再判顺序；sort且limit=null不等价于extreme，ties=all不能消除区别。完整新问题的结果目标独立提取，不继承旧kind。'
    catalog['aggregation_groups']=planner_groups()
    catalog['aggregation_policy']='对象类型分组使用type原字段；层级编号分组使用level原字段。两者不可替代。'
    catalog['dedicated_capabilities']={
        'policy':'以下是系统已实现、但尚未迁入business_request协议的专用查询。主入口必须转legacy，让专用规划和执行器校验；不可把协议表达限制当系统能力不支持，也不可删掉关系条件硬塞入普通查询。',
        'pbs_equipment_class_parts':{
            'inputs':['PBS现场范围的完整名称或编码','设备类的完整名称或编码','可选部件筛选与直接/全部下级范围'],
            'path':['PBS范围内设备','设备构型及设备类祖先映射','现场实际挂接部件','部件类字典'],
            'outputs':['部件列表','部件总数','部件类别数及各类别数量'],
            'contract':'entity保持PBS范围；query.target=parts且equipment_class独立保留；类别分组用analyze/group_count/class_code。无匹配或关系资料缺失由执行器报告。不得扩大到全局构型。'},
        'pbs_point_scope':{'inputs':['PBS根对象的完整名称或编码','可选测点字段筛选'],
            'path':['先核验PBS根对象','根对象自身及全部后代的原始父链','按测点编码关联原始记录','再应用测点筛选'],
            'outputs':['范围内测点记录','记录条数','已实现的排序、极值或统计'],
            'contract':'PBS对象范围与测点自身身份是不同条件。已实现专用查询保持entity={tree:pbs,code或name:根对象}，query.target=points，query.filters仅含测点自身筛选；不能把根标识放入测点identity/name/code equals冒充范围，不能猜测编码前缀关联。没有明确直接深度时按现有自身及全部后代口径说明；明确仅直接层级而协议不支持时澄清，不冒充已实现。'},
        'other_dedicated':['对应设备/设备类/部件类、父对象及PBS构型映射','按执行目录允许维度的分组统计/排名/占比','针对已执行结果的依据解释'],
        'boundary':'只支持已验证关系，不支持任意跨树SQL、实时故障诊断或预测。普通列表、属性、单构型下级仍按原business_request规则。'}
    if store is not None:
        catalog['point_categories']={};catalog['category_coverage']={}
        for field,column in POINT_FIELDS.items():
            if field not in ('source','status','switch','unit'):continue
            values=[r['value'] for r in store.rows('SELECT DISTINCT '+column+' AS value FROM points ORDER BY '+column+' LIMIT 129',[])]
            catalog['point_categories'][field]=values[:128]
            catalog['category_coverage'][field]={'complete':len(values)<=128,'displayed':min(len(values),128)}
        catalog['category_policy']='目录是当前数据取值，不是禁止查询其他值的白名单。category_coverage.complete=false表示仅提供样例，未列出不代表不存在；无匹配时由数据库返回空结果，不能替换为其他类别或拒绝合法查询。'
    return catalog

def request_view(state,changed):
    # 规范化数据库身份只用于等价比较，不作为模型语义输入。
    return [copy.deepcopy(t) for t in state['tasks'] if t['id'] in changed]

def literal_references(question,store):
    """从用户原话链接字段和对象，不依赖任一候选计划。"""
    if store is None:return []
    refs=[]
    for table,domain in (('points','points'),('objects',None)):
        for field in ('name','code'):
            rows=store.rows('SELECT DISTINCT '+field+' AS value'+(',tree' if domain is None else '')+
                ' FROM '+table+' WHERE length('+field+')>0 AND instr(?,'+field+')>0 ORDER BY length('+field+') DESC LIMIT 32',[question])
            for row in rows:
                value=row['value']
                for match in re.finditer(re.escape(value),question):
                    start,end=match.span()
                    if field=='code' and ((start and re.fullmatch(r'[A-Za-z0-9_&.#-]',question[start-1])) or (end<len(question) and re.fullmatch(r'[A-Za-z0-9_&.#-]',question[end]))):continue
                    refs.append({'domain':domain or row['tree'],'field':field,'value':value,'start':start,'end':end})
    # 嵌在更长已知名称或编码中的短编码，不是另一处独立引用。
    # 同一文字位置命中不同对象树时都保留，这是实际歧义。
    complete=[r for r in refs if not any(x['start']<=r['start'] and x['end']>=r['end'] and x['end']-x['start']>r['end']-r['start'] for x in refs)]
    result=[];seen=set()
    for r in complete:
        key=(r['domain'],r['field'],r['value'])
        if key not in seen:result.append(r);seen.add(key)
    from coordinated_references import coordinated_literals
    result+=coordinated_literals(question,store,result)
    from identifier_aliases import schema_name_aliases
    result+=schema_name_aliases(question,store)
    return result

def resolve_sources(checklist,question,reference_context=None):
    if checklist.get('version') not in (2,3,4,5,6,7,8,9,10,11,12,13):return checklist
    from business_request import resolve_request_actions
    out=resolve_request_actions(checklist,question,'id') if checklist['version'] in (7,8,9,10,11,12,13) else copy.deepcopy(checklist)
    version=out.pop('version');segments={s['id']:s for s in source_segments(question)}
    if not isinstance(out.get('tasks'),list):raise RequestInvalid('条件清单tasks必须是数组。')
    def quote(ids,inherit=False):
        if inherit and ids==[]:return None
        if not isinstance(ids,list) or not ids or any(type(i)!=int or i not in segments for i in ids) or len(set(ids))!=len(ids):raise RequestInvalid('原话片段编号不存在或重复。')
        return question[min(segments[i]['start'] for i in ids):max(segments[i]['end'] for i in ids)]
    for task in out.get('tasks',[]):
        if not isinstance(task,dict):raise RequestInvalid('条件清单任务必须是对象。')
        if version in (7,8,9,10,11,12,13) and task.get('operation')=='retain':continue
        kind=None
        if version in (6,7,8,9,10,11,12,13):
            kind=task.pop('kind',None)
            if kind not in (('query','parts','descendants','explain','unsupported') if version in (12,13) else ('query','parts','explain','unsupported') if version==11 else ('query','explain','unsupported')) or 'operation' in task:raise RequestInvalid('V6任务必须明确query/explain/unsupported类型，不能另带operation。')
            if kind not in ('query','parts','descendants'):
                if 'quote' in task:raise RequestInvalid('不能重写任务原话。')
                task['operation']=kind;task['quote']=quote(task.pop('spans',None))
                continue
        if version in (3,4,5,6,7,8,9,10,11,12,13):
            if 'operation' in task:raise RequestInvalid('V3由返回字段决定查询形式，不接受重复operation字段。')
            task['operation']=kind if kind in ('parts','descendants') else 'attributes' if task.get('properties') else 'search'
        if 'quote' in task:raise RequestInvalid('不能同时重写引文和引用编号。')
        task['quote']=quote(task.pop('spans',None))
        for f in task.get('conditions',[]):
            if 'quote' in f:raise RequestInvalid('不能重写条件原话。')
            if version in (4,5,6,7,8,9,10,11,12,13):
                if 'reference' not in f:raise RequestInvalid('V4条件须区分本轮片段、已确认条件和前文引用。')
                refid=f.pop('reference')
                if refid is not None:
                    refs=[r for r in (reference_context or {}).get('references',[]) if r.get('id')==refid]
                    if type(refid)!=int or len(refs)!=1 or f.pop('spans',None)!=[]:
                        raise RequestInvalid('前文引用编号无效，或与本轮来源混用。')
                    ref=refs[0];target=task.get('target')
                    # 同一选中编码的跨域引用必须有目录实际核验，不能凭PBS外观当测点。
                    mapped='config' if target in ('equipment','parts') else target
                    if ref['domain']!=mapped and ref.get('kind') in ('user_selection','executed_entity'):
                        peers=[r for r in (reference_context or {}).get('references',[]) if r['value']==ref['value'] and r['domain']==mapped and r.get('kind')==ref.get('kind') and r['field']==ref['field']]
                        if len(peers)==1:ref=peers[0]
                    if (f.get('operator')!='equals' or f.get('field') not in ('name','code','identity') or
                        ref['value']!=f.get('value') or f['field']!='identity' and ref['field'] not in ('identity',f['field']) or
                        not (ref['domain'] is None or ref['domain']==('config' if target in ('equipment','parts') else target) or target=='objects' and ref['domain']!='points')):
                        raise RequestInvalid('前文引用与对象标识、字段或目标域不符。')
                    # 当前任务仍需提供用户采用旧值的原话依据；
                    # apply_delta 再将实际值绑定到可信的历史来源。
                    f['quote']=task['quote']
                    continue
            f['quote']=quote(f.pop('spans',None),True)
    return out

def prior_view(previous):
    return [({'id':t['id'],'operation':t['operation'],'topics':copy.deepcopy(t['topics'])} if t['operation'] in NOTE_OPERATIONS else
             {'id':t['id'],'operation':t['operation'],'target':t['target'],'properties':t['properties'],
             'purpose':t['sources'].get('purpose',{}).get('value','data'),'subject_scope':t['sources'].get('subject_scope',{}).get('value','none'),
             **({'scope':t['scope']} if t['operation'] in ('parts','descendants') else {}),
             **({'population':t['population']} if t['operation']=='descendants' else {}),
             **({'result_goal':copy.deepcopy(t['result_goal'])} if 'result_goal' in t else {}),'unit':t['unit'],'conditions':[{k:f[k] for k in ('field','operator','value')} for f in t['filters']]}
             ) for t in (previous or {}).get('tasks',[])]

def extract(question,previous,thinking='disabled',model=None,effort=None,store=None,reference_context=None,verified_schema=None):
    from model import NoRedirect,ENDPOINT,MODEL
    from attributes import CATALOG
    from query_filters import POINT_FIELDS,POINT_RAW_FIELDS,OBJECT_FIELDS,OPERATORS
    prompt=(ROOT/'prompts/system/request-checklist-v25.txt').read_text(encoding='utf-8')
    catalog=verified_schema['business_catalog'] if verified_schema else business_catalog(store)
    payload={'question':question,'segments':source_segments(question),'prior':prior_view(previous)}
    if reference_context:payload['reference_context']=reference_context
    if store is not None:payload['literal_references']=literal_references(question,store)
    elif verified_schema:payload['literal_references']=verified_schema['literal_references']
    body={'model':model or MODEL,'messages':[{'role':'system','content':prompt+'\n业务目录：'+json.dumps(catalog,ensure_ascii=False)},
            {'role':'user','content':json.dumps(payload,ensure_ascii=False)}],
          'response_format':{'type':'json_object'},'thinking':{'type':thinking},'stream':False,'max_tokens':8192 if thinking=='enabled' else 4096}
    if thinking=='enabled':body['reasoning_effort']=effort or os.environ.get('ICCM_CHECKLIST_EFFORT','high')
    else:body['temperature']=0
    start=time.monotonic();attempts=[]
    for attempt in range(2):
        req=urllib.request.Request(ENDPOINT,data=json.dumps(body,ensure_ascii=False).encode(),headers={'Authorization':'Bearer '+os.environ.get('DEEPSEEK_API_KEY',''),'Content-Type':'application/json'},method='POST')
        with urllib.request.build_opener(NoRedirect).open(req,timeout=60 if thinking=='enabled' else 15) as res:raw=json.load(res)
        choice=raw['choices'][0]
        if choice.get('finish_reason')!='stop':raise RequestInvalid('独立条件提取未完整结束。')
        content=choice['message']['content'];attempts.append({'content':content,'model':raw.get('model'),'usage':raw.get('usage')})
        try:
            answer=json.loads(content)
            if answer.get('version')!=13:raise RequestInvalid('当前独立清单必须使用V13完整结果目标契约，不能降级到旧协议。')
            delta=to_delta(answer,previous,question,reference_context)
            if delta is not None:apply_delta(delta,previous,question,reference_context)
            break
        except RequestAmbiguous:break
        except (ValueError,TypeError,KeyError) as error:
            attempts[-1]['validation_error']=str(error)
            if attempt:
                failure=RequestInvalid('独立清单经一次修正仍不合法：'+str(error))
                failure.extraction_trace={'input':payload,'attempts':copy.deepcopy(attempts),'seconds':round(time.monotonic()-start,3)}
                if hasattr(error,'business_constraint'):failure.business_constraint=copy.deepcopy(error.business_constraint)
                raise failure from None
            body['messages']+=[{'role':'assistant','content':content},{'role':'user','content':'程序校验发现协议冲突：'+str(error)+'。请重新按原话和完整业务目录提取同一份条件清单。只修正结构、引用编号或互斥字段，不得忽略原话条件；若原话不能表达为可执行任务应明确unsupported。只输出JSON。'}]
    # 不保存供应商的思考正文或 Authorization 请求头。
    return answer,{'model':raw.get('model'),'thinking':thinking,'effort':body.get('reasoning_effort'),'seconds':round(time.monotonic()-start,3),'usage':raw.get('usage'),
                   'input':payload,'checklist':copy.deepcopy(answer),'attempts':attempts,
                   'empty_prior_update_normalized':answer.get('mode')=='update' and not (previous or {}).get('tasks') and all(t.get('id') is None for t in answer.get('tasks',[]))}

def signature(f):return tuple(f[k] for k in ('field','operator','value'))

def to_delta(checklist,previous,question,reference_context=None):
    if not isinstance(checklist,dict):raise RequestInvalid('条件清单必须是JSON对象。')
    if checklist.get('version') in (9,10,11,12,13) and checklist.get('status') not in ('ready','unsupported'):
        raise RequestInvalid('V9不输出重复的全局clarify状态；完整任务的单位歧义由程序校验，其他缺失信息用unsupported并说明原因。')
    goal_required=checklist.get('version')==13
    purpose_required=checklist.get('version') in (10,11,12,13)
    explicit_execution=checklist.get('version') in (5,6,7,8,9,10,11,12,13)
    checklist=resolve_sources(checklist,question,reference_context)
    from business_request import require_keys
    def require(ok,msg):
        if not ok:raise RequestInvalid(msg)
    require(isinstance(checklist,dict) and set(checklist)=={'status','mode','tasks','clarification'},'条件清单结构错误。')
    require(checklist['status'] in ('ready','clarify','unsupported') and checklist['mode'] in ('new','update'),'条件清单状态错误。')
    require(isinstance(checklist['clarification'],str) and len(checklist['clarification'])<=1000,'澄清内容错误。')
    if checklist['status']=='unsupported':
        require(checklist['tasks']==[] and checklist['clarification'],'不支持的条件不能执行。')
        return None
    require(isinstance(checklist['tasks'],list) and 1<=len(checklist['tasks'])<=4,'条件清单任务数错误。')
    old={t['id']:t for t in (previous or {}).get('tasks',[])};patches=[]
    # 是否续接对话与是否已有查询任务是两个独立判断；
    # 没有旧任务和被引用编号时，new/update 的状态效果相同。
    mode=checklist['mode']
    if mode=='update' and not old and all(isinstance(t,dict) and t.get('id') is None for t in checklist['tasks']):
        mode='new'

    for task in checklist['tasks']:
        task=copy.deepcopy(task)
        request_quote=task.pop('request_quote',None)
        if task.get('operation')=='retain':
            require_keys(task,{'id','execute','quote','operation'},'retain清单')
            require(mode=='update' and task['id'] in old and task['execute'] is False and task['quote'] is None and request_quote is None,'retain只能原样引用已确认任务。')
            patches.append({'base':task['id'],'execute':False,'quote':None,'set':{},'filters':[]})
            continue
        if task.get('operation') in NOTE_OPERATIONS:
            require_keys(task,{'id','quote','operation','topics','execute'},'checklist说明任务')
            execute=task['execute'];q=task['quote'];base=old.get(task['id']) if mode=='update' else None
            require(type(execute) is bool and isinstance(q,str) and q and q in question,'说明任务的执行或原话无效。')
            require(bool(base) if mode=='update' else task['id'] is None,'说明任务引用错误。')
            replacing=bool(base and base['operation'] not in NOTE_OPERATIONS)
            fields={k:copy.deepcopy(task[k]) for k in ('operation','topics') if replacing or not base or task[k]!=base.get(k)}
            require(execute or base and not fields and not replacing,'不执行的说明必须保持原样。')
            patch={'base':task['id'],'quote':q,'set':fields,'filters':[],'execute':execute}
            if request_quote is not None:patch['request_quote']=request_quote
            if replacing:patch.update(replace_task=True,retain_filters=[])
            patches.append(patch)
            continue
        require_keys(task,{'id','quote','operation','target','properties','unit','conditions'}|({'execute'} if explicit_execution else set())|({'purpose','subject_scope'} if purpose_required else set())|({'scope'} if task.get('operation') in ('parts','descendants') else set())|({'population'} if task.get('operation')=='descendants' else set())|({'result_goal'} if goal_required and task.get('operation') in ('search','attributes') or 'result_goal' in task else set()),'checklist.tasks[]（clarification仅放在顶层）')
        execute=task.get('execute',True)
        require(type(execute) is bool,'execute必须是布尔值。')
        q=task['quote'];require(isinstance(q,str) and q and q in question,'任务缺少本轮原话。')
        base=old.get(task['id']) if mode=='update' else None
        require(bool(base) if mode=='update' else task['id'] is None,'条件清单任务引用错误；mode='+mode+'；有效旧任务id='+json.dumps(list(old))+'；update必须引用一个有效旧任务，new的id必须null。')
        from object_scope import is_domain_draft
        completing_domain=is_domain_draft(previous,base) and task.get('purpose')=='introduction' and task.get('subject_scope')=='explicit'
        replacing=bool(base and not completing_domain and (base['operation'] in NOTE_OPERATIONS or task['target']!=base['target'] or (task['operation'] in ('parts','descendants'))!=(base['operation'] in ('parts','descendants'))))
        fields={k:task[k] for k in (('operation','target','properties','scope','population') if task['operation']=='descendants' else ('operation','target','properties','scope') if task['operation']=='parts' else ('operation','target','properties')) if replacing or not base or task[k]!=base.get(k)}
        if 'result_goal' in task and (replacing or not base or task['result_goal']!=base.get('result_goal')):fields['result_goal']=copy.deepcopy(task['result_goal'])
        if not replacing and task['operation']=='search' and task['properties']==[]:fields.pop('properties',None)
        require(isinstance(task['conditions'],list) and len(task['conditions'])<=8,'条件清单数量错误。')
        unmatched={f['id']:f for f in base['filters']} if base else {};edits=[];seen=set();retained=[]
        for c in task['conditions']:
            require_keys(c,{'field','operator','value','quote'},'checklist.tasks[].conditions[]')
            require(all(isinstance(c[k],str) for k in ('field','operator','value')),'原子条件类型错误。')
            sig=signature(c);require(sig not in seen,'条件重复。');seen.add(sig)
            match=next((fid for fid,f in unmatched.items() if signature(f)==sig),None)
            if c['quote'] is None:
                require(match is not None,'继承条件与已确认状态不符。');unmatched.pop(match)
                if replacing:retained.append(match)
                continue
            require(isinstance(c['quote'],str) and c['quote'] and c['quote'] in question,'条件缺少本轮原话。')
            if match is not None:
                unmatched.pop(match)
                if replacing:retained.append(match)
                continue
            # 这里只匹配单个端点，存在歧义的条件删除另行处理。
            replace=[] if replacing else [fid for fid,f in unmatched.items() if f['field']==c['field'] and f['operator']==c['operator']]
            fid=replace[0] if len(replace)==1 else None
            if fid:unmatched.pop(fid)
            edits.append({'action':'replace' if fid else 'add','ids':[fid] if fid else [],'conditions':[{k:c[k] for k in ('field','operator','value')}],'quote':c['quote']})
        if unmatched and not replacing:edits.append({'action':'remove','ids':list(unmatched),'conditions':[],'quote':q})
        patch={'base':task['id'],'quote':q,'set':fields,'filters':edits}
        if request_quote is not None:patch['request_quote']=request_quote
        if replacing:patch.update(replace_task=True,retain_filters=retained)
        if replacing or not base or task['unit']!=base['unit']:patch['unit']=task['unit']
        if purpose_required:patch.update(purpose=task['purpose'],subject_scope=task['subject_scope'])
        if explicit_execution:patch['execute']=execute
        require(execute or base and not fields and not edits and not replacing and 'unit' not in patch,
                '不执行的任务必须完整保留原状态，不能同时修改字段、条件或单位。')
        patches.append(patch)
    return {'version':1,'mode':mode,'tasks':patches}

def compile_checklist(checklist,previous,question,store,reference_context=None):
    delta=to_delta(checklist,previous,question,reference_context)
    if delta is None:return None,None,[],None
    plan,state,changed=apply_delta(delta,previous,question,reference_context)
    if checklist['status']!='ready':raise RequestAmbiguous(checklist.get('clarification') or '独立清单尚有未明确条件。',state)
    state=ground_identifiers(store,state,changed)
    return compile_selected(state,changed,execution_quotes(delta)),state,changed,delta

def canonical_tasks(state,changed,store):
    from result_goal import default_goal
    """比较业务语义，忽略来源元数据、编号分配和 AND 条件顺序。"""
    from typed_fields import decimal_value,canonical_unit,NUMERIC_OPS,NUMERIC_FIELDS
    from query_filters import TARGETS
    result=[]
    for tid in changed:
        t=next(t for t in state['tasks'] if t['id']==tid);fs=[]
        if t['operation'] in NOTE_OPERATIONS:
            result.append({'task_id':tid,'operation':t['operation'],'topics':sorted(t['topics'])})
            continue
        for f in t['filters']:
            field,op,value=signature(f)
            if t['target']=='points' and field in NUMERIC_FIELDS and op=='equals':op='eq_num'
            if op in NUMERIC_OPS:value=str(decimal_value(value).normalize())
            if field=='unit' and op=='equals':value=canonical_unit(value)
            if field in ('identity','name','code') and op=='equals':
                cols=['name','code'] if field=='identity' else [field]
                table='points' if t['target']=='points' else 'objects';where=' OR '.join(c+'=?' for c in cols);args=[value]*len(cols)
                if table=='objects':
                    tree,level=TARGETS[t['target']]
                    if tree!='*':where='('+where+') AND tree=?';args.append(tree)
                    if level:where+=' AND level=?';args.append(level)
                identity='line' if table=='points' else 'tree'
                rows=store.rows('SELECT DISTINCT '+identity+',code FROM '+table+' WHERE '+where,args)
                if rows:field='resolved_identity';value=json.dumps(sorted((r[identity],r['code']) for r in rows),ensure_ascii=False)
                elif t['operation']=='attributes':
                    from identity_candidates import suggestion_signature
                    suggestion=suggestion_signature(store,t['target'],field,value)
                    if suggestion:field='unresolved_identity_suggestion';value=suggestion
            fs.append((field,op,value))
        if t['target']=='points':
            from date_fields import canonical_year_filters
            fs=canonical_year_filters(fs,store)
        target=t['target']
        # 跨树精确身份定位只有命中唯一原对象时，才与其实际树等价。
        # 不改变执行计划；多对象、列表、额外筛选仍保留原域差异。
        props=set(t['properties']);goal=t.get('result_goal',default_goal(t['operation']))
        if (target=='objects' and t['operation']=='attributes' and
                t['sources'].get('purpose',{}).get('value')=='identity' and
                {'name','code'}<=props<={'name','code','type','level','parent'} and
                goal.get('kind')=='attributes' and len(fs)==1 and
                fs[0][0]=='resolved_identity' and fs[0][1]=='equals'):
            identities=json.loads(fs[0][2])
            if len(identities)==1 and identities[0][0] in ('pbs','config','equipment_class','part_class'):
                target=identities[0][0]
        result.append({'task_id':tid,'operation':t['operation'],'target':target,'scope':t['scope'],**({'population':t['population']} if t['operation']=='descendants' else {}),'properties':sorted(t['properties']),
                       'filters':sorted(fs),'unit':t['unit'],'result_goal':({'native_descendants':'records_and_count'} if t['operation']=='descendants' else copy.deepcopy(t.get('result_goal',default_goal(t['operation'])))),'purpose':t['sources'].get('purpose',{}).get('value','data')})
    return result

def reconcile(candidate,changed,independent,independent_changed,store):
    a=canonical_tasks(candidate,changed,store);b=canonical_tasks(independent,independent_changed,store)
    return {'matches':a==b,'candidate':a,'independent':b}

def transition_facts(previous, requested, mode):
    """区分本轮实际执行的任务与完整保留的请求状态。"""
    if mode not in ('new','update') or not isinstance(requested,list):
        raise RequestInvalid('状态转换输入无效。')
    before=prior_view(previous)
    after=copy.deepcopy(before) if mode=='update' else []
    updates=prior_view({'tasks':requested})
    for task in updates:
        index=next((i for i,t in enumerate(after) if t['id']==task['id']),None)
        if index is None:after.append(task)
        else:after[index]=task
    executed=[t['id'] for t in updates]
    return {'executed_task_ids':executed,
            'preserved_without_execution':[t['id'] for t in after if t['id'] not in executed],
            'state_after':after}


def adjudicate(question,previous,comparison,candidate_mode,independent_mode,model,store=None,reference_context=None):
    from model import NoRedirect,ENDPOINT
    from attributes import CATALOG
    from business_request import review_semantics
    def semantics(tasks):
        if not isinstance(tasks,list):return None
        return review_semantics({'tasks':tasks},[t['id'] for t in tasks])
    body={'model':model,'messages':[
      {'role':'system','content':(ROOT/'prompts/system/request-reconcile-v3.txt').read_text(encoding='utf-8')+'\n业务目录：'+json.dumps(business_catalog(store),ensure_ascii=False)},
      {'role':'user','content':json.dumps({'question':question,'segments':source_segments(question),'prior':prior_view(previous),
        'reference_context':reference_context,'literal_references':literal_references(question,store),
        'computed_semantics':{'candidate':semantics(comparison['candidate']),'independent':semantics(comparison['independent'])},
        'transition_facts':{'candidate':transition_facts(previous,comparison['candidate'],candidate_mode),'independent':transition_facts(previous,comparison['independent'],independent_mode)},
        'candidate':{'mode':candidate_mode,'tasks':comparison['candidate']},'independent':{'mode':independent_mode,'tasks':comparison['independent']}},ensure_ascii=False)}],
      'response_format':{'type':'json_object'},'thinking':{'type':os.environ.get('ICCM_RECONCILE_THINKING','disabled')},'max_tokens':4096,'stream':False}
    if body['thinking']['type']=='enabled':body['reasoning_effort']=os.environ.get('ICCM_CHECKLIST_EFFORT','low')
    else:body['temperature']=0
    req=urllib.request.Request(ENDPOINT,data=json.dumps(body,ensure_ascii=False).encode(),headers={'Authorization':'Bearer '+os.environ.get('DEEPSEEK_API_KEY',''),'Content-Type':'application/json'},method='POST')
    start=time.monotonic()
    with urllib.request.build_opener(NoRedirect).open(req,timeout=60) as response:raw=json.load(response)
    choice=raw['choices'][0]
    if choice.get('finish_reason')!='stop':raise RequestInvalid('分歧裁决未完整结束。')
    verdict=json.loads(choice['message']['content']);ids={s['id'] for s in source_segments(question)}
    if not isinstance(verdict,dict) or set(verdict)!={'choice','spans','reason'} or verdict['choice'] not in ('candidate','independent','clarify'):raise RequestInvalid('分歧裁决超出选择权限。')
    if not isinstance(verdict['spans'],list) or not verdict['spans'] or any(type(i)!=int or i not in ids for i in verdict['spans']):raise RequestInvalid('分歧裁决缺少原话依据。')
    if not isinstance(verdict['reason'],str) or not 0<len(verdict['reason'])<=500:raise RequestInvalid('分歧裁决缺少具体说明。')
    return {**verdict,'model':raw.get('model'),'usage':raw.get('usage'),'seconds':round(time.monotonic()-start,3)}

def gate(question,previous,candidate,changed,mode,store,reference_context=None):
    """不静默改写：一致则通过，分歧则受限选择完整请求或不执行。"""
    model=os.environ.get('ICCM_CHECKLIST_MODEL','deepseek-v4-pro')
    thinking=os.environ.get('ICCM_CHECKLIST_THINKING','disabled')
    pending=getattr(_ASYNC,'pending',None)
    if pending and pending[0]==extraction_key(question,previous,reference_context):
        _ASYNC.pending=None;start=time.monotonic();answer,trace=pending[1].result()
        trace.update(prefetched=True,wait_seconds=round(time.monotonic()-start,3))
    else:answer,trace=extract(question,previous,thinking,model,store=store,reference_context=reference_context)
    ambiguity=None
    try:plan,state,ids,delta=compile_checklist(answer,previous,question,store,reference_context)
    except RequestAmbiguous as error:
        ambiguity=error;plan=None;state=error.state;ids=(state or {}).get('last_executed_tasks',[]);delta=None
    except (ValueError,TypeError,KeyError) as error:
        return {'decision':'clarify','reason':'独立条件清单未通过校验，请补充或重述条件。','extraction':trace,'error':str(error)}
    if plan is None:
        if answer['status']=='unsupported':
            return {'decision':'clarify','choice':'clarify','reason':answer['clarification'],'extraction':trace,'capability_rejected':True}
        from relationship_request import reviewable_draft
        from object_scope import reviewable_domain_draft
        relationship_review=mode==answer.get('mode') and reviewable_draft(candidate,changed,state,ids,store)
        domain_review=mode==answer.get('mode') and reviewable_domain_draft(candidate,changed,state,ids,store)
        if domain_review:
            # 用户已在完整标识之外给出对象域词；
            # 模型漏提该词时，不能要求用户重复提供。
            from object_scope import explicit_domain
            if all(explicit_domain(question,t['target'],reference_context) for t in candidate['tasks'] if t['id'] in changed):
                return {'decision':'accept','choice':'candidate','extraction':trace,'explicit_domain_evidence':True}
        # 模型投票不能豁免执行所需前置条件；
        # 保留未提交草稿，让下一次补答可以继续解决。
        out={'decision':'clarify','choice':'clarify','requires_clarification':True,
             'reason':str(ambiguity) if ambiguity else answer['clarification'],
             'extraction':trace}
        if state:out['pending_state']=state
        if relationship_review or domain_review:
            from semantic_review import describe_disagreement
            out['semantic_review']=describe_disagreement(request_view(candidate,changed),request_view(state,ids),mode,answer['mode'],True)
        return out
    from request_gateway import validate_categories
    candidate_error=independent_error=None
    try:validate_categories(candidate,changed,store)
    except RequestInvalid as error:candidate_error=str(error)
    try:validate_categories(state,ids,store)
    except RequestInvalid as error:independent_error=str(error)
    if candidate_error or independent_error:
        out={'decision':'clarify','choice':'clarify','extraction':trace,'reason':candidate_error or independent_error,
             'constraint_errors':{'candidate':candidate_error,'independent':independent_error}}
        if candidate_error and not independent_error:
            out.update(decision='accept',choice='independent',plan=plan,state=state,changed=ids,delta=delta)
        # 独立解释无效时，不能据此认证候选方案。
        return out
    comparison=reconcile(candidate,changed,state,ids,store)
    same_future=canonical_tasks(candidate,[t['id'] for t in candidate['tasks']],store)==canonical_tasks(state,[t['id'] for t in state['tasks']],store)
    comparison['same_future_state']=same_future
    comparison['matches']=comparison['matches'] and (mode==answer['mode'] or same_future)
    out={'decision':'accept' if comparison['matches'] else 'clarify','choice':'candidate','extraction':trace,'comparison':comparison}
    if comparison['matches']:return out
    # 默认快照投影与单条测点列表输出同一事实；其他结果动作不可用此例外。
    ca,cb=comparison['candidate'],comparison['independent']
    if len(ca)==len(cb)==1 and mode==answer['mode']:
        a,b=ca[0],cb[0];kinds={a.get('result_goal',{}).get('kind'),b.get('result_goal',{}).get('kind')}
        rows=[t for t in (a,b) if t['operation']=='search' and not t['properties']]
        attrs=[t for t in (a,b) if t['operation']=='attributes' and set(t['properties'])=={'value','unit','source','time','physical_quantity'}]
        strip=lambda t:{k:v for k,v in t.items() if k not in ('operation','properties','result_goal')}
        unique=(len(a.get('filters',[]))==1 and a['filters'][0][0]=='resolved_identity' and len(json.loads(a['filters'][0][2]))==1)
        if kinds=={'records','attributes'} and rows and attrs and a['target']=='points' and unique and strip(a)==strip(b):
            choice='candidate' if a['operation']=='attributes' else 'independent'
            out.update(decision='accept',choice=choice,native_snapshot_projection=True)
            if choice=='independent':out.update(plan=plan,state=state,changed=ids,delta=delta)
            return out
    # 两种身份用途均已通过各自的对象域前置检查。
    if comparison['candidate'] and len(comparison['candidate'])==len(comparison['independent']):
        normalize=lambda tasks:[{**t,'purpose':'identity'} if t.get('purpose') in ('identity','introduction') else t for t in tasks]
        if normalize(comparison['candidate'])==normalize(comparison['independent']) and mode==answer['mode']:
            out.update(decision='accept',choice='candidate',identity_purpose_equivalence=True)
            return out
    # 旧属性适配器没有用途槽位；若两份已校验计划指向
    # 完全相同的对象及投影，保留完整的类型化请求。
    ca,cb=comparison['candidate'],comparison['independent']
    legacy=[t for t in candidate['tasks'] if t['id'] in changed]
    if len(ca)==len(cb)==len(legacy) and all(not t['sources'].get('purpose') for t in legacy):
        strip=lambda tasks:[{k:v for k,v in t.items() if k!='purpose'} for t in tasks]
        if strip(ca)==strip(cb) and all(t['operation']=='attributes' and t['purpose']=='identity' for t in cb):
            out.update(decision='accept',choice='independent',plan=plan,state=state,changed=ids,delta=delta,
                       legacy_identity_equivalence=True)
            return out
    # 读取来源是展示上下文，不是不同的业务筛选条件。
    # 只能选择已有的完整建议，不能删除用户所问字段，
    # 也不能拼接或合并条件；其他投影差异仍需澄清。
    ca,cb=comparison['candidate'],comparison['independent']
    if len(ca)==len(cb):
        directions=[];proven_projection_ids=set()
        for left,right in zip(ca,cb):
            x,y=copy.deepcopy(left),copy.deepcopy(right)
            xp,yp=set(x.pop('properties',[])),set(y.pop('properties',[]))
            optional={'source','time','physical_quantity'}
            point_context=x.get('target')=='points' and {'value','unit'}<=xp&yp and not (xp^yp)-optional
            identity_context={'name','code'}<=xp&yp and not (xp^yp)-{'type','level','parent'} and x.get('purpose') in ('data','identity','introduction') and y.get('purpose') in ('data','identity','introduction')
            if identity_context:x['purpose']=y['purpose']='identity'
            if x!=y or x['operation']!='attributes' or not (point_context or identity_context):
                directions=[];break
            proven_projection_ids.add(x['task_id'])
            if xp<yp:directions.append('independent')
            elif yp<xp:directions.append('candidate')
        # 只归一已逐项证明的上下文元数据投影；完整整组状态仍须一致。
        # new删掉未提及分支时不能因为当前答案相同而通过。
        projection_future=False
        if directions and len(set(directions))==1:
            normalize=lambda tasks:[{**t,'properties':[]} if t['task_id'] in proven_projection_ids else t for t in tasks]
            projection_future=normalize(canonical_tasks(candidate,[t['id'] for t in candidate['tasks']],store))==normalize(canonical_tasks(state,[t['id'] for t in state['tasks']],store))
        if directions and len(set(directions))==1 and (mode==answer['mode'] or projection_future):
            choice=directions[0]
            out.update(decision='accept',choice=choice,provenance_projection=True,
                       proven_projection_future_state=projection_future)
            if choice=='independent':out.update(plan=plan,state=state,changed=ids,delta=delta)
            return out
    requests={'candidate':request_view(candidate,changed),'independent':request_view(state,ids)}
    from endpoint_review import prepare,adjudicate as review_endpoint
    endpoints=prepare(question,comparison,requests) if os.environ.get('ICCM_ENDPOINT_REVIEW','0')=='1' and (mode==answer['mode'] or same_future) else None
    if endpoints is None:
        # 模型投票不能提供独立业务证据；保留两份有效解释，
        # 等待用户明确确认查询计划。
        if not any(t['operation'] not in NOTE_OPERATIONS for t in requests['candidate']):
            out.update(choice='clarify',reason='对本轮应交付的说明存在分歧，请明确需要的内容。')
            return out
        from semantic_review import business_question,describe_disagreement
        out.update(decision='clarify',choice='clarify',requires_clarification=True,
                   reason=business_question(requests['candidate'],requests['independent'],mode,answer['mode'],comparison),
                   pending_state=copy.deepcopy(candidate),
                   semantic_review=describe_disagreement(requests['candidate'],requests['independent'],mode,answer['mode'],same_future))
        from clarification_state import make_slot
        slot=make_slot(requests['candidate'],requests['independent'],comparison)
        if slot:out['pending_slot']=slot
        return out
    verdict=review_endpoint(question,endpoints,model)
    out['adjudication']=verdict
    out['choice']=verdict['choice'];out['reason']=verdict['reason']
    if verdict['choice']=='clarify':return out
    out['decision']='accept'
    if verdict['choice']=='independent':out.update(plan=plan,state=state,changed=ids,delta=delta)
    return out
