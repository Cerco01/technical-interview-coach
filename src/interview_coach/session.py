from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from .bank import learner_safe, questions
from .session_rules import (
    ACTIVE_ASSESSMENT_RECORD_ERROR,
    ASSESSMENT_BLUEPRINT,
    CORE_CATEGORIES,
    DIFFICULTIES,
    REASONING_FORMATS,
    TIER_ORDER,
    SessionError,
    active_assessment_question as _active_assessment_question,
    adapt_difficulty as _adapt_difficulty_rule,
    build_report as _build_report,
    candidate_identity as _candidate_identity,
    difficulty_distance as _difficulty_distance,
    digest,
    learner_priority as _learner_priority,
    matches_slot as _matches_slot,
    parse_utc,
    practice_recommendation as _practice_recommendation,
    seed_key as _seed_key,
    select_assessment as _select_assessment,
    select_practice as _select_practice,
    timing as _timing,
    transition as _transition_rule,
    utc_text,
    validate_final_assessment as _validate_final_assessment,
)

Clock = Callable[[], datetime]


def system_clock() -> datetime:
    return datetime.now(timezone.utc)


def read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SessionError(f"{path}: {exc}") from exc
    if not isinstance(value, dict):
        raise SessionError(f"{path}: expected a JSON object")
    return value


class SessionStore:
    def __init__(self, state_path: Path, sessions_dir: Path):
        self.state_path = state_path
        self.sessions_dir = sessions_dir

    def load(self) -> dict[str, Any]:
        state = read_object(self.state_path)
        required = {"schema_version", "session_id", "status", "revision", "transition_log"}
        if state.get("schema_version") != 1 or not required <= set(state):
            raise SessionError(f"{self.state_path}: malformed or incompatible active session state")
        if state["status"] != "active":
            raise SessionError(f"{self.state_path}: stale completed state conflicts with a new active session")
        return state

    def _atomic_write(self, path: Path, value: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
            # Replacement is the commit point. Directory sync strengthens crash
            # durability, but failure here must not make a committed write look rejected.
            try:
                directory_fd = os.open(path.parent, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            except OSError:
                pass
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise

    def create(self, state: dict[str, Any]) -> None:
        if self.state_path.exists():
            self.load()
            raise SessionError(f"active session already exists: {self.state_path}")
        self._atomic_write(self.state_path, state)

    def save(self, state: dict[str, Any], expected_revision: int) -> None:
        current = self.load()
        if current["session_id"] != state["session_id"] or current["revision"] != expected_revision:
            raise SessionError("active session changed in another process; reload before retrying")
        state["revision"] = expected_revision + 1
        self._atomic_write(self.state_path, state)

    def archive(self, state: dict[str, Any], expected_revision: int) -> Path:
        current = self.load()
        if current["session_id"] != state["session_id"] or current["revision"] != expected_revision:
            raise SessionError("active session changed in another process; reload before finishing")
        state["revision"] = expected_revision + 1
        destination = self.sessions_dir / f"{state['session_id']}.json"
        if destination.exists():
            existing = read_object(destination)
            if existing != state:
                raise SessionError(f"completed session archive already exists with different content: {destination}")
        else:
            self._atomic_write(destination, state)
        self.state_path.unlink()
        return destination

    def completed(self, session_id: str | None = None) -> dict[str, Any]:
        if session_id:
            path = self.sessions_dir / f"{session_id}.json"
        else:
            paths = sorted(self.sessions_dir.glob("session-*.json"), key=lambda item: item.stat().st_mtime)
            if not paths:
                raise SessionError(f"no completed sessions found in {self.sessions_dir}")
            path = paths[-1]
        state = read_object(path)
        if state.get("status") != "completed" or not isinstance(state.get("report"), dict):
            raise SessionError(f"{path}: malformed completed session")
        return state


def default_paths(state: Path | None = None, data_dir: Path | None = None) -> SessionStore:
    if state and data_dir:
        raise SessionError("use either --state or --data-dir, not both")
    if data_dir:
        root = data_dir
        state_path = root / "state/active-session.json"
    elif state:
        state_path = state
        root = state.parent.parent if state.parent.name == "state" else state.parent
    else:
        root = Path(os.environ.get("INTERVIEW_COACH_DATA_DIR", Path.cwd()))
        state_path = root / "state/active-session.json"
    return SessionStore(state_path, root / "sessions")


def _history_records(sessions_dir: Path) -> tuple[list[str], list[str]]:
    attempted: list[str] = []
    sources: list[str] = []
    for path in sorted(sessions_dir.glob("*")):
        if path.suffix not in {".json", ".jsonl"} or not path.is_file():
            continue
        try:
            values = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] if path.suffix == ".jsonl" else [json.loads(path.read_text(encoding="utf-8"))]
        except (OSError, json.JSONDecodeError):
            continue
        used = []
        for value in values:
            if not isinstance(value, dict):
                continue
            for attempt in value.get("attempts", value.get("question_attempts", [])):
                if isinstance(attempt, dict) and isinstance(attempt.get("question_id"), str):
                    used.append(attempt["question_id"])
        if used:
            sources.append(path.name)
            attempted.extend(used)
    return attempted[-24:], sources


def _learner_context(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.exists():
        return None
    value = read_object(path)
    progress = value.get("topic_progress")
    if value.get("schema_version") != 1 or not isinstance(progress, list):
        raise SessionError(f"{path}: malformed or incompatible learner state")
    normalized = []
    for item in progress:
        if not isinstance(item, dict) or not isinstance(item.get("topic_id"), str):
            raise SessionError(f"{path}: malformed topic progress")
        mastery = item.get("mastery")
        if not isinstance(mastery, (int, float)) or isinstance(mastery, bool) or not 0 <= mastery <= 1:
            raise SessionError(f"{path}: invalid topic mastery")
        normalized.append({"topic_id": item["topic_id"], "mastery": mastery, "next_review": item.get("next_review")})
    return {"source": path.name, "digest": digest(normalized), "topic_progress": normalized}


def _transition(state: dict[str, Any], event: str, before: str, after: str, at: str, details: dict[str, Any] | None = None) -> None:
    entry = _transition_rule(len(state["transition_log"]), event, before, after, at, details)
    state["transition_log"].append(entry)


def _adapt_difficulty(state: dict[str, Any]) -> dict[str, Any]:
    difficulty, decision = _adapt_difficulty_rule(state["difficulty_state"], state["attempts"][-1]["score"])
    state["difficulty_state"] = difficulty
    return decision


class SessionService:
    def __init__(self, store: SessionStore, clock: Clock = system_clock, bank: dict[str, dict[str, Any]] | None = None):
        self.store = store
        self.clock = clock
        self.bank = bank or questions()

    def _now(self) -> tuple[datetime, str]:
        value = self.clock()
        return value, utc_text(value)

    def start(
        self,
        flow: str,
        mode: str = "study",
        seed: str = "interview-coach",
        question_limit: int | None = None,
        duration_minutes: int | None = None,
        difficulty: str = "intermediate",
        topic_id: str | None = None,
        learner_state: Path | None = None,
    ) -> dict[str, Any]:
        if flow not in {"practice", "assessment"}:
            raise SessionError("flow must be practice or assessment")
        if mode not in {"interview", "study", "review"}:
            raise SessionError("mode must be interview, study, or review")
        if difficulty not in DIFFICULTIES:
            raise SessionError("difficulty must be beginner, intermediate, or advanced")
        if flow == "assessment":
            if mode != "interview":
                raise SessionError("assessment flow requires interview pedagogical mode")
            question_limit = 12 if question_limit is None else question_limit
            duration_minutes = 75 if duration_minutes is None else duration_minutes
            if not 5 <= question_limit <= 30:
                raise SessionError("assessment question limit must be from 5 to 30")
            if not 15 <= duration_minutes <= 180:
                raise SessionError("assessment duration must be from 15 to 180 minutes")
        else:
            if question_limit is not None or duration_minutes is not None:
                raise SessionError("--questions and --minutes configure assessment flow only")
            question_limit = 0
            duration_minutes = 0
        now, now_text = self._now()
        history, sources = _history_records(self.store.sessions_dir)
        if learner_state is None:
            learner_state = self.store.state_path.parent / "learner.json" if self.store.state_path.parent.name == "state" else None
        learner = _learner_context(learner_state)
        identities = _candidate_identity(self.bank.values())
        session_id = f"session-{now.strftime('%Y%m%d-%H%M%S')}-{digest([seed, now_text])[:8]}"
        state: dict[str, Any] = {
            "schema_version": 1,
            "session_id": session_id,
            "flow": flow,
            "mode": mode,
            "status": "active",
            "phase": "answering",
            "revision": 0,
            "seed": seed,
            "started_at": now_text,
            "deadline_at": utc_text(now + timedelta(minutes=duration_minutes)) if duration_minutes else None,
            "ended_at": None,
            "question_limit": question_limit,
            "duration_minutes": duration_minutes,
            "hints_allowed": flow == "practice" and mode in {"study", "review"},
            "current_question_id": None,
            "selected_question_ids": [],
            "eligible_candidate_ids": [item["id"] for item in identities],
            "eligible_candidate_digest": digest(identities),
            "history": {"recent_question_ids": history, "source_files": sources},
            "learner_context": learner,
            "difficulty_state": {"current": difficulty, "evidence_since_change": [], "lock_remaining": 0, "last_direction": None},
            "attempts": [],
            "selection_decisions": [],
            "score_inputs": [],
            "transition_log": [],
            "practice": {"topic_id": topic_id, "recommendation": None, "retry_count": 0, "pending_action": None},
            "completion_reason": None,
            "report": None,
        }
        if flow == "assessment":
            question_id, decision = _select_assessment(state, self.bank)
        else:
            question_id, decision = _select_practice(state, self.bank, topic_id, exclude_selected=False)
        state["current_question_id"] = question_id
        state["selected_question_ids"].append(question_id)
        state["selection_decisions"].append(decision)
        _transition(state, "session_started", "none", "answering", now_text, {"question_id": question_id, "flow": flow})
        self.store.create(state)
        return self._status_projection(state, now)

    def _load_active(self) -> tuple[dict[str, Any], datetime]:
        state = self.store.load()
        now, _ = self._now()
        if state["flow"] == "assessment" and state["deadline_at"] and now >= parse_utc(state["deadline_at"]):
            return self._complete(state, "time_expired", now), now
        return state, now

    def _complete(self, state: dict[str, Any], reason: str, now: datetime) -> dict[str, Any]:
        if state["status"] == "completed":
            return state
        now_text = utc_text(now)
        revision = state["revision"]
        before = state["phase"]
        state["status"] = "completed"
        state["phase"] = "completed"
        state["ended_at"] = now_text
        state["completion_reason"] = reason
        _transition(state, "session_completed", before, "completed", now_text, {"reason": reason})
        state["report"] = _build_report(state)
        self.store.archive(state, revision)
        return state

    def _status_projection(self, state: dict[str, Any], now: datetime) -> dict[str, Any]:
        elapsed = max(0, int((now - parse_utc(state["started_at"])).total_seconds()))
        remaining = max(0, int((parse_utc(state["deadline_at"]) - now).total_seconds())) if state["deadline_at"] else None
        result = {
            "schema_version": 1,
            "session_id": state["session_id"],
            "flow": state["flow"],
            "mode": state["mode"],
            "status": state["status"],
            "phase": state["phase"],
            "current_question_id": state["current_question_id"] if state["status"] == "active" else None,
            "questions_completed": len(state["attempts"]),
            "question_limit": state["question_limit"],
            "elapsed_seconds": elapsed,
            "remaining_seconds": remaining,
        }
        if state["flow"] == "practice":
            result["hints_allowed"] = state["hints_allowed"]
            result["recommendation"] = state["practice"]["recommendation"]
            if state["attempts"] and state["phase"] == "paused":
                assessment = state["attempts"][-1]["assessment"]
                result["feedback"] = {key: assessment[key] for key in ("score", "max_score", "summary", "improvement")}
        if state["status"] == "completed":
            result["completion_reason"] = state["completion_reason"]
            result["report_available"] = True
        return result

    def status(self) -> dict[str, Any]:
        state, now = self._load_active()
        return self._status_projection(state, now)

    def current(self) -> dict[str, Any]:
        state, now = self._load_active()
        if state["status"] != "active":
            return self._status_projection(state, now)
        result = self._status_projection(state, now)
        question = self.bank[state["current_question_id"]]
        result["question"] = _active_assessment_question(question) if state["flow"] == "assessment" else learner_safe(question)
        return result

    def record(self, session_id: str, question_id: str, assessment_path: Path) -> dict[str, Any]:
        state, now = self._load_active()
        if state["status"] != "active":
            raise SessionError(f"session completed before the assessment could be recorded: {state['completion_reason']}")
        try:
            assessment = read_object(assessment_path)
            _validate_final_assessment(assessment)
            assessment_id = digest(assessment)
            record_id = digest([session_id, question_id, assessment_id])
            prior = next((item for item in state["attempts"] if item["record_id"] == record_id), None)
            if prior:
                result = self._status_projection(state, now)
                result.update({"accepted": True, "idempotent": True, "record_id": record_id})
                return result
            if session_id != state["session_id"]:
                raise SessionError("record session_id does not match the active session")
            if question_id != state["current_question_id"] or assessment.get("question_id") != question_id:
                raise SessionError("record question_id and assessment must match the active question")
            if state["phase"] != "answering":
                raise SessionError("current question is already finalized; choose an explicit practice action")
            question = self.bank[question_id]
        except Exception:
            if state["flow"] == "assessment":
                raise SessionError(ACTIVE_ASSESSMENT_RECORD_ERROR) from None
            raise
        now_text = utc_text(now)
        attempt = {
            "record_id": record_id,
            "assessment_id": assessment_id,
            "question_id": question_id,
            "recorded_at": now_text,
            "score": assessment["score"],
            "max_score": 10,
            "primary_category": question["primary_category"],
            "primary_format": question["primary_format"],
            "difficulty": question["difficulty"],
            "deterministic_status": assessment["deterministic_status"],
            "assessment": assessment,
        }
        revision = state["revision"]
        state["attempts"].append(attempt)
        state["score_inputs"].append({"question_id": question_id, "assessment_id": assessment_id, "score": assessment["score"], "recorded_at": now_text})
        if state["flow"] == "practice":
            state["phase"] = "paused"
            state["practice"]["recommendation"] = _practice_recommendation(attempt)
            state["practice"]["pending_action"] = None
            _transition(state, "answer_recorded", "answering", "paused", now_text, {"question_id": question_id, "record_id": record_id})
            self.store.save(state, revision)
            result = self._status_projection(state, now)
            result.update({"accepted": True, "idempotent": False, "record_id": record_id})
            return result
        adaptation = _adapt_difficulty(state)
        _transition(state, "answer_recorded", "answering", "advancing", now_text, {"question_id": question_id, "record_id": record_id, "adaptation": adaptation})
        if len(state["attempts"]) >= state["question_limit"]:
            completed = self._complete(state, "question_limit", now)
            result = self._status_projection(completed, now)
            result.update({"accepted": True, "idempotent": False, "record_id": record_id})
            return result
        next_question, decision = _select_assessment(state, self.bank)
        state["current_question_id"] = next_question
        state["selected_question_ids"].append(next_question)
        state["selection_decisions"].append(decision)
        state["phase"] = "answering"
        _transition(state, "question_auto_advanced", "advancing", "answering", now_text, {"question_id": next_question})
        self.store.save(state, revision)
        result = self._status_projection(state, now)
        result.update({"accepted": True, "idempotent": False, "record_id": record_id})
        return result

    def _practice_state(self) -> tuple[dict[str, Any], datetime]:
        state, now = self._load_active()
        if state["status"] != "active" or state["flow"] != "practice":
            raise SessionError("command requires an active practice session")
        return state, now

    def next(self) -> dict[str, Any]:
        state, now = self._practice_state()
        if state["phase"] != "paused":
            raise SessionError("practice advances only after a finalized answer and explicit next action")
        revision = state["revision"]
        before_question = state["current_question_id"]
        recommendation = state["practice"]["recommendation"] or {}
        if recommendation.get("difficulty") in DIFFICULTIES:
            state["difficulty_state"]["current"] = recommendation["difficulty"]
        category = recommendation.get("category") if not state["practice"]["topic_id"] else None
        question_id, decision = _select_practice(state, self.bank, state["practice"]["topic_id"], category)
        state["current_question_id"] = question_id
        state["selected_question_ids"].append(question_id)
        state["selection_decisions"].append(decision)
        state["phase"] = "answering"
        state["practice"]["recommendation"] = None
        _transition(state, "practice_next", "paused", "answering", utc_text(now), {"from_question_id": before_question, "question_id": question_id})
        self.store.save(state, revision)
        return self.current()

    def retry(self) -> dict[str, Any]:
        state, now = self._practice_state()
        if state["phase"] != "paused":
            raise SessionError("retry requires a finalized practice question")
        revision = state["revision"]
        state["phase"] = "answering"
        state["practice"]["retry_count"] += 1
        state["practice"]["recommendation"] = None
        _transition(state, "practice_retry", "paused", "answering", utc_text(now), {"question_id": state["current_question_id"]})
        self.store.save(state, revision)
        return self.current()

    def change_topic(self, topic_id: str) -> dict[str, Any]:
        state, now = self._practice_state()
        if state["phase"] != "paused":
            raise SessionError("change-topic requires a finalized practice question")
        revision = state["revision"]
        question_id, decision = _select_practice(state, self.bank, topic_id)
        state["practice"]["topic_id"] = topic_id
        state["practice"]["recommendation"] = None
        state["current_question_id"] = question_id
        state["selected_question_ids"].append(question_id)
        state["selection_decisions"].append(decision)
        state["phase"] = "answering"
        _transition(state, "practice_topic_changed", "paused", "answering", utc_text(now), {"topic_id": topic_id, "question_id": question_id})
        self.store.save(state, revision)
        return self.current()

    def explain(self) -> dict[str, Any]:
        state, now = self._practice_state()
        if state["phase"] != "paused":
            raise SessionError("explain requires a finalized practice question")
        revision = state["revision"]
        state["practice"]["pending_action"] = "explain"
        _transition(state, "practice_explanation_requested", "paused", "paused", utc_text(now), {"question_id": state["current_question_id"]})
        self.store.save(state, revision)
        return {
            "session_id": state["session_id"],
            "action": "explain",
            "question_id": state["current_question_id"],
            "instruction": "The LLM may now explain the finalized answer using post-answer context. Keep the session paused until the learner chooses next, retry, change-topic, or finish.",
            "phase": "paused",
        }

    def finish(self) -> dict[str, Any]:
        state, now = self._load_active()
        if state["status"] != "active":
            return self._status_projection(state, now)
        completed = self._complete(state, "user_finished", now)
        return self._status_projection(completed, now)

    def report(self, session_id: str | None = None) -> dict[str, Any]:
        if self.store.state_path.exists():
            state, _ = self._load_active()
            if state["flow"] == "assessment" and state["status"] == "active" and (session_id is None or session_id == state["session_id"]):
                raise SessionError("assessment report is withheld until the session is completed")
        return self.store.completed(session_id)["report"]
