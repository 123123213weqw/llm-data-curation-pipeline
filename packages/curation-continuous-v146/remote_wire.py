"""Compress frozen scripts before SSH; commands small, large deployments use packed stdin."""
import base64,zlib,shlex
def script_transport(code,limit=24576):
 if not isinstance(code,str) or not code or type(limit) is not int or limit<128:raise ValueError('Invalid frozen script transport')
 packed=base64.b64encode(zlib.compress(code.encode())).decode()
 if len(packed)<=limit:
  wrapper='import base64,zlib;exec(zlib.decompress(base64.b64decode('+repr(packed)+')))';stdin=None;mode='compressed-argument'
 else:
  wrapper='import sys,base64,zlib;exec(zlib.decompress(base64.b64decode(sys.stdin.buffer.read(),validate=True)))';stdin=packed;mode='compressed-stdin'
 return '/srv/curation/venv/bin/python -B -c '+shlex.quote(wrapper),stdin,mode
