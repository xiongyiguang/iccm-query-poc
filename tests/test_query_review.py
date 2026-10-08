"""确认契约：批准前不能执行，批准后按用户编辑的精确计划执行。"""
import copy,json,sys,time,unittest,urllib.error
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import query_review as review
import model
from data import QueryError,Store
from query_plan import execute_plan
from request_gateway import seal
import test_filters
from test_business_request import seed,delta,patch as task_patch,edit,condition
from business_request import apply_delta

def plan():
    return dict(operation='search',entity=None,scope='direct',clarification='',
                query=dict(target='points',filters=[dict(field='value',operator='gte',value='50'),dict(field='value',operator='lte',value='80')]))
def edits(preview):
    return [{k:copy.deepcopy(t[k]) for k in ('index','enabled','values')} for t in preview['review']['tasks']]

class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.session={'context':{},'results':{},'busy':False}
        self.p=plan()
        self.preview=review.issue(self.session,'sid','v1','至少50，还不到80',self.p,{})
        self.token=self.preview['review']['id']
    def confirm(self,changes=None,**kwargs):
        return review.confirm(self.session,kwargs.get('sid','sid'),kwargs.get('version','v1'),kwargs.get('token',self.token),changes if changes is not None else edits(self.preview))
    def test_preview_is_deep_copy_and_does_not_commit_context(self):
        self.assertEqual(self.preview['status'],'review')
        self.assertEqual(self.preview['records'],[])
        self.assertEqual(self.session['context'],{})
        self.preview['review']['tasks'][0]['values']['query']['filters'].clear()
        self.assertEqual(len(self.session['pending_review']['plan']['query']['filters']),2)
    def test_confirmed_upper_bound_is_exact_and_one_use_without_model(self):
        changes=edits(self.preview);changes[0]['values']['query']['filters'][1]['operator']='lt'
        with patch.object(model,'interpret',side_effect=AssertionError('model must not run')):
            p,trace,q=self.confirm(changes)
        self.assertEqual(p['query']['filters'][1]['operator'],'lt')
        self.assertTrue(trace['user_confirmed'])
        self.assertEqual(self.p['query']['filters'][1]['operator'],'lte')
        with self.assertRaises(QueryError):self.confirm(changes)
    def test_session_version_context_expiry_and_token_are_bound(self):
        for kw in ({'sid':'other'},{'version':'v2'},{'token':'bad'}):
            with self.subTest(kw=kw),self.assertRaises(QueryError):self.confirm(**kw)
        self.session['context']={'changed':True}
        with self.assertRaises(QueryError):self.confirm()
        self.session['context']={}
        self.session['pending_review']['expires']=time.monotonic()-1
        with self.assertRaises(QueryError):self.confirm()
    def test_invalid_edits_preserve_draft_and_do_not_mutate_original(self):
        invalid=[]
        v=edits(self.preview);v[0]['values']['operation']='data_overview';invalid.append(v)
        v=edits(self.preview);v[0]['values']['query']['filters'][0]['value']='not-a-number';invalid.append(v)
        v=edits(self.preview);v[0]['values']['query']['filters'][0]['field']='SQL';invalid.append(v)
        v=edits(self.preview);v[0]['values'].pop('scope');invalid.append(v)
        v=edits(self.preview);v[0]['index']=True;invalid.append(v)
        v=edits(self.preview);v[0]['enabled']=False;invalid.append(v)
        for v in invalid:
            with self.subTest(v=v),self.assertRaises(QueryError):self.confirm(v)
            self.assertEqual(self.session['pending_review']['plan'],self.p)
        self.assertEqual(self.confirm()[0],self.p)
    def test_numeric_unit_ambiguity_still_rejected(self):
        v=edits(self.preview);v[0]['values']['query']['filters'].append(condition('unit','equals','度'))
        with self.assertRaises(QueryError):self.confirm(v)
    def test_threshold_defaults_are_visible_and_editable(self):
        p=dict(operation='threshold',entity={'tree':'pbs','code':'x'},scope='direct',clarification='')
        out=review.issue(self.session,'sid','v1','阈值',p,{})
        self.assertGreater(len(out['review']['tasks'][0]['values']['thresholds']),1)
        v=edits(out);v[0]['values']['thresholds']=['actual_high3']
        confirmed,_,_=review.confirm(self.session,'sid','v1',out['review']['id'],v)
        self.assertEqual(confirmed['thresholds'],['actual_high3'])
        self.assertNotIn('thresholds',p)
    def test_complexity_based_on_structure(self):
        simple={**plan(),'query':{'target':'parts','filters':[condition('name','contains','1')]}}
        self.assertFalse(review.required(simple,{}))
        self.assertTrue(review.required(simple,{'business_request':{'tasks':[]}}))
        self.assertFalse(review.required(simple,{'business_request':{'tasks':[{}]}},{'business_request_delta':{'mode':'new'}}))
        self.assertTrue(review.required(simple,{'business_request':{'tasks':[{}]}},{'business_request_delta':{'mode':'update'}}))
        self.assertTrue(review.required(self.p,{}))
        self.assertTrue(review.required({**simple,'scope':'all'},{}))
        self.assertFalse(review.required(dict(operation='clarify',entity=None,scope='direct',clarification='补充'),{}))
    def test_deselection_preserves_other_old_branches_and_provenance(self):
        q='Plant3'
        original,first,_=seed()
        extra=task_patch(None,{'operation':'search','target':'parts'},[edit('add',[],[condition('name','contains','1')],q)],q)
        first_patch=task_patch(None,{'operation':'search','target':'points'},[edit('add',[],[condition('source','equals','Plant3'),condition('value','gt','5'),condition('unit','is_blank','')],q)],q)
        _,state,_=apply_delta(delta([first_patch,extra]),None,q)
        combined,candidate,changed=apply_delta(delta([task_patch('t1',q=q),task_patch('t2',q=q)],'update'),state,q)
        self.session['context']={'business_request':state}
        p=review.issue(self.session,'sid','v1',q,combined,{'business_request_state':candidate,'changed_tasks':changed,'business_request_delta':{'mode':'update'}})
        v=edits(p);v[1]['enabled']=False
        v[0]['values']['query']['filters'][1]['value']='80'
        out,trace,_=review.confirm(self.session,'sid','v1',p['review']['id'],v)
        confirmed=trace['business_request_state']
        self.assertEqual(len(confirmed['tasks']),2)
        self.assertEqual(confirmed['tasks'][1],state['tasks'][1])
        self.assertEqual(confirmed['tasks'][0]['filters'][0],state['tasks'][0]['filters'][0])
        self.assertEqual(confirmed['tasks'][0]['filters'][1]['value'],'80')
        self.assertEqual(confirmed['tasks'][0]['filters'][1]['source']['kind'],'user_confirmation')
        self.assertEqual(state['tasks'][0]['filters'][1]['value'],'5')
    def test_pending_only_update_commits_selected_tasks_without_draft_siblings(self):
        q='Plant3'
        tasks=[task_patch(None,{'operation':'search','target':'points'},[edit('add',[],[condition('source','equals','Plant3'),condition('value','gt',v)],q)],q) for v in ('5','8')]
        _,pending,_=apply_delta(delta(tasks),None,q)
        p,candidate,changed=apply_delta(delta([task_patch('t1',q=q),task_patch('t2',q=q)],'update'),pending,q)
        self.session['context']={'pending_business_request':pending}
        preview=review.issue(self.session,'sid','v1',q,p,{'business_request_state':candidate,'changed_tasks':changed,'business_request_delta':{'mode':'update'}})
        v=edits(preview);v[1]['enabled']=False
        _,trace,_=review.confirm(self.session,'sid','v1',preview['review']['id'],v)
        self.assertEqual([t['id'] for t in trace['business_request_state']['tasks']],['t1'])
        self.assertNotIn('business_request',self.session['context'])
        self.assertEqual(self.session['context']['pending_business_request'],pending)
    def test_unsupported_branch_is_kept_as_explanation_not_turned_into_query(self):
        clarify=dict(operation='clarify',entity=None,scope='direct',clarification='不支持诊断')
        batch=dict(operation='batch',entity=None,scope='direct',clarification='',tasks=[{'question':'查询','intent':self.p},{'question':'诊断','intent':clarify}])
        p=review.issue(self.session,'sid','v1','查询和诊断',batch,{})
        out,_,_=review.confirm(self.session,'sid','v1',p['review']['id'],edits(p))
        self.assertEqual(out['tasks'][1]['intent'],clarify)
    def test_parameterized_text_remains_literal(self):
        from query_filters import predicates
        value="' OR 1=1 --"
        changes=edits(self.preview)
        changes[0]['values']['query']={'target':'parts','filters':[condition('name','equals',value)]}
        p,_,_=self.confirm(changes);clauses,args=predicates(p['query'])
        self.assertNotIn(value,''.join(clauses));self.assertIn(value,args)

class ReviewSemanticStateTests(unittest.TestCase):
    def issue_identity(self,scope='explicit',target='config'):
        from test_object_scope import delta
        q='构型MOHB是什么' if scope=='explicit' else '跨树介绍MOHB'
        p,state,changed=apply_delta(delta(q,purpose='identity',scope=scope,target=target),None,q)
        session={'context':{},'results':{},'busy':False}
        preview=review.issue(session,'semantic-review','v1',q,p,
            {'business_request_state':state,'changed_tasks':changed,'business_request_delta':{'mode':'new'}})
        return session,preview,state
    def test_unchanged_confirmation_preserves_purpose_and_scope_provenance(self):
        for scope,target in (('explicit','config'),('cross_tree','objects')):
            session,preview,original=self.issue_identity(scope,target);saved=copy.deepcopy(original)
            _,trace,_=review.confirm(session,'semantic-review','v1',preview['review']['id'],edits(preview))
            confirmed=trace['business_request_state']['tasks'][0]
            for key in ('purpose','subject_scope'):
                self.assertEqual(confirmed['sources'][key],original['tasks'][0]['sources'][key])
            self.assertEqual(confirmed['target'],target);self.assertEqual(original,saved)
            confirmed['sources']['purpose']['value']='data'
            self.assertEqual(original['tasks'][0]['sources']['purpose']['value'],'identity')
    def test_edited_query_uses_user_fields_not_old_purpose(self):
        for change in ('object','projection','tree'):
            session,preview,original=self.issue_identity();v=edits(preview)
            if change=='object':v[0]['values']['query']['filters'][0]['value']='MOH'
            elif change=='projection':v[0]['values']['properties']=['name']
            else:v[0]['values']['query']['target']='equipment_class'
            p,trace,_=review.confirm(session,'semantic-review','v1',preview['review']['id'],v)
            task=trace['business_request_state']['tasks'][0]
            for key,value in (('purpose','data'),('subject_scope','none')):
                self.assertEqual(task['sources'][key]['kind'],'user_confirmation')
                self.assertEqual(task['sources'][key]['value'],value)
                self.assertEqual(task['sources'][key]['previous'],original['tasks'][0]['sources'][key])
            self.assertEqual(p['query'],v[0]['values']['query'])
            self.assertEqual(p.get('properties'),v[0]['values'].get('properties'))
    def test_preserved_cross_tree_task_can_continue_after_confirmation(self):
        from test_object_scope import delta
        session,preview,_=self.issue_identity('cross_tree','objects')
        _,trace,_=review.confirm(session,'semantic-review','v1',preview['review']['id'],edits(preview))
        state=trace['business_request_state'];d=delta('继续跨树确认MOHB',scope='cross_tree',target='objects')
        d['mode']='update';d['tasks'][0].update(base='t1',filters=[],set={})
        p,out,_=apply_delta(d,state,'继续跨树确认MOHB')
        self.assertEqual(p['query']['target'],'objects')
        self.assertEqual(out['tasks'][0]['filters'],state['tasks'][0]['filters'])

class ReviewHttpTests(test_filters.FilterHttpTests):
    @staticmethod
    def model_trace(p,q):
        d=delta([task_patch(None,{'operation':p['operation'],'target':p['query']['target']},[edit('add',[],p['query']['filters'],q)],q)])
        _,state,changed=apply_delta(d,None,q)
        model.TRACE.value={'engine':'business_request','business_request_state':state,'changed_tasks':changed,'business_request_delta':d}
    def issue(self,sid='review-http',p=None):
        import app
        p=p or plan()
        def interpret(q,c,s):
            self.model_trace(p,q)
            return copy.deepcopy(p)
        # 旧的已保存确认接口仍须可测试，新查询不再生成确认单。
        session={'context':{},'results':{},'busy':False}
        app.SESSIONS[sid]=session
        self.model_trace(p,'至少50，还不到80')
        response=review.issue(session,sid,app.STORE.version,'至少50，还不到80',p,model.get_trace())
        response['continuation']=app.snapshot(sid,session,app.STORE.version)
        self.assertEqual(response['status'],'review')
        self.assertEqual(session['context'],{})
        self.assertEqual(session['results'],{})
        return response
    def test_http_confirmation_executes_exact_edit_once(self):
        import app
        r=self.issue();v=edits(r);v[0]['values']['query']['filters'][1]['operator']='lt'
        with patch.object(app,'interpret',side_effect=AssertionError('reinterpreted')),patch.object(app,'execute_plan',wraps=execute_plan) as execute:
            out=self.request('/api/confirm',{'session':'review-http','review':r['review']['id'],'tasks':v,'trace':True})
        execute.assert_called_once()
        expected={**plan(),'query':v[0]['values']['query']}
        self.assertEqual(execute.call_args.args[1],expected)
        oracle=execute_plan(app.STORE,expected)
        self.assertEqual(out['total'],len(oracle['records']))
        self.assertEqual(out['records'],oracle['records'][:20])
        self.assertEqual(out['mode'],'confirmed')
        self.assertEqual(out['context']['query'],expected['query'])
        with self.assertRaises(urllib.error.HTTPError):
            self.request('/api/confirm',{'session':'review-http','review':r['review']['id'],'tasks':v})
    def test_invalid_confirmation_can_be_corrected(self):
        r=self.issue('review-edit');v=edits(r);v[0]['values']['query']['filters'][0]['value']='NaN'
        with self.assertRaises(urllib.error.HTTPError):self.request('/api/confirm',{'session':'review-edit','review':r['review']['id'],'tasks':v})
        out=self.request('/api/confirm',{'session':'review-edit','review':r['review']['id'],'tasks':edits(r)})
        self.assertEqual(out['status'],'ok')
    def test_old_cancel_does_not_remove_new_review(self):
        first=self.issue('review-cancel-race');second=self.issue('review-cancel-race')
        self.request('/api/review/cancel',{'session':'review-cancel-race','review':first['review']['id']})
        out=self.request('/api/confirm',{'session':'review-cancel-race','review':second['review']['id'],'tasks':edits(second)})
        self.assertEqual(out['status'],'ok')
    def test_cancel_reset_clear_and_resume_invalidate(self):
        for path in ('/api/review/cancel','/api/reset','/api/context','/api/resume'):
            sid='invalidate-'+path.rsplit('/',1)[-1];r=self.issue(sid)
            self.request(path,{'session':sid,'continuation':r['continuation']})
            with self.assertRaises(urllib.error.HTTPError):self.request('/api/confirm',{'session':sid,'review':r['review']['id'],'tasks':edits(r)})
    def test_simple_independent_query_still_direct(self):
        import app
        p={**plan(),'query':{'target':'parts','filters':[condition('name','contains','ABC')]}}
        def interpret(q,c,s):self.model_trace(p,q);return p
        with patch.object(app,'interpret',side_effect=interpret),patch('request_checklist.gate',return_value={'decision':'accept','choice':'candidate'}):
            r=self.request('/api/query',{'session':'review-simple','question':'名称含ABC的部件'})
        self.assertEqual(r['status'],'ok');self.assertNotIn('review',r)

if __name__=='__main__':unittest.main(verbosity=2)
