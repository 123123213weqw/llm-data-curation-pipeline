#!/usr/bin/env python3
"""Independent local-Qwen audit worker, not a production failover controller.

Never changes DeepSeek receipts, starts GPUs, approves data, or retries attempts.
Run on the model host: teacher tokenizer/context admission is mandatory.
"""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
import fcntl
import json
from pathlib import Path
import sys
import time
from urllib.error import HTTPError
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent/'payload/code'
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'scripts')]
from small_agent.curation.core import canonical, fingerprint, validate_annotation, decoder_schema
from small_agent.curation.ledger import Ledger
from small_agent.curation.store_qwen_v35 import Batch, protocol
from small_agent.curation.evidence_ids_qwen_v35 import request_body, resolve, check_judge
from p0_curation_bounded_resume_v3 import recoverable
import p0_curation_worker_v3 as transport


def local_endpoint(judge):
    check_judge(judge)
    u = urlparse(judge['endpoint']['base_url'])
    if (u.scheme != 'http' or u.hostname != '127.0.0.1' or not u.port
            or u.username or u.password or u.query or u.fragment or u.path != '/v1'):
        raise ValueError('Only explicitly bound host-local Qwen endpoints are allowed')


def job_identity(base):
    return fingerprint(dict(purpose='local_qwen_source_quality_audit_v35',
                            judge='qwen', protocol=base))


def admitted(tokenizer, body, judge):
    n = transport.teacher_input_length(tokenizer, body['messages'],
                                      judge['generation']['chat_template_kwargs'])
    return n + judge['generation']['max_tokens'] + 256 <= judge['endpoint']['maximum_context_tokens']


def attempt(task, judge, prompt, schema, timeout):
    job, doc, body, base = task
    started = time.monotonic()
    result = dict(base, status='error', generated_at_unix=time.time(),
                  actual_request_sha256=fingerprint(body))
    try:
        response = transport.send(judge['endpoint']['base_url'], 'chat', body, '', timeout)
        result.update(usage=response.get('usage'), response_id=response.get('id'),
                      served_model=response.get('model'))
        if response.get('model') not in judge['served_models']:
            raise ValueError('Served model mismatch')
        wire = transport.extract(response, 'chat')
        result.update(wire_annotation=wire, raw_annotation=wire)
        label = resolve(wire, doc, schema, judge)
        result['raw_annotation'] = label
        validate_annotation(label, doc, decoder_schema(doc, schema, judge))
        result.update(status='ok', annotation=label,
                      conservative_keep_veto=wire['decision']=='keep' and label['decision']!='keep')
    except HTTPError as exc:
        result.update(http_status=exc.code, error='HTTP '+str(exc.code))
    except Exception as exc:
        result['error'] = type(exc).__name__
    result['latency_seconds'] = round(time.monotonic()-started, 6)
    return job, result


def run(batch, ledger_path, *, workers=4, limit=512, timeout=240):
    if not 1 <= workers <= 32 or not 1 <= limit <= 512:
        raise ValueError('Bounded local concurrency and batch size required')
    if batch.registry['deployment_status'] != 'verified':
        raise ValueError('Offline identities must not call a live model')
    judge = batch.registry['judges']['qwen']
    local_endpoint(judge)
    tokenizer = transport.tokenizer_for(judge)
    work = batch.root/'worker'/'qwen'
    work.mkdir(parents=True, exist_ok=True)
    pricing = dict(uncached_input=0, output=0, margin=1)
    files = [work/'worker.lock', Path(ledger_path).with_suffix('.local-qwen.lock')]
    handles = []
    try:
        for path in files:
            path.parent.mkdir(parents=True, exist_ok=True)
            f = path.open('a'); handles.append(f)
            fcntl.flock(f, fcntl.LOCK_EX|fcntl.LOCK_NB)
        ledger = Ledger(Path(ledger_path), budget_cny=0,
                        account_sha256=fingerprint(judge), pricing=pricing)
        try:
            if ledger.report()['requests_by_state'].get('inflight',0):
                raise ValueError('Unknown local inflight: inspect; never reissue')
            for row in ledger.db.execute('SELECT result_json FROM requests WHERE result_json IS NOT NULL'):
                r=json.loads(row[0])
                base={k:r[k] for k in ('source_id','text_sha256','prompt_sha256','schema_sha256','model',
                                      'temperature','inference_sha256','judge_identity_sha256','wire_schema_sha256') if k in r}
                if r.get('status')!='ok' and not recoverable(r,base,judge['served_models']):
                    raise ValueError('Unknown prior local result: inspect, not automatic retry')
            jobs=batch.pending('qwen')[:limit]
            counts=Counter(); reason=None; considered=0;latencies=[];input_tokens=0;output_tokens=0
            from engine import refill
            from common import pressure
            def prepare(j):
                nonlocal considered
                considered+=1
                doc=batch.docs[j['document_id']]
                base=protocol(doc,batch.prompt,batch.schema,judge);key=job_identity(base)
                cached=ledger.result(key)
                if cached is not None:
                    p=work/(key+'.jsonl');transport.write_receipt(p,cached)
                    batch.import_results('qwen',p);counts['reused_without_request']+=1
                    return None
                body=request_body(doc,batch.prompt,batch.schema,judge)
                if not admitted(tokenizer,body,judge):
                    counts['context_hold_no_truncation_no_request']+=1;return None
                if not ledger.reserve(key,0):raise ValueError('Unknown reservation; no replay')
                return (key,doc,body,base)
            def execute(task):return attempt(task,judge,batch.prompt,batch.schema,timeout)
            def finish(task,pair):
                nonlocal input_tokens,output_tokens
                key,result=pair
                latencies.append(result.get('latency_seconds',0));u=result.get('usage') or {}
                input_tokens+=u.get('prompt_tokens',0);output_tokens+=u.get('completion_tokens',0)
                ledger.finish(key,result,observed_cost_cny=0)
                p=work/(key+'.jsonl');transport.write_receipt(p,result)
                batch.import_results('qwen',p);counts['local_requests']+=1
                if result['status']=='ok':counts['valid_outputs']+=1;return True
                if recoverable(result,task[3],judge['served_models']):
                    counts['known_invalid_not_retried']+=1;return True
                return False
            measured=refill(jobs,prepare,execute,finish,workers,lambda:not pressure()['reasons'])
            reason=measured['stop_reason']
            measured.update(input_tokens=input_tokens,output_tokens=output_tokens,tokens_per_second=(input_tokens+output_tokens)/max(measured['elapsed_seconds'],1e-9),latencies_seconds=latencies)
            out=dict(version=129,original_protocol_version=35,scheduling=measured,stage='stopped_fail_closed' if reason else 'all_selected_attempted_with_holds',
                     stop_reason=reason,selected=len(jobs),considered=considered,counts=dict(counts),
                     batch=batch.report(),model=judge['model'],local_only=True,paid_api_requests=0,
                     full_document_only=True,training_approved=False,training_started=False)
            transport.atomic_status(work/'LOCAL_STATUS_V35.json',out)
            return out
        finally:ledger.close()
    finally:
        for f in handles:f.close()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--batch',type=Path,required=True)
    p.add_argument('--ledger',type=Path,required=True)
    p.add_argument('--allow-local',action='store_true')
    p.add_argument('--workers',type=int,default=4)
    p.add_argument('--limit',type=int,default=512)
    a=p.parse_args()
    if not a.allow_local:raise ValueError('Explicit local-model execution required')
    batch=Batch(a.batch)
    try:
        from urllib.request import urlopen
        j=batch.registry['judges']['qwen'];local_endpoint(j)
        with urlopen(j['endpoint']['base_url'].removesuffix('/v1')+'/health',timeout=8) as r:
            if r.status!=200:raise ValueError('Bound backend unhealthy')
        with urlopen(j['endpoint']['base_url']+'/models',timeout=8) as r:models=json.load(r)['data']
        if not any(m['id']==j['model'] and m['root']==j['endpoint']['teacher_tokenizer_directory'] and m['max_model_len']==j['endpoint']['maximum_context_tokens'] for m in models):
            raise ValueError('Real backend identity/root/context changed')
        result=run(batch,a.ledger,workers=a.workers,limit=a.limit)
    finally:batch.close()
    print(canonical(result))
    return 3 if result['stop_reason'] else 0


if __name__=='__main__':raise SystemExit(main())
