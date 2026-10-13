"""Bounded Python-subset interpreter, NOT exec/eval or a general Python sandbox.

Only a full-match, question-derived contract supplies the independent oracle.
Unsupported language/specification is HOLD, never a successful correctness check.
"""
import ast
import re


def question_contract(question):
    q = question.strip()
    patterns = [
        (r"(?:创建一个程序，找到给定列表中数字的总和。|计算输入列表中所有数字的总和)\s*输入：\s*(\[[\d, +\-]+\])", "sum"),
        (r"(?:创建一个程序，按升序对数字列表进行排序。|写一个函数，接受一个数字数组并按升序排序。)\s*输入：\s*(\[[\d, +\-]+\])", "sort"),
        (r"(?:写一段代码来找到数组中最大的数字。|写一个函数来找到给定数组的最大元素。)\s*输入：\s*(\[[\d, +\-]+\])", "max"),
        (r"编写一个函数来反转列表的顺序。\s*输入：\s*(?:list1\s*=\s*)?(\[[\d, +\-]+\])", "reverse"),
    ]
    for pattern, name in patterns:
        m = re.fullmatch(pattern, q)
        if m:
            value = ast.literal_eval(m[1])
            if not 1 <= len(value) <= 128 or any(type(x) is not int or abs(x) > 10**9 for x in value):
                return None
            oracle = {"sum": sum, "sort": sorted, "max": max, "reverse": lambda a: list(reversed(a))}[name]
            return {"name": name, "input": value, "expected": oracle(value), "question_only_oracle": True}
    return None


class Unsupported(ValueError):
    pass


class Interpreter:
    def __init__(self):
        self.env = {}
        self.outputs = []
        self.steps = 0

    def tick(self):
        self.steps += 1
        if self.steps > 5000:
            raise Unsupported("step budget")

    def bounded(self, value):
        if type(value) is int and abs(value) <= 10**12:
            return value
        if isinstance(value, (str, list, tuple)) and len(value) <= 256:
            if isinstance(value, (list, tuple)):
                for x in value:
                    self.bounded(x)
            return value
        raise Unsupported("value type/size")

    def expr(self, node):
        self.tick()
        if isinstance(node, ast.Constant):
            return self.bounded(node.value)
        if isinstance(node, ast.Name) and not node.id.startswith("_"):
            return self.bounded(self.env[node.id])
        if isinstance(node, (ast.List, ast.Tuple)):
            return self.bounded([self.expr(x) for x in node.elts])
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            return self.bounded(-self.expr(node.operand))
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult)):
            a, b = self.expr(node.left), self.expr(node.right)
            if type(a) is not int or type(b) is not int:
                raise Unsupported("integer arithmetic only")
            return self.bounded(a + b if isinstance(node.op, ast.Add) else a - b if isinstance(node.op, ast.Sub) else a * b)
        if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Slice) and node.slice.lower is None and node.slice.upper is None and self.expr(node.slice.step) == -1:
            return self.bounded(self.expr(node.value)[::-1])
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and not node.keywords:
            args = [self.expr(x) for x in node.args]
            funcs = {"sum": sum, "sorted": sorted, "max": max, "min": min, "len": len, "list": list, "reversed": lambda x: list(reversed(x))}
            if node.func.id in funcs and len(args) == 1:
                return self.bounded(funcs[node.func.id](*args))
        raise Unsupported("unsupported expression")

    def statements(self, nodes):
        for node in nodes:
            self.tick()
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) and not node.targets[0].id.startswith("_"):
                self.env[node.targets[0].id] = self.expr(node.value)
            elif isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name) and isinstance(node.op, ast.Add):
                self.env[node.target.id] = self.bounded(self.env[node.target.id] + self.expr(node.value))
            elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name) and node.value.func.id == "print" and len(node.value.args) == 1 and not node.value.keywords:
                self.outputs.append(self.expr(node.value.args[0]))
            elif isinstance(node, ast.For) and isinstance(node.target, ast.Name) and not node.target.id.startswith("_") and not node.orelse:
                if any(isinstance(n, ast.Return) for stmt in node.body for n in ast.walk(stmt)):
                    raise Unsupported("return inside loop is outside this subset")
                values = self.expr(node.iter)
                if not isinstance(values, (list, tuple)):
                    raise Unsupported("loop iterable")
                for v in values:
                    self.env[node.target.id] = v
                    self.statements(node.body)
            elif isinstance(node, ast.Return):
                return self.expr(node.value)
            else:
                raise Unsupported("unsupported statement")
        return None


def verify_code(messages):
    if len(messages) != 2 or [m["role"] for m in messages] != ["user", "assistant"]:
        return {"status": "HOLD", "reason": "unsupported conversation contract"}
    contract = question_contract(messages[0]["content"])
    if contract is None:
        return {"status": "HOLD", "reason": "no independent supported question contract"}
    fences = re.findall(r"```(?:python|Python)\s*\n(.*?)```", messages[1]["content"], re.S)
    if len(fences) != 1:
        return {"status": "HOLD", "reason": "one explicit Python block required"}
    try:
        src = fences[0]
        if len(src) > 8000:
            raise Unsupported("code size")
        tree = ast.parse(src)
        if sum(1 for _ in ast.walk(tree)) > 512:
            raise Unsupported("AST size")
        i = Interpreter()
        if len(tree.body) == 1 and isinstance(tree.body[0], ast.FunctionDef):
            fn = tree.body[0]
            if fn.decorator_list or fn.returns or fn.args.defaults or fn.args.kwonlyargs or fn.args.vararg or fn.args.kwarg or len(fn.args.args) != 1 or fn.args.posonlyargs or fn.args.args[0].annotation:
                raise Unsupported("function signature")
            i.env[fn.args.args[0].arg] = contract["input"]
            actual = i.statements(fn.body)
        else:
            i.statements(tree.body)
            if len(i.outputs) != 1:
                raise Unsupported("single unambiguous output required")
            actual = i.outputs[0]
        return {"status": "PASS" if type(actual) is type(contract["expected"]) and actual == contract["expected"] else "HOLD",
                "reason": "independent concrete input matches" if actual == contract["expected"] else "computed output mismatch",
                "contract": contract["name"], "tested_inputs": 1, "question_only_oracle": True,
                "scope": "bounded subset concrete input; not universal correctness", "interpreter_steps": i.steps}
    except (Unsupported, SyntaxError, KeyError, TypeError, ValueError, OverflowError, RecursionError) as e:
        return {"status": "HOLD", "reason": str(e)}
