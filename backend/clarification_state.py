"""把澄清绑定到确切槽位，仅对程序保存的选项执行受限更新。"""
import copy,hashlib,json,re
from business_request import compile_selected

FIELD_LABELS={'name':['名称','按名称','对象名称'],'code':['编码','按编码','对象编码'],'identity':['名称或编码','名称或者编码']}
TARGET_LABELS={'pbs':['PBS','PBS树'],'config':['构型','构型树'],'equipment_class':['设备类'],'part_class':['部件类'],'points':['测点','测量点']}

def request_base_hash(previous):
 return hashlib.sha256(json.dumps(previous,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def quantity_pending(question,request,previous):
 """只保存真实原话及唯一数量位置，不把未执行提取变成已确认对象。"""
 if not isinstance(request,dict):return None
 limits=[t.get('set',{}).get('result_goal',{}).get('limit') for t in request.get('tasks',[]) if isinstance(t,dict) and isinstance(t.get('set'),dict) and isinstance(t['set'].get('result_goal'),dict) and t['set']['result_goal'].get('kind')=='sort']
 invalid=[n for n in limits if type(n) is int and not 1<=n<=100]
 if len(limits)!=1 or len(invalid)!=1:return None
 quoted=[m.span() for m in re.finditer(r'“[^”]*”|「[^」]*」|『[^』]*』|\"[^\"]*\"|`[^`]*`',question)]
 quoted += [m.span() for m in re.finditer(r'(?:名字(?:叫|为)|名称(?:为|是)|名为|编码(?:为|是))[^，。；;！？!?]*',question)]
 spans=[]
 for m in re.finditer(r'(?:前|返回|取|显示|输出|列出|只要)\s*([+-]?\d+)\s*(?:条|个|项|组)',question):
  if int(m.group(1))==invalid[0] and not any(a<=m.start() and m.end()<=b for a,b in quoted):spans.append(list(m.span(1)))
 if len(spans)!=1:return None
 return {'version':1,'kind':'sort_limit','question':question,'span':spans[0],'requested':invalid[0],'base_hash':request_base_hash(previous)}

def resolve_quantity(question,context):
 """仅替换待确认数量；原条件/顺序原话逐字保留，再走完整双模型核验。"""
 pending=context.get('pending_constraint_request')
 if not isinstance(pending,dict) or set(pending)!={'version','kind','question','span','requested','base_hash'} or pending.get('version')!=1 or pending.get('kind')!='sort_limit':return None
 previous=context.get('pending_business_request') or context.get('business_request')
 if pending['base_hash']!=request_base_hash(previous):return None
 original=pending['question'];span=pending['span']
 if not isinstance(original,str) or not isinstance(span,list) or len(span)!=2 or any(type(n) is not int for n in span) or not 0<=span[0]<span[1]<=len(original):return None
 try:
  if int(original[span[0]:span[1]])!=pending['requested']:return None
 except ValueError:return None
 expected=quantity_pending(original,{'tasks':[{'set':{'result_goal':{'kind':'sort','limit':pending['requested']}}}]},previous)
 if expected!=pending:return None
 answer=question.strip().strip('。！？!?')
 pattern=r'(?:改(?:为|成)|换(?:成|为)|那就(?:改(?:为|成))?|就|返回|取)?\s*(?:前)?\s*([+-]?\d+)\s*(?:条|个|项|组)?(?:\s*[，,；;]\s*(?:其他(?:条件和排序|条件及排序|条件|排序)?|其余(?:条件|排序)?)(?:保持)?不变)?'
 match=re.fullmatch(pattern,answer)
 if not match:return None
 number=int(match.group(1));valid=1<=number<=100
 return {'pending':copy.deepcopy(pending),'answer':question,'quantity':number,'valid':valid,'resolved_question':original[:span[0]]+str(number)+original[span[1]:] if valid else None}

def make_slot(candidate,independent,comparison=None):
 for i,(a,b) in enumerate(zip(candidate,independent)):
  base={'task_id':a['id'],'task_index':i,'kind':'choice'}
  if a.get('target')!=b.get('target'):
   choices=[{'value':v,'labels':TARGET_LABELS[v]} for v in (a.get('target'),b.get('target')) if v in TARGET_LABELS]
   if len(choices)==2:return {**base,'field':'target','choices':choices}
  af=a.get('filters',[]);bf=b.get('filters',[])
  same_filters=bool(comparison and comparison['candidate'][i].get('filters')==comparison['independent'][i].get('filters'))
  if not same_filters and len(af)==len(bf)==1 and af[0]['operator']==bf[0]['operator']=='equals' and af[0]['value']==bf[0]['value'] and af[0]['field']!=bf[0]['field'] and {af[0]['field'],bf[0]['field']}<=set(FIELD_LABELS):
   return {**base,'field':'identifier_field','filter_id':af[0]['id'],'identity_value':af[0]['value'],'choices':[{'value':v,'labels':labels} for v,labels in FIELD_LABELS.items()]}
  for field,labels in (('scope',{'direct':['直接下级','直接的'],'all':['全部下级','所有下级']}),('population',{'parts':['仅部件','部件'],'all_objects':['所有对象','全部对象']})):
   if a.get(field)!=b.get(field) and a.get(field) in labels and b.get(field) in labels:
    return {**base,'field':field,'choices':[{'value':v,'labels':labels[v]} for v in (a[field],b[field])]}
 return None

def domain_slot(state):
 tasks=(state or {}).get('tasks',[])
 if len(tasks)!=1:return None
 task=tasks[0];fs=task.get('filters',[])
 if task.get('operation')!='attributes' or task.get('target')=='points' or task.get('sources',{}).get('purpose',{}).get('value') not in ('identity','introduction') or len(fs)!=1 or fs[0].get('field') not in FIELD_LABELS or fs[0].get('operator')!='equals':return None
 return {'task_id':task['id'],'kind':'choice','field':'target','identity_value':fs[0]['value'],'filter_id':fs[0]['id'],'choices':[{'value':v,'labels':labels+[x+'呢' for x in labels]+['那'+x+'呢' for x in labels]} for v,labels in TARGET_LABELS.items() if v!='points']}

CONTINUE_LABELS={'继续','继续查询','就这个','就这个，继续刚才的问题','继续刚才的问题','查询选中对象'}

def resolve_selection(question,context,selection,store):
 """点选是当前候选身份槽位的输入，复合新问题仍交给完整模型理解。"""
 previous=context.get('pending_business_request');tasks=(previous or {}).get('tasks',[])
 if not store or not isinstance(selection,dict) or set(selection)!={'tree','code'} or question.strip().strip('。！？!?') not in CONTINUE_LABELS or len(tasks)!=1:return None
 task=tasks[0]
 if task.get('operation')!='attributes' or task.get('unit',{}).get('state')=='ambiguous':return None
 if context.get('outcome',{}).get('kind') not in ('ambiguous','not_found') and context.get('pending_slot',{}).get('field')!='identifier_field':return None
 from query_filters import TARGETS
 target=task['target'];tree=TARGETS[target][0]
 if selection.get('tree')!=('pbs' if target=='points' else tree) or not isinstance(selection.get('code'),str):return None
 identities=[f for f in task['filters'] if f['field'] in FIELD_LABELS]
 if len(identities)!=1 or identities[0]['operator']!='equals' or not 3<=len(identities[0]['value'])<=100:return None
 query={'target':target,'filters':[{k:f[k] for k in ('field','operator','value')} for f in task['filters']]}
 for f in query['filters']:
  if f['field'] in FIELD_LABELS:f['operator']='contains'
 found=store.filtered({'operation':'search','entity':None,'scope':'direct','clarification':'','query':query})
 if not any(r['tree']==selection['tree'] and r['code']==selection['code'] for r in found['records']):return None
 state=copy.deepcopy(previous);task=state['tasks'][0];revision=state.get('revision',0)+1
 f=next(f for f in task['filters'] if f['id']==identities[0]['id'])
 source={'kind':'user_selection','turn':revision,'quote':question,'selection':copy.deepcopy(selection),'identity_source':copy.deepcopy(f['source'])}
 f.update(field='code',value=selection['code'],source=source)
 task['sources']['request']=source;state['revision']=revision;state['last_executed_tasks']=[task['id']]
 state.pop('pending_reason',None);state.pop('pending_tasks',None)
 plan=compile_selected(state,[task['id']],[question])
 return plan,state,[task['id']],{'kind':'selection','answer':question,'selection':copy.deepcopy(selection),'filter_id':f['id'],'previous_revision':previous.get('revision',0)}

def resolve_answer(question,context,selection=None,store=None):
 selected=resolve_selection(question,context,selection,store)
 if selected:return selected
 previous=context.get('pending_business_request') or context.get('business_request')
 slot=context.get('pending_slot') or domain_slot(previous)
 # 已完成的单对象属性任务中，确切属性名是明确的新读取动作。
 # 有未决字段时仍优先回答原槽位，不把名称确认改成名称投影。
 if not context.get('pending_business_request') and not context.get('pending_slot') and not context.get('pending_request'):
  from attributes import CATALOG
  tasks=(previous or {}).get('tasks',[])
  if len(tasks)==1 and tasks[0].get('operation')=='attributes' and len(tasks[0].get('filters',[]))==1:
   task=tasks[0];f=task['filters'][0]
   choices=[{'value':[key],'labels':[spec['label']]+({'name':['名称'],'code':['编码']}.get(key,[]))} for key,spec in CATALOG.items()]
   answer=question.strip().strip('。！？!?').casefold()
   if any(answer in [x.casefold() for x in c['labels']] for c in choices):
    slot={'task_id':task['id'],'kind':'choice','field':'properties','identity_value':f['value'],'filter_id':f['id'],'choices':choices}
 if not slot or not previous or slot.get('kind')!='choice':return None
 answer=question.strip().strip('。！？!?').casefold()
 chosen=[c for c in slot.get('choices',[]) if answer in [x.casefold() for x in c['labels']]]
 if len(chosen)!=1:return None
 state=copy.deepcopy(previous);tasks=[t for t in state['tasks'] if t['id']==slot.get('task_id')]
 if len(tasks)!=1:return None
 task=tasks[0];value=chosen[0]['value'];revision=state.get('revision',0)+1
 source={'kind':'user_clarification','turn':revision,'quote':question,'slot':slot['field']}
 if slot['field']=='identifier_field':
  fs=[f for f in task['filters'] if f['id']==slot.get('filter_id') and f['value']==slot.get('identity_value') and f['operator']=='equals']
  if len(fs)!=1 or value not in FIELD_LABELS:return None
  f=fs[0];source['identity_source']=copy.deepcopy(f['source']);f['field']=value;f['source']=source
 elif slot['field'] in ('target','scope','population','properties'):
  if slot.get('identity_value') is not None:
   fs=[f for f in task['filters'] if f['id']==slot.get('filter_id') and f['value']==slot['identity_value']]
   if len(fs)!=1:return None
  task[slot['field']]=value;task['sources'][slot['field']]=source
  if slot['field']=='properties':
   from result_goal import default_goal
   task['result_goal']=default_goal('attributes');task['sources']['result_goal']=source
  if slot['field']=='target' and task['sources'].get('purpose',{}).get('value') in ('identity','introduction'):
   task['sources']['subject_scope']={**source,'value':'explicit'}
 else:return None
 state['revision']=revision;state['last_executed_tasks']=[task['id']]
 state.pop('pending_reason',None);state.pop('pending_tasks',None)
 plan=compile_selected(state,[task['id']],[question])
 return plan,state,[task['id']],{'slot':copy.deepcopy(slot),'answer':question,'value':value,'previous_revision':previous.get('revision',0)}
