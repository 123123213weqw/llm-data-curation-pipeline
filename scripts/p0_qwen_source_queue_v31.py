#!/usr/bin/env python3
"""Local source calibration only. Real independent references required; no publishing or GPU setup."""
import argparse,json,fcntl,sys,os,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'src'),str(ROOT/'scripts')]
from small_agent.curation.store_qwen_v25 import Batch,file_sha
from p0_qwen_worker_v25 import run


def verify_job(deployment,job):
    if job.get('version')!=31 or job.get('scope')!='source_calibration_only_no_publication':raise ValueError('Explicit source-only job required')
    s=job['budget_assessment']['snapshot']
    if not job['budget_assessment']['allowed'] or s['cap_micros']!=1000000000 or s['unresolved_requests'] or s['unknown_or_fatal_outputs']:raise ValueError('Paid budget authorization not settled')
    if job.get('paid_extra_budget_cny')!=0 or job.get('production_switch_completed') is not False:raise ValueError('No paid extension or inferred production switch')
    registry=deployment/'identity32k/qwen_registry_v25.json'
    if file_sha(registry)!=job['teacher_registry_sha256']:raise ValueError('Source teacher registry changed')
    for row in job['cohorts']:
        gate=row['independent_reference_gate']
        if gate['status']!='passed' or gate['holds'] or gate['counts']['drop_keep']!=0:raise ValueError('Independent reference is HOLD')
        ref=Batch(deployment/'references'/row['reference_cohort']/'batch')
        try:
            if ref.manifest_hash!=gate['batch_manifest_sha256'] or ref.state_fingerprint()!=gate['review_state_sha256']:raise ValueError('Live reference state differs from approved proof')
        finally:ref.close()
        b=Batch(deployment/'source_audits_v31'/row['key']/'batch')
        try:
            if b.manifest_hash!=row['manifest_sha256'] or b.registry!=json.loads(registry.read_text()):raise ValueError('Source batch identity changed')
        finally:b.close()
    return True


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--deployment',type=Path,required=True)
    p.add_argument('--job',type=Path,required=True);p.add_argument('--ledger',type=Path,required=True);a=p.parse_args()
    job=json.loads(a.job.read_text());verify_job(a.deployment,job)
    state=a.deployment/'state';state.mkdir(exist_ok=True)
    def status(stage,**kw):
        path=state/'SOURCE_QUEUE_STATUS_V31.json';tmp=path.with_suffix('.tmp')
        tmp.write_text(json.dumps(dict(version=31,stage=stage,job_sha256=file_sha(a.job),engine_sha256=file_sha(Path(__file__)),
            updated_unix=time.time(),paid_api_requests=0,training_approved=False,production_switch_completed=False,**kw),sort_keys=True,indent=2)+'\n');os.replace(tmp,path)
    with (state/'source-queue-v31.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        completed=[]
        for row in job['cohorts']:
            status('SOURCE_CALIBRATION_SCORING',cohort=row['cohort'],completed_cohorts=completed)
            b=Batch(a.deployment/'source_audits_v31'/row['key']/'batch')
            try:result=run(b,a.ledger,workers=2,limit=512)
            finally:b.close()
            if result['stop_reason']:
                status('STOPPED_FAIL_CLOSED',cohort=row['cohort'],reason=result['stop_reason'],completed_cohorts=completed);return 3
            completed.append(row['cohort'])
        status('SOURCE_CALIBRATION_ATTEMPTED_NOT_PUBLICATION',completed_cohorts=completed)
    return 0
if __name__=='__main__':raise SystemExit(main())
