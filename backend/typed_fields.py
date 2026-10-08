"""可执行标量类型；无效数字文本不能变成零。"""
from decimal import Decimal, InvalidOperation

NUMERIC_OPS={'gt','gte','lt','lte','eq_num'}
NUMERIC_LABELS={'gt':'大于','gte':'大于等于','lt':'小于','lte':'小于等于','eq_num':'数值等于'}
THRESHOLDS={f'{family}_{side}{level}':f'{label}报警阈值-{direction}{level}'
    for family,label in [('actual','真实值'),('estimate','估计值'),('rate_deviation','变化速率偏差')]
    for side,direction in [('low','低'),('high','高')] for level in (1,2,3)}
NUMERIC_FIELDS={'value','rate','prediction',*THRESHOLDS}
UNIT_ALIASES={'℃':'℃','°C':'℃','摄氏度':'℃','摄氏':'℃','℉':'℉','°F':'℉','华氏度':'℉','华氏':'℉'}
# 表达不充分的单位即使被模型标为明确，也不等于物理单位；
# 此目录识别单位值，不对问句短语分类。
AMBIGUOUS_UNITS={'度'}

def canonical_unit(value):
    if value in UNIT_ALIASES:return UNIT_ALIASES[value]
    # 完整单位标签中的温标名称仍指向同一种单位。
    # 不处理冲突温标，也不从单独的“度”推断单位。
    scales={unit for name,unit in (('摄氏','℃'),('华氏','℉')) if name in value}
    return next(iter(scales)) if len(scales)==1 else value

def decimal_value(value):
    if not isinstance(value,str) or len(value)>128:return None
    try:
        n=Decimal(value.strip())
        return n if n.is_finite() and abs(n.as_tuple().exponent)<=200 else None
    except (InvalidOperation,ValueError):return None

def compare(left,op,right):
    a,b=decimal_value(left),decimal_value(right)
    if a is None or b is None:return 0
    return int({'gt':a>b,'gte':a>=b,'lt':a<b,'lte':a<=b,'eq_num':a==b}[op])

def validate_thresholds(intent):
    selected=intent.get('thresholds')
    if selected is None:return
    if intent.get('operation')!='threshold' or not isinstance(selected,list) or not selected or len(selected)>18 or len(set(selected))!=len(selected) or any(x not in THRESHOLDS for x in selected):
        raise ValueError('阈值选择必须完整指定有效字段，不能丢弃档位。')

def project_thresholds(result,intent):
    validate_thresholds(intent)
    selected=intent.get('thresholds') or list(THRESHOLDS)
    result['threshold_details']=[]
    for row in result['records']:
        raw=row['evidence']['fields'];values={THRESHOLDS[k]:raw.get(THRESHOLDS[k]) or '未提供' for k in selected}
        result['threshold_details'].append({'source':row['source'],'time':row['time'],'thresholds':values,'evidence':row['evidence']})
        # 保留旧数据字段兼容客户端，但不能把它们当作用户所问投影。
        high=raw.get(THRESHOLDS['actual_high1'],'');a,b=decimal_value(raw.get('测量值','')),decimal_value(high)
        row.update(high1=high or '未提供',difference=str(a-b) if a is not None and b is not None else '无法计算')
    result['requested_thresholds']=selected
    result['coverage']={'complete':True,'requested':selected,'answered':selected}
    result['note']+='按所问阈值字段及各来源逐条展示；空值为未提供，不补零；阈值比较不代表完整报警规则或故障诊断。'
    if len(result['records'])==1:
        row=result['records'][0];values=result['threshold_details'][0]['thresholds']
        provided={k:v for k,v in values.items() if v!='未提供'}
        shown=values if intent.get('thresholds') else provided
        result['answer']=f"{row['name']}（{row['code']}）："+('；'.join(k+'：'+v for k,v in shown.items()) if shown else '所有阈值均未提供')+'。'
        if not intent.get('thresholds') and len(provided)<len(values):result['answer']+=f'其余 {len(values)-len(provided)} 个阈值字段未提供。'
        result['metrics']=[{'label':k,'value':v} for k,v in shown.items()]
    return result
