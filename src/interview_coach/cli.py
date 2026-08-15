from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from . import workspace
from .bank import BankError, get_question, learner_safe, questions, sorted_questions
from .evaluation import EvaluationError, evidence_for
from .review import ReviewError, finalize, prepare
from .session import SessionError, SessionService, default_paths
from .validation import ValidationError, validate

# Compatibility exports for callers that imported scaffold policy from the CLI.
FLAT_SUFFIXES = workspace.FLAT_SUFFIXES
scaffold_text = workspace.scaffold_text
flat_scaffold_filename = workspace.flat_scaffold_filename
create_scaffold = workspace.create_scaffold

EXIT_USAGE = 2
EXIT_VALIDATION = 3
EXIT_FAILED = 4
EXIT_RUNTIME = 5

def emit(value: Any, output: Path | None = None) -> None:
    text = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="interview-coach", description="Hybrid local and LLM interview answer evaluation")
    sub = result.add_subparsers(dest="command", required=True)
    sub.add_parser("validate", help="validate packaged curriculum, bank, schemas, and evaluator coverage")
    listing = sub.add_parser("list", help="list learner-safe question metadata")
    listing.add_argument("--format", choices=("json", "text"), default="text")
    show = sub.add_parser("show", help="show one learner-safe prompt and submission contract")
    show.add_argument("question_id")
    show.add_argument("--format", choices=("json", "text"), default="text")
    scaffold = sub.add_parser(
        "scaffold",
        help="create or reopen a learner-safe submission scaffold",
        epilog=(
            "Practice: interview-coach scaffold q-python-003 --output workspace --flat --open. "
            "Assessment: add --assessment and use a fresh file; existing non-empty assessment files are refused."
        ),
    )
    scaffold.add_argument("question_id")
    scaffold.add_argument("--output", type=Path, required=True)
    scaffold.add_argument("--flat", action="store_true", help="use <question-id>.<type> directly inside the output directory")
    scaffold.add_argument(
        "--assessment",
        action="store_true",
        help="with --flat, use an isolated assessment-<question-id>.<type> file and refuse prior non-empty answers",
    )
    scaffold.add_argument("--open", action="store_true", help="open the scaffold in the current VS Code window")
    evaluate = sub.add_parser("evaluate", help="run deterministic checks and write objective evidence")
    evaluate.add_argument("question_id")
    evaluate.add_argument("submission", type=Path)
    evaluate.add_argument("--output", type=Path, required=True)
    evaluate.add_argument("--timeout", type=float, default=10.0)
    review = sub.add_parser("prepare-review", help="create post-answer LLM scoring context")
    review.add_argument("question_id")
    review.add_argument("answer", type=Path)
    review.add_argument("--evidence", type=Path)
    review.add_argument("--output", type=Path, required=True)
    final = sub.add_parser("finalize", help="validate LLM rubric scores and compute the final score")
    final.add_argument("question_id")
    final.add_argument("assessment", type=Path)
    final.add_argument("--evidence", type=Path)
    final.add_argument("--output", type=Path, required=True)
    session = sub.add_parser("session", help="run resumable deterministic practice or assessment sessions")
    session_sub = session.add_subparsers(dest="session_command", required=True)

    def add_storage(command: argparse.ArgumentParser) -> None:
        command.add_argument("--state", type=Path, help="exact active-session JSON path")
        command.add_argument("--data-dir", type=Path, help="root containing private state/ and sessions/ directories")

    start = session_sub.add_parser("start", help="start a practice or assessment session")
    start.add_argument("--flow", choices=("practice", "assessment"), required=True)
    start.add_argument("--mode", choices=("interview", "study", "review"))
    start.add_argument("--seed", default="interview-coach")
    start.add_argument("--questions", type=int)
    start.add_argument("--minutes", type=int)
    start.add_argument("--difficulty", choices=("beginner", "intermediate", "advanced"), default="intermediate")
    start.add_argument("--topic")
    start.add_argument("--learner-state", type=Path, help="optional learner progress JSON; defaults beside active state")
    add_storage(start)
    status = session_sub.add_parser("status", help="show learner-safe active session status")
    add_storage(status)
    current = session_sub.add_parser("current", help="show the current learner-safe question")
    add_storage(current)
    record = session_sub.add_parser("record", help="record one finalized assessment bound to the active question")
    record.add_argument("--session-id", required=True)
    record.add_argument("--question-id", required=True)
    record.add_argument("--assessment", type=Path, required=True)
    add_storage(record)
    next_question = session_sub.add_parser("next", help="explicitly advance a paused practice session")
    add_storage(next_question)
    retry = session_sub.add_parser("retry", help="retry the same finalized practice question")
    add_storage(retry)
    change_topic = session_sub.add_parser("change-topic", help="select the next practice question from another topic")
    change_topic.add_argument("topic_id")
    add_storage(change_topic)
    explain = session_sub.add_parser("explain", help="record a post-answer LLM explanation request")
    add_storage(explain)
    finish = session_sub.add_parser("finish", help="finish and archive the active session")
    add_storage(finish)
    report = session_sub.add_parser("report", help="release a completed session report")
    report.add_argument("--session-id")
    add_storage(report)
    return result


def open_in_vscode(path: Path) -> None:
    command = ["code", "-r", str(path)]
    manual = f"Open it manually with: code -r {path}"
    install = "In VS Code, run Shell Command: Install 'code' command in PATH if needed."
    try:
        completed = subprocess.run(command, capture_output=True, text=True, check=False, shell=False)
    except OSError as exc:
        print(f"WARNING: scaffold created at {path}, but VS Code could not be opened ({exc}). {manual}. {install}", file=sys.stderr)
        return
    if completed.returncode != 0:
        detail = completed.stderr.strip()
        suffix = f" ({detail})" if detail else ""
        print(f"WARNING: scaffold created at {path}, but VS Code exited with code {completed.returncode}{suffix}. {manual}. {install}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "validate":
            result = validate()
            print(f"Validated {result['topics']} topics, {result['questions']} questions, {result['schemas']} schemas, and {result['deterministic']} deterministic evaluators.")
            return 0
        if args.command == "list":
            records = sorted_questions(questions().values())
            safe = [{key: item[key] for key in ("id", "title", "difficulty", "primary_format", "priority_rank")} for item in records]
            if args.format == "json": emit(safe)
            else:
                for item in safe: print(f"{item['priority_rank']:>2}  {item['id']:<20} {item['difficulty']:<12} {item['primary_format']:<21} {item['title']}")
            return 0
        if args.command == "session":
            service = SessionService(default_paths(args.state, args.data_dir))
            if args.session_command == "start":
                mode = args.mode or ("interview" if args.flow == "assessment" else "study")
                value = service.start(args.flow, mode, args.seed, args.questions, args.minutes, args.difficulty, args.topic, args.learner_state)
            elif args.session_command == "status":
                value = service.status()
            elif args.session_command == "current":
                value = service.current()
            elif args.session_command == "record":
                value = service.record(args.session_id, args.question_id, args.assessment)
            elif args.session_command == "next":
                value = service.next()
            elif args.session_command == "retry":
                value = service.retry()
            elif args.session_command == "change-topic":
                value = service.change_topic(args.topic_id)
            elif args.session_command == "explain":
                value = service.explain()
            elif args.session_command == "finish":
                value = service.finish()
            elif args.session_command == "report":
                value = service.report(args.session_id)
            else:
                return EXIT_USAGE
            emit(value)
            return 0
        question = get_question(args.question_id)
        if args.command == "show":
            safe = learner_safe(question)
            if args.format == "json": emit(safe)
            else:
                print(f"{safe['id']}: {safe['title']}\n\n{safe['prompt']}\n\nSubmission: {safe['submission_contract']['filename']} ({safe['evaluation_strategy']})")
            return 0
        if args.command == "scaffold":
            destination = workspace.create_scaffold(question, args.output, flat=args.flat, assessment=args.assessment)
            print(destination, flush=True)
            if args.open:
                open_in_vscode(destination)
            return 0
        if args.command == "evaluate":
            if args.timeout <= 0: raise EvaluationError("--timeout must be greater than zero")
            evidence = evidence_for(args.question_id, args.submission, args.timeout)
            emit(evidence, args.output)
            return 0 if evidence["status"] == "passed" else (EXIT_FAILED if evidence["status"] == "failed" else EXIT_RUNTIME)
        if args.command == "prepare-review":
            emit(prepare(args.question_id, args.answer, args.evidence), args.output)
            return 0
        if args.command == "finalize":
            emit(finalize(args.question_id, args.assessment, args.evidence), args.output)
            return 0
    except (BankError, EvaluationError, ReviewError, SessionError, ValidationError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return EXIT_VALIDATION
    return EXIT_USAGE


if __name__ == "__main__":
    raise SystemExit(main())
