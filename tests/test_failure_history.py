"""失败回执恢复真正的上次成功状态，不把失败计划当结果。"""
import json,urllib.error,unittest
import test_filters

class FailureHistory(unittest.TestCase):
 setUpClass=classmethod(test_filters.FilterHttpTests.setUpClass.__func__)
 tearDownClass=classmethod(test_filters.FilterHttpTests.tearDownClass.__func__)
 request=test_filters.FilterHttpTests.request
 def test_error_snapshot_preserves_actual_focus_and_resumes_after_eviction(self):
  sid='failure-history-proof'
  result=self.request('/api/query',{'session':sid,'intent':{'operation':'parts','entity':{'tree':'config','code':'MOHB01'},'scope':'direct','clarification':''}})
  with self.assertRaises(urllib.error.HTTPError) as error:self.request('/api/query',{'session':sid,'intent':{'operation':'parts','entity':{'tree':'config','code':'MOHB01'},'scope':'invalid','clarification':''}})
  payload=json.load(error.exception)
  self.assertEqual(payload['context']['entity'],result['context']['entity']);self.assertIn('continuation',payload);self.assertNotIn('result',payload)
  self.request('/api/reset',{'session':sid})
  resumed=self.request('/api/resume',{'session':sid,'continuation':payload['continuation']})
  self.assertEqual(resumed['context']['entity'],result['context']['entity']);self.assertEqual(resumed['context']['scope'],'direct')

if __name__=='__main__':unittest.main()
