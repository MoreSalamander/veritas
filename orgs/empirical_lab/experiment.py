"""The Empirical Lab's artifacts: a Hypothesis, an Experiment (code), and the Run manifest.

A hypothesis carries a machine-checkable PREDICTION — either a comparison between two conditions of
a metric (ensemble > single) or a threshold (ensemble >= 0.8). The experiment is code that prints a
JSON result mapping the metric to its conditions' values. The run manifest records the experiment's
output across repeated runs, so reproducibility and support can be checked against real data.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable

from engine.executor import Executor

_OPS: dict[str, Callable[[float, float], bool]] = {
    ">": lambda a, b: a > b, ">=": lambda a, b: a >= b,
    "<": lambda a, b: a < b, "<=": lambda a, b: a <= b,
}
_REPRO_TOLERANCE = 1e-9  # results must match this closely across runs to count as reproducible


class ExperimentParseError(ValueError):
    """A proposed artifact is not usable. The owning gate rejects on this."""


@dataclass
class Prediction:
    kind: str  # "compare" | "threshold"
    op: str
    left: str = ""       # compare: metric condition
    right: str = ""      # compare: metric condition
    condition: str = ""  # threshold: metric condition
    value: float = 0.0   # threshold: the bar


@dataclass
class Hypothesis:
    statement: str
    metric: str
    prediction: Prediction


def _extract_obj(text: str) -> dict[str, Any]:
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ExperimentParseError("no JSON object found")
    try:
        obj: Any = json.loads(text[start : end + 1])
    except (ValueError, TypeError) as exc:
        raise ExperimentParseError(f"not valid JSON: {exc}") from exc
    if not isinstance(obj, dict):
        raise ExperimentParseError("not a JSON object")
    return obj


def parse_hypothesis(payload: str) -> Hypothesis:
    obj = _extract_obj(payload)
    p = obj.get("prediction")
    if not isinstance(p, dict):
        raise ExperimentParseError("missing 'prediction'")
    kind = str(p.get("type") or p.get("kind") or "").strip()
    op = str(p.get("op", "")).strip()
    pred = Prediction(
        kind=kind, op=op,
        left=str(p.get("left", "")).strip(), right=str(p.get("right", "")).strip(),
        condition=str(p.get("condition", "")).strip(),
        value=float(p["value"]) if p.get("value") is not None else 0.0,
    )
    return Hypothesis(
        statement=str(obj.get("statement", "")).strip(),
        metric=str(obj.get("metric", "")).strip(),
        prediction=pred,
    )


def hypothesis_completeness(h: Hypothesis) -> tuple[bool, list[str]]:
    """Gateable = it has a statement, a metric, and a prediction a result can be checked against."""
    missing: list[str] = []
    if not h.statement:
        missing.append("statement")
    if not h.metric:
        missing.append("metric")
    p = h.prediction
    if p.op not in _OPS:
        missing.append("prediction.op")
    if p.kind == "compare":
        if not p.left or not p.right:
            missing.append("prediction.left/right")
    elif p.kind == "threshold":
        if not p.condition:
            missing.append("prediction.condition")
    else:
        missing.append("prediction.type (compare|threshold)")
    return (not missing, missing)


def evaluate_prediction(h: Hypothesis, result: dict[str, Any]) -> tuple[bool, str]:
    """Does this experiment result satisfy the hypothesis? The data decides."""
    metric = result.get(h.metric)
    if not isinstance(metric, dict):
        return (False, f"result has no '{h.metric}' measurements (as a condition->value map)")
    p = h.prediction
    try:
        if p.kind == "compare":
            a, b = float(metric[p.left]), float(metric[p.right])
            ok = _OPS[p.op](a, b)
            return (ok, f"{p.left}={a:g} {p.op} {p.right}={b:g} → {'holds' if ok else 'does NOT hold'}")
        a, t = float(metric[p.condition]), p.value
        ok = _OPS[p.op](a, t)
        return (ok, f"{p.condition}={a:g} {p.op} {t:g} → {'holds' if ok else 'does NOT hold'}")
    except (KeyError, TypeError, ValueError) as exc:
        return (False, f"result missing a predicted condition: {exc}")


# --- the run manifest (the artifact the run stage produces) -------------------------------

@dataclass
class RunManifest:
    metric: str
    runs: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None


def parse_manifest(payload: str) -> RunManifest:
    obj = _extract_obj(payload)
    runs = obj.get("runs", [])
    if not isinstance(runs, list):
        raise ExperimentParseError("manifest 'runs' must be a list")
    return RunManifest(metric=str(obj.get("metric", "")), runs=[r for r in runs if isinstance(r, dict)],
                       error=(str(obj["error"]) if obj.get("error") else None))


def run_experiment(executor: Executor, code: str, metric: str, n: int = 2, timeout: float = 30.0) -> str:
    """Execute the (already security-scanned) experiment n times and capture each JSON result.
    Stops at the first failure and records it — the gates rule on the manifest."""
    runs: list[dict[str, Any]] = []
    error: str | None = None
    for _ in range(n):
        res = executor.run(code, {}, timeout)
        if not res.ok:
            error = (res.stderr or "timed out").strip()[-300:]
            break
        try:
            runs.append(_extract_obj(res.stdout))
        except ExperimentParseError as exc:
            error = f"no JSON result on stdout: {exc}"
            break
    return json.dumps({"metric": metric, "runs": runs, "error": error})


def _flatten(d: dict[str, Any]) -> dict[str, float]:
    flat: dict[str, float] = {}
    for k, v in d.items():
        if isinstance(v, dict):
            for k2, v2 in v.items():
                if isinstance(v2, (int, float)):
                    flat[f"{k}.{k2}"] = float(v2)
        elif isinstance(v, (int, float)):
            flat[k] = float(v)
    return flat


def results_match(r1: dict[str, Any], r2: dict[str, Any]) -> tuple[bool, str]:
    """Two runs reproduce iff they have the same numeric measurements (within tolerance)."""
    f1, f2 = _flatten(r1), _flatten(r2)
    if f1.keys() != f2.keys():
        return (False, f"different measurements: {sorted(f1)} vs {sorted(f2)}")
    drifted = [k for k in f1 if abs(f1[k] - f2[k]) > _REPRO_TOLERANCE]
    if drifted:
        ex = drifted[0]
        return (False, f"{ex} changed between runs: {f1[ex]:g} vs {f2[ex]:g}")
    return (True, f"{len(f1)} measurement(s) identical across runs")
