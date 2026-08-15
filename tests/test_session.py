from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from interview_coach.bank import questions
from interview_coach.session import ACTIVE_ASSESSMENT_RECORD_ERROR, CORE_CATEGORIES, SessionError, SessionService, SessionStore
from interview_coach.session_rules import adapt_difficulty, candidate_identity, select_assessment, transition


class MutableClock:
    def __init__(self, value: datetime | None = None):
        self.value = value or datetime(2026, 8, 14, 12, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.value

    def advance(self, **kwargs: int) -> None:
        self.value += timedelta(**kwargs)


class SessionBehaviorTests(unittest.TestCase):
    def service(self, directory: str, clock: MutableClock | None = None, bank=None) -> SessionService:
        root = Path(directory)
        return SessionService(SessionStore(root / "state/active-session.json", root / "sessions"), clock or MutableClock(), bank)

    def assessment(self, directory: str, question_id: str, score: int, marker: str = "") -> Path:
        value = {
            "schema_version": 1,
            "question_id": question_id,
            "score": score,
            "max_score": 10,
            "criteria": [],
            "summary": f"Private finalized feedback {marker}",
            "improvement": "Private improvement",
            "deterministic_status": "not_applicable",
        }
        path = Path(directory) / f"assessment-{question_id}-{marker or score}.json"
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def record_current(self, service: SessionService, directory: str, score: int, marker: str = "") -> dict:
        status = service.status()
        path = self.assessment(directory, status["current_question_id"], score, marker)
        return service.record(status["session_id"], status["current_question_id"], path)

    def test_assessment_rule_preserves_seeded_selection_without_io(self):
        records = questions()
        identities = candidate_identity(records.values())
        state = {
            "eligible_candidate_ids": [item["id"] for item in identities],
            "selected_question_ids": [],
            "difficulty_state": {"current": "intermediate"},
            "history": {"recent_question_ids": []},
            "seed": "repeatable",
            "learner_context": None,
        }
        original = json.loads(json.dumps(state))

        first = select_assessment(state, records)
        second = select_assessment(state, records)

        self.assertEqual(first, second)
        self.assertEqual("q-python-001", first[0])
        self.assertEqual(original, state)

    def test_transition_rule_is_pure_and_deterministic(self):
        details = {"question_id": "q-python-001"}
        original = dict(details)

        first = transition(3, "answer_recorded", "answering", "advancing", "2026-08-15T12:00:00Z", details)
        second = transition(3, "answer_recorded", "answering", "advancing", "2026-08-15T12:00:00Z", details)

        self.assertEqual(first, second)
        self.assertEqual(3, first["sequence"])
        self.assertEqual(original, details)
        self.assertIsNot(first["details"], details)

    def test_difficulty_adaptation_rule_is_pure_and_deterministic(self):
        difficulty = {"current": "intermediate", "evidence_since_change": [9], "lock_remaining": 0, "last_direction": None}
        original = json.loads(json.dumps(difficulty))

        first = adapt_difficulty(difficulty, 8)
        second = adapt_difficulty(difficulty, 8)

        self.assertEqual(first, second)
        self.assertEqual(original, difficulty)
        self.assertEqual(
            ({"current": "advanced", "evidence_since_change": [], "lock_remaining": 2, "last_direction": "up"},
             {"action": "up", "from": "intermediate", "to": "advanced", "scores": [9, 8]}),
            first,
        )

    def test_practice_pauses_and_requires_explicit_next(self):
        with tempfile.TemporaryDirectory() as directory:
            service = self.service(directory)
            started = service.start("practice", mode="study", seed="practice-seed")
            self.assertTrue(started["hints_allowed"])
            self.assertTrue(service.status()["hints_allowed"])
            question_id = started["current_question_id"]
            recorded = self.record_current(service, directory, 7)
            self.assertTrue(recorded["hints_allowed"])
            self.assertEqual("paused", recorded["phase"])
            self.assertEqual(question_id, recorded["current_question_id"])
            self.assertIn("feedback", recorded)
            current = service.current()
            self.assertTrue(current["hints_allowed"])
            self.assertEqual(question_id, current["question"]["id"])
            advanced = service.next()
            self.assertEqual("answering", advanced["phase"])
            self.assertNotEqual(question_id, advanced["current_question_id"])
            self.assertEqual(questions()[question_id]["primary_category"], advanced["question"]["primary_category"])

    def test_practice_retry_change_topic_explain_resume_finish_and_report(self):
        with tempfile.TemporaryDirectory() as directory:
            clock = MutableClock()
            service = self.service(directory, clock)
            started = service.start("practice", mode="review", seed="resume")
            self.assertTrue(started["hints_allowed"])
            self.record_current(service, directory, 4, "first")
            explanation = service.explain()
            self.assertEqual("paused", explanation["phase"])
            self.assertNotIn("rubric", json.dumps(explanation).lower())
            service = self.service(directory, clock)
            retried = service.retry()
            self.assertEqual(started["current_question_id"], retried["current_question_id"])
            self.record_current(service, directory, 6, "retry")
            changed = service.change_topic("sql-fundamentals")
            self.assertIn("sql-fundamentals", changed["question"]["topic_ids"])
            finished = service.finish()
            self.assertTrue(finished["hints_allowed"])
            self.assertEqual("completed", finished["status"])
            report = service.report(finished["session_id"])
            self.assertEqual("not_assessed", report["readiness"]["band"])
            self.assertFalse((Path(directory) / "state/active-session.json").exists())

    def test_assessment_defaults_repeatability_coverage_and_no_duplicates(self):
        decisions = []
        for run in range(2):
            with tempfile.TemporaryDirectory() as directory:
                service = self.service(directory)
                started = service.start("assessment", mode="interview", seed="repeatable")
                state = service.store.load()
                self.assertEqual(12, started["question_limit"])
                self.assertEqual(75, state["duration_minutes"])
                self.assertFalse(state["hints_allowed"])
                self.assertNotIn("hints_allowed", started)
                while service.store.state_path.exists():
                    self.record_current(service, directory, 7, str(len(state["attempts"])))
                    if service.store.state_path.exists():
                        state = service.store.load()
                completed = service.store.completed(started["session_id"])
                selected = completed["selected_question_ids"]
                self.assertEqual(12, len(selected))
                self.assertEqual(12, len(set(selected)))
                categories = {questions()[item]["primary_category"] for item in selected}
                self.assertTrue(CORE_CATEGORIES <= categories)
                decisions.append(selected)
        self.assertEqual(decisions[0], decisions[1])

    def test_assessment_adapts_up_down_and_uses_cooldown(self):
        with tempfile.TemporaryDirectory() as directory:
            service = self.service(directory)
            started = service.start("assessment", mode="interview", seed="adapt", question_limit=5)
            self.record_current(service, directory, 9, "one")
            self.record_current(service, directory, 8, "two")
            state = service.store.load()
            self.assertEqual("advanced", state["difficulty_state"]["current"])
            self.assertEqual(2, state["difficulty_state"]["lock_remaining"])
            self.record_current(service, directory, 2, "three")
            self.record_current(service, directory, 2, "four")
            state = service.store.load()
            self.assertEqual("advanced", state["difficulty_state"]["current"])
            self.record_current(service, directory, 2, "five")
            completed = service.store.completed(started["session_id"])
            self.assertEqual("intermediate", completed["difficulty_state"]["current"])
        with tempfile.TemporaryDirectory() as directory:
            service = self.service(directory)
            service.start("assessment", mode="interview", seed="down", question_limit=5)
            self.record_current(service, directory, 3, "one")
            self.record_current(service, directory, 4, "two")
            self.assertEqual("beginner", service.store.load()["difficulty_state"]["current"])

    def test_assessment_auto_advances_without_feedback_and_releases_report_only_after_finish(self):
        with tempfile.TemporaryDirectory() as directory:
            service = self.service(directory)
            started = service.start("assessment", mode="interview", seed="private", question_limit=5)
            first = started["current_question_id"]
            recorded = self.record_current(service, directory, 9)
            self.assertNotEqual(first, recorded["current_question_id"])
            serialized = json.dumps(recorded).lower()
            for forbidden in ("private finalized", "criteria", "improvement", "rubric", '"score"'):
                self.assertNotIn(forbidden, serialized)
            with self.assertRaises(SessionError):
                service.report(started["session_id"])
            service.finish()
            report = service.report(started["session_id"])
            self.assertEqual(9.0, report["subjective_summary"]["average"])
            self.assertIn("non-certification", report["readiness"]["caveat"].lower())

    def test_timeout_survives_restart_and_explicit_early_finish(self):
        with tempfile.TemporaryDirectory() as directory:
            clock = MutableClock()
            service = self.service(directory, clock)
            started = service.start("assessment", mode="interview", duration_minutes=15)
            clock.advance(minutes=14)
            self.assertEqual("active", self.service(directory, clock).status()["status"])
            clock.advance(minutes=2)
            timed_out = self.service(directory, clock).status()
            self.assertEqual("completed", timed_out["status"])
            report = service.report(started["session_id"])
            self.assertEqual("time_expired", report["completion_reason"])
            self.assertEqual(960, report["timing"]["elapsed_seconds"])
            self.assertEqual(0, report["timing"]["remaining_seconds"])
        with tempfile.TemporaryDirectory() as directory:
            service = self.service(directory)
            started = service.start("assessment", mode="interview")
            service.finish()
            self.assertEqual("user_finished", service.report(started["session_id"])["completion_reason"])

    def test_insufficient_category_uses_persisted_fallback(self):
        bank = {key: value for key, value in questions().items() if value["primary_category"] != "numpy"}
        with tempfile.TemporaryDirectory() as directory:
            service = self.service(directory, bank=bank)
            started = service.start("assessment", mode="interview", seed="fallback", question_limit=6)
            for index in range(6):
                self.record_current(service, directory, 6, str(index))
            completed = service.store.completed(started["session_id"])
            decision = completed["selection_decisions"][5]
            self.assertEqual("numpy", decision["target"])
            self.assertIn("fallback:insufficient_target_category", decision["reasons"])

    def test_record_binding_and_duplicate_are_safe(self):
        with tempfile.TemporaryDirectory() as directory:
            service = self.service(directory)
            started = service.start("practice", seed="binding")
            question_id = started["current_question_id"]
            path = self.assessment(directory, question_id, 7)
            first = service.record(started["session_id"], question_id, path)
            duplicate = service.record(started["session_id"], question_id, path)
            self.assertFalse(first["idempotent"])
            self.assertTrue(duplicate["idempotent"])
            self.assertEqual(1, len(service.store.load()["attempts"]))
            with self.assertRaises(SessionError):
                service.record("session-wrong", question_id, path)
            wrong = self.assessment(directory, "q-sql-001", 7, "wrong")
            with self.assertRaises(SessionError):
                service.record(started["session_id"], "q-sql-001", wrong)
        with tempfile.TemporaryDirectory() as directory:
            service = self.service(directory)
            started = service.start("assessment", mode="interview", question_limit=5)
            first_question = started["current_question_id"]
            path = self.assessment(directory, first_question, 7)
            advanced = service.record(started["session_id"], first_question, path)
            duplicate = service.record(started["session_id"], first_question, path)
            self.assertTrue(duplicate["idempotent"])
            self.assertEqual(advanced["current_question_id"], duplicate["current_question_id"])
            self.assertEqual(1, len(service.store.load()["attempts"]))

    def test_malformed_state_and_atomic_failure_preserve_prior_state(self):
        with tempfile.TemporaryDirectory() as directory:
            service = self.service(directory)
            service.store.state_path.parent.mkdir(parents=True)
            service.store.state_path.write_text("{broken", encoding="utf-8")
            with self.assertRaises(SessionError):
                service.status()
            service.store.state_path.write_text(json.dumps({"schema_version": 1, "session_id": "session-stale", "status": "completed", "revision": 1, "transition_log": []}), encoding="utf-8")
            with self.assertRaises(SessionError):
                service.status()
        with tempfile.TemporaryDirectory() as directory:
            service = self.service(directory)
            service.start("practice")
            before = service.store.state_path.read_bytes()
            state = service.store.load()
            state["phase"] = "paused"
            with mock.patch("interview_coach.session.os.replace", side_effect=OSError("injected replace failure")):
                with self.assertRaises(OSError):
                    service.store.save(state, state["revision"])
            self.assertEqual(before, service.store.state_path.read_bytes())
            self.assertEqual([], list(service.store.state_path.parent.glob(".*.tmp")))
        with tempfile.TemporaryDirectory() as directory:
            service = self.service(directory)
            started = service.start("assessment", mode="interview", question_limit=5)
            question_id = started["current_question_id"]
            assessment = self.assessment(directory, question_id, 7)
            with mock.patch("interview_coach.session.os.fsync", side_effect=[None, OSError("injected directory fsync failure")]):
                recorded = service.record(started["session_id"], question_id, assessment)
            committed = service.store.load()
            self.assertTrue(recorded["accepted"])
            self.assertEqual(1, committed["revision"])
            self.assertEqual(1, len(committed["attempts"]))
            self.assertEqual(recorded["current_question_id"], committed["current_question_id"])
            duplicate = service.record(started["session_id"], question_id, assessment)
            self.assertTrue(duplicate["idempotent"])
            self.assertEqual(1, len(service.store.load()["attempts"]))

    def test_custom_state_path_works_from_arbitrary_cwd(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as cwd:
            state = Path(directory) / "private/session.json"
            environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": str(SRC)}
            command = [sys.executable, "-m", "interview_coach.cli", "session", "start", "--flow", "practice", "--state", str(state)]
            started = subprocess.run(command, cwd=cwd, env=environment, capture_output=True, text=True, check=False)
            current = subprocess.run([sys.executable, "-m", "interview_coach.cli", "session", "current", "--state", str(state)], cwd=cwd, env=environment, capture_output=True, text=True, check=False)
            self.assertEqual(0, started.returncode, started.stderr)
            self.assertEqual(0, current.returncode, current.stderr)
            self.assertTrue(state.is_file())
            self.assertIn('"question"', current.stdout)

    def test_learner_state_is_used_without_inventing_progress(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            learner = {
                "schema_version": 1,
                "learner": {"id": "test", "display_name": "Test", "created_at": "2026-01-01T00:00:00Z"},
                "preferences": {"default_mode": "study", "session_minutes": 20, "target_difficulty": "intermediate"},
                "topic_progress": [{"topic_id": "sql-joins-aggregation", "status": "reviewing", "mastery": 0.1, "attempts": 1, "correct": 0, "confidence": 2, "last_practiced": "2026-01-01T00:00:00Z", "next_review": "2026-01-02"}],
                "updated_at": "2026-01-01T00:00:00Z",
            }
            learner_path = root / "learner.json"
            learner_path.write_text(json.dumps(learner), encoding="utf-8")
            service = self.service(directory)
            service.start("practice", mode="review", learner_state=learner_path)
            state = service.store.load()
            self.assertEqual("learner.json", state["learner_context"]["source"])
            self.assertEqual(64, len(state["learner_context"]["digest"]))
            self.assertIn("learner_state:due_and_low_mastery_tiebreak", state["selection_decisions"][0]["reasons"])

    def test_new_session_documents_validate_against_schemas(self):
        try:
            import jsonschema
        except ImportError:
            self.skipTest("jsonschema test dependency is unavailable")
        with tempfile.TemporaryDirectory() as directory:
            service = self.service(directory)
            started = service.start("practice")
            state = service.store.load()
            active_schema = json.loads((ROOT / "schemas/active-session.schema.json").read_text(encoding="utf-8"))
            transition_schema = json.loads((ROOT / "schemas/transition.schema.json").read_text(encoding="utf-8"))
            jsonschema.validate(state, active_schema)
            for transition in state["transition_log"]:
                jsonschema.validate(transition, transition_schema)
            service.finish()
            completed = service.store.completed(started["session_id"])
            report_schema = json.loads((ROOT / "schemas/report.schema.json").read_text(encoding="utf-8"))
            session_schema = json.loads((ROOT / "schemas/session.schema.json").read_text(encoding="utf-8"))
            jsonschema.validate(completed["report"], report_schema)
            jsonschema.validate(completed, session_schema)
            legacy = json.loads((ROOT / "examples/session-template.json").read_text(encoding="utf-8"))
            jsonschema.validate(legacy, session_schema)

    def test_active_assessment_cli_output_has_no_hidden_feedback(self):
        with tempfile.TemporaryDirectory() as directory:
            environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": str(SRC)}
            base = [sys.executable, "-m", "interview_coach.cli", "session"]
            started = subprocess.run([*base, "start", "--flow", "assessment", "--questions", "5", "--data-dir", directory], cwd=ROOT, env=environment, capture_output=True, text=True, check=False)
            status = subprocess.run([*base, "status", "--data-dir", directory], cwd=ROOT, env=environment, capture_output=True, text=True, check=False)
            current = subprocess.run([*base, "current", "--data-dir", directory], cwd=ROOT, env=environment, capture_output=True, text=True, check=False)
            self.assertEqual(0, started.returncode, started.stderr)
            self.assertEqual(0, status.returncode, status.stderr)
            self.assertEqual(0, current.returncode, current.stderr)
            started_value = json.loads(started.stdout)
            assessment = self.assessment(directory, started_value["current_question_id"], 7, "cli-output")
            record_command = [*base, "record", "--session-id", started_value["session_id"], "--question-id", started_value["current_question_id"], "--assessment", str(assessment), "--data-dir", directory]
            recorded = subprocess.run(record_command, cwd=ROOT, env=environment, capture_output=True, text=True, check=False)
            duplicate = subprocess.run(record_command, cwd=ROOT, env=environment, capture_output=True, text=True, check=False)
            finished = subprocess.run([*base, "finish", "--data-dir", directory], cwd=ROOT, env=environment, capture_output=True, text=True, check=False)
            self.assertEqual(0, recorded.returncode, recorded.stderr)
            self.assertEqual(0, duplicate.returncode, duplicate.stderr)
            self.assertEqual(0, finished.returncode, finished.stderr)
            output = (started.stdout + status.stdout + current.stdout + recorded.stdout + duplicate.stdout + finished.stdout).lower()
            for forbidden in ("hints_allowed", "evaluation_strategy", "evaluator_ref", "objective_criteria", "expected_concepts", '"rubric"', '"criteria"', '"summary"', '"improvement"', "private finalized", '"score"', "correctness"):
                self.assertNotIn(forbidden, output)

    def test_active_assessment_record_errors_are_neutral(self):
        with tempfile.TemporaryDirectory() as directory:
            environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": str(SRC)}
            session_base = [sys.executable, "-m", "interview_coach.cli", "session"]
            start_result = subprocess.run([*session_base, "start", "--flow", "assessment", "--questions", "5", "--data-dir", directory], cwd=ROOT, env=environment, capture_output=True, text=True, check=False)
            self.assertEqual(0, start_result.returncode, start_result.stderr)
            started = json.loads(start_result.stdout)
            question_id = started["current_question_id"]
            valid = json.loads(self.assessment(directory, question_id, 7).read_text(encoding="utf-8"))
            cases = {
                "missing_file": None,
                "malformed_json": "{broken",
                "invalid_shape": json.dumps({}),
                "invalid_score": json.dumps({**valid, "score": 11}),
                "invalid_status": json.dumps({**valid, "deterministic_status": "wrong"}),
                "wrong_question": json.dumps({**valid, "question_id": "q-wrong-001"}),
            }
            base = [*session_base, "record", "--data-dir", directory]
            for name, content in cases.items():
                with self.subTest(name=name):
                    path = Path(directory) / f"{name}.json"
                    if content is not None:
                        path.write_text(content, encoding="utf-8")
                    command = [*base, "--session-id", started["session_id"], "--question-id", question_id, "--assessment", str(path)]
                    if name == "wrong_question":
                        command[command.index("--question-id") + 1] = "q-wrong-001"
                    result = subprocess.run(command, cwd=ROOT, env=environment, capture_output=True, text=True, check=False)
                    self.assertEqual(3, result.returncode)
                    self.assertEqual("", result.stdout)
                    self.assertEqual(f"ERROR: {ACTIVE_ASSESSMENT_RECORD_ERROR}\n", result.stderr)
                    prohibited = ("hints_allowed", "0 to 10", "score", "rubric", "criteria", "deterministic", "question_id", "session_id", "does not match", "schema")
                    for term in prohibited:
                        self.assertNotIn(term, result.stderr.lower())
            service = SessionService(SessionStore(Path(directory) / "state/active-session.json", Path(directory) / "sessions"))
            valid_path = self.assessment(directory, question_id, 7, "digest")
            with mock.patch("interview_coach.session.digest", side_effect=TypeError("internal digest detail")):
                with self.assertRaisesRegex(SessionError, f"^{ACTIVE_ASSESSMENT_RECORD_ERROR}$"):
                    service.record(started["session_id"], question_id, valid_path)
            with self.assertRaisesRegex(SessionError, f"^{ACTIVE_ASSESSMENT_RECORD_ERROR}$"):
                service.record("session-wrong", question_id, valid_path)


if __name__ == "__main__":
    unittest.main()
