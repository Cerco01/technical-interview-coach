from __future__ import annotations

from typing import Literal, NotRequired, TypedDict


Difficulty = Literal["beginner", "intermediate", "advanced"]
Flow = Literal["practice", "assessment"]
Mode = Literal["interview", "study", "review"]
SessionStatus = Literal["active", "completed"]
SessionPhase = Literal["answering", "paused", "completed"]
DeterministicStatus = Literal["passed", "failed", "error", "timeout", "not_applicable"]
CompletionReason = Literal["question_limit", "time_expired", "user_finished", "unrecoverable_state"]
Tier = Literal["core", "differentiator", "specialized"]
QuestionFormat = Literal[
    "implementation",
    "sql_query",
    "debugging",
    "conceptual_reasoning",
    "case_study",
    "data_manipulation",
]
EvaluationStrategy = Literal["executable", "sql", "dataframe", "numeric", "rubric_only"]
SubmissionKind = Literal["python_module", "sql_query", "answer_text"]


class SubmissionContract(TypedDict):
    kind: SubmissionKind
    filename: str
    entrypoint: NotRequired[str]
    signature: NotRequired[str]
    returns: NotRequired[str]
    columns: NotRequired[list[str]]


class QuestionEvaluation(TypedDict):
    strategy: EvaluationStrategy
    submission_contract: SubmissionContract
    evaluator_ref: str | None
    objective_criteria: list[int]


class RubricCriterion(TypedDict):
    criterion: str
    points: int


class Question(TypedDict):
    schema_version: int
    id: str
    title: str
    difficulty: Difficulty
    topic_ids: list[str]
    priority_rank: int
    tier: Tier
    primary_format: QuestionFormat
    primary_category: str
    prompt: str
    evaluation: QuestionEvaluation
    expected_concepts: list[str]
    rubric: list[RubricCriterion]
    hints: list[str]
    follow_ups: list[str]


QuestionBank = dict[str, Question]


class CandidateIdentity(TypedDict):
    id: str
    difficulty: Difficulty
    tier: Tier
    priority_rank: int
    primary_category: str
    primary_format: QuestionFormat


class AssessmentCriterion(TypedDict):
    criterion_index: int
    criterion: str
    awarded_points: int
    max_points: int
    evidence: str


class FinalAssessment(TypedDict):
    schema_version: int
    question_id: str
    score: int
    max_score: int
    criteria: list[AssessmentCriterion]
    summary: str
    improvement: str
    deterministic_status: DeterministicStatus


class Attempt(TypedDict):
    record_id: str
    assessment_id: str
    question_id: str
    recorded_at: str
    score: int
    max_score: int
    primary_category: str
    primary_format: QuestionFormat
    difficulty: Difficulty
    deterministic_status: DeterministicStatus
    assessment: FinalAssessment


class SelectionDecision(TypedDict):
    slot_index: int
    target: str
    question_id: str
    requested_difficulty: Difficulty
    selected_difficulty: Difficulty
    candidate_count: int
    reasons: list[str]


class TransitionEntry(TypedDict):
    schema_version: int
    sequence: int
    at: str
    event: str
    from_phase: str
    to_phase: str
    details: dict[str, object]


class DifficultyState(TypedDict):
    current: Difficulty
    evidence_since_change: list[int]
    lock_remaining: int
    last_direction: Literal["up", "down"] | None


AdaptationDecision = TypedDict(
    "AdaptationDecision",
    {
        "action": Literal["hold", "up", "down"],
        "reason": NotRequired[str],
        "scores": NotRequired[list[int]],
        "from": NotRequired[Difficulty],
        "to": NotRequired[Difficulty],
    },
)


class PracticeRecommendation(TypedDict):
    action: Literal["retry", "next"]
    reason: str
    category: NotRequired[str]
    difficulty: NotRequired[Difficulty]


class SessionHistory(TypedDict):
    recent_question_ids: list[str]
    source_files: list[str]


class TopicProgress(TypedDict):
    topic_id: str
    mastery: int | float
    next_review: str | None


class LearnerContext(TypedDict):
    source: str
    digest: str
    topic_progress: list[TopicProgress]


class ScoreInput(TypedDict):
    question_id: str
    assessment_id: str
    score: int
    recorded_at: str


class PracticeState(TypedDict):
    topic_id: str | None
    recommendation: PracticeRecommendation | None
    retry_count: int
    pending_action: Literal["explain"] | None


class SessionReport(TypedDict):
    schema_version: int
    session_id: str
    flow: Flow
    mode: Mode
    completion_reason: CompletionReason
    timing: dict[str, object]
    coverage: dict[str, object]
    objective_summary: dict[str, object]
    subjective_summary: dict[str, object]
    competency_evidence: list[dict[str, object]]
    strengths: list[str]
    gaps: list[str]
    readiness: dict[str, str]
    attempts: list[Attempt]
    audit: dict[str, object]


class SessionState(TypedDict):
    schema_version: int
    session_id: str
    flow: Flow
    mode: Mode
    status: SessionStatus
    phase: SessionPhase
    revision: int
    seed: str
    started_at: str
    deadline_at: str | None
    ended_at: str | None
    question_limit: int
    duration_minutes: int
    hints_allowed: bool
    current_question_id: str | None
    selected_question_ids: list[str]
    eligible_candidate_ids: list[str]
    eligible_candidate_digest: str
    history: SessionHistory
    learner_context: LearnerContext | None
    difficulty_state: DifficultyState
    attempts: list[Attempt]
    selection_decisions: list[SelectionDecision]
    score_inputs: list[ScoreInput]
    transition_log: list[TransitionEntry]
    practice: PracticeState
    completion_reason: CompletionReason | None
    report: SessionReport | None
