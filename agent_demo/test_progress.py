"""查询过程展示独立于模型响应速度；此处均为离线检查。"""
import threading
import unittest
from server import Demo


class Metadata:
    def begin_turn(self, session, question):
        return {'literal_references': [], 'previous_query': None}

    def meta(self):
        return {'version':'test-snapshot','counts':{'pbs':10,'points':20}}


class DelayedRuntime:
    def __init__(self, fail=False):
        self.entered=threading.Event()
        self.release=threading.Event()
        self.fail=fail

    def call(self, method, params):
        self.entered.set()
        self.release.wait(3)
        if self.fail:
            raise RuntimeError('test model unavailable')
        return {'turn':{'id':'test-turn'}}


class ProcessTests(unittest.TestCase):
    def test_completion_check_is_bounded_and_keeps_plan_in_process(self):
        d=Demo.__new__(Demo);d.lock=threading.RLock()
        session={'id':'one','thread':'thread-one','events':[], 'busy':True,
                 'generation':'g','business_calls':0,'completion_check':False,'calls':0}
        d.sessions={'one':session}
        called=threading.Event();calls=[]
        class ImmediateRuntime:
            def call(self, method, params):
                calls.append(method);called.set();return {'turn':{'id':'check-turn'}}
        d.runtime=ImmediateRuntime()
        d.notify('item/completed',{'threadId':'thread-one','item':{'type':'agentMessage','id':'m','text':'我将查询','phase':'final_answer'}})
        self.assertEqual(session['events'][-1]['phase'],'commentary')
        d.notify('turn/completed',{'threadId':'thread-one','turn':{'status':'completed'}})
        self.assertTrue(called.wait(1));self.assertTrue(session['busy'])
        self.assertFalse(any(e['kind']=='done' for e in session['events']))
        d.notify('turn/completed',{'threadId':'thread-one','turn':{'status':'completed'}})
        self.assertFalse(session['busy']);self.assertEqual(calls,['turn/start'])

    def test_completion_check_never_repeats_a_business_receipt(self):
        d=Demo.__new__(Demo);d.lock=threading.RLock()
        session={'id':'one','thread':'thread-one','events':[], 'busy':True,'business_calls':1}
        d.sessions={'one':session}
        d.notify('turn/completed',{'threadId':'thread-one','turn':{'status':'completed'}})
        self.assertFalse(session['busy']);self.assertEqual(session['events'][0]['kind'],'done')

    def test_new_thread_does_not_block_other_thread_notifications(self):
        d=Demo.__new__(Demo)
        d.lock=threading.RLock();d.sessions={};d.creating=0
        notified=threading.Event()
        class CallbackRuntime:
            def new_thread(self, *args, **kwargs):
                def notification():
                    with d.lock: notified.set()
                worker=threading.Thread(target=notification,daemon=True);worker.start()
                if not notified.wait(1):raise RuntimeError('creation blocks event reader')
                return {'model':'gpt-6-luna','thread':{'id':'new-thread'}}
        d.runtime=CallbackRuntime()
        self.assertIn(d.create()['id'],d.sessions)
        self.assertEqual(d.creating,0)

    def test_failed_creation_releases_reserved_capacity(self):
        d=Demo.__new__(Demo)
        d.lock=threading.RLock();d.sessions={};d.creating=0
        class FailedRuntime:
            def new_thread(self,*args,**kwargs):raise RuntimeError('unavailable')
        d.runtime=FailedRuntime()
        with self.assertRaises(RuntimeError):d.create()
        self.assertEqual(d.creating,0)
        self.assertFalse(d.sessions)

    def demo(self, fail=False):
        d=Demo.__new__(Demo)
        d.lock=threading.RLock();d.data=Metadata();d.runtime=DelayedRuntime(fail)
        d.sessions={'one':{'id':'one','thread':'thread-one','model':'test','events':[],'busy':False}}
        self.addCleanup(d.runtime.release.set)
        return d

    def test_real_preparation_before_model_responds(self):
        d=self.demo();d.ask('one','查询设备')
        self.assertTrue(d.runtime.entered.wait(1))
        events=d.get('one')['events']
        self.assertEqual([e['kind'] for e in events],['user','process'])
        self.assertIn('PBS 10',events[1]['text'])
        self.assertEqual(events[1]['snapshot_version'],'test-snapshot')
        self.assertFalse(any(e['kind']=='tool_result' for e in events))
        d.notify('turn/completed',{'threadId':'thread-one','turn':{'status':'interrupted'}})

    def test_rejection_does_not_fake_process(self):
        d=self.demo()
        with self.assertRaises(ValueError):d.ask('one','')
        self.assertEqual(d.get('one')['events'],[])

    def test_model_failure_keeps_preparation_without_success(self):
        d=self.demo(True);d.ask('one','查询设备')
        self.assertTrue(d.runtime.entered.wait(1));d.runtime.release.set()
        import time
        deadline=time.monotonic()+1
        while d.get('one')['busy'] and time.monotonic()<deadline:time.sleep(.01)
        events=d.get('one')['events']
        self.assertTrue(any(e['kind']=='error' for e in events))
        self.assertFalse(any(e['kind'] in ['tool_result','done'] for e in events))


if __name__=='__main__':unittest.main(verbosity=2)
