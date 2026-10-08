import unittest,sys,os,hashlib,json,threading,urllib.request,urllib.error
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from web_auth import WebAuth
import app
SALT='0123456789abcdef0123456789abcdef'
HASH=SALT+'$'+hashlib.pbkdf2_hmac('sha256',b'test-only-password',bytes.fromhex(SALT),200000).hex()
class LoginTests(unittest.TestCase):
 def setUp(self):
  self.env=patch.dict(os.environ,{'ICCM_AUTH_REQUIRED':'1','ICCM_AUTH_USER':'iccm','ICCM_AUTH_PASSWORD_HASH':HASH,'ICCM_PUBLIC_ORIGIN':'http://example.test:8899'});self.env.start();self.auth=WebAuth()
 def tearDown(self):self.env.stop()
 def test_password_cookie_logout(self):
  status,_,cookie=self.auth.login('iccm','test-only-password','test');self.assertEqual(status,200)
  self.assertIn('HttpOnly',cookie);self.assertIn('SameSite=Strict',cookie);self.assertTrue(self.auth.valid(cookie))
  self.auth.logout(cookie);self.assertFalse(self.auth.valid(cookie))
 def test_expiry_forgery(self):
  _,_,cookie=self.auth.login('iccm','test-only-password','test');self.assertFalse(self.auth.valid('iccm_session=forged'))
  with patch('web_auth.time.time',return_value=10**12):self.assertFalse(self.auth.valid(cookie))
 def test_throttling(self):
  for i in range(8):self.assertEqual(self.auth.login('iccm','bad','test')[0],401)
  self.assertEqual(self.auth.login('iccm','test-only-password','test')[0],429)
 def test_config_and_local(self):
  with patch.dict(os.environ,{'ICCM_AUTH_PASSWORD_HASH':''}):self.assertEqual(self.auth.login('iccm','x','test')[0],503)
  with patch.dict(os.environ,{'ICCM_AUTH_REQUIRED':''}):self.assertTrue(self.auth.valid(None))
  with patch.dict(os.environ,{'ICCM_PUBLIC_ORIGIN':'https://example.test'}):self.assertIn('; Secure',self.auth.cookie('x',10))
 def test_http_gate_and_flow(self):
  with patch.object(app,'AUTH',self.auth):
   server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
   base='http://127.0.0.1:'+str(server.server_port)
   def call(path,body=None,cookie=None,origin=None):
    headers={'Content-Type':'application/json','Origin':origin or base}
    if cookie:headers['Cookie']=cookie
    req=urllib.request.Request(base+path,data=json.dumps(body).encode() if body is not None else None,headers=headers)
    return urllib.request.urlopen(req,timeout=5)
   try:
    with call('/') as r:self.assertTrue(r.url.endswith('/login'));self.assertIn('登录工作空间',r.read().decode())
    for path in ['/api/meta','/api/import/schema']:
     with self.assertRaises(urllib.error.HTTPError) as c:call(path)
     self.assertEqual(c.exception.code,401)
    with self.assertRaises(urllib.error.HTTPError) as c:call('/api/import/commit',{})
    self.assertEqual(c.exception.code,401)
    with self.assertRaises(urllib.error.HTTPError) as c:call('/api/auth/login',{'username':'iccm','password':'test-only-password'},origin='http://evil.example')
    self.assertEqual(c.exception.code,403)
    with call('/api/auth/login',{'username':'iccm','password':'test-only-password'}) as r:cookie=r.headers['Set-Cookie']
    with call('/',cookie=cookie) as r:self.assertIn('退出登录',r.read().decode())
    with call('/api/auth/logout',{},cookie) as r:self.assertIn('Max-Age=0',r.headers['Set-Cookie'])
    with call('/',cookie=cookie) as r:self.assertTrue(r.url.endswith('/login'))
   finally:server.shutdown();server.server_close()
