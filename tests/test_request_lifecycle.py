"""用受控时序复现响应已完成但旧清理尚未结束的连续请求。"""
import copy,json,threading,unittest,urllib.error
from unittest.mock import patch
import test_filters

class RequestLifecycleTests(unittest.TestCase):
 setUpClass=classmethod(test_filters.FilterHttpTests.setUpClass.__func__)
 tearDownClass=classmethod(test_filters.FilterHttpTests.tearDownClass.__func__)
 request=test_filters.FilterHttpTests.request
 def test_completed_response_releases_owner_and_late_cleanup_keeps_new_busy(self):
  import app,request_checklist
  sid='lifecycle-controlled';first_cleanup=threading.Event();release_cleanup=threading.Event();first_done=threading.Event();second_started=threading.Event();release_second=threading.Event()
  tids={};observed=[];answers=[];errors=[]
  original_send=app.Handler.send;original_post=app.Handler.do_POST;original_execute=app.execute_plan;original_cleanup=request_checklist.discard_extraction
  plan={'operation':'parts','entity':{'tree':'config','code':'MOHB01'},'scope':'direct','clarification':'first'}
  def execute(store,intent):
   marker=intent['clarification']
   if marker=='first':tids['first']=threading.get_ident()
   if marker=='second':
    second_started.set()
    if not release_second.wait(5):raise AssertionError('第二请求未释放')
   return original_execute(store,intent)
  def send(handler,status,payload):
   if threading.get_ident()==tids.get('first') and 'result' in payload:
    observed.append(app.SESSIONS[sid]['busy'])
   return original_send(handler,status,payload)
  def cleanup():
   if threading.get_ident()==tids.get('first'):
    first_cleanup.set()
    if not release_cleanup.wait(5):raise AssertionError('旧清理未释放')
   original_cleanup()
  def post(handler):
   try:return original_post(handler)
   finally:
    if threading.get_ident()==tids.get('first'):first_done.set()
  def second():
   try:answers.append(self.request('/api/query',{'session':sid,'intent':{**plan,'clarification':'second'}}))
   except Exception as e:errors.append(e)
  worker=None
  with patch.object(app,'execute_plan',side_effect=execute),patch.object(app.Handler,'send',send),patch.object(app.Handler,'do_POST',post),patch.object(request_checklist,'discard_extraction',side_effect=cleanup):
   try:
    self.assertEqual(self.request('/api/query',{'session':sid,'intent':copy.deepcopy(plan)})['status'],'ok')
    self.assertTrue(first_cleanup.wait(3));self.assertEqual(observed,[False])
    worker=threading.Thread(target=second);worker.start();self.assertTrue(second_started.wait(3))
    release_cleanup.set();self.assertTrue(first_done.wait(3))
    with self.assertRaises(urllib.error.HTTPError) as caught:self.request('/api/query',{'session':sid,'intent':{**plan,'clarification':'third'}})
    self.assertEqual(caught.exception.code,400);self.assertIn('尚未完成',json.load(caught.exception)['error'])
    release_second.set();worker.join(3);self.assertFalse(worker.is_alive());self.assertEqual(errors,[]);self.assertEqual(answers[0]['status'],'ok')
   finally:
    release_cleanup.set();release_second.set()
    if worker is not None:worker.join(3)

if __name__=='__main__':unittest.main()
