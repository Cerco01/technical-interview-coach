from __future__ import annotations

from pathlib import Path
from typing import Any

from .evaluation import EvaluationError

FLAT_SUFFIXES = {
    "python_module": ".py",
    "sql_query": ".sql",
    "answer_text": ".md",
}


def scaffold_text(question: dict[str, Any]) -> str:
    contract = question["evaluation"]["submission_contract"]
    kind = contract["kind"]
    if kind == "python_module":
        entrypoint = contract["entrypoint"]
        signature = contract["signature"]
        return f'"""Submission for {question["id"]}.\n\nReturn: {contract["returns"]}\n"""\n\n\ndef {entrypoint}{signature}:\n    raise NotImplementedError("implement {entrypoint}")\n'
    if kind == "sql_query":
        columns = ", ".join(contract["columns"])
        return f"-- Submission for {question['id']}\n-- Write one read-only SELECT or WITH query.\n-- Output columns in order: {columns}\n"
    return f"# Answer for {question['id']}\n\nWrite your reasoning here. Tell the coach \"I am finished\" when your answer is ready.\n"


def flat_scaffold_filename(question: dict[str, Any], assessment: bool = False) -> str:
    question_id = question.get("id")
    if not isinstance(question_id, str) or not question_id.startswith("q-") or any(
        not part or not part.isascii() or not part.isalnum() or part.lower() != part
        for part in question_id.split("-")
    ):
        raise EvaluationError(f"unsafe question ID for flat scaffold: {question_id}")
    kind = question["evaluation"]["submission_contract"].get("kind")
    try:
        suffix = FLAT_SUFFIXES[kind]
    except (KeyError, TypeError):
        raise EvaluationError(f"unsupported submission contract for flat scaffold: {kind}") from None
    prefix = "assessment-" if assessment else ""
    return f"{prefix}{question_id}{suffix}"


def create_scaffold(question: dict[str, Any], output: Path, *, flat: bool = False, assessment: bool = False) -> Path:
    if assessment and not flat:
        raise EvaluationError("--assessment requires --flat")
    if ".." in output.parts:
        raise EvaluationError(f"scaffold output cannot contain path traversal: {output}")
    filename = flat_scaffold_filename(question, assessment) if flat else question["evaluation"]["submission_contract"]["filename"]
    relative = Path(filename)
    if relative.is_absolute() or relative.name != filename:
        raise EvaluationError(f"unsafe scaffold filename: {filename}")
    if output.is_symlink() or (output.exists() and not output.is_dir()):
        raise EvaluationError(f"scaffold output must be a directory: {output}")
    output.mkdir(parents=True, exist_ok=True)
    destination = output / relative
    if flat:
        stem = filename.removesuffix(relative.suffix)
        collisions = [path for path in output.glob(f"{stem}.*") if path != destination]
        if collisions:
            raise EvaluationError(f"wrong-type scaffold collision: {collisions[0]}")
    if destination.is_symlink() or (destination.exists() and not destination.is_file()):
        raise EvaluationError(f"unsafe scaffold collision: {destination}")
    if assessment and destination.exists() and destination.stat().st_size:
        raise EvaluationError(
            f"assessment scaffold already contains an answer: {destination}; use a fresh assessment workspace or remove it explicitly"
        )
    if not destination.exists() or destination.stat().st_size == 0:
        destination.write_text(scaffold_text(question), encoding="utf-8")
    return destination.resolve()
