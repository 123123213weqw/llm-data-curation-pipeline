#!/usr/bin/env python3
"""v67 continuation: fix completion observation race and heldout eligibility; reuse identical completed v35 evidence.

One GPU's independent compact64 QA -> unchanged full physical release gates.

Eight slots have separate teacher/QA identities. Stock allocation and physical
inventory writers are serialized, while real teacher work is parallel. Unknown
requests stop this slot without resend; unrelated slots can continue.
"""
import argparse,fcntl,json,os,sqlite3,subprocess,sys,time
from collections import defaultdict
from contextlib import contextmanager
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'src'),str(ROOT/'scripts')]
from p0_qwen_source_dispatch_v31 import command,SSH,SSH_TRANSPORT,frozen_write
SSH=SSH[:1]+['-o','ForwardAgent=no','-o','StrictHostKeyChecking=yes']+SSH[1:]
SSH_TRANSPORT+=' -o ForwardAgent=no -o StrictHostKeyChecking=yes'
from p0_inventory_supply_v24 import sample,source_query
from p0_inventory_supply_v11 import retrieve,terms
from p0_arrow_reader_v15 import ArrowRawReader
from p0_heldout_reserve_v24 import select_reserve
from p0_prepare_qwen_references_v35 import prepare_math
from small_agent.curation.quality_qwen_v35 import make_batch,control_rows,reference_gate,source_gate,publication_quality,verify_teacher_scope
from small_agent.curation.store_qwen_v35 import Batch
from small_agent.curation.supply_control import digest,file_sha
from small_agent.curation.release_gates_v5 import bound_json,ledger_snapshot,EvalScreen
from small_agent.curation.full_inventory_v11 import layer
from small_agent.curation.fallback_qwen_v25 import validate_activation

@contextmanager
def locked(path,seconds=900):
 with Path(path).open('a') as f:
  end=time.monotonic()+seconds
  while True:
   try:fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB);break
   except BlockingIOError:
    if time.monotonic()>end:raise TimeoutError('Existing writer lock retained; do not steal')
    time.sleep(1)
  yield

def import_terminal(folder):
 b=Batch(folder/'batch')
 try:
  for p in sorted((folder/'batch/worker/qwen').glob('*.jsonl')):b.import_results('qwen',p)
 finally:b.close()
 p=folder/'batch/worker/qwen/LOCAL_STATUS_V35.json'
 if not p.exists():raise ValueError('Missing actual local terminal')
 v=json.loads(p.read_text())
 if v['stop_reason'] or v['considered']!=v['selected']:raise ValueError('Unknown/incomplete local outcome: NEVER resend')
 return v

def observe_worker_terminal(terminal,unit):
 """Observe only; recheck terminal after unit stops to close finish/probe race.

 No requests, launches or retries occur here. A genuinely absent or unknown
 terminal remains fail-closed, including transport exceptions.
 """
 def probe():
  raw=command(SSH+['test ! -f '+str(terminal)+' || cat '+str(terminal)],timeout=30).strip()
  if not raw:return None
  v=json.loads(raw)
  if v['stop_reason'] or v['considered']!=v['selected']:
   raise ValueError('Unknown local terminal; slot stopped, never retry')
  return v
 deadline=time.monotonic()+14400
 while True:
  v=probe()
  if v is not None:return v
  if time.monotonic()>deadline:raise TimeoutError('Worker observation deadline; inspect, never retry')
  active=command(SSH+['systemctl --user show '+unit+' -p ActiveState --value'],timeout=30).strip()
  if active not in ('active','activating'):
   # Terminal publication precedes worker exit. It may have occurred after the
   # first probe and before systemctl; do not misclassify cache-only completion.
   v=probe()
   if v is not None:return v
   raise ValueError('Worker stopped without terminal after final recheck; never restart')
  time.sleep(20)

def score(folder,D,gpu,scope):
 key=digest([str(folder.resolve()),file_sha(folder/'batch/MANIFEST.json')])[:24]
 remote=D/'pool_v36/work'/f'gpu_{gpu}'/key
 unit='curation-qwen36-'+key+'.service';ledger=D/'pool_v36/ledgers'/f'gpu_{gpu}'/(scope+'.sqlite')
 command(SSH+['mkdir -p '+str(remote)+' '+str(ledger.parent)])
 command(['rsync','-a','--ignore-existing','-e',SSH_TRANSPORT,str(folder)+'/', 'GPU_WORKER:'+str(remote)+'/'],timeout=240)
 terminal=remote/'batch/worker/qwen/LOCAL_STATUS_V35.json'
 probe=command(SSH+['test ! -f '+str(terminal)+' || cat '+str(terminal)],timeout=30).strip()
 if probe:
  v=json.loads(probe)
  if v['stop_reason']:raise ValueError('Preserved previous unknown request; no restart')
 else:
  launch=f'''set -eu; D={D}; U={unit}; if systemctl --user show "$U" -p LoadState --value | grep -qx loaded; then echo EXISTING_UNIT_NO_DUPLICATE; else N=4; if test {gpu} = 1 && systemctl --user show curation-qwen-source-qa-v31.service -p ActiveState --value | grep -Eq '^(active|activating)$'; then N=2; fi; systemd-run --user --no-block --unit="$U" --property=Type=oneshot --property=TimeoutStartSec=4h --property=WorkingDirectory="$D/code" --property=CPUQuota=200% --property=MemoryMax=8G --setenv=CUDA_VISIBLE_DEVICES= --setenv=OMP_NUM_THREADS=1 --setenv=TOKENIZERS_PARALLELISM=false /srv/curation/venv/bin/python -u scripts/p0_qwen_worker_v35.py --batch {remote}/batch --ledger {ledger} --workers "$N" --limit 512 --allow-local; fi'''
  command(SSH+[launch],timeout=40)
 observe_worker_terminal(terminal,unit)
 dest=folder/'batch/worker/qwen';dest.mkdir(parents=True,exist_ok=True)
 command(['rsync','-a','--include=*.jsonl','--include=LOCAL_STATUS_V35.json','--exclude=*','-e',SSH_TRANSPORT,
  'GPU_WORKER:'+str(remote/'batch/worker/qwen')+'/',str(dest)+'/'],timeout=60)
 import_terminal(folder)

def reference(cfg,out,domain,language,D,gpu,policy):
 f=out/'references'/(domain+'_'+language)
 if not (f/'PLAN.json').exists():
  if domain=='math' and language=='en':prepare_math(cfg,Path(cfg['existing_math_reference']),f)
  else:
   rows,labels,proof=control_rows(domain,language)
   make_batch(cfg,f,rows,dict(kind='reference',domain=domain,language=language,independent=True,strata={r['normalized_sha256']:domain+'/'+language for r in rows}))
   frozen_write(f/'labels.json',labels);frozen_write(f/'verification.json',proof)
   frozen_write(f/'REFERENCE_QWEN_V35.json',dict(version=35,domain=domain,language=language,training_eligible=False,
    natural_corpus_factual_error_rate_certified=False,checker_sha256=file_sha(ROOT/'src/small_agent/curation/quality_qwen_v35.py'),
    evidence_files=[dict(path=str((f/n).resolve()),sha256=file_sha(f/n)) for n in ('PLAN.json','labels.json','verification.json')]))
 score(f,D,gpu,'reference_'+domain+'_'+language)
 gate=reference_gate(f,json.loads((f/'labels.json').read_text()),policy['quality'])
 frozen_write(f/'ACTUAL_GATE_V36.json',gate)
 if gate['status']!='passed':return None
 return f

def select_new(db,cfg,source,domain,lang,sg,mode,perf):
 approved=sg['approved_strata'];params=[source,domain,lang]
 clause="r.gate='CANDIDATE' AND r.job IS NULL"
 if mode=='source_audit':
  if not approved:return []
  clause+=' AND r.stratum IN ('+','.join('?' for _ in approved)+')';params+=approved
 else:
  clause="r.gate IN ('CANDIDATE','CANDIDATE_FALLBACK') AND r.job IS NULL"
  if approved:clause+=" AND (r.gate='CANDIDATE_FALLBACK' OR r.stratum NOT IN ("+','.join('?' for _ in approved)+'))';params+=approved
 q=source_query(db,clause)
 strata=approved if mode=='source_audit' else [r[0] for r in db.execute('SELECT DISTINCT stratum FROM ('+q+") WHERE split='train'",params)]
 # Routing restrictions apply to TRAIN, not the original heldout splits.
 # Individual mode still fully reviews every selected validation/test body.
 hq,hparams=(q,params) if mode=='source_audit' else (source_query(db,"r.gate IN ('CANDIDATE','CANDIDATE_FALLBACK') AND r.job IS NULL"),[source,domain,lang])
 held=select_reserve(db,hq,hparams,strata,target_tokens=perf.get('heldout_target_tokens_per_stratum',16384),maximum_documents_per_stratum=128 if mode=='source_audit' else 32)
 if held is None:return []
 limit=cfg['maximum_batch_documents']*perf['fast_batch_size_multiplier'] if mode=='source_audit' else 512-len(held)
 target=cfg['batch_train_body_tokens']*perf['fast_batch_size_multiplier'] if mode=='source_audit' else cfg['batch_train_body_tokens']
 if limit<1:return []
 chosen=[];n=0
 for r in db.execute(q+" AND r.split='train' ORDER BY r.rank LIMIT ?",[*params,limit]):
  chosen.append(r);n+=r['n']
  if n>=target:break
 return chosen+held if chosen else []

def capacity_available(database,recipe):
 db=sqlite3.connect('file:'+str(database)+'?mode=ro',uri=True)
 try:
  pending=db.execute("SELECT COUNT(*) FROM batches WHERE status NOT IN ('ready','quarantined','legacy_internal')").fetchone()[0]
 finally:db.close()
 return pending<int(recipe['maximum_unreleased_batches']),pending

def _publish_locked(cfg,cp,batch,src,ref,domain,mode,perfpath,out):
 env={**os.environ,'CUDA_VISIBLE_DEVICES':'','OMP_NUM_THREADS':'1','P0_PARALLEL_CONFIG':str(perfpath)}
 def run(script,args):subprocess.run([sys.executable,str(ROOT/'scripts'/script),*map(str,args)],check=True,env=env)
 current=Path(Path(cfg['inventory_root'],'CURRENT').read_text().strip())
 if json.loads(current.read_text())['ledger']!=ledger_snapshot(Path(cfg['database'])):
  run('p0_build_inventory_index_v13.py',['--database',cfg['database'],'--legacy-receipt',cfg['legacy_receipt'],'--sketch-root',cfg['sketch_root'],'--output',cfg['inventory_root']])
  current=Path(Path(cfg['inventory_root'],'CURRENT').read_text().strip())
 args=dict(candidates=batch/'candidates.parquet',source_audit=src,reference=ref,batch_audit=batch/'review',
  eval_registry=cfg['eval_registry'],inventory_index=current,database=cfg['database'],tokenizer=cfg['tokenizer'],output=batch/'release',
  source_terms=Path(cfg['root'])/'terms'/cfg['_source']/'SOURCE_TERMS.json',candidate_binding=batch/'CANDIDATE_BINDING.json',config=cp,
  recipe=cfg['recipe'],policy=cfg['release_policy'],domain=domain,mode=mode)
 run('p0_release_inventory_batch_qwen_v35.py',[v for k,x in args.items() for v in ('--'+k.replace('_','-'),x)])

def publish(cfg,cp,batch,src,ref,domain,mode,perfpath,out):
 # Wait for ORIGINAL recipe admission without holding a writer lock while asleep.
 # Never retry a started publisher/partial, clear HOLD or increase capacity.
 end=time.monotonic()+12*3600;recipe=json.loads(Path(cfg['recipe']).read_text())
 while True:
  with locked(Path(cfg['root'])/'release-coordinator.lock',seconds=max(1,end-time.monotonic())):
   available,pending=capacity_available(Path(cfg['database']),recipe)
   if available:return _publish_locked(cfg,cp,batch,src,ref,domain,mode,perfpath,out)
  f=Path(out)/'CAPACITY_WAIT_V67.json';f.write_text(json.dumps(dict(stage='WAIT_ORIGINAL_CAPACITY_NO_HOLD_CHANGE',pending=pending,maximum_unreleased_batches=recipe['maximum_unreleased_batches'],batch=str(batch),updated_unix=time.time(),teacher_requests_retried=0)))
  if time.monotonic()>=end:raise TimeoutError('Original capacity remains HOLD; no publisher attempt or retry')
  time.sleep(30)

def completed_evidence_base(root,gpu,cohort,key,domain,lang):
 # Read-only exact-cohort evidence from the known settled prior continuation.
 # Scope, hashes, actual gates and terminal are still verified by the caller.
 bases=[root/'qwen_pool_v61'/f'gpu_{gpu}'/digest([cohort])[:24],root/'qwen_pool_v58'/f'gpu_{gpu}'/digest([cohort])[:24],root/'qwen_pool_v55'/f'gpu_{gpu}'/digest([cohort])[:24],root/'qwen_pool_v44'/f'gpu_{gpu}'/digest([cohort])[:24],root/'qwen_pool_v42'/f'gpu_{gpu}'/digest([cohort])[:24],root/'qwen_pool_v48'/f'gpu_{gpu}'/digest([cohort])[:24],root/'qwen_pool_v37'/f'gpu_{gpu}'/digest([cohort])[:24],root/'qwen_pool_v39'/f'gpu_{gpu}'/digest([cohort])[:24],root/'qwen_pool_v36'/f'gpu_{gpu}']
 for base in bases:
  if all(p.exists() for p in (base/'references'/(domain+'_'+lang)/'ACTUAL_GATE_V36.json',base/'source_audits'/key/'ACTUAL_GATE_V36.json')):return base
 return bases[-1]

def run_cohort(a):
 if a.gpu not in range(8) or len(set(a.cohorts))!=len(a.cohorts):raise ValueError('Unique authorized GPU/cohorts required')
 cfg=json.loads(a.config.read_text());root=Path(cfg['root']);out=root/'qwen_pool_v67'/f'gpu_{a.gpu}'/digest(a.cohorts)[:24];out.mkdir(parents=True,exist_ok=True)
 perf=json.loads(a.performance.read_text());policy=json.loads(Path(cfg['release_policy']).read_text())
 if any(perf.get(k) is not False for k in ('quality_thresholds_changed','skip_hashes','parallel_ledger_writers')):raise ValueError('Unsafe performance configuration')
 registry=bound_json(root/'REGISTRY.json');sources={s['id']:s for s in registry['sources']};reader=ArrowRawReader()
 frozen_write(out/'SLOT_BINDING_V67.json',dict(version=67,engine_sha256=file_sha(Path(__file__)),config_sha256=file_sha(a.config),
  teacher_registry_sha256=file_sha(Path(cfg['qwen_registry'])),performance_sha256=file_sha(a.performance),gpu=a.gpu,cohorts=a.cohorts,unknown_csharp_preserved=True))
 def status(stage,**kw):
  f=out/'STATUS_V67.json';t=f.with_suffix('.tmp');t.write_text(json.dumps(dict(version=67,stage=stage,updated_unix=time.time(),gpu=a.gpu,paid_api_requests=0,training_started=False,**kw),indent=2)+'\n');os.replace(t,f)
 with locked(out/'slot.lock',seconds=1):
  db=sqlite3.connect(root/'stock.sqlite',timeout=60);db.row_factory=sqlite3.Row
  try:
   end=a.deadline;qualified=[]
   for cohort in a.cohorts:
    source,domain,lang=cohort.split('/')
    if lang=='csharp':status('C_SHARP_OLD_UNKNOWN_PRESERVED_NO_RETRY',cohort=cohort);continue
    if source not in sources:status('SOURCE_NOT_REGISTERED_HOLD',cohort=cohort);continue
    if not db.execute(source_query(db,"r.gate IN ('CANDIDATE','CANDIDATE_FALLBACK') AND r.job IS NULL")+" AND r.split='train' LIMIT 1",(source,domain,lang)).fetchone():continue
    # Do not consume new calibration requests for a cohort with no eligible
    # original train + validation + test stock; never steal jobs or alter split.
    if not select_new(db,cfg,source,domain,lang,dict(approved_strata=[]),'individual',perf):
     status('NO_COMPLETE_UNALLOCATED_SPLIT_STOCK_NEXT_COHORT',cohort=cohort);continue
    status('INDEPENDENT_REFERENCE_QA',cohort=cohort);validate_activation(Path(cfg['activation_receipt']))
    st=terms(cfg,sources[source])
    if st.get('internal_training_eligible') is not True or st.get('distribution_eligible') is not False:raise ValueError('Source license gate HOLD')
    key=digest([cohort,file_sha(Path(cfg['qwen_registry']))])[:24]
    oldbase=completed_evidence_base(root,a.gpu,cohort,key,domain,lang)
    oldref=oldbase/'references'/(domain+'_'+lang);oldsrc=oldbase/'source_audits'/key
    if (oldref/'ACTUAL_GATE_V36.json').exists() and (oldsrc/'ACTUAL_GATE_V36.json').exists():
     verify_teacher_scope(cfg,[oldref,oldsrc])
     rg=reference_gate(oldref,json.loads((oldref/'labels.json').read_text()),policy['quality'])
     sg=source_gate(oldsrc,policy['quality'])
     if rg!=json.loads((oldref/'ACTUAL_GATE_V36.json').read_text()) or sg!=json.loads((oldsrc/'ACTUAL_GATE_V36.json').read_text()):raise ValueError('Frozen actual evidence changed')
     for completed in (oldref,oldsrc):
      terminal=json.loads((completed/'batch/worker/qwen/LOCAL_STATUS_V35.json').read_text())
      if terminal['stop_reason'] or terminal['considered']!=terminal['selected']:raise ValueError('Incomplete actual old result, never reissue')
     if rg['status']!='passed':status('REFERENCE_QUALITY_HOLD',cohort=cohort);continue
     frozen_write(out/'REUSED_IDENTICAL_PROTOCOL_V67.json',dict(version=67,reference=str(oldref),source=str(oldsrc),teacher_registry_sha256=file_sha(Path(cfg['qwen_registry'])),reference_gate_sha256=file_sha(oldref/'ACTUAL_GATE_V36.json'),source_gate_sha256=file_sha(oldsrc/'ACTUAL_GATE_V36.json'),model_calls=0,quality_thresholds_changed=False))
     qualified.append((cohort,oldsrc,oldref,sg));status('REUSED_ACTUAL_QA_NO_RESEND',cohort=cohort,approved_strata=sg['approved_strata']);break
    ref=reference(cfg,out,domain,lang,a.deployment,a.gpu,policy)
    if ref is None:status('REFERENCE_QUALITY_HOLD',cohort=cohort);continue
    src=out/'source_audits'/key
    selected,pop=sample(db,source,domain,lang,64,gate_clause="r.initial_gate='CANDIDATE'")
    if not selected:continue
    rows=[] if (src/'PLAN.json').exists() else retrieve(cfg,db,selected,registry,reader)
    make_batch(cfg,src,rows,dict(kind='source',source_id=source,domain=domain,language=lang,population=pop,
     strata={r['h']:r['stratum'] for r in selected},registry_sha256=file_sha(root/'REGISTRY.json')))
    status('ACTUAL_SOURCE_CALIBRATION',cohort=cohort);score(src,a.deployment,a.gpu,'source_'+key)
    sg=source_gate(src,policy['quality']);frozen_write(src/'ACTUAL_GATE_V36.json',sg)
    qualified.append((cohort,src,ref,sg));status('SOURCE_QA_COMPLETED_SAME_THRESHOLDS',cohort=cohort,source_gate=sg['status'],approved_strata=sg['approved_strata'])
    # Start releasing the first available cohort instead of waiting for every
    # source on this GPU to be calibrated. Later sources remain explicit TODOs.
    break
   turn=0
   while qualified and time.monotonic()<end:
    progress=False
    for cohort,src,ref,sg in qualified:
     source,domain,lang=cohort.split('/');mode='source_audit' if sg['approved_strata'] and turn%4!=3 else 'individual'
     status('SELECT_UNALLOCATED_STOCK',cohort=cohort,mode=mode)
     validate_activation(Path(cfg['activation_receipt']))
     with locked(root/'queue.lock'):
      records=select_new(db,cfg,source,domain,lang,sg,mode,perf)
      if not records:continue
      name='qwen67_'+digest([cohort,mode,file_sha(Path(cfg['qwen_registry'])),[r['h'] for r in records]])[:24]
      with db:
       db.execute('INSERT INTO jobs(name,source,mode) VALUES (?,?,?)',(name,source,mode))
       for r in records:
        if db.execute('UPDATE records SET job=? WHERE h=? AND job IS NULL',(name,r['h'])).rowcount!=1:raise ValueError('Concurrent stock allocation')
     progress=True;batch=out/'batches'/name;batch.mkdir(parents=True,exist_ok=True);candidate=batch/'candidates.parquet'
     status('ORIGINAL_RAW_READ_AND_ISOLATION',cohort=cohort,job=name)
     import pyarrow as pa,pyarrow.parquet as pq
     rows=retrieve(cfg,db,records,registry,reader);rows,_=EvalScreen(Path(cfg['eval_registry']),policy['evaluation']).filter(rows)
     known=sqlite3.connect('file:'+str(Path(cfg['database']))+'?mode=ro',uri=True)
     try:rows=[r for r in rows if not known.execute('SELECT 1 FROM documents WHERE body_sha=?',(r['normalized_sha256'],)).fetchone()]
     finally:known.close()
     if not rows or {r['split'] for r in rows}!={'train','validation','test'}:
      with db:db.execute("UPDATE jobs SET state='HOLD_ISOLATION' WHERE name=?",(name,));db.execute("UPDATE records SET gate='HOLD_ISOLATION' WHERE job=?",(name,))
      continue
     pq.write_table(pa.Table.from_pylist(rows),candidate,compression='zstd')
     frozen_write(batch/'CANDIDATE_BINDING.json',dict(teacher='qwen',teacher_registry_sha256=file_sha(Path(cfg['qwen_registry'])),
      candidate_sha256=file_sha(candidate),registry_sha256=file_sha(root/'REGISTRY.json'),source_id=source,domain=domain,language=lang,
      allocation_sha256=digest(sorted(r['h'] for r in records)),controller_sha256=file_sha(Path(__file__))))
     grouped=defaultdict(list)
     for r in rows:grouped[layer(r)].append(r)
     review=rows if mode=='individual' else [r for s in sorted(grouped) for r in sorted(grouped[s],key=lambda r:digest(['rolling-v11',r['normalized_sha256']]))[:8*perf['fast_batch_size_multiplier']]]
     make_batch(cfg,batch/'review',review,dict(kind='batch',mode=mode,candidate_sha256=file_sha(candidate),
      strata={r['normalized_sha256']:layer(r) for r in review},population={s:len(v) for s,v in grouped.items()},source_manifest_sha256=file_sha(src/'PLAN.json')))
     status('ROLLING_OR_COMPLETE_INDIVIDUAL_QA',cohort=cohort,job=name,mode=mode);score(batch/'review',a.deployment,a.gpu,'source_'+src.name)
     q=publication_quality(cfg,candidate,src,ref,batch/'review',mode)
     if q['status']!='passed':
      frozen_write(batch/'QUALITY_HOLD_V67.json',q)
      with db:db.execute("UPDATE jobs SET state='HOLD_QUALITY' WHERE name=?",(name,));db.execute("UPDATE records SET gate='HOLD_QUALITY' WHERE job=?",(name,))
      if mode=='source_audit':
       inspected=set(json.loads((batch/'review/PLAN.json').read_text())['body_ids'])
       with db:db.executemany("UPDATE records SET gate='CANDIDATE_FALLBACK',job=NULL WHERE h=? AND job=?",[(r['normalized_sha256'],name) for r in rows if r['normalized_sha256'] not in inspected])
      continue
     cfg_release=dict(cfg,_source=source);cp=batch/'RELEASE_CONFIG_V67.json';frozen_write(cp,cfg_release)
     status('FULL_DEDUP_EVAL_SPLIT_PACK_PHYSICAL_PUBLICATION',cohort=cohort,job=name)
     publish(cfg_release,cp,batch,src,ref,domain,mode,a.performance,out)
     ready=batch/'release/READY_INTERNAL.json';state='READY_INTERNAL' if ready.exists() else 'HOLD_PHYSICAL'
     with db:db.execute('UPDATE jobs SET state=? WHERE name=?',(state,name));db.execute('UPDATE records SET gate=? WHERE job=?',(state,name))
     if ready.exists():status('ACTUAL_READY_INTERNAL',cohort=cohort,job=name,train_body_tokens=json.loads(ready.read_text())['unique_train_body_tokens'])
     if mode=='source_audit':
      inspected=set(json.loads((batch/'review/PLAN.json').read_text())['body_ids'])
      with db:db.executemany("UPDATE records SET gate='CANDIDATE_FALLBACK',job=NULL WHERE h=? AND job=?",[(h,name) for h in set(q['excluded_ids'])-inspected])
    turn+=1
    if not progress and turn%4!=3:
     if turn%4==0:break
     continue
   status('SLOT_BOUNDED_RUN_COMPLETE',qualified_cohorts=len(qualified))
  except Exception as exc:
   status('SLOT_STOPPED_PRESERVE_UNKNOWN_NO_RETRY',error=type(exc).__name__,detail=str(exc)[-500:]);raise
  finally:db.close()
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--config',type=Path,required=True);p.add_argument('--deployment',type=Path,required=True)
 p.add_argument('--gpu',type=int,required=True);p.add_argument('--cohorts',nargs='+',required=True);p.add_argument('--performance',type=Path,required=True);a=p.parse_args()
 if a.gpu not in range(8) or len(set(a.cohorts))!=len(a.cohorts):raise ValueError('Authorized unique GPU/cohorts required')
 cfg=json.loads(a.config.read_text());root=Path(cfg['root']);out=root/'qwen_pool_v67'/f'gpu_{a.gpu}';out.mkdir(parents=True,exist_ok=True)
 if (out/'CONTINUATION_BINDING_V67.json').exists() or (out/'RUN_INTENT_V67.json').exists():raise ValueError('Existing v67 continuation: observe only, no repeat')
 frozen_write(out/'RUN_INTENT_V67.json',dict(started_unix=time.time(),engine_sha256=file_sha(Path(__file__)),gpu=a.gpu))
 frozen_write(out/'CONTINUATION_BINDING_V67.json',dict(version=67,engine_sha256=file_sha(Path(__file__)),config_sha256=file_sha(a.config),performance_sha256=file_sha(a.performance),teacher_registry_sha256=file_sha(Path(cfg['qwen_registry'])),gpu=a.gpu,cohorts=a.cohorts,train_split_reassigned=False,old_unknown_preserved=True))
 def status(stage,**kw):
  f=out/'STATUS_V67.json';t=f.with_suffix('.tmp');t.write_text(json.dumps(dict(version=67,stage=stage,updated_unix=time.time(),gpu=a.gpu,paid_api_requests=0,training_started=False,**kw),indent=2)+'\n');os.replace(t,f)
 try:
  with locked(out/'continuation.lock',seconds=1):
   old=command(['systemctl','--user','show',f'curation-qwen-overnight-v36-{a.gpu}.service','-p','ActiveState','--value']).strip()
   if old in ('active','activating'):raise ValueError('Old slot still running; no concurrent replacement')
   prior=command(['systemctl','--user','show',f'curation-qwen-continuation-v37-{a.gpu}.service','-p','ActiveState','--value']).strip()
   if prior in ('active','activating'):raise ValueError('Prior continuation still running; no concurrent replacement')
   prior39=command(['systemctl','--user','show',f'curation-qwen-continuation-v39-{a.gpu}.service','-p','ActiveState','--value']).strip()
   if prior39 in ('active','activating'):raise ValueError('Prior v39 still running; no concurrent replacement')
   for old_version in (42,44,48,55,58,61,65):
    oldunit=f'curation-qwen-continuation-v{old_version}-{a.gpu}.service'
    if command(['systemctl','--user','show',oldunit,'-p','ActiveState','--value']).strip() in ('active','activating'):raise ValueError('Prior continuation still active; no replacement')
   for oldunit in (f'curation-qwen-isolated-v46-{a.gpu}.service',f'curation-qwen-isolated-v59-{a.gpu}.service',f'curation-qwen-isolated-v63-{a.gpu}.service',f'curation-qwen-isolated-v64-{a.gpu}.service'):
    if command(['systemctl','--user','show',oldunit,'-p','ActiveState','--value']).strip() in ('active','activating'):raise ValueError('Prior isolated continuation active')
   a.deadline=time.monotonic()+12*3600
   for cohort in a.cohorts:
    if time.monotonic()>=a.deadline:break
    status('ADVANCING_UNALLOCATED_COHORT',cohort=cohort)
    child=argparse.Namespace(**vars(a));child.cohorts=[cohort]
    run_cohort(child)
   status('BOUNDED_CONTINUATION_COMPLETE')
 except Exception as exc:
  status('CONTINUATION_STOPPED_PRESERVE_UNKNOWN_NO_RETRY',error=type(exc).__name__,detail=str(exc)[-500:]);raise
if __name__=='__main__':main()
