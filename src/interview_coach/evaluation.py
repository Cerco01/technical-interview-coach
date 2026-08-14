from __future__ import annotations

import json
import os
import shutil
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from .bank import BankError, get_question
from .private.specs import PYTHON_SPECS, SQL_SPECS


class EvaluationError(ValueError):
    pass


def resolve_submission(path: Path, filename: str) -> Path:
    candidate = path / filename if path.is_dir() else path
    if not candidate.is_file():
        raise EvaluationError(f"submission file not found: {candidate}")
    return candidate


def resource_limits():
    if os.name != "posix":
        return None

    def apply() -> None:
        import resource

        limits = (
            (resource.RLIMIT_CPU, 10),
            (resource.RLIMIT_FSIZE, 1_048_576),
            (resource.RLIMIT_NOFILE, 64),
        )
        for key, value in limits:
            try:
                resource.setrlimit(key, (value, value))
            except (OSError, ValueError):
                pass
        if hasattr(resource, "RLIMIT_NPROC"):
            try:
                resource.setrlimit(resource.RLIMIT_NPROC, (64, 64))
            except (OSError, ValueError):
                pass

    return apply


def run_python(question_id: str, source: Path, timeout: float) -> tuple[str, list[dict[str, str]], dict[str, Any]]:
    with tempfile.TemporaryDirectory(prefix="interview-coach-") as directory:
        workspace = Path(directory)
        submission = workspace / "solution.py"
        shutil.copyfile(source, submission)
        runner = Path(__file__).with_name("runner.py")
        command = [sys.executable, "-B", "-I", str(runner), question_id, str(submission)]
        environment = {
            "PATH": os.environ.get("PATH", ""),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONIOENCODING": "utf-8",
            "PYTHONHASHSEED": "0",
        }
        try:
            completed = subprocess.run(
                command,
                cwd=workspace,
                env=environment,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
                shell=False,
                preexec_fn=resource_limits(),
            )
        except subprocess.TimeoutExpired:
            return "timeout", [{"id": "runtime", "status": "timeout", "message": f"submission exceeded {timeout:g} seconds"}], {"stdout": "", "stderr": "", "truncated": False}
        if len(completed.stdout) > 1_000_000 or len(completed.stderr) > 1_000_000:
            return "error", [{"id": "runtime", "status": "error", "message": "evaluator output exceeded 1 MB"}], {"stdout": "", "stderr": "", "truncated": True}
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError:
            message = completed.stderr.strip() or f"runner exited with code {completed.returncode}"
            return "error", [{"id": "runtime", "status": "error", "message": message[:500]}], {"stdout": "", "stderr": "", "truncated": False}
        learner_output = payload.get("learner_output", {"stdout": "", "stderr": "", "truncated": False})
        if "error" in payload:
            error = payload["error"]
            return "error", [{"id": "runtime", "status": "error", "message": f"{error['type']}: {error['message']}"}], learner_output
        checks = payload["checks"]
        status = "passed" if all(item["status"] == "passed" for item in checks) else "failed"
        return status, checks, learner_output


DENIED_SQL_ACTIONS = {
    sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE,
    sqlite3.SQLITE_ALTER_TABLE, sqlite3.SQLITE_DROP_TABLE, sqlite3.SQLITE_DROP_INDEX,
    sqlite3.SQLITE_ATTACH, sqlite3.SQLITE_DETACH, sqlite3.SQLITE_PRAGMA,
    sqlite3.SQLITE_CREATE_TABLE, sqlite3.SQLITE_CREATE_INDEX, sqlite3.SQLITE_TRANSACTION,
}


def run_sql(question_id: str, source: Path, timeout: float) -> tuple[str, list[dict[str, str]], dict[str, Any]]:
    spec = SQL_SPECS[question_id]
    query = source.read_text(encoding="utf-8")
    connection = sqlite3.connect(":memory:")
    try:
        for statement in spec["setup"]:
            connection.execute(statement)
        connection.commit()
        connection.set_authorizer(lambda action, _a, _b, _db, _trigger: sqlite3.SQLITE_DENY if action in DENIED_SQL_ACTIONS else sqlite3.SQLITE_OK)
        deadline = time.monotonic() + timeout
        connection.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 1000)
        try:
            cursor = connection.execute(query)
            columns = [item[0] for item in cursor.description or []]
            rows = [list(row) for row in cursor.fetchall()]
        except sqlite3.Error as exc:
            status = "timeout" if "interrupted" in str(exc).lower() else "error"
            return status, [{"id": "sql-execution", "status": status, "message": str(exc)}], {"stdout": "", "stderr": "", "truncated": False}
    finally:
        connection.close()
    expected_rows = spec["rows"]
    if not spec["order_sensitive"]:
        rows = sorted(rows, key=repr)
        expected_rows = sorted(expected_rows, key=repr)
    checks = [
        {"id": "columns", "status": "passed" if columns == spec["columns"] else "failed", "message": "result column names and order"},
        {"id": "rows", "status": "passed" if rows == expected_rows else "failed", "message": "result rows and values"},
    ]
    status = "passed" if all(item["status"] == "passed" for item in checks) else "failed"
    return status, checks, {"stdout": "", "stderr": "", "truncated": False}


def evidence_for(question_id: str, submission: Path, timeout: float = 10.0) -> dict[str, Any]:
    question = get_question(question_id)
    evaluation = question["evaluation"]
    strategy = evaluation["strategy"]
    if strategy == "rubric_only":
        raise EvaluationError("this question is rubric-only; commit answer text and use prepare-review")
    source = resolve_submission(submission, evaluation["submission_contract"]["filename"])
    if question_id in PYTHON_SPECS:
        status, checks, learner_output = run_python(question_id, source, timeout)
    elif question_id in SQL_SPECS:
        status, checks, learner_output = run_sql(question_id, source, timeout)
    else:
        raise EvaluationError(f"no deterministic evaluator registered for {question_id}")
    covered = set(evaluation["objective_criteria"])
    failed = status != "passed"
    criteria = []
    for index, rubric in enumerate(question["rubric"]):
        objective = index in covered
        criteria.append({
            "criterion_index": index,
            "max_points": rubric["points"],
            "objective_check": "passed" if objective and not failed else (status if objective else "not_applicable"),
            "scoring_constraint": "max_rubric_points" if not objective or not failed else "zero_points",
        })
    counts = {state: sum(item["status"] == state for item in checks) for state in ("passed", "failed", "error", "timeout")}
    return {
        "schema_version": 1,
        "question_id": question_id,
        "strategy": strategy,
        "status": status,
        "objective_checks": checks,
        "summary": counts,
        "rubric_constraints": criteria,
        "learner_output": learner_output,
        "safety": "trusted_local_code_only",
    }
