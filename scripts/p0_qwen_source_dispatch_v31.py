#!/usr/bin/env python3
"""V100 -> owned L40 bounded source QA dispatch. No paid calls, no release, no HOLD clearing."""
import argparse,json,fcntl,subprocess,os,signal,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'src'),str(ROOT/'scripts')]
from small_agent.curation.supply_control import file_sha
from small_agent.curation.fallback_qwen_v25 import validate_activation
from small_agent.curation.store_qwen_v25 import Batch
from small_agent.curation.quality_qwen_v25 import reference_gate

SSH=['ssh','-o','BatchMode=yes','-o','ControlPath=none','-o','ConnectTimeout=8','GPU_WORKER']
SSH_TRANSPORT='ssh -o BatchMode=yes -o ControlPath=none -o ConnectTimeout=8'

def command(args,timeout=75):
    p=subprocess.Popen(list(map(str,args)),stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,start_new_session=True)
    try:out,_=p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(p.pid,signal.SIGKILL);out,_=p.communicate();raise TimeoutError('Transport outcome unknown; inspect unit/receipts before any retry')
    if p.returncode:raise RuntimeError('Transport/remote command failed: '+out[-1000:])
    return out


def frozen_write(path,data):
    if path.exists():
        if json.loads(path.read_text())!=data:raise ValueError('Frozen dispatch receipt differs')
    else:
        with path.open('x') as f:json.dump(data,f,indent=2,sort_keys=True);f.write('\n')


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--curation-root',type=Path,required=True)
    p.add_argument('--deployment',type=Path,required=True);a=p.parse_args()
    R=a.curation_root;out=R/'full_inventory_v11/qwen_fallback_v31';out.mkdir(exist_ok=True)
    auth=R/'full_inventory_v11/qwen_fallback_v25/PAID_BUDGET_AUTHORIZATION_V25.json'
    policy=json.loads((ROOT/'configs/curation/p0_release_gates_v5.json').read_text())['quality']
    references=R/'references/qwen_fallback_v25/references'
    with (out/'dispatch-v31.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        def status(stage,**kw):
            path=out/'SOURCE_DISPATCH_STATUS_V31.json';temp=path.with_suffix('.tmp')
            temp.write_text(json.dumps(dict(version=31,stage=stage,updated_unix=time.time(),paid_api_requests=0,production_switch_completed=False,**kw),sort_keys=True,indent=2)+'\n');os.replace(temp,path)
        if (out/'SOURCE_DISPATCH_LAUNCHED_V31.json').exists():
            print('EXISTING_DISPATCH_NO_DUPLICATE');return
        deadline=time.monotonic()+7200
        preparation=out/'SOURCE_PREPARATION_V31.json'
        while not preparation.exists():
            active=command(['systemctl','--user','show','curation-qwen-source-prepare-v31.service','-p','ActiveState','--value']).strip()
            if active not in ('active','activating') or time.monotonic()>deadline:raise ValueError('Source preparation stopped/missing; inspect rather than rerun')
            status('WAITING_SOURCE_PREPARATION');time.sleep(30)
        prep=json.loads(preparation.read_text());cfg=json.loads((out/'SOURCE_PREPARATION_CONFIG_V31.json').read_text())
        while True:
            command(['rsync','-a','--include=/general_en_en/','--include=/general_zh_zh/','--include=/technical_en/',
                '--include=/*/batch/','--include=/*/batch/worker/','--include=/*/batch/worker/qwen/',
                '--include=/*/batch/worker/qwen/*.jsonl','--include=/*/batch/worker/qwen/LOCAL_STATUS_V25.json','--exclude=*',
                '-e',SSH_TRANSPORT,'GPU_WORKER:'+str(a.deployment/'references')+'/',str(references)+'/'])
            gates={};terminal=[]
            for name in ('general_en_en','general_zh_zh','technical_en'):
                folder=references/name;b=Batch(folder/'batch')
                try:
                    for path in sorted((folder/'batch/worker/qwen').glob('*.jsonl')):b.import_results('qwen',path)
                finally:b.close()
                gates[name]=reference_gate(folder,json.loads((folder/'labels.json').read_text()),policy)
                terminal.append((folder/'batch/worker/qwen/LOCAL_STATUS_V25.json').exists())
            if all(terminal):break
            if time.monotonic()>deadline:raise ValueError('Reference testing timeout; no source dispatch')
            status('WAITING_INDEPENDENT_REFERENCE',gates=gates);time.sleep(45)
        if any(g['status']!='passed' for g in gates.values()):
            status('INDEPENDENT_REFERENCE_HOLD_NO_SOURCE_DISPATCH',gates=gates);return
        assessment=validate_activation(auth)
        refnames={'general_zh':'general_zh_zh','technical':'technical_en','general_en':'general_en_en'}
        cohorts=[]
        for row in prep['cohorts']:
            domain=row['cohort'].split('/')[1];source_folder=Path(row['folder'])
            cohorts.append(dict(row,key=source_folder.name,reference_cohort=refnames[domain],independent_reference_gate=gates[refnames[domain]]))
        job=dict(version=31,scope='source_calibration_only_no_publication',cohorts=cohorts,
            budget_assessment=assessment,authorization_sha256=file_sha(auth),
            teacher_registry_sha256=prep['teacher_registry_sha256'],source_preparation_sha256=file_sha(preparation),
            independent_quality_policy_sha256=file_sha(ROOT/'configs/curation/p0_release_gates_v5.json'),
            paid_extra_budget_cny=0,production_switch_completed=False,engine_sha256=file_sha(Path(__file__)))
        jp=out/'SOURCE_JOB_V31.json';frozen_write(jp,job)
        command(SSH+['mkdir -p '+str(a.deployment/'source_audits_v31')+' '+str(a.deployment/'state')])
        command(['rsync','-a','--ignore-existing','-e',SSH_TRANSPORT,str(out/'source_audits')+'/',
            'GPU_WORKER:'+str(a.deployment/'source_audits_v31')+'/'],timeout=180)
        command(['rsync','-a','--ignore-existing','-e',SSH_TRANSPORT,str(jp),
            'GPU_WORKER:'+str(a.deployment/'state/SOURCE_JOB_V31.json')])
        command(['rsync','-a','--ignore-existing','-e',SSH_TRANSPORT,str(ROOT/'scripts/p0_qwen_source_queue_v31.py'),
            'GPU_WORKER:'+str(a.deployment/'code/scripts/p0_qwen_source_queue_v31.py')])
        # Verify remote registry, every portable Batch and live independent reference state before launch.
        remote_python='/srv/curation/venv/bin/python'
        verify="cd "+str(a.deployment/'code')+"; "+remote_python+" -c \"import sys,json;from pathlib import Path;sys.path[:0]=['src','scripts'];from p0_qwen_source_queue_v31 import verify_job;verify_job(Path('"+str(a.deployment)+"'),json.loads(Path('"+str(a.deployment/'state/SOURCE_JOB_V31.json')+"').read_text()));print('VERIFIED_SOURCE_QA_JOB')\""
        command(SSH+[verify])
        status('SOURCE_QA_LAUNCH_INTENT',job_sha256=file_sha(jp),quality_gates=gates)
        launch=f'''set -e; D={a.deployment}; if test -f "$D/state/SOURCE_QUEUE_STATUS_V31.json"; then echo EXISTING_STATUS_NO_DUPLICATE; elif systemctl --user show curation-qwen-source-qa-v31.service -p LoadState --value | grep -qx loaded; then echo EXISTING_UNIT_NO_DUPLICATE; else systemd-run --user --unit=curation-qwen-source-qa-v31 --property=Type=oneshot --property=TimeoutStartSec=12h --property=WorkingDirectory="$D/code" --property=CPUQuota=200% --property=MemoryMax=8G --setenv=CUDA_VISIBLE_DEVICES= {remote_python} -u scripts/p0_qwen_source_queue_v31.py --deployment "$D" --job "$D/state/SOURCE_JOB_V31.json" --ledger "$D/state/local_qwen_source_v31.sqlite"; fi; systemctl --user show curation-qwen-source-qa-v31.service -p LoadState -p ActiveState -p MainPID'''
        observed=command(SSH+[launch],timeout=45)
        frozen_write(out/'SOURCE_DISPATCH_LAUNCHED_V31.json',dict(version=31,job_sha256=file_sha(jp),observed_start_response=observed,
            paid_api_requests=0,production_switch_completed=False,training_approved=False))
        status('SOURCE_QA_DISPATCH_OBSERVED_NOT_PRODUCTION_RELEASE',observed=observed)
if __name__=='__main__':main()
