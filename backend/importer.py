"""校验不可变数据集，通过版本比较后发布，并保留历史快照。"""
import base64,csv,hashlib,io,json,os,threading,time,uuid
from pathlib import Path
from data import Store,ROOT,QueryError
SCHEMA=json.loads((Path(__file__).with_name('import_schema.json')).read_text(encoding='utf-8'))
LABELS={'pbs':'PBS','config':'构型树','equipment_class':'设备类','part_class':'部件类','points':'测点记录'}
MAX_BYTES=16*1024*1024

def counts(store):
    out={k:0 for k in LABELS}
    out.update({r['tree']:r['n'] for r in store.rows('SELECT tree,count(*) n FROM objects GROUP BY tree')})
    out['points']=store.rows('SELECT count(*) n FROM points')[0]['n'];return out

def parse_file(item):
    if not isinstance(item,dict):raise QueryError('文件格式无效。')
    kind=item.get('kind');name=item.get('name','')
    if kind not in SCHEMA or not isinstance(name,str) or not name.lower().endswith('.csv') or len(name)>180 or any(x in name for x in ('/','\\','\x00')):raise QueryError('请选择有效的CSV文件及数据类型。')
    try:raw=base64.b64decode(item['content'],validate=True)
    except Exception:raise QueryError('文件内容无效。') from None
    if not raw or len(raw)>MAX_BYTES:raise QueryError('单个文件需为非空CSV且不超过16MB。')
    text=None
    for encoding in ('utf-8-sig','gb18030'):
        try:text=raw.decode(encoding);break
        except UnicodeDecodeError:pass
    if text is None or '\x00' in text:raise QueryError(name+'：仅支持UTF-8或GB18030编码的CSV。')
    reader=csv.DictReader(io.StringIO(text,newline=''),strict=True)
    fields=reader.fieldnames or []
    if len(fields)!=len(set(fields)) or set(fields)!=set(SCHEMA[kind]):
        missing=set(SCHEMA[kind])-set(fields);extra=set(fields)-set(SCHEMA[kind])
        raise QueryError(name+'：表头不符合所选数据类型。缺少：'+','.join(sorted(missing))+'；多出：'+','.join(sorted(extra))+'。请按所示字段整理。')
    rows=[];key='测量点编码' if kind=='points' else ('对象代码' if '对象代码' in fields else '对象编码')
    for n,row in enumerate(reader,2):
        if None in row or any(v is None for v in row.values()):raise QueryError(f'{name} 第{n}行列数不完整。')
        if not row[key].strip():raise QueryError(f'{name} 第{n}行缺少对象/测点编码。')
        if row[key]!=row[key].strip():raise QueryError(f'{name} 第{n}行编码包含首尾空格。')
        rows.append(row)
        if len(rows)>100000:raise QueryError('单文件超过10万条记录。')
    if not rows:raise QueryError(name+'：文件没有数据记录。')
    return {'kind':kind,'file':name,'sha256':hashlib.sha256(raw).hexdigest(),'rows':rows}

class Imports:
    def __init__(self,directory=ROOT/'inputs'/'imports'):
        self.directory=Path(directory);self.lock=threading.RLock();self.pending={}
    def load(self):
        active=self.directory/'active.json'
        if not active.exists():return Store()
        data=json.loads(active.read_text(encoding='utf-8'));return self.read_snapshot(data['id'])
    def read_snapshot(self,ident):
        if not isinstance(ident,str) or len(ident)!=32 or any(c not in '0123456789abcdef' for c in ident):raise QueryError('快照标识无效。')
        p=self.directory/(ident+'.json')
        if not p.exists():raise QueryError('快照不存在。')
        return Store(dataset=json.loads(p.read_text(encoding='utf-8'))['dataset'])
    def history(self):
        if not self.directory.exists():return []
        rows=[]
        for p in self.directory.glob('*.json'):
            if len(p.stem)!=32:continue
            d=json.loads(p.read_text(encoding='utf-8'));rows.append({k:d[k] for k in ('id','created','version','counts')})
        return sorted(rows,key=lambda d:d['created'],reverse=True)
    def preview(self,current,body):
        with self.lock:
            restore=body.get('restore')
            if restore:
                candidate=self.read_snapshot(restore);mode='restore';files=[];skipped=0
            else:
                mode=body.get('mode')
                if mode not in ('append','replace'):raise QueryError('请选择追加或清空后导入。')
                items=body.get('files')
                if not isinstance(items,list) or not 1<=len(items)<=10:raise QueryError('一次请选择1至10个CSV文件。')
                try:files=[parse_file(f) for f in items]
                except csv.Error:raise QueryError('CSV引号或字段格式损坏，请修正文件后重试。') from None
                dataset=list(current.dataset) if mode=='append' else [];hashes={(f['kind'],f['sha256']) for f in dataset};skipped=0
                for f in files:
                    signature=(f['kind'],f['sha256'])
                    if signature in hashes:skipped+=1;continue
                    dataset.append(f);hashes.add(signature)
                if sum(len(f['rows']) for f in dataset)>300000:raise QueryError('当前快照最多支持30万条导入记录。')
                candidate=Store(dataset=dataset)
            warnings=[]
            absent=candidate.rows("SELECT count(*) n FROM objects o WHERE parent!='' AND NOT EXISTS(SELECT 1 FROM objects p WHERE p.tree=o.tree AND p.code=o.parent)")[0]['n']
            if absent:warnings.append(f'{absent}条父引用在当前数据中缺少目标，查询时会说明详情缺失。')
            no_pbs=candidate.rows("SELECT count(*) n FROM points p WHERE NOT EXISTS(SELECT 1 FROM objects o WHERE o.tree='pbs' AND o.code=p.code)")[0]['n']
            if no_pbs:warnings.append(f'{no_pbs}条测点记录未按编码匹配PBS，可查原始记录但不能确定归属。')
            if mode=='replace':warnings.append('清空范围为全部五类已有数据；本批未提供的数据类型将为空。原文件与历史快照保留。')
            ident=uuid.uuid4().hex
            self.pending={ident:{'store':candidate,'base':current.version,'created':time.monotonic(),'mode':mode}}
            return {'preview':ident,'mode':mode,'before':counts(current),'after':counts(candidate),'warnings':warnings,'skipped_files':skipped,'files':[{'name':f['file'],'kind':f['kind'],'rows':len(f['rows'])} for f in files]}
    def save_snapshot(self,store):
        self.directory.mkdir(parents=True,exist_ok=True);ident=uuid.uuid4().hex
        record={'id':ident,'created':time.time(),'version':store.version,'counts':counts(store),'dataset':store.dataset}
        draft=self.directory/(ident+'.tmp')
        with draft.open('x',encoding='utf-8') as f:json.dump(record,f,ensure_ascii=False);f.flush();os.fsync(f.fileno())
        os.replace(draft,self.directory/(ident+'.json'))
        return ident
    def commit(self,current,preview):
        with self.lock:
            p=self.pending.get(preview)
            if not p or time.monotonic()-p['created']>900:raise QueryError('预览已过期，请重新校验。')
            if p['base']!=current.version:raise QueryError('数据已变化，请重新校验。')
            # 先持久化新旧快照，再修改活动指针；失败时仍使用旧数据。
            self.save_snapshot(current);ident=self.save_snapshot(p['store'])
            pointer=self.directory/('pointer-'+uuid.uuid4().hex+'.tmp')
            with pointer.open('x',encoding='utf-8') as f:json.dump({'id':ident},f);f.flush();os.fsync(f.fileno())
            os.replace(pointer,self.directory/'active.json');self.pending={}
            return p['store']
