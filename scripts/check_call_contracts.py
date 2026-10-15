"""Check statically resolved calls, including re-exports and unique mixin methods.

Dynamic attributes and ambiguous methods are intentionally left to runtime tests.
"""

import ast
import sys

violations = []
from pathlib import Path

modules = {
    ".".join(p.with_suffix("").parts): ast.parse(p.read_text())
    for p in Path("backend").rglob("*.py")
}


def source_module(m, n):
    if not n.level:
        return n.module or ""
    parts = m.split(".")[: -n.level]
    return ".".join(parts + ((n.module or "").split(".") if n.module else []))


exports = {m: {} for m in modules}
for m, t in modules.items():
    for n in t.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            exports[m][n.name] = n
for _ in range(12):
    for m, t in modules.items():
        for n in t.body:
            if isinstance(n, ast.ImportFrom):
                target = exports.get(source_module(m, n), {})
                for a in n.names:
                    if a.name == "*":
                        exports[m].update(
                            {k: v for k, v in target.items() if not k.startswith("_")}
                        )
                    elif a.name in target:
                        exports[m][a.asname or a.name] = target[a.name]
methods = {}
for t in modules.values():
    for n in ast.walk(t):
        if isinstance(n, ast.ClassDef):
            for f in n.body:
                if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    methods.setdefault(f.name, []).append(f)
for m, t in modules.items():
    parents = {child: parent for parent in ast.walk(t) for child in ast.iter_child_nodes(parent)}
    for c in ast.walk(t):
        if not isinstance(c, ast.Call) or any(isinstance(a, ast.Starred) for a in c.args):
            continue
        f = None
        skip = 0
        if isinstance(c.func, ast.Name):
            f = exports[m].get(c.func.id)
        elif (
            isinstance(c.func, ast.Attribute)
            and isinstance(c.func.value, ast.Name)
            and c.func.value.id == "self"
        ):
            owner = parents.get(c)
            while owner is not None and not isinstance(owner, ast.ClassDef):
                owner = parents.get(owner)
            local = [n for n in owner.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                     and n.name == c.func.attr] if owner else []
            choices = local or methods.get(c.func.attr, [])
            if len(choices) == 1:
                f = choices[0]
                skip = (
                    0
                    if any(
                        isinstance(d, ast.Name) and d.id == "staticmethod" for d in f.decorator_list
                    )
                    else 1
                )
        if not isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        args = f.args
        pos = args.posonlyargs + args.args
        if not args.vararg and len(c.args) + skip > len(pos):
            violations.append(
                f"{m}:{c.lineno}: {ast.unparse(c.func)} receives {len(c.args)} positional arguments; accepts {len(pos) - skip}"
            )
        if not any(kw.arg is None for kw in c.keywords):
            supplied = {a.arg for a in pos[: len(c.args) + skip]} | {kw.arg for kw in c.keywords}
            required = {a.arg for a in pos[: len(pos) - len(args.defaults)]}
            required |= {
                a.arg for a, default in zip(args.kwonlyargs, args.kw_defaults) if default is None
            }
            for name in sorted(required - supplied):
                violations.append(f"{m}:{c.lineno}: {ast.unparse(c.func)} missing argument {name}")
        valid = {a.arg for a in args.args + args.kwonlyargs}
        if not args.kwarg:
            for kw in c.keywords:
                if kw.arg and kw.arg not in valid:
                    violations.append(
                        f"{m}:{c.lineno}: {ast.unparse(c.func)} unexpected keyword {kw.arg}"
                    )

for violation in violations:
    print(violation)
print(f"Call contract violations: {len(violations)}")
sys.exit(bool(violations))
