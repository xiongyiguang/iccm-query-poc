"""原话义务与最终请求覆盖：不读取模型角色、候选引文或查询结果。

有界语法只消费登记字段及明确条件/控制。来源偏移和未覆盖义务保留，
规则无法可靠解析的显式条件拒绝执行；不自动修补模型计划。
"""
import copy
import re
import weakref
import threading
from datetime import datetime
from attributes import CATALOG
from business_request import RequestInvalid
from date_fields import TIMEZONE, calendar_period, parse_time, canonical_time_filters, canonical_year_filters
from typed_fields import NUMERIC_FIELDS, decimal_value, canonical_unit, UNIT_ALIASES


class CoverageInvalid(RequestInvalid):
    def __init__(self, report):
        self.report = report
        labels = list(dict.fromkeys(x['text'] for x in report['obligations'] if not x['covered']))
        super().__init__('原话要求尚未完整核验：'+'；'.join(labels[:4])+'。请确认这些条件；尚未执行查询。')


ALIASES = {k: {v['label'], *v['fields'].values()} for k, v in CATALOG.items()}
for k, words in {'source': ['来源'], 'time': ['时间'], 'status': ['状态'],
                 'switch': ['开关状态'], 'name': ['名称'], 'code': ['编码'],
                 'level': ['对象层级'], 'class_code': ['部件类代码']}.items():
    ALIASES[k].update(words)
TOKENS = {word: k for k, words in ALIASES.items() for word in words}
FIELD = '|'.join(map(re.escape, sorted(TOKENS, key=len, reverse=True)))
OPS = {'大于等于': 'gte', '不小于': 'gte', '至少': 'gte', '小于等于': 'lte',
       '不大于': 'lte', '不超过': 'lte', '至多': 'lte', '大于': 'gt', '超过': 'gt',
       '小于': 'lt', '低于': 'lt', '不包含': 'not_contains', '包含': 'contains',
       '以': 'starts_with', '等于': 'equals', '为': 'equals', '是': 'equals',
       '不早于': 'date_gte', '早于': 'date_lt', '在': 'date_equals'}
OPS.update({'>=':'gte','<=':'lte','>':'gt','<':'lt','=':'equals','≥':'gte','≤':'lte'})
OP = '|'.join(map(re.escape, sorted(OPS, key=len, reverse=True)))
DATE = r'(?:[12]\d{3}(?:(?:[-/]\d{1,2})(?:[-/]\d{1,2})?|年(?:\d{1,2}月(?:\d{1,2}日)?)?)?(?:\s+\d{1,2}:\d{2}(?::\d{2})?)?|今年|去年)'
NUMBER = r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?'

def _value_end(tail):
    """完整类型值只能接句界、连词或查询目标；不吞掉未知单位/修饰。"""
    tail=tail.lstrip()
    if re.match(r'(?:及|和|并|或)?(?:以上|以下|以内|以外|以后|以前|之后|之前|以来|左右|月末|月底|年末|年底|初|中|末|底)',tail):return False
    return not tail or bool(re.match(r'[，,。；;、!?？！:：“”"」』`）)\]]|并且|而且|且|并|及|以及|同时|的|条件|筛选|限制|过滤|测点|记录|原行|原记录|数据|监测|列出|返回|输出|显示|保留|统计|计数|查询|查|取|只',tail))
TREE_WORDS = {'config': ['构型树', '构型'], 'pbs': ['PBS树', 'PBS'],
              'equipment_class': ['设备类表', '设备类字典'], 'part_class': ['部件类表', '部件类字典'],
              'points': ['监测表', '测点表']}
TREE = {w: t for t, ws in TREE_WORDS.items() for w in ws}
_VALUES=weakref.WeakKeyDictionary()
_VALUES_LOCK=threading.Lock()


def condition_values(store):
    if store is None:return {}
    with _VALUES_LOCK:
        try:cached=_VALUES.get(store);cacheable=True
        except TypeError:cached=None;cacheable=False
        if cached and cached[0]==store.version:return cached[1]
        values={field:[r['value'] for r in store.rows('SELECT DISTINCT '+column+' AS value FROM points WHERE '+column+"!='' AND length("+column+')<=300',[])]
                for field,column in [('source','system'),('status','status'),('switch','switch'),('unit','unit')]}
        if cacheable:_VALUES[store]=(store.version,values)
        return values


def views(plan):
    """各种规划协议投影到同一检查视图；只看编译后的执行参数。"""
    if plan.get('operation') == 'batch':
        result=[v for t in plan['tasks'] for v in views(t['intent'])]
        for i,v in enumerate(result,1):v['ordinal']=i
        return result
    if plan.get('operation') == 'relational':
        return [dict(copy.deepcopy(t['spec']), operation='relational', ordinal=t['id'],
                     target=t['spec'].get('target_tree') or (t['spec'].get('root') or {}).get('tree'),
                     goal={}, analysis={}) for i, t in enumerate(plan['relational_tasks'], 1)]
    q = plan.get('query') or {}
    root = plan.get('entity')
    return [dict(operation=plan.get('operation'), ordinal=1, root=({'tree':root['tree'], 'field':'code', 'value':root['code']} if root else None),
                 target=q.get('target'), filters=q.get('filters', []), classes={}, depth=plan.get('scope'),
                 population='parts' if plan.get('operation') == 'parts' or q.get('target')=='parts' else 'devices' if q.get('target')=='equipment' else None,
                 group_by=(plan.get('analysis') or {}).get('group_by'),
                 properties=plan.get('properties', []), goal=plan.get('result_goal') or {},
                 analysis=plan.get('analysis') or {}, limit=None, sort=[])]


def _literal(value):
    return value.strip().strip('“”"「」『』`').strip()


def _field_condition(text):
    unary=re.match(r'('+FIELD+r')\s*(?:必须|需)?\s*(不为空|非空|为空|未提供|已提供|缺失)',text)
    if unary:return {'field':TOKENS[unary[1]],'operator':'not_blank' if unary[2] in ('不为空','非空','已提供') else 'is_blank','value':''},unary.end()
    changes=r'改为|改成|调整为|换成|换为|替换为|更改为|保持为'
    middle=r'\s*(?:的)?(?:条件|筛选|限制)?\s*(?:'+changes+r')?\s*'
    m = re.match(r'('+FIELD+r')'+middle+r'(?:必须|应当|需|要)?\s*('+OP+r')\s*(.*)', text)
    if m:field,op,rest,value_start=TOKENS[m[1]],OPS[m[2]],m[3],m.start(3)
    else:
        m=re.match(r'('+FIELD+r')\s*(?:的)?(?:条件|筛选|限制)?\s*(?:'+changes+r'|设为)\s*(.*)',text)
        if not m:return None
        field,op,rest,value_start=TOKENS[m[1]],'equals',m[2],m.start(2)
    blank=re.match(r'(?:空(?:值)?|未提供|未填写|缺失)(?!的?意思|含义)',rest)
    if op=='equals' and blank:return {'field':field,'operator':'is_blank','value':''},value_start+blank.end()
    if field == 'time' and op not in ('contains','not_contains','starts_with'):
        d = re.match(DATE, rest)
        if not d: return None
        value = d[0]
        if re.match(r'\s*(?:到|至|之间|以内|以后|以前|以来)',rest[d.end():]):return None
        if value in ('今年', '去年'):
            value = str(datetime.now(TIMEZONE).year-(value == '去年'))
        else:
            value = value.replace('年','-').replace('月','-').replace('日','').rstrip('-')
            date=re.match(r'([12]\d{3})(?:[-/](\d{1,2}))?(?:[-/](\d{1,2}))?(.*)',value)
            value=date[1]+('-%02d'%int(date[2]) if date[2] else '')+('-%02d'%int(date[3]) if date[3] else '')+date[4]
        if not parse_time(value) and not calendar_period(value): return None
        end=d.end();period=calendar_period(value)
        if period:
            suffixes={1:r'全年|之内|内',2:r'份|整月|全月|之内|内',3:r'当天|整天|全天|之内|内'}[len(value.split('-'))]
            suffix=re.match(r'\s*(?:'+suffixes+r')',rest[end:])
            if suffix:end+=suffix.end()
        if not _value_end(rest[end:]):return None
        temporal={'equals':'date_equals','date_equals':'date_equals','gte':'date_gte','lt':'date_lt','date_gte':'date_gte','date_lt':'date_lt'}.get(op)
        if temporal is None:return None
        if temporal!='date_equals' and calendar_period(value):value=calendar_period(value)[0].isoformat()
        return {'field':field, 'operator':temporal, 'value':value}, value_start+end
    if field in NUMERIC_FIELDS and op in ('gt','gte','lt','lte','equals'):
        n = re.match(NUMBER, rest)
        if not n: return None
        tail=rest[n.end():].lstrip();unit=None;end=n.end()
        if re.match(r'万|千|百|亿|约|左右|到|至|倍',tail):return None
        for alias in sorted(UNIT_ALIASES,key=len,reverse=True):
            if tail.startswith(alias):unit=canonical_unit(alias);end=len(rest)-len(tail)+len(alias);break
        if re.match(r'[A-Za-z℃°%]',tail) and unit is None:return None
        if not _value_end(rest[end:]):return None
        c={'field':field, 'operator':'eq_num' if op == 'equals' else op, 'value':n[0]}
        if unit:c['unit']=unit
        return c, value_start+end
    if op not in ('equals','contains','not_contains','starts_with'): return None
    quoted = re.match(r'[“"「『`]([^”"」』`]+)[”"」』`]', rest)
    if rest.startswith(('“','"','「','『','`')) and not quoted:return None
    if quoted: value=quoted[1]; end=quoted.end()
    else:
        value=re.split(r'\s*(?:并且|而且|且|并|同时|及|以及|的(?:测点|记录|设备|部件)|，|,|。|；|;|[？?！!])',rest,1)[0].strip()
        value=re.sub(r'(?:开头|结尾)$','',value).strip();end=len(value)
    if not value or value in ('什么','多少','哪个','哪些','啥','否','什么对象'): return None
    if field=='time' and not quoted and re.fullmatch(r'[12]\d{3}年',value):value=value[:-1]
    return {'field':field, 'operator':op, 'value':_literal(value)}, value_start+end


def obligations(question, store=None, context=None):
    out=[]; protected=[]
    chunks=list(re.finditer(r'(?:“[^”]*”|"[^"]*"|「[^」]*」|『[^』]*』|`[^`]*`|[^，,。；;！？!?])+',question))
    def add(kind, value, start, end, ordinal=None):
        out.append({'kind':kind, 'expected':value, 'start':start, 'end':end,
                    'text':question[start:end], 'ordinal':ordinal})
    ordinal=None;block=0
    for chunk in chunks:
        text=chunk[0]
        number=re.search(r'第([一二三四1-4])(?:项|个任务)',text)
        if number:
            ordinal='一二三四'.index(number[1])+1 if number[1] in '一二三四' else int(number[1]);block+=1
        elif re.match(r'\s*(?:另外|另查|另一个(?:问题|查询)|第二个查询)',text):block+=1;ordinal=None
        initial=len(out)
        # 判断/解释/背景不能把提及的字段值变成筛选。明确筛选子句另行解析。
        surface=re.sub(r'“[^”]*”|"[^"]*"|「[^」]*」|『[^』]*』|`[^`]*`',lambda m:' '*len(m[0]),text)
        background=bool(re.match(r'\s*(?:之前|上次|原来|曾经|例如|比如|假设)',surface))
        explanation=bool(re.search(r'解释|什么是|如何|怎么|定义|含义|意思|区别|为什么',surface)) and not bool(re.search(r'查(?:询|找)?|筛选|限定|只看',surface))
        for m in re.finditer(FIELD,text):
            if background or explanation: continue
            if any(a<=chunk.start()+m.start()<b for a,b in protected): continue
            rest=text[m.start():]; parsed=_field_condition(rest)
            if parsed:
                condition,n=parsed;start=chunk.start()+m.start();end=start+n
                unit=condition.pop('unit',None)
                # 名称值/引用值中的数字和控制词不参与其他义务扫描。
                protected.append((start+len(m[0]),end))
                qualifier=text[max(0,m.start()-6):m.start()]
                if condition['field'] in ('name','code'):
                    for word,tree in [('设备类','equipment_class'),('部件类','part_class')]:
                        if qualifier.endswith(word):condition['field']=tree
                removal=bool(re.search(r'(?:取消|撤销|撤掉|去掉|移除|只撤掉)\s*[“"「『`]?(?:'+re.escape(m[0])+r')\s*$',text[:m.end()]))
                add('remove_filter' if removal else 'filter',condition,start,end,ordinal)
                if not removal and condition['field']=='time' and condition['operator']=='date_equals' and calendar_period(condition['value']) and re.search(r'改为|改成|调整为|换成|换为|替换为|更改为|设为',rest[:n]):
                    add('period_replace',copy.deepcopy(condition),start,end,ordinal)
                if unit and not removal:add('filter',{'field':'unit','operator':'equals','value':unit},start,end,ordinal)
            elif re.match(r'(?:'+FIELD+r')\s*(?:的)?(?:条件|筛选|限制)?\s*(?:改为|改成|调整为|换成|换为|替换为|更改为)?\s*(?:必须|应当|需|要)?\s*(?:'+OP+r'|介于|从|范围(?:为|是|从|在)|不等于|不是|晚于|不晚于|后于)',rest) and not re.search(r'为什|是什|是多少|为啥|是啥|是否|从新到旧|从旧到新|从早到晚|从晚到早|[从由]高到低|[从由]低到高',rest):
                add('unparsed',{'field':TOKENS[m[0]]},chunk.start()+m.start(),chunk.end(),ordinal)
        if background or explanation:continue
        # 原表有限值可表达省略字段的选择（如“只看开启的测点”）；
        # 值跨字段命中时保留歧义，不按模型选择猜字段。
        matches={}
        from identifier_aliases import complete_literal_pattern
        enum_needed=bool(re.search(r'只(?:看|查|要|取)|仅(?:看|查|保留)|限定|筛选|来自|(?:查|看|统计|列出).*(?:源系统|来源|报警状态|开关状态|开启|关闭).*?(?:测点|监测|原行|记录)',text))
        for field,values in (condition_values(store) if enum_needed else {}).items():
            for value in sorted(values,key=len,reverse=True):
                for m in re.finditer(complete_literal_pattern(value),text):
                    start=chunk.start()+m.start();end=chunk.start()+m.end()
                    if any(a<=start<b for a,b in protected):continue
                    prefix=text[:m.start()];suffix=text[m.end():]
                    if re.search(r'没有查到|未查到|查不到',prefix):continue
                    if re.fullmatch(NUMBER,value) and not any(prefix.rstrip().endswith(w) for w in ALIASES[field]):continue
                    if field=='unit' and not any(prefix.rstrip().endswith(w) for w in ALIASES[field]):continue
                    if not (re.search(r'只(?:看|查|要|取)|仅(?:看|查|保留)|限定|筛选|来自',prefix)
                            or re.search(r'查|看|统计|列出',prefix) and re.match(r'(?:的)?(?:测点|监测|原行|记录)',suffix)):continue
                    # 引用名称不提供枚举值条件，即便名称含有同样文字。
                    if re.search(r'名称|名字|名为',prefix) or prefix.count('“')>prefix.count('”'):continue
                    matches.setdefault((start,end,value),set()).add(field)
        for (start,end,value),fields in matches.items():
            if any(a<=start and end<=z and (a,z)!=(start,end) for a,z,_ in matches):continue
            if len(fields)==1:add('filter',{'field':next(iter(fields)),'operator':'equals','value':value},start,end,ordinal)
            else:add('unparsed',{'fields':sorted(fields)},start,end,ordinal)
        control=text
        for a,z in protected:
            a=max(a-chunk.start(),0);z=min(z-chunk.start(),len(text))
            if a<z:control=control[:a]+' '*(z-a)+control[z:]
        control=re.sub(r'“[^”]*”|"[^"]*"|「[^」]*」|『[^』]*』|`[^`]*`',lambda m:' '*len(m[0]),control)
        # 明确年月/日期片段也独立成时间义务；数据名称里的年份不作日期。
        if store is not None:
            from request_checklist import literal_references
            for ref in literal_references(text,store):
                if ref.get('field')=='name' and 'start' in ref and 'end' in ref:
                    a,z=ref['start'],ref['end'];control=control[:a]+' '*(z-a)+control[z:]
        for date in re.finditer(r'(?<![A-Za-z0-9_&.#-])'+DATE+r'(?![A-Za-z0-9_&.#-])',control):
            if not re.search(r'年|月|日|[-/]',date[0]):continue
            parsed=_field_condition('测量时间在'+control[date.start():])
            if parsed:
                cond,_=parsed
                prefix=control[:date.start()]
                if re.search(r'取消|撤销|去掉|移除|不要沿用|不沿用',prefix):
                    add('remove', 'time',chunk.start()+date.start(),chunk.start()+date.end(),ordinal)
                else:add('filter',cond,chunk.start()+date.start(),chunk.start()+date.end(),ordinal)
            else:add('unparsed',{'field':'time'},chunk.start()+date.start(),chunk.end(),ordinal)
        # 未登记字段或尚未支持的比较不能被两模型共同丢成无条件查询。
        for m in re.finditer(r'大于等于|小于等于|不超过|不小于|大于|小于|超过|不等于|等于|>=|<=|>|<|≥|≤',control):
            start=chunk.start()+m.start()
            if not any(o['start']<=start<o['end'] for o in out[initial:]):
                fields={o['expected']['field'] for o in out[initial:] if o['kind']=='filter' and o['expected']['field'] in NUMERIC_FIELDS and o['start']<start}
                if not fields and re.search(r'沿用|保持|保留|刚才|之前',control):
                    ctx=context or {};old=[]
                    old+=list((ctx.get('query') or {}).get('filters',[]))
                    old += [f for t in (ctx.get('business_request') or {}).get('tasks',[]) for f in t.get('filters',[])]
                    old += [f for t in (ctx.get('relational_state') or {}).get('tasks',[]) for f in t['spec'].get('filters',[])]
                    fields={f['field'] for f in old if f['field'] in NUMERIC_FIELDS}
                if len(fields)==1:
                    field=next(iter(fields));label=CATALOG[field]['label'];parsed=_field_condition(label+control[m.start():])
                    if parsed:
                        condition,n=parsed;unit=condition.pop('unit',None)
                        add('filter',condition,start,start+n-len(label),ordinal)
                        if unit:add('filter',{'field':'unit','operator':'equals','value':unit},start,start+n-len(label),ordinal)
                        continue
                add('unparsed',{'operator':m[0]},chunk.start(),chunk.end(),ordinal)
        # 否定历史不是本轮肯定范围；取消条件由状态差分核对。
        from request_turn import positive_scope_text
        positive=positive_scope_text(control)
        for pattern,depth in [(r'(?:直属|直接(?:下级|子(?:级|对象)?|部件|设备)|下一层)','direct'),
                              (r'(?:全部|所有)(?:下级|后代|层级)|全层级','all')]:
            m=re.search(pattern,positive)
            if m:add('depth',depth,chunk.start(),chunk.end(),ordinal)
        m=re.search(r'(?:按|依据)\s*(部件类(?:别)?|类别|来源|源系统|对象类型|类型|功能位置)\s*(?:分组|统计|汇总|分布)',control)
        if m:
            group={'部件类':'class','部件类别':'class','类别':'class','来源':'source','源系统':'source','对象类型':'type','类型':'type','功能位置':'location'}[m[1]]
            add('group',group,chunk.start()+m.start(),chunk.start()+m.end(),ordinal)
        m=re.search(r'(?:取|返回|显示|列出|输出|保留)?\s*前\s*(\d+)\s*(?:条|项|个|类|组)',control)
        if m and not re.search(r'不要|取消|撤销',control):add('limit',int(m[1]),chunk.start()+m.start(),chunk.start()+m.end(),ordinal)
        m=re.search(r'(?:按|根据)\s*('+FIELD+r')\s*(?:从新到旧|从旧到新|从早到晚|从晚到早|升序|降序|[从由]高到低|[从由]低到高)',control)
        if m:
            direction='desc' if re.search(r'从新到旧|从晚到早|降序|[从由]高到低',m[0]) else 'asc'
            add('sort',{'field':TOKENS[m[1]],'direction':direction},chunk.start()+m.start(),chunk.start()+m.end(),ordinal)
        m=re.search(r'(?:取消|撤销|去掉|移除|不再限定|不要沿用|不沿用|别沿用)\s*('+FIELD+r')\s*(?:条件|限制|筛选)?',control)
        if m:
            tail=control[m.end():]
            if re.match(r'\s*(?:分组|汇总|统计)',tail):
                add('ungroup',TOKENS[m[1]],chunk.start()+m.start(),chunk.start()+m.end(),ordinal)
            elif not any(o['kind']=='remove_filter' and chunk.start()<=o['start']<chunk.end() for o in out):
                add('remove',TOKENS[m[1]],chunk.start()+m.start(),chunk.start()+m.end(),ordinal)
        if re.search(r'(?:范围|层级|深度)(?:照旧|不变|保持|沿用)|沿用(?:刚才|之前|原来)(?:的)?范围',control):
            add('keep_depth',None,chunk.start(),chunk.end(),ordinal)
        keep=re.search(r'(?:保持|保留|沿用)\s*(?:刚才|原来|之前)?(?:的)?\s*('+FIELD+r')\s*(?:条件|筛选|限制)|('+FIELD+r')\s*(?:条件|筛选|限制)?\s*(?:保持|保留|不变|不动)',control)
        if keep:
            blank_retention=bool(re.search(r'(?:未提供|缺失|空白|为空)\s*$',control[:keep.start()]))
            add('include_blank' if blank_retention else 'keep_field',TOKENS[keep[1] or keep[2]],chunk.start()+keep.start(),chunk.start()+keep.end(),ordinal)
        # 完整根引用带明确对象域，不能跨表偷换同码对象。
        if store is not None:
            from request_checklist import literal_references
            refs=literal_references(text,store)
            for ref in refs:
                if 'start' not in ref or 'end' not in ref:continue
                before=text[:ref['start']]
                marker=re.search(r'('+ '|'.join(map(re.escape,sorted(TREE,key=len,reverse=True)))+r')\s*$',before,re.I)
                input_prefix=before[:marker.start()] if marker else ''
                input_role=not input_prefix.strip() or bool(re.search(r'(?:查(?:询|找)?|读(?:取)?|统计|换(?:成|为)?|切(?:到|换到)|根对象(?:为|是)?|根为)\s*(?:设备|部件|对象|原表)?\s*$',input_prefix))
                tree={w.casefold():t for w,t in TREE.items()}.get(marker[1].casefold()) if marker else None
                if marker and tree==ref['domain'] and input_role:
                    add('root',{'tree':ref['domain'],'field':ref['field'],'value':ref['value']},chunk.start()+marker.start(),chunk.start()+ref['end'],ordinal)
        from request_turn import independent
        if independent(control):add('independent',None,chunk.start(),chunk.end(),ordinal)
        if re.search(r'不执行|不要执行|不查询|暂不查询|只保存条件|仅保存条件',control):
            add('no_execute',None,chunk.start(),chunk.end(),ordinal)
        for o in out[initial:]:o['block']=block
    return out


def _same_filter(expected, actual, store):
    field=expected['field'];op=expected['operator'];value=expected['value']
    if actual.get('field')!=field:return False
    aop=actual.get('operator');av=actual.get('value')
    if field=='time':
        def norm(f):return canonical_time_filters(canonical_year_filters([(f['field'],f['operator'],f['value'])],store))
        # 日期字符串equals仅在原始格式一致时可等价；日期语义使用数学范围规范。
        if aop=='equals':return op=='date_equals' and value==av and parse_time(value) is not None
        return norm(expected)==norm(actual)
    if field in NUMERIC_FIELDS and op in ('eq_num','gt','gte','lt','lte'):
        return aop==op and decimal_value(value)==decimal_value(av)
    if field=='unit':value=canonical_unit(value);av=canonical_unit(av)
    return op==aop and value==av


def _covers(o, v, prior, store):
    kind=o['kind'];e=o['expected']
    if kind=='unparsed':return False
    if kind=='period_replace':
        current=[(f['field'],f['operator'],f['value']) for f in v['filters'] if f['field']=='time']
        wanted=[(e['field'],e['operator'],e['value'])]
        return set(canonical_time_filters(canonical_year_filters(current,store)))==set(canonical_time_filters(canonical_year_filters(wanted,store)))
    if kind=='filter':
        if e['field'] in ('equipment_class','part_class') and e['operator']=='equals':
            value=v.get('classes',{}).get(e['field'])
            if not value:return False
            rows=store.rows('SELECT code,name FROM objects WHERE tree=? AND (code=? OR name=?)',[e['field'],value,value])
            return bool(rows) and len({x['code'] for x in rows})==1 and any(e['value'] in (x['code'],x['name']) for x in rows)
        if e['field']=='time':
            tuples=[(f['field'],f['operator'],f['value']) for f in v['filters'] if f['field']=='time']
            expected=canonical_time_filters(canonical_year_filters([(e['field'],e['operator'],e['value'])],store))
            if set(expected)<=set(canonical_time_filters(canonical_year_filters(tuples,store))):return True
        if any(_same_filter(e,f,store) for f in v['filters']):return True
        if e['field']=='type' and e['operator']=='equals':
            return v.get('population')=={'部件':'parts','设备':'devices'}.get(e['value'])
        root=v.get('root')
        if e['field'] in ('name','code') and e['operator']=='equals' and root:
            if root['field'] in (e['field'],'identity') and root['value']==e['value']:return True
            from relational_query import Graph
            try:node=Graph(store).resolve(root)
            except ValueError:return False
            return isinstance(node,dict) and node.get(e['field'])==e['value']
        return False
    if kind=='depth':return bool(v.get('root') or v.get('classes')) and v.get('depth')==e
    if kind=='group':return v.get('group_by')==e or e=='class' and v.get('group_by')=='class_code'
    if kind=='limit':return e in (v.get('limit'),v.get('goal',{}).get('limit'),v.get('analysis',{}).get('limit'))
    if kind=='sort':return v.get('goal',{}).get('kind')=='sort' and all(v['goal'].get(k)==val for k,val in e.items()) or e['direction']=='asc' and v.get('sort')==[e['field']]
    if kind=='remove':return not any(f['field']==e for f in v['filters']) and e not in v.get('classes',{})
    if kind=='remove_filter':return not any(_same_filter(e,f,store) for f in v['filters'])
    if kind=='ungroup':return v.get('group_by') is None
    if kind=='root':
        roots=[r for r in (v.get('root'),v.get('compare_root')) if r]
        if any(r['tree']==e['tree'] and r['value']==e['value'] and r['field'] in (e['field'],'identity') for r in roots):return True
        from query_filters import TARGETS
        target_tree=TARGETS.get(v.get('target'),(v.get('target'),None))[0]
        if target_tree==e['tree'] and any(f['field'] in (e['field'],'identity') and f['operator']=='equals' and f['value']==e['value'] for f in v['filters']):return True
        from relational_query import Graph
        for root in roots:
            if root['tree']!=e['tree']:continue
            try:node=Graph(store).resolve(root)
            except ValueError:continue
            if isinstance(node,dict) and node.get(e['field'])==e['value']:return True
        return False
    if kind=='keep_depth':
        old=prior[v['ordinal']-1] if len(prior)>=v['ordinal'] else None
        return bool(old and v.get('depth')==old.get('depth'))
    if kind=='include_blank':
        return not any(f['field']==e and not (f['operator']=='is_blank' or f['operator']=='equals' and f['value']=='') for f in v['filters'])
    if kind=='keep_field':
        before=prior[v['ordinal']-1] if len(prior)>=v['ordinal'] else {}
        old_filters=[f for f in before.get('filters',[]) if f['field']==e]
        return bool(old_filters) and all(any(_same_filter(f,a,store) for a in v['filters']) for f in old_filters)
    return False


def audit(store, question, plan, context=None, trace=None):
    vv=views(plan)
    active=[v for v in vv if v['operation'] not in ('clarify','conversation','explain','unsupported','explain_result')]
    obligations_=obligations(question,store if active else None,context)
    # 澄清/能力说明尚未执行SQL；仍记录未覆盖项，不误称完整查询已验。
    if not active:return {'version':1,'status':'not_executed','obligations':obligations_}
    context=context or {};old=(context.get('relational_state') or {}).get('tasks',[])
    trace=trace or {}
    state=trace.get('business_request_state') or {}
    executed=trace.get('changed_tasks') or []
    positions={t['id']:i for i,t in enumerate(state.get('tasks',[]),1)}
    if len(executed)==len(vv) and all(t in positions for t in executed):
        for v,tid in zip(vv,executed):v['ordinal']=positions[tid]
    prior=[dict(t['spec'],ordinal=i) for i,t in enumerate(old,1)]
    if not prior:prior=[dict(t,ordinal=i,depth=t.get('scope')) for i,t in enumerate((context.get('business_request') or {}).get('tasks',[]),1)]
    if not prior and context.get('query'):prior=[dict(filters=context['query'].get('filters',[]),depth=context.get('scope'),ordinal=1)]
    if not prior and context.get('scope'):prior=[dict(depth=context['scope'],ordinal=1)]
    for o in obligations_:
        candidates=[v for v in active if o['ordinal'] is None or o['ordinal']==v['ordinal']]
        if o['kind']=='no_execute':
            o['matched_tasks']=[];o['covered']=not candidates;continue
        if o['kind']=='independent':
            from request_checklist import literal_references
            current={r['value'] for r in literal_references(question,store)}
            old_filters=[f for t in (context.get('business_request') or {}).get('tasks',[]) for f in t.get('filters',[])]
            old_filters+=list((context.get('query') or {}).get('filters',[]))
            old_filters += [f for t in old for f in t['spec'].get('filters',[])]
            stated=[x['expected'] for x in obligations_ if x['kind']=='filter']
            old_root=(context.get('entity') or {}).get('code')
            def independent_view(v):
                if old_root and (v.get('root') or {}).get('value')==old_root and old_root not in current:return False
                return all(not any(all(old.get(k)==f.get(k) for k in ('field','operator','value')) for old in old_filters)
                           or any(_same_filter(e,f,store) for e in stated) for f in v['filters'])
            o['matched_tasks']=[v['ordinal'] for v in candidates if independent_view(v)]
        else:o['matched_tasks']=[v['ordinal'] for v in candidates if _covers(o,v,prior,store)]
        o['covered']=bool(o['matched_tasks'])
    # 同一条件子句的约束必须能共同落在一项任务，防止在多项间拆散条件。
    for block in {o.get('block') for o in obligations_}:
        group=[o for o in obligations_ if o['kind']=='filter' and o.get('block')==block]
        if len(group)>1 and not set.intersection(*(set(o['matched_tasks']) for o in group)):
            for o in group:o['covered']=False
    report={'version':1,'coverage_scope':'registered_explicit_requirements',
            'status':'covered' if all(o['covered'] for o in obligations_) else 'blocked',
            'obligations':obligations_, 'task_count':len(active), 'no_model_output_roles_used':True}
    if report['status']=='blocked':raise CoverageInvalid(report)
    return report
