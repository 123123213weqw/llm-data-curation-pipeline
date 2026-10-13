"""Program-verified bilingual judge controls, not training data or benchmark answers."""
import hashlib,json,random,re
from fractions import Fraction
from pathlib import Path

def canon(x):return json.dumps(x,sort_keys=True,ensure_ascii=False,separators=(',',':'))
def fp(x):return hashlib.sha256(canon(x).encode()).hexdigest()
def make_controls():
 rows=[];labels={};proof=[]
 for phase,offset in [('calibration',5000),('sealed_validation',6000)]:
  for lang in ['en','zh']:
   for domain in ['math','code','instruction','grounding']:
    for v in range(4):
     n=13+offset+v*7+(3 if lang=='zh' else 0)
     if domain=='math':
      a,b,c=n,n+3,2+v
      if v==0:
       expected=str((a+b)*c);bad=str(int(expected)+1);q=(f'Calculate ({a}+{b})*{c}. Output only the integer.' if lang=='en' else f'计算({a}+{b})*{c}，只输出整数，不加解释。');check={'integer_oracle':(a+b)*c}
      elif v==1:
       val=Fraction(a,b)+Fraction(c,b+2);expected=str(val.numerator)+'/'+str(val.denominator);bad=str(val.numerator+1)+'/'+str(val.denominator);q=(f'Compute {a}/{b}+{c}/{b+2}. Output only the reduced numerator/denominator.' if lang=='en' else f'计算{a}/{b}+{c}/{b+2}，只输出最简分数分子/分母。');check={'fraction_cross_product':(a*(b+2)+c*b),'denominator_product':b*(b+2),'fraction_expected':expected}
      elif v==2:
       expected=str(a*c-b);bad=str(int(expected)-c);q=(f'A warehouse has {a} boxes with {c} items each. It sells {b} items, not boxes. How many items remain? Output only the integer.' if lang=='en' else f'仓库有{a}箱，每箱{c}件。售出{b}件（不是箱），剩余几件？只输出整数。');check={'unit_items_oracle':a*c-b}
      else:
       expected=str(a%b);bad=str(a//b);q=(f'What is the nonnegative remainder when {a} is divided by {b}? Output only the integer.' if lang=='en' else f'{a}除以{b}的非负余数是多少？只输出整数。');check={'divmod_oracle':list(divmod(a,b))}
      good=expected;checker=lambda s,e=expected:s==e
     elif domain=='instruction':
      if v==0:
       expected={'number':n,'tag':f'item{v}'};good=canon(expected);bad=canon(dict(expected,number=n+1));q=(f'Output exactly a JSON object with number={n} and tag="item{v}". No extra fields or text.' if lang=='en' else f'严格输出JSON对象，number为{n}，tag为"item{v}"。不要其他字段或说明。')
       def checker(s,e=expected):
        try:return json.loads(s)==e
        except (ValueError,TypeError):return False
      elif v==1:
       good=f'ALPHA{n}\nBETA{n}\nGAMMA{n}';bad=good+'\nDELTA';q=(f'Output exactly these three uppercase lines: ALPHA{n}, BETA{n}, GAMMA{n}, in that order. No fourth line or explanation.' if lang=='en' else f'输出三行大写文字，依次为ALPHA{n}、BETA{n}、GAMMA{n}。不要第四行或解释。');checker=lambda s,e=good:s==e
      elif v==2:
       vals=[n+2,n,n+1];good=canon(sorted(vals));bad=canon(vals);q=(f'Sort {canon(vals)} ascending. Output only a JSON array, preserving all three values.' if lang=='en' else f'将{canon(vals)}按升序排列，只输出JSON数组，保留全部三个数。')
       def checker(s,e=sorted(vals)):
        try:return json.loads(s)==e
        except (ValueError,TypeError):return False
      else:
       good=f'BEGIN:{n}:END';bad=f'{n}:END';q=(f'Output exactly BEGIN:{n}:END, with both markers and no other text.' if lang=='en' else f'只输出BEGIN:{n}:END，必须保留前后标记，不要其他文本。');checker=lambda s,e=good:s==e
      check={'exact_constraint_good':good,'deliberate_bad':bad}
     elif domain=='grounding':
      city=f'City{n}';color=['blue','green','red','silver'][v];other=['green','red','silver','blue'][v]
      passage=(f'The parcel Q{n} is stored in {city}. Its label color is {color}. It was inspected on day {n+2}.' if lang=='en' else f'编号Q{n}的包裹存放于{city}。标签颜色是{color}。检查日期是第{n+2}天。')
      q=passage+(' According to this passage, output only the label color for Q'+str(n)+'.' if lang=='en' else f'只依据上文，输出Q{n}的标签颜色。');good=color;bad=other;checker=lambda s,e=color:s==e;check={'literal_fact':color,'passage':passage}
     else:
      specs=[('sum_even','sum(x for x in xs if x % 2 == 0)','sum(x for x in xs if x % 2 != 0)',lambda xs:sum(x for x in xs if x%2==0)),('count_unique','len(set(xs))','len(xs)',lambda xs:len(set(xs))),('sort_values','sorted(xs)','sorted(set(xs))',lambda xs:sorted(xs)),('sum_abs','sum(abs(x) for x in xs)','sum(xs)',lambda xs:sum(abs(x) for x in xs))]
      name,yes,no,oracle=specs[v];testsets=[[],[n,n,-n,0,2],[-3,1,1,4,6],[0,0,0],[-10,-2,-2]];expected=[oracle(xs) for xs in testsets]
      contract=['sum of even integers','number of distinct integers','ascending sorted list preserving duplicates','sum of absolute values'][v]
      q=(f'Provide a Python function solve(xs) returning the {contract}. xs is a list of integers, including negatives and duplicates. Return code only. Required examples: ' if lang=='en' else f'编写Python函数solve(xs)，要求返回{contract}。xs是整数列表，可能有负数或重复元素。只返回代码。必须满足这些例子：')+canon([{'input':xs,'output':y} for xs,y in zip(testsets,expected)])
      good='def solve(xs):\n    return '+yes;bad='def solve(xs):\n    return '+no
      def checker(s,sets=testsets,expected=expected):
       env={'__builtins__':{'sum':sum,'len':len,'set':set,'sorted':sorted,'abs':abs}}
       try:exec(compile(s,'trusted_generated_control','exec'),env);return [env['solve'](xs) for xs in sets]==expected
       except Exception:return False
      check={'program_test_inputs':testsets,'independent_expected_outputs':expected,'only_own_generated_code_executed':True}
     assert checker(good) is True and checker(bad) is False,(domain,v)
     pair=fp([phase,lang,domain,v,q]);proof.append(dict(pair_id=pair,phase=phase,language=lang,domain=domain,good_passed=True,bad_rejected=True,checks=check))
     for expected,answer in [('keep',good),('drop',bad)]:
      ms=[{'role':'user','content':q},{'role':'assistant','content':answer}];i=fp(ms);rows.append(dict(id=i,messages=ms,phase=phase,domain=domain,language=lang,pair_id=pair));labels[i]={'expected':expected,'pair_id':pair,'phase':phase,'domain':domain,'language':lang,'program_verified':True}
 random.Random(2026101306).shuffle(rows);assert len(rows)==128 and len(labels)==128
 return rows,labels,proof

def write_controls(root):
 rows,labels,proof=make_controls()
 for n,v in [('CONTROLS.json',rows),('LABELS.private.json',labels),('PROGRAM_GOLD_PROOF.json',{'pairs':proof,'rows':128,'all_good_and_corrupted_answers_executed_or_exact_checked':True,'manual_review_claimed':False,'benchmark_examples_used':False,'no_training_eligibility':True})]:
  with (Path(root)/n).open('x') as f:json.dump(v,f,indent=2,ensure_ascii=False);f.write('\n')
 return rows,labels,proof
