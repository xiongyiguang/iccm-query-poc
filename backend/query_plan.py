"""执行数量受限的独立任务，不在此拆分自然语言。"""
from data import QueryError,BusinessOutcome
from model import validate

def exact_lookup_subject(intent,result,version):
 """只有实际执行的精确单对象查询才能确立该主体事实。"""
 from query_filters import TARGETS
 if result.get('status')!='ok' or intent.get('operation')!='search' or intent.get('entity') or intent.get('scope')!='direct':return None
 q=intent.get('query') or {};target=q.get('target')
 if set(q)!={'target','filters'} or target not in TARGETS or target in ('objects','points'):return None
 fs=q['filters'];records=result.get('records',[])
 if not isinstance(fs,list) or not isinstance(records,list) or len(fs)!=1 or len(records)!=1 or result.get('total',len(records))!=1:return None
 f=fs[0];row=records[0]
 if not isinstance(f,dict) or not isinstance(row,dict):return None
 if f.get('operator')!='equals' or f.get('field') not in ('identity','name','code'):return None
 tree=TARGETS[target][0]
 if row.get('tree')!=tree or not row.get('code') or not isinstance(row.get('name'),str):return None
 aliases=(row['name'],row['code']) if f['field']=='identity' else (row[f['field']],)
 if not f.get('value') or f['value'] not in aliases:return None
 return {k:row[k] for k in ('tree','code','name')}|{'version':version}

def task_context(intent,result):
 if result.get('status')=='clarify':
  return {'pending_request':intent,'clarification':result['answer']}
 if result.get('outcome'):
  return {'pending_request':intent,'outcome':result['outcome']}
 c={'entity':result['entity'],'scope':result['scope'],'operation':intent['operation']}
 if result.get('requested_properties'):
  c['requested_properties']=result['requested_properties']
  c['answered_properties']=result.get('coverage',{}).get('answered',[])
 if result.get('analysis'):c['analysis']=result['analysis']
 if result.get('query_receipt'):c['query_receipt']=result['query_receipt']
 if result.get('lookup_query'):c['lookup_query']=result['lookup_query']
 if result.get('query'):c['query']=result['query']
 elif intent['operation']=='parts':c['query']={'target':'parts','filters':[]}
 elif intent['operation'] in ('alarms','measurements'):
  c['query']={'target':'points','filters':([{'field':'status','operator':'equals','value':'已报警'},{'field':'switch','operator':'equals','value':'开启'}] if intent['operation']=='alarms' else [])}
 if result.get('relation'):
  c['relation']=result['relation']
  # 已定位的父对象成为明确焦点，不再保留子对象定位条件。
  c.pop('lookup_query',None)
 return c

def execute_plan(store,intent):
 intent=validate(intent)
 if intent['operation']!='batch':return execute_one(store,intent)
 results=[]
 for i,task in enumerate(intent['tasks'],1):
  try:r=execute_one(store,task['intent'])
  except QueryError as e:
   r=dict(answer=str(e),status='error',records=[],evidence=[],metrics=[],path=[],entity=None,scope='direct',note='此项未完成；其他独立查询正常处理。')
  r={**r,'task_number':i,'task_question':task['question']}
  r['task_context']=task_context(task['intent'],r) if r['status'] in ('ok','clarify') or r.get('outcome') else {'entity':None,'scope':'direct','operation':task['intent']['operation']}
  if r['status']=='clarify':r['task_context']['pending_question']=task['question']
  results.append(r)
 answer='已分别处理 '+str(len(results))+' 个问题。'
 # 只识别已执行的比较计划，不在此处对用户措辞分类。
 if all(r['status']=='ok' and r.get('query') and not r['entity'] for r in results):
  signatures={(r['query']['target'],tuple(sorted((f['field'],f['operator'],f['value']) for f in r['query']['filters']))) for r in results}
  comparisons=[{('pbs',(('level','equals','设备'),)),('equipment',()),('equipment_class',())},
               {('pbs',(('level','equals','部件'),)),('parts',()),('part_class',())},
               {('pbs',(('level','equals','时序测点'),)),('points',())}]
  if signatures in comparisons:
   answer='本次导入数据按不同口径统计：'+'；'.join(m['label']+' '+str(m['value']) for r in results for m in r['metrics'])+'。这些数量不能相加或互换，请按需要选择对应结果。'
 return dict(answer=answer,status='batch',records=[],evidence=[],metrics=[],path=[],entity=None,scope='direct',note='',items=results)


def execute_one(store,intent):
 try:result=store.execute(intent)
 except BusinessOutcome as issue:
  result=dict(status=issue.status,answer=str(issue),records=[],metrics=[],evidence=[],path=[],entity=None,scope=intent['scope'],
              note='尚未完成对象定位或关联核验，未计算数量；原请求已保留，可更正后继续。',
              outcome={'kind':issue.status,'subject':issue.subject,'candidates':issue.candidates,'count_computed':False},pending_request=intent)
 if result.get('status')=='clarify' and result.get('lookup_query'):
  kind='ambiguous' if result.get('records') else 'not_found'
  result.update(status=kind,metrics=[],pending_request=intent,outcome={'kind':kind,'subject':result['lookup_query'],'candidates':[{'tree':r.get('tree'),'code':r.get('code'),'name':r.get('name')} for r in result.get('records',[])[:20]],'count_computed':False})
 if result.get('status')!='ok':
  if result.get('outcome',{}).get('kind')=='not_found':
   from identity_candidates import suggest
   result=suggest(store,intent,result)
  return result
 query=result.get('query') or intent.get('query')
 receipt={'operation':intent['operation'],'requested_entity':intent.get('entity'),
          'resolved_entity':result.get('entity'),'scope':result['scope'],
          'query':query,'analysis':intent.get('analysis'),
          'grain':result.get('grain') or ('measurement_record' if query and query['target']=='points' else 'config_object' if query and query['target'] in ('parts','equipment','config') else 'object'),
          'classification_coverage':result.get('classification_coverage')}
 result['query_receipt']=receipt
 subject=exact_lookup_subject(intent,result,store.version)
 if subject:receipt['confirmed_subject']=subject
 return result
