"""Once-only original full publisher. Transport may wait; teacher requests never retry."""
import argparse,base64,json,os,re,shlex,sqlite3,subprocess,sys,time,zlib
from pathlib import Path
from common import sha,frozen,atomic,terminal_ok

SSH=['ssh','-p','2222','-o','BatchMode=yes','-o','ControlPath=none','-o','ConnectTimeout=8','-o','ForwardAgent=no','-o','StrictHostKeyChecking=yes','GPU_WORKER']
REMOTE=Path('/srv/gpu-worker/experiments/qwen38-fp8-serving-v1/curation_fallback_v25/night_idle_20261005_v109')

def safe_item(item):
 if not re.fullmatch(r'(qwen131_[a-f0-9]{24})',item['name']):
  plan=json.loads((Path(__file__).parent/'RECOVERY_PLAN.json').read_text())
  if item!=plan['item'] or not item.get('recovery') or item['name']!='qwen129_f56cc17a3b916632c1c0fb6e':raise ValueError('Unbound old item')
 p=Path(item['folder'])
 if p.is_absolute() or '..' in p.parts:raise ValueError('Unsafe item path')

def fetch(gpu,item):
 safe_item(item)
 code=r'''
import json,base64,zlib,hashlib,sqlite3,re
from pathlib import Path
H=Path(ROOT);S=H/('runtime/gpu_'+str(GPU));C=S/(NAME+'_COMPLETE.json');F=H/'payload'/FOLDER/'batch';T=F/'worker/qwen/LOCAL_STATUS_V35.json'
if not C.exists():
 print(json.dumps({'status':'failed' if (S/(NAME+'_FAILURE.json')).exists() else 'wait'}));raise SystemExit(0)
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
v=json.loads(C.read_text());assert sha(T)==v['terminal_sha256'];files={}
for p in (F/'worker/qwen').iterdir():
 if p.name=='LOCAL_STATUS_V35.json' or re.fullmatch('[a-f0-9]{64}\\.jsonl',p.name):files[p.name]=base64.b64encode(p.read_bytes()).decode()
# Filename regex is checked independently by the primary importer.
for p in (F/'worker/qwen').glob('*.jsonl'):
 assert re.fullmatch('[a-f0-9]{64}\.jsonl',p.name);files[p.name]=base64.b64encode(p.read_bytes()).decode()
db=sqlite3.connect('file:'+str(S/(NAME+'.sqlite'))+'?mode=ro',uri=True)
assert not db.execute("select 1 from requests where state='inflight' or result_json is null").fetchone()
rows=[json.loads(r[0]) for r in db.execute('select result_json from requests')];db.close()
obj={'status':'complete','gpu':GPU,'name':NAME,'folder':FOLDER,'complete':v,'batch_manifest_sha256':sha(F/'MANIFEST.json'),'files':files,'ledger_results':rows,'ledger_sha256':sha(S/(NAME+'.sqlite'))}
raw=json.dumps(obj,separators=(',',':')).encode();assert len(raw)<32*1024**2
print(json.dumps({'zlib_b64':base64.b64encode(zlib.compress(raw)).decode()}))
'''.replace('ROOT',repr(str(REMOTE))).replace('GPU',str(gpu)).replace('NAME',repr(item['name'])).replace('FOLDER',repr(item['folder']))
 # No launch/score action in a transport request. A lost reply only delays import.
 cmd='/srv/curation/venv/bin/python -B -c '+shlex.quote(code)
 from flow import hard
 v=json.loads(hard([*SSH,cmd],timeout=60,env={**os.environ,'SSH_AUTH_SOCK':''}))
 if 'zlib_b64' in v:return json.loads(zlib.decompress(base64.b64decode(v['zlib_b64'])))
 return v

def receipt_values(raw):
 # JSONL uses literal LF bytes, not Unicode display separators inside JSON strings.
 # Preserve original bytes and every original cardinality/protocol/ledger gate.
 return [json.loads(line) for line in raw.decode('utf-8').split('\n') if line]

def verify_import(P,gpu,item,v,Batch,protocol,job_identity,recoverable):
 safe_item(item);f=P/item['folder'];b=Batch(f/'batch')
 try:
  if (v['gpu'],v['name'],v['folder'],v['batch_manifest_sha256'])!=(gpu,item['name'],item['folder'],b.manifest_hash):raise ValueError('Remote exact batch binding changed')
  terminal_ok(v['complete']['terminal'])
  files=v['files'];t=base64.b64decode(files['LOCAL_STATUS_V35.json']);terminal_ok(json.loads(t))
  if __import__('hashlib').sha256(t).hexdigest()!=v['complete']['terminal_sha256']:raise ValueError('Remote terminal differs')
  expected={job_identity(protocol(d,b.prompt,b.schema,b.registry['judges']['qwen'])):protocol(d,b.prompt,b.schema,b.registry['judges']['qwen']) for d in b.docs.values()}
  results={job_identity({k:r[k] for k in ('source_id','text_sha256','prompt_sha256','schema_sha256','model','temperature','inference_sha256','judge_identity_sha256','wire_schema_sha256')}):r for r in v['ledger_results']}
  if len(results)!=len(v['ledger_results']) or not set(results)<=set(expected):raise ValueError('Unknown/repeated ledger response')
  for k,r in results.items():
   if any(r.get(n)!=x for n,x in expected[k].items()):raise ValueError('Actual response protocol differs')
   if r.get('status')!='ok' and not recoverable(r,expected[k],b.registry['judges']['qwen']['served_models']):raise ValueError('Actual unknown request preserved; no release')
  rows={}
  for name,data in files.items():
   if name=='LOCAL_STATUS_V35.json':continue
   if not re.fullmatch('[a-f0-9]{64}\.jsonl',name):raise ValueError('Unknown transport filename')
   raw=base64.b64decode(data);values=receipt_values(raw)
   if len(values)!=1 or name[:-6] not in results or values[0]!=results[name[:-6]]:raise ValueError('Receipt/ledger mismatch')
   rows[name]=raw
  if {n[:-6] for n in rows}!=set(results):raise ValueError('Incomplete physical model receipts')
  out=f/'batch/worker/qwen';out.mkdir(parents=True,exist_ok=False)
  for name,raw in {**rows,'LOCAL_STATUS_V35.json':t}.items():
   with (out/name).open('xb') as w:w.write(raw);w.flush();os.fsync(w.fileno())
  for name in sorted(rows):b.import_results('qwen',out/name)
  return b.report()
 finally:b.close()

def verify_ready(output,database,load_manifest):
 r=output/'READY_INTERNAL.json';v=json.loads(r.read_text());h=sha(r)
 if v['status']!='READY_INTERNAL' or v['teacher']!='qwen' or v['distribution_eligible'] is not False:raise ValueError('Wrong READY scope')
 db=sqlite3.connect('file:'+str(database)+'?mode=ro',uri=True)
 try:
  row=db.execute('select receipt_sha,train_tokens from releases where batch_id=?',(v['batch_id'],)).fetchone()
  if row!=(h,v['unique_train_body_tokens']):raise ValueError('Receipt/SQL mismatch')
  actual=db.execute("select coalesce(sum(tokens),0) from documents where batch_id=? and split='train'",(v['batch_id'],)).fetchone()[0]
  if actual!=v['unique_train_body_tokens']:raise ValueError('Actual train-only body count differs')
 finally:db.close()
 if {c['name'] for c in v['checks']}!={'source_policy','quality_scope','global_exact_near_dedup','split_eval_isolation','tokenizer_pack_loader'}:raise ValueError('Original complete gate set required')
 for check in v['checks']:
  if check['status']!='passed':raise ValueError('Quality check incomplete')
  for e in check['evidence_files']:
   if sha(e['path'])!=e['sha256']:raise ValueError('Physical check bytes changed')
 for k in ('document_index','pack_manifest'):
  if sha(v[k]['path'])!=v[k]['sha256']:raise ValueError('READY physical pointer changed')
 m,shards=load_manifest(output/'tokenized',verify_hashes=True)
 if m['sequence_length']!=4096:raise ValueError('Original pack context changed')
 return dict(batch_id=v['batch_id'],receipt_sha256=h,train_body_tokens=v['unique_train_body_tokens'],pack_manifest_sha256=sha(output/'tokenized/manifest.json'),verified_bin_idx_files=2*len(shards))
