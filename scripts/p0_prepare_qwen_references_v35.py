#!/usr/bin/env python3
"""CPU-only preparation of independent Qwen controls; never invokes a teacher.

Uses the independent compact64 transport/checker. Math reuses independently checked text,
gold labels and arithmetic proofs ONLY, never old teacher scores or SQLite.
Code controls are checked with the existing syntax parser, not compilation.
"""
from __future__ import annotations
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'src'),str(ROOT/'scripts')]
from small_agent.curation import quality_qwen_v35 as quality
from small_agent.curation.core import sha
from small_agent.curation.store_qwen_v35 import Batch
from small_agent.curation.release_gates_v5 import bound_json,write
from small_agent.curation.supply_control import file_sha
import p0_math_reference_v6 as arithmetic_checker


def negative_body(positive,steps,offset=10000):
    text=positive
    for s in steps:
        text=text.replace('<<'+s['expression']+'='+s['result']+'>>',
                          '<<'+s['expression']+'='+str(arithmetic_checker.arithmetic(s['expression'])+offset)+'>>')
    return text+'\nCalculation summary (claimed results):\n'+'\n'.join(
        s['expression']+' = '+str(arithmetic_checker.arithmetic(s['expression'])+offset) for s in steps)+'\n'


def verify_math(rows,labels,proof):
    ids=[r['document_id'] for r in rows];label_ids=[r['document_id'] for r in labels]
    if len(set(ids))!=len(ids) or len(set(label_ids))!=len(label_ids) or set(ids)!=set(label_ids):
        raise ValueError('One independent label per exact math body required')
    docs={r['document_id']:r for r in rows};checks={r['source_row']:r for r in proof['checks']}
    pairs={};counts={'keep':0,'drop':0}
    for label in labels:
        d=docs[label['document_id']];kind=label['expected'];row=label['source_row']
        if kind not in counts or sha(d['document_text'])!=d['document_id']:
            raise ValueError('Independent math body/label changed')
        if d['family_id']!=sha('gsm8k:'+str(row)) or d['language']!='en':
            raise ValueError('Independent math source/family changed')
        if kind in pairs.setdefault(row,{}):raise ValueError('Duplicate class in reference pair')
        pairs[row][kind]=d['document_text'];counts[kind]+=1
    if set(pairs)!=set(checks) or any(set(p)!= {'keep','drop'} for p in pairs.values()):
        raise ValueError('Arithmetic proof/pair coverage differs')
    for row,pair in pairs.items():
        steps=arithmetic_checker.verified_steps(pair['keep'])
        if steps!=checks[row]['verified_annotated_steps'] or checks[row]['negative_offset']!=10000:
            raise ValueError('Independent exact arithmetic proof differs')
        if pair['drop']!=negative_body(pair['keep'],steps):
            raise ValueError('Negative is not the exact bound controlled contradiction')
        try:arithmetic_checker.verified_steps(pair['drop'])
        except ValueError as e:
            if str(e)!='annotated arithmetic not exact':raise
        else:raise ValueError('Negative arithmetic control is not incorrect')
    return dict(counts=counts,verified_pairs=len(pairs),passed=True,
                scope='annotated arithmetic and controlled contradictions only; not natural-document fact certification')


def prepare_code(cfg,target,language):
    rows,labels,proof=quality.control_rows('code',language)
    meta=dict(kind='reference',domain='code',language=language,independent=True,
              strata={r['normalized_sha256']:r['domain']+'/'+r['language'] for r in rows})
    plan=quality.make_batch(cfg,target,rows,meta)
    write(target/'labels.json',labels);write(target/'verification.json',proof)
    marker=dict(version=35,domain='code',language=language,training_eligible=False,
                natural_corpus_factual_error_rate_certified=False,
                checker_sha256=file_sha(Path(quality.__file__)),
                evidence_files=[dict(path=str(p.resolve()),sha256=file_sha(p)) for p in
                                (target/'PLAN.json',target/'labels.json',target/'verification.json')])
    write(target/'REFERENCE_QWEN_V35.json',marker)
    gate=quality.reference_gate(target,labels,json.loads(Path(cfg['release_policy']).read_text())['quality'])
    return dict(domain='code',language=language,documents=len(rows),gate=gate,
                manifest_sha256=file_sha(target/'batch/MANIFEST.json'),model_calls=0)


def prepare_math(cfg,source,target):
    ref=bound_json(source/'REFERENCE.json')
    if (ref.get('training_eligible') is not False or not ref.get('independently_verified_arithmetic_steps')
            or ref['checker_sha256']!=file_sha(Path(arithmetic_checker.__file__))):
        raise ValueError('Bound independently verified original arithmetic reference required')
    rows=[json.loads(line) for line in (source/'input.jsonl').read_text().splitlines() if line.strip()]
    labels=json.loads((source/'labels.json').read_text());proof=json.loads((source/'verification.json').read_text())
    check=verify_math(rows,labels,proof)
    if min(check['counts'].values())<16:raise ValueError('Independent reference classes insufficient')
    converted=[dict(normalized_sha256=r['document_id'],text=r['document_text'],source_id=r['source_id'],
                    source_locator=r['source_locator'],source_revision=r['source_revision'],family_id=r['family_id'],
                    language='en',domain='math',own_text_tokens=r['token_count']) for r in rows]
    meta=dict(kind='reference',domain='math',language='en',independent=True,
              original_gold_input_sha256=file_sha(source/'input.jsonl'),
              original_gold_labels_sha256=file_sha(source/'labels.json'),
              strata={r['document_id']:r['sampling_stratum'] for r in rows})
    quality.make_batch(cfg,target,converted,meta)
    b=Batch(target/'batch')
    try:
        if set(b.docs)!={r['document_id'] for r in rows}:raise ValueError('Frozen teacher reference IDs changed')
    finally:b.close()
    write(target/'labels.json',labels);write(target/'verification.json',proof)
    write(target/'CPU_INDEPENDENT_MATH_RECHECK_V35.json',check)
    marker=dict(version=35,domain='math',language='en',training_eligible=False,
                independently_verified_arithmetic_steps=True,natural_corpus_factual_error_rate_certified=False,
                source_file=ref['source_file'],limits=ref['limits'],checker_sha256=file_sha(Path(arithmetic_checker.__file__)),
                qwen_teacher_registry_sha256=file_sha(Path(cfg['qwen_registry'])),
                teacher_scores_reused=False,preparation_sha256=file_sha(Path(__file__)),
                evidence_files=[dict(path=str(p.resolve()),sha256=file_sha(p)) for p in
                                (source/'REFERENCE.json',source/'input.jsonl',source/'labels.json',source/'verification.json',
                                 target/'PLAN.json',target/'labels.json',target/'verification.json',
                                 target/'CPU_INDEPENDENT_MATH_RECHECK_V35.json')])
    write(target/'REFERENCE.json',marker)
    gate=quality.reference_gate(target,labels,json.loads(Path(cfg['release_policy']).read_text())['quality'])
    return dict(domain='math',language='en',documents=len(rows),independent_recheck=check,gate=gate,
                manifest_sha256=file_sha(target/'batch/MANIFEST.json'),model_calls=0)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--config',type=Path,required=True)
    p.add_argument('--output-root',type=Path,required=True);p.add_argument('--math-source',type=Path)
    p.add_argument('--code-languages',nargs='*',default=[]);a=p.parse_args()
    cfg=json.loads(a.config.read_text())
    if cfg.get('reference_only') is not True or cfg.get('teacher')!='qwen' or cfg.get('auto_training') is not False:
        raise ValueError('Explicit Qwen reference-only CPU configuration required')
    out=[]
    for language in a.code_languages:
        out.append(prepare_code(cfg,a.output_root/('code_'+language),language))
        print(json.dumps(out[-1]),flush=True)
    if a.math_source:
        out.append(prepare_math(cfg,a.math_source,a.output_root/'math_en'))
        print(json.dumps(out[-1]),flush=True)
    print(json.dumps(dict(stage='CPU_REFERENCE_PREPARATION_ONLY',cohorts=len(out),model_calls=0,quality_approved=False)),flush=True)
if __name__=='__main__':main()
