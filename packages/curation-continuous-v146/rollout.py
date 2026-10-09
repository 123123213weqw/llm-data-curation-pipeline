"""One-shot guarded rollout: seal OLD producer, drain, derive fresh, test, launch once.
Never signals a publisher, GPU model or unknown teacher attempt. No retries of actions.
"""
import base64,json,os,shlex,shutil,sqlite3,subprocess,sys,time,zlib,signal
from pathlib import Path
from common import sha,frozen,atomic,show
from flow import hard,event_terminal,verify_bound
from drain import sealed_names
from receipt_adapter import SSH,verify_ready

def load(p):return json.loads(Path(p).read_text())
def exact_units(current,bound,allow_finished=False):
 for unit,b in bound.items():
  s=current[unit]
  if s['MainPID']=='0' and allow_finished and s['ActiveState'] in ('inactive','failed'):continue
  if any(s.get(k)!=b.get(k) for k in ('MainPID','InvocationID','ControlGroup')):raise ValueError('Prior controller identity changed: '+unit)
 return True

def cpu_drained(old,units):
 if not (old/'PRODUCER_DONE.json').exists() or not (old/'PIPELINE_FINAL.json').exists():return False
 if any(s['MainPID']!='0' for s in units.values()):return False
 names=sealed_names(old)
 if names is None or not all(event_terminal(old,n) for n in names):raise ValueError('Prior durable queue not terminal')
 if load(old/'PIPELINE_FINAL.json')['errors'] or (old/'PIPELINE_FAILURE.json').exists() or (old/'PREPARE_FAILURE.json').exists():raise ValueError('Prior genuine failure: preserve, no auto recovery')
 return True

def remote(code,timeout=80):
 # SSH stdin avoids ARG_MAX for full frozen evidence; no action retry on timeout.
 from remote_wire import script_transport
 cmd,packed,mode=script_transport(code)
 p=subprocess.Popen([*SSH,cmd],stdin=subprocess.PIPE if packed is not None else subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,start_new_session=True,env={**os.environ,'SSH_AUTH_SOCK':''})
 try:out,err=p.communicate(packed,timeout=timeout)
 except subprocess.TimeoutExpired:
  os.killpg(p.pid,signal.SIGKILL);p.communicate();raise TimeoutError('Unknown remote outcome: observe only, no action resend')
 if p.returncode:raise ConnectionError(err[-2500:]+out[-1000:])
 value=json.loads(out)
 from boundary import decode_boundary
 return decode_boundary(value) if value.get('encoding')=='zlib-base64-v146' else value

def main():
 H=Path(sys.argv[1]);rc=load(H/'ROLLOUT_CONFIG.json');old=Path(rc['old_root']);R=H.parent;C=R/'code';L=rc['new_remote_root'];oldL=rc['old_remote_root']
 for n,h in rc['code_sha256'].items():
  if sha(H/n)!=h:raise ValueError('Rollout code changed '+n)
 for n,h in rc['input_sha256'].items():
  if sha(H/n)!=h:raise ValueError('Rollout input/helper changed '+n)
 if sha(old/'CONFIG.json')!=rc['old_config_sha256']:raise ValueError('Prior config changed')
 frozen(H/'ROLLOUT_RUN_INTENT.json',dict(unix=time.time(),pid=os.getpid(),user_authorization='2026-10-09 user 好的 补一下: code/technical deficit scheduling',no_old_teacher_retry=True))
 try:
  units={u:show(u) for u in rc['old_units']};exact_units(units,rc['old_units'])
  # This derivation is permitted only after exact known pre-deploy failure of v139.
  prior=Path(rc['failed_rollout_root']);ps=show('curation-domain-rollout-v141.service')
  if ps['MainPID']!='0' or ps['LoadState']!='not-found' or (prior/'ROLLOUT_LAUNCH_INTENT.json').exists():raise ValueError('Prior 141 not exact unlaunched boundary')
  for path,h in rc['failed_rollout_files_sha256'].items():
   if sha(path)!=h:raise ValueError('Prior prelaunch boundary changed '+path)
  test=load(prior/'COMPRESSED_COMMAND_REAL_RELAY_TEST.json')
  if test['requests']!=18105 or not test['exact_binding']['exact_body_key_job_binding'] or not test['no_teacher_requests']:raise ValueError('Actual unchanged full-boundary relay proof required')
  for n in ['GPU_DEPLOY_INTENT.json','GPU_LAUNCH_INTENT.json','LAUNCH_INTENT.json','CONFIG.json','EXCLUSION_BASE.json']:
   if (prior/n).exists():raise ValueError('Possible prior side effect; observe only')
  if list((prior/'queue').glob('*.json')):raise ValueError('Prior queue exists')
  if not (old/'STOP_NEW.json').exists() or sha(old/'STOP_NEW.json')!=rc['old_seal_sha256']:raise ValueError('Prior producer seal changed')
  if not cpu_drained(old,units):raise ValueError('Prior producer not fully drained')
  frozen(H/'KNOWN_PREDEPLOY_RECOVERY_BOUNDARY.json',dict(unix=time.time(),prior_prelaunch_proof_sha256=sha(prior/'COMPRESSED_COMMAND_REAL_RELAY_TEST.json'),old_seal_sha256=sha(old/'STOP_NEW.json'),no_new_seal=True,no_prior_request_replay=True))
  end=time.monotonic()+12*3600
  while True:
   units={u:show(u) for u in rc['old_units']};exact_units(units,rc['old_units'],True)
   if cpu_drained(old,units):break
   if time.monotonic()>end:raise TimeoutError('Safe drain deadline; no unknown interruption or new launch')
   atomic(H/'ROLLOUT_STATUS.json',dict(unix=time.time(),stage='WAIT_OLD_DURABLE_QUEUE_AND_STARTED_PUBLICATION_DRAIN',old_units=units,no_new_teacher_requests=True));time.sleep(15)
  sys.path[:0]=[str(H/'runtime-deps'),str(C/'src'),str(C/'scripts')];os.environ['PYTHONPATH']=str(H/'runtime-deps')
  from small_agent.curation.store_qwen_v35 import Batch,protocol
  from small_agent.curation.quality_qwen_v35 import reference_gate,verify_teacher_scope
  from small_agent.data.sharded_format import load_sharded_manifest
  from p0_qwen_worker_v35 import job_identity
  from small_agent.curation.supply_control import digest
  from grounding import protocol_plan
  from portable import build_index,ProofIndex,make_portable,write_input_manifests
  ex=load(old/'EXCLUSION_BASE.json');ids=set(ex['body_ids']);keys=set(ex['request_keys']);prior_tasks=[]
  for p in sorted((old/'queue').glob('*.json')):
   t=load(p);F=Path(t['config']).parent;b=Batch(old/'payload'/t['folder']/'batch')
   try:i,k=protocol_plan(b,protocol,job_identity)
   finally:b.close()
   ids.update(i);keys.update(k);prior_tasks.append(t)
  for p in (old/'payload').glob('gpu_*/*/ALLOCATION_INTENT.json'):ids.update(load(p)['body_ids'])
  prior_ready=[verify_ready(Path(t['config']).parent/'release',Path(load(t['config'])['database']),load_sharded_manifest) for t in prior_tasks if (old/'events'/(t['name']+'_VERIFIED_READY.json')).exists()]
  frozen(H/'PRIOR_CPU_DRAIN_BOUNDARY.json',dict(unix=time.time(),units=units,config_sha256=sha(old/'CONFIG.json'),seal_sha256=sha(old/'PRODUCER_DONE.json'),final_sha256=sha(old/'PIPELINE_FINAL.json'),queue_sha256={p.name:sha(p) for p in (old/'queue').glob('*.json')},events_sha256={p.name:sha(p) for p in (old/'events').glob('*.json')},all_new137_READY_reverified=prior_ready,all_old_allocations_excluded=True))
  # A read-only exact GPU terminal audit. No signal, retry or old private-state writes.
  boundary_code=(H/'gpu_boundary.py.txt').read_text().replace('__OLD_ROOT__',repr(oldL))
  from boundary import cached_boundary
  gb=cached_boundary(rc);frozen(H/'PRIOR_GPU_DRAIN_BOUNDARY.json',gb)
  ids.update(gb['body_ids']);keys.update(gb['request_keys'])
  frozen(H/'EXCLUSION_BASE.json',dict(ex,body_ids=sorted(ids),request_keys=sorted(keys),parent_exclusion_sha256=sha(old/'EXCLUSION_BASE.json'),parent_CPU_boundary_sha256=sha(H/'PRIOR_CPU_DRAIN_BOUNDARY.json'),parent_GPU_boundary_sha256=sha(H/'PRIOR_GPU_DRAIN_BOUNDARY.json'),all_prior_HOLD_and_unknown_preserved=True))
  commit=build_index(H,ids,keys)
  for n in ['queue','events','blocked','scope_terminals','payload']:(H/n).mkdir(exist_ok=True)
  for p in (old/'blocked').iterdir():shutil.copy2(p,H/'blocked'/p.name)
  oc=load(old/'CONFIG.json');catalog=load(old/'SOURCE_CATALOG.json');newroutes=load(H/'NEW_ROUTES_PLAN.json');ref_policy=load(C/'configs/curation/p0_release_gates_v5.json')['quality']
  for r in newroutes:
   cohort=r['cohort'];d,l=cohort.split('/')[1:];g=r['logical'];q=R/f'full_inventory_v11/qwen_pool_v36/configs/gpu_{g}.json';ref=Path(r['reference'].replace('__NEW_ROOT__',str(H)));source=H/'source_audits'/digest([cohort])[:24]
   files={str(q):sha(q)}
   if not r['new_reference']:
    cfg=load(q);verify_teacher_scope(cfg,[ref]);gate=reference_gate(ref,load(ref/'labels.json'),ref_policy)
    if gate!=load(ref/'ACTUAL_GATE_V36.json') or gate['status']!='passed':raise ValueError('Actual language/domain reference does not pass')
    files.update({str(p):sha(p) for p in ref.rglob('*') if p.is_file() and not p.name.endswith(('-wal','-shm','.lock'))})
   catalog.append(dict(scope=digest([cohort])[:24],logical=g,cohort=cohort,config=str(q),source=str(source),reference=str(ref),source_calibration_required=True,immutable_files=files))
  if len({r['cohort'] for r in catalog})!=len(catalog):raise ValueError('Repeated admitted route')
  frozen(H/'SOURCE_CATALOG.json',catalog);shutil.copy2(old/'PERFORMANCE.json',H/'PERFORMANCE.json')
  deps={str(p.relative_to(H/'runtime-deps')):sha(p) for p in (H/'runtime-deps').rglob('*') if p.is_file()}
  recipe=C/'configs/curation/base_1b_supply_20b_v4.json'
  c=dict(oc,version=146,code_sha256=rc['code_sha256'],performance=str(H/'PERFORMANCE.json'),remote_root=L,prior_remote_root=oldL,database=str(R/'state/supply_20b_v4.sqlite'),supply_recipe=str(recipe),supply_recipe_sha256=sha(recipe),runtime_dependencies=str(H/'runtime-deps'),runtime_dependencies_sha256=deps,exclusion_commitment_sha256=sha(H/'EXCLUSION_COMMITMENT.json'))
  c['engine_sha256']=dict(c['engine_sha256'],**{str(H/'SOURCE_CATALOG.json'):sha(H/'SOURCE_CATALOG.json'),str(H/'PERFORMANCE.json'):sha(H/'PERFORMANCE.json')});frozen(H/'CONFIG.json',c);verify_bound(H,c)
  # Real complete 32-control protocol, full-history absence, CPU→GPU transfer. No teacher dispatch.
  fixture=H/'payload/transport_fixture';shutil.copytree(Path(rc['scratch'])/'reference_fixture/html',fixture/'review');b=Batch(fixture/'review/batch')
  try:fi,fk=protocol_plan(b,protocol,job_identity)
  finally:b.close()
  index=ProofIndex(H)
  try:frozen(fixture/'EXCLUSION_PROOF.json',make_portable(H,index,fi,fk))
  finally:index.close()
  write_input_manifests(H,fixture)
  bundle=base64.b64encode(zlib.compress(json.dumps({p.name:base64.b64encode(p.read_bytes()).decode() for p in H.glob('*.py')}).encode())).decode()
  deploy=(H/'gpu_deploy.py.txt').read_text().replace('__NEW_ROOT__',repr(L)).replace('__OLD_ROOT__',repr(oldL)).replace('__BUNDLE__',repr(bundle)).replace('__CPU_CFG__',repr(c)).replace('__COMMIT__',repr(commit)).replace('__BOUNDARY__',repr(gb))
  frozen(H/'GPU_DEPLOY_INTENT.json',dict(unix=time.time(),target=L,no_retry=True));ack=remote(deploy,900);frozen(H/'GPU_DEPLOY_OBSERVED.json',ack)
  frozen(H/'REAL_TRANSFER_INTENT.json',dict(unix=time.time(),fixture_manifest_sha256=sha(fixture/'INPUT_FILES.json'),no_dispatch=True))
  transport='ssh -p 2222 -o BatchMode=yes -o ControlPath=none -o ConnectTimeout=8 -o ForwardAgent=no -o StrictHostKeyChecking=yes'
  hard(['rsync','-az','-e',transport,str(fixture)+'/', 'GPU_WORKER:'+L+'/payload/transport_fixture/'],timeout=600,env={**os.environ,'SSH_AUTH_SOCK':''})
  verify=(H/'gpu_fixture_launch.py.txt').read_text().replace('__NEW_ROOT__',repr(L)).replace('__PROOF_SHA__',repr(sha(fixture/'INPUT_FILES.json')))
  # The single action below performs the final proof and launches only once, after all evidence is confirmed.
  frozen(H/'GPU_LAUNCH_INTENT.json',dict(unix=time.time(),target=L));gstart=remote(verify,120);frozen(H/'GPU_LAUNCH_OBSERVED.json',gstart)
  frozen(H/'LAUNCH_INTENT.json',dict(unix=time.time(),CONFIG_sha256=sha(H/'CONFIG.json'),GPU=gstart,no_old_restart=True))
  for script,unit,mem,high,cpu in [('primary.py','curation-qwen-continuous-v146.service','64G','56G','1200%'),('prepare.py','curation-qwen-continuous-preheat-v146.service','32G','28G','400%')]:
   if show(unit)['LoadState']!='not-found':raise ValueError('Existing new unit: observe only')
   args=['systemd-run','--user','--no-block','--unit='+unit,'--property=Type=oneshot','--property=CPUQuota='+cpu,'--property=MemoryMax='+mem,'--property=MemoryHigh='+high,'--property=MemorySwapMax=0','--property=Restart=no','--property=Nice=15','--property=TimeoutStartSec=infinity','--property=StandardOutput=append:'+str(H/(script+'.log')),'--property=StandardError=append:'+str(H/(script+'.log')),'--working-directory='+str(H),'--setenv=PYTHONDONTWRITEBYTECODE=1','--setenv=CUDA_VISIBLE_DEVICES=','--setenv=OMP_NUM_THREADS=1','--setenv=OPENBLAS_NUM_THREADS=1','--setenv=TOKENIZERS_PARALLELISM=false',sys.executable,'-B','-u',str(H/script),str(H)]
   z=subprocess.run(args,capture_output=True,text=True,timeout=20);frozen(H/(script+'_START_RESPONSE.json'),dict(rc=z.returncode,stdout=z.stdout,stderr=z.stderr));assert z.returncode==0,z.stderr;frozen(H/(script+'_OBSERVED.json'),show(unit))
  frozen(H/'ROLLOUT_COMPLETE.json',dict(unix=time.time(),stage='V146_CONTINUOUS_DOMAIN_DEFICIT_CONTROLLERS_LAUNCHED',new_READY_not_yet_claimed=True,no_training=True));atomic(H/'ROLLOUT_STATUS.json',load(H/'ROLLOUT_COMPLETE.json'))
 except BaseException as e:
  frozen(H/'ROLLOUT_FAILURE.json',dict(unix=time.time(),error=repr(e),no_action_retry=True,old_work_preserved=True));raise
if __name__=='__main__':main()
