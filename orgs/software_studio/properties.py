"""P13a — structured oracles: relations a HARD gate can check without trusting a
model-authored value.

The problem P13 closes: an exact `expected` value in a spec case is a number the
*model* wrote. A hard gate that checks `f(x) == expected` is therefore trusting the
model's judgment — the exact thing the deterministic scaffold exists to never do. If
the model's `expected` is wrong, the gate's verdict is wrong: it rejects correct code,
or blesses code that conforms to a wrong belief.

The fix is to verify *relations the function must satisfy regardless of its exact
output* — round-trips, idempotence, monotonicity, structural invariants. These need no
known answer; they only need the function to be self-consistent. Such a check is
ORACLE-FREE, so it can be HARD. A value-bearing anchor (`f(0) == 32`) still embeds a
model number, so it stays SOFT (advisory) and lives on the old `cases` path.

Inputs are not oracles. The model may freely propose *inputs*; the relation checked
over the function's own outputs is ours — compiled deterministically here, never a
model scalar interpolated into source as truth. (Data rides as JSON through the
environment and is looped over — the injection-safe pattern proven in the first run.)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class PropertyParseError(ValueError):
    """A proposed property is malformed or not oracle-free. The property gate rejects."""


class PropertyKind(str, Enum):
    ROUND_TRIP = "round_trip"   # inverse(f(x)) ~= x  — needs an inverse function in scope
    IDEMPOTENT = "idempotent"   # f(f(x)) == f(x)     — unary
    MONOTONIC = "monotonic"     # ordered inputs -> ordered outputs
    INVARIANT = "invariant"     # a named structural invariant holds on f(x)


# The closed library of structural invariants. Each is a self-contained check over a
# function's own output (and, where noted, its single list input) — no external truth.
INVARIANTS: frozenset[str] = frozenset(
    {
        "sorted_ascending",          # output is a list, non-decreasing
        "sorted_descending",         # output is a list, non-increasing
        "is_permutation_of_input",   # output is a multiset-permutation of args[0]
        "length_preserved",          # len(output) == len(args[0])
        "elements_unique",           # output has no duplicates
        "non_negative",              # output >= 0
    }
)

_DIRECTIONS: frozenset[str] = frozenset({"increasing", "decreasing"})

# Every kind here is oracle-free by construction — that is the whole point of the module.
ORACLE_FREE = True


@dataclass(frozen=True)
class Property:
    kind: PropertyKind
    inputs: list[list[Any]]            # each entry is an args-list for the function
    inverse: str | None = None         # round_trip: name of the inverse function
    direction: str = "increasing"      # monotonic: "increasing" | "decreasing"
    strict: bool = False               # monotonic: strict (<) vs non-strict (<=)
    invariant: str | None = None       # invariant: a name from INVARIANTS

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"kind": self.kind.value, "inputs": self.inputs}
        if self.kind is PropertyKind.ROUND_TRIP:
            payload["inverse"] = self.inverse
        elif self.kind is PropertyKind.MONOTONIC:
            payload["direction"] = self.direction
            payload["strict"] = self.strict
        elif self.kind is PropertyKind.INVARIANT:
            payload["invariant"] = self.invariant
        return payload

    def describe(self) -> str:
        n = len(self.inputs)
        if self.kind is PropertyKind.ROUND_TRIP:
            return f"round_trip via {self.inverse}() over {n} input(s)"
        if self.kind is PropertyKind.MONOTONIC:
            strict = "strict " if self.strict else ""
            return f"{strict}monotonic ({self.direction}) over {n} input(s)"
        if self.kind is PropertyKind.INVARIANT:
            return f"invariant:{self.invariant} over {n} input(s)"
        return f"idempotent over {n} input(s)"


def _require_inputs(raw: Any, index: int) -> list[list[Any]]:
    if not isinstance(raw, list) or not raw:
        raise PropertyParseError(f"property {index}: 'inputs' must be a non-empty list")
    inputs: list[list[Any]] = []
    for j, args in enumerate(raw):
        if not isinstance(args, list):
            raise PropertyParseError(
                f"property {index}: input {j} must be an args-list (a JSON array)"
            )
        inputs.append(args)
    return inputs


def parse_property(obj: Any, index: int) -> Property:
    """Validate one proposed property into a typed, oracle-free Property — or reject."""
    if not isinstance(obj, dict):
        raise PropertyParseError(f"property {index} must be a JSON object")

    raw_kind = obj.get("kind")
    try:
        kind = PropertyKind(raw_kind)
    except ValueError as exc:
        raise PropertyParseError(
            f"property {index}: unknown kind {raw_kind!r} "
            f"(allowed: {', '.join(k.value for k in PropertyKind)})"
        ) from exc

    inputs = _require_inputs(obj.get("inputs"), index)

    if kind is PropertyKind.ROUND_TRIP:
        inverse = obj.get("inverse")
        if not isinstance(inverse, str) or not inverse.isidentifier():
            raise PropertyParseError(
                f"property {index}: round_trip needs an 'inverse' function identifier"
            )
        for j, args in enumerate(inputs):
            if len(args) != 1:
                raise PropertyParseError(
                    f"property {index}: round_trip input {j} must have exactly one arg"
                )
        return Property(kind=kind, inputs=inputs, inverse=inverse)

    if kind is PropertyKind.IDEMPOTENT:
        for j, args in enumerate(inputs):
            if len(args) != 1:
                raise PropertyParseError(
                    f"property {index}: idempotent input {j} must have exactly one arg"
                )
        return Property(kind=kind, inputs=inputs)

    if kind is PropertyKind.MONOTONIC:
        direction = obj.get("direction", "increasing")
        if direction not in _DIRECTIONS:
            raise PropertyParseError(
                f"property {index}: monotonic 'direction' must be one of {sorted(_DIRECTIONS)}"
            )
        if len(inputs) < 2:
            raise PropertyParseError(
                f"property {index}: monotonic needs at least 2 ordered inputs"
            )
        return Property(
            kind=kind, inputs=inputs, direction=direction, strict=bool(obj.get("strict", False))
        )

    # INVARIANT
    invariant = obj.get("invariant")
    if invariant not in INVARIANTS:
        raise PropertyParseError(
            f"property {index}: 'invariant' must be one of {sorted(INVARIANTS)}"
        )
    return Property(kind=kind, inputs=inputs, invariant=invariant)


def parse_properties(raw: Any) -> list[Property]:
    """Parse a JSON array of property objects. An absent/empty list is valid (no
    oracle-free properties offered) — the caller decides what that means for hardness."""
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise PropertyParseError("'properties' must be a JSON array")
    return [parse_property(obj, i) for i, obj in enumerate(raw)]


def serialize(properties: list[Property]) -> str:
    """JSON for the env channel — never interpolated into source."""
    return json.dumps([p.to_payload() for p in properties])


# The deterministic checker. Reads properties + function name from the environment,
# runs each relation against the candidate code in scope, raises AssertionError on the
# first violation, prints a summary on success. No model value is ever the oracle.
PROPERTY_HARNESS = r"""
import json as _json, os as _os, math as _math

def _close(a, b):
    if (isinstance(a, (int, float)) and isinstance(b, (int, float))
            and not isinstance(a, bool) and not isinstance(b, bool)):
        return _math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-9)
    return a == b

def _call(name, args):
    fn = globals().get(name)
    if fn is None:
        raise AssertionError(name + "() not found at module scope")
    return fn(*args)

def _ordered(prev, cur, direction, strict):
    if direction == "increasing":
        return (prev < cur) if strict else (prev <= cur)
    return (prev > cur) if strict else (prev >= cur)

def _invariant(name, args, out):
    if name == "sorted_ascending":
        return all(out[i] <= out[i + 1] for i in range(len(out) - 1))
    if name == "sorted_descending":
        return all(out[i] >= out[i + 1] for i in range(len(out) - 1))
    if name == "is_permutation_of_input":
        return sorted(out) == sorted(args[0])
    if name == "length_preserved":
        return len(out) == len(args[0])
    if name == "elements_unique":
        return len(set(out)) == len(out)
    if name == "non_negative":
        return out >= 0
    raise AssertionError("unknown invariant: " + str(name))

_props = _json.loads(_os.environ["VERITAS_PROPS"])
_fn = _os.environ["VERITAS_FN"]

for _pi, _p in enumerate(_props):
    _kind = _p["kind"]
    _inputs = _p["inputs"]
    if _kind == "round_trip":
        _inv = _p["inverse"]
        for _a in _inputs:
            _back = _call(_inv, [_call(_fn, _a)])
            if not _close(_back, _a[0]):
                raise AssertionError(
                    "property %d round_trip: %s(%s(%r)) -> %r, expected %r"
                    % (_pi, _inv, _fn, _a[0], _back, _a[0]))
    elif _kind == "idempotent":
        for _a in _inputs:
            _once = _call(_fn, _a)
            _twice = _call(_fn, [_once])
            if not _close(_twice, _once):
                raise AssertionError(
                    "property %d idempotent: f(f(%r))=%r != f(%r)=%r"
                    % (_pi, _a[0], _twice, _a[0], _once))
    elif _kind == "monotonic":
        _outs = [_call(_fn, _a) for _a in _inputs]
        for _i in range(len(_outs) - 1):
            if not _ordered(_outs[_i], _outs[_i + 1], _p["direction"], _p["strict"]):
                raise AssertionError(
                    "property %d monotonic(%s): f(*%r)=%r then f(*%r)=%r breaks order"
                    % (_pi, _p["direction"], _inputs[_i], _outs[_i],
                       _inputs[_i + 1], _outs[_i + 1]))
    elif _kind == "invariant":
        _name = _p["invariant"]
        for _a in _inputs:
            _out = _call(_fn, _a)
            if not _invariant(_name, _a, _out):
                raise AssertionError(
                    "property %d invariant %s violated: f(*%r) -> %r"
                    % (_pi, _name, _a, _out))
    else:
        raise AssertionError("unknown property kind: " + str(_kind))

print("OK", len(_props), "properties")
"""
