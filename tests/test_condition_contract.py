import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import test_relational_query as fixture
from query_filters import condition_contract,OPERATORS
from relational_continuity import prepared_context
from relational_state import reference


class Contract(unittest.TestCase):
 @classmethod
 def setUpClass(cls):fixture.Relations.setUpClass();cls.store=fixture.Relations.s
 def context(self,root=None,goal='records'):
  return {'entity':root,'query_receipt':{'operation':'search','grain':'measurement_record','resolved_entity':root,'query':{'target':'points','filters':[{'field':'source','operator':'equals','value':'S'}]},'result_goal':{'kind':goal},'goal_receipt':{'completed':True},'scope':'all'}}
 def test_operator_catalog_matches_actual_validator(self):self.assertEqual(set(condition_contract()['operators']),OPERATORS)
 def test_date_period_has_separate_precision_and_operator(self):
  d=condition_contract()['date'];self.assertEqual(d['field'],'time');self.assertEqual(d['calendar_period_operator'],'date_equals');self.assertIn('month',d['precision_encoding'])
 def test_confirmed_global_point_records_can_continue_as_relation(self):
  ctx=self.context();out=prepared_context(ctx,self.store);spec=out['relational_state']['tasks'][0]['spec'];self.assertIsNone(spec['root']);self.assertEqual(spec['filters'],ctx['query_receipt']['query']['filters']);self.assertNotIn('relational_state',ctx)
 def test_confirmed_root_point_collection_can_continue(self):
  out=prepared_context(self.context({'tree':'pbs','code':'L&D'}),self.store);self.assertEqual(out['relational_state']['tasks'][0]['spec']['root']['value'],'L&D')
 def test_point_attribute_or_unexecuted_query_is_not_site_root(self):
  ctx=self.context();ctx['query_receipt']['operation']='attributes';self.assertNotIn('relational_state',prepared_context(ctx,self.store));ctx['query_receipt']['operation']='search';ctx['query_receipt']['goal_receipt']['completed']=False;self.assertNotIn('relational_state',prepared_context(ctx,self.store))
 def test_numeric_or_count_goal_is_not_replaced_by_record_collection(self):
  for goal in ('sort','extreme','count'):self.assertNotIn('relational_state',prepared_context(self.context(goal=goal),self.store))
 def test_unknown_root_or_multiple_task_context_is_not_bridged(self):
  self.assertNotIn('relational_state',prepared_context(self.context({'tree':'pbs','code':'MISSING'}),self.store));ctx=self.context();ctx['business_request']={'tasks':[{'id':'t1'},{'id':'t2'}]};self.assertNotIn('relational_state',prepared_context(ctx,self.store))
 def test_catalog_table_target_is_explicit_global_reference(self):self.assertIsNone(reference({'type':'global','quote':'监测表'},'独立问题：监测表来源等于S',{},self.store))
