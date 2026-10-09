"""在模型工具边界核验公开结构，给出字段路径；业务语义仍由既有校验器处理。"""
import json
import copy


def prepare_request(proposal, schema):
    """只兼容任务层误放的空ids；非空编号和其他未知字段不丢弃。"""
    prepared = copy.deepcopy(proposal)
    ignored = []
    if isinstance(prepared, dict) and isinstance(prepared.get('tasks'), list):
        for index, task in enumerate(prepared['tasks']):
            if isinstance(task, dict) and task.get('ids') == []:
                task.pop('ids')
                ignored.append({'path': 'request.tasks[' + str(index) + '].ids',
                                'reason': '空数组不携带条件编号；实际条件仍由filters动作逐项核验。'})
    check_structure(schema, prepared)
    return prepared, ignored

def check_structure(schema,value,path='request'):
 if 'anyOf' in schema:
  candidates=[s for s in schema['anyOf'] if matches(s.get('type'),value)]
  errors=[]
  for candidate in candidates:
   try:check_structure(candidate,value,path);return
   except ValueError as error:errors.append(str(error))
  raise ValueError(errors[0] if errors else path+'的类型不符合公开工具协议。')
 if not matches(schema.get('type'),value):raise ValueError(path+'的类型不符合公开工具协议。')
 if 'enum' in schema and value not in schema['enum']:raise ValueError(path+'不在合法字段目录中，请核对catalog与公开协议。')
 if isinstance(value,dict):
  props=schema.get('properties',{});extra=set(value)-set(props)
  if schema.get('additionalProperties') is False and extra:
   key=sorted(extra)[0];hint='；ids只能放在filters每项动作里，请移除任务层ids' if key=='ids' else ''
   raise ValueError(path+'.'+key+'不是合法键'+hint+'。')
  missing=set(schema.get('required',[]))-set(value)
  if missing:raise ValueError(path+'.'+sorted(missing)[0]+'缺失，请按公开协议补充。')
  for key,item in value.items():
   if key in props:check_structure(props[key],item,path+'.'+key)
 elif isinstance(value,list):
  if len(value)<schema.get('minItems',0) or len(value)>schema.get('maxItems',len(value)):raise ValueError(path+'的项数不符合公开工具协议。')
  if schema.get('uniqueItems') and len({json.dumps(x,sort_keys=True,ensure_ascii=False) for x in value})!=len(value):raise ValueError(path+'不能有重复项。')
  for i,item in enumerate(value):check_structure(schema.get('items',{}),item,path+'['+str(i)+']')
 elif isinstance(value,str):
  if len(value)<schema.get('minLength',0) or len(value)>schema.get('maxLength',len(value)):raise ValueError(path+'的文字长度不符合公开协议。')

def matches(types,value):
 if types is None:return True
 if isinstance(types,list):return any(matches(t,value) for t in types)
 return {'object':isinstance(value,dict),'array':isinstance(value,list),'string':isinstance(value,str),'integer':type(value) is int,'boolean':type(value) is bool,'null':value is None}.get(types,False)
