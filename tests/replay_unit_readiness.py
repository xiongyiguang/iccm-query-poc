"""冻结未见过的单位对照，用原始行预期和完整分页核验。"""
import sys,json,hashlib
from pathlib import Path
import replay_acceptance as a
BASE=a.ROOT/'docs/.staging/unit-readiness-20260924'
def cases():
 f=lambda field,operator,value:dict(field=field,operator=operator,value=value)
 def search(low='50',high='80',unit='℃'):
  fs=[f('value','gt',low),f('value','lt',high)]
  if unit:fs.append(f('unit','equals',unit))
  return dict(kind='search',filters=fs)
 raw=[
 ('chain','上下限分开算：测量值要高于50摄氏度，且低于80摄氏度；两端都不取。',search()),
 ('chain','只把下界换为51，端点是否包含、上界和温标都照旧。',search('51')),
 ('chain','去掉温标限制，数值上下界保留。',search('51',unit='')),
 ('chain','现在把同一数值区间限制在华氏温标，边界不改。',search('51',unit='℉')),
 ('ambiguous','列出测量值超过43度的测点。',dict(kind='clarify')),
 ('ambiguous','温标用摄氏度。',dict(kind='search',filters=[f('value','gt','43'),f('unit','equals','℃')])),
 ('repeat','高于12°C并且低于36°C的读数记录有哪些？',search('12','36')),
 ('contrast','按华氏度筛选，别按摄氏度：测量值高于11且低于31。',search('11','31','℉')),
 ('none','不用附加任何单位条件，只筛测量值高于-8且低于-2。',search('-8','-2','')),
 ('blank','单位字段没有填写、测量值又大于0的记录有哪些？',dict(kind='search',filters=[f('unit','is_blank',''),f('value','gt','0')])),
 ('present','仅查单位字段已填写、测量值小于0的记录；不限定具体温标。',dict(kind='search',filters=[f('unit','not_blank',''),f('value','lt','0')])),
 ('label','单位等于摄氏度的测点请列出，不设置数值范围。',dict(kind='search',filters=[f('unit','equals','℃')]))]
 return [dict(id='U'+str(i).zfill(2),group=g,question=q,expect=e) for i,(g,q,e) in enumerate(raw,1)]
def freeze():
 sys.path.insert(0,str(a.ROOT/'backend'));from importer import Imports
 store=Imports().load();data={x['kind']:x['rows'] for x in store.dataset};store.db.close()
 cs=cases()
 for c in cs:c['expect']=a.h.build_oracle(c['expect'],data)
 # 鉴权回放客户端会再次检查数据集身份。
 frozen=dict(version=store.version,cases=cs)
 BASE.mkdir(parents=True,exist_ok=True);p=BASE/'frozen.json';assert not p.exists()
 p.write_text(json.dumps(frozen,ensure_ascii=False,indent=2),encoding='utf8');p.with_suffix('.sha256').write_text(a.sha(p.read_bytes()),encoding='ascii')
 print('Frozen',len(cs),'unit cases before calls')
def load(letter):
 assert letter=='U';p=BASE/'frozen.json';raw=p.read_bytes();digest=a.sha(raw);assert digest==p.with_suffix('.sha256').read_text()
 f=json.loads(raw);fix=json.loads((BASE/'oracle-correction-v1.json').read_text(encoding='utf8'))
 assert fix['original_frozen_sha256']==digest and fix['correction']=={'target':'points'}
 for c in f['cases']:
  if c['id'] in fix['case_ids']:
   assert c['expect']['kind']=='search' and 'target' not in c['expect']
   c['expect']['target']='points'
 return f['cases'],dict(path=str(p.relative_to(a.ROOT)),sha256=digest,version=f['version'],correction=fix)
if __name__=='__main__':
 if '--freeze' in sys.argv:freeze()
 else:a.load_suite=load;a.main()
