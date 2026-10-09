"""Once-only mutations; network uncertainty quarantines scope, never replays it."""
import json,time,subprocess
from pathlib import Path
from common import sha,frozen
from flow import block,blocked
NETWORK_ERRORS=(ConnectionError,TimeoutError,subprocess.TimeoutExpired,json.JSONDecodeError)

def dispatch_once(H,R,t,transfer,stock_terminal):
 H=Path(H);E=H/'events';name=t['name'];hold=E/(name+'_TRANSPORT_HOLD.json')
 if hold.exists():return False # only observe durable terminal; no action repeated
 if (E/(name+'_TRANSFER_INTENT.json')).exists():raise ValueError('Existing transport intent; observation only')
 F=(H/'payload'/t['folder']).parent
 proof=sha(F/'INPUT_FILES.json')
 state='HOLD_TRANSPORT_NOT_SENT'
 if not blocked(H,t['scope']):
  try:
   transfer(H,R,t);return True
  except NETWORK_ERRORS as error:
   state='HOLD_TRANSPORT_UNKNOWN';reason=repr(error)
 else:reason='Previously blocked scope; no transport or teacher attempt'
 frozen(hold,dict(unix=time.time(),name=name,scope=t['scope'],state=state,reason=reason,input_manifest_sha256=proof,preserved_files_sha256={str(p):sha(p) for p in F.rglob('*') if p.is_file()},no_retry=True,not_READY=True,possible_remote_attempt_unknown=state=='HOLD_TRANSPORT_UNKNOWN'))
 if t['kind']=='batch':stock_terminal(json.loads(Path(t['config']).read_text()),t,state)
 block(H,t['scope'],'Transport uncertainty retained; no resend; independent sources may continue')
 return False

def feedback_once(H,cfg,t,state,send):
 H=Path(H);E=H/'events';p=E/(t['name']+'_FEEDBACK_UNCERTAIN.json')
 if p.exists():return False
 if (E/(t['name']+'_FEEDBACK_INTENT.json')).exists():raise ValueError('Existing feedback intent; observation only')
 try:send(H,cfg,t,state);return True
 except NETWORK_ERRORS as error:
  frozen(p,dict(unix=time.time(),name=t['name'],scope=t['scope'],state=state,error=repr(error),no_retry=True,local_publication_state_unchanged=True))
  block(H,t['scope'],'Feedback acknowledgement unknown; retain publication, no resend')
  return False

def notify_done_once(H,send):
 H=Path(H);p=H/'GPU_DONE_NOTIFY_INTENT.json'
 if p.exists():raise ValueError('Existing producer notification intent; observation only')
 frozen(p,dict(unix=time.time(),producer_done_sha256=sha(H/'PRODUCER_DONE.json'),no_retry=True))
 try:return send()
 except NETWORK_ERRORS as error:
  frozen(H/'GPU_DONE_NOTIFY_UNCERTAIN.json',dict(unix=time.time(),error=repr(error),no_retry=True,local_results_preserved=True));return None
