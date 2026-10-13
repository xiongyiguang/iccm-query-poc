"""验证分类、型号与现场实例的角色，及客户原题的固定数据基线。"""
import copy
import csv
import json
import sys
import unittest
from collections import Counter
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from data import Store,SOURCE,QueryError
from relational_query import Graph,canonical,execute_task,NodeRoleUnknown

def object_row(code,parent,kind,config=False,cls='B'):
    row={'对象代码':code,'父对象代码':parent,'对象描述中文':code,'对象层级':kind}
    if config:row.update(对象层级='7',对象层级描述=kind,所属部件类代码=cls)
    return row

def dataset():
    return {'pbs':[object_row('L','','功能位置'),object_row('OTHER','','功能位置'),
        object_row('L&D','L','设备'),object_row('L&E','L','设备'),object_row('OTHER&D','OTHER','设备'),
        object_row('L&D#p','L&D','部件'),object_row('L&E#p','L&E','部件'),object_row('OTHER&D#p','OTHER&D','部件')],
        'config':[object_row('TOP','','大类',True),object_row('C','TOP','小类',True),object_row('D','C','设备',True),object_row('E','C','设备',True),object_row('D#p','D','部件',True),object_row('E#p','E','部件',True)],
        'equipment_class':[{'对象编码':c,'父对象编码':p,'描述':n,'层级':lv} for c,p,n,lv in [('TOP','','类别顶层','1'),('C','TOP','类别','3'),('D','C','设备类名称但实际型号','3'),('E','C','另一型号','4')]],
        'part_class':[{'对象编码':'B','父对象编码':'','对象描述中文':'部件分类','对象层级':'4'}],
        'points':[{'测量点编码':'L&D#p','测量点名称':'点','源系统':'S','开关':'开启','状态':''}]}

class EquipmentRoles(unittest.TestCase):
    def setUp(self):self.raw=dataset();self.store=self.make(self.raw);self.graph=Graph(self.store)
    def tearDown(self):self.store.db.close()
    def make(self,raw):return Store(dataset=[{'kind':k,'file':k+'.csv','sha256':k,'rows':v,'seed':True} for k,v in raw.items()])
    def query(self,**changes):
        return canonical({'root':{'tree':'pbs','field':'code','value':'L'},'kind':'collection','population':'parts','classes':{'equipment_class':'D'},**changes})
    def result(self,**changes):return execute_task(self.graph,self.query(**changes))
    def test_model_leaf_does_not_select_sibling_or_other_location(self):
        r=self.result();self.assertEqual([x['code'] for x in r['record_facts']],['L&D#p']);self.assertEqual(r['selection_roles'][0]['role'],'equipment_config')
    def test_model_name_and_code_same_identity(self):self.assertEqual(self.result(classes={'equipment_class':'设备类名称但实际型号'})['record_facts'],self.result()['record_facts'])
    def test_numeric_level_three_can_still_be_model(self):self.assertEqual(self.graph.classify({'equipment_class':'D'}),{'equipment_config':'D'})
    def test_true_class_includes_two_models(self):self.assertEqual(self.result(classes={'equipment_class':'C'})['population_facts']['part_total'],2)
    def test_class_ancestor_uses_parent_chain(self):self.assertEqual(self.result(classes={'equipment_class':'TOP'})['population_facts']['part_total'],2)
    def test_device_population_matches_model(self):self.assertEqual([r['code'] for r in self.result(population='devices')['record_facts']],['L&D'])
    def test_points_keep_same_model_and_source(self):self.assertEqual(self.result(population='points',filters=[{'field':'source','operator':'equals','value':'S'}])['population_facts']['record_count'],1)
    def test_part_class_condition_is_not_dropped(self):self.assertEqual(self.result(classes={'equipment_class':'D','part_class':'B'})['population_facts']['part_total'],1)
    def test_direct_scope_not_replaced_by_model_scope(self):self.assertEqual(self.result(depth='direct')['population_facts']['part_total'],0)
    def test_config_scope_never_becomes_pbs_instances(self):self.assertEqual([r['code'] for r in self.result(root={'tree':'config','field':'code','value':'D'})['record_facts']],['D#p'])
    def test_pbs_identity_cannot_be_class_selector(self):
        with self.assertRaises(QueryError):self.result(classes={'equipment_class':'L&D'})
    def test_parent_conflict_fails_closed(self):
        self.graph.objects[('config','D')]={**self.graph.objects[('config','D')],'parent':'WRONG'}
        r=self.result();self.assertEqual(r['status'],'data_insufficient');self.assertEqual(r['metrics'],[]);self.assertFalse(r['outcome']['count_computed'])
    def test_non_device_alias_fails_closed(self):
        self.graph.objects[('config','D')]={**self.graph.objects[('config','D')],'level':'子设备'}
        self.assertEqual(self.result()['status'],'data_insufficient')
    def test_missing_config_is_unknown_role_not_empty_collection(self):
        self.graph.objects.pop(('config','D'))
        r=self.result();self.assertEqual(r['status'],'data_insufficient');self.assertNotIn('population_facts',r);self.assertEqual(r['metrics'],[])
    def test_classify_conflict_cannot_return_an_executable_selector(self):
        self.graph.objects[('config','D')]={**self.graph.objects[('config','D')],'parent':'WRONG'}
        with self.assertRaises(NodeRoleUnknown):self.graph.classify({'equipment_class':'D'})
    def test_actual_device_reports_class_and_config_separately(self):
        links=self.graph.links(self.graph.objects[('pbs','L&D')]);self.assertEqual(links['equipment_config']['code'],'D');self.assertEqual(links['equipment_class']['code'],'C');self.assertEqual(links['pbs_device']['code'],'L&D')
    def test_model_parent_cannot_be_reported_as_equipment_class(self):
        self.graph.objects[('config','D')]={**self.graph.objects[('config','D')],'parent':'E'}
        links=self.graph.links(self.graph.objects[('pbs','L&D')]);self.assertEqual(links['equipment_config']['code'],'D');self.assertIsNone(links['equipment_class'])
        result=self.result(root={'tree':'pbs','field':'code','value':'L&D'},kind='relation',population='objects',classes={})
        self.assertEqual(result['relation_facts']['equipment_class'],[]);self.assertTrue(any(x['role']=='equipment_class' for x in result['missing_links']))
    def test_legacy_and_graph_use_same_model_selection(self):
        from related_parts import execute_related_parts
        r=execute_related_parts(self.store,{'entity':{'tree':'pbs','code':'L'},'scope':'all','query':{'target':'parts','filters':[],'equipment_class':{'field':'name','operator':'equals','value':'设备类名称但实际型号'}}})
        self.assertEqual([x['code'] for x in r['records']],['L&D#p'])

@unittest.skipUnless((SOURCE/'pbs.csv').exists(),'客户脱敏CSV保留在仓库外，本环境未提供')
class CustomerOnsiteBaseline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.store=Store();cls.graph=Graph(cls.store)
    @classmethod
    def tearDownClass(cls):cls.store.db.close()
    def test_original_model_node_scope_and_class_count(self):
        r=execute_task(self.graph,canonical({'root':{'tree':'pbs','field':'code','value':'XJ3ABC002RR'},'kind':'collection','population':'parts','classes':{'equipment_class':'设备类描述3727'}}))
        self.assertEqual((r['population_facts']['part_total'],r['population_facts']['distinct_resolved_classes']),(90,23));self.assertEqual(r['classification_coverage']['unresolved'],0)
        # 原CSV父链独立计算，不用被测Graph的关系或筛选作预期。
        def read(name):
            with (SOURCE/name).open(encoding='gb18030',newline='') as f:return list(csv.DictReader(f))
        pbs=read('pbs.csv');cfg={r['对象代码']:r for r in read('构型树.csv')};parent={r['对象代码']:r['父对象代码'] for r in pbs}
        def below(code,root):
            seen=set()
            while code in parent and code not in seen:
                if parent[code]==root:return True
                seen.add(code);code=parent[code]
            return False
        parts=[r for r in pbs if r['对象层级']=='部件' and below(r['对象代码'],'XJ3ABC002RR&RRGA02')]
        classes={cfg[r['对象代码'].split('&',1)[1]]['所属部件类代码'] for r in parts}
        self.assertEqual((len(parts),len(classes)),(90,23));self.assertEqual({r['code'] for r in r['record_facts']},{p['对象代码'] for p in parts})
    def test_original_config_all_and_direct_are_separate(self):
        for depth,total in [('all',5749),('direct',0)]:
            r=execute_task(self.graph,canonical({'root':{'tree':'config','field':'name','value':'构型对象描述10435'},'kind':'collection','population':'parts','depth':depth}))
            self.assertEqual(r['population_facts']['part_total'],total)

if __name__=='__main__':unittest.main()
