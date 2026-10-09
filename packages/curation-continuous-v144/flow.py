"""Durable bounded continuous flow; per-scope READY barriers, immutable events."""
import json,time,os,signal,subprocess
from pathlib import Path
from common import sha,frozen,atomic
VERSION=144

def hard(args,timeout=60,**kw):
 p=subprocess.Popen(args,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,start_new_session=True,**kw)
 try:a,b=p.communicate(timeout=timeout)
 except subprocess.TimeoutExpired:
  os.killpg(p.pid,signal.SIGKILL);p.communicate();raise TimeoutError('Transport outcome unknown; observe only, no action resend')
 if p.returncode:raise ConnectionError(b[-2000:]+a[-1000:])
 return a

def event_terminal(H,name):
 E=Path(H)/'events'
 return any((E/(name+s)).exists() for s in ('_PUBLICATION_TERMINAL.json','_SOURCE_TERMINAL.json','_REFERENCE_TERMINAL.json','_QA_HOLD.json','_PUBLISH_FAILURE.json','_TRANSPORT_HOLD.json'))

def backlog(H):
 return sum(not event_terminal(H,json.loads(p.read_text())['name']) for p in (Path(H)/'queue').glob('*.json'))

def can_prepare(H,limit):
 if type(limit) is not int or not 1<=limit<=4:raise ValueError('Bounded queue required')
 return not (Path(H)/'STOP_NEW.json').exists() and backlog(H)<limit

def blocked(H,scope):return (Path(H)/'blocked'/str(scope)).exists()
def block(H,scope,reason):
 p=Path(H)/'blocked'/str(scope)
 if not p.exists():frozen(p,dict(unix=time.time(),reason=reason,no_retry=True))

def first_ready(item,feedback):
 return feedback.get('name')==item['name'] and feedback.get('state') in ('READY_INTERNAL','SOURCE_CALIBRATED','REFERENCE_CALIBRATED')

def safe_scope(x):
 import re
 if not re.fullmatch('[a-f0-9]{24}',x):raise ValueError('Unsafe source scope')
 return x

def valid_flow_config(c):
 if c['version']!=144 or c['compute_workers']!=4 or c['qa_workers']!=8 or c['maximum_backlog']!=4:raise ValueError('Unverified execution shape')
 if c['no_paid'] is not True or c['no_training'] is not True or c['quality_thresholds_changed'] is not False:raise ValueError('Authorization/gates differ')
 if c['stop_on_first_ready'] is not False or c['maximum_batches'] is not None:raise ValueError('Continuous supply is not a two-batch experiment')
 return True

def verify_bound(H,c):
 valid_flow_config(c)
 if sha(Path(H)/'EXCLUSION_COMMITMENT.json')!=c['exclusion_commitment_sha256']:raise ValueError('Frozen full exclusion commitment changed')
 for n,h in c['code_sha256'].items():
  if sha(Path(H)/n)!=h:raise ValueError('Frozen runtime changed '+n)
 for n,h in c.get('runtime_dependencies_sha256',{}).items():
  if sha(Path(c['runtime_dependencies'])/n)!=h:raise ValueError('Frozen parser dependency changed '+n)
 for n,h in c.get('engine_sha256',{}).items():
  if sha(n)!=h:raise ValueError('Frozen original engine changed '+n)

# Socket-free unit tests use this scheduler logic, production uses identical decisions.
def choose_mode(turn,gate):
 return 'individual' if not gate['approved_strata'] or turn%4==3 else 'source_audit'
