import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from data import Store
from request_checklist import literal_references
from date_fields import date_literal_spans


class Dates(unittest.TestCase):
 def setUp(self):self.s=Store(dataset=[{'kind':'config','file':'config.csv','sha256':'fixture','seed':True,'rows':[{'对象代码':'1','对象描述中文':'数字构型','对象层级描述':'设备'}]}])
 def tearDown(self):self.s.db.close()
 def test_numbers_in_complete_valid_dates_are_not_object_ids(self):
  for q in ['时间改为1970年1月1日','测量时间在2026年1月','时间等于2025/1/1 8:00','时间等于2025-01-01']:
   self.assertTrue(date_literal_spans(q));self.assertEqual(literal_references(q,self.s),[])
 def test_explicit_numeric_root_outside_date_remains_a_real_reference(self):
  refs=literal_references('构型1，测量时间在1970年1月1日',self.s);self.assertEqual([(x['domain'],x['field'],x['value'],x['start']) for x in refs],[('config','code','1',2)])
 def test_invalid_date_is_not_silently_proven_as_calendar_span(self):self.assertEqual(date_literal_spans('时间在2025年2月31日'),[])
