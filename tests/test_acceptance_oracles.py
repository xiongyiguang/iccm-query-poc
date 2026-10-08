import copy,unittest
from replay_semantic_holdout import check

class AcceptanceOracleTests(unittest.TestCase):
 def setUp(self):
  self.expected={'kind':'unsupported'}
  self.note={'status':'conversation','answer':'不提供故障诊断及维修决策。','records':[]}
 def accepted(self,response):
  return all(v for k,v in check(self.expected,response).items() if k!='needs_review')
 def test_explicit_boundary_without_companion_query_is_candidate(self):
  self.assertTrue(self.accepted(self.note))
  self.assertTrue(self.accepted({'status':'batch','items':[self.note]}))
 def test_boundary_cannot_hide_successful_extra_read(self):
  read={'status':'ok','attributes':[{'property':'time','value':'1970'}],'records':[]}
  self.assertFalse(self.accepted({'status':'batch','items':[read,self.note]}))
 def test_even_empty_extra_query_is_not_authorized(self):
  for status in ('ok','not_found'):
   self.assertFalse(self.accepted({'status':'batch','items':[{'status':status,'records':[]},self.note]}))
 def test_note_status_cannot_hide_structured_results(self):
  for key in ('records','attributes','metrics','threshold_details'):
   bad={**self.note,key:[{'value':'1'}]}
   self.assertFalse(self.accepted({'status':'batch','items':[bad]}))

if __name__=='__main__':unittest.main()
