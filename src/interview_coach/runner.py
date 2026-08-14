from __future__ import annotations

import contextlib
import copy
import importlib.util
import io
import json
import math
import sys
import traceback
from pathlib import Path
from typing import Any

# Running this file directly keeps isolated mode independent of the caller's cwd.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from interview_coach.private.specs import PYTHON_SPECS


class LimitedWriter(io.TextIOBase):
    def __init__(self, limit: int = 16_384) -> None:
        self.limit = limit
        self.parts: list[str] = []
        self.length = 0
        self.truncated = False

    def write(self, value: str) -> int:
        remaining = self.limit - self.length
        if remaining > 0:
            self.parts.append(value[:remaining])
            self.length += min(len(value), remaining)
        if len(value) > remaining:
            self.truncated = True
        return len(value)

    def value(self) -> str:
        return "".join(self.parts)


def load_module(path: Path):
    spec = importlib.util.spec_from_file_location("learner_submission", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load learner submission")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def decode(value: Any, np=None, pd=None) -> Any:
    if isinstance(value, dict) and "__iterator__" in value:
        return iter(value["__iterator__"])
    if isinstance(value, dict) and "__ndarray__" in value:
        return np.array(value["__ndarray__"], dtype=value.get("dtype"))
    if isinstance(value, dict) and "__dataframe__" in value:
        return pd.DataFrame(value["__dataframe__"])
    if isinstance(value, list):
        return [decode(item, np=np, pd=pd) for item in value]
    if isinstance(value, dict):
        return {key: decode(item, np=np, pd=pd) for key, item in value.items()}
    return value


def normalize(value: Any) -> Any:
    if hasattr(value, "item") and callable(value.item):
        try:
            return value.item()
        except ValueError:
            pass
    if isinstance(value, tuple):
        return [normalize(item) for item in value]
    if isinstance(value, list):
        return [normalize(item) for item in value]
    if isinstance(value, dict):
        return {str(key): normalize(item) for key, item in value.items()}
    return value


def records_equal(actual, expected) -> bool:
    actual_records = actual.reset_index(drop=True).to_dict(orient="records")
    return normalize(actual_records) == expected


def run_custom(name: str, function, np, pd) -> list[dict[str, str]]:
    if name == "first_success":
        result = function(1.0, np.random.default_rng(7), 5, 20)
        ok = isinstance(result, dict) and result.get("mean_trials") == 1 and result.get("capped_runs") == 0
        invalid = False
        try:
            function(0, np.random.default_rng(1), 5, 2)
        except ValueError:
            invalid = True
        return [{"id": "certain-success-and-validation", "status": "passed" if ok and invalid else "failed", "message": "deterministic success and input validation"}]
    if name == "bootstrap":
        first = function([1, 2, 9], [0, 1, 2], np.random.default_rng(42), 200)
        second = function([1, 2, 9], [0, 1, 2], np.random.default_rng(42), 200)
        ok = normalize(first) == normalize(second) and len(first) == 2 and len(first[1]) == 2 and math.isclose(float(first[0]), 2.0)
        return [{"id": "reproducible-point-and-interval", "status": "passed" if ok else "failed", "message": "point estimate and seeded percentile interval"}]
    if name == "clean_accounts":
        frame = pd.DataFrame({"account_id":["a","a","b","c"],"updated_at":["2026-01-01","2026-01-02","bad","2026-01-03"],"email":["old","new","broken","c"],"status":["x","y","x","z"]})
        clean, malformed = function(frame.copy())
        ok = clean["account_id"].tolist() == ["a","c"] and clean["email"].tolist() == ["new","c"] and malformed["account_id"].tolist() == ["b"]
        return [{"id":"latest-valid-and-malformed-report","status":"passed" if ok else "failed","message":"latest valid rows and malformed evidence"}]
    if name == "timestamps":
        frame = pd.DataFrame({"id":[1,2,3,4],"observed_at":["2026-01-02T01:00:00+01:00","bad","","2026-01-01T23:00:00Z"]})
        actual = function(frame.copy())
        ok = actual["id"].tolist() == [4,1,2,3] and actual["invalid_observed_at"].tolist() == [False,False,True,False] and str(actual["observed_at"].dtype).startswith("datetime64[ns, UTC]")
        return [{"id":"utc-flags-and-stable-order","status":"passed" if ok else "failed","message":"UTC parsing, malformed flag, and stable invalid-last order"}]
    if name == "reshape":
        frame = pd.DataFrame({"team":["a","a","b"],"month":["2026-01","2026-01","2026-01"],"metric":["sales","cost","sales"],"value":[5,2,8]})
        actual = function(frame.copy()).sort_values(["team","month"]).reset_index(drop=True)
        ok = set(actual.columns) == {"team","month","sales","cost"} and actual.loc[0,"sales"] == 5 and actual.loc[0,"cost"] == 2
        duplicate = pd.concat([frame, frame.iloc[[0]]], ignore_index=True)
        rejected = False
        try:
            function(duplicate)
        except ValueError:
            rejected = True
        return [{"id":"pivot-and-duplicate-rejection","status":"passed" if ok and rejected else "failed","message":"ordinary columns and duplicate full-key rejection"}]
    raise RuntimeError(f"unknown custom evaluator: {name}")


def run(question_id: str, submission: Path) -> dict[str, Any]:
    spec = PYTHON_SPECS[question_id]
    np = pd = None
    if spec.get("numpy"):
        import numpy as np
    if spec.get("pandas"):
        import pandas as pd
    module = load_module(submission)
    function = getattr(module, spec["entrypoint"], None)
    if not callable(function):
        raise ValueError(f"submission must define callable {spec['entrypoint']}()")
    if "custom" in spec:
        checks = run_custom(spec["custom"], function, np, pd)
        return {"checks": checks}
    checks = []
    for index, case in enumerate(spec["cases"], 1):
        args = decode(copy.deepcopy(case.get("args", [])), np=np, pd=pd)
        before = copy.deepcopy(args[case["preserve_arg"]]) if "preserve_arg" in case else None
        try:
            actual = function(*args)
            if spec.get("materialize"):
                actual = list(actual)
            if "raises" in case:
                ok = False
                message = f"expected {case['raises']}"
            elif "expected_array" in case:
                ok = bool(np.allclose(actual, case["expected_array"], equal_nan=True))
                ok = ok and (not case.get("finite") or bool(np.isfinite(actual).all()))
                message = case["name"]
            elif "expected_records" in case:
                ok = records_equal(actual, case["expected_records"])
                message = case["name"]
            else:
                ok = normalize(actual) == case["expected"]
                message = case["name"]
        except Exception as exc:
            if case.get("raises") == type(exc).__name__:
                ok, message = True, case["name"]
            else:
                ok, message = False, f"{case['name']}: {type(exc).__name__}: {exc}"
        if ok and "preserve_arg" in case:
            current = args[case["preserve_arg"]]
            if np is not None and hasattr(current, "shape"):
                ok = bool(np.array_equal(current, before, equal_nan=True))
            else:
                ok = current == before
            if not ok:
                message = f"{case['name']}: input was mutated"
        checks.append({"id": f"case-{index}", "status": "passed" if ok else "failed", "message": message})
    return {"checks": checks}


def main() -> int:
    output = LimitedWriter()
    error = LimitedWriter()
    try:
        question_id, path = sys.argv[1], Path(sys.argv[2])
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
            result = run(question_id, path)
        result["learner_output"] = {"stdout": output.value(), "stderr": error.value(), "truncated": output.truncated or error.truncated}
        print(json.dumps(result, allow_nan=False, sort_keys=True))
        return 0
    except Exception as exc:
        payload = {"error": {"type": type(exc).__name__, "message": str(exc)}, "learner_output": {"stdout": output.value(), "stderr": error.value(), "truncated": output.truncated or error.truncated}}
        print(json.dumps(payload, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
