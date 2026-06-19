"""P15 — the Language seam: the software org, one verification model, many languages.

The org's way of knowing code is correct never changes — *execute it and check* — only the
toolchain does. So a Language supplies the language-specific bits: the developer's prompt, a
syntax check, and the cases/properties harnesses (run through the executor). Python is the
reference; JavaScript is the first sibling. Adding a language is implementing this interface,
not touching the engine. The oracle-free property idea (round-trip, monotonic, invariant,
idempotent) carries across languages unchanged — only its harness is re-expressed.

Data always rides as JSON through the environment, never interpolated into source — the
injection-safe rule, now upheld in every language's harness.
"""

from __future__ import annotations

import ast
import json
import os
import sys
from abc import ABC, abstractmethod
from typing import Any

from engine.executor import Executor
from orgs.software_studio.properties import PROPERTY_HARNESS, Property, serialize


def _last_line(stderr: str) -> str:
    return stderr.strip().splitlines()[-1] if stderr.strip() else "non-zero exit"


class Language(ABC):
    name: str
    ext: str
    dev_system: str  # the developer system prompt for this language

    @abstractmethod
    def syntax_ok(self, executor: Executor, code: str, function_name: str, timeout: float = 10.0) -> tuple[bool, str]:
        ...

    @abstractmethod
    def run_cases(self, executor: Executor, code: str, function_name: str,
                  cases: list[dict[str, Any]], timeout: float = 10.0) -> tuple[bool, str]:
        ...

    @abstractmethod
    def run_properties(self, executor: Executor, code: str, function_name: str,
                       properties: list[Property], timeout: float = 10.0) -> tuple[bool, str]:
        ...


# --- Python: the reference language (delegates to the proven, in-tree harnesses) ----------

_PY_CASES_HARNESS = """
import json as _json, os as _os, math as _math
def _eq(a, b):
    if isinstance(a, bool) or isinstance(b, bool):
        return a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return _math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-9)
    return a == b
_cases = _json.loads(_os.environ["VERITAS_CASES"])
_fn = globals().get(_os.environ["VERITAS_FN"])
if _fn is None:
    raise AssertionError(_os.environ["VERITAS_FN"] + "() not found at module scope")
for _i, _c in enumerate(_cases):
    _got = _fn(*_c["args"])
    if not _eq(_got, _c["expected"]):
        raise AssertionError("case %d: %s(*%r) -> %r, expected %r" % (
            _i, _os.environ["VERITAS_FN"], _c["args"], _got, _c["expected"]))
print("OK", len(_cases), "cases")
"""


class PythonLanguage(Language):
    name = "python"
    ext = ".py"
    dev_system = (
        "You are a careful Python developer. Given a JSON spec, respond with ONLY the Python "
        "source that defines the function — no prose, no markdown fences, no tests. The function "
        "must be named exactly as function_name and satisfy every case."
    )

    def syntax_ok(self, executor: Executor, code: str, function_name: str, timeout: float = 10.0) -> tuple[bool, str]:
        try:
            tree = ast.parse(code)
        except SyntaxError as exc:
            return False, f"syntax error: {exc}"
        defined = any(
            isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == function_name
            for n in ast.walk(tree)
        )
        return (True, f"parses; {function_name}() defined") if defined else (False, f"{function_name}() is not defined")

    def run_cases(self, executor: Executor, code: str, function_name: str,
                  cases: list[dict[str, Any]], timeout: float = 10.0) -> tuple[bool, str]:
        if not cases:
            return True, "no cases to run"
        env = {**os.environ, "VERITAS_CASES": json.dumps(cases), "VERITAS_FN": function_name}
        result = executor.run_argv([sys.executable, "main.py"], env, timeout,
                                   files={"main.py": f"{code}\n{_PY_CASES_HARNESS}"})
        return (True, f"{len(cases)}/{len(cases)} cases passed") if result.ok else (False, _last_line(result.stderr))

    def run_properties(self, executor: Executor, code: str, function_name: str,
                       properties: list[Property], timeout: float = 10.0) -> tuple[bool, str]:
        if not properties:
            return True, "no oracle-free properties offered — behavior not hard-verified"
        env = {**os.environ, "VERITAS_PROPS": serialize(properties), "VERITAS_FN": function_name}
        result = executor.run_argv([sys.executable, "main.py"], env, timeout,
                                   files={"main.py": f"{code}\n{PROPERTY_HARNESS}"})
        held = "; ".join(p.describe() for p in properties)
        return (True, f"{len(properties)} property(ies) hold: {held}") if result.ok else (False, _last_line(result.stderr))


# --- JavaScript: the first sibling (Node) -------------------------------------------------

_JS_CASES_HARNESS = r"""
const _cases = JSON.parse(process.env.VERITAS_CASES);
const _fnname = process.env.VERITAS_FN;
let _fn; try { _fn = eval(_fnname); } catch (e) {}
if (typeof _fn !== "function") { console.error(_fnname + "() not found"); process.exit(1); }
function _eq(a, b) {
  if (typeof a === "number" && typeof b === "number")
    return a === b || Math.abs(a - b) <= Math.max(1e-9 * Math.max(Math.abs(a), Math.abs(b)), 1e-9);
  return JSON.stringify(a) === JSON.stringify(b);
}
for (let i = 0; i < _cases.length; i++) {
  const c = _cases[i], got = _fn(...c.args);
  if (!_eq(got, c.expected)) {
    console.error(`case ${i}: ${_fnname}(${JSON.stringify(c.args)}) -> ${JSON.stringify(got)}, expected ${JSON.stringify(c.expected)}`);
    process.exit(1);
  }
}
console.log("OK " + _cases.length + " cases");
"""

_JS_PROPERTY_HARNESS = r"""
const _props = JSON.parse(process.env.VERITAS_PROPS);
const _fnname = process.env.VERITAS_FN;
function _call(name, args) { let f; try { f = eval(name); } catch (e) {} if (typeof f !== "function") throw new Error(name + "() not found"); return f(...args); }
function _close(a, b) {
  if (typeof a === "number" && typeof b === "number")
    return a === b || Math.abs(a - b) <= Math.max(1e-9 * Math.max(Math.abs(a), Math.abs(b)), 1e-9);
  return JSON.stringify(a) === JSON.stringify(b);
}
function _ordered(prev, cur, dir, strict) {
  if (dir === "increasing") return strict ? prev < cur : prev <= cur;
  return strict ? prev > cur : prev >= cur;
}
function _invariant(name, args, out) {
  if (name === "sorted_ascending") return out.every((v, i) => i === 0 || out[i - 1] <= v);
  if (name === "sorted_descending") return out.every((v, i) => i === 0 || out[i - 1] >= v);
  if (name === "is_permutation_of_input") return JSON.stringify([...out].sort()) === JSON.stringify([...args[0]].sort());
  if (name === "length_preserved") return out.length === args[0].length;
  if (name === "elements_unique") return new Set(out).size === out.length;
  if (name === "non_negative") return out >= 0;
  throw new Error("unknown invariant: " + name);
}
for (let pi = 0; pi < _props.length; pi++) {
  const p = _props[pi], inputs = p.inputs;
  if (p.kind === "round_trip") {
    for (const a of inputs) { const back = _call(p.inverse, [_call(_fnname, a)]);
      if (!_close(back, a[0])) { console.error(`property ${pi} round_trip failed`); process.exit(1); } }
  } else if (p.kind === "idempotent") {
    for (const a of inputs) { const once = _call(_fnname, a), twice = _call(_fnname, [once]);
      if (!_close(twice, once)) { console.error(`property ${pi} idempotent failed`); process.exit(1); } }
  } else if (p.kind === "monotonic") {
    const outs = inputs.map(a => _call(_fnname, a));
    for (let i = 0; i < outs.length - 1; i++)
      if (!_ordered(outs[i], outs[i + 1], p.direction, p.strict)) { console.error(`property ${pi} monotonic failed`); process.exit(1); }
  } else if (p.kind === "invariant") {
    for (const a of inputs) { const out = _call(_fnname, a);
      if (!_invariant(p.invariant, a, out)) { console.error(`property ${pi} invariant ${p.invariant} failed`); process.exit(1); } }
  } else { console.error("unknown kind: " + p.kind); process.exit(1); }
}
console.log("OK " + _props.length + " properties");
"""


class JavaScriptLanguage(Language):
    name = "javascript"
    ext = ".js"
    dev_system = (
        "You are a careful JavaScript (Node) developer. Given a JSON spec, respond with ONLY the "
        "JavaScript source that defines the function at top level (a `function NAME(...)` "
        "declaration so it is in scope by name) — no prose, no markdown fences, no tests, no "
        "module.exports. The function must be named exactly as function_name and satisfy every case."
    )

    def syntax_ok(self, executor: Executor, code: str, function_name: str, timeout: float = 10.0) -> tuple[bool, str]:
        check = (
            f"{code}\n"
            f"if (typeof (()=>{{try{{return eval({function_name!r})}}catch(e){{return undefined}}}})() "
            f"!== 'function') {{ console.error({function_name!r}+' not defined'); process.exit(1); }}\n"
            "console.log('OK');\n"
        )
        result = executor.run_argv(["node", "main.js"], {**os.environ}, timeout, files={"main.js": check})
        return (True, f"parses; {function_name}() defined") if result.ok else (False, _last_line(result.stderr))

    def run_cases(self, executor: Executor, code: str, function_name: str,
                  cases: list[dict[str, Any]], timeout: float = 10.0) -> tuple[bool, str]:
        if not cases:
            return True, "no cases to run"
        env = {**os.environ, "VERITAS_CASES": json.dumps(cases), "VERITAS_FN": function_name}
        result = executor.run_argv(["node", "main.js"], env, timeout,
                                   files={"main.js": f"{code}\n{_JS_CASES_HARNESS}"})
        return (True, f"{len(cases)}/{len(cases)} cases passed") if result.ok else (False, _last_line(result.stderr))

    def run_properties(self, executor: Executor, code: str, function_name: str,
                       properties: list[Property], timeout: float = 10.0) -> tuple[bool, str]:
        if not properties:
            return True, "no oracle-free properties offered — behavior not hard-verified"
        env = {**os.environ, "VERITAS_PROPS": serialize(properties), "VERITAS_FN": function_name}
        result = executor.run_argv(["node", "main.js"], env, timeout,
                                   files={"main.js": f"{code}\n{_JS_PROPERTY_HARNESS}"})
        held = "; ".join(p.describe() for p in properties)
        return (True, f"{len(properties)} property(ies) hold: {held}") if result.ok else (False, _last_line(result.stderr))


LANGUAGES: dict[str, Language] = {
    "python": PythonLanguage(),
    "javascript": JavaScriptLanguage(),
}
