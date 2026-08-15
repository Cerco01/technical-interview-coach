# Coaching Workflows

Choose a session flow and pedagogical mode before selecting a question. The flow controls advancement and disclosure; the mode controls coaching behavior. Ask one question at a time and use canonical IDs in every persisted result.

## Session Flows

| Flow | Advancement | Active feedback | Hints | Completion |
| --- | --- | --- | --- | --- |
| Practice | Learner explicitly chooses the next action | Immediate after finalization | Allowed by study/review rules | Learner finish or configured limit/time |
| Assessment | Automatically advances after a bound finalized record | Withheld until completion | Never | 12-question/75-minute default, user finish, timeout, or unrecoverable state |

Practice actions are `next`, `retry`, `explain`, `change-topic`, and `finish`. Recording a practice answer MUST leave the session paused. `explain` records an LLM-handled post-answer action and MUST NOT advance.

For every newly current question, create only its submission file in `submissions/<session-id>/<question-id>/`. Practice start, `next`, `change-topic`, and a relevant `retry` trigger this lifecycle; assessment record auto-advance does the same. These are ignored, session-specific and question-specific learner files. Do not precreate later questions.

```bash
interview-coach scaffold <question-id> \
  --output submissions/<session-id>/<question-id> \
  --open
```

The command always prints the exact file path. A missing file or an existing empty file receives the learner-safe template; an existing non-empty file is returned unchanged. Directory, symlink, and unsafe filename collisions fail without modifying learner work. `--open` runs `code -r <exact-file>` so a VS Code integrated terminal reuses the current window. If the editor command is missing or fails, scaffold creation still succeeds: relay the printed path, open it manually, or run VS Code's **Shell Command: Install 'code' command in PATH**. Other clients remain fully functional because the path is standard output.

Assessment uses interview mode, begins at intermediate difficulty, and accepts 5-30 questions and 15-180 minutes. Twelve questions at 75 minutes is the standard configuration and generally takes approximately 60-75 minutes depending on response speed.

### Assessment Blueprint

The standard 12 slots are ordered as follows so coverage is maintained even when difficulty changes:

1. Python/algorithms
2. SQL
3. Pandas
4. Probability/statistics
5. ML/evaluation
6. NumPy
7. Debugging or case reasoning
8. Python/algorithms
9. SQL
10. Pandas
11. Probability/statistics
12. ML/evaluation

For each slot, filter by the slot, requested difficulty, unused session IDs, and observed completed-session history. Prefer an unattempted match when real history exists. If a valid learner state exists, due and lower-mastery matching topics provide a deterministic tie-break. Then order by tier, rank decile, seeded hash, and exact rank. If the target category is empty, fall back to unselected core-category questions; if that set is empty, use any unselected eligible question. Persist every fallback reason and the learner-state digest, never invented progress.

The eligible candidate identity includes question ID, category, format, difficulty, tier, and priority rank. Persist the complete eligible ID set and its SHA-256 digest, seed, selection decisions, finalized score inputs, and transition log. This supports replay without storing prompts, chats, or invented learner history.

### Adaptive Difficulty

- Start at `intermediate` unless explicitly configured.
- Raise one level only when the two most recent eligible scores are both at least 8/10.
- Lower one level only when both are at most 4/10.
- Hold when evidence is mixed, insufficient, or already at a boundary.
- After a change, lock adaptation for two scored questions. A reversal therefore needs new sustained evidence and cannot oscillate question by question.

Difficulty never overrides the category slot. If the requested level is unavailable, choose the nearest available level and persist that fallback.

### Practice Recommendation

- Score 0-4: recommend retrying the same question.
- Score 5-7: recommend another question in the same primary category and current difficulty.
- Score 8-10: recommend the same category one difficulty higher, capped at advanced.

The recommendation is advisory and persisted. Advancement still requires an explicit learner action. An explicit topic remains stronger than a category recommendation.

### Assessment Disclosure

During an active assessment, learner-facing output contains only session timing/progress, the current learner-safe prompt, and record acceptance. It MUST NOT contain hints, scores, correctness, criterion feedback, rubrics, expected concepts, solutions, summaries, or improvements. Finalized details remain private local state for the eventual report.

## Interview Mode

1. Agree on topic, difficulty, duration, and whether clarifying questions are allowed.
2. Select an eligible matching question from an `available` topic. Prefer unused questions, then lower `priority_rank` and `core` tier material while respecting difficulty and prerequisites.
3. Present only the question `prompt` and relevant constraints.
4. Scaffold the current answer, give the learner the exact path, and wait for "I am finished" or equivalent.
5. Use neutral clarification, not directional coaching.
6. After answer completion, run deterministic evaluation when declared, then score against the rubric using the answer and objective evidence. This boundary is not a Git commit. Explain gaps and ask at most two follow-ups.
7. Summarize evidence and propose the next topic or review date.

### Non-Disclosure Guardrail

Before the learner finishes the answer, do not quote, paraphrase, enumerate, or confirm `expected_concepts`, rubric criteria, hints, solution reasoning, or follow-up answers. If the learner asks for help, offer one choice: continue unaided or convert the current question to study mode. Record the mode change. A factual clarification may define ambiguous wording but must not narrow the solution.

## Study Mode

1. Establish what the learner already understands.
2. Present a question and allow the learner to attempt it.
3. Release hints in array order, one at a time, only after an attempt or request.
4. Explain the underlying concept, then ask the learner to restate or apply it.
5. Evaluate with the rubric and identify one concrete improvement.

Study mode may expose expected concepts after the initial attempt. Prefer reasoning and small examples over immediately giving a finished answer.

## Review Mode

1. Read the learner profile and choose topics that are overdue, lowest-mastery, or lowest-confidence.
2. Prefer due questions, then questions not used in recent sessions. Within equally eligible material, use lower `priority_rank` and `core` tier first.
3. Begin without notes. If recall fails, switch to study behavior and record that support was needed.
4. Update attempts, correctness evidence, confidence, mastery, and `next_review`.

## Session Close

Write the completed session atomically under `sessions/` before removing `state/active-session.json`. Reports contain competency evidence by category, category/format/difficulty coverage, an objective deterministic-status summary, a subjective 0-10 rubric score summary, persisted timing, strengths, gaps, and a non-certification readiness band.

Assessment readiness bands use the session mean without claiming psychometric precision: at least 8 is `targeted_interview_ready`, 6-7.9 is `developing_readiness`, and below 6 is `foundations_need_reinforcement`. Fewer than six scored questions or missing core categories adds a limited-evidence caveat. Practice reports use `not_assessed`.

Never store secrets, full chat transcripts, or unrelated personal information. Persist UTC timestamps and compute elapsed time from them after restart or sleep; never estimate elapsed time from process uptime.

## Hybrid Evaluation

The answer-completion boundary applies to CLI use as well as conversation:

1. `list`, `show`, and `scaffold` may expose only learner-safe metadata, prompts, and public submission contracts.
2. Create or reuse only the current question's scaffold. Never truncate a non-empty learner submission and never precreate future answers.
3. Wait for the learner's explicit "I am finished" before `evaluate` or `prepare-review`; answer completion is not a Git commit.
4. `evaluate` runs declared local checks and writes stable evidence. It never assigns subjective rubric points.
5. `prepare-review` is post-answer and may expose the rubric, answer, and deterministic evidence to the LLM.
6. The LLM scores every rubric criterion with concise cited evidence.
7. `finalize` rejects scores above rubric maxima and nonzero scores blocked by failed objective checks, then computes the 0-10 total.

Passing local checks is necessary for full credit on covered criteria but is not sufficient. Rubric-only questions skip step 4 rather than using fake keyword or exact-answer automation.
