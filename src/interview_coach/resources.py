from __future__ import annotations

import importlib.metadata
import sysconfig
from pathlib import Path


def data_root() -> Path:
    """Locate canonical data in a checkout, editable install, or wheel install."""
    checkout = Path(__file__).resolve().parents[2]
    if (checkout / "curriculum/topics.json").is_file():
        return checkout
    distribution = importlib.metadata.distribution("technical-interview-coach")
    candidates = (
        Path(distribution.locate_file("interview_coach_data")),
        Path(sysconfig.get_path("data")) / "interview_coach_data",
    )
    for installed in candidates:
        if (installed / "curriculum/topics.json").is_file():
            return installed
    raise RuntimeError("installed interview coach data could not be located")


def repository_root() -> Path | None:
    root = Path(__file__).resolve().parents[2]
    return root if (root / "scripts/validate.py").is_file() else None
