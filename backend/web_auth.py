"""可选云端登录，使用密码哈希和有有效期的服务端会话。"""
import os,time,secrets,hashlib,hmac,threading
from http.cookies import SimpleCookie,CookieError
class WebAuth:
 def __init__(self):self.sessions={};self.attempts={};self.lock=threading.RLock()
 def required(self):return os.environ.get('ICCM_AUTH_REQUIRED')=='1'
 def valid(self,cookie):
  if not self.required():return True
  try:c=SimpleCookie(cookie or '');token=c['iccm_session'].value
  except (KeyError,ValueError,CookieError):return False
  with self.lock:
   return self.sessions.get(token,0)>time.time()
 def login(self,username,password,ip):
  if not self.required():return 200,{'ok':True},None
  configured=os.environ.get('ICCM_AUTH_PASSWORD_HASH','')
  if not configured:return 503,{'error':'登录配置尚未就绪，请联系管理员。'},None
  now=time.time()
  with self.lock:
   self.attempts={k:v for k,v in self.attempts.items() if v[1]>now}
   n,until=self.attempts.get(ip,(0,now+60))
   if n>=8:return 429,{'error':'尝试次数较多，请一分钟后重试。'},None
   self.attempts[ip]=(n+1,until)
   if len(self.attempts)>4096:return 429,{'error':'登录繁忙，请稍后重试。'},None
  try:
   salt,expected=configured.split('$',1)
   actual=hashlib.pbkdf2_hmac('sha256',password.encode(),bytes.fromhex(salt),200000).hex()
   verified=hmac.compare_digest(actual,expected) and hmac.compare_digest(username.encode(),os.environ.get('ICCM_AUTH_USER','iccm').encode())
  except (ValueError,TypeError):return 503,{'error':'登录配置尚未就绪，请联系管理员。'},None
  if not verified:return 401,{'error':'账号或密码不正确，请重新输入。'},None
  with self.lock:
   self.attempts.pop(ip,None)
   self.sessions={k:v for k,v in self.sessions.items() if v>now}
   if len(self.sessions)>=1024:return 429,{'error':'登录会话较多，请稍后重试。'},None
   token=secrets.token_urlsafe(32);self.sessions[token]=now+8*3600
  return 200,{'ok':True},self.cookie(token,8*3600)
 def cookie(self,token,age):
  secure='; Secure' if os.environ.get('ICCM_PUBLIC_ORIGIN','').startswith('https://') else ''
  return f'iccm_session={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age={age}'+secure
 def logout(self,cookie):
  try:
   token=SimpleCookie(cookie or '')['iccm_session'].value
   with self.lock:self.sessions.pop(token,None)
  except (KeyError,ValueError,CookieError):pass
  return self.cookie('',0)
AUTH=WebAuth()
