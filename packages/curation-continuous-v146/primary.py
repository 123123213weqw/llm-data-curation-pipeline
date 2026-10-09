"""Streaming CPU→durable transport→GPU→import queue→single original publisher."""
import json,os,sys,time,subprocess,shlex,queue,threading,sqlite3,hashlib
from pathlib import Path
from common import sha,frozen,atomic,cpu_pressure
from flow import hard,verify_bound,block
import receipt_adapter as adapter
from transport import dispatch_once,feedback_once,notify_done_once
from drain import producer_notifiable,fully_drained
from portable import verify_cpu_input
SSH=adapter.SSH
TRANSPORT='ssh -C -p 2222 -o BatchMode=yes -o ControlPath=none -o ConnectTimeout=8 -o ForwardAgent=no -o StrictHostKeyChecking=yes'

def remote(code,timeout=120):
 return json.loads(hard([*SSH,'/srv/curation/venv/bin/python -B -c '+shlex.quote(code)],timeout=timeout,env={**os.environ,'SSH_AUTH_SOCK':''}))

def transfer(H,remote_root,t):
 F=(H/'payload'/t['folder']).parent;name=t['name'];event=H/'events';verify_cpu_input(H,F);proof=sha(F/'INPUT_FILES.json')
 frozen(event/(name+'_TRANSFER_INTENT.json'),dict(unix=time.time(),input_manifest_sha256=proof,never_teacher_retry=True))
 # Each full review body is shipped once; massive candidate corpus stays on the CPU host.
 target=remote_root/'payload'/F.relative_to(H/'payload')
 remote('from pathlib import Path; import json; p=Path('+repr(str(target))+');p.mkdir(parents=True,exist_ok=False);print(json.dumps({"created":True}))')
 out=hard(['rsync','-az','--ignore-existing','--exclude=candidates.parquet','--exclude=ALLOCATION_INTENT.json','--exclude=INPUT_FILES_CPU.json','-e',TRANSPORT,str(F)+'/', 'GPU_WORKER:'+str(target)+'/'],timeout=600,env={**os.environ,'SSH_AUTH_SOCK':''})
 code='''import json,sys
from pathlib import Path
H=Path(ROOT);sys.path.insert(0,str(H));from gpu import verify_files
from common import frozen,sha
F=Path(TARGET);assert sha(F/'INPUT_FILES.json')==PROOF
verify_files(H,json.loads((F/'INPUT_FILES.json').read_text()))
t=TASK;frozen(H/'inbox'/QUEUE_NAME,t);print(json.dumps({'admitted':t['name'],'manifest_sha256':PROOF}))
'''.replace('ROOT',repr(str(remote_root))).replace('TARGET',repr(str(target))).replace('PROOF',repr(proof)).replace('TASK',repr(t)).replace('QUEUE_NAME',repr(f"{t['ordinal']:04d}_{t['gpu']}_{name}.json"))
 ack=remote(code);frozen(event/(name+'_TRANSFERRED.json'),dict(unix=time.time(),ack=ack))

def feedback(H,cfg,t,state):
 if t.get('recovery'):
  frozen(H/'events'/(t['name']+'_RECOVERY_FEEDBACK.json'),dict(state=state,no_gpu_dispatch=True));return
 E=H/'events';v=dict(unix=time.time(),name=t['name'],scope=t['scope'],state=state)
 frozen(E/(t['name']+'_FEEDBACK_INTENT.json'),v)
 remote('from pathlib import Path; import json; import sys; H=Path('+repr(cfg['remote_root'])+');sys.path.insert(0,str(H));from common import frozen;frozen(H/"feedback"/'+repr(t['name']+'.json')+','+repr(v)+');print(json.dumps({"acknowledged":True}))')
 frozen(E/(t['name']+'_FEEDBACK_OBSERVED.json'),v)

def stock_terminal(q,t,state):
 from p0_qwen_overnight_slot_v67 import locked
 root=Path(q['root'])
 with locked(root/'queue.lock'):
  db=sqlite3.connect(root/'stock.sqlite',timeout=30)
  try:
   with db:
    expected='CPU_PREHEATED_V135_NOT_READY' if t.get('recovery') else 'CPU_PREHEATED_V146_NOT_READY'
    if db.execute('select state from jobs where name=?',(t['name'],)).fetchone()!=(expected,):raise ValueError('Assigned stock changed')
    db.execute('update jobs set state=? where name=?',(state,t['name']));db.execute('update records set gate=? where job=?',(state,t['name']))
  finally:db.close()

def publish_one(H,cfg,t):
 C=Path(cfg['code']);sys.path[:0]=[cfg['runtime_dependencies'],str(C/'src'),str(C/'scripts')];os.environ['PYTHONPATH']=cfg['runtime_dependencies']
 from p0_qwen_overnight_slot_v67 import publish
 from small_agent.curation.quality_qwen_v35 import publication_quality
 from small_agent.data.sharded_format import load_sharded_manifest
 F=Path(t['candidate']).parent;q=json.loads(Path(t['config']).read_text());src=Path(t['source']);ref=Path(t['reference']);E=H/'events';name=t['name'];state='HOLD_QUALITY'
 try:
  quality=publication_quality(q,F/'candidates.parquet',src,ref,F/'review',t['mode']);frozen(F/'PUBLICATION_PRECHECK_V146.json',quality)
  if quality['status']=='passed':
   while cpu_pressure()['reasons']:
    atomic(H/'ADMISSION.json',dict(unix=time.time(),stage='WAIT_CPU_PRESSURE_BEFORE_PUBLICATION',job=name,pressure=cpu_pressure()));time.sleep(10)
   frozen(E/(name+'_PUBLISH_INTENT.json'),dict(unix=time.time(),candidate_sha256=sha(F/'candidates.parquet'),quality_sha256=sha(F/'PUBLICATION_PRECHECK_V146.json'),original_gates_unchanged=True))
   publish(q,Path(t['config']),F,src,ref,t['cohort'].split('/')[1],t['mode'],Path(cfg['performance']),H)
   state='HOLD_PHYSICAL'
   if (F/'release/READY_INTERNAL.json').exists():
    verified=adapter.verify_ready(F/'release',Path(q['database']),load_sharded_manifest);frozen(E/(name+'_VERIFIED_READY.json'),dict(verified,job=name,verified_unix=time.time()));state='READY_INTERNAL'
  stock_terminal(q,t,state)
  frozen(E/(name+'_PUBLICATION_TERMINAL.json'),dict(unix=time.time(),state=state))
  if state!='READY_INTERNAL':block(H,t['scope'],state+'; no retry or automatic HOLD clearing')
  feedback_once(H,cfg,t,state,feedback)
 except BaseException as e:
  frozen(E/(name+'_PUBLISH_FAILURE.json'),dict(unix=time.time(),error=repr(e),no_retry=True));raise

def main():
 H=Path(sys.argv[1]);cfg=json.loads((H/'CONFIG.json').read_text());verify_bound(H,cfg);P=H/'payload';E=H/'events';R=Path(cfg['remote_root']);adapter.REMOTE=R
 C=Path(cfg['code']);from runtime_cpu import bootstrap;bootstrap(cfg)
 from small_agent.curation.store_qwen_v35 import Batch,protocol
 from p0_qwen_worker_v35 import job_identity
 from p0_curation_bounded_resume_v3 import recoverable
 from small_agent.curation.quality_qwen_v35 import source_gate,reference_gate,verify_teacher_scope
 frozen(H/'PIPELINE_RUN_INTENT.json',dict(unix=time.time(),pid=os.getpid(),new_stock_only=True,continuous=True,automatic_retry=False))
 sent={};imported=set();pub=queue.Queue(maxsize=2);stop=threading.Event();errors=[]
 def writer():
  while not stop.is_set() or not pub.empty():
   try:t=pub.get(timeout=.5)
   except queue.Empty:continue
   try:publish_one(H,cfg,t)
   except BaseException as e:
    errors.append(repr(e));stop.set()
    if not (H/'STOP_NEW.json').exists():frozen(H/'STOP_NEW.json',dict(unix=time.time(),reason=repr(e),do_not_interrupt_started_publication=True))
   finally:pub.task_done()
   if errors:break
 th=threading.Thread(target=writer);th.start();done_sent=False
 try:
  while not stop.is_set():
   for p in sorted((H/'queue').glob('*.json')):
    t=json.loads(p.read_text());name=t['name']
    if name not in sent:
     if t.get('recovery'):
      plan=json.loads((H/'RECOVERY_PLAN.json').read_text());assert t==plan['item'];sent[name]=t;continue
     if (E/(name+'_TRANSFER_INTENT.json')).exists():raise ValueError('Existing transport intent; observation only')
     admitted=dispatch_once(H,R,t,transfer,stock_terminal);sent[name]=t
     if not admitted:imported.add(name)
   for name,t in list(sent.items()):
    if name in imported or pub.full():continue
    try:
     adapter.REMOTE=Path(cfg['prior_remote_root']) if t.get('recovery') else R
     v=adapter.fetch(t['gpu'],t)
    except (ConnectionError,TimeoutError,subprocess.TimeoutExpired,json.JSONDecodeError) as e:
     atomic(H/'TRANSPORT_WAIT.json',dict(unix=time.time(),job=name,error=repr(e),readonly_receipt_retry_only=True));continue
    if v['status']=='wait':continue
    if v['status']!='complete':
     frozen(E/(name+'_QA_HOLD.json'),dict(unix=time.time(),preserved=True,reason=v));block(H,t['scope'],'Unknown local response retained; no replay');imported.add(name)
     if t['kind']=='batch':stock_terminal(json.loads(Path(t['config']).read_text()),t,'HOLD_UNKNOWN')
     feedback_once(H,cfg,t,'HOLD_UNKNOWN',feedback);continue
    frozen(E/(name+'_IMPORT_INTENT.json'),dict(unix=time.time(),ledger_sha256=v['ledger_sha256'],bundle_sha256=hashlib.sha256(json.dumps(v,sort_keys=True).encode()).hexdigest()))
    report=adapter.verify_import(P,t['gpu'],t,v,Batch,protocol,job_identity,recoverable)
    if v['complete']['terminal']['selected']!=t['selected']:raise ValueError('Partial source/rolling/individual sample')
    frozen(E/(name+'_IMPORTED.json'),dict(unix=time.time(),report=report,ledger_sha256=v['ledger_sha256']));imported.add(name)
    if t['kind']=='reference':
     from reference import finish_reference
     q=json.loads(Path(t['config']).read_text());gate=finish_reference(q,Path(t['reference']),reference_gate,verify_teacher_scope)
     state='REFERENCE_CALIBRATED' if gate['status']=='passed' else 'HOLD_REFERENCE'
     frozen(E/(name+'_REFERENCE_TERMINAL.json'),dict(unix=time.time(),gate=gate,state=state,not_READY=True,no_training_credit=True))
     if state!='REFERENCE_CALIBRATED':block(H,t['scope'],'Independent reference quality HOLD; no retry')
     feedback_once(H,cfg,t,state,feedback)
    elif t['kind']=='source':
     q=json.loads(Path(t['config']).read_text());src=Path(t['source']);verify_teacher_scope(q,[src,Path(t['reference'])]);policy=json.loads(Path(q['release_policy']).read_text())['quality'];sg=source_gate(src,policy)
     frozen(src/'ACTUAL_GATE_V36.json',sg);frozen(E/(name+'_SOURCE_TERMINAL.json'),dict(unix=time.time(),gate=sg,source_specific=True,not_READY=True));feedback_once(H,cfg,t,'SOURCE_CALIBRATED',feedback)
    else:pub.put(t)
   if not done_sent and producer_notifiable(H,sent):
    ack=notify_done_once(H,lambda:remote('from pathlib import Path;import json;import sys;H=Path('+repr(str(R))+');sys.path.insert(0,str(H));from common import frozen;frozen(H/"PRODUCER_DONE.json",'+repr(json.loads((H/'PRODUCER_DONE.json').read_text()))+');print(json.dumps({"done":True}))'));done_sent=True
   if (H/'PREPARE_FAILURE.json').exists():raise ValueError('Producer failed; preserve all scopes')
   ready=[json.loads(p.read_text()) for p in E.glob('*_VERIFIED_READY.json')];bids={r['batch_id']:r['train_body_tokens'] for r in ready}
   atomic(H/'PIPELINE_STATUS.json',dict(unix=time.time(),stage='CONTINUOUS_STREAMING_SINGLE_PUBLICATION_WRITER',transferred=sum((E/(n+'_TRANSFERRED.json')).exists() or t.get('recovery',False) for n,t in sent.items()),transport_holds=sum((E/(n+'_TRANSPORT_HOLD.json')).exists() for n in sent),imported=sum((E/(n+'_IMPORTED.json')).exists() for n in sent),observed_terminal=len(imported),publication_queue=pub.qsize(),publishing=pub.unfinished_tasks,producer_done=done_sent,errors=errors,READY_batches=len(bids),READY_train_body_tokens=sum(bids.values()),continuous=True,maximum_batches=None,not_all_stock_washed=True))
   if done_sent and fully_drained(H,sent,imported,pub.unfinished_tasks):break
   time.sleep(3)
 except BaseException as e:
  frozen(H/'PIPELINE_FAILURE.json',dict(unix=time.time(),error=repr(e),no_retry=True))
  if not (H/'STOP_NEW.json').exists():frozen(H/'STOP_NEW.json',dict(unix=time.time(),reason=repr(e),do_not_interrupt_started_publication=True))
  raise
 finally:
  stop.set();th.join() # Started original publication must not be interrupted.
 frozen(H/'PIPELINE_FINAL.json',dict(unix=time.time(),errors=errors,transferred=list(sent),imported=sorted(imported),not_all_stock_washed=True))
if __name__=='__main__':main()
