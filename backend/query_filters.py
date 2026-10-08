"""所有检索目标共享类型化、参数化的文本筛选条件。"""
TARGETS={
 'parts':('config','部件'), 'equipment':('config','设备'),
 'config':('config',None), 'pbs':('pbs',None),
 'equipment_class':('equipment_class',None), 'part_class':('part_class',None),
 'points':(None,None), 'objects':('*',None)}
TARGET_LABELS={'objects':'跨树对象','parts':'部件构型','equipment':'设备构型','config':'构型对象','pbs':'PBS对象','equipment_class':'设备类字典记录','part_class':'部件类字典记录','points':'测点记录'}
TARGET_MEANINGS={'objects':'跨树对象（不限定对象树）','parts':'构型树中的部件','equipment':'构型树中的设备','config':'构型树中的对象（全部层级）','pbs':'PBS树中的对象'}
def target_catalog():
 return {key:{'label':TARGET_MEANINGS.get(key,TARGET_LABELS[key]),'tree':tree,'level':level} for key,(tree,level) in TARGETS.items()}
OBJECT_FIELDS={'name':'name','code':'code','level':'level','parent':'parent','class_code':'class_code'}
POINT_FIELDS={'name':'name','code':'code','source':'system','status':'status','switch':'switch','unit':'unit','time':'time'}
from attributes import CATALOG
# 测点数值筛选与属性读取共用同一原始字段登记表。
POINT_RAW_FIELDS={key:spec['fields']['points'] for key,spec in CATALOG.items() if 'points' in spec['fields'] and key not in POINT_FIELDS}
from typed_fields import NUMERIC_FIELDS,NUMERIC_OPS,NUMERIC_LABELS,decimal_value,canonical_unit
from date_fields import DATE_OPS,DATE_LABELS,parse_time,calendar_period
OPERATORS=DATE_OPS|{'contains','equals','starts_with','not_contains','is_blank','not_blank'}|NUMERIC_OPS

def filter_fields(target):
 return [*({**POINT_FIELDS,**POINT_RAW_FIELDS} if target=='points' else OBJECT_FIELDS),'identity']

DETAIL_OPS={'object','equipment','equipment_class','part_class','parent','measurement','threshold','duration'}

def validate_detail_query(operation,query):
 validate_query(query)
 if operation not in DETAIL_OPS:
  raise ValueError('这类操作暂不能结合筛选条件执行，请先明确对象；原条件已保留。')
 if operation in ('measurement','threshold','duration') and query['target']!='points':
  raise ValueError('数值和阈值需要定位测点，请提供测点名称或编码。')
 if query['target']=='points' and operation not in ('object','measurement','threshold','duration'):
  raise ValueError('对象关系查询需要PBS或构型对象，请先选择对应对象。')
 return query

def validate_query(query):
 if not isinstance(query,dict) or not {'target','filters'}<=set(query) or set(query)-{'target','filters','equipment_class'} or query['target'] not in TARGETS:
  raise ValueError('查询目标格式无效。')
 if 'equipment_class' in query:
  relation=query['equipment_class']
  if query['target']!='parts' or not isinstance(relation,dict) or set(relation)!={'field','operator','value'} or relation['field'] not in ('name','code','identity') or relation['operator']!='equals':
   raise ValueError('设备分类关系仅支持部件查询的完整名称或编码匹配。')
  validate_query({'target':'equipment_class','filters':[relation]})
 filters=query['filters']
 if not isinstance(filters,list) or len(filters)>8:raise ValueError('筛选条件须为列表且最多8项。')
 fields={**POINT_FIELDS,**POINT_RAW_FIELDS} if query['target']=='points' else OBJECT_FIELDS
 for f in filters:
  if not isinstance(f,dict) or set(f)!={'field','operator','value'}:raise ValueError('筛选条件格式无效。')
  if f['field'] not in filter_fields(query['target']) or f['operator'] not in OPERATORS:raise ValueError('不支持的筛选字段或比较方式；未执行查询。')
  if f['operator'] in NUMERIC_OPS and (query['target']!='points' or f['field'] not in NUMERIC_FIELDS or decimal_value(f['value']) is None):raise ValueError('数值比较必须使用数值字段和有效数字；未执行查询。')
  if query['target']=='points' and f['field'] in NUMERIC_FIELDS and f['operator'] not in NUMERIC_OPS|{'is_blank','not_blank'} and not (f['operator']=='equals' and decimal_value(f['value']) is not None):raise ValueError('数值字段不能使用文本比较；请明确数值条件。')
  if f['operator'] in DATE_OPS and (query['target']!='points' or f['field']!='time' or (parse_time(f['value']) is None and not (f['operator']=='date_equals' and calendar_period(f['value'])))):raise ValueError('日期比较需要有效时间字段与边界，未执行。')
  if f['field']=='identity' and f['operator'] not in ('contains','equals','starts_with'):raise ValueError('名称或编码联合搜索只支持包含、相等或前缀。')
  if not isinstance(f['value'],str) or len(f['value'])>300:raise ValueError('筛选值格式无效。')
  if query['target']=='points' and f['field']=='unit' and f['operator']=='equals':f['value']=canonical_unit(f['value'])
  if f['operator'] in ('is_blank','not_blank'):
   if f['value']!='':raise ValueError('空值条件不能携带非空筛选值。')
  elif not f['value']:raise ValueError('请提供非空筛选值。')
 return query

def predicates(query,alias='r'):
 validate_query(query)
 fields=POINT_FIELDS if query['target']=='points' else OBJECT_FIELDS
 clauses=[];args=[]
 for f in query['filters']:
  if f['field']=='identity':
   alternatives=[]
   for field in ('name','code'):
    sub,values=predicates({'target':query['target'],'filters':[{**f,'field':field}]},alias)
    alternatives.extend(sub);args.extend(values)
   clauses.append('('+' OR '.join(alternatives)+')')
   continue
  field=f['field']
  if query['target']=='points' and field in POINT_RAW_FIELDS:
   col="json_extract("+alias+".raw, '$."+POINT_RAW_FIELDS[field]+"')"
  else:col=alias+'.'+fields[field]
  op=f['operator'];v=f['value']
  if query['target']=='points' and field in NUMERIC_FIELDS and op=='equals':op='eq_num'
  if op in DATE_OPS:clauses.append('date_compare('+col+',?,?)=1');args.extend([op,v])
  elif op in NUMERIC_OPS:clauses.append('decimal_compare('+col+',?,?)=1');args.extend([op,v])
  elif op=='equals':clauses.append(('canonical_unit('+col+')' if query['target']=='points' and field=='unit' else col)+'=?');args.append(v)
  elif op=='contains':clauses.append('instr('+col+',?)>0');args.append(v)
  elif op=='not_contains':clauses.append('instr('+col+',?)=0');args.append(v)
  elif op=='starts_with':clauses.append('substr('+col+',1,length(?))=?');args.extend([v,v])
  elif op=='is_blank':clauses.append("trim(coalesce("+col+",''))=''")
  else:clauses.append("trim(coalesce("+col+",''))<>''")
 return clauses,args

def target_label(query):
 target=TARGET_LABELS[query['target']]
 if query['target']=='pbs':
  levels=[f['value'] for f in query['filters'] if f['field']=='level' and f['operator']=='equals']
  if len(levels)==1:target='PBS'+levels[0]+'对象'
 return target

def describe(query):
 fields={'name':'名称','code':'编码','level':'层级','parent':'父编码','class_code':'所属部件类编码','source':'源系统','status':'状态','switch':'开关','unit':'单位','time':'测量时间'}
 fields.update({key:CATALOG[key]['label'] for key in POINT_RAW_FIELDS})
 ops={**NUMERIC_LABELS,**DATE_LABELS,'equals':'等于','contains':'包含','starts_with':'开头为','not_contains':'不包含','is_blank':'未提供','not_blank':'已提供'}
 target=target_label(query)
 fields['identity']='（名称或编码）'
 if query.get('equipment_class'):target+='（设备分类'+query['equipment_class']['value']+'）'
 return target+'；'+(' 且 '.join(fields[f['field']]+ops[f['operator']]+('「'+f['value']+'」' if f['value'] else '') for f in query['filters']) or '未附加字段筛选')
