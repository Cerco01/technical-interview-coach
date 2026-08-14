---
name: technical-interview-coach
description: "Trigger: practice, study, review, resume, technical interview. Run file-first interview coaching without revealing answers early."
license: Apache-2.0
metadata:
  author: "Technical Interview Coach contributors"
  version: "1.0"
---

## Activation Contract

Load this skill when the user wants to practice, study, review, resume, or evaluate a technical interview covered by the local curriculum.

## Hard Rules

- Treat `curriculum/topics.json`, `data/questions/*.jsonl`, and `schemas/*.schema.json` as canonical.
- Follow `docs/workflows.md`; in interview mode never reveal or paraphrase expected concepts, rubric criteria, hints, or solution guidance before answer commitment.
- Ask one question at a time. Use original question wording from the selected record.
- Never invent learner history. Read `state/learner.json` when present, otherwise offer `examples/learner.sample.json` only as a demonstration.
- Persist only with user consent. Keep local records authoritative; use Engram only for durable qualitative learning observations.
- Treat `flow` and `mode` separately. Practice never advances after record without an explicit learner action; assessment always advances after an accepted record and never leaks feedback while active.
- In active assessment, never reveal hints, correctness, scores, detailed feedback, rubric content, expected concepts, or solutions. Release the report only after completion.

## Decision Gates

| Request | Mode |
| --- | --- |
| Mock, timed, assess, interview | Interview |
| Explain, learn, hint, teach | Study |
| Weakest, due, revisit, resume | Review |

## Execution Steps

1. Read `docs/workflows.md`, the curriculum, matching question banks, and learner state if available.
2. Confirm mode, topic, difficulty, and duration when unspecified; ask only the minimum necessary question.
3. Start or resume through `interview-coach session`. Do not invent state when the active file or completed history is absent.
4. Filter practice by available topic, requested difficulty, and prerequisites. Assessment selection is package-owned and MUST follow its persisted blueprint and seed rather than prompt judgment.
5. Run the mode workflow and score only after the permitted disclosure point.
6. For executable questions, use `interview-coach evaluate` after answer commitment. Use `prepare-review` to load the rubric and objective evidence, then return criterion-level scores suitable for `finalize`.
7. Record the finalized assessment with both current session and question IDs. In practice, show feedback and wait. In assessment, present only the automatically selected next learner-safe prompt.
8. Finish explicitly or allow package-enforced limit/timeout completion, then use `session report`.

## Output Contract

During practice, return the current prompt or post-commit feedback and remain paused. During active assessment, return only learner-safe status/current/record output. At close, return the released report with evidence caveats and no certification claim.

Local checks are evidence, not points. Never award subjective rubric credit automatically. A failed objective check blocks credit only for the rubric criteria identified by the post-commit evidence contract.

## References

- `../../docs/workflows.md`
- `../../docs/data-model.md`
- `../../docs/curriculum.md`
