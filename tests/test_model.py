import json,sys,unittest,urllib.error
from pathlib import Path
from unittest.mock import patch,MagicMock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import model

class ModelTests(unittest.TestCase):
    def test_no_key_no_network(self):
        with patch.dict(model.os.environ,{},clear=True),patch.object(model.urllib.request,'build_opener') as net:
            self.assertFalse(model.status()['available'])
            with self.assertRaises(model.ModelUnavailable):model.interpret('test',{},None)
            net.assert_not_called()
    def test_contract(self):
        good={'operation':'parts','entity':{'tree':'config','code':'TEST'},'scope':'all','clarification':''}
        self.assertEqual(model.validate(good),good)
        for bad in [[],{**good,'sql':'SELECT 1'},{**good,'entity':{'tree':'other','code':'TEST'}},{**good,'scope':'unknown'}]:
            with self.assertRaises(model.ModelUnavailable):model.validate(bad)
    def test_request_and_response(self):
        intent={'operation':'clarify','entity':None,'scope':'direct','clarification':'请明确对象'}
        response=MagicMock();response.__enter__.return_value.read.return_value=json.dumps({'choices':[{'finish_reason':'stop','message':{'content':json.dumps(intent)}}]}).encode()
        route=MagicMock();route.__enter__.return_value.read.return_value=json.dumps({'choices':[{'message':{'content':json.dumps({'unit':{'state':'none','value':''},'reference':None,'projection':'specified','scope':None,'needs_history':False,'identifier_field':None})}}]}).encode()
        with patch.dict(model.os.environ,{'DEEPSEEK_API_KEY':'test-only','ICCM_REQUEST_ENGINE':'legacy'}),patch.object(model.urllib.request,'build_opener') as factory:
            factory.return_value.open.side_effect=[route,response]
            self.assertEqual(model.interpret('test',{},None),intent)
            self.assertEqual(factory.return_value.open.call_count,2)
            req=factory.return_value.open.call_args.args[0];body=json.loads(req.data)
            self.assertEqual(req.full_url,'https://api.deepseek.com/chat/completions')
            self.assertEqual(body['thinking'],{'type':'disabled'})
            self.assertEqual(body['response_format'],{'type':'json_object'})
            self.assertNotIn('test-only',body['messages'][0]['content'])
    def test_http_error_does_not_leak(self):
        with patch.dict(model.os.environ,{'DEEPSEEK_API_KEY':'test-only','ICCM_REQUEST_ENGINE':'legacy'}),patch.object(model.urllib.request,'build_opener') as f:
            f.return_value.open.side_effect=urllib.error.HTTPError(model.ENDPOINT,401,'secret-response',{},None)
            with self.assertRaises(model.ModelUnavailable) as c:model.interpret('test',{},None)
            self.assertNotIn('secret-response',str(c.exception));self.assertIn('密钥无效',str(c.exception))
    def test_redirect_not_followed(self):
        self.assertIsNone(model.NoRedirect().redirect_request(None,None,302,'',{},'https://elsewhere.invalid'))
    def test_route_repairs_invalid_field_once(self):
        intent={'operation':'search','entity':None,'scope':'direct','clarification':'','query':{'target':'points','filters':[{'field':'value','operator':'gt','value':'60'}]}}
        route={'unit':{'state':'none','value':''},'reference':None,'projection':'specified','scope':None,'needs_history':False,'identifier_field':None,'resolved_question':None,'domain':'points','thresholds':None,'comparisons':[{'field':'actual','operator':'gt','value':'60'}]}
        fixed={**route,'comparisons':intent['query']['filters']}
        def response(value):
            reply=MagicMock();reply.__enter__.return_value.read.return_value=json.dumps({'choices':[{'finish_reason':'stop','message':{'content':json.dumps(value)}}]}).encode();return reply
        with patch.dict(model.os.environ,{'DEEPSEEK_API_KEY':'test-only','ICCM_REQUEST_ENGINE':'legacy'}),patch.object(model.urllib.request,'build_opener') as factory:
            factory.return_value.open.side_effect=[response(route),response(fixed),response(intent)]
            self.assertEqual(model.interpret('测量值大于60',{},None),intent)
            self.assertEqual(factory.return_value.open.call_count,3)
            self.assertEqual(model.get_trace()['context_route']['repairs'],1)
    def test_unknown_route_domain_does_not_widen_explicit_plan(self):
        intent={'operation':'attributes','entity':None,'scope':'direct','clarification':'','query':{'target':'config','filters':[{'field':'code','operator':'equals','value':'MOHB01'}]},'properties':['name','type']}
        route={'unit':{'state':'none','value':''},'reference':None,'projection':'specified','scope':None,'needs_history':False,'identifier_field':'code','resolved_question':None,'domain':None,'thresholds':None,'comparisons':[]}
        responses=[]
        for value in [route,intent]:
            response=MagicMock();response.__enter__.return_value.read.return_value=json.dumps({'choices':[{'finish_reason':'stop','message':{'content':json.dumps(value)}}]}).encode();responses.append(response)
        with patch.dict(model.os.environ,{'DEEPSEEK_API_KEY':'test-only','ICCM_REQUEST_ENGINE':'legacy'}),patch.object(model.urllib.request,'build_opener') as factory:
            factory.return_value.open.side_effect=responses
            self.assertEqual(model.interpret('构型对象编码为MOHB01，告诉我名称和类型',{},None),intent)

if __name__=='__main__':unittest.main(verbosity=2)
