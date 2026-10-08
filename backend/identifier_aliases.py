"""只为按原字段标题编号的脱敏名称建立可核验简称，不猜测任意对象尾码。"""
import re
from attributes import CATALOG

def complete_literal_pattern(value):
 """仅在标识自身的ASCII边缘检查扩展字符；中文名称可紧邻中文句中的数字。"""
 edge=r'[A-Za-z0-9_&.#-]'
 left=r'(?<!'+edge+r')' if value and re.fullmatch(edge,value[0]) else ''
 right=r'(?!'+edge+r')' if value and re.fullmatch(edge,value[-1]) else ''
 return left+re.escape(value)+right

def schema_name_aliases(question,store):
 refs=[]
 for domain,field_label in CATALOG['name']['fields'].items():
  if not field_label.endswith('名称'):continue
  short=field_label[:-2]
  if not short:continue
  table='points' if domain=='points' else 'objects'
  for match in re.finditer(re.escape(short)+r'(\d+)(?![\dA-Za-z_])',question):
   full=field_label+match.group(1);sql='SELECT DISTINCT name FROM '+table+' WHERE name=?';args=[full]
   if table=='objects':sql+=' AND tree=?';args.append(domain)
   if len(store.rows(sql,args))!=1:continue
   refs.append({'domain':domain,'field':'name','value':full,'start':match.start(),'end':match.end(),'kind':'schema_alias','quote':match.group(),'raw_field_label':field_label})
 return refs
