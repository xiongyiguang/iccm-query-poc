"""对提供的五份 CSV 执行只读查询，结果可定位原始来源。"""
import csv
import hashlib
import json
import sqlite3
import threading
from collections import Counter
from query_filters import TARGETS, predicates, describe, target_label
from decimal import Decimal, InvalidOperation
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT.parent / '中广核iCCM项目智能问数DEMO脱敏数据'
TREES = {'pbs': 'pbs', 'config': '构型树', 'equipment_class': '设备类', 'part_class': '部件类'}
OPS = {'data_overview', 'analyze', 'conversation', 'search', 'object', 'equipment', 'equipment_class', 'parts', 'part_class', 'parent', 'measurements', 'alarms', 'measurement', 'duration', 'threshold', 'clarify'}


class QueryError(ValueError):
    pass


class BusinessOutcome(QueryError):
    def __init__(self,status,message,subject=None,candidates=None):
        super().__init__(message)
        self.status=status;self.subject=subject;self.candidates=candidates or []


class Store:
    def __init__(self, source=SOURCE, dataset=None):
        self.lock = threading.RLock()
        self.db = sqlite3.connect(':memory:', check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        from typed_fields import compare,canonical_unit
        self.db.create_function('decimal_compare',3,compare,deterministic=True)
        self.db.create_function('canonical_unit',1,canonical_unit,deterministic=True)
        self.db.executescript('''
          CREATE TABLE objects(tree TEXT,code TEXT,parent TEXT,name TEXT,level TEXT,class_code TEXT,source TEXT,line INT,raw TEXT,PRIMARY KEY(tree,code));
          CREATE INDEX parent_idx ON objects(tree,parent);
          CREATE TABLE ancestors(tree TEXT,child TEXT,ancestor TEXT,depth INT,PRIMARY KEY(tree,child,ancestor));
          CREATE INDEX ancestor_idx ON ancestors(tree,ancestor,depth);
          CREATE TABLE points(line INTEGER PRIMARY KEY,code TEXT,name TEXT,system TEXT,value TEXT,unit TEXT,status TEXT,switch TEXT,time TEXT,raw TEXT);
          CREATE INDEX point_code ON points(code);
        ''')
        self.inputs = []
        if dataset is None:
            dataset=[]
            for kind,name in {**TREES,'points':'测量点数据分析'}.items():
                rows=self.read(source/(name+'.csv'))
                dataset.append({'kind':kind,'file':name+'.csv','sha256':self.inputs[-1]['sha256'],'rows':rows,'seed':True})
        self.dataset=dataset
        self.inputs=[{'file':f['file'],'sha256':f['sha256'],'kind':f['kind']} for f in dataset]
        self.point_refs={};seen={};point_id=1
        for packet in dataset:
            tree=packet['kind']
            source_label=packet['file'] if packet.get('seed') else packet['file']+' ['+packet['sha256'][:12]+']'
            for line,r in enumerate(packet['rows'],2):
                if tree=='points':
                    point_id+=1
                    self.point_refs[point_id]=(source_label,line)
                    self.db.execute('INSERT INTO points VALUES(?,?,?,?,?,?,?,?,?,?)',(point_id,r['测量点编码'],r.get('测量点名称',''),r.get('源系统',''),r.get('测量值',''),r.get('单位',''),r.get('状态',''),r.get('开关',''),r.get('测量时间',''),json.dumps(r,ensure_ascii=False)))
                else:
                    code=r.get('对象代码',r.get('对象编码',''));parent=r.get('父对象代码',r.get('父对象编码',''))
                    key=(tree,code)
                    if key in seen:
                        if seen[key]!=r:raise QueryError(f'{packet["file"]} 第{line}行：对象 {code} 与已有记录冲突；未导入。')
                        continue
                    seen[key]=r
                    self.db.execute('INSERT INTO objects VALUES(?,?,?,?,?,?,?,?,?)',(tree,code,parent,r.get('描述',r.get('对象描述中文','')),r.get('对象层级描述',r.get('对象层级',r.get('层级',''))),r.get('所属部件类代码',''),source_label,line,json.dumps(r,ensure_ascii=False)))
        # 沿真实父引用构建祖先关系并拒绝环路，不按编码前缀判断祖先。
        for tree in TREES:
            mapping = {r['code']: r['parent'] for r in self.db.execute('SELECT code,parent FROM objects WHERE tree=?', (tree,))}
            for child in mapping:
                parent, seen, depth = mapping[child], {child}, 1
                while parent in mapping:
                    if depth>64:raise QueryError('对象层级超过64层，无法导入此结构。')
                    if parent in seen:
                        raise QueryError(f'{tree} 的父子关系存在环：{child}')
                    seen.add(parent)
                    self.db.execute('INSERT INTO ancestors VALUES(?,?,?,?)', (tree, child, parent, depth))
                    parent, depth = mapping[parent], depth + 1
        self.db.commit()
        self.db.execute('PRAGMA query_only=ON')
        self.version = hashlib.sha256(json.dumps(self.inputs, sort_keys=True).encode()).hexdigest()[:12]

    def read(self, path):
        self.inputs.append({'file': path.name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
        with path.open(encoding='gb18030', newline='') as f:
            return list(csv.DictReader(f))

    def rows(self, sql, args=()):
        with self.lock:
            return [dict(r) for r in self.db.execute(sql, args)]

    def obj(self, tree, code):
        rows = self.rows('SELECT * FROM objects WHERE tree=? AND code=?', (tree, code))
        if not rows:
            raise BusinessOutcome('not_found',f'本次导入的{TREES.get(tree, tree)}数据中，未找到编码为「{code}」的对象。请核对名称或编码。',{'tree':tree,'code':code})
        return rows[0]

    def search(self, text='', tree='pbs', parent=None):
        if tree not in TREES:
            raise QueryError('未知对象树')
        if parent is not None:
            return self.rows('SELECT tree,code,name,level,parent FROM objects WHERE tree=? AND parent=? ORDER BY code LIMIT 100', (tree, parent))
        return self.rows('SELECT tree,code,name,level,parent FROM objects WHERE tree=? AND (instr(code,?)>0 OR instr(name,?)>0) ORDER BY code LIMIT 100', (tree, text, text))

    def browse(self,tree='pbs',code=None,text='',page=0):
        if tree not in TREES:raise QueryError('未知对象树')
        page=max(0,int(page));size=24;args=[tree];conditions=['o.tree=?'];current=None;path=[]
        if code is not None:
            obj=self.obj(tree,code)
            current={k:obj[k] for k in ('tree','code','name','level','parent')}
            path=self.rows('SELECT o.tree,o.code,o.name,o.level,o.parent FROM ancestors a JOIN objects o ON o.tree=a.tree AND o.code=a.ancestor WHERE a.tree=? AND a.child=? ORDER BY a.depth DESC',(tree,code))
            conditions.append('o.parent=?');args.append(code)
        elif text:
            conditions.append('(instr(o.code,?)>0 OR instr(o.name,?)>0)');args.extend([text,text])
        else:
            conditions.append('NOT EXISTS(SELECT 1 FROM objects p WHERE p.tree=o.tree AND p.code=o.parent)')
        where=' AND '.join(conditions)
        total=self.rows('SELECT count(*) n FROM objects o WHERE '+where,args)[0]['n']
        page=min(page,max(0,(total-1)//size))
        records=self.rows('SELECT o.tree,o.code,o.name,o.level,o.parent,(SELECT count(*) FROM objects c WHERE c.tree=o.tree AND c.parent=o.code) children FROM objects o WHERE '+where+' ORDER BY o.code LIMIT ? OFFSET ?',args+[size,page*size])
        return {'current':current,'path':path,'records':records,'total':total,'page':page,'page_size':size,'search':text,'tree':tree}

    def ref(self,row):
        source,line=(row['source'],row['line']) if 'source' in row else self.point_refs.get(row['line'],('测量点数据分析.csv',row['line']))
        return {'file': source, 'line': line, 'fields': json.loads(row['raw'])}

    def config(self, entity, evidence):
        tree, code = entity['tree'], entity['code']
        if tree == 'config':
            row = self.obj(tree, code)
        elif tree == 'pbs':
            current = self.obj(tree, code)
            evidence.append(self.ref(current))
            # 优先使用结构对象本身，再查找结构对象祖先。
            candidates = [current] + self.rows('SELECT o.* FROM ancestors a JOIN objects o ON o.tree=a.tree AND o.code=a.ancestor WHERE a.tree=? AND a.child=? ORDER BY a.depth', ('pbs', code))
            row = None
            for candidate in candidates:
                if candidate['level'] not in ('设备', '子设备', '部件') or '&' not in candidate['code']:
                    continue
                found = self.rows('SELECT * FROM objects WHERE tree=? AND code=?', ('config', candidate['code'].split('&', 1)[1]))
                if found and found[0]['level'] == candidate['level']:
                    row = found[0]
                    if candidate['code'] != current['code']:
                        evidence.append(self.ref(candidate))
                    break
            if row is None:
                raise BusinessOutcome('incomplete','已找到现场对象，但缺少经过记录校验的构型关联，暂时无法完成此项查询。',entity)
        else:
            raise QueryError('请选择PBS或构型树中的设备/部件对象。')
        evidence.append(self.ref(row))
        return row

    def relation_result(self, row, relation, target_tree, field, entity, evidence, path, scope, navigate=True):
        """解析直接引用时保留已有的原始事实。"""
        label={'parent':'父对象','equipment_class':'设备类','part_class':'部件类'}[relation]
        code=row[field]
        targets=self.rows('SELECT * FROM objects WHERE tree=? AND code=?',(target_tree,code)) if code else []
        target=targets[0] if targets else None
        state='resolved' if target else ('reference_only' if code else 'not_provided')
        subject={k:row[k] for k in ('tree','code','name','level')}
        ref=self.ref(row);evidence=[*evidence,ref]
        result_path=[*path]
        if not any(x['tree']==row['tree'] and x['code']==row['code'] for x in result_path):result_path.append(subject)
        records=[]
        if target:
            detail={k:target[k] for k in ('tree','code','name','level')}
            records=[{**detail,'evidence':self.ref(target)}]
            evidence.append(self.ref(target));result_path.append(detail)
            answer=f'{label}：{target["name"]}（{code}），类型/层级：{target["level"] or "未提供"}。'
            if relation=='parent' and navigate:entity={'tree':target_tree,'code':code}
        else:
            detail=None
            answer=(f'{row["name"]} 的{label}编码是 {code}，但本次导入数据没有包含该对象的详细记录，因此无法继续展示它的名称和类型。' if code else f'{row["name"]} 的本次记录未提供{label}编码，无法确定其{label}。')
            # 保留实际存在的主体，不能把未解决的引用升级为主体。
            entity={'tree':row['tree'],'code':row['code']}
        evidence=list({(e['file'],e['line']):e for e in evidence}.values())
        result_path=list({(x['tree'],x['code']):x for x in result_path}.values())
        return dict(answer=answer,status='ok',entity=entity,scope=scope,records=records,metrics=[],path=result_path,evidence=evidence,
                    note='本次导入数据中的直接关联；未导入的目标不可继续浏览。'+('已移动到父对象。' if relation=='parent' and navigate and target else '当前讨论对象未改变。'),
                    relation=dict(kind=relation,label=label,status=state,subject=subject,target_code=code or None,target=detail,evidence=ref,navigated=bool(relation=='parent' and navigate and target)))

    def filtered(self, intent):
        query=intent.get('query')
        if isinstance(query,dict) and 'equipment_class' in query:
            from related_parts import execute_related_parts
            return execute_related_parts(self,intent)
        try: conditions,args=predicates(query)
        except ValueError as e: raise QueryError(str(e)) from None
        target=query['target']; tree,level=TARGETS[target]
        entity=intent.get('entity'); scope=intent.get('scope','direct'); evidence=[]
        if target!='points':
            if tree!='*':conditions.insert(0,'r.tree=?');args.insert(0,tree)
            if level:conditions.append('r.level=?');args.append(level)
        if entity:
            if target in ('parts','equipment','config'):
                parent=self.config(entity,evidence); entity={'tree':'config','code':parent['code']}
            else:
                if entity['tree']!=('pbs' if target=='points' else tree):raise QueryError('父对象与查询目标不属于同一对象树。')
                if target=='points' and not self.rows('SELECT code FROM objects WHERE tree=? AND code=?',('pbs',entity['code'])):
                    if not self.rows('SELECT code FROM points WHERE code=?',(entity['code'],)):raise BusinessOutcome('not_found','本次导入数据中未找到指定PBS对象或测点，请核对名称或编码。',entity)
                else:
                    parent=self.obj(entity['tree'],entity['code']);evidence.append(self.ref(parent))
            if target=='points':
                # 监测范围包含根对象及真实 PBS 后代，与测量查询口径一致。
                conditions.append("(r.code=? OR r.code IN (SELECT child FROM ancestors WHERE tree='pbs' AND ancestor=?))")
                args.extend([entity['code'],entity['code']])
            elif scope=='direct':conditions.append('r.parent=?');args.append(entity['code'])
            else:
                conditions.append('r.code IN (SELECT child FROM ancestors WHERE tree=? AND ancestor=?)')
                args.extend([tree,entity['code']])
        rows=self.rows('SELECT r.* FROM '+('points' if target=='points' else 'objects')+' r WHERE '+(' AND '.join(conditions) or '1=1')+' ORDER BY r.code,r.line',args)
        records=[]
        for r in rows:
            if target=='points':
                records.append({'tree':'pbs','code':r['code'],'name':r['name'],'source':r['system'],'value':r['value'] or '未提供','unit':r['unit'] or '未提供','state':r['status'] or '未提供','switch':r['switch'],'time':r['time'] or '未提供','location':'见PBS对象关系','evidence':self.ref(r)})
            else:
                records.append({'tree':r['tree'],'code':r['code'],'name':r['name'],'level':r['level'],'parent':r['parent'],'class_code':r['class_code'],'evidence':self.ref(r)})
        condition=describe(query)
        note='查询口径：'+condition+'。文本按原值区分大小写。'
        if target=='points':note+='重复测点记录保留，不同编码数不等于已核验的物理测点数。'
        if target=='points' and entity is None and query['filters'] and all(f['field'] in ('status','switch') for f in query['filters']):
            census=self.rows('SELECT status,count(*) n FROM points GROUP BY status')
            note+='全表状态参考（不受本次筛选限制）：'+'；'.join((r['status'] or '状态未提供')+' '+str(r['n'])+'条' for r in census)+'。'
        if entity:note+='父对象：'+entity['code']+'；'+('自身及全部PBS下级' if target=='points' else '直接下级' if scope=='direct' else '全部下级')+'。'
        else:note+='范围：本次导入的全部目标记录。'
        label=target_label(query)
        answer=f'符合条件的{label}：{len(rows):,} 条。'
        metrics=[{'label':label,'value':len(rows)}]
        if target=='points':
            unique=len({r['code'] for r in rows})
            answer=f'符合条件的测点记录：{len(rows):,} 条，涉及 {unique:,} 个不同测点编码。'
            metrics.append({'label':'不同测点编码','value':unique})
            from data_context import point_summary,summary_text
            answer+=summary_text(point_summary(records))
        if entity:answer=('当前对象 '+entity['code']+'（'+('自身及全部PBS下级' if target=='points' else '直接下级' if scope=='direct' else '全部下级')+'）：')+answer
        return dict(answer=answer,records=records,evidence=evidence,metrics=metrics,path=[],entity=entity,scope=scope,status='ok',note=note,query=query)

    def detail_query(self, intent):
        from query_filters import validate_detail_query
        try: validate_detail_query(intent['operation'],intent['query'])
        except ValueError as e: raise QueryError(str(e)) from None
        # 本快照缺少的时间戳不能通过选择对象补齐。
        # 先校验完整查询并保留其条件，不能展示候选对象，
        # 让用户误以为选中某个对象就能计算报警时长。
        if intent['operation']=='duration':
            result=self.execute({k:v for k,v in intent.items() if k!='query'})
            result['lookup_query']=intent['query']
            return result
        found=self.filtered({**intent,'operation':'search'})
        records=found['records']; keys={(r['tree'],r['code']) for r in records}
        found['lookup_query']=found.pop('query')
        if len(keys)!=1:
            found['status']='clarify'
            found['answer']=('未找到符合条件的对象，请检查名称、编码或筛选范围。' if not keys else f'找到 {len(keys)} 个不同对象，请从下方选择一个后查看详情。')
            return found
        tree,code=next(iter(keys)); subject={'tree':tree,'code':code}
        if intent['query']['target']!='points':
            result=self.execute({k:v for k,v in {**intent,'entity':subject}.items() if k!='query'})
            result['lookup_query']=intent['query'];result['note']='对象定位：'+describe(intent['query'])+'。'+result['note']
            return result
        found.update(entity=subject,scope='direct',path=[{'tree':tree,'code':code,'name':records[0]['name']}])
        # 保存已精确定位的测点，同时保留原始记录筛选条件。
        filters=list(intent['query']['filters'])
        if not any(f['field']=='code' and f['operator']=='equals' and f['value']==code for f in filters):
            filters=[f for f in filters if f['field'] not in ('name','code','identity')]+[{'field':'code','operator':'equals','value':code}]
        found['lookup_query']={'target':'points','filters':filters}
        if intent['operation']=='duration':
            r=self.execute({'operation':'duration','entity':subject,'scope':'direct','clarification':''})
            r['lookup_query']=intent['query'];return r
        found['note']='对象定位：'+describe(intent['query'])+'。按来源和测量时间逐条展示，不择一冒充实时值。'
        found['answer']=f"{records[0]['name']}（{code}）：找到 {len(records)} 条来源记录。"
        if intent['operation']=='object':
            names=self.rows('SELECT name FROM objects WHERE tree=? AND code=?',('pbs',code))
            found['answer']=f"测点名称：{records[0]['name']}（{code}）。"+('PBS对象名称：'+names[0]['name']+'。' if names else '未匹配PBS对象。')
        if intent['operation']=='threshold':
            from typed_fields import project_thresholds
            return project_thresholds(found,intent)
        return found

    def execute(self, intent):
        if isinstance(intent,dict) and isinstance(intent.get('entity'),dict) and 'identity' in intent['entity']:
            from model import validate
            intent=validate(intent)
            subject=intent['entity'];value=subject['identity']
            found=self.rows('SELECT tree,code,name FROM objects WHERE tree=? AND (code=? OR name=?) ORDER BY code',
                            (subject['tree'],value,value))
            if not found:
                raise BusinessOutcome('not_found','本次导入的构型数据中，未找到名称或编码为「'+value+'」的对象。请核对标识。',subject)
            if len(found)>1:
                raise BusinessOutcome('ambiguous','标识「'+value+'」对应多个构型对象，请指定唯一编码。',subject,found[:20])
            return self.execute({**intent,'entity':{'tree':'config','code':found[0]['code']}})
        if isinstance(intent,dict) and isinstance(intent.get('entity'),dict) and 'name' in intent['entity']:
            from model import validate
            intent=validate(intent)
            subject=intent['entity']
            found=self.rows('SELECT code FROM objects WHERE tree=? AND name=?',(subject['tree'],subject['name']))
            if not found:raise BusinessOutcome('not_found','本次导入的'+TREES[subject['tree']]+'数据中，未找到名称为「'+subject['name']+'」的对象。请核对名称或编码。',subject)
            if len(found)>1:raise BusinessOutcome('ambiguous','名称「'+subject['name']+'」对应多个对象，请指定编码：'+'、'.join(r['code'] for r in found[:20]),subject,found[:20])
            return self.execute({**intent,'entity':{'tree':subject['tree'],'code':found[0]['code']}})
        if not isinstance(intent,dict) or set(intent)-{'operation','entity','scope','clarification','query','message','analysis','properties','navigate','topics','subjects','thresholds'}: raise QueryError('未知查询参数；未执行查询。')
        from relation_check import validate_subjects,execute as check_relations
        try:validate_subjects(intent)
        except ValueError as e:raise QueryError(str(e)) from None
        if intent.get('operation')=='relation_check':return check_relations(self,intent)
        from data_context import validate_topics,explain
        try:validate_topics(intent)
        except ValueError as e:raise QueryError(str(e)) from None
        if intent.get('operation')=='explain':return explain(self,intent)
        if 'navigate' in intent and (intent.get('operation')!='parent' or type(intent['navigate']) is not bool):raise QueryError('导航标识仅适用于父关系，且须为布尔值。')
        from attributes import validate_properties, execute_attributes
        try: validate_properties(intent)
        except ValueError as e: raise QueryError(str(e)) from None
        if intent.get('operation')=='attributes':
            from model import validate
            validate(intent)
            return execute_attributes(self,intent)
        if intent.get('operation')=='analyze':
            from analytics import execute_analysis
            from model import validate
            validate(intent)
            return execute_analysis(self,intent)
        op = intent.get('operation')
        if op not in OPS:
            raise QueryError('不支持的操作；不能执行自由SQL。')
        entity = intent.get('entity')
        if entity is not None and (not isinstance(entity, dict) or set(entity) != {'tree','code'} or entity['tree'] not in TREES):
            raise QueryError('对象格式无效。')
        scope = intent.get('scope', 'direct')
        if scope not in ('direct','all'):
            raise QueryError('层级范围无效。')
        if op=='data_overview':
            if entity is not None or intent.get('query') is not None: raise QueryError('数据概览不接受对象筛选。')
            descriptions=[
                ('pbs','PBS（现场对象目录）','包含功能位置、设备、部件和测点等；按父对象字段组织，同码测点关联测量记录。'),
                ('config','构型树（设备与部件结构）','部分PBS对象按已确认编码规则关联构型，再沿父子关系查看设备和部件，不能直接把两表完整编码等同。'),
                ('equipment_class','设备类（分类字典）','设备构型通过其对应分类节点关联设备类，读取分类描述；字典行数不等于现场设备数量。'),
                ('part_class','部件类（分类字典）','构型中的所属部件类编码关联部件类，说明部件所属分类。'),
                ('points','测量点数据分析（测点记录）','测量点编码关联PBS对象代码，查看数值、时间、状态和阈值；记录数不等于不同测点编码数。')]
            counts={**{k:0 for k in TREES},**{r['tree']:r['n'] for r in self.rows('SELECT tree,count(*) n FROM objects GROUP BY tree')}}
            counts['points']=self.rows('SELECT count(*) n FROM points')[0]['n']
            return dict(answer='本次导入五张表：PBS与构型树描述对象和结构，设备类与部件类提供分类，测点记录提供观测数据。它们通过父子关系、分类引用、同码测点和已确认编码规则关联。',records=[{'cells':[label,counts[key],meaning]} for key,label,meaning in descriptions],evidence=[],metrics=[],path=[],entity=None,status='conversation',scope='direct',note='表格依次为数据、当前记录数、作用与关联。关系说明依据已核对的数据字段和客户编码说明；并非所有记录均可关联。数据为导入快照，缺失引用与字段不补造，不支持实时监测或故障诊断。')
        if op=='search': return self.filtered(intent)
        if intent.get('query') is not None: return self.detail_query(intent)
        if op in ('measurement','threshold'):
            if not entity or entity['tree']!='pbs': raise QueryError('请提供具体测点名称或编码，或选择PBS对象。')
            return self.detail_query({**intent,'entity':None,'query':{'target':'points','filters':[{'field':'code','operator':'equals','value':entity['code']}]}})
        if op=='object' and entity and entity['tree']=='pbs' and self.rows('SELECT code FROM points WHERE code=?',(entity['code'],)):
            return self.detail_query({**intent,'entity':None,'query':{'target':'points','filters':[{'field':'code','operator':'equals','value':entity['code']}]}})
        evidence, records, metrics, path = [], [], [], []
        next_entity = entity
        note = '本次导入快照；名称与数值保留原始脱敏数据。'
        if op=='conversation':
            message=intent.get('message')
            if not isinstance(message,str) or not 0<len(message.strip())<=1200 or entity is not None: raise QueryError('对话回复格式无效。')
            return dict(answer=message,records=[],evidence=[],metrics=[],path=[],entity=None,status='conversation',scope=scope,note='')
        if op == 'clarify':
            return dict(answer=intent.get('clarification') or '请明确对象或查询范围。', records=[], evidence=[], metrics=[], path=[], entity=entity, status='clarify', scope=scope, note='')
        if op == 'duration':
            if entity:
                ps = self.rows('SELECT * FROM points WHERE code=? ORDER BY line', (entity['code'],))
                evidence = [self.ref(r) for r in ps]
            answer = '无法计算报警持续时长或平均时长：这批数据缺少报警开始时间和恢复时间。选择测点也无法补齐这些数据；需补充报警事件记录后再计算。'
            note = '测量时间不是报警开始时间；不能用当前时间减测量时间计算。'
        elif op in ('alarms','measurements'):
            conditions, args = [], []
            if entity:
                if entity['tree'] != 'pbs':
                    raise QueryError('监测归属查询需要PBS对象；构型不能反推唯一现场实例。')
                # 测点可能不存在于 PBS，但存在于监测文件。
                conditions.append('(p.code=? OR p.code IN (SELECT child FROM ancestors WHERE tree=? AND ancestor=?))')
                args.extend([entity['code'], 'pbs', entity['code']])
                source_row = self.rows('SELECT * FROM objects WHERE tree=? AND code=?', ('pbs',entity['code']))
                if source_row: evidence.append(self.ref(source_row[0]))
            if op == 'alarms':
                conditions.extend(['p.status=?', 'p.switch=?'])
                args.extend(['已报警','开启'])
            sql = 'SELECT p.* FROM points p' + (' WHERE ' + ' AND '.join(conditions) if conditions else '') + ' ORDER BY p.code,p.system,p.line'
            points = self.rows(sql, args)
            for r in points:
                location = self.rows("SELECT o.code FROM ancestors a JOIN objects o ON o.tree=a.tree AND o.code=a.ancestor WHERE a.tree='pbs' AND a.child=? AND o.level='功能位置' ORDER BY a.depth LIMIT 1", (r['code'],))
                records.append({'name':r['name'],'code':r['code'],'tree':'pbs','source':r['system'],'value':r['value'] or '未提供','unit':r['unit'] or '未提供','state':r['status'] or '未提供','switch':r['switch'],'time':r['time'] or '未提供','location':location[0]['code'] if location else '未匹配','evidence':self.ref(r)})
            metrics = [{'label':'记录数','value':len(points)}, {'label':'不同测点','value':len({r['code'] for r in points})}]
            answer = f'找到 {len(points):,} 条'+('开启且已报警的记录。' if op == 'alarms' else '测点记录。')
            from data_context import point_summary,summary_text
            answer+=summary_text(point_summary(records))
            note = '筛选：开关=开启，状态=已报警。未匹配PBS的记录仍保留。' if op=='alarms' else note

        else:
            if not entity: raise QueryError('请先选择对象。')
            row = self.obj(entity['tree'], entity['code'])
            evidence.append(self.ref(row))
            path.append({'tree':entity['tree'],'code':row['code'],'name':row['name'],'level':row['level']})
            if op in ('equipment','equipment_class','parts','part_class'):
                row = self.config(entity, evidence)
                path.append({'tree':'config','code':row['code'],'name':row['name'],'level':row['level']})
                next_entity={'tree':'config','code':row['code']}
            if op in ('equipment','equipment_class'):
                if row['level'] != '设备':
                    parents=self.rows("SELECT o.* FROM ancestors a JOIN objects o ON o.tree=a.tree AND o.code=a.ancestor WHERE a.tree='config' AND a.child=? AND o.level='设备' ORDER BY a.depth LIMIT 1", (row['code'],))
                    if not parents: raise BusinessOutcome('incomplete','已找到对象，但本次导入数据未能关联到设备层级祖先，无法继续此项查询。',entity)
                    row=parents[0]; evidence.append(self.ref(row))
                next_entity={'tree':'config','code':row['code']}
                if op=='equipment_class':
                    return self.relation_result(row,op,'equipment_class','parent',next_entity,evidence,path,scope)
                answer=('设备类：' if op=='equipment_class' else '设备构型：')+row['name']+'（'+row['code']+'）。'
                records=[{'tree':row['tree'],'code':row['code'],'name':row['name'],'level':row['level'],'evidence':self.ref(row)}]
            elif op=='parts':
                direct=self.rows("SELECT * FROM objects WHERE tree='config' AND parent=? AND level='部件' ORDER BY code", (row['code'],))
                all_parts=self.rows("SELECT o.* FROM ancestors a JOIN objects o ON o.tree=a.tree AND o.code=a.child WHERE a.tree='config' AND a.ancestor=? AND o.level='部件' ORDER BY o.code", (row['code'],))
                chosen=direct if scope=='direct' else all_parts
                metrics=[{'label':'直接部件','value':len(direct)},{'label':'全部下级部件','value':len(all_parts)}]
                answer=f'{row["code"]} 下有 {len(direct)} 个直接部件、{len(all_parts)} 个全部下级部件。'
                for r in chosen:
                    classes=self.rows("SELECT * FROM objects WHERE tree='part_class' AND code=?", (r['class_code'],))
                    records.append({'tree':'config','code':r['code'],'name':r['name'],'parent':r['parent'],'class':classes[0]['name'] if classes else '未匹配','class_code':r['class_code'],'evidence':self.ref(r),'class_evidence':self.ref(classes[0]) if classes else None})
                note='当前列表：'+('直接部件' if scope=='direct' else '全部下级部件')+'；依据父对象关系递归，按部件层级筛选。'
            elif op=='part_class':
                return self.relation_result(row,op,'part_class','class_code',next_entity,evidence,path,scope)
            elif op=='parent':
                return self.relation_result(row,op,entity['tree'],'parent',entity,evidence,path,scope,intent.get('navigate',True))
            else:
                answer=f'{row["name"]}（{row["code"]}），层级：{row["level"]}。'
                records=[{'tree':row['tree'],'code':row['code'],'name':row['name'],'level':row['level'],'evidence':self.ref(row)}]
        seen=set(); unique=[]
        for ref in evidence:
            key=(ref['file'],ref['line'])
            if key not in seen: seen.add(key); unique.append(ref)
        path = list({(r['tree'],r['code']):r for r in path}.values())
        return dict(answer=answer,records=records,evidence=unique,metrics=metrics,path=path,entity=next_entity,scope=scope,status='data_insufficient' if op=='duration' else 'ok',note=note)
