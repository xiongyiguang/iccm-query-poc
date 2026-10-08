"""不解释用户自然语言，把构型根对象的关系请求编译为查询。"""
def compile_parts(task):
    from business_request import require
    require(task['target']=='config', '部件范围查询的根对象必须明确为构型。')
    require(task['scope'] in ('direct','all') and task['sources'].get('scope',{}).get('kind')!='default',
            '部件查询须明确直接或全部下级范围。')
    require(task['properties']==[] and task['unit']=={'state':'none','value':''},
            '部件范围查询不能携带属性投影或数值单位。')
    fs=task['filters']
    require(isinstance(fs,list) and len(fs)==1, '部件范围查询须有且仅有一个根对象。')
    f=fs[0]
    require(f['field'] in ('identity','code','name') and f['operator']=='equals' and
            isinstance(f['value'],str) and 0<len(f['value'])<=300,
            '根对象须按完整名称或编码精确定位。')
    return {'operation':'parts','entity':{'tree':'config',f['field']:f['value']},
            'scope':task['scope'],'clarification':''}
