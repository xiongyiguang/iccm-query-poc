import json,sys,unittest
from pathlib import Path
from unittest.mock import patch,MagicMock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import model

def response(value,finish='stop'):
 r=MagicMock();r.__enter__.return_value.read.return_value=json.dumps({'choices':[{'finish_reason':finish,'message':{'content':json.dumps(value)}}]}).encode();return r

def intent(kind='ratio',limit=100):
 return dict(operation='analyze',entity=None,scope='direct',clarification='',query={'target':'points','filters':[]},analysis=dict(kind=kind,group_by=None if kind=='ratio' else 'location',order='desc',limit=limit,numerator=[{'field':'status','operator':'equals','value':'已报警'}] if kind=='ratio' else []))

class StatisticsReviewTests(unittest.TestCase):
 def test_invalid_ratio_limit(self):
  for n in [3,5]:
   with self.assertRaises(model.ModelUnavailable):model.validate(intent(limit=n))
  self.assertEqual(model.validate(intent())['analysis']['kind'],'ratio')
 def test_review_corrects_before_execution(self):
  bad=intent(limit=5);good=intent('group_count',5)
  with patch.dict(model.os.environ,{'DEEPSEEK_API_KEY':'test-only','ICCM_REQUEST_ENGINE':'legacy'}),patch.object(model.urllib.request,'build_opener') as net:
   net.return_value.open.side_effect=[response({'unit':{'state':'none','value':''},'reference':None,'projection':'specified','scope':None,'needs_history':False,'identifier_field':None}),response(bad),response(good)]
   result=model.interpret('按功能位置分组排名',{},None)
   self.assertEqual(result,good);self.assertEqual(net.return_value.open.call_count,3)
   self.assertEqual(model.get_trace()['statistics_review']['candidate'],bad)
 def test_incomplete_review_fails_closed(self):
  with patch.dict(model.os.environ,{'DEEPSEEK_API_KEY':'test-only','ICCM_REQUEST_ENGINE':'legacy'}),patch.object(model.urllib.request,'build_opener') as net:
   net.return_value.open.side_effect=[response({'unit':{'state':'none','value':''},'reference':None,'projection':'specified','scope':None,'needs_history':False,'identifier_field':None}),response(intent()),response(intent(), 'length')]
   with self.assertRaises(model.ModelUnavailable):model.interpret('占比',{},None)
 def test_batch_is_reviewed(self):
  self.assertTrue(model.has_statistics({'operation':'batch','tasks':[{'intent':intent()}]}))
  self.assertFalse(model.has_statistics({'operation':'attributes'}))
