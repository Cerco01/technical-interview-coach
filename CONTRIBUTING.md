# Contributing Questions and Evaluators

Add a question and its evaluator as one reviewable work unit. The bank, deterministic behavior, learner-safe disclosure, and documentation must remain valid together.

Session changes are a separate work unit: keep selector/state behavior, schemas, learner-safe CLI projections, documentation, and behavior tests together.

## Authoring Path

1. Add one independently authored record to the matching `data/questions/*.jsonl` bank.
2. Declare `evaluation.strategy`, the public `submission_contract`, and objective rubric indices.
3. Add deterministic fixture behavior to `src/interview_coach/private/specs.py` when the strategy is not `rubric_only`.
4. Add behavior tests for passing, failing, error, and boundary cases that materially apply.
5. Run validation and the full test suite.

Use `rubric_only` for conceptual reasoning, case studies, and explanation-led debugging when exact execution would not measure the requested skill. Never award synthetic objective points merely because keywords appear in prose.

## Disclosure Check

Before review, confirm that `list`, `show`, and `scaffold` expose only the prompt and public submission shape. Expected values may exist in package-private evaluator fixtures, but scaffolds and learner-facing output must not contain complete solutions, rubric criteria, hints, evaluator references, or expected concepts.

Do not include copied source identifiers, private paths, source documents, real learner answers, production data, or provenance details. Use minimal synthetic fixtures with reserved example domains where an address is needed.

Active assessment output must remain free of score, correctness, summary, improvement, criterion, rubric, expected-concept, hint, and solution content. Private ignored state may retain finalized details for the completion report; this is workflow privacy, not cryptographic secrecy.

## Verification

```bash
PYTHONDONTWRITEBYTECODE=1 interview-coach validate
PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s tests -v
```

Build and install from a wheel in a temporary virtual environment before release. Direct all build caches and outputs outside the repository.

For session changes, also verify practice pause/explicit advance, assessment auto-advance/non-disclosure, restart timeout, record binding/idempotency, atomic failure preservation, seeded replay, blueprint fallback, and arbitrary-working-directory behavior.
