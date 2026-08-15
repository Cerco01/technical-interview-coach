from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .bank import get_question


class ReviewError(ValueError):
    pass


def read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReviewError(f"{path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ReviewError(f"{path}: expected a JSON object")
    return value


def prepare(question_id: str, answer_path: Path, evidence_path: Path | None) -> dict[str, Any]:
    question = get_question(question_id)
    try:
        answer = answer_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ReviewError(f"could not read completed answer: {exc}") from exc
    evidence = read_object(evidence_path) if evidence_path else None
    if evidence and evidence.get("question_id") != question_id:
        raise ReviewError("evidence question_id does not match requested question")
    return {
        "schema_version": 1,
        "question_id": question_id,
        "answer_committed": True,
        "prompt": question["prompt"],
        "answer": answer,
        "deterministic_evidence": evidence,
        "rubric": [{"criterion_index": index, **item} for index, item in enumerate(question["rubric"])],
        "llm_protocol": {
            "instruction": "Score each rubric criterion from explicit answer and deterministic evidence only. Return one score entry per criterion, concise evidence, a summary, and one improvement.",
            "required_score_fields": ["criterion_index", "awarded_points", "evidence"],
            "objective_rule": "A zero_points constraint requires zero. Passing objective checks supplies evidence but never awards subjective points automatically.",
        },
    }


def finalize(question_id: str, assessment_path: Path, evidence_path: Path | None) -> dict[str, Any]:
    question = get_question(question_id)
    assessment = read_object(assessment_path)
    evidence = read_object(evidence_path) if evidence_path else None
    scores = assessment.get("scores")
    if not isinstance(scores, list) or len(scores) != len(question["rubric"]):
        raise ReviewError("assessment must contain exactly one score per rubric criterion")
    constraints = {}
    if evidence:
        if evidence.get("question_id") != question_id:
            raise ReviewError("evidence question_id does not match requested question")
        constraints = {item["criterion_index"]: item["scoring_constraint"] for item in evidence.get("rubric_constraints", [])}
    normalized = []
    seen = set()
    for score in scores:
        if set(score) != {"criterion_index", "awarded_points", "evidence"}:
            raise ReviewError("each score requires only criterion_index, awarded_points, and evidence")
        index = score["criterion_index"]
        if not isinstance(index, int) or index in seen or not 0 <= index < len(question["rubric"]):
            raise ReviewError(f"invalid or duplicate criterion_index: {index!r}")
        seen.add(index)
        points = score["awarded_points"]
        maximum = question["rubric"][index]["points"]
        if not isinstance(points, int) or isinstance(points, bool) or not 0 <= points <= maximum:
            raise ReviewError(f"criterion {index} points must be an integer from 0 to {maximum}")
        if constraints.get(index) == "zero_points" and points != 0:
            raise ReviewError(f"criterion {index} is capped at zero by deterministic evidence")
        if not isinstance(score["evidence"], str) or not score["evidence"].strip():
            raise ReviewError(f"criterion {index} requires concise evidence")
        normalized.append({"criterion_index": index, "criterion": question["rubric"][index]["criterion"], "awarded_points": points, "max_points": maximum, "evidence": score["evidence"]})
    normalized.sort(key=lambda item: item["criterion_index"])
    return {
        "schema_version": 1,
        "question_id": question_id,
        "score": sum(item["awarded_points"] for item in normalized),
        "max_score": 10,
        "criteria": normalized,
        "summary": str(assessment.get("summary", "")),
        "improvement": str(assessment.get("improvement", "")),
        "deterministic_status": evidence.get("status") if evidence else "not_applicable",
    }
