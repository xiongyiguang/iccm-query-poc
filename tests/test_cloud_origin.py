import unittest,sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from app import Handler
class CloudOrigin(unittest.TestCase):
 def setUp(self):
  self.h=object.__new__(Handler);self.h.server=SimpleNamespace(server_port=18765)
 def test_default_rejects_public(self):
  with patch.dict('os.environ',{'ICCM_PUBLIC_ORIGIN':''}):
   self.assertFalse(self.h.allowed_origin('http://106.53.130.181:8899'))
   self.assertTrue(self.h.allowed_origin('http://127.0.0.1:18765'))
 def test_explicit_origin_exact_only(self):
  with patch.dict('os.environ',{'ICCM_PUBLIC_ORIGIN':'http://106.53.130.181:8899'}):
   self.assertTrue(self.h.allowed_origin('http://106.53.130.181:8899'))
   for origin in ['http://evil.example','http://106.53.130.181:8899.evil.example','null','https://106.53.130.181:8899']:
    self.assertFalse(self.h.allowed_origin(origin))
 def test_public_host_still_rejected(self):
  self.h.headers={'Host':'106.53.130.181:8899'};self.assertFalse(self.h.allowed_host())
  self.h.headers={'Host':'127.0.0.1:18765'};self.assertTrue(self.h.allowed_host())
