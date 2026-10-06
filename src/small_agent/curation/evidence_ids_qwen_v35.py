"""Offline candidate compact-64 wire protocol; unchanged full body and conservative grounding. Not quality-approved or production-enabled."""
import copy,json
from pathlib import Path
from jsonschema import Draft202012Validator
from .core import canonical,fingerprint,validate_annotation,span
from .supply_control import file_sha
from .literal_context_v6 import catalog

def extension():
    return dict(kind='local_qwen_evidence_ids_v35_compact64_conservative_veto',adapter_sha256=file_sha(Path(__file__)),catalog_sha256=file_sha(Path(__file__).with_name('literal_context_v6.py')),maximum_entries=64,candidate_entries=384,selection='uniform_endpoints_after_unique_grounding_v1')

def spans(doc):
    text=doc['document_text'];items=[]
    for i,q in enumerate(catalog(text)):
        try:location=span(text,q)
        except ValueError:continue # .count misses OVERLAPPING repeated occurrences.
        start=location['start'];items.append(dict(id='e'+str(i).zfill(3),start=start,end=start+len(q),text=q))
    if not items:raise ValueError('No uniquely grounded evidence; hold without API')
    if len(items)>64:
        items=[items[(len(items)-1)*i//63] for i in range(64)]
    return items

def check_judge(judge):
    g=judge['generation']
    if (g.get('evidence_id_transport')!=extension() or judge.get('family')!='qwen'
        or judge['endpoint']['kind']!='chat' or g.get('temperature')!=0
        or g.get('thinking')!='omit' or g.get('chat_template_kwargs')!={'enable_thinking':False}
        or g.get('decoder_schema_projection','identity') not in ('identity','omit_uniqueItems_v1')):
        raise ValueError('Frozen local Qwen chat identity/transport differs')

def project_schema(schema):
    if isinstance(schema,dict):return {k:project_schema(v) for k,v in schema.items() if k!='uniqueItems'}
    if isinstance(schema,list):return [project_schema(v) for v in schema]
    return schema

def wire_schema(doc,schema,judge):
    check_judge(judge);s=copy.deepcopy(schema);ids=[x['id'] for x in spans(doc)];p=s['properties']
    for key in ('document_id','body_sha256'):p[key]={'type':'string','const':doc[key]}
    p['anchors']['items']={'type':'string','enum':ids};p['anchors']['maxItems']=1
    p['findings']['items']['properties']['quotes']['items']={'type':'string','enum':ids}
    p['findings']['maxItems']=3
    return project_schema(s) if judge["generation"].get("decoder_schema_projection")=="omit_uniqueItems_v1" else s

def request_body(doc,prompt,schema,judge):
    check_judge(judge);payload=json.loads(doc['review_payload']);payload['evidence_spans']=spans(doc)
    g=judge['generation']
    return dict(model=judge['model'],messages=[dict(role='system',content=prompt),dict(role='user',content=canonical(payload))],
        temperature=g['temperature'],max_tokens=g['max_tokens'],stream=False,
        chat_template_kwargs=g['chat_template_kwargs'],
        response_format=dict(type='json_schema',json_schema=dict(name='quality_evidence_ids_qwen_v35_compact64',schema=wire_schema(doc,schema,judge))))

def resolve(raw,doc,schema,judge):
    Draft202012Validator(wire_schema(doc,schema,judge)).validate(raw)
    mapping={x['id']:x['text'] for x in spans(doc)};out=copy.deepcopy(raw)
    out['anchors']=[mapping[x] for x in raw['anchors']]
    for f in out['findings']:f['quotes']=[mapping[x] for x in f['quotes']]
    # Fail closed: contradictory KEEP can only become HOLD, never approval.
    if out['decision']=='keep' and any(f['severity'] in ('review','reject') for f in out['findings']):out['decision']='uncertain'
    validate_annotation(out,doc,schema) # Original full-body uniqueness remains mandatory.
    return out

def validate_receipt(result,doc,prompt,schema,judge):
    body=request_body(doc,prompt,schema,judge)
    if result.get('actual_request_sha256')!=fingerprint(body):raise ValueError('Actual request binding differs')
    normalized=resolve(result['wire_annotation'],doc,schema,judge)
    if normalized!=result.get('annotation') or normalized!=result.get('raw_annotation'):raise ValueError('Evidence resolver/decision was altered')
    return normalized
