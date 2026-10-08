"""冻结未见过的问法，预期直接遍历原始记录，不复用查询实现。"""
import argparse,collections,hashlib,http.cookiejar,json,sys,time,uuid,urllib.request,urllib.error
from decimal import Decimal,InvalidOperation
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'docs/.staging/semantic-holdout-20260924'
FIELDS={'name':'测量点名称','code':'测量点编码','value':'测量值','unit':'单位','status':'状态','switch':'开关','source':'源系统','prediction':'预测值','rate':'变化速率'}
for family,label in [('actual','真实值'),('estimate','估计值'),('rate_deviation','变化速率偏差')]:
 for side,cn in [('low','低'),('high','高')]:
  for n in (1,2,3):FIELDS[f'{family}_{side}{n}']=f'{label}报警阈值-{cn}{n}'
def f(field,op,value):return dict(field=field,operator=op,value=value)
def search(filters):return dict(kind='search',target='points',filters=filters)
def attrs(name,props):return dict(kind='attributes',name=name,properties=props)
def cases():
 a=[];b=[]
 def add(dst,g,q,e):dst.append(dict(id=('A' if dst is a else 'B')+str(len(dst)+1).zfill(2),group=g,question=q,expect=e))
 add(a,'range','帮我筛出读数至少50、但还不到80摄氏度的测点。上下界别都算进去。',search([f('value','gte','50'),f('value','lt','80'),f('unit','equals','℃')]))
 add(a,'range','上限改为70，其他筛选要求照旧。',search([f('value','gte','50'),f('value','lt','70'),f('unit','equals','℃')]))
 add(a,'range','这次不限制温度单位，仍按刚才的数值区间查。',search([f('value','gte','50'),f('value','lt','70')]))
 add(a,'neg','列出开关为开启、状态不是已报警的测量点。',search([f('switch','equals','开启'),f('status','not_contains','已报警')]))
 add(a,'neg','现在反过来，只要已报警的；开关条件别动。',search([f('switch','equals','开启'),f('status','equals','已报警')]))
 add(a,'source','源系统2的测点里，单位未填写的列给我。',search([f('source','equals','源系统2'),f('unit','is_blank','')]))
 add(a,'source','把未填写改成已填写，来源不变。',search([f('source','equals','源系统2'),f('unit','not_blank','')]))
 add(a,'empty','筛选预测值缺失的测点，注意空值不是数字0。',search([f('prediction','is_blank','')]))
 add(a,'zero','找测量值恰好为零的记录，缺失的不要混进来。',search([f('value','eq_num','0')]))
 add(a,'rate','列出变化速率小于负0.001的测点，不是绝对值小于0.001。',search([f('rate','lt','-0.001')]))
 add(a,'point','测量点名称7，给我原始读数、变化速率和单位这三项。',attrs('测量点名称7',['value','rate','unit']))
 add(a,'point','只保留真实值报警的第三档高限和预测值。',attrs('测量点名称7',['actual_high3','prediction']))
 add(a,'point','对象换成测量点名称19，还是刚才这两项。',attrs('测量点名称19',['actual_high3','prediction']))
 add(a,'exact','只在构型树中按名称完全等于KOHA30检索，别拿编码来匹配。',dict(kind='object_search',target='config',filters=[f('name','equals','KOHA30')]))
 add(a,'direct','构型KOHA30直接挂了多少个部件？只算下一层。',dict(kind='count',code='KOHA30',scope='direct',level='部件'))
 add(a,'direct','改算所有后代部件，不包含它自己。',dict(kind='count',code='KOHA30',scope='all',level='部件'))
 add(a,'ambig','找温度大于45度的点。',dict(kind='clarify'))
 add(a,'ambig','我是说华氏度，不是摄氏度。',search([f('value','gt','45'),f('unit','equals','℉')]))
 add(a,'multi','分别查测量点名称7的真实值高3和测量点名称19的真实值低2，不要把两者的阈值串了。',dict(kind='batch',items=[attrs('测量点名称7',['actual_high3']),attrs('测量点名称19',['actual_low2'])]))
 add(a,'or','给我测量值小于0或者大于100的测点，满足任意一个条件就算。',dict(kind='unsupported',reason='OR必须明确拒绝或正确分支表达，不能变AND'))
 add(a,'risk','测量点名称19的测量时间显示1970年，据此判断设备今天是否故障。',dict(kind='unsupported',reason='缺少有效实时数据，不能编造故障诊断'))
 add(a,'vague','把那些有问题的设备都找出来。',dict(kind='clarify'))
 add(b,'bounds','温度单位限定℃，读数大于20且不高于40的记录请列出。',search([f('unit','equals','℃'),f('value','gt','20'),f('value','lte','40')]))
 add(b,'bounds','下界调到25，仍然不含下界，其余不变。',search([f('unit','equals','℃'),f('value','gt','25'),f('value','lte','40')]))
 add(b,'switch','找源系统1中开关关闭的测点。',search([f('source','equals','源系统1'),f('switch','equals','关闭')]))
 add(b,'switch','开关改为开启，但只留下已报警的。',search([f('source','equals','源系统1'),f('switch','equals','开启'),f('status','equals','已报警')]))
 add(b,'negative','测量值低于-1的记录有哪些？按有符号数比较。',search([f('value','lt','-1')]))
 add(b,'blank','有单位但预测值没有填的测点，请列出来。',search([f('unit','not_blank',''),f('prediction','is_blank','')]))
 add(b,'name','测量点名称以“测量点名称12”开头的记录有哪些？',search([f('name','starts_with','测量点名称12')]))
 add(b,'name','改为完整名称等于测量点名称12，不要前缀匹配。',search([f('name','equals','测量点名称12')]))
 add(b,'point','读取测量点名称19的真实值低2、真实值高2及估计值高2，未提供的逐项说明。',attrs('测量点名称19',['actual_low2','actual_high2','estimate_high2']))
 add(b,'point','换成测量点名称7，字段清单保持不变。',attrs('测量点名称7',['actual_low2','actual_high2','estimate_high2']))
 add(b,'exact','构型树只匹配名称为MOHB02的对象；零条就返回零条，不用代码兜底。',dict(kind='object_search',target='config',filters=[f('name','equals','MOHB02')]))
 add(b,'scope','统计构型MOHB02的下一层部件个数。',dict(kind='count',code='MOHB02',scope='direct',level='部件'))
 add(b,'scope','下一层限制去掉，我要它整棵子树里的部件数，但不算根。',dict(kind='count',code='MOHB02',scope='all',level='部件'))
 add(b,'unit','有哪些测点读数不低于35度？',dict(kind='clarify'))
 add(b,'unit','以摄氏度为准。',search([f('value','gte','35'),f('unit','equals','℃')]))
 add(b,'multi','测量点名称19要真实值高2；测量点名称7要变化速率。请各查各的。',dict(kind='batch',items=[attrs('测量点名称19',['actual_high2']),attrs('测量点名称7',['rate'])]))
 add(b,'unsupported','把同一测点昨天到今天的变化趋势画出来，并预测明天。',dict(kind='unsupported',reason='单次导入快照不能捏造时间序列或预测'))
 add(b,'vague','把表现最差的那几个找出来给我。',dict(kind='clarify'))
 return {'A':a,'B':b}
def dec(x):
 try:return Decimal(x) if Decimal(x).is_finite() else None
 except (InvalidOperation,TypeError):return None
def match(value,p):
 op=p['operator'];v=p['value']
 if op in ('gt','gte','lt','lte','eq_num'):
  x,y=dec(value),dec(v)
  return x is not None and y is not None and {'gt':x>y,'gte':x>=y,'lt':x<y,'lte':x<=y,'eq_num':x==y}[op]
 return {'equals':value==v,'contains':v in value,'not_contains':v not in value,'starts_with':value.startswith(v),'is_blank':not value.strip(),'not_blank':bool(value.strip())}[op]
def build_oracle(e,data):
 e=dict(e);kind=e['kind']
 if kind in ('search','object_search'):
  rows=data['points' if kind=='search' else e['target']]
  fields=FIELDS if kind=='search' else {'name':'对象描述中文','code':'对象代码'}
  found=[r for r in rows if all(match(r.get(fields[p['field']],''),p) for p in e['filters'])]
  e.update(total=len(found),row_hash=hashlib.sha256(json.dumps(found,ensure_ascii=False,sort_keys=True).encode()).hexdigest())
 elif kind=='attributes':
  rows=[r for r in data['points'] if r['测量点名称']==e['name']];assert rows
  e.update(code=rows[0]['测量点编码'],values={p:[r[FIELDS[p]] for r in rows] for p in e['properties']})
 elif kind=='count':
  rows={r['对象代码']:r for r in data['config']};n=0
  for code,r in rows.items():
   parent=r['父对象代码'];seen=set()
   while parent in rows and parent not in seen:
    if parent==e['code']:
     n+=r['对象层级描述']==e['level'];break
    if e['scope']=='direct':break
    seen.add(parent);parent=rows[parent]['父对象代码']
  e['total']=n
 elif kind=='batch':e['items']=[build_oracle(x,data) for x in e['items']]
 return e
def freeze():
 if (OUT/'frozen.json').exists():raise SystemExit('Frozen suite exists; never overwrite.')
 sys.path.insert(0,str(ROOT/'backend'));from importer import Imports
 s=Imports().load();data={x['kind']:x['rows'] for x in s.dataset};suites=cases()
 # 这里只防止问句逐字重复，是维护者编写的留出集，不是第三方盲测。
 old='\n'.join(p.read_text(encoding='utf-8-sig') for p in (ROOT/'tests').glob('replay_*.py') if p.name!=Path(__file__).name)
 for group in suites.values():
  for c in group:
   assert c['question'] not in old,c['id']
   c['expect']=build_oracle(c['expect'],data)
 obj={'created':'2026-09-24','baseline_commit':'05312be','version':s.version,'design':'A diagnostic; B sealed until common-mechanism fix; same author, independent source-row oracle','suites':suites}
 raw=json.dumps(obj,ensure_ascii=False,indent=2).encode();OUT.mkdir(parents=True,exist_ok=True)
 (OUT/'frozen.json').write_bytes(raw);(OUT/'frozen.sha256').write_text(hashlib.sha256(raw).hexdigest(),encoding='ascii')
 s.db.close();print('Frozen A',len(suites['A']),'B',len(suites['B']),hashlib.sha256(raw).hexdigest())
def normalized(filters):
 numeric={p['field'] for p in filters if p['operator'] in ('gt','gte','lt','lte','eq_num')}
 filters=[p for p in filters if not(p['field'] in numeric and p['operator']=='not_blank')]
 return sorted((p['field'],'eq_num' if p['field'] in ('value','prediction','rate') and p['operator']=='equals' else p['operator'],str(dec(p['value'])) if p['operator'] in ('gt','gte','lt','lte','eq_num') else p['value']) for p in filters)
def check(e,r):
 kind=e['kind'];plan=(r.get('trace') or {}).get('validated_intent') or {};q=r.get('query') or plan.get('query') or {}
 result={'understanding':False,'conditions':False,'result':False}
 ok=r.get('status')=='ok'
 if kind in ('search','object_search'):
  result['understanding']=q.get('target')==e['target'] and plan.get('operation') in ('search','object','attributes')
  actual=q.get('filters',[]);expected=e['filters']
  # identity 不等同于显式 name/code 条件。
  result['conditions']=normalized(actual)==normalized(expected)
  fields=FIELDS if kind=='search' else {'name':'对象描述中文','code':'对象代码'}
  rows_valid=all(all(match((row.get('evidence') or {}).get('fields',{}).get(fields[p['field']],''),p) for p in e['filters']) for row in r.get('records',[]))
  result['result']=rows_valid and r.get('total')==e['total'] and (ok or e['total']==0 and r.get('status') in ('not_found','clarify'))
 elif kind=='missing_parent':
  entity=plan.get('entity') or {};valid=r.get('status')=='not_found' and entity.get('code')==e['code'] and not r.get('metrics')
  result={k:valid for k in result}
 elif kind=='attributes':
  entity=r.get('entity') or {};result['understanding']=entity.get('code')==e['code']
  props={x['property']:x for x in r.get('attributes',[])}
  thresh=r.get('threshold_details',[])
  result['conditions']=set(e['properties'])<=set(props or r.get('requested_thresholds',[]))
  good=True
  for p,values in e['values'].items():
   if p in props:
    good &= props[p].get('value') in values and props[p].get('status')==('missing' if not values[0] else 'known')
   elif thresh:good &= [x['thresholds'].get(FIELDS[p]) for x in thresh]==[v or '未提供' for v in values]
   else:good=False
  result['result']=ok and good
 elif kind=='count':
  ent=plan.get('entity') or r.get('entity') or {};result['understanding']=ent.get('code')==e['code']
  result['conditions']=plan.get('scope')==e['scope'] and (plan.get('operation')=='parts' or (plan.get('query') or {}).get('target')=='parts')
  vals=[x.get('value') for x in r.get('metrics',[])]
  result['result']=ok and (e['total'] in vals or r.get('total')==e['total'])
 elif kind=='batch':
  items=r.get('items',[]);checks=[]
  for spec in e['items']:
   matches=[x for x in items if (x.get('entity') or {}).get('code')==spec['code']]
   checks.append(check(spec,matches[0]) if len(matches)==1 else {k:False for k in result})
  result={k:len(items)==len(e['items']) and all(x[k] for x in checks) for k in result}
 else:
  safe=r.get('status') in ('clarify','conversation','unsupported') and not r.get('records') and not r.get('items')
  if kind=='unsupported' and r.get('status')=='batch':
   items=r.get('items',[])
   boundary=any(y.get('status') in ('conversation','clarify') and ('不提供故障诊断' in y.get('answer','') or '无连续历史序列' in y.get('answer','')) for y in items)
   # 独立的不支持能力预期，不授权执行伴随查询；
   # 合法混合请求必须逐项定义明确的多任务预期。
   only_notes=all(y.get('status') in ('conversation','clarify','unsupported') and
                  not any(y.get(k) for k in ('records','items','attributes','metrics','threshold_details')) for y in items)
   safe=boundary and only_notes
  # 这些结果需人工核验，不能因系统拒绝执行就自动判为通过。
  result={k:safe for k in result};result['needs_review']=True
 return result
def main():
 p=argparse.ArgumentParser();p.add_argument('--freeze',action='store_true');p.add_argument('--suite',choices=['A','B','C','D','E']);p.add_argument('--url',default='http://106.53.130.181:8899');p.add_argument('--rounds',type=int,default=2);p.add_argument('--run');args=p.parse_args()
 if args.freeze:return freeze()
 stem='frozen-'+args.suite if args.suite in ('C','D','E') else 'frozen'
 raw=(OUT/(stem+'.json')).read_bytes();assert hashlib.sha256(raw).hexdigest()==(OUT/(stem+'.sha256')).read_text()
 frozen=json.loads(raw)
 correction=None
 if args.suite=='C':
  correction=json.loads((OUT/'C-oracle-correction.json').read_text(encoding='utf-8'))
  assert correction['original_frozen_sha256']==hashlib.sha256(raw).hexdigest()
  for c in frozen['suites']['C']:
   if c['id'] in correction['case_ids']:c['expect']={**c['expect'],'kind':'missing_parent'}
 path=OUT/(args.run+'.json');assert not path.exists()
 op=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()));meta={};sessions=set();results=[]
 def call(endpoint,body):
  headers={'Content-Type':'application/json','Origin':args.url}
  if meta:headers['X-Demo-Token']=meta['token']
  try:
   with op.open(urllib.request.Request(args.url+endpoint,data=json.dumps(body).encode(),headers=headers),timeout=120) as x:return x.status,json.load(x)
  except urllib.error.HTTPError as x:return x.code,json.load(x)
 cloud=not args.url.startswith('http://127.0.0.1')
 if cloud:
  creds={k.strip():v.strip() for line in (ROOT/'.local/cloud-8899-access.txt').read_text(encoding='utf-8-sig').splitlines() if ':' in line for k,v in [line.split(':',1)]}
  assert call('/api/auth/login',{'username':creds['Username'],'password':creds['Password']})[0]==200;creds.clear()
 meta=json.load(op.open(args.url+'/api/meta'));assert meta['version']==frozen['version']
 try:
  for n in range(args.rounds):
   prefix='blind-'+uuid.uuid4().hex[:12]
   for c in frozen['suites'][args.suite]:
    sid=prefix+'-'+c['group'];sessions.add(sid);t=time.perf_counter()
    status,r=call('/api/query',dict(session=sid,question=c['question'],version=meta['version'],trace=True))
    try:checks=check(c['expect'],r)
    except (ValueError,TypeError,KeyError,IndexError) as ex:checks=dict(understanding=False,conditions=False,result=False,assertion_error=str(ex))
    entry={**c,'round':n+1,'http':status,'seconds':round(time.perf_counter()-t,3),'checks':checks,'passed':all(checks[k] for k in ('understanding','conditions','result')),'response':r}
    results.append(entry);path.write_text(json.dumps(dict(frozen_sha256=hashlib.sha256(raw).hexdigest(),oracle_correction=correction,url=args.url,results=results),ensure_ascii=False,indent=2),encoding='utf-8')
    print(c['id'],n+1,entry['passed'],checks,flush=True)
   for sid in sessions:call('/api/reset',{'session':sid})
   sessions.clear()
 finally:
  for sid in sessions:call('/api/reset',{'session':sid})
  if cloud:call('/api/auth/logout',{})
 print('PASSED',sum(x['passed'] for x in results),'/',len(results),flush=True)
if __name__=='__main__':main()

