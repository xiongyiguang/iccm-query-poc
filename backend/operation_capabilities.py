"""根据当前对象和实际只读关联证据给出快捷操作可用性。"""
from data import QueryError,BusinessOutcome

PBS_OPERATIONS=[('对应设备','equipment'),('查看测点','measurements'),('阈值对照','threshold'),('报警时长','duration')]
CONFIG_OPERATIONS=[('查看名称','object'),('直接部件','parts'),('部件类','part_class')]

def operations_for(store,entity):
 if not isinstance(entity,dict) or set(entity)!={'tree','code'} or entity['tree'] not in ('pbs','config','equipment_class','part_class') or not isinstance(entity['code'],str) or not 0<len(entity['code'])<=300:raise QueryError('请选择有效对象。')
 definitions=PBS_OPERATIONS if entity['tree']=='pbs' else CONFIG_OPERATIONS if entity['tree']=='config' else [('查看名称','object')]
 items=[]
 for label,operation in definitions:
  intent={'operation':operation,'entity':entity,'scope':'direct','clarification':''}
  try:
   result=store.execute(intent);enabled=result.get('status')=='ok';reason='' if enabled else result['answer']
   if operation=='measurements' and enabled and not result.get('records'):
    enabled=False;reason='该对象及其PBS下级未匹配到监测记录。'
   if operation=='duration':enabled=False;reason='当前快照缺少报警开始与恢复事件，不能计算时长。'
  except (QueryError,BusinessOutcome) as error:enabled=False;reason=str(error)
  items.append({'label':label,'operation':operation,'enabled':enabled,'reason':reason})
 return {'entity':entity,'version':store.version,'operations':items}
