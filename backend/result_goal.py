"""保留业务交付目标，并在完整筛选集合上执行确定性结果动作。"""
import copy
from decimal import localcontext
from attributes import CATALOG
from typed_fields import decimal_value,canonical_unit,THRESHOLDS
from date_fields import parse_time

KINDS={'records','count','attributes','extreme','sort','difference','unsupported'}
KEYS={'kind','field','direction','limit','ties','operands','basis'}

class GoalConstraintError(ValueError):
 """程序校验的业务边界，区别于模型结构或网络失败。"""
 def __init__(self,message,constraint):
  super().__init__(message);self.business_constraint=copy.deepcopy(constraint)

def default_goal(operation):
 return {'kind':'attributes' if operation=='attributes' else 'records','field':None,'direction':None,'limit':None,'ties':'all','operands':[],'basis':'measurement'}

def validate_goal(goal,operation=None,target=None):
 if not isinstance(goal,dict) or set(goal)!=KEYS:raise ValueError('结果目标结构不完整；不能降级为普通记录列表。')
 if not isinstance(goal['kind'],str) or goal['kind'] not in KINDS or goal['ties']!='all' or goal['basis'] not in ('measurement','raw_numbers'):raise ValueError('结果目标或计算口径不支持。')
 kind=goal['kind'];field=goal['field'];direction=goal['direction'];limit=goal['limit'];operands=goal['operands']
 if not isinstance(operands,list):raise ValueError('计算对象必须为列表。')
 if kind in ('records','count','attributes','unsupported'):
  if field is not None or direction is not None or limit is not None or operands:raise ValueError('普通结果目标不能携带未执行的排序或计算参数。')
  if kind in ('records','count') and operation=='attributes':raise ValueError('属性读取必须使用attributes结果目标，不能标成记录列表或计数。')
  if kind=='attributes' and operation not in (None,'attributes'):raise ValueError('属性目标不能退化为列表。')
 elif kind in ('extreme','sort'):
  if target not in (None,'points') or field not in ('value','time','thresholds') or direction not in ('asc','desc') or operands:raise ValueError('排序/极值需要支持的测点字段和明确方向。')
  if kind=='extreme' and (field=='thresholds' or limit is not None):raise ValueError('极值保留全部并列，不能任意取首项。')
  if kind=='sort' and limit is not None:
   if type(limit) is not int:raise ValueError('排序数量须在1至100之间。')
   if not 1<=limit<=100:raise GoalConstraintError('排序数量须在1至100之间。',{'code':'sort_limit_bounds','minimum':1,'maximum':100})
  if field=='thresholds' and operation not in (None,'attributes'):raise ValueError('阈值排序需要先读取属性。')
  if field in ('time','value') and operation not in (None,'search','clarify'):raise ValueError('测量记录的排序或极值需要search记录查询，不能在属性投影上计算。')
 elif kind=='difference':
  if target not in (None,'points') or field!='value' or direction not in (None,'absolute') or limit is not None or len(operands)!=2:raise ValueError('差值必须明确两个操作数、测量值字段及有向/绝对差。')
  if operation not in (None,'search','clarify'):raise ValueError('差值需要search记录查询，不能在属性投影上计算。')
  for operand in operands:
   if not isinstance(operand,dict) or set(operand)!={'field','value'} or operand['field'] not in ('name','code','identity') or not isinstance(operand['value'],str) or not 0<len(operand['value'])<=300:raise ValueError('差值对象需要有来源的名称或编码。')
 if kind not in ('difference','extreme','sort') and goal['basis']!='measurement':raise ValueError('纯算术口径仅用于数值运算。')
 return goal

def validate_plan_goal(intent):
 if 'result_goal' not in intent:return
 goal=validate_goal(intent['result_goal'],intent.get('operation'),(intent.get('query') or {}).get('target'))
 if intent.get('operation')=='parts' and goal['kind'] not in ('records','count'):raise ValueError('关系执行器只支持原生列表与计数目标。')
 if intent.get('operation') not in ('search','attributes','clarify','parts'):raise ValueError('当前执行路径不能丢弃结果目标。')
 if goal['kind']=='difference' and any(f['field'] in ('name','code','identity') for f in intent.get('query',{}).get('filters',[])):raise ValueError('两个差值对象不能作为互斥条件合取；请分别声明操作数。')

def empty_result(intent,status,answer,note=''):
 return {'status':status,'answer':answer,'records':[],'metrics':[],'evidence':[],'path':[],'entity':intent.get('entity'),'scope':intent.get('scope','direct'),'note':note}

def apply_goal(store,intent,result):
 """执行后核对结果动作；缺数据或不支持均不冒充成功。"""
 goal=intent.get('result_goal')
 if not goal:return result
 validate_plan_goal(intent)
 if result.get('status')!='ok':return result
 kind=goal['kind'];out=copy.deepcopy(result)
 if kind=='unsupported':return empty_result(intent,'clarify','此结果目标尚不支持，未执行替代查询。')
 if kind in ('records','count','attributes'):
  out['goal_receipt']={'goal':copy.deepcopy(goal),'completed':True,'population':len(result.get('records',[]))}
  return out
 if kind=='difference':return difference(store,intent,goal)
 field=goal['field'];reverse=goal['direction']=='desc'
 if field=='thresholds':
  facts=out.get('attributes',[]);selected=[f for f in facts if f['property'] in THRESHOLDS]
  if not selected:return empty_result(intent,'clarify','未读取报警阈值，不能执行阈值排序。')
  present=[f for f in selected if f['status']=='known' and decimal_value(str(f['value'])) is not None]
  missing=[f for f in selected if f not in present]
  present.sort(key=lambda f:decimal_value(str(f['value'])),reverse=reverse)
  ordered=present+missing
  out['attributes']=ordered[:goal['limit']]+[f for f in facts if f not in selected]
  out['answer']='报警阈值按数值'+('从高到低' if reverse else '从低到高')+'排序；缺失值列在末尾。'
  if goal['limit'] is not None:out['answer']+='仅返回排序后前 '+str(goal['limit'])+' 项。'
  out['note']=out.get('note','')+'不同阈值族保留原字段名称；未补齐缺失阈值。'
 else:
  rows=out.get('records',[]);usable=[];missing=0
  for row in rows:
   raw=row.get(field);value=parse_time(raw) if field=='time' else decimal_value(str(raw or ''))
   if value is None:missing+=1
   else:usable.append((value,row))
  if field=='value' and usable and goal['basis']!='raw_numbers':
   units={canonical_unit(str(row.get('unit',''))) for _,row in usable}
   if len(units)!=1 or units.intersection({'','未提供','--'}):
    return empty_result(intent,'clarify','数值排序或极值需要明确可比较的单位和测量范围；当前记录含不同或缺失单位。','尚未把不同物理量混合排序。')
  if not usable:return empty_result(intent,'data_insufficient','当前范围没有有效的'+('测量时间' if field=='time' else '测量值')+'，无法完成结果目标。')
  usable.sort(key=lambda item:item[0],reverse=reverse)
  value=usable[0][0]
  chosen=[row for key,row in usable if key==value] if kind=='extreme' else [row for _,row in usable][:goal['limit']]
  out['records']=chosen;out['metrics']=[{'label':'匹配记录','value':len(rows)},{'label':'结果记录','value':len(chosen)}]
  out['evidence']=[row['evidence'] for row in chosen if row.get('evidence')]
  out['answer']=('最早' if field=='time' and not reverse else '最晚' if field=='time' else '最高' if reverse else '最低')+'的'+('测量时间' if field=='time' else '测量值')+'为 '+str(value)+'，共 '+str(len(chosen))+' 条并列记录。' if kind=='extreme' else '按'+('测量时间' if field=='time' else '测量值')+('降序' if reverse else '升序')+'返回 '+str(len(chosen))+' 条记录。'
  out['note']=out.get('note','')+f'基于完整范围{len(rows)}条记录计算；缺失或无效值{missing}条未参与。极值保留全部并列；原始时间和数值保持不变。'
 out['goal_receipt']={'goal':copy.deepcopy(goal),'completed':True,'population':len(result.get('records',[]))}
 return out

def difference(store,intent,goal):
 readings=[];evidence=[]
 for operand in goal['operands']:
  query=copy.deepcopy(intent['query']);query['filters']+=[{'field':operand['field'],'operator':'equals','value':operand['value']}]
  found=store.filtered({**intent,'operation':'search','query':query});rows=found['records']
  if len(rows)!=1:return empty_result(intent,'clarify','差值对象「'+operand['value']+'」对应 '+str(len(rows))+' 条来源记录，请明确唯一读数或来源/时间。')
  row=rows[0];value=decimal_value(str(row.get('value','')))
  if value is None:return empty_result(intent,'data_insufficient','差值对象缺少有效测量值，未计算。')
  readings.append((value,row));evidence.append(row['evidence'])
 if goal['basis']!='raw_numbers':
  return empty_result(intent,'clarify','已定位两个读数，但现有数据缺少可靠物理量定义。请明确可比较口径，或说明仅计算原始数值的第一项减第二项。','不能因两行单位相同或均为空就认定物理量可比较。')
 # 对齐两项有效数字的完整位跨度，避免默认28位精度静默舍入；
 # 输入长度与指数已由共享数值校验限制，局部设置不影响其他请求。
 numbers=[x[0] for x in readings]
 with localcontext() as context:
  context.prec=max(1,max(x.adjusted() for x in numbers)-min(x.as_tuple().exponent for x in numbers)+2)
  value=numbers[0]-numbers[1]
 if goal['direction']=='absolute':value=value.copy_abs()
 label='原始数值绝对差' if goal['direction']=='absolute' else '原始数值：第一项减第二项'
 out=empty_result(intent,'ok',label+' = '+str(value)+'。','仅为所声明动作的纯算术差；没有认定两项属于同一物理量，原始来源和测量时间已保留。')
 out.update(metrics=[{'label':'纯算术绝对差' if goal['direction']=='absolute' else '纯算术差值','value':str(value)}],evidence=evidence,operands=[row for _,row in readings],goal_receipt={'goal':copy.deepcopy(goal),'completed':True})
 return out
