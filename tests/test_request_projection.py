"""属性交付证明的真实身份、字段来源和未修改任务反例。"""
import copy,json,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from data import Store
from result_goal import default_goal
from request_projection import explicit_scalar_projection_choice

class ProjectionProof(unittest.TestCase):
 def setUp(self):
  self.store=Store(dataset=[{'kind':'points','file':'points.csv','sha256':'fixture','seed':True,'rows':[{'测量点编码':'P_A','测量点名称':'测量点甲','测量值':'1.25'},{'测量点编码':'P_B','测量点名称':'测量点乙','测量值':'2.50'},{'测量点编码':'P_C','测量点名称':'测量值仪','测量值':'3.75'}]}])
 def tearDown(self):self.store.db.close()
 def plans(self,name='测量点甲',props=None):
  ids=[[r['line'],r['code']] for r in self.store.rows('SELECT line,code FROM points WHERE name=?',[name])]
  a={'task_id':'t1','operation':'search','target':'points','scope':'direct','properties':[],'filters':[('resolved_identity','equals',json.dumps(ids))],'unit':{'state':'none','value':''},'purpose':'data','result_goal':default_goal('search')}
  b=copy.deepcopy(a);b.update(operation='attributes',properties=props or ['value'],result_goal=default_goal('attributes'));return a,b
 def choice(self,q,a=None,b=None,fa=None,fb=None):
  if a is None:a,b=self.plans()
  return explicit_scalar_projection_choice(q,a,b,fa or [a],fb or [b],self.store)
 def test_exact_point_and_requested_value_select_attribute_delivery(self):self.assertEqual(self.choice('开始新问题，查询测量点甲的测量值'),'independent')
 def test_candidate_attributes_are_also_selected_by_current_source(self):
  a,b=self.plans();self.assertEqual(self.choice('查询测量点甲的测量值',b,a),'candidate')
 def test_field_word_inside_identity_is_not_a_requested_projection(self):
  a,b=self.plans('测量值仪');self.assertIsNone(self.choice('查询测量值仪',a,b))
 def test_value_filter_is_not_reinterpreted_as_plain_read(self):self.assertIsNone(self.choice('查询测量点甲测量值大于1的记录'))
 def test_multiple_current_identities_cannot_share_one_scalar_proof(self):self.assertIsNone(self.choice('查询测量点甲和测量点乙的测量值'))
 def test_wrong_requested_property_is_not_selected(self):
  a,b=self.plans(props=['time']);self.assertIsNone(self.choice('查询测量点甲的测量值',a,b))
 def test_different_preserved_task_is_not_ignored(self):
  a,b=self.plans();other=copy.deepcopy(a);other['task_id']='t2';changed=copy.deepcopy(other);changed['properties']=['time'];self.assertIsNone(self.choice('查询测量点甲的测量值',a,b,[a,other],[b,changed]))
 def test_extra_source_filter_must_still_agree(self):
  a,b=self.plans();b['filters'].append(('source','equals','S'));self.assertIsNone(self.choice('查询测量点甲的测量值',a,b))

if __name__=='__main__':unittest.main()
