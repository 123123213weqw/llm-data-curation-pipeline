"""Narrow exact arithmetic tool. Parses the question only; never reads gold or executes candidate code."""
import ast,re
from fractions import Fraction

def arithmetic(s):
 if len(s)>160 or not re.fullmatch(r'[0-9+*/()% .-]+',s):raise ValueError('unsupported expression')
 tree=ast.parse(s.strip(),mode='eval')
 if sum(1 for _ in ast.walk(tree))>64:raise ValueError('expression complexity')
 def run(n):
  if isinstance(n,ast.Constant) and type(n.value) is int and abs(n.value)<=10**9:return Fraction(n.value)
  if isinstance(n,ast.BinOp) and isinstance(n.op,(ast.Add,ast.Sub,ast.Mult,ast.Div,ast.Mod)):
   a,b=run(n.left),run(n.right)
   if isinstance(n.op,ast.Add):v=a+b
   elif isinstance(n.op,ast.Sub):v=a-b
   elif isinstance(n.op,ast.Mult):v=a*b
   elif isinstance(n.op,ast.Div):v=a/b
   else:
    if a.denominator!=1 or b.denominator!=1 or b<=0:raise ValueError('unsupported remainder')
    v=a%b
   if max(abs(v.numerator),v.denominator)>10**30:raise ValueError('result bound')
   return v
  if isinstance(n,ast.UnaryOp) and isinstance(n.op,ast.USub):return -run(n.operand)
  raise ValueError('unsupported expression node')
 return run(tree.body)

def program_check(messages):
 # Exactly one user question: multi-turn/free-form proof problems deliberately unsupported.
 if len(messages)!=2 or [m['role'] for m in messages]!=['user','assistant']:return None
 q=messages[0]['content'];v=None;kind=None
 patterns=[(r'Calculate (.+)\. Output only the integer\.', 'integer'),(r'计算(.+)，只输出整数，不加解释。','integer'),(r'Compute (.+)\. Output only the reduced numerator/denominator\.','reduced_fraction'),(r'计算(.+)，只输出最简分数分子/分母。','reduced_fraction')]
 try:
  for pattern,k in patterns:
   m=re.fullmatch(pattern,q)
   if m:v=arithmetic(m[1]);kind=k;break
  if v is None:
   m=re.fullmatch(r'What is the nonnegative remainder when (\d+) is divided by (\d+)\? Output only the integer\.',q) or re.fullmatch(r'(\d+)除以(\d+)的非负余数是多少？只输出整数。',q)
   if m:v=arithmetic(f'{m[1]}%{m[2]}');kind='integer'
  if v is None:
   m=re.fullmatch(r'A warehouse has (\d+) boxes with (\d+) items each\. It sells (\d+) items, not boxes\. How many items remain\? Output only the integer\.',q) or re.fullmatch(r'仓库有(\d+)箱，每箱(\d+)件。售出(\d+)件（不是箱），剩余几件？只输出整数。',q)
   if m:v=arithmetic(f'{m[1]}*{m[2]}-{m[3]}');kind='integer'
  if v is None:return None
  if kind=='integer' and v.denominator!=1:return None
  value=str(v.numerator) if kind=='integer' else f'{v.numerator}/{v.denominator}'
  return {'tool':'question_only_exact_fraction_v1','supported_contract':kind,'verified_value':value,'candidate_answer_used_in_calculation':False,'arbitrary_code_execution':False}
 except (ValueError,SyntaxError,ZeroDivisionError,OverflowError):return None
