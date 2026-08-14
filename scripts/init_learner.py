#!/usr/bin/env python3
"""Create a local learner profile without external dependencies."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "learner"


def build_profile(name: str, learner_id: str | None = None) -> dict:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    return {
        "schema_version": 1,
        "learner": {"id": learner_id or slugify(name), "display_name": name, "created_at": now},
        "preferences": {"default_mode": "study", "session_minutes": 20, "target_difficulty": "intermediate"},
        "topic_progress": [],
        "updated_at": now,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", required=True, help="Learner display name")
    parser.add_argument("--id", dest="learner_id", help="Optional lowercase hyphenated learner ID")
    parser.add_argument("--output", type=Path, default=ROOT / "state/learner.json")
    parser.add_argument("--force", action="store_true", help="Replace an existing output file")
    args = parser.parse_args()
    learner_id = args.learner_id or slugify(args.name)
    if re.fullmatch(r"[a-z0-9-]+", learner_id) is None:
        parser.error("--id must contain only lowercase letters, digits, and hyphens")
    if args.output.exists() and not args.force:
        parser.error(f"{args.output} already exists; use --force to replace it")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(build_profile(args.name, learner_id), indent=2) + "\n", encoding="utf-8")
    print(f"Created learner profile at {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
