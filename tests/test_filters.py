import unittest,sys,json,csv
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from data import Store,QueryError,SOURCE
from query_filters import validate_query
from model import validate,ModelUnavailable

class Filters(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.s=Store()
 def query(self,target,filters,entity=None,scope='direct'):
  return self.s.execute({'operation':'search','entity':entity,'scope':scope,'query':{'target':target,'filters':filters}})
 def f(self,field,value,operator='contains'):return {'field':field,'operator':operator,'value':value}
 def test_name_not_code(self):
  r=self.query('parts',[self.f('name','ABC')]);self.assertEqual(r['records'],[])
  with (SOURCE/'构型树.csv').open(encoding='gb18030',newline='') as f:rows=list(csv.DictReader(f))
  expected=[x for x in rows if x.get('对象层级描述',x.get('对象层级'))=='部件' and '1' in x.get('描述',x.get('对象描述中文',''))]
  r=self.query('parts',[self.f('name','1')]);self.assertGreater(len(expected),20);self.assertEqual(len(r['records']),len(expected))
 def test_literal_no_wildcard(self):
  for value in ['%',"' OR 1=1 --",'_']:
   r=self.query('part_class',[self.f('name',value)]);self.assertEqual(r['records'],[])
 def test_parent_scope_and_evidence(self):
  e={'tree':'config','code':'MOHB01'}
  self.assertEqual(len(self.query('parts',[],e)['records']),51)
  r=self.query('parts',[],e,'all');self.assertEqual(len(r['records']),221)
  self.assertTrue(all(x['evidence']['file']=='构型树.csv' for x in r['records']))
 def test_point_states_and_duplicates(self):
  r=self.query('points',[self.f('status','已报警','equals'),self.f('switch','开启','equals')]);self.assertEqual(len(r['records']),48)
  r=self.query('points',[self.f('status','','is_blank')]);self.assertTrue(all(x['state']=='未提供' for x in r['records']))
  r=self.query('points',[self.f('code','XJ2ABC001PO.ZRs.2ABC003KA.UGb','equals')]);self.assertEqual(len(r['records']),4)
 def test_unknown_predicates_fail(self):
  for f in [self.f('SQL','x'),self.f('name','','contains'),self.f('name','x','gt')]:
   with self.assertRaises(QueryError):self.query('parts',[f])
  with self.assertRaises(QueryError):self.s.execute({'operation':'parts','entity':{'tree':'config','code':'MOHB01'},'query':{'target':'parts','filters':[]}})
 def test_all_targets_and_and(self):
  for target in ['parts','equipment','config','pbs','equipment_class','part_class','points']:
   r=self.query(target,[self.f('name','1'),self.f('name','2','not_contains')]);self.assertTrue(all('1' in x['name'] and '2' not in x['name'] for x in r['records']))
 def test_schema_guard(self):
  good={'operation':'search','entity':None,'scope':'direct','clarification':'','query':{'target':'parts','filters':[self.f('name','ABC')]}}
  self.assertEqual(validate(good),good)
  # V5 规范化保留全部条件，不能丢弃条件。
  self.assertEqual(validate({**good,'operation':'parts'}),good)
  detail={**good,'operation':'equipment_class'}
  self.assertEqual(validate(detail),detail)
  r=self.s.execute(detail)
  self.assertEqual(r['status'],'clarify');self.assertEqual(r['records'],[])
  self.assertEqual(r['lookup_query'],good['query'])
  with self.assertRaises(ModelUnavailable):validate({**good,'operation':'threshold'})

class FilterHttpTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  import app,threading
  cls.app=app;app.STORE=Store()
  cls.server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler)
  cls.url=f'http://127.0.0.1:{cls.server.server_port}'
  cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
 @classmethod
 def tearDownClass(cls):cls.server.shutdown();cls.server.server_close()
 def request(self,path,body):
  import urllib.request
  req=urllib.request.Request(self.url+path,data=json.dumps(body).encode(),headers={'X-Demo-Token':self.app.TOKEN,'Content-Type':'application/json'})
  with urllib.request.urlopen(req) as r:return json.load(r)
 def test_filtered_page_and_empty_context(self):
  intent={'operation':'search','entity':None,'scope':'direct','query':{'target':'parts','filters':[{'field':'name','operator':'contains','value':'1'}]}}
  r=self.request('/api/query',{'session':'filter-page','intent':intent})
  self.assertEqual(r['total'],11856);self.assertEqual(len(r['records']),20)
  page=self.request('/api/page',{'session':'filter-page','result':r['result'],'page':592})
  self.assertEqual(len(page['records']),16)
  intent['query']['filters'][0]['value']='ABC'
  r=self.request('/api/query',{'session':'filter-page','intent':intent})
  self.assertEqual(r['total'],0);self.assertEqual(r['context']['query'],intent['query'])
 def test_model_receives_full_query_context(self):
  from unittest.mock import patch
  prior={'operation':'search','entity':None,'scope':'direct','query':{'target':'parts','filters':[{'field':'name','operator':'contains','value':'1'}]}}
  self.request('/api/query',{'session':'filter-follow','intent':prior})
  def interpret(question,context,selection):
   self.assertEqual(context['query'],prior['query'])
   return {'operation':'clarify','entity':None,'scope':'direct','clarification':'test'}
  with patch.object(self.app,'interpret',interpret):
   r=self.request('/api/query',{'session':'filter-follow','question':'ambiguous'})
  self.assertEqual(r['status'],'clarify');self.assertEqual(r['context']['query'],prior['query'])
  self.request('/api/context',{'session':'filter-follow'})
  self.assertEqual(self.app.SESSIONS['filter-follow']['context'],{})

if __name__=='__main__':unittest.main(verbosity=2)
