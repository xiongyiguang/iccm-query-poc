import copy
import json
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from business_request import apply_delta,commit_state,RequestInvalid

Q='source Plant3; value above 5; unit blank'

def spec(value,quote=Q):return {'value':value,'quote':quote}
def condition(field,op,value):return {'field':field,'operator':op,'value':value}
def patch(base,fields=None,edits=None,q=Q):return {'base':base,'quote':q,'set':fields or {},'filters':edits or [],**({'unit':{'state':'none','value':''}} if base is None else {})}
def edit(action,ids,conditions,q=Q):return {'action':action,'ids':ids,'conditions':conditions,'quote':q}
def delta(tasks,mode='new'):return {'version':1,'mode':mode,'tasks':tasks}
def seed():
    filters=[condition('source','equals','Plant3'),condition('value','gt','5'),condition('unit','is_blank','')]
    return apply_delta(delta([patch(None,{'operation':spec('search'),'target':spec('points')},[edit('add',[],filters)])]),{},Q)

class BusinessRequestTests(unittest.TestCase):
    def two_object_tasks(self):
        q='C1 C2'
        tasks=[patch(None,{'operation':'attributes','target':'config','properties':['name','code']},[edit('add',[],[condition('code','equals',code)],q)],q) for code in ('C1','C2')]
        return apply_delta(delta(tasks),None,q)[1]
    def test_explicit_task_replacement_preserves_sibling_and_retained_provenance(self):
        state=self.two_object_tasks();original=copy.deepcopy(state);q='first task use class tree, same identifier'
        replacement=patch('t1',{'operation':'attributes','target':'equipment_class','properties':['name','code']},q=q)
        replacement.update(replace_task=True,retain_filters=['f1'])
        p,out,changed=apply_delta(delta([replacement],'update'),state,q)
        self.assertEqual(p['query'],{'target':'equipment_class','filters':[condition('code','equals','C1')]})
        self.assertEqual(changed,['t1']);self.assertEqual(out['tasks'][1],state['tasks'][1]);self.assertEqual(state,original)
        self.assertEqual(out['tasks'][0]['filters'],state['tasks'][0]['filters'])
        self.assertEqual(out['tasks'][0]['sources']['replacement']['previous_target'],'config')
    def test_extra_condition_source_field_is_rejected_with_specific_path(self):
        q='value above 5'
        task=patch(None,{'operation':'search','target':'points'},[edit('add',[],[{**condition('value','gt','5'),'spans':[1]}],q)],q)
        original=copy.deepcopy(task)
        with self.assertRaisesRegex(RequestInvalid,r'tasks.*conditions.*spans'):apply_delta(delta([task]),None,q)
        self.assertEqual(task,original)
    def test_inactive_replacement_fields_preserve_normal_update_and_do_not_allow_target_change(self):
        state=self.two_object_tasks();q='first name only'
        task=patch('t1',{'properties':['name']},q=q)
        task.update(replace_task=False,retain_filters=[])
        _,out,_=apply_delta(delta([task],'update'),state,q)
        self.assertEqual(out['tasks'][0]['properties'],['name'])
        self.assertEqual(out['tasks'][0]['filters'],state['tasks'][0]['filters'])
        self.assertEqual(out['tasks'][1],state['tasks'][1])
        for retained in (None,{},'f1',['missing'],['f1','f1'],['f2']):
            bad=copy.deepcopy(task);bad['retain_filters']=retained
            with self.assertRaises(RequestInvalid):apply_delta(delta([bad],'update'),state,q)
        task['set']['target']='equipment_class'
        with self.assertRaisesRegex(RequestInvalid,'replace_task=true'):apply_delta(delta([task],'update'),state,q)
    def test_partial_retention_assertions_are_semantically_lossless(self):
        import itertools
        _,old,_=seed();q='change value to 8'
        base=patch('t1',edits=[edit('replace',['f2'],[condition('value','gt','8')],q)],q=q)
        expected=apply_delta(delta([base],'update'),old,q)
        for size in range(3):
            for kept in itertools.permutations(['f1','f3'],size):
                d=copy.deepcopy(base);d.update(replace_task=False,retain_filters=list(kept))
                actual=apply_delta(delta([d],'update'),old,q)
                self.assertEqual(actual,expected)
        self.assertEqual(old['tasks'][0]['filters'][1]['value'],'5')
    def test_retention_of_every_unchanged_condition_keeps_ids_and_sources(self):
        _,old,_=seed();t=patch('t1');t['retain_filters']=['f3','f1','f2']
        p,out,changed=apply_delta(delta([t],'update'),old,Q)
        self.assertEqual(out['tasks'][0]['filters'],old['tasks'][0]['filters'])
        self.assertEqual(p['query']['filters'],[condition(f['field'],f['operator'],f['value']) for f in old['tasks'][0]['filters']])
    def test_retention_cannot_overlap_modified_or_removed_condition(self):
        _,old,_=seed();saved=copy.deepcopy(old)
        for action,values in [('replace',[condition('value','gt','8')]),('remove',[])]:
            t=patch('t1',edits=[edit(action,['f2'],values)]);t['retain_filters']=['f2']
            with self.assertRaisesRegex(RequestInvalid,'同时'):apply_delta(delta([t],'update'),old,Q)
            self.assertEqual(old,saved)
    def test_retention_cannot_cross_scope_or_task(self):
        old=self.two_object_tasks()
        for target,kept in [('equipment_class',['f1']),('config',['f2'])]:
            t=patch('t1',{'target':target},q='class');t['retain_filters']=kept
            with self.assertRaises(RequestInvalid):apply_delta(delta([t],'update'),old,'class')
    def test_retention_cannot_create_queries_or_apply_to_notes(self):
        fresh=patch(None,{'operation':'search','target':'parts'},q='list')
        fresh['retain_filters']=['f1']
        with self.assertRaises(RequestInvalid):apply_delta(delta([fresh]),None,'list')
        _,old,_=seed();t=patch('t1');t.update(execute=False,retain_filters=['f1'])
        with self.assertRaises(RequestInvalid):apply_delta(delta([t],'update'),old,Q)
        t=patch('t1',{'operation':'explain','topics':['alarm']});t['retain_filters']=['f1']
        with self.assertRaises(RequestInvalid):apply_delta(delta([t],'update'),old,Q)
    def test_task_replacement_clears_only_unretained_conditions(self):
        state=self.two_object_tasks();q='first task list classes without filters'
        replacement=patch('t1',{'operation':'search','target':'equipment_class','properties':[]},q=q)
        replacement.update(replace_task=True,retain_filters=[])
        p,out,_=apply_delta(delta([replacement],'update'),state,q)
        self.assertEqual(p['query']['filters'],[]);self.assertEqual(out['tasks'][1],state['tasks'][1])
    def test_task_replacement_rejects_cross_task_ids_incomplete_sets_and_mixed_edits(self):
        state=self.two_object_tasks();original=copy.deepcopy(state);q='replace first task'
        good=patch('t1',{'operation':'attributes','target':'equipment_class','properties':['name']},q=q)
        good.update(replace_task=True,retain_filters=['f1'])
        bads=[]
        for ids in (['f2'],['f99'],['f1','f1']):
            b=copy.deepcopy(good);b['retain_filters']=ids;bads.append(b)
        b=copy.deepcopy(good);b['set'].pop('properties');bads.append(b)
        b=copy.deepcopy(good);b['filters']=[edit('remove',['f1'],[],q)];bads.append(b)
        b=copy.deepcopy(good);b['replace_task']=1;bads.append(b)
        b=copy.deepcopy(good);b['replace_task']=False;bads.append(b)
        for b in bads:
            with self.subTest(b=b),self.assertRaises(RequestInvalid):apply_delta(delta([b],'update'),state,q)
            self.assertEqual(state,original)
    def test_retained_filter_incompatible_with_replacement_domain_still_rejected(self):
        _,state,_=seed();original=copy.deepcopy(state);q='replace with config'
        replacement=patch('t1',{'operation':'search','target':'config','properties':[]},q=q)
        replacement.update(replace_task=True,retain_filters=['f2'])
        with self.assertRaises(ValueError):apply_delta(delta([replacement],'update'),state,q)
        self.assertEqual(state,original)
    def test_replacement_keeps_unit_only_when_its_filter_is_explicitly_retained(self):
        q='value above 7 摄氏度'
        first=patch(None,{'operation':'search','target':'points'},[edit('add',[],[condition('value','gt','7'),condition('unit','equals','℃')],q)],q)
        _,state,_=apply_delta(delta([first]),None,q);q='replace first request but keep both conditions'
        replacement=patch('t1',{'operation':'search','target':'points','properties':[]},q=q)
        replacement.update(replace_task=True,retain_filters=['f1','f2'],unit={'state':'none','value':''})
        _,out,_=apply_delta(delta([replacement],'update'),state,q)
        self.assertEqual(out['tasks'][0]['unit'],{'state':'specified','value':'℃'})
        self.assertEqual(out['tasks'][0]['sources']['unit'],state['tasks'][0]['sources']['unit'])
    def test_model_cannot_declare_bare_degree_a_known_numeric_unit(self):
        from business_request import RequestAmbiguous
        q='读数不到29度';task=patch(None,{'operation':'search','target':'points'},[edit('add',[],[condition('value','lt','29'),condition('unit','equals','度')],q)],q)
        task['unit']={'state':'specified','value':'度'}
        with self.assertRaises(RequestAmbiguous) as caught:apply_delta(delta([task]),{},q)
        draft=caught.exception.state;self.assertEqual([f['field'] for f in draft['tasks'][0]['filters']],['value'])
        q='华氏度';p,s,_=apply_delta(delta([patch('t1',edits=[edit('add',[],[condition('unit','equals','℉')],q)],q=q)],'update'),draft,q)
        self.assertEqual(p['query']['filters'],[condition('value','lt','29'),condition('unit','equals','℉')])
    def test_review_intervals_are_computed_by_actual_predicates(self):
        from business_request import review_semantics
        q='50 to 80';t=patch(None,{'operation':'search','target':'points'},[edit('add',[],[condition('value','gte','50'),condition('value','lt','80')],q)],q)
        _,s,c=apply_delta(delta([t]),{},q);i=review_semantics(s,c)[0]['intervals'][0]
        self.assertTrue(i['lower_included']);self.assertFalse(i['upper_included']);self.assertEqual(i['included_boundary_count'],1);self.assertFalse(i['both_endpoints_included'])
    def test_unit_source_binding_is_local_to_task_and_does_not_change_other_sources(self):
        q='readings above 5 摄氏度';t=patch(None,{'operation':'search','target':'points'},[edit('add',[],[condition('unit','equals','℃'),condition('value','gt','5')],'readings above 5')],q)
        t['unit']={'state':'specified','value':'℃'}
        _,s,_=apply_delta(delta([t]),{},q);fs=s['tasks'][0]['filters']
        self.assertEqual(fs[0]['source']['quote'],'摄氏度');self.assertEqual(fs[1]['source']['quote'],'readings above 5')
        t['quote']='readings above 5'
        with self.assertRaises(RequestInvalid):apply_delta(delta([t]),{},q)
    def test_pending_draft_is_separate_and_unit_reply_cannot_revive_old_filters(self):
        from business_request import RequestAmbiguous,extraction_context
        from session_state import snapshot,restore
        _,confirmed,_=seed();q='new request above 65 degrees'
        task=patch(None,{'operation':'search','target':'points'},[edit('add',[],[condition('value','gt','65')],q)],q)
        task['unit']={'state':'ambiguous','value':''}
        with self.assertRaises(RequestAmbiguous) as caught:apply_delta(delta([task]),confirmed,q)
        draft=caught.exception.state;self.assertIsNotNone(draft)
        ctx=commit_state({}, {'engine':'business_request','pending_business_request':draft},{'status':'clarify'},{'business_request':confirmed})
        self.assertEqual(ctx['business_request'],confirmed)
        view=extraction_context(ctx);self.assertEqual(view['business_request'],draft);self.assertEqual(view['request_status'],'awaiting_unit')
        token=snapshot('draft',{'context':ctx,'dialogue':[]},'v');self.assertEqual(restore(token,'draft','v')['context'],ctx)
        q='摄氏度';task=patch('t1',edits=[edit('add',[],[condition('unit','equals','℃')],q)],q=q)
        plan,state,_=apply_delta(delta([task],'update'),draft,q)
        self.assertEqual(plan['query']['filters'],[condition('value','gt','65'),condition('unit','equals','℃')])
        out=commit_state(ctx,{'business_request_state':state},{'status':'ok'},ctx)
        self.assertNotIn('pending_business_request',out);self.assertEqual(out['business_request'],state)
    def test_guessed_celsius_filter_without_literal_unit_is_rejected(self):
        q='above 65 degrees';task=patch(None,{'operation':'search','target':'points'},[edit('add',[],[condition('value','gt','65'),condition('unit','equals','℃')],q)],q)
        with self.assertRaises(RequestInvalid):apply_delta(delta([task]),{},q)
    def test_edit_one_keeps_other_predicates_and_provenance(self):
        _,state,_=seed();before=copy.deepcopy(state);q='change source to Plant1'
        p,out,_=apply_delta(delta([patch('t1',edits=[edit('replace',['f1'],[condition('source','equals','Plant1')],q)],q=q)],'update'),state,q)
        self.assertEqual(state,before)
        self.assertEqual(p['query']['filters'],[condition('value','gt','5'),condition('unit','is_blank',''),condition('source','equals','Plant1')])
        fs={f['id']:f for f in out['tasks'][0]['filters']};self.assertEqual(fs['f2'],state['tasks'][0]['filters'][1]);self.assertEqual(fs['f1']['source']['turn'],2)
    def test_remove_only_named_filter(self):
        _,state,_=seed();q='remove unit filter'
        p,out,_=apply_delta(delta([patch('t1',edits=[edit('remove',['f3'],[],q)],q=q)],'update'),state,q)
        self.assertEqual(len(p['query']['filters']),2);self.assertNotIn('unit',[f['field'] for f in p['query']['filters']])
    def test_new_topic_resets_tasks(self):
        _,state,_=seed();q='list all points'
        p,s,_=apply_delta(delta([patch(None,{'operation':spec('search',q),'target':spec('points',q)},q=q)]),state,q)
        self.assertEqual(p['query']['filters'],[]);self.assertEqual(len(s['tasks']),1)
    def test_unknown_or_repeated_filter_ids_are_rejected(self):
        _,state,_=seed()
        for ids in [['f99'],['f1','f1']]:
            with self.assertRaises(RequestInvalid):apply_delta(delta([patch('t1',edits=[edit('remove',ids,[])])],'update'),state,Q)
        with self.assertRaises(RequestInvalid):apply_delta(delta([patch('t1',edits=[edit('remove',['f1'],[]),edit('remove',['f1'],[])])],'update'),state,Q)
    def test_branch_identity_isolated_and_other_branch_retained(self):
        _,s,_=seed();second=copy.deepcopy(s['tasks'][0]);second['id']='t2'
        for i,f in enumerate(second['filters'],4):f['id']=f'f{i}'
        s['tasks'].append(second);s['next_filter_id']=7;q='second branch remove value'
        p,out,changed=apply_delta(delta([patch('t2',edits=[edit('remove',['f5'],[],q)],q=q)],'update'),s,q)
        self.assertEqual(changed,['t2']);self.assertEqual(out['tasks'][0],s['tasks'][0]);self.assertEqual(len(p['query']['filters']),2)
        with self.assertRaises(RequestInvalid):apply_delta(delta([patch('t2',edits=[edit('remove',['f2'],[],q)],q=q)],'update'),s,q)
    def test_missing_or_historical_quote_rejected(self):
        _,s,_=seed()
        with self.assertRaises(RequestInvalid):apply_delta(delta([patch('t1')],'update'),s,'unrelated new question')
    def test_target_switch_requires_new_request(self):
        _,s,_=seed()
        with self.assertRaises(RequestInvalid):apply_delta(delta([patch('t1',{'target':spec('config')})],'update'),s,Q)
    def test_no_state_no_update(self):
        with self.assertRaises(RequestInvalid):apply_delta(delta([patch('t1')],'update'),{},Q)
    def test_failed_execution_does_not_commit_new_state(self):
        _,state,_=seed();ctx={'business_request':{'old':True}}
        trace={'business_request_state':state}
        for result in [{'status':'error'},{'status':'clarify'},{'status':'batch','items':[{'status':'ok'},{'status':'error'}]}]:
            self.assertEqual(commit_state(copy.deepcopy(ctx),trace,result),ctx)
        self.assertEqual(commit_state({},trace,{'status':'ok'})['business_request'],state)
    def test_signed_history_retains_task_and_condition_ids(self):
        from session_state import snapshot,restore
        _,state,_=seed();s={'context':{'business_request':state},'dialogue':[]}
        token=snapshot('id',s,'version');self.assertEqual(restore(token,'id','version')['context'],s['context'])
    def test_replace_subject_retains_projection(self):
        q='PointA value and prediction';fields={'operation':spec('attributes',q),'target':spec('points',q),'properties':spec(['value','prediction'],q)}
        _,state,_=apply_delta(delta([patch(None,fields,[edit('add',[],[condition('name','equals','PointA')],q)],q)]),{},q)
        q='same fields on PointB';p,s,_=apply_delta(delta([patch('t1',edits=[edit('replace',['f1'],[condition('name','equals','PointB')],q)],q=q)],'update'),state,q)
        self.assertEqual(p['properties'],['value','prediction']);self.assertEqual(s['tasks'][0]['sources']['properties']['turn'],1)
    def test_search_cannot_accidentally_gain_property_projection(self):
        _,state,_=seed()
        with self.assertRaises(RequestInvalid):apply_delta(delta([patch('t1',{'properties':spec(['value'])})],'update'),state,Q)
    def test_invalid_operator_or_unknown_field_never_compiles(self):
        _,s,_=seed()
        for f in [condition('unknown','equals','x'),condition('value','contains','5')]:
            with self.assertRaises(ValueError):apply_delta(delta([patch('t1',edits=[edit('add',[],[f])])],'update'),s,Q)
    def test_unmentioned_endpoint_is_preserved(self):
        _,s,_=seed();q='upper bound 10 included'
        p,s,_=apply_delta(delta([patch('t1',edits=[edit('add',[],[condition('value','lte','10')],q)],q=q)],'update'),s,q)
        q='upper bound now 8';p,s,_=apply_delta(delta([patch('t1',edits=[edit('replace',['f4'],[condition('value','lte','8')],q)],q=q)],'update'),s,q)
        self.assertIn(condition('value','gt','5'),p['query']['filters']);self.assertIn(condition('value','lte','8'),p['query']['filters'])
    def test_single_extraction_compiles_without_second_model(self):
        import model
        from unittest.mock import patch as mockpatch,MagicMock
        request={'version':10,'roles':{'background':[],'output':[1,2,3],'control':[]},'mode':'new','tasks':[{'base':None,'action':'request','request_spans':[1,2,3],'spans':[1,2,3],'purpose':'data','subject_scope':'none','set':{'operation':'search','target':'points','result_goal':__import__('result_goal').default_goal('search')},'filters':[{'action':'add','ids':[],'spans':[1,2,3],'conditions':[condition('value','gt','5')]}],'unit':{'state':'none','value':''}}]}
        response=MagicMock();response.__enter__.return_value.read.return_value=json.dumps({'choices':[{'finish_reason':'stop','message':{'content':json.dumps({'business_request':request,'legacy':None})}}]}).encode()
        with mockpatch.dict(model.os.environ,{'DEEPSEEK_API_KEY':'synthetic','ICCM_REQUEST_ENGINE':'contract'}),mockpatch.object(model.urllib.request,'build_opener') as net:
            net.return_value.open.return_value=response
            p=model.interpret(Q,{},None)
            self.assertEqual(net.return_value.open.call_count,1);self.assertEqual(p['query']['filters'],[condition('value','gt','5')])
            self.assertEqual(model.get_trace()['engine'],'business_request')
    def test_missing_envelope_never_silently_falls_back(self):
        from business_request import unpack_route
        for envelope in [{},{'business_request':None},{'business_request':{},'legacy':{}}]:
            with self.assertRaises(RequestInvalid):unpack_route(envelope)
        prompt=(Path(__file__).resolve().parents[1]/'prompts/system/context-scope-v8.txt').read_text(encoding='utf-8')
        self.assertIn('JSON',prompt)
    def test_literal_grounding_uses_each_tasks_own_span(self):
        from business_request import ground_identifiers
        from data import Store
        # 无需真实数据仓库，用小型 SQLite 表验证数据绑定。
        import sqlite3
        class Mini:
            def __init__(self):
                self.db=sqlite3.connect(':memory:');self.db.row_factory=sqlite3.Row
                self.db.execute('CREATE TABLE points(name TEXT,code TEXT,system TEXT)')
                self.db.executemany('INSERT INTO points VALUES(?,?,?)',[('测量点名称51','C51','S'),('测量点名称52','C52','S')])
            def rows(self,sql,args=()):return [dict(x) for x in self.db.execute(sql,args)]
        store=Mini()
        try:
            q='测量点名称51的值，测量点名称52的预测值';tasks=[]
            for n,prop in [('51','value'),('52','prediction')]:
                quote='测量点名称'+n
                tasks.append(patch(None,{'operation':spec('attributes',quote),'target':spec('points',quote),'properties':spec([prop],quote)},[edit('add',[],[condition('name','equals',n)],quote)],quote))
            _,s,changed=apply_delta(delta(tasks),{},q);out=ground_identifiers(store,s,changed)
            self.assertEqual([t['filters'][0]['value'] for t in out['tasks']],['测量点名称51','测量点名称52']);self.assertEqual(s['tasks'][0]['filters'][0]['value'],'51')
        finally:store.db.close()
    def test_failed_new_query_restores_previous_confirmed_request(self):
        _,s,_=seed();prior={'business_request':s};out=commit_state({'outcome':{}},{'business_request_state':{'new':True}},{'status':'not_found'},prior)
        self.assertEqual(out['business_request'],s)
    def test_numeric_request_cannot_omit_or_guess_ambiguous_unit(self):
        from business_request import RequestAmbiguous
        task=patch(None,{'operation':'search','target':'points'},[edit('add',[],[condition('value','gt','5')])])
        task.pop('unit')
        with self.assertRaises(RequestInvalid):apply_delta(delta([task]),{},Q)
        task['unit']={'state':'ambiguous','value':''}
        with self.assertRaises(RequestAmbiguous):apply_delta(delta([task]),{},Q)
    def test_unit_source_and_filter_agree(self):
        q='above 5 ℃';task=patch(None,{'operation':'search','target':'points'},[edit('add',[],[condition('value','gt','5')],q)],q)
        task['unit']={'state':'specified','value':'℃'}
        with self.assertRaises(RequestInvalid):apply_delta(delta([task]),{},q)
        task['filters'].append(edit('add',[],[condition('unit','equals','℃')],q))
        p,s,_=apply_delta(delta([task]),{},q);self.assertEqual(s['tasks'][0]['unit']['value'],'℃')
        q='remove unit';_,s,_=apply_delta(delta([patch('t1',edits=[edit('remove',['f2'],[],q)],q=q)],'update'),s,q)
        self.assertEqual(s['tasks'][0]['unit']['state'],'none')
    def test_task_directory_not_legacy_focus_controls_branch_input(self):
        from business_request import extraction_context
        _,s,_=seed();ctx={'business_request':s,'entity':{'code':'UNRELATED'},'dialogue':[{'question':'old'}]}
        view=extraction_context(ctx);self.assertNotIn('entity',view);self.assertNotIn('dialogue',view)
        self.assertEqual(view['task_directory'][0]['number'],1);self.assertEqual(view['task_directory'][0]['id'],'t1')
    def test_generated_delta_sequences_preserve_every_untouched_condition(self):
        import random
        rng=random.Random(924)
        for sequence in range(40):
            _,state,_=seed()
            for step in range(25):
                before={f['id']:copy.deepcopy(f) for f in state['tasks'][0]['filters']}
                action=rng.choice(['add','replace','remove'])
                if not before:action='add'
                if len(before)>=7 and action=='add':action='remove'
                ids=[] if action=='add' else [rng.choice(list(before))]
                q=f'change {sequence} {step}'
                field=before[ids[0]]['field'] if ids and action=='replace' else 'rate'
                # 保持对象字面引用原样，其余生成值都是标量。
                value=f'Plant{sequence}_{step}' if field=='source' else str(sequence*100+step)
                q+=' '+value
                op='equals' if field in ('source','unit') else 'gt'
                conditions=[] if action=='remove' else [condition(field,op,value)]
                _,out,_=apply_delta(delta([patch('t1',edits=[edit(action,ids,conditions,q)],q=q)],'update'),state,q)
                after={f['id']:f for f in out['tasks'][0]['filters']}
                for fid,old in before.items():
                    if fid not in ids:self.assertEqual(after[fid],old)
                if action=='remove':self.assertNotIn(ids[0],after)
                self.assertEqual(state['tasks'][0]['filters'],list(before.values()))
                state=out
    def test_coverage_review_has_no_plan_mutation_channel(self):
        import model
        from unittest.mock import patch as mockpatch,MagicMock
        _,s,_=seed();before=copy.deepcopy(s)
        def response(obj):
            r=MagicMock();r.__enter__.return_value.read.return_value=json.dumps({'choices':[{'finish_reason':'stop','message':{'content':json.dumps(obj)}}]}).encode();return r
        with mockpatch.object(model.urllib.request,'build_opener') as net:
            net.return_value.open.return_value=response({'decision':'clarify','issues':[{'kind':'unit','quote':Q}]})
            self.assertEqual(model.review_request_coverage(Q,None,s,['t1'])['decision'],'clarify')
            self.assertEqual(s,before)
            for obj in [{'decision':'accept','issues':[],'plan':{}},{'decision':'clarify','issues':[{'kind':'unit','quote':'not in question'}]}]:
                net.return_value.open.return_value=response(obj)
                with self.assertRaises(model.PlanInvalid):model.review_request_coverage(Q,None,s,['t1'])
    def test_legacy_receipt_bridge_preserves_filters_not_free_text(self):
        from business_request import import_receipt
        filters=[condition('source','equals','Plant3'),condition('value','lt','9')]
        r={'status':'ok','query_receipt':{'operation':'search','query':{'target':'points','filters':filters},'scope':'direct','requested_entity':None}}
        s=import_receipt(r,'original',{});self.assertEqual(s['origin'],'executed_legacy_receipt')
        q='upper bound 8';p,out,_=apply_delta(delta([patch('t1',edits=[edit('replace',['f2'],[condition('value','lt','8')],q)],q=q)],'update'),s,q)
        self.assertIn(filters[0],p['query']['filters']);self.assertEqual(out['tasks'][0]['filters'][0]['source']['kind'],'executed_receipt')
        r['query_receipt']['requested_entity']={'tree':'config','code':'P'};self.assertIsNone(import_receipt(r,'original'))

if __name__=='__main__':unittest.main()
