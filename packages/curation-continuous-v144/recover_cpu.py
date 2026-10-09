"""One-shot parser-only CPU handoff after all four original QA scopes settle."""
import sys,os,json,time,shutil,base64,zlib,subprocess
from pathlib import Path
from common import frozen,atomic,sha,show
from rollout import remote
from adoption import admissible
from runtime_cpu import bootstrap

def load(p):return json.loads(Path(p).read_text())
def main():
 H=Path(sys.argv[1]);rc=load(H/'RECOVERY_CONFIG.json');old=Path(rc['old_root']);R=H.parent
 for n,h in rc['files_sha256'].items():
  if sha(H/n)!=h:raise ValueError('Frozen recovery input changed '+n)
 for path,h in rc['prior_files_sha256'].items():
  if sha(path)!=h:raise ValueError('Prior CPU fault boundary changed '+path)
 items=load(H/'RECOVERY_ITEMS.json');admissible(items,load(old/'PIPELINE_FAILURE.json'))
 if any(show(u)['MainPID']!='0' for u in rc['old_cpu_units']):raise ValueError('Prior CPU not terminal')
 if any(p.exists() for p in [old/'publication',old/'PUBLISH_INTENT.json']) or list((old/'events').glob('*_PUBLISH_INTENT.json')):raise ValueError('Possible prior publication; not parser-only recovery')
 frozen(H/'RECOVERY_RUN_INTENT.json',dict(unix=time.time(),pid=os.getpid(),no_teacher_replay=True))
 try:
  oldL=rc['old_remote_root'];L=rc['new_remote_root'];names=[t['name'] for t in items]
  # Already-started old QA must settle naturally; never kills or resends it.
  end=time.monotonic()+3600
  while True:
   query="import json;from pathlib import Path;H=Path("+repr(oldL)+");names="+repr([(t['gpu'],t['name']) for t in items])+";print(json.dumps({'complete':all((H/('runtime/gpu_'+str(g))/(n+'_COMPLETE.json')).exists() for g,n in names),'failures':[str(p) for p in H.glob('runtime/gpu_*/*_FAILURE.json')]}))"
   v=remote(query,120)
   if v['failures']:raise ValueError('Original QA failed/unknown; retain all scopes')
   if v['complete']:break
   if time.monotonic()>end:raise TimeoutError('Original QA still active; observation only')
   atomic(H/'RECOVERY_STATUS.json',dict(unix=time.time(),stage='WAIT_EXISTING_QA_SETTLED_NO_REPLAY'));time.sleep(20)
  # One graceful producer seal after complete receipts, no signals/models/cache changes.
  frozen(H/'GPU_OLD_SEAL_INTENT.json',dict(unix=time.time(),original_jobs=names))
  v=remote("import json,sys,time;from pathlib import Path;H=Path("+repr(oldL)+");sys.path.insert(0,str(H));from common import frozen,show;u=show('curation-qwen-continuous-gpu-v142.service');assert u['MainPID']=='1328462' and u['InvocationID']=='8d561c5f55364601bbf968540b0882be';assert not (H/'STOP_NEW.json').exists();frozen(H/'STOP_NEW.json',dict(unix=time.time(),reason='144 parser-only CPU acceptance recovery; all prior QA complete',no_request_replay=True));print(json.dumps({'sealed':True}))",120);frozen(H/'GPU_OLD_SEAL_OBSERVED.json',v)
  while True:
   v=remote("import json,sys;from pathlib import Path;H=Path("+repr(oldL)+");sys.path.insert(0,str(H));from common import show;u=show('curation-qwen-continuous-gpu-v142.service');print(json.dumps({'unit':u,'final':json.loads((H/'GPU_FINAL.json').read_text()) if (H/'GPU_FINAL.json').exists() else None}))",120)
   if v['unit']['MainPID']=='0' and v['final'] is not None:
    if v['final']['errors']:raise ValueError('Prior GPU controller error')
    break
   time.sleep(5)
  gb=remote((H/'gpu_boundary.py.txt').read_text().replace('__OLD_ROOT__',repr(oldL)),360);frozen(H/'PRIOR_GPU_BOUNDARY.json',gb)
  if gb['full_physical_receipts_verified']!=192:raise ValueError('Exact four settled scopes expected')
  c=load(old/'CONFIG.json');bootstrap(dict(c,runtime_dependencies=str(H/'runtime-deps')))
  from small_agent.curation.store_qwen_v35 import Batch,protocol
  from p0_qwen_worker_v35 import job_identity
  from p0_curation_bounded_resume_v3 import recoverable
  from small_agent.curation.quality_qwen_v35 import source_gate,reference_gate,verify_teacher_scope
  import receipt_adapter as adapter
  adapter.REMOTE=Path(oldL)
  P=H/'payload';P.mkdir();(H/'references').mkdir();(H/'source_audits').mkdir()
  adopted=[]
  for t in items:
   F=P/Path(t['folder']).parent;shutil.copytree(old/'payload'/Path(t['folder']).parent,F)
   v=adapter.fetch(t['gpu'],t)
   if v['status']!='complete':raise ValueError('Settled original receipt not complete')
   old_import=old/'events'/(t['name']+'_IMPORTED.json')
   if old_import.exists():
    # CSS was fully imported before its lazy parser gate failed. Preserve its SQL state.
    b=Batch(F/'review/batch')
    try:
     if b.manifest_hash!=v['batch_manifest_sha256'] or b.report()!=load(old_import)['report']:raise ValueError('Previously imported exact SQL report changed')
     for n,data in v['files'].items():
      if (F/'review/batch/worker/qwen'/n).read_bytes()!=base64.b64decode(data):raise ValueError('Previously imported full physical response changed')
    finally:b.close()
   else:adapter.verify_import(P,t['gpu'],t,v,Batch,protocol,job_identity,recoverable)
   q=load(t['config']);policy=load(q['release_policy'])['quality']
   if t['kind']=='reference':
    dest=H/'references'/Path(t['reference']).name;dest.symlink_to(F/'review',target_is_directory=True);verify_teacher_scope(q,[dest]);gate=reference_gate(dest,load(dest/'labels.json'),policy)
   else:
    dest=H/'source_audits'/t['scope'];dest.symlink_to(F/'review',target_is_directory=True);verify_teacher_scope(q,[dest,Path(t['reference'])]);gate=source_gate(dest,policy)
   frozen(dest/'ACTUAL_GATE_V36.json',gate);adopted.append(dict(name=t['name'],kind=t['kind'],cohort=t['cohort'],gate=gate,ledger_sha256=v['ledger_sha256'],gate_sha256=sha(dest/'ACTUAL_GATE_V36.json'),teacher_requests_replayed=0,not_READY=True))
  frozen(H/'ADOPTED_ACTUAL_GATES.json',adopted)
  # All old reference/source bodies remain excluded even if their gate is HOLD.
  from portable import build_index,ProofIndex,make_portable,write_input_manifests
  from grounding import protocol_plan
  ex=load(old/'EXCLUSION_BASE.json');ids=set(ex['body_ids'])|set(gb['body_ids']);keys=set(ex['request_keys'])|set(gb['request_keys']);frozen(H/'EXCLUSION_BASE.json',dict(ex,body_ids=sorted(ids),request_keys=sorted(keys),parent_exclusion_sha256=sha(old/'EXCLUSION_BASE.json'),parent_GPU_boundary_sha256=sha(H/'PRIOR_GPU_BOUNDARY.json'),all_HOLD_unknown_preserved=True));commit=build_index(H,ids,keys)
  for n in ['queue','events','blocked','scope_terminals']:(H/n).mkdir()
  for p in (old/'blocked').iterdir():shutil.copy2(p,H/'blocked'/p.name)
  cat=load(old/'SOURCE_CATALOG.json')
  for sc in cat:
   for k in ['source','reference']:
    if sc[k].startswith(str(old)+'/'):sc[k]=str(H)+sc[k][len(str(old)):]
  frozen(H/'SOURCE_CATALOG.json',cat);shutil.copy2(old/'PERFORMANCE.json',H/'PERFORMANCE.json')
  deps={str(p.relative_to(H/'runtime-deps')):sha(p) for p in (H/'runtime-deps').rglob('*') if p.is_file()};C=R/'code';cfg=dict(c,version=144,code_sha256={p.name:sha(p) for p in H.glob('*.py')},performance=str(H/'PERFORMANCE.json'),remote_root=L,prior_remote_root=oldL,runtime_dependencies=str(H/'runtime-deps'),runtime_dependencies_sha256=deps,exclusion_commitment_sha256=sha(H/'EXCLUSION_COMMITMENT.json'))
  cfg['engine_sha256']=dict(cfg['engine_sha256'],**{str(H/'SOURCE_CATALOG.json'):sha(H/'SOURCE_CATALOG.json'),str(H/'PERFORMANCE.json'):sha(H/'PERFORMANCE.json'),str(H/'RECOVERY_ITEMS.json'):sha(H/'RECOVERY_ITEMS.json'),str(H/'ADOPTED_ACTUAL_GATES.json'):sha(H/'ADOPTED_ACTUAL_GATES.json')});frozen(H/'CONFIG.json',cfg)
  from flow import verify_bound,hard
  verify_bound(H,cfg)
  fixture=H/'payload/transport_fixture';shutil.copytree(Path(rc['scratch'])/'reference_fixture/typescript',fixture/'review');b=Batch(fixture/'review/batch')
  try:fi,fk=protocol_plan(b,protocol,job_identity)
  finally:b.close()
  ix=ProofIndex(H)
  try:frozen(fixture/'EXCLUSION_PROOF.json',make_portable(H,ix,fi,fk))
  finally:ix.close()
  write_input_manifests(H,fixture)
  bundle=base64.b64encode(zlib.compress(json.dumps({p.name:base64.b64encode(p.read_bytes()).decode() for p in H.glob('*.py')}).encode())).decode()
  deploy=(H/'gpu_deploy.py.txt').read_text().replace('__NEW_ROOT__',repr(L)).replace('__OLD_ROOT__',repr(oldL)).replace('__BUNDLE__',repr(bundle)).replace('__CPU_CFG__',repr(cfg)).replace('__COMMIT__',repr(commit)).replace('__BOUNDARY__',repr(gb))
  frozen(H/'GPU_DEPLOY_INTENT.json',dict(unix=time.time(),target=L));ack=remote(deploy,900);frozen(H/'GPU_DEPLOY_OBSERVED.json',ack)
  frozen(H/'REAL_TRANSFER_INTENT.json',dict(unix=time.time(),fixture_manifest_sha256=sha(fixture/'INPUT_FILES.json')));transport='ssh -C -p 2222 -o BatchMode=yes -o ControlPath=none -o ConnectTimeout=8 -o ForwardAgent=no -o StrictHostKeyChecking=yes';hard(['rsync','-az','-e',transport,str(fixture)+'/','GPU_WORKER:'+L+'/payload/transport_fixture/'],timeout=600,env={**os.environ,'SSH_AUTH_SOCK':''})
  verify=(H/'gpu_fixture_launch.py.txt').read_text().replace('__NEW_ROOT__',repr(L)).replace('__PROOF_SHA__',repr(sha(fixture/'INPUT_FILES.json')));frozen(H/'GPU_LAUNCH_INTENT.json',dict(unix=time.time(),target=L));gs=remote(verify,120);frozen(H/'GPU_LAUNCH_OBSERVED.json',gs)
  frozen(H/'LAUNCH_INTENT.json',dict(unix=time.time(),config_sha256=sha(H/'CONFIG.json'),no_teacher_replay=True))
  for script,unit,mem,high,cpu in [('primary.py','curation-qwen-continuous-v144.service','64G','56G','1200%'),('prepare.py','curation-qwen-continuous-preheat-v144.service','32G','28G','400%')]:
   if show(unit)['LoadState']!='not-found':raise ValueError('Existing new unit, do not repeat')
   args=['systemd-run','--user','--no-block','--unit='+unit,'--property=Type=oneshot','--property=CPUQuota='+cpu,'--property=MemoryMax='+mem,'--property=MemoryHigh='+high,'--property=MemorySwapMax=0','--property=Restart=no','--property=Nice=15','--property=TimeoutStartSec=infinity','--property=StandardOutput=append:'+str(H/(script+'.log')),'--property=StandardError=append:'+str(H/(script+'.log')),'--working-directory='+str(H),'--setenv=PYTHONDONTWRITEBYTECODE=1','--setenv=CUDA_VISIBLE_DEVICES=','--setenv=OMP_NUM_THREADS=1','--setenv=OPENBLAS_NUM_THREADS=1','--setenv=TOKENIZERS_PARALLELISM=false',sys.executable,'-B','-u',str(H/script),str(H)]
   z=subprocess.run(args,capture_output=True,text=True,timeout=20);frozen(H/(script+'_START_RESPONSE.json'),dict(rc=z.returncode,stdout=z.stdout,stderr=z.stderr));assert z.returncode==0,z.stderr;frozen(H/(script+'_OBSERVED.json'),show(unit))
  frozen(H/'RECOVERY_COMPLETE.json',dict(unix=time.time(),adopted_scopes=4,teacher_replays=0,new_READY_not_claimed=True));atomic(H/'RECOVERY_STATUS.json',load(H/'RECOVERY_COMPLETE.json'))
 except BaseException as e:frozen(H/'RECOVERY_FAILURE.json',dict(unix=time.time(),error=repr(e),no_retry=True));raise
if __name__=='__main__':main()
