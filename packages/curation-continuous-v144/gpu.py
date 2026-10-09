"""Three persistent local backends, transparent nonretry aliases, exact scope feedback barriers."""
import json,sys,os,time,subprocess,threading,http.client,socket,re
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from urllib.request import urlopen
from common import sha,frozen,atomic,show,model_binding,validate_binding,identity,idle_card,pressure,fresh,terminal_ok
from flow import hard,verify_bound,first_ready
from portable import verify_portable,reserve_fresh

def original_protocol_runtime(H):
 # Exact production import shape, independent of unittest PYTHONPATH/cwd.
 C=Path(H)/'payload/code'
 sys.path[:0]=[str(C/'src'),str(C/'scripts')]
 from small_agent.curation.store_qwen_v35 import Batch,protocol
 from p0_qwen_worker_v35 import job_identity
 from grounding import protocol_plan
 return Batch,protocol,job_identity,protocol_plan

def snapshot():
 gs={}
 for line in subprocess.check_output(['nvidia-smi','--query-gpu=index,uuid,memory.used,utilization.gpu','--format=csv,noheader,nounits'],text=True,timeout=10).splitlines():
  i,u,m,v=map(str.strip,line.split(','));gs[int(i)]=dict(uuid=u,memory=int(m),util=int(v))
 apps=[dict(uuid=l.split(',')[0].strip(),pid=l.split(',')[1].strip()) for l in subprocess.check_output(['nvidia-smi','--query-compute-apps=gpu_uuid,pid','--format=csv,noheader,nounits'],text=True,timeout=10).splitlines()]
 return gs,apps

def verify_files(H,mapping):
 for n,h in mapping.items():
  p=Path(n)
  if p.is_absolute() or '..' in p.parts or sha(H/'payload'/p)!=h:raise ValueError('Input SHA/path differs: '+n)

def proxy_handler(port):
 class Proxy(BaseHTTPRequestHandler):
  protocol_version='HTTP/1.1'
  def forward(self):
   n=int(self.headers.get('Content-Length','0'))
   if n<0 or n>16*1024**2: self.send_error(413);return
   if self.path not in ('/health','/v1/models','/metrics','/v1/chat/completions'):self.send_error(404);return
   raw=self.rfile.read(n);con=http.client.HTTPConnection('127.0.0.1',port,timeout=300)
   try:
    # Exactly one backend request; no retry, truncation, protocol rewrite or cache purge.
    con.request(self.command,self.path,body=raw if n else None,headers={'Content-Type':self.headers.get('Content-Type','application/json'),'Connection':'close'})
    r=con.getresponse();data=r.read();self.send_response(r.status);self.send_header('Content-Type',r.getheader('Content-Type','application/json'));self.send_header('Content-Length',str(len(data)));self.send_header('Connection','close');self.end_headers();self.wfile.write(data)
   except (ConnectionError,OSError,TimeoutError):
    # Lost replies remain unknown at the strict original worker, never resubmitted.
    try:self.send_error(502)
    except OSError:pass
   finally:con.close();self.close_connection=True
  do_GET=forward;do_POST=forward
  def log_message(self,*a):pass
 return Proxy

def owned_idle(H,cfg,route,binding):
 if not validate_binding(show(route['unit']),binding):raise ValueError('Bound backend gone; no restart')
 gs,apps=snapshot();i=route['physical']
 for a in apps:
  if a['uuid']==gs[i]['uuid']:
   try:u,c,_=identity(a['pid'])
   except FileNotFoundError:continue
   if (u,c)!=(os.getuid(),binding['ControlGroup']):raise ValueError('Foreign GPU process; no new request')

def consume(H,cfg,lane,binding):
 route=cfg['backends'][str(lane)];done=set();last={};blocked_scopes=set()
 while True:
  owned_idle(H,cfg,route,binding)
  items=[]
  for p in sorted((H/'inbox').glob('*.json')):
   t=json.loads(p.read_text());s=t['scope']
   if cfg['logical_lane'][str(t['gpu'])]!=lane or t['name'] in done:continue
   if s in blocked_scopes:
    S=H/f'runtime/gpu_{t["gpu"]}';S.mkdir(parents=True,exist_ok=True);frozen(S/(t['name']+'_FAILURE.json'),dict(unix=time.time(),reason='Same scope blocked, no attempt made',no_retry=True));done.add(t['name']);continue
   if s in last:
    fp=H/'feedback'/(last[s]+'.json')
    if not fp.exists():continue
    f=json.loads(fp.read_text())
    if not first_ready({'name':last[s]},f):blocked_scopes.add(s);continue
   items.append(t)
  if not items:
   if (H/'PRODUCER_DONE.json').exists() and all(t['name'] in done for p in (H/'inbox').glob('*.json') for t in [json.loads(p.read_text())] if cfg['logical_lane'][str(t['gpu'])]==lane):break
   if (H/'STOP_NEW.json').exists():break
   atomic(H/f'LANE_{lane}_STATUS.json',dict(unix=time.time(),stage='WAIT_NEXT_PREHEATED_SCOPE_OR_VERIFIED_READY',completed=len(done),blocked_scopes=sorted(blocked_scopes),model_stays_loaded=True));time.sleep(2);continue
  t=items[0];name=t['name'];S=H/f'runtime/gpu_{t["gpu"]}';S.mkdir(parents=True,exist_ok=True);F=H/'payload'/Path(t['folder']).parent
  try:
   verify_files(H,json.loads((F/'INPUT_FILES.json').read_text()));proof=json.loads((F/'EXCLUSION_PROOF.json').read_text());verify_portable(H,proof)
   Batch,protocol,job_identity,protocol_plan=original_protocol_runtime(H)
   b=Batch(F/'review/batch')
   try:actual_ids,actual_keys=protocol_plan(b,protocol,job_identity)
   finally:b.close()
   if actual_ids!=proof['new_body_ids'] or actual_keys!=proof['new_request_keys']:raise ValueError('Portable proof is not actual full Batch protocol')
   reserve_fresh(H,name,actual_ids,actual_keys)
   if (S/(name+'_START_INTENT.json')).exists() or (S/(name+'.sqlite')).exists() or (F/'review/batch/worker').exists():raise ValueError('Existing attempt, observation only')
   with urlopen(f'http://127.0.0.1:{route["port"]}/metrics',timeout=8) as x:(S/(name+'_METRICS_BEFORE.txt')).write_bytes(x.read())
   frozen(S/(name+'_START_INTENT.json'),dict(unix=time.time(),task=t,workers=8,lane=lane,worker_sha256=sha(H/'worker.py'),original_protocol_unchanged=True))
   with (S/(name+'.log')).open('x') as f:
    # Do not impose a wall-clock killer on pressure-deferred or active scopes.
    z=subprocess.run([sys.executable,'-B','-u',str(H/'worker.py'),'--batch',str(F/'review/batch'),'--ledger',str(S/(name+'.sqlite')),'--workers','8','--limit','512','--allow-local'],stdout=f,stderr=subprocess.STDOUT,env={**os.environ,'CUDA_VISIBLE_DEVICES':'','OMP_NUM_THREADS':'1','TOKENIZERS_PARALLELISM':'false'})
   if z.returncode:raise ValueError('Worker failed/unknown; preserve scope, no replay')
   terminal=F/'review/batch/worker/qwen/LOCAL_STATUS_V35.json';v=json.loads(terminal.read_text());terminal_ok(v)
   if v['selected']!=t['selected']:raise ValueError('Partial original source/rolling/individual scope')
   frozen(S/(name+'_COMPLETE.json'),dict(name=name,kind=t['kind'],folder=t['folder'],terminal=v,terminal_sha256=sha(terminal),actual_batch_report=v['batch'],workers=8))
   last[t['scope']]=name;done.add(name)
   atomic(H/f'LANE_{lane}_STATUS.json',dict(unix=time.time(),stage='FULL_QA_COMPLETE_WAIT_ORIGINAL_CPU_GATES',task=t,completed=len(done),not_READY=True))
  except BaseException as e:
   frozen(S/(name+'_FAILURE.json'),dict(unix=time.time(),error=repr(e),no_retry=True));blocked_scopes.add(t['scope']);done.add(name)
 frozen(H/f'LANE_{lane}_FINAL.json',dict(unix=time.time(),completed=sorted(done),blocked_scopes=sorted(blocked_scopes),not_all_stock_washed=True))

def main():
 H=Path(sys.argv[1]);cfg=json.loads((H/'GPU_CONFIG.json').read_text());verify_bound(H,cfg);verify_files(H,cfg['payload_code_sha256']);original_protocol_runtime(H);frozen(H/'GPU_RUN_INTENT.json',dict(unix=time.time(),pid=os.getpid(),continuous=True))
 while not list((H/'inbox').glob('*.json')):
  if (H/'PRODUCER_DONE.json').exists() or (H/'STOP_NEW.json').exists():return
  atomic(H/'GPU_STATUS.json',dict(unix=time.time(),stage='WAIT_FIRST_DURABLE_CPU_INPUT'));time.sleep(3)
 # No model launch, stop, restart or cache mutation. Reuse exact prior idle identity.
 from reuse import verify_reuse
 bindings=verify_reuse(H,cfg)
 frozen(H/'INHERITED_ALIASES_VERIFIED.json',dict(unix=time.time(),prior_alias_owner=cfg['prior_alias_owner'],no_backend_restart=True))
 servers=[]
 threads=[];errors=[]
 def work(lane,b):
  try:consume(H,cfg,lane,b)
  except BaseException as e:errors.append(repr(e));frozen(H/f'LANE_{lane}_FAILURE.json',dict(unix=time.time(),error=repr(e),no_retry=True))
 for lane,b in bindings.items():
  th=threading.Thread(target=work,args=(lane,b));th.start();threads.append(th)
 for th in threads:th.join()
 for server in servers:server.shutdown();server.server_close()
 # No automatic backend stop or restart; active/unknown work cannot be accidentally killed.
 frozen(H/'GPU_FINAL.json',dict(unix=time.time(),errors=errors,not_all_stock_washed=True))
if __name__=='__main__':main()
