from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from .bank import BankError, questions, read_json
from .private.specs import PYTHON_SPECS, SQL_SPECS
from .resources import data_root, repository_root


class ValidationError(ValueError):
    pass


EXPECTED_FORMATS = {"implementation":10,"sql_query":7,"debugging":7,"conceptual_reasoning":14,"case_study":7,"data_manipulation":5}
EXPECTED_TIERS = {"core":24,"differentiator":18,"specialized":8}
EXPECTED_DIFFICULTIES = {"beginner":12,"intermediate":28,"advanced":10}
STRATEGIES = {"executable", "sql", "dataframe", "numeric", "rubric_only"}
LOCAL_PATH = re.compile(rb"(?:/" + rb"Users/|/" + rb"home/[^/\s]+/|[A-Za-z]:" + rb"\\(?:Users|home)\\)", re.I)
PROHIBITED_SUFFIXES = {
    ".7z", ".csv", ".db", ".feather", ".gz", ".h5", ".hdf5", ".joblib",
    ".npy", ".npz", ".parquet", ".pdf", ".pickle", ".pkl", ".pyc", ".pyo",
    ".sqlite", ".sqlite3", ".tar", ".tgz", ".tsv", ".xls", ".xlsx", ".zip",
}
PROHIBITED_DIRS = {
    ".atl", ".mypy_cache", ".nox", ".pytest_cache", ".ruff_cache", ".tox",
    ".venv", "__pycache__", "build", "dist", "evidence", "htmlcov", "reviews",
    "sessions", "state", "submissions", "venv",
}
PROHIBITED_NAMES = {".coverage", ".DS_Store", ".env", "active-session.json", "learner.json"}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValidationError(message)


def validate_privacy(root: Path) -> None:
    violations = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        name = path.name
        if (
            path.is_symlink()
            or any(part in PROHIBITED_DIRS for part in relative.parts)
            or name in PROHIBITED_NAMES
            or name.startswith(".env.")
            or name.endswith(".egg-info")
            or path.suffix.lower() in PROHIBITED_SUFFIXES
        ):
            violations.append(str(relative))
            continue
        if path.is_file():
            content = path.read_bytes()
            if LOCAL_PATH.search(content):
                violations.append(str(relative))
    require(not violations, "privacy/artifact guard violations: " + ", ".join(violations))


def validate(root: Path | None = None, scan_privacy: bool = True) -> dict[str, int]:
    root = root or data_root()
    curriculum_path = root / "curriculum/topics.json" if root.name != "interview_coach_data" else root / "curriculum/topics.json"
    curriculum = read_json(curriculum_path)
    topics = curriculum.get("topics", [])
    require(len(topics) == 37, f"expected 37 topics, got {len(topics)}")
    topic_ids = {item["id"] for item in topics}
    require(len(topic_ids) == 37, "topic IDs must be unique")
    records = questions(root)
    require(len(records) == 50, f"expected 50 questions, got {len(records)}")
    require({item["priority_rank"] for item in records.values()} == set(range(1, 51)), "priority ranks must be contiguous 1..50")
    require(Counter(item["primary_format"] for item in records.values()) == Counter(EXPECTED_FORMATS), "question format allocation mismatch")
    require(Counter(item["tier"] for item in records.values()) == Counter(EXPECTED_TIERS), "question tier allocation mismatch")
    require(Counter(item["difficulty"] for item in records.values()) == Counter(EXPECTED_DIFFICULTIES), "question difficulty allocation mismatch")
    registered = set(PYTHON_SPECS) | set(SQL_SPECS)
    for question_id, item in records.items():
        require(item["schema_version"] == 3, f"{question_id}: unsupported schema_version")
        require(set(item["topic_ids"]) <= topic_ids, f"{question_id}: unknown topic")
        require(sum(entry["points"] for entry in item["rubric"]) == 10, f"{question_id}: rubric must total 10")
        evaluation = item.get("evaluation", {})
        strategy = evaluation.get("strategy")
        require(strategy in STRATEGIES, f"{question_id}: invalid evaluation strategy")
        contract = evaluation.get("submission_contract", {})
        require(isinstance(contract.get("filename"), str) and isinstance(contract.get("kind"), str), f"{question_id}: invalid submission contract")
        if contract.get("kind") == "python_module":
            require(all(isinstance(contract.get(field), str) for field in ("entrypoint", "signature", "returns")), f"{question_id}: incomplete Python submission contract")
        if contract.get("kind") == "sql_query":
            require(isinstance(contract.get("columns"), list) and contract["columns"], f"{question_id}: SQL output columns are required")
        indices = evaluation.get("objective_criteria")
        require(isinstance(indices, list) and len(indices) == len(set(indices)) and all(isinstance(index, int) and 0 <= index < len(item["rubric"]) for index in indices), f"{question_id}: invalid objective criteria")
        if strategy == "rubric_only":
            require(evaluation.get("evaluator_ref") is None and not indices, f"{question_id}: rubric-only evaluation cannot claim objective coverage")
        else:
            require(question_id in registered and evaluation.get("evaluator_ref") == f"builtin:{question_id}", f"{question_id}: deterministic evaluator is not registered")
        if item["primary_format"] in {"implementation", "sql_query", "data_manipulation"}:
            require(strategy != "rubric_only", f"{question_id}: primary format requires deterministic evaluation")
    schema_dir = root / "schemas"
    schema_paths = list(schema_dir.glob("*.schema.json"))
    require(len(schema_paths) == 9, f"expected 9 schemas, got {len(schema_paths)}")
    for path in schema_paths:
        require(read_json(path).get("$schema") == "https://json-schema.org/draft/2020-12/schema", f"{path.name}: unexpected schema draft")
    source_root = repository_root()
    if scan_privacy and source_root and root.resolve() == source_root.resolve():
        validate_privacy(source_root)
    return {"topics": len(topics), "questions": len(records), "schemas": len(schema_paths), "deterministic": len(registered)}
