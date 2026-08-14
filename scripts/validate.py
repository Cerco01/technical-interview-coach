#!/usr/bin/env python3
"""Compatibility wrapper for ``interview-coach validate``."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from interview_coach.validation import ValidationError, validate, validate_privacy  # noqa: E402


def main() -> int:
    try:
        result = validate(ROOT)
    except ValidationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"Validated {result['topics']} topics, {result['questions']} questions, {result['schemas']} schemas, and {result['deterministic']} deterministic evaluators.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
