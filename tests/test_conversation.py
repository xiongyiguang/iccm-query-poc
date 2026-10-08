import unittest,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from model import validate,ModelUnavailable
from data import Store
from unittest.mock import patch
from test_filters import FilterHttpTests
class ConversationTests(unittest.TestCase):
 def test_conversation_no_data_access(self):
  intent={'operation':'conversation','entity':None,'scope':'direct','clarification':'','message':'我是iCCM设备数据助手。'}
  validate(intent)
  store=object.__new__(Store)
  with patch.object(store,'rows',side_effect=AssertionError('must not query')):
   result=store.execute(intent)
  self.assertEqual(result['status'],'conversation');self.assertEqual(result['records'],[])
 def test_message_boundaries(self):
  base={'operation':'conversation','entity':None,'scope':'direct','clarification':''}
  for extra in [{'message':''},{'message':'x'*1201},{'message':'ok','entity':{'tree':'config','code':'MOHB01'}},{'operation':'parts','message':'there are 100'}]:
   with self.assertRaises(ModelUnavailable):validate({**base,**extra})
class ConversationHttpTests(FilterHttpTests):
 def test_help_keeps_query_and_dialogue(self):
  initial={'operation':'parts','entity':{'tree':'config','code':'MOHB01'},'scope':'all'}
  r=self.request('/api/query',{'session':'help-test','intent':initial});before=r['context']
  reply={'operation':'conversation','entity':None,'scope':'direct','clarification':'','message':'可以按名称筛选。'}
  with patch.object(self.app,'interpret',return_value=reply):
   r=self.request('/api/query',{'session':'help-test','question':'怎么问你'})
  self.assertEqual(r['context'],before);self.assertEqual(r['status'],'conversation')
  self.assertNotIn('trace',r)
  def next_call(q,c,s,store=None):
   self.assertEqual(c['entity'],initial['entity']);self.assertEqual(c['scope'],'all')
   self.assertEqual(c['dialogue'][-1]['question'],'怎么问你')
   return initial
  with patch.object(self.app,'interpret',next_call),patch('request_checklist.gate',return_value={'decision':'accept','choice':'candidate'}):
   r=self.request('/api/query',{'session':'help-test','question':'继续'})
  self.assertEqual(r['status'],'ok')
  self.assertEqual(r['total'],221)
if __name__=='__main__':unittest.main(verbosity=2)
