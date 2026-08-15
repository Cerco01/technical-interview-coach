from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any, Iterable


ASSESSMENT_BLUEPRINT = (
    "python_algorithms",
    "sql",
    "pandas_data_handling",
    "probability_statistics",
    "core_ml_evaluation",
    "numpy",
    "debugging_case_reasoning",
    "python_algorithms",
    "sql",
    "pandas_data_handling",
    "probability_statistics",
    "core_ml_evaluation",
)
CORE_CATEGORIES = {
    "python_algorithms",
    "numpy",
    "pandas_data_handling",
    "sql",
    "probability_statistics",
    "core_ml_evaluation",
}
DIFFICULTIES = ("beginner", "intermediate", "advanced")
TIER_ORDER = {"core": 0, "differentiator": 1, "specialized": 2}
REASONING_FORMATS = {"debugging", "case_study"}
ACTIVE_ASSESSMENT_RECORD_ERROR = "assessment record was not accepted; verify the active session and current question, then retry with a finalized assessment"


class SessionError(ValueError):
    pass


def utc_text(value: datetime) -> str:
    if value.tzinfo is None:
        raise SessionError("clock must return a timezone-aware datetime")
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_utc(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise SessionError(f"invalid persisted UTC timestamp: {value!r}") from exc
    if parsed.tzinfo is None:
        raise SessionError(f"persisted timestamp has no timezone: {value!r}")
    return parsed.astimezone(timezone.utc)


def digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def learner_priority(state: dict[str, Any], question: dict[str, Any]) -> tuple[int, float]:
    context = state.get("learner_context")
    if not context:
        return (1, 1.0)
    matches = [item for item in context["topic_progress"] if item["topic_id"] in question["topic_ids"]]
    if not matches:
        return (1, 1.0)
    started_date = state["started_at"][:10]
    due = 0 if any(item.get("next_review") and item["next_review"] <= started_date for item in matches) else 1
    return (due, min(float(item["mastery"]) for item in matches))


def candidate_identity(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": item["id"],
            "difficulty": item["difficulty"],
            "tier": item["tier"],
            "priority_rank": item["priority_rank"],
            "primary_category": item["primary_category"],
            "primary_format": item["primary_format"],
        }
        for item in sorted(records, key=lambda candidate: candidate["id"])
    ]


def seed_key(seed: str, slot: int, question_id: str) -> str:
    return hashlib.sha256(f"{seed}:{slot}:{question_id}".encode("utf-8")).hexdigest()


def difficulty_distance(candidate: str, requested: str) -> int:
    return abs(DIFFICULTIES.index(candidate) - DIFFICULTIES.index(requested))


def matches_slot(question: dict[str, Any], slot: str) -> bool:
    if slot == "debugging_case_reasoning":
        return question["primary_format"] in REASONING_FORMATS
    return question["primary_category"] == slot


def select_assessment(state: dict[str, Any], records: dict[str, dict[str, Any]]) -> tuple[str, dict[str, Any]]:
    slot_index = len(state["selected_question_ids"])
    target = ASSESSMENT_BLUEPRINT[slot_index % len(ASSESSMENT_BLUEPRINT)]
    remaining = [records[item] for item in state["eligible_candidate_ids"] if item not in state["selected_question_ids"]]
    matching = [item for item in remaining if matches_slot(item, target)]
    reasons = [f"blueprint:{target}"]
    if not matching:
        matching = [item for item in remaining if item["primary_category"] in CORE_CATEGORIES]
        reasons.append("fallback:insufficient_target_category")
    if not matching:
        matching = remaining
        reasons.append("fallback:any_eligible_category")
    if not matching:
        raise SessionError("assessment candidate set is exhausted before the question limit")
    requested = state["difficulty_state"]["current"]
    exact = [item for item in matching if item["difficulty"] == requested]
    if exact:
        matching = exact
        reasons.append(f"difficulty:{requested}")
    else:
        nearest_distance = min(difficulty_distance(item["difficulty"], requested) for item in matching)
        matching = [item for item in matching if difficulty_distance(item["difficulty"], requested) == nearest_distance]
        reasons.append(f"difficulty_fallback:nearest_to_{requested}")
    recent = set(state["history"]["recent_question_ids"])
    unused = [item for item in matching if item["id"] not in recent]
    if unused:
        matching = unused
        reasons.append("history:unused_preferred")
    else:
        reasons.append("history:recent_allowed_no_unused_match")
    matching.sort(
        key=lambda item: (
            *learner_priority(state, item),
            TIER_ORDER[item["tier"]],
            (item["priority_rank"] - 1) // 10,
            seed_key(state["seed"], slot_index, item["id"]),
            item["priority_rank"],
        )
    )
    selected = matching[0]
    if state.get("learner_context"):
        reasons.append("learner_state:due_and_low_mastery_tiebreak")
    decision = {
        "slot_index": slot_index,
        "target": target,
        "question_id": selected["id"],
        "requested_difficulty": requested,
        "selected_difficulty": selected["difficulty"],
        "candidate_count": len(matching),
        "reasons": reasons,
    }
    return selected["id"], decision


def select_practice(
    state: dict[str, Any],
    records: dict[str, dict[str, Any]],
    topic_id: str | None,
    primary_category: str | None = None,
    exclude_selected: bool = True,
) -> tuple[str, dict[str, Any]]:
    candidates = list(records.values())
    reasons = []
    if topic_id:
        candidates = [item for item in candidates if topic_id in item["topic_ids"]]
        reasons.append(f"topic:{topic_id}")
        if not candidates:
            raise SessionError(f"no question matches topic: {topic_id}")
    elif primary_category:
        category_candidates = [item for item in candidates if item["primary_category"] == primary_category]
        if category_candidates:
            candidates = category_candidates
            reasons.append(f"recommendation_category:{primary_category}")
    difficulty = state["difficulty_state"]["current"]
    exact = [item for item in candidates if item["difficulty"] == difficulty]
    if exact:
        candidates = exact
        reasons.append(f"difficulty:{difficulty}")
    if exclude_selected:
        unused_session = [item for item in candidates if item["id"] not in state["selected_question_ids"]]
        if unused_session:
            candidates = unused_session
            reasons.append("session:unused_preferred")
    recent = set(state["history"]["recent_question_ids"])
    unused_history = [item for item in candidates if item["id"] not in recent]
    if unused_history:
        candidates = unused_history
        reasons.append("history:unused_preferred")
    slot = len(state["selection_decisions"])
    candidates.sort(
        key=lambda item: (
            *learner_priority(state, item),
            TIER_ORDER[item["tier"]],
            (item["priority_rank"] - 1) // 10,
            seed_key(state["seed"], slot, item["id"]),
            item["priority_rank"],
        )
    )
    if not candidates:
        raise SessionError("no eligible practice question remains")
    selected = candidates[0]
    if state.get("learner_context"):
        reasons.append("learner_state:due_and_low_mastery_tiebreak")
    return selected["id"], {
        "slot_index": len(state["selected_question_ids"]),
        "target": topic_id or "general_practice",
        "question_id": selected["id"],
        "requested_difficulty": difficulty,
        "selected_difficulty": selected["difficulty"],
        "candidate_count": len(candidates),
        "reasons": reasons,
    }


def transition(sequence: int, event: str, before: str, after: str, at: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "sequence": sequence,
        "at": at,
        "event": event,
        "from_phase": before,
        "to_phase": after,
        "details": dict(details) if details else {},
    }


def validate_final_assessment(value: dict[str, Any]) -> None:
    required = {"schema_version", "question_id", "score", "max_score", "criteria", "summary", "improvement", "deterministic_status"}
    if not required <= set(value) or value.get("schema_version") != 1:
        raise SessionError("assessment is not a finalized assessment object")
    score = value.get("score")
    if not isinstance(score, int) or isinstance(score, bool) or not 0 <= score <= 10 or value.get("max_score") != 10:
        raise SessionError("final assessment score must be an integer from 0 to 10")
    if value.get("deterministic_status") not in {"passed", "failed", "error", "timeout", "not_applicable"}:
        raise SessionError("final assessment has an invalid deterministic status")


def active_assessment_question(question: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": question["id"],
        "title": question["title"],
        "difficulty": question["difficulty"],
        "topic_ids": question["topic_ids"],
        "primary_format": question["primary_format"],
        "primary_category": question["primary_category"],
        "prompt": question["prompt"],
        "submission_contract": question["evaluation"]["submission_contract"],
    }


def adapt_difficulty(difficulty: dict[str, Any], latest_score: int) -> tuple[dict[str, Any], dict[str, Any]]:
    updated = {**difficulty, "evidence_since_change": [*difficulty["evidence_since_change"], latest_score]}
    if updated["lock_remaining"]:
        updated["lock_remaining"] -= 1
        return updated, {"action": "hold", "reason": "post_change_cooldown"}
    if len(updated["evidence_since_change"]) < 2:
        return updated, {"action": "hold", "reason": "insufficient_evidence"}
    evidence = updated["evidence_since_change"][-2:]
    current_index = DIFFICULTIES.index(updated["current"])
    direction = 1 if min(evidence) >= 8 else (-1 if max(evidence) <= 4 else 0)
    if direction == 0 or not 0 <= current_index + direction < len(DIFFICULTIES):
        return updated, {"action": "hold", "reason": "evidence_not_decisive", "scores": evidence}
    before = updated["current"]
    updated["current"] = DIFFICULTIES[current_index + direction]
    updated["evidence_since_change"] = []
    updated["lock_remaining"] = 2
    updated["last_direction"] = "up" if direction > 0 else "down"
    decision = {"action": updated["last_direction"], "from": before, "to": updated["current"], "scores": evidence}
    return updated, decision


def practice_recommendation(attempt: dict[str, Any]) -> dict[str, Any]:
    score = attempt["score"]
    if score <= 4:
        return {"action": "retry", "reason": "score indicates the same question needs another attempt"}
    if score <= 7:
        return {"action": "next", "category": attempt["primary_category"], "reason": "reinforce the same competency at current difficulty"}
    target_index = min(DIFFICULTIES.index(attempt["difficulty"]) + 1, len(DIFFICULTIES) - 1)
    return {"action": "next", "category": attempt["primary_category"], "difficulty": DIFFICULTIES[target_index], "reason": "extend demonstrated competency with a harder nearby question"}


def timing(state: dict[str, Any], ended_at: str) -> dict[str, Any]:
    started = parse_utc(state["started_at"])
    ended = parse_utc(ended_at)
    elapsed = max(0, int((ended - started).total_seconds()))
    allocated = state["duration_minutes"] * 60 if state["duration_minutes"] else None
    return {
        "started_at": state["started_at"],
        "ended_at": ended_at,
        "elapsed_seconds": elapsed,
        "allocated_seconds": allocated,
        "remaining_seconds": max(0, allocated - elapsed) if allocated is not None else None,
    }


def build_report(state: dict[str, Any]) -> dict[str, Any]:
    attempts = state["attempts"]
    by_category: dict[str, list[int]] = defaultdict(list)
    for attempt in attempts:
        by_category[attempt["primary_category"]].append(attempt["score"])
    competency = [
        {
            "category": category,
            "questions": len(scores),
            "average_score": round(sum(scores) / len(scores), 1),
            "score_range": [min(scores), max(scores)],
        }
        for category, scores in sorted(by_category.items())
    ]
    average = round(sum(item["score"] for item in attempts) / len(attempts), 1) if attempts else None
    if state["flow"] == "assessment" and average is not None:
        band = "targeted_interview_ready" if average >= 8 else ("developing_readiness" if average >= 6 else "foundations_need_reinforcement")
        caveat = "Non-certification estimate based only on this session."
        if len(attempts) < 6 or not CORE_CATEGORIES <= set(by_category):
            caveat += " Evidence is limited because the session ended early or did not cover every core category."
    else:
        band = "not_assessed"
        caveat = "Practice results guide learning and are not a readiness assessment or certification."
    deterministic = Counter(item["deterministic_status"] for item in attempts)
    strengths = [item["category"] for item in competency if item["average_score"] >= 8]
    gaps = [item["category"] for item in competency if item["average_score"] < 6]
    return {
        "schema_version": 1,
        "session_id": state["session_id"],
        "flow": state["flow"],
        "mode": state["mode"],
        "completion_reason": state["completion_reason"],
        "timing": timing(state, state["ended_at"]),
        "coverage": {
            "questions_completed": len(attempts),
            "question_limit": state["question_limit"],
            "categories": dict(sorted(Counter(item["primary_category"] for item in attempts).items())),
            "formats": dict(sorted(Counter(item["primary_format"] for item in attempts).items())),
            "difficulties": dict(sorted(Counter(item["difficulty"] for item in attempts).items())),
        },
        "objective_summary": {
            "deterministic_status_counts": dict(sorted(deterministic.items())),
            "note": "Objective checks provide evidence and rubric caps; they do not award a separate objective point total.",
        },
        "subjective_summary": {
            "scale": "0-10 rubric total per question",
            "average": average,
            "minimum": min((item["score"] for item in attempts), default=None),
            "maximum": max((item["score"] for item in attempts), default=None),
            "subjective_scoring_note": "Criterion scores were supplied post-answer by the LLM; deterministic checks supplied evidence and caps, not automatic points.",
        },
        "competency_evidence": competency,
        "strengths": strengths,
        "gaps": gaps,
        "readiness": {"band": band, "caveat": caveat},
        "attempts": attempts,
        "audit": {
            "seed": state["seed"],
            "eligible_candidate_digest": state["eligible_candidate_digest"],
            "selection_decisions": state["selection_decisions"],
            "score_inputs": state["score_inputs"],
            "transition_log": state["transition_log"],
        },
    }
