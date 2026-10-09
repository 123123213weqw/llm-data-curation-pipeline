"""Exact request-key to record-ID reservation binding; text SHA is not record ID."""
def verify_reservation_pairs(actual,expected):
 actual=list(actual);expected=list(expected)
 if len(set(actual))!=len(actual) or len(set(expected))!=len(expected):raise ValueError('Duplicate exact reservation binding')
 if any(len(t)!=3 or any(not isinstance(x,str) or not x for x in t) for t in actual+expected):raise ValueError('Invalid exact reservation triple')
 for rows in (actual,expected):
  if len({r[0] for r in rows})!=len(rows) or len({r[1] for r in rows})!=len(rows):raise ValueError('Repeated record ID or request key')
 if set(actual)!=set(expected):raise ValueError('Exact record-ID/request-key/job reservation mismatch')
 return dict(records=len(actual),exact_body_key_job_binding=True,text_sha_not_used_as_record_id=True)

import base64,zlib,json,hashlib
LIMIT=64*1024*1024
def encode_boundary(value):
 raw=json.dumps(value,ensure_ascii=False,separators=(',',':')).encode()
 if len(raw)>LIMIT:raise ValueError('Boundary too large')
 return dict(encoding='zlib-base64-v146',bytes=len(raw),content_sha256=hashlib.sha256(raw).hexdigest(),payload=base64.b64encode(zlib.compress(raw)).decode())
def decode_boundary(value):
 if set(value)!={'encoding','bytes','content_sha256','payload'} or value['encoding']!='zlib-base64-v146':raise ValueError('Invalid boundary envelope')
 if type(value['bytes']) is not int or not 0<=value['bytes']<=LIMIT:raise ValueError('Invalid boundary size')
 packed=base64.b64decode(value['payload'],validate=True);z=zlib.decompressobj();raw=z.decompress(packed,LIMIT+1)
 if len(raw)>LIMIT or not z.eof or z.unused_data or z.unconsumed_tail:raise ValueError('Invalid bounded compressed stream')
 if len(raw)!=value['bytes'] or hashlib.sha256(raw).hexdigest()!=value['content_sha256']:raise ValueError('Boundary content SHA/size mismatch')
 result=json.loads(raw)
 if not isinstance(result,dict):raise ValueError('Boundary must be object')
 return result

def cached_boundary(rc):
 from pathlib import Path
 from common import sha
 p=Path(rc['cached_gpu_boundary'])
 if sha(p)!=rc['cached_gpu_boundary_sha256']:raise ValueError('Cached actual boundary bytes changed')
 v=json.loads(p.read_text());n=rc['expected_prior_requests']
 if type(n) is not int or n<=0 or len(v['body_ids'])!=n or len(v['request_keys'])!=n or len(set(v['body_ids']))!=n or len(set(v['request_keys']))!=n:raise ValueError('Actual prior request coverage changed')
 if v['reservation_binding']!=dict(records=n,exact_body_key_job_binding=True,text_sha_not_used_as_record_id=True):raise ValueError('Actual exact binding missing')
 if v['full_physical_receipts_verified']!=n or sum(v['ledger_counts'].values())!=n or not v['no_teacher_requests']:raise ValueError('Actual terminal physical coverage missing')
 prefix=rc['old_remote_root']+'/'
 if any(not p.startswith(prefix) or '..' in p.split('/') or len(h)!=64 or any(c not in '0123456789abcdef' for c in h) for p,h in v['files_sha256'].items()):raise ValueError('Wrong frozen remote evidence map')
 if not v['files_sha256'] or v['unit']['MainPID']!='0':raise ValueError('Prior GPU not terminal')
 return v
