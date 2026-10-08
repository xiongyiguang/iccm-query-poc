"""只读引用诊断，不承担自然语言意图分类。"""
import copy

def diagnose(store,plan,question):
    issues=[]
    def visit(intent,path):
        if intent.get('operation')=='batch':
            for n,task in enumerate(intent['tasks']):visit(task['intent'],path+['tasks',n,'intent'])
            return
        refs=[]
        e=intent.get('entity')
        if e:refs.append((path+['entity'],e['tree'],'name' if 'name' in e else 'code',e.get('name',e.get('code'))))
        q=intent.get('query') or {}
        rel=q.get('equipment_class')
        if rel:refs.append((path+['query','equipment_class'],'equipment_class',rel['field'],rel['value']))
        for loc,tree,field,value in refs:
            sql="SELECT code FROM objects WHERE tree=? AND "+({'name':'name=?','code':'code=?','identity':'(name=? OR code=?)'}[field])
            if store.rows(sql,[tree,value]+([value] if field=='identity' else [])):continue
            # 只有在原问题中完整出现的数据库名称才能作为依据。
            candidates=store.rows("SELECT tree,code,name FROM objects WHERE tree=? AND name<>'' AND instr(?,name)>0 AND instr(name,?)>0 ORDER BY length(name) DESC,code LIMIT 11",(tree,question,value))
            if not candidates or len(candidates)>10:continue
            issues.append({'id':len(issues),'path':loc,'field':field,'value':value,'candidates':candidates})
    visit(plan,[])
    return issues

def apply_repairs(plan,issues,response):
    if not isinstance(response,dict) or set(response)!={'repairs'} or not isinstance(response['repairs'],list):raise ValueError('引用复核格式无效。')
    fixed=copy.deepcopy(plan);seen=set()
    for item in response['repairs']:
        if not isinstance(item,dict) or set(item)!={'reference','candidate'} or type(item['reference']) is not int or type(item['candidate']) is not int:raise ValueError('引用复核索引无效。')
        n=item['reference'];c=item['candidate']
        if n in seen or not 0<=n<len(issues) or not 0<=c<len(issues[n]['candidates']):raise ValueError('引用复核候选越界。')
        seen.add(n);issue=issues[n];candidate=issue['candidates'][c];target=fixed
        for key in issue['path'][:-1]:target=target[key]
        leaf=issue['path'][-1]
        if leaf=='entity':target[leaf]={'tree':candidate['tree'],'name':candidate['name']}
        else:target[leaf]={**target[leaf],'field':'name','value':candidate['name']}
    return fixed
