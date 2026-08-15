# Canonical Data Model

Local UTF-8 files are the source of truth. JSON is used for bounded documents, JSONL for append-friendly record collections, and JSON Schema documents the interoperable contracts.

## Records

| Record | Canonical location | Contract |
| --- | --- | --- |
| Topic | `curriculum/topics.json` | Validated by `scripts/validate.py` |
| Question | `data/questions/*.jsonl` | `schemas/question.schema.json` |
| Deterministic evidence | User-selected JSON file | `schemas/evidence.schema.json` |
| Post-answer review context | User-selected JSON file | `schemas/review-context.schema.json` |
| Final assessment | User-selected JSON file | `schemas/assessment.schema.json` |
| Active deterministic session | `state/active-session.json` or `--state` | `schemas/active-session.schema.json` |
| Session transition | Embedded in active/completed state | `schemas/transition.schema.json` |
| Completed session | `sessions/<session-id>.json` | `schemas/session.schema.json` |
| Released report | Embedded in completed session | `schemas/report.schema.json` |
| Legacy practice session | One JSON object per line in `sessions/*.jsonl` | `schemas/session.schema.json` version 1 compatibility |
| Learner progress | `state/learner.json` | `schemas/progress.schema.json` |

Examples under `examples/` are committed fixtures, not live learner data.

## Identity And Time

- IDs are lowercase, hyphenated, and immutable after publication.
- Question IDs use `q-<bank>-<number>`; session IDs use `session-<date>-<suffix>`.
- All cross-record links use IDs, never array positions or display names.
- Timestamps use RFC 3339 UTC strings. Calendar-only review dates use `YYYY-MM-DD`.
- Finalized records bind the caller-supplied session ID, active question ID, assessment question ID, and a stable assessment digest. Replaying the same identity is idempotent; mismatches are rejected.

## Question Priority

The initial bank contains exactly 50 question-schema version 3 records. `priority_rank` is globally unique and contiguous from 1 (highest interview value) through 50. `tier` is one of `core`, `differentiator`, or `specialized`; `primary_format` and `primary_category` are stable enums used to validate bank balance. A question may reference several supporting topics, but its primary category is singular.

Each question declares an evaluation strategy, public submission contract, optional package-private evaluator reference, and the rubric-criterion indices covered by objective checks. Evaluator references and objective mappings are post-answer internals and are excluded from learner-safe CLI output.

Selection first respects topic, difficulty, learner due or unused state, and prerequisites. Rank and tier order otherwise eligible questions; they do not override learner evidence.

## Progress Semantics

`mastery` is a value from 0 to 1 based on accumulated evidence, not one answer. `attempts` and `correct` are monotonic counters. `confidence` is the learner's self-report from 1 to 5. `next_review` may be `null` when no review has been scheduled.

Session state carries a monotonically increasing revision. Writers compare the persisted session ID and revision before replacing state, write a same-directory temporary file, flush it, and atomically replace the previous file. Completion writes the archive before removing active state. A failed replacement leaves the prior state intact.

The active record persists seed, candidate IDs and digest, selection decisions and reasons, score inputs, difficulty evidence/cooldown, attempts, and transitions. Assessment details are intentionally present in private state but projected out of learner-facing active output. Completed reports may release those details. `objective_summary` reports deterministic evidence/caps without inventing objective points; `subjective_summary` reports the finalized 0-10 rubric totals.

The coach may update learner progress only from completed evidence. Engram can retain qualitative learning observations, but it must not silently replace canonical local records or create attempted-question history.

## Evolution Rules

1. Add optional fields freely only when old records remain valid.
2. Increment `schema_version` for breaking shape or semantic changes.
3. Never reuse a removed topic or question ID for a different concept.
4. Run `python3 scripts/validate.py` before relying on edited data.

SQLite is used only for fresh deterministic SQL fixtures. Canonical curriculum, question, learner, session, and evaluation records remain file-first; no persistent database or migration layer is required.

Structured deterministic selection is intentional: the bounded 50-question bank already has curated eligibility and ranking metadata. RAG would reduce replayability without solving a current retrieval problem. Reconsider it only when a substantially larger or unstructured corpus makes metadata curation insufficient and retrieval quality can be evaluated against a fixed benchmark.
