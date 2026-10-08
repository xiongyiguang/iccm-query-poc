import threading
import unittest
from answers import receipt_answer
from tools import DataTools
from server import Demo


class ReceiptAnswers(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.data = DataTools()

    def test_mixed_population_uses_full_composition(self):
        r = self.data.call('answer-children', 'iccm_children', {'tree':'config','identifier':'MOHB01','depth':'direct','kind':'objects'})
        text = receipt_answer([('iccm_children', r)])
        for wanted in ('52', '部件：51', '子设备：1', '本页显示 20'):self.assertIn(wanted,text)

    def test_formatted_values_are_published_without_raw_scientific_notation(self):
        r = self.data.call('answer-rate','iccm_attributes',{'target':'points','identifier':'XJ1ABC001PO.JVD.1ABC029MV.LBe_Y','properties':['rate','value','unit']})
        text = receipt_answer([('iccm_attributes',r)])
        for wanted in ('-0.000000000405','测量值：0','单位：未提供'):self.assertIn(wanted,text)
        self.assertNotIn('-4.05E-10',text)

    def test_candidate_identity_is_not_a_selected_object(self):
        r=self.data.call('answer-candidate','iccm_find',{'tree':'objects','identifier':'MOHB'})
        text=receipt_answer([('iccm_find',r)])
        for wanted in ('设备类描述1860','构型对象描述14316','尚未选定'):self.assertIn(wanted,text)

    def test_final_model_draft_cannot_replace_the_receipt(self):
        d=Demo.__new__(Demo);d.lock=threading.RLock()
        s={'id':'one','thread':'one','events':[],'business_calls':1,'receipts':[('iccm_query',{'status':'ok','answer':'真实计数为118条。','records':[]})]}
        d.sessions={'one':s}
        d.notify('item/started',{'threadId':'one','item':{'type':'agentMessage','id':'m','phase':'final_answer'}})
        d.notify('item/agentMessage/delta',{'threadId':'one','itemId':'m','delta':'编造999条'})
        self.assertFalse(s['events'])
        d.notify('item/completed',{'threadId':'one','item':{'type':'agentMessage','id':'m','text':'编造999条','phase':'final_answer'}})
        self.assertEqual(s['events'][-1]['text'],'真实计数为118条。')
        self.assertEqual(s['events'][-1]['model_draft'],'编造999条')

    def test_explanation_of_filtered_children_uses_actual_parent_reference(self):
        r=self.data.call('answer-explain','iccm_children',{'tree':'config','identifier':'MOHB01','depth':'direct','kind':'parts'})
        e=self.data.call('answer-explain','iccm_explain',{'result_id':r['result_id']})
        text=receipt_answer([('iccm_explain',e)])
        self.assertIn('真实父对象编码',text);self.assertTrue(e['evidence'])

    def test_clarification_overrides_preliminary_lookup(self):
        text=receipt_answer([('iccm_find',{'status':'ok','answer':'找到对象'}),
                             ('iccm_query',{'status':'clarify','answer':'请选择直接或全部下级'})])
        self.assertEqual(text,'请选择直接或全部下级')


if __name__=='__main__':unittest.main(verbosity=2)
