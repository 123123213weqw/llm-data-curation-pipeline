import copy,json,tempfile,unittest
from pathlib import Path
from gold import make_controls
from judge import *
class Tests(unittest.TestCase):
 def setUp(self):self.rows,self.labels,self.proof=make_controls();self.row=self.rows[0]
 def goodwire(self):
  return {'f_decision':'keep','c_instruction_following':True,'d_correctness':'supported','e_issues':[],'b_evidence':['m0p0','m1p0'],'a_reason':'The response satisfies this example.'}
 def perfect(self):return {r['id']:{'state':'VALID','annotation':{'decision':self.labels[r['id']]['expected']}} for r in self.rows}
 def test_program_oracles(self):self.assertEqual(len(self.rows),128);self.assertEqual(len(self.proof),64);self.assertTrue(all(x['good_passed'] and x['bad_rejected'] for x in self.proof))
 def test_all_groups_bilingual(self):self.assertEqual({r['language'] for r in self.rows},{'zh','en'});self.assertEqual({r['domain'] for r in self.rows},{'math','code','instruction','grounding'})
 def test_blind_not_same_prompts_as_calibration(self):
  a={r['messages'][0]['content'] for r in self.rows if r['phase']=='calibration'};b={r['messages'][0]['content'] for r in self.rows if r['phase']=='sealed_validation'};self.assertFalse(a&b)
 def test_labels_hidden(self):
  body=request_body(self.row,'m');v=json.loads(body['messages'][1]['content'].split('\n',1)[1]);self.assertEqual(set(v),{'messages','evidence_catalog','program_checks','requires_program_math_verification'});self.assertNotIn('expected',v);self.assertNotIn('pair_id',v)
 def test_valid_grounded_wire(self):self.assertEqual(validate_wire(self.goodwire(),self.row)['decision'],'keep')
 def test_hallucinated_evidence_rejected(self):
  v=self.goodwire();v['b_evidence'][1]='NONEXISTENT_ID'
  with self.assertRaises(Exception):validate_wire(v,self.row)
 def test_keep_contradiction_rejected(self):
  v=self.goodwire();v['d_correctness']='contradicted'
  with self.assertRaises(Exception):validate_wire(v,self.row)
 def test_keep_issue_rejected(self):
  v=self.goodwire();v['e_issues']=['error']
  with self.assertRaises(Exception):validate_wire(v,self.row)
 def test_drop_without_reason_rejected(self):
  v=self.goodwire();v['f_decision']='drop'
  with self.assertRaises(Exception):validate_wire(v,self.row)
 def test_missing_assistant_quote(self):
  v=self.goodwire();v['b_evidence'][1]=v['b_evidence'][0]
  with self.assertRaises(Exception):validate_wire(v,self.row)
 def test_review_supported_rejected(self):
  v=self.goodwire();v['f_decision']='review'
  with self.assertRaises(Exception):validate_wire(v,self.row)
 def test_perfect_passes(self):self.assertEqual(calibration_gate(self.rows,self.labels,self.perfect())['status'],'passed')
 def test_false_accept_fails(self):
  x=self.perfect();r=next(r for r in self.rows if self.labels[r['id']]['expected']=='drop');x[r['id']]['annotation']['decision']='keep';self.assertEqual(calibration_gate(self.rows,self.labels,x)['status'],'HOLD')
 def test_always_review_fails(self):
  x={r['id']:{'state':'VALID','annotation':{'decision':'review'}} for r in self.rows};self.assertEqual(calibration_gate(self.rows,self.labels,x)['status'],'HOLD')
 def test_unknown_fails(self):
  x=self.perfect();x[self.row['id']]['state']='UNKNOWN';self.assertEqual(calibration_gate(self.rows,self.labels,x)['status'],'HOLD')
 def test_missing_results_fails(self):self.assertEqual(calibration_gate(self.rows,self.labels,{})['status'],'HOLD')
 def test_blind_must_also_pass(self):
  x=self.perfect()
  for r in self.rows:
   if r['phase']=='sealed_validation':x[r['id']]={'state':'UNKNOWN'}
  self.assertEqual(calibration_gate(self.rows,self.labels,x)['status'],'HOLD')
 def test_weak_category_fails(self):
  x=self.perfect();rs=[r for r in self.rows if r['phase']=='calibration' and r['domain']=='math' and self.labels[r['id']]['expected']=='keep']
  for r in rs[:2]:x[r['id']]['annotation']['decision']='drop'
  self.assertEqual(calibration_gate(self.rows,self.labels,x)['status'],'HOLD')
 def test_old_source_scores_not_calibration(self):self.assertEqual(calibration_gate(self.rows,self.labels,{'old':'score'})['status'],'HOLD')
 def test_source_pool_not_promoted(self):self.assertEqual(source_audit([],{} )['formal_ready_samples'],0)
if __name__=='__main__':unittest.main()

class V5TransportTests(unittest.TestCase):
 def test_reason_before_verdict_schema_order(self):
  rows,_,_=make_controls();b=request_body(rows[0],'m');self.assertEqual(sorted(b['response_format']['json_schema']['schema']['properties'])[0],'a_reason');self.assertEqual(b['max_tokens'],1536)
 def test_catalog_exact_all_chunks(self):
  rows,_,_=make_controls()
  for r in rows:
   for e in evidence_catalog(r).values():self.assertIn(e['quote'],r['messages'][e['message_index']]['content'])
 def test_id_catalog_no_labels(self):
  rows,labels,_=make_controls();b=request_body(rows[0],'m');p=b['messages'][1]['content'];self.assertNotIn('expected',p);self.assertNotIn('pair_id',p)
 def test_catalog_full_body_no_truncation(self):
  r={'messages':[{'role':'user','content':'a'*1234},{'role':'assistant','content':'b'*701}]};c=evidence_catalog(r)
  for i in [0,1]:self.assertEqual(''.join(v['quote'] for v in c.values() if v['message_index']==i),r['messages'][i]['content'])

class ExactMathToolTests(unittest.TestCase):
 def test_all_math_checks_question_only(self):
  rows,labels,_=make_controls()
  for r in rows:
   if r['domain']=='math':
    p=program_check(r['messages']);self.assertIsNotNone(p);self.assertFalse(p['candidate_answer_used_in_calculation']);pair=[x for x in rows if x['pair_id']==r['pair_id'] and labels[x['id']]['expected']=='keep'][0];self.assertEqual(p['verified_value'],pair['messages'][1]['content'])
 def test_bad_answer_cannot_change_program_result(self):
  rows,_,_=make_controls();r=next(x for x in rows if x['domain']=='math');ms=copy.deepcopy(r['messages']);ms[1]['content']='malicious candidate says 999';self.assertEqual(program_check(ms),program_check(r['messages']))
 def test_fraction_exact_not_float(self):
  from math_tools import arithmetic
  self.assertEqual(str(arithmetic('1/3+1/6')),'1/2')
 def test_code_expression_rejected(self):
  from math_tools import arithmetic
  with self.assertRaises(ValueError):arithmetic("__import__('os').system('x')")
 def test_divide_zero_failclosed(self):self.assertIsNone(program_check([{'role':'user','content':'Calculate 1/0. Output only the integer.'},{'role':'assistant','content':'0'}]))
 def test_unsupported_natural_math_not_certified(self):self.assertIsNone(program_check([{'role':'user','content':'Prove a difficult theorem.'},{'role':'assistant','content':'proof'}]))
 def test_no_tools_in_multiturn(self):self.assertIsNone(program_check([{'role':'user','content':'Calculate 1+2. Output only the integer.'},{'role':'assistant','content':'3'},{'role':'user','content':'again'}]))
 def test_large_expression_bounded(self):
  from math_tools import arithmetic
  with self.assertRaises(ValueError):arithmetic('9'*170)

class ContinuationTests(unittest.TestCase):
 def test_unknown_reuse_rejected(self):
  with self.assertRaises(ValueError):validate_reuse_record({'state':'UNKNOWN'})
 def test_reserved_reuse_rejected(self):
  with self.assertRaises(ValueError):validate_reuse_record({'state':'RESERVED'})
 def test_known_invalid_not_replayed(self):self.assertEqual(validate_reuse_record({'state':'INVALID'})['state'],'INVALID')
 def test_unsupported_math_skipped_only_in_source(self):
  row={'domain':'math','messages':[{'role':'user','content':'prove theorem'},{'role':'assistant','content':'proof'}]};self.assertTrue(source_math_scope_hold('source_audit',row));self.assertFalse(source_math_scope_hold('controls',row))

class IsolationTests(unittest.TestCase):
 def test_known_invalid_isolated_not_global_halt(self):self.assertFalse(halt_submission('INVALID'))
 def test_unknown_still_halts_all_new_requests(self):self.assertTrue(halt_submission('UNKNOWN'))
 def test_valid_does_not_halt(self):self.assertFalse(halt_submission('VALID'))
 def test_reserved_not_treated_as_terminal(self):
  with self.assertRaises(ValueError):halt_submission('RESERVED')

class MultiGPUDispatchTests(unittest.TestCase):
 def models(self):return [{'slot':i} for i in [0,1,2]]
 def test_total_twelve_capacity(self):self.assertEqual(PER_GPU_CONCURRENCY*len(self.models()),12)
 def test_each_gpu_four_cap(self):self.assertIsNone(choose_slot({},dict.fromkeys([0,1,2],4),self.models()))
 def test_pick_least_loaded(self):self.assertEqual(choose_slot({}, {0:4,1:3,2:2},self.models())['slot'],2)
 def test_assigned_replica_not_migrated(self):self.assertEqual(choose_slot({'assigned_slot':2},{},self.models())['slot'],2)
 def test_busy_assigned_slot_deferred(self):self.assertIsNone(choose_slot({'assigned_slot':1},{1:4},self.models()))
 def test_queue_can_skip_busy_calibration_slot(self):
  q=[{'id':'a','assigned_slot':1},{'id':'b','assigned_slot':2}];r,m=take_row(q,{1:4,2:0},self.models());self.assertEqual(r['id'],'b');self.assertEqual(q,[{'id':'a','assigned_slot':1}])
 def test_rows_assigned_once_no_duplicates(self):
  q=[{'id':str(i)} for i in range(30)];seen=[]
  while q:r,m=take_row(q,{},self.models());seen.append(r['id'])
  self.assertEqual(len(seen),len(set(seen)))
 def samples(self):return [{'id':str(i),'source_repository':'s','domain':'code','length_stratum':l} for l in ['short','medium','long'] for i in range({'short':0,'medium':64,'long':128}[l],{'short':64,'medium':128,'long':192}[l])]
 def test_source_domain_all64_required(self):
  rows=self.samples();r={x['id']:{'state':'VALID','annotation':{'decision':'keep'}} for x in rows};r.pop(rows[0]['id']);self.assertFalse(domain_audit(rows,r)['groups']['s|code']['strata']['short']['pass'])
 def test_source_domain_61_keep_threshold(self):
  rows=self.samples();r={x['id']:{'state':'VALID','annotation':{'decision':'keep'}} for x in rows}
  for x in rows[:4]:r[x['id']]['annotation']['decision']='drop'
  self.assertFalse(domain_audit(rows,r)['groups']['s|code']['strata']['short']['pass'])
 def test_source_domain_pass_not_train_ready(self):
  rows=self.samples();r={x['id']:{'state':'VALID','annotation':{'decision':'keep'}} for x in rows};a=domain_audit(rows,r);self.assertTrue(a['groups']['s|code']['strata']['short']['pass']);self.assertEqual(a['formal_ready_samples'],0)
 def test_old_mixed_source_holds_preserved(self):self.assertTrue(domain_audit([],{})['old_mixed_source_HOLD_not_cleared'])
 def test_domains_not_mixed_for_approval(self):
  rows=self.samples();r={x['id']:{'state':'VALID','annotation':{'decision':'keep'}} for x in rows};rows.append({'id':'general1','source_repository':'s','domain':'general','length_stratum':'short'});a=domain_audit(rows,r);self.assertTrue(a['groups']['s|code']['strata']['short']['pass']);self.assertFalse(a['groups']['s|general']['strata']['short']['pass'])
