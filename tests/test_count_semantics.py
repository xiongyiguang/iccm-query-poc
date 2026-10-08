import unittest,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from data import Store
from query_plan import execute_plan

def search(target,filters=None,entity=None,scope='direct'):
 return dict(operation='search',entity=entity,scope=scope,clarification='',query={'target':target,'filters':filters or []})
def equals(field,value):return {'field':field,'operator':'equals','value':value}

class CountSemanticsTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.s=Store()
 def test_object_grains(self):
  for target,level,n,label in [('pbs','设备',42,'PBS设备对象'),('equipment',None,2205,'设备构型'),('equipment_class',None,3748,'设备类字典记录'),('pbs','部件',3614,'PBS部件对象'),('parts',None,18692,'部件构型'),('part_class',None,1631,'部件类字典记录'),('config',None,24025,'构型对象'),('pbs','时序测点',12904,'PBS时序测点对象')]:
   r=self.s.execute(search(target,[equals('level',level)] if level else []))
   self.assertEqual(len(r['records']),n)
   self.assertEqual(r['metrics'][0],{'label':label,'value':n})
   self.assertIn(label,r['answer'])
 def test_measurement_grains(self):
  r=self.s.execute(search('points'))
  self.assertEqual([m['value'] for m in r['metrics']],[12985,12981])
  r=self.s.execute(search('points',[equals('code','XJ2ABC001PO.ZRs.2ABC003KA.UGb')]))
  self.assertEqual([m['value'] for m in r['metrics']],[4,1])
  r=self.s.execute(search('points',[equals('code','NO-SUCH-CODE')]))
  self.assertEqual([m['value'] for m in r['metrics']],[0,0])
 def test_scoped_count(self):
  r=self.s.execute(search('parts',entity={'tree':'config','code':'MOHB01'},scope='all'))
  self.assertEqual(len(r['records']),221)
  self.assertIn('MOHB01',r['answer']);self.assertIn('全部下级',r['answer'])
 def test_comparison(self):
  intents=[search('pbs',[equals('level','设备')]),search('equipment'),search('equipment_class')]
  r=execute_plan(self.s,dict(operation='batch',entity=None,scope='direct',clarification='',tasks=[{'question':str(i),'intent':x} for i,x in enumerate(intents)]))
  self.assertIn('不能相加或互换',r['answer'])
  self.assertEqual([len(x['records']) for x in r['items']],[42,2205,3748])
 def test_alarm_switch_is_independent(self):
  # 构造关闭但已报警的合成记录，避免真实数据计数相同掩盖条件错误。
  s=Store()
  s.db.execute('PRAGMA query_only=OFF')
  with s.db:
   s.db.execute("INSERT INTO points VALUES(?,?,?,?,?,?,?,?,?,?)",(99999,'TEST-ALARM-OFF','测试','test','0','','已报警','关闭','','{}'))
  s.db.execute('PRAGMA query_only=ON')
  only=s.execute(search('points',[equals('status','已报警')]))
  enabled=s.execute(search('points',[equals('status','已报警'),equals('switch','开启')]))
  self.assertEqual(len(only['records']),49);self.assertEqual(len(enabled['records']),48)
if __name__=='__main__':unittest.main()
