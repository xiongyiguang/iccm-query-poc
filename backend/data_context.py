"""基于原始依据构建上下文及完整集合摘要，不依赖用户措辞。"""
import json
from collections import Counter

DOMAIN_FACTS={
 'provenance':'原始CSV已脱敏，导入器保留原值；不能说名称由本系统在导入时替换，也不知道客户脱敏的具体过程。',
 'objects':'PBS包含功能位置、设备、部件和时序测点等现场对象。构型是结构和分类层级，设备类/部件类是字典。分类条数不是设备台数，不能相加。',
 'references':'记录中可以保留父对象编码，而本次导入数据未包含该父对象的详细记录。这时可以展示父编码，但无法确定其名称和类型；这与原记录没有填写父编码是两种情况。',
 'quality':'1970年时间可能是源系统默认值或占位值，具体原因未经客户确认。原值保留，不能当作可信报警开始时间。名称代码和单位都不足以定义所测物理量。',
 'alarm':'已报警仅按状态；开启且已报警额外要求开启。没有报警不等于健康。原始报警原因是记录文本，可以查询并结合阈值作数值比较，但不是故障根因或完整报警算法。',
 'architecture':['交互展示层：输入、对象选择、表格图表和依据','会话与任务编排层：保存对象与筛选，组织独立任务和澄清','语义解析层：DeepSeek结合上下文产生受约束意图，统计另作复核','查询与计算层：程序参数化查表、关联、统计和计算，不执行模型自由SQL','数据与证据层：五份导入CSV快照，保留原字段、文件和行号'],
 'limits':'未接入实时监测或RAG行业知识库；无连续历史序列、可靠报警事件起止或寿命预测资料，不提供故障诊断及维修决策。'
}

TOPICS={'provenance':'名称脱敏与导入','objects':'数据对象与分类','references':'父引用与缺失详情',
        'quality':'时间与物理量解释边界','alarm':'报警含义与诊断边界','architecture':'系统职责与数据流',
        'limits':'当前能力边界','counts':'数量口径对照','coverage':'测点关联覆盖'}

STATIC_TOPICS={k:v for k,v in TOPICS.items() if k not in ('counts','coverage')}

def static_facts(store):
    facts=dict(DOMAIN_FACTS)
    if any(not f.get('seed') for f in store.dataset):facts['provenance']='当前包含现场导入文件，系统保留其原始字段值；是否脱敏及处理过程需以文件提供方说明为准。'
    return facts

def validate_topics(intent):
    topics=intent.get('topics')
    if intent.get('operation')!='explain':
        if topics is not None:raise ValueError('非说明操作不能携带说明主题。')
        return
    if (intent.get('entity') is not None or any(intent.get(k) is not None for k in ('query','analysis','properties','message')) or
        not isinstance(topics,list) or not 1<=len(topics)<=5 or any(not isinstance(t,str) or t not in TOPICS for t in topics) or len(set(topics))!=len(topics)):
        raise ValueError('说明主题必须来自已核实目录，不能附加未核实消息或对象筛选。')

def explain(store,intent):
    validate_topics(intent)
    facts=knowledge_context(store) if any(t in ('counts','coverage') for t in intent['topics']) else {'facts':static_facts(store)}
    records=[]
    for topic in intent['topics']:
        if topic=='counts':
            text='当前PBS共有 '+str(facts['tree_counts']['pbs'])+' 条对象，其中功能位置 '+str(facts['pbs_function_locations'])+' 条。功能位置只是PBS的一部分；设备构型与分类字典属于不同统计口径，不能跨表相加当设备总量。'
        elif topic=='coverage':
            c=facts['point_to_pbs'];text=f"本次有 {c['total_records']} 条测点记录，其中 {c['matched_records']} 条按编码匹配PBS，{c['unmatched_records']} 条未匹配。"+c['meaning']
        else:
            value=facts['facts'][topic];text='；'.join(value)+'。' if isinstance(value,list) else value
        records.append({'cells':[TOPICS[topic],text]})
    return dict(answer='；'.join(r['cells'][1] for r in records),status='conversation',entity=None,scope='direct',
        records=[],columns=[],metrics=[],path=[],evidence=[],
        note='概念说明依据已核对字段及实现职责；数量由本次导入库计算。不是RAG行业知识检索，未经确认的来源原因不作断言。',explanation_topics=intent['topics'])

def point_summary(records):
    raw=[r['evidence']['fields'] for r in records]
    states=Counter(r.get('状态','') or '未提供' for r in raw)
    return {'records':len(raw),'with_value':sum(bool(str(r.get('测量值','')).strip()) for r in raw),
            'states':dict(states),'reasons':dict(Counter(r['报警原因'] for r in raw if r.get('报警原因'))),'grain':'原始记录，未去重'}

def summary_text(summary):
    states=summary['states']
    text=(f"其中 {summary['with_value']} 条提供测量值；已报警 {states.get('已报警',0)} 条，"
            f"未报警 {states.get('未报警',0)} 条，状态未提供 {states.get('未提供',0)} 条。")
    if 0<len(summary['reasons'])<=5:
        text+='原始报警原因文本：'+'；'.join(k+' '+str(v)+'条' for k,v in summary['reasons'].items())+'；不等于设备故障根因。'
    return text

def knowledge_context(store):
    counts=store.rows('SELECT tree,level,count(*) n FROM objects GROUP BY tree,level')
    totals={k:0 for k in ('pbs','config','equipment_class','part_class')}
    for row in counts:totals[row['tree']]=totals.get(row['tree'],0)+row['n']
    coverage=store.rows("SELECT count(*) total,coalesce(sum(EXISTS(SELECT 1 FROM objects o WHERE o.tree='pbs' AND o.code=p.code)),0) matched FROM points p")[0]
    domain=static_facts(store)
    return {'sources':'对象层级计数来自objects；测点关联覆盖来自points与PBS同码连接；概念说明来自已核对项目字段及实现职责。',
            'data_version':store.version,'facts':domain,'tree_counts':totals,
            'pbs_function_locations':sum(r['n'] for r in counts if r['tree']=='pbs' and r['level']=='功能位置'),
            'count_semantics':'tree_counts是每棵树完整行数。功能位置是PBS的一部分，200不是PBS总量。不同树之间不可相加当设备总量；同一树各互斥层级行数可由程序加总，模型不自行计算。',
            'point_to_pbs':{'total_records':coverage['total'],'matched_records':coverage['matched'],
                            'unmatched_records':coverage['total']-coverage['matched'],
                            'meaning':'仅测点编码与PBS对象代码精确关联，不等于所有记录均归属设备或部件。'}}
