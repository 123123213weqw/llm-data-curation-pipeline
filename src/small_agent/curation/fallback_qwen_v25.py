"""Read-only paid-budget admission. Never sends, retries, clears HOLDs or starts GPUs."""
import json
from pathlib import Path
import sqlite3

from .core import fingerprint
from .ledger import micros
from .supply_control import file_sha,digest
from .release_gates_v5 import bound_json,write


def campaign_snapshot(profile_path):
    profile=json.loads(Path(profile_path).read_text())
    if profile['campaign_budget_cny']!=1000:
        raise ValueError('Existing 1000 CNY campaign only; never increase budget')
    identity=fingerprint(dict(currency='CNY',cap_micros=micros(1000),
        account_sha256=profile['expected_key_sha256'],pricing=profile['pricing_cny_per_million']))
    db=sqlite3.connect('file:'+str(Path(profile['campaign_ledger']).resolve())+'?mode=ro',uri=True)
    try:
        db.execute('BEGIN')
        found=db.execute("SELECT value FROM meta WHERE key='identity'").fetchone()
        if found is None or found[0]!=identity:raise ValueError('Paid account/budget/pricing identity changed')
        rows=list(db.execute('SELECT job_key,reserved,counted,state,result_json FROM requests ORDER BY job_key'))
        total=0;unknown=[];errors=[]
        for job,reserved,counted,state,raw in rows:
            if type(counted) is not int or counted<0:raise ValueError('Invalid paid counted cost')
            total+=counted
            if state!='usage_estimated':unknown.append(digest(job));continue
            result=json.loads(raw) if raw else {}
            if result.get('status')=='ok':continue
            # A returned, billed, well-identified invalid label is not an unknown request.
            usage=result.get('usage') or {}
            known_invalid=(result.get('error') in ('ValueError','ValidationError') and isinstance(result.get('raw_annotation'),dict)) or result.get('error')=='JSONDecodeError'
            inp=usage.get('input_tokens',usage.get('prompt_tokens'));out=usage.get('output_tokens',usage.get('completion_tokens'))
            if not (known_invalid and result.get('response_id') and result.get('served_model')==profile['model']
                    and type(inp) is int and inp>=0 and type(out) is int and out>=0):
                errors.append(digest(job))
        return profile,dict(campaign_identity_sha256=identity,ledger_snapshot_sha256=digest(rows),
            counted_micros=total,cap_micros=micros(1000),remaining_micros=micros(1000)-total,
            requests=len(rows),unresolved_requests=len(unknown),unknown_or_fatal_outputs=len(errors))
    finally:db.close()


def next_reservation(profile,status_path,snapshot):
    """Confirm settled remainder cannot fund even ONE still-unsent eligible job.

    A large parallel window may have temporarily exhausted reservations while
    later completions free budget. That is NOT proof of campaign exhaustion.
    """
    from .store_v8 import Batch,protocol
    from .evidence_ids_v8 import request_body
    import p0_curation_worker_v3 as transport
    path=Path(status_path);status=json.loads(path.read_text());c=status['configuration']
    if status.get('stage')!='stopped_fail_closed' or status.get('stop_reason')!='budget_backpressure':
        raise ValueError('Only actual paid worker budget_backpressure evidence allowed')
    if (Path(c['campaign_ledger']).resolve()!=Path(profile['campaign_ledger']).resolve()
            or c['account_sha256']!=profile['expected_key_sha256']):
        raise ValueError('Paid stop belongs to another account/ledger')
    worker=Path(__file__).resolve().parents[3]/'scripts/p0_deepseek_worker_v8.py'
    if c['worker_sha256']!=file_sha(worker):raise ValueError('Paid worker implementation differs')
    batch=Batch(path.parents[2])
    try:
        if c['batch_manifest_sha256']!=batch.manifest_hash:raise ValueError('Paid stopped batch differs')
        judge=batch.registry['judges']['deepseek'];ep=judge['endpoint']
        if judge['model']!=profile['model'] or ep['pricing_cny_per_million']!=profile['pricing_cny_per_million']:
            raise ValueError('Stopped paid teacher/pricing differs')
        db=sqlite3.connect('file:'+str(Path(profile['campaign_ledger']).resolve())+'?mode=ro',uri=True)
        try:
            amounts=[]
            for job in batch.pending('deepseek'):
                doc=batch.docs[job['document_id']];base=protocol(doc,batch.prompt,batch.schema,judge)
                key=transport.job_identity(batch,'deepseek',base)
                if db.execute('SELECT 1 FROM requests WHERE job_key=?',(key,)).fetchone():continue
                body=request_body(doc,batch.prompt,batch.schema,judge)
                n=len(transport.canonical(body).encode('utf-8'))+4096
                if n>ep['maximum_input_tokens']:continue
                amounts.append(micros(transport.usage_cost(dict(input_tokens=n,output_tokens=judge['generation']['max_tokens']),ep['pricing_cny_per_million'])))
            return min(amounts) if amounts else None
        finally:db.close()
    finally:batch.close()


def assess(profile_path,status_path=None):
    profile,s=campaign_snapshot(profile_path)
    result=dict(version=25,snapshot=s,allowed=False,reason=None,paid_requests_sent=0,
                holds_cleared=0,services_started=0,production_switch_completed=False)
    if s['unresolved_requests'] or s['unknown_or_fatal_outputs']:
        result['reason']='unresolved_cost_or_unknown_output_not_exhaustion';return result
    if s['remaining_micros']<=0:
        result.update(allowed=True,reason='settled_campaign_cap_exhausted');return result
    if status_path is not None:
        # Check the inexpensive classification before opening the frozen batch.
        status=json.loads(Path(status_path).read_text())
        if status.get('stop_reason')=='budget_backpressure':
            bound=next_reservation(profile,status_path,s)
            result['minimum_unsent_reservation_micros']=bound
            if bound is not None and s['remaining_micros']<bound:
                # Snapshot must be stable across the paid-batch reading window.
                if campaign_snapshot(profile_path)[1]!=s:raise ValueError('Paid ledger changed during admission')
                result.update(allowed=True,reason='settled_remainder_cannot_fund_next_unsent_request')
                return result
            result['reason']='temporary_window_backpressure_or_no_eligible_jobs';return result
        result['reason']='non_budget_worker_stop_not_exhaustion';return result
    result['reason']='paid_budget_still_available';return result


def freeze_authorization(profile_path,output,status_path=None):
    result=assess(profile_path,status_path)
    if not result['allowed']:raise ValueError('Local fallback not authorized: '+result['reason'])
    files=[Path(__file__),Path(profile_path)]
    if status_path is not None:files.append(Path(status_path))
    receipt=dict(stage='PAID_CAMPAIGN_EXHAUSTED_LOCAL_FALLBACK_AUTHORIZED',assessment=result,
        paid_profile_path=str(Path(profile_path).resolve()),
        paid_status_path=str(Path(status_path).resolve()) if status_path is not None else None,
        evidence_files=[dict(path=str(p.resolve()),sha256=file_sha(p)) for p in files])
    write(output,receipt);return receipt


def validate_activation(path):
    r=bound_json(path)
    if r.get('stage')!='PAID_CAMPAIGN_EXHAUSTED_LOCAL_FALLBACK_AUTHORIZED':
        raise ValueError('Real settled paid-budget authorization required')
    current=assess(r['paid_profile_path'],r.get('paid_status_path'))
    if not current['allowed'] or current['snapshot']['campaign_identity_sha256']!=r['assessment']['snapshot']['campaign_identity_sha256']:
        raise ValueError('Fallback budget condition no longer satisfied')
    return current


def release_contract(cfg,candidate_binding,output):
    """Qwen cannot consume a DeepSeek candidate binding or existing old release."""
    if cfg.get('version')!=25 or cfg.get('teacher')!='qwen':raise ValueError('Explicit independent Qwen v25 configuration required')
    validate_activation(Path(cfg['activation_receipt']))
    h=file_sha(Path(cfg['qwen_registry']))
    if candidate_binding.get('teacher')!='qwen' or candidate_binding.get('teacher_registry_sha256')!=h:
        raise ValueError('Candidate must have independent frozen Qwen teacher binding')
    for name in ('INPUT_BINDING.json','READY_INTERNAL.json','RELEASE_INTENT.json'):
        path=Path(output)/name
        if path.exists():
            old=json.loads(path.read_text())
            if old.get('teacher')!='qwen' or old.get('teacher_registry_sha256')!=h:
                raise ValueError('Never reuse/overwrite old or different-teacher release output')
    return h
