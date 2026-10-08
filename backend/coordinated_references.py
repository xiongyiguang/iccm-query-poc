"""依据完整已知标识解析并列数字后缀省略，始终以原数据验证展开值。"""
import re

def coordinated_literals(question,store,anchors):
 result=[]
 for anchor in anchors:
  if anchor.get('field') not in ('name','code'):continue
  value=anchor['value'];suffix=re.search(r'\d+$',value)
  if not suffix or suffix.start()==0:continue
  tail=question[anchor['end']:]
  matched=re.match(r'\s*(?:和|与|及|、|，|,)\s*(\d+)(?=$|[^\dA-Za-z_])',tail)
  if not matched:continue
  expanded=value[:suffix.start()]+matched.group(1);domain=anchor['domain'];field=anchor['field']
  if expanded==value:continue
  table='points' if domain=='points' else 'objects';sql='SELECT DISTINCT '+field+' value FROM '+table+' WHERE '+field+'=?';args=[expanded]
  if table=='objects':sql+=' AND tree=?';args.append(domain)
  rows=store.rows(sql,args)
  if len(rows)!=1:continue
  start=anchor['end']+matched.start(1);end=anchor['end']+matched.end(1)
  result.append({'domain':domain,'field':field,'value':expanded,'start':start,'end':end,'kind':'coordinated_literal','quote':question[anchor['start']:end],'anchor':{k:anchor[k] for k in ('field','value','domain','start','end')}})
 return result
