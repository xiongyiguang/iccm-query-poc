import csv,json,sys,time,unittest
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from data import Store,SOURCE,QueryError
from query_plan import execute_plan
from typed_fields import THRESHOLDS
from request_contract import enforce
from session_state import snapshot,restore,make_room,public_result,compact_evidence
from result_explanation import explain_result

def plan(op='search',target='points',filters=None,**extra):
    return dict(operation=op,entity=None,scope='direct',clarification='',query={'target':target,'filters':filters or []},**extra)
def f(field,value,operator='equals'):return dict(field=field,value=value,operator=operator)

class RefactorContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.s=Store()
    @classmethod
    def tearDownClass(cls):cls.s.db.close()

    def test_all_threshold_dimensions_source_backed(self):
        for key,field in THRESHOLDS.items():
            with self.subTest(key=key):
                r=execute_plan(self.s,plan('threshold',filters=[f('name','测量点名称11')],thresholds=[key]))
                self.assertEqual(r['requested_thresholds'],[key])
                self.assertEqual(r['threshold_details'][0]['thresholds'],{field:r['records'][0]['evidence']['fields'][field] or '未提供'})
                self.assertEqual([m['label'] for m in r['metrics']],[field])
        r=execute_plan(self.s,plan('threshold',filters=[f('name','测量点名称11')],thresholds=['actual_high2']))
        self.assertIn('80',r['answer']);self.assertNotIn('高1',r['answer'])

    def test_missing_high1_does_not_hide_low2(self):
        r=execute_plan(self.s,plan('threshold',filters=[f('name','测量点名称4')]))
        self.assertIn('低2：128',r['answer']);self.assertEqual(len(r['threshold_details'][0]['thresholds']),18)

    def test_numeric_filters_independent_csv_oracle(self):
        with (SOURCE/'测量点数据分析.csv').open(encoding='gb18030',newline='') as stream:rows=list(csv.DictReader(stream))
        numeric=[]
        for row in rows:
            try:value=Decimal(row['测量值'].strip())
            except InvalidOperation:continue
            if value.is_finite():numeric.append((row['测量点编码'],value))
        for op,compare in [('gt',lambda a,b:a>b),('gte',lambda a,b:a>=b),('lt',lambda a,b:a<b),('lte',lambda a,b:a<=b),('eq_num',lambda a,b:a==b)]:
            for bound in ['0','60','-0.001','4.069898987E1']:
                with self.subTest(op=op,bound=bound):
                    expected=[code for code,value in numeric if compare(value,Decimal(bound))]
                    r=execute_plan(self.s,plan(filters=[f('value',bound,op)]))
                    self.assertEqual(Counter(x['code'] for x in r['records']),Counter(expected))

    def test_numeric_type_rejection(self):
        for value in ['大于60','NaN','Infinity','60度','']:
            with self.subTest(value=value),self.assertRaises((QueryError,RuntimeError)):
                execute_plan(self.s,plan(filters=[f('value',value)]))
        r=execute_plan(self.s,plan(filters=[f('value','60','gt'),f('unit','℃')]))
        self.assertTrue(r['records']);self.assertTrue(all(x['unit']=='℃' and Decimal(x['value'])>60 for x in r['records']))

    def test_explicit_and_global_identity(self):
        r=execute_plan(self.s,plan('attributes','equipment_class',[f('identity','设备类描述1860')],properties=['name','code']))
        self.assertEqual(r['entity'],{'tree':'equipment_class','code':'MOHB'})
        r=execute_plan(self.s,plan('attributes','objects',[f('identity','MOHB')],properties=['name']))
        self.assertEqual(r['status'],'ambiguous');self.assertEqual({(x['tree'],x['code']) for x in r['records']},{('config','MOHB'),('equipment_class','MOHB')})
        r=execute_plan(self.s,plan('attributes','config',[f('name','MOHB01')],properties=['name']))
        self.assertNotEqual(r['status'],'ok')

    def test_independent_slots_prevent_lost_requirements(self):
        for request in [{'thresholds':['actual_high2']},{'comparisons':[f('value','60','gt')]}]:
            with self.assertRaises(ValueError):enforce(plan('threshold',thresholds=['actual_high1']),request)

    def test_location_query_count_and_independent_parent_walk(self):
        objects={x['code']:x for x in self.s.rows("SELECT code,parent,name,level FROM objects WHERE tree='pbs'")}
        expected=Counter()
        for point in self.s.rows('SELECT code FROM points'):
            code=point['code'];seen=set()
            while code in objects and objects[code]['level']!='功能位置' and code not in seen:
                seen.add(code);code=objects[code]['parent']
            expected[code if code in objects and objects[code]['level']=='功能位置' else '']+=1
        calls=[];self.s.db.set_trace_callback(calls.append)
        try:r=execute_plan(self.s,plan('analyze',analysis={'kind':'group_count','group_by':'location','order':'desc','limit':100,'numerator':[]}))
        finally:self.s.db.set_trace_callback(None)
        ordered=sorted(expected,key=lambda key:(-expected[key],key))[:100]
        self.assertEqual([(x['cells'][1],x['cells'][2]) for x in r['records']],[(key or '—',expected[key]) for key in ordered])
        self.assertLess(len(calls),10)
        wire=public_result(r);self.assertEqual(len(wire['evidence']),20);self.assertEqual(wire['evidence_total'],12985)
        self.assertLess(len(json.dumps(wire,ensure_ascii=False).encode()),100000)

    def test_resume_tamper_version_and_eviction(self):
        state={'context':{'entity':{'tree':'config','code':'MOHB01'}},'dialogue':[]}
        token=snapshot('a',state,'v1');self.assertEqual(restore(token,'a','v1')['context'],state['context'])
        for args in [(token,'b','v1'),(token,'a','v2'),(token+'x','a','v1')]:
            with self.assertRaises(ValueError):restore(*args)
        sessions={'busy':{'busy':True},'idle':{'busy':False,'touched':0}}
        make_room(sessions,2);self.assertEqual(set(sessions),{'busy'})

    def test_paged_totals_and_shared_evidence(self):
        child={'records':[{'cells':[n]} for n in range(51)],'evidence':[]}
        wire=public_result(public_result({'records':[],'items':[child]}))
        self.assertEqual(wire['items'][0]['total'],51)
        a={'evidence':[{'file':'synthetic.csv','line':2,'fields':{'value':'1'}}]}
        b=json.loads(json.dumps(a));compact_evidence(self.s,a);compact_evidence(self.s,b)
        self.assertIs(a['evidence'][0],b['evidence'][0])

    def test_units_are_equivalent_without_conversion(self):
        counts=[]
        for unit in ['℃','°C','摄氏度']:
            r=execute_plan(self.s,plan(filters=[f('value','60','gt'),f('unit',unit)]));counts.append(len(r['records']))
        self.assertEqual(len(set(counts)),1);self.assertGreater(counts[0],0)

    def test_result_explanation_uses_receipt(self):
        r=execute_plan(self.s,dict(operation='parts',entity={'tree':'config','code':'MOHB01'},scope='all',clarification=''))
        e=explain_result(r);self.assertIn('MOHB01',e['answer']);self.assertIn('父引用',e['answer']);self.assertIn('全部后代',e['answer']);self.assertTrue(e['evidence'])
        self.assertEqual(explain_result(None)['status'],'clarify')

if __name__=='__main__':unittest.main()
