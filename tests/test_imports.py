import base64,csv,io,json,sys,threading,unittest,uuid,urllib.request,urllib.error
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from importer import Imports,SCHEMA,parse_file,counts
from data import Store,QueryError,ROOT
from data_context import knowledge_context

def file(kind='pbs',code='IMPORT-A',parent='',value='',name='现场.csv',encoding='utf-8-sig',reverse=False):
    fields=list(SCHEMA[kind]);fields=fields[::-1] if reverse else fields
    r={k:'' for k in fields};r['测量点编码' if kind=='points' else '对象代码' if '对象代码' in fields else '对象编码']=code
    if kind=='points':r.update({'测量点名称':'现场测点','测量值':value,'真实值报警阈值-高1':'3'})
    else:r['父对象代码' if '父对象代码' in fields else '父对象编码']=parent;r['对象描述中文' if '对象描述中文' in fields else '描述']='现场对象'
    text=io.StringIO(newline='');w=csv.DictWriter(text,fields);w.writeheader();w.writerow(r)
    return {'kind':kind,'name':name,'content':base64.b64encode(text.getvalue().encode(encoding)).decode()}

class ImportTests(unittest.TestCase):
 def setUp(self):
  self.manager=Imports(ROOT/'docs/.staging/import-20260920/tests'/uuid.uuid4().hex);self.empty=Store(dataset=[])
 def preview(self,files,current=None,mode='append'):
  return self.manager.preview(current or self.empty,{'mode':mode,'files':files})
 def test_encoding_and_header_order(self):
  for encoding in ['utf-8-sig','gb18030']:
   packet=parse_file(file(encoding=encoding,reverse=True));self.assertEqual(packet['rows'][0]['对象代码'],'IMPORT-A')
 def test_invalid_headers_payload_paths(self):
  for item in [dict(file(),name='../bad.csv'),dict(file(),content='bad!'),dict(file(),kind='other'),dict(file(),content=base64.b64encode(b'a,b\n1,2').decode())]:
   with self.assertRaises(QueryError):parse_file(item)
 def test_empty_record_key_and_file(self):
  with self.assertRaises(QueryError):parse_file(file(code=''))
  with self.assertRaises(QueryError):parse_file(dict(file(),content=''))
 def test_preview_does_not_publish(self):
  r=self.preview([file()]);self.assertEqual(counts(self.empty)['pbs'],0);self.assertEqual(r['after']['pbs'],1);self.assertFalse((self.manager.directory/'active.json').exists())
 def test_commit_restart_and_history_restore(self):
  r=self.preview([file()]);one=self.manager.commit(self.empty,r['preview']);self.assertEqual(counts(self.manager.load())['pbs'],1)
  old=next(h for h in self.manager.history() if h['counts']['pbs']==0)
  p=self.manager.preview(one,{'restore':old['id']});restored=self.manager.commit(one,p['preview']);self.assertEqual(counts(restored)['pbs'],0)
 def test_append_replace_and_identical_file(self):
  a=self.manager.commit(self.empty,self.preview([file()])['preview'])
  p=self.preview([file(code='IMPORT-B',name='第二.csv')],a);self.assertEqual(p['after']['pbs'],2)
  p=self.preview([file(name='改名.csv')],a);self.assertEqual(p['after']['pbs'],1);self.assertEqual(p['skipped_files'],1)
  p=self.preview([file('points',value='9')],a,'replace');self.assertEqual(p['after']['pbs'],0);self.assertEqual(p['after']['points'],1)
 def test_conflict_does_not_change_active(self):
  a=self.manager.commit(self.empty,self.preview([file()])['preview'])
  with self.assertRaises(QueryError):self.preview([file(parent='NEW')],a)
  self.assertEqual(self.manager.load().version,a.version)
 def test_cycle_rejected_missing_reference_warned(self):
  with self.assertRaises(QueryError):self.preview([file(code='A',parent='B'),file(code='B',parent='A')])
  r=self.preview([file(parent='ABSENT')]);self.assertTrue(r['warnings'])
 def test_multisource_point_evidence_and_threshold(self):
  a=self.manager.commit(self.empty,self.preview([file('points',code='P',value='9',name='first.csv')])['preview'])
  b=self.manager.commit(a,self.preview([file('points',code='P',value='0',name='second.csv')],a)['preview'])
  r=b.execute({'operation':'threshold','entity':None,'scope':'direct','query':{'target':'points','filters':[{'field':'code','operator':'equals','value':'P'}]}})
  self.assertEqual([x['difference'] for x in r['records']],['6','-3']);self.assertEqual([x['evidence']['line'] for x in r['records']],[2,2]);self.assertIn('second.csv',r['records'][1]['evidence']['file'])
 def test_same_file_internal_duplicates_preserved(self):
  f=file('points',value='0');raw=base64.b64decode(f['content']).decode('utf-8-sig');f['content']=base64.b64encode((raw+raw.splitlines()[1]+'\n').encode()).decode()
  self.assertEqual(self.preview([f])['after']['points'],2)
 def test_stale_preview_and_failed_persistence(self):
  p=self.preview([file()]);other=Store(dataset=[parse_file(file(code='OTHER'))])
  with self.assertRaises(QueryError):self.manager.commit(other,p['preview'])
  with patch('importer.os.replace',side_effect=OSError('disk')):
   with self.assertRaises(OSError):self.manager.commit(self.empty,p['preview'])
  self.assertFalse((self.manager.directory/'active.json').exists());self.assertEqual(counts(self.empty)['pbs'],0)
 def test_partial_dataset_knowledge(self):
  k=knowledge_context(self.empty);self.assertEqual(k['point_to_pbs']['matched_records'],0);self.assertEqual(k['tree_counts']['pbs'],0)
  s=Store(dataset=[parse_file(file())]);self.assertIn('是否脱敏',knowledge_context(s)['facts']['provenance']);self.assertEqual(s.execute({'operation':'data_overview','entity':None,'scope':'direct'})['records'][1]['cells'][1],0)

class ImportHttpTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  import app
  cls.app=app;cls.old=(app.STORE,app.IMPORTS);app.STORE=Store(dataset=[]);app.IMPORTS=Imports(ROOT/'docs/.staging/import-20260920/http'/uuid.uuid4().hex);app.SESSIONS.clear()
  cls.server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler);cls.url='http://127.0.0.1:'+str(cls.server.server_port);threading.Thread(target=cls.server.serve_forever,daemon=True).start()
 @classmethod
 def tearDownClass(cls):cls.server.shutdown();cls.server.server_close();cls.app.STORE,cls.app.IMPORTS=cls.old;cls.app.SESSIONS.clear()
 def post(self,path,body,token=True):
  req=urllib.request.Request(self.url+path,json.dumps(body).encode(),{'Content-Type':'application/json','X-Demo-Token':self.app.TOKEN if token else 'bad'})
  with urllib.request.urlopen(req) as r:return json.load(r)
 def test_import_flow_version_busy_and_permissions(self):
  with self.assertRaises(urllib.error.HTTPError) as e:self.post('/api/import/preview',{'mode':'replace','files':[file()]},False)
  self.assertEqual(e.exception.code,403)
  old=self.app.STORE.version;p=self.post('/api/import/preview',{'mode':'replace','files':[file()]})
  self.app.SESSIONS['busy']={'busy':True}
  with self.assertRaises(urllib.error.HTTPError):self.post('/api/import/commit',{'preview':p['preview']})
  self.assertEqual(self.app.STORE.version,old);self.app.SESSIONS['busy']['busy']=False
  r=self.post('/api/import/commit',{'preview':p['preview']});self.assertEqual(r['counts']['pbs'],1);self.assertEqual(self.app.SESSIONS,{})
  with self.assertRaises(urllib.error.HTTPError):self.post('/api/query',{'version':old,'session':'old','intent':{'operation':'data_overview','entity':None,'scope':'direct'}})
  q=self.post('/api/query',{'version':r['version'],'session':'new','intent':{'operation':'search','entity':None,'scope':'direct','query':{'target':'pbs','filters':[]}}});self.assertEqual(q['total'],1)

if __name__=='__main__':unittest.main()
