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
- Follow `docs/workflows.md`; in interview mode never reveal or paraphrase expected concepts, rubric criteria, hints, or solution guidance before answer completion.
- Ask one question at a time. Use original question wording from the selected record.
- Never invent learner history. Read `state/learner.json` when present, otherwise offer `examples/learner.sample.json` only as a demonstration.
- Persist only with user consent. Keep local records authoritative; use Engram only for durable qualitative learning observations.
- Treat `flow` and `mode` separately. Practice never advances after record without an explicit learner action; assessment always advances after an accepted record and never leaks feedback while active.
- In active assessment, never reveal hints, correctness, scores, detailed feedback, rubric content, expected concepts, or solutions. Release the report only after completion.
- Create only the current question's scaffold. Do not precreate future question files or describe answer completion as a Git commit.
- Keep practice feedback in chat. Never write feedback into learner code or add code comments unless the learner explicitly requests comments in the file.
- Never reset scaffold after failure. Practice retry reopens the same non-empty flat question file without recreating, truncating, or copying it.

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
5. After every new current question from practice start, `next`, or `change-topic`, run `interview-coach scaffold <question-id> --output workspace --flat --open`. A relevant `retry` runs the same command and MUST reopen the exact same flat question file with its non-empty bytes preserved. A new question opens its sibling file in `workspace/`. Reuse the exact path printed by the CLI; never put a session ID in a learner-facing directory name.
6. Tell the learner the exact file to edit, then wait for "I am finished" or an equivalent explicit answer completion. This is not a Git commit. Do not evaluate, prepare review, or advance while waiting.
7. For executable questions, use `interview-coach evaluate` only after answer completion. Use `prepare-review` to load the rubric and objective evidence, then return criterion-level scores suitable for `finalize`. For `answer.md` contracts, skip deterministic evaluation and use `prepare-review` directly.
8. If editor opening warns or the client cannot launch VS Code, relay the printed path and manual `code -r <exact-file>` command. Do not fail the interview because editor opening failed.
9. Do not open a file for a genuinely conversational-only contract unless `scaffold` supports it with an `answer_text` Markdown contract.
10. Assessment uses `interview-coach scaffold <question-id> --output workspace --flat --assessment --open` only after package-owned selection. This opens `workspace/assessment-<question-id>.<ext>`, never the practice file. If that assessment file is non-empty, stop and require a fresh assessment workspace or explicit learner cleanup; never reveal, reuse, or reset it silently.
11. Record the finalized assessment with both current session and question IDs. In practice, return feedback in chat and wait without changing learner code. After assessment auto-advance, present only the automatically selected next learner-safe prompt, scaffold its isolated assessment file, and wait again.
12. Finish explicitly or allow package-enforced limit/timeout completion, then use `session report`.

## Output Contract

During practice, return the current prompt or post-answer feedback and remain paused. During active assessment, return only learner-safe status/current/record output. At close, return the released report with evidence caveats and no certification claim.

Local checks are evidence, not points. Never award subjective rubric credit automatically. A failed objective check blocks credit only for the rubric criteria identified by the post-answer evidence contract.

## References

- `../../docs/workflows.md`
- `../../docs/data-model.md`
- `../../docs/curriculum.md`
