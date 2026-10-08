import sys
import unittest
from pathlib import Path
from decimal import Decimal
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from data import Store,QueryError


class QueryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.store=Store()
    def query(self,op,code=None,tree='pbs',scope='direct'):
        return self.store.execute({'operation':op,'entity':{'tree':tree,'code':code} if code else None,'scope':scope})
    def test_source_counts_and_readonly(self):
        self.assertEqual(self.store.rows('SELECT count(*) n FROM points')[0]['n'],12985)
        self.assertEqual(self.store.rows('SELECT count(*) n FROM objects')[0]['n'],46200)
        with self.assertRaises(Exception): self.store.db.execute("DELETE FROM points")
    def test_equipment_name_not_category(self):
        r=self.query('equipment','XJ2ABC002MO&MOHB01')
        self.assertIn('构型对象描述14477',r['answer'])
        self.assertNotIn('设备类描述1860',r['answer'])
    def test_equipment_class_and_context(self):
        r=self.query('equipment_class','XJ2ABC002MO&MOHB01')
        self.assertIn('设备类描述1860',r['answer'])
        self.assertEqual(r['entity'],{'tree':'config','code':'MOHB01'})
        self.assertTrue(any(x['file']=='设备类.csv' for x in r['evidence']))
    def test_part_sets_and_hierarchy(self):
        direct=self.query('parts','MOHB01','config')
        all_r=self.query('parts','MOHB01','config','all')
        self.assertEqual(len(direct['records']),51)
        self.assertEqual(len(all_r['records']),221)
        self.assertTrue({r['code'] for r in direct['records']} < {r['code'] for r in all_r['records']})
        self.assertTrue(all(r['parent']=='MOHB01' for r in direct['records']))
    def test_class_and_parent(self):
        r=self.query('part_class','MOHB01#1','config')
        self.assertIn('部件类描述360',r['answer'])
        self.assertEqual(self.query('parent','MOHB01#1','config')['entity']['code'],'MOHB01')
    def test_alarm_global_and_location(self):
        r=self.query('alarms')
        self.assertEqual(len(r['records']),48)
        self.assertEqual(sum(x['location']=='未匹配' for x in r['records']),16)
        self.assertEqual(len(self.query('alarms','XJ2ABC001MO')['records']),10)
    def test_measurement_count_and_missing(self):
        r=self.query('measurements','XJ2ABC001MO')
        self.assertEqual(len(r['records']),901)
        self.assertEqual(sum(x['state']=='未提供' for x in r['records']),771)
    def test_multiple_sources_retained(self):
        r=self.query('measurement','XJ2ABC001PO.ZRs.2ABC003KA.UGb')
        self.assertEqual(len(r['records']),4)
        thresholds=self.query('threshold','XJ2ABC001PO.ZRs.2ABC003KA.UGb')
        self.assertEqual(len(thresholds['records']),4)
        self.assertEqual(len(thresholds['threshold_details']),4)
        self.assertEqual([x['evidence'] for x in thresholds['records']],[x['evidence'] for x in r['records']])
    def test_threshold_and_duration(self):
        code='XJ2ABC001MO.TMP.2ABC109MT.BBe'
        r=self.query('threshold',code)
        self.assertEqual(Decimal(r['records'][0]['difference']),Decimal('6.69898987'))
        self.assertEqual({m['label']:m['value'] for m in r['metrics']}['真实值报警阈值-高2'],'80')
        r=self.query('duration',code)
        self.assertEqual(r['status'],'data_insufficient')
        self.assertIn('不是报警开始时间',r['note'])
    def test_unknown_and_injection(self):
        with self.assertRaises(QueryError): self.query('object',"' OR 1=1 --")
        with self.assertRaises(QueryError): self.query('DROP TABLE')
        with self.assertRaises(QueryError): self.query('parts','MOHB01','config','unknown')
    def test_no_config_to_fake_site_mapping(self):
        with self.assertRaises(QueryError): self.query('alarms','MOHB01','config')
    def test_search_names_and_wildcards(self):
        r=self.store.search('设备类描述1860','equipment_class')
        self.assertEqual(r[0]['code'],'MOHB')
        self.assertEqual(self.store.search("' OR 1=1 --",'pbs'),[])

class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import app,threading
        cls.app=app
        app.STORE=Store()
        cls.server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler)
        cls.url=f'http://127.0.0.1:{cls.server.server_port}'
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
    @classmethod
    def tearDownClass(cls): cls.server.shutdown();cls.server.server_close()
    def request(self,path,body=None,token=True):
        import urllib.request,json
        headers={'Content-Type':'application/json'}
        if token: headers['X-Demo-Token']=self.app.TOKEN
        req=urllib.request.Request(self.url+path,data=json.dumps(body).encode() if body is not None else None,headers=headers)
        with urllib.request.urlopen(req,timeout=5) as r: return json.load(r)
    def test_page_full_set_and_context_clear(self):
        q=self.request('/api/query',{'session':'pagination','intent':{'operation':'parts','entity':{'tree':'config','code':'MOHB01'},'scope':'all'}})
        self.assertEqual(q['total'],221);self.assertEqual(len(q['records']),20)
        self.request('/api/context',{'session':'pagination'})
        last=self.request('/api/page',{'session':'pagination','result':q['result'],'page':11})
        self.assertEqual(len(last['records']),1)
        self.assertEqual(self.app.SESSIONS['pagination']['context'],{})
    def test_token_and_static_boundary(self):
        import urllib.error
        with self.assertRaises(urllib.error.HTTPError) as c:self.request('/api/query',{'session':'bad'},False)
        self.assertEqual(c.exception.code,403)
        with self.assertRaises(urllib.error.HTTPError) as c:self.request('/../PROJECT.yaml')
        self.assertEqual(c.exception.code,404)
    def test_cancel_late_model_does_not_restore_state(self):
        import threading,urllib.error
        from unittest.mock import patch
        started,release=threading.Event(),threading.Event();codes=[]
        def model(*args,**kwargs):
            started.set();release.wait(3)
            return {'operation':'parts','entity':{'tree':'config','code':'MOHB01'},'scope':'direct'}
        def request():
            try:self.request('/api/query',{'session':'cancel','question':'test'})
            except urllib.error.HTTPError as e:codes.append(e.code)
        with patch.object(self.app,'interpret',model):
            worker=threading.Thread(target=request);worker.start();self.assertTrue(started.wait(2))
            self.request('/api/reset',{'session':'cancel'});release.set();worker.join(3)
        self.assertEqual(codes,[409]);self.assertNotIn('cancel',self.app.SESSIONS)

if __name__=='__main__': unittest.main(verbosity=2)
