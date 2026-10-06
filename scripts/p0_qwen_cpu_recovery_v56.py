#!/usr/bin/env python3
"""Explicit CPU-only derived publication for verified OOM/backpressure. No QA sends.

Never modifies original candidates, receipts or engines, retries unknown teacher
requests, clears unrelated HOLD, or publishes without the original full gates.
"""
import argparse,json,os,sqlite3,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'src'),str(ROOT/'scripts')]
from p0_qwen_overnight_slot_v58 import locked,publish,completed_evidence_base
from p0_qwen_source_dispatch_v31 import frozen_write
from small_agent.curation.supply_control import file_sha,digest,recipe_identity
from small_agent.curation.full_inventory_v11 import AllStockControl
from small_agent.curation.quality_qwen_v35 import publication_quality,verify_teacher_scope,reference_gate,source_gate
from small_agent.curation.fallback_qwen_v25 import validate_activation

ITEMS=[(5,'qwen_pool_v44/gpu_5/9f48aa7dca20d8258050b0dc/batches/qwen44_065a6164a648f21cf24e80b5','curation-qwen-continuation-v44-5.service','oom-kill'),
 (1,'qwen_pool_v44/gpu_1/9f48aa7dca20d8258050b0dc/batches/qwen44_6f782a6dff1f94f15fce1bcb','curation-qwen-isolated-v46-1.service','exit-code'),
 (6,'qwen_pool_v48/gpu_6/53c6f27d30cf0957bb172448/batches/qwen48_d1751025ebfb965be10c3d88','curation-qwen-continuation-v48-6.service','exit-code')]

def terminal_guard(v):
 if v.get('stop_reason') is not None or v.get('selected')!=v.get('considered') or not isinstance(v.get('selected'),int) or v['selected']<1:
  raise ValueError('Incomplete/unknown teacher outcome preserved; no CPU recovery')

def failure_guard(state,result,expected,log):
 if state in ('active','activating') or result!=expected:raise ValueError('Existing/unknown controller; do not replace')
 if expected=='exit-code' and 'ValueError: backpressure' not in log:raise ValueError('Not the observed explicit backpressure failure')
 if expected=='oom-kill' and 'killed by the OOM killer' not in log:raise ValueError('OOM not independently observed')

def prepare(root,performance):
 out=root/'qwen_pool_v56';out.mkdir(exist_ok=True);plans=[]
 if (out/'CPU_RECOVERY_PLAN_V56.json').exists() or (out/'LAUNCH_INTENT_V56.json').exists():raise ValueError('Existing recovery intent: inspect only')
 for gpu,relative,unit,expected in ITEMS:
  old=root/relative
  if any((old/'release'/n).exists() for n in ('READY_INTERNAL.json','RELEASE_INTENT.json')):raise ValueError('Never derive an existing committed/unknown intent')
  state=subprocess.check_output(['systemctl','--user','show',unit,'-p','ActiveState','--value'],text=True).strip()
  result=subprocess.check_output(['systemctl','--user','show',unit,'-p','Result','--value'],text=True).strip()
  log=subprocess.check_output(['journalctl','--user','-u',unit,'-n','60','--no-pager','-o','cat'],text=True)
  failure_guard(state,result,expected,log)
  binding=json.loads((old/'release/INPUT_BINDING.json').read_text());cb=json.loads((old/'CANDIDATE_BINDING.json').read_text())
  version=44 if 'qwen_pool_v44' in relative else 48
  cfgpath=old/f'RELEASE_CONFIG_V{version}.json';cfg=json.loads(cfgpath.read_text())
  if cb['controller_sha256']!=file_sha(ROOT/f'scripts/p0_qwen_overnight_slot_v{version}.py') or cb['teacher_registry_sha256']!=file_sha(Path(cfg['qwen_registry'])):raise ValueError('Original controller/teacher changed')
  validate_activation(Path(cfg['activation_receipt']))
  for key,p in {'candidate_sha256':old/'candidates.parquet','candidate_binding_sha256':old/'CANDIDATE_BINDING.json','config_sha256':cfgpath,'quality_sha256':old/'release/QUALITY.json','tokenizer_sha256':Path(cfg['tokenizer']),'policy_sha256':Path(cfg['release_policy'])}.items():
   if file_sha(p)!=binding[key]:raise ValueError('Frozen input changed: '+key)
  for p,h in binding['engine_sha256'].items():
   if file_sha(Path(p))!=h:raise ValueError('Original engine changed')
  terminal=json.loads((old/'review/batch/worker/qwen/LOCAL_STATUS_V35.json').read_text());terminal_guard(terminal)
  cohort=cb['source_id']+'/'+cb['domain']+'/'+cb['language'];key=digest([cohort,file_sha(Path(cfg['qwen_registry']))])[:24]
  base=completed_evidence_base(root,gpu,cohort,key,cb['domain'],cb['language']);src=base/'source_audits'/key;ref=base/'references'/(cb['domain']+'_'+cb['language'])
  verify_teacher_scope(cfg,[src,ref,old/'review']);quality=json.loads(Path(cfg['release_policy']).read_text())['quality']
  for f,gate in ((ref,reference_gate(ref,json.loads((ref/'labels.json').read_text()),quality)),(src,source_gate(src,quality))):
   terminal_guard(json.loads((f/'batch/worker/qwen/LOCAL_STATUS_V35.json').read_text()))
   if gate!=json.loads((f/'ACTUAL_GATE_V36.json').read_text()):raise ValueError('Actual source/reference gate differs')
  q=publication_quality(cfg,old/'candidates.parquet',src,ref,old/'review',binding['mode'])
  if q['status']!='passed' or digest(q)!=digest(json.loads((old/'release/QUALITY.json').read_text())):raise ValueError('Actual original QA scope differs')
  folder=out/'recoveries'/old.name;
  if folder.exists():raise ValueError('Existing partial derivation: no automatic retry')
  folder.mkdir(parents=True)
  proof=dict(version=56,gpu=gpu,original_batch=str(old),failure_unit=unit,failure_state=state,failure_result=result,journal_sha256=digest(log),old_binding_sha256=file_sha(old/'release/INPUT_BINDING.json'),candidate_sha256=file_sha(old/'candidates.parquet'),terminal_sha256=file_sha(old/'review/batch/worker/qwen/LOCAL_STATUS_V35.json'),quality_sha256=file_sha(old/'release/QUALITY.json'),new_performance_sha256=file_sha(performance),teacher_requests=0,original_splits_preserved=True,quality_thresholds_changed=False)
  frozen_write(folder/'CPU_RECOVERY_V56.json',proof)
  if not (folder/'candidates.parquet').exists():os.link(old/'candidates.parquet',folder/'candidates.parquet')
  if file_sha(folder/'candidates.parquet')!=binding['candidate_sha256']:raise ValueError('Derived hardlink differs')
  if not (folder/'review').exists():(folder/'review').symlink_to(old/'review',target_is_directory=True)
  if (folder/'review').resolve()!=(old/'review').resolve():raise ValueError('Derived QA pointer differs')
  newcb=dict(cb,cpu_recovery_sha256=file_sha(folder/'CPU_RECOVERY_V56.json'));frozen_write(folder/'CANDIDATE_BINDING.json',newcb)
  newcfg=dict(cfg,cpu_recovery_sha256=file_sha(folder/'CPU_RECOVERY_V56.json'));frozen_write(folder/'RELEASE_CONFIG_V56.json',newcfg)
  bid=digest(dict(domain=cb['domain'],input_binding=binding,recipe=recipe_identity(json.loads(Path(cfg['recipe']).read_text()))))
  plans.append(dict(gpu=gpu,original=str(old),folder=str(folder),source_audit=str(src),reference=str(ref),mode=binding['mode'],domain=cb['domain'],old_bid=bid,config=str(folder/'RELEASE_CONFIG_V56.json')))
 frozen_write(out/'CPU_RECOVERY_PLAN_V56.json',dict(version=56,engine_sha256=file_sha(Path(__file__)),performance_sha256=file_sha(performance),items=plans,teacher_requests=0,quality_thresholds_changed=False))
 # ONLY the specifically observed CPU OOM occupies pending capacity. Retain its
 # old stages/binding and mark quarantined, never clear unrelated waiting/HOLD.
 cfg=json.loads(Path(plans[0]['config']).read_text())
 with locked(root/'release-coordinator.lock',1),locked(Path(cfg['database']).parent/'production-release.lock',1):
  ctl=AllStockControl(Path(cfg['database']),json.loads(Path(cfg['recipe']).read_text()))
  try:
   r=ctl.db.execute('select status,reason from batches where batch_id=?',(plans[0]['old_bid'],)).fetchone()
   if not r:raise ValueError('Expected observed OOM registration missing')
   if ctl.db.execute('select 1 from releases where batch_id=?',(plans[0]['old_bid'],)).fetchone():raise ValueError('OOM batch became committed')
   if r[0]=='quarantined':
    if not str(r[1]).startswith('V56_CONFIRMED_CPU_OOM_PRESERVED:'):raise ValueError('Other quarantine must be preserved')
   elif r[0]=='queued':ctl.hold(plans[0]['old_bid'],'V56_CONFIRMED_CPU_OOM_PRESERVED:'+str(out/'CPU_RECOVERY_PLAN_V56.json'),quarantine=True)
   else:raise ValueError('Unexpected OOM state preserved')
  finally:ctl.close()
 frozen_write(out/'PREPARED_CPU_RECOVERY_V56.json',dict(stage='DERIVED_CPU_ONLY_READY_TO_RUN_NOT_RELEASED',plan_sha256=file_sha(out/'CPU_RECOVERY_PLAN_V56.json'),old_oom_preserved=True,unrelated_holds_changed=False,teacher_requests=0))
 return plans

def run(root,performance):
 out=root/'qwen_pool_v56';plan=json.loads((out/'CPU_RECOVERY_PLAN_V56.json').read_text())
 if plan['engine_sha256']!=file_sha(Path(__file__)) or plan['performance_sha256']!=file_sha(performance):raise ValueError('Frozen recovery changed')
 with locked(out/'runner.lock',1):
  for item in plan['items']:
   folder=Path(item['folder']);cfg=json.loads(Path(item['config']).read_text());status=folder/'STATUS_V56.json'
   if (folder/'RUN_INTENT_V56.json').exists():
    if (folder/'release/READY_INTERNAL.json').exists():continue
    raise ValueError('Existing CPU recovery intent; inspect, no automatic retry')
   frozen_write(folder/'RUN_INTENT_V56.json',dict(version=56,plan_sha256=file_sha(out/'CPU_RECOVERY_PLAN_V56.json'),started_unix=time.time(),teacher_requests=0))
   def report(stage,**kw):status.write_text(json.dumps(dict(version=56,stage=stage,gpu=item['gpu'],updated_unix=time.time(),teacher_requests=0,**kw),indent=2)+'\n')
   report('FULL_ORIGINAL_PUBLICATION_GATES_CPU_ONLY')
   try:
    publish(cfg,Path(item['config']),folder,Path(item['source_audit']),Path(item['reference']),item['domain'],item['mode'],performance,out)
    ready=folder/'release/READY_INTERNAL.json';state='READY_INTERNAL' if ready.exists() else 'HOLD_PHYSICAL'
    with locked(root/'queue.lock'):
     db=sqlite3.connect(root/'stock.sqlite',timeout=60)
     with db:
      name=Path(item['original']).name
      db.execute('update jobs set state=?,reason=? where name=?',(state,str(folder/'CPU_RECOVERY_V56.json'),name));db.execute('update records set gate=? where job=?',(state,name))
      if item['mode']=='source_audit':
       q=publication_quality(cfg,folder/'candidates.parquet',Path(item['source_audit']),Path(item['reference']),folder/'review',item['mode']);inspected=set(json.loads((folder/'review/PLAN.json').read_text())['body_ids'])
       db.executemany("update records set gate='CANDIDATE_FALLBACK',job=NULL where h=? and job=?",[(h,name) for h in set(q['excluded_ids'])-inspected])
     db.close()
    report(state,train_body_tokens=json.loads(ready.read_text())['unique_train_body_tokens'] if ready.exists() else 0)
   except Exception as exc:report('CPU_RECOVERY_STOPPED_PRESERVE_NO_RETRY',error=type(exc).__name__,detail=str(exc)[-700:]);raise

def main():
 p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--performance',type=Path,required=True);p.add_argument('--mode',choices=('prepare','run'),required=True);a=p.parse_args()
 perf=json.loads(a.performance.read_text())
 if perf['release_cpu_workers']!=2 or any(perf[k] is not False for k in ('quality_thresholds_changed','skip_hashes','parallel_ledger_writers')):raise ValueError('Unsafe recovery configuration')
 if a.mode=='prepare':print(json.dumps(prepare(a.root,a.performance)))
 else:run(a.root,a.performance)
if __name__=='__main__':main()
