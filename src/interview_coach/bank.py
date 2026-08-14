from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from .resources import data_root


class BankError(ValueError):
    pass


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BankError(f"{path}: {exc}") from exc


def questions(root: Path | None = None) -> dict[str, dict[str, Any]]:
    root = root or data_root()
    result: dict[str, dict[str, Any]] = {}
    for path in sorted((root / "questions" if root.name == "interview_coach_data" else root / "data/questions").glob("*.jsonl")):
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise BankError(f"{path}:{line_number}: {exc}") from exc
            question_id = record.get("id")
            if question_id in result:
                raise BankError(f"duplicate question id: {question_id}")
            result[question_id] = record
    return result


def get_question(question_id: str) -> dict[str, Any]:
    try:
        return questions()[question_id]
    except KeyError as exc:
        raise BankError(f"unknown question id: {question_id}") from exc


def learner_safe(question: dict[str, Any]) -> dict[str, Any]:
    evaluation = question["evaluation"]
    return {
        "id": question["id"],
        "title": question["title"],
        "difficulty": question["difficulty"],
        "topic_ids": question["topic_ids"],
        "priority_rank": question["priority_rank"],
        "tier": question["tier"],
        "primary_format": question["primary_format"],
        "primary_category": question["primary_category"],
        "prompt": question["prompt"],
        "evaluation_strategy": evaluation["strategy"],
        "submission_contract": evaluation["submission_contract"],
    }


def sorted_questions(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(records, key=lambda item: item["priority_rank"])
