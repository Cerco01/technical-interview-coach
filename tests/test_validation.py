from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from interview_coach.bank import get_question, questions
from interview_coach.cli import main
from interview_coach.evaluation import EvaluationError, evidence_for
from interview_coach.review import ReviewError, finalize, prepare
from interview_coach.validation import ValidationError, validate, validate_privacy


class CoachBehaviorTests(unittest.TestCase):
    def write(self, directory: str, name: str, content: str) -> Path:
        path = Path(directory) / name
        path.write_text(content, encoding="utf-8")
        return path

    def cli(self, *args: str, cwd: str | None = None) -> subprocess.CompletedProcess[str]:
        environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": str(SRC)}
        return subprocess.run([sys.executable, "-m", "interview_coach.cli", *args], cwd=cwd or ROOT, env=environment, capture_output=True, text=True, check=False)

    def test_bank_invariants_and_deterministic_coverage(self):
        result = validate(ROOT, scan_privacy=False)
        records = questions(ROOT)
        self.assertEqual({"topics": 37, "questions": 50, "schemas": 9, "deterministic": 22}, result)
        self.assertEqual(set(range(1, 51)), {item["priority_rank"] for item in records.values()})
        self.assertEqual({"implementation":10,"sql_query":7,"debugging":7,"conceptual_reasoning":14,"case_study":7,"data_manipulation":5}, dict(Counter(item["primary_format"] for item in records.values())))
        for item in records.values():
            if item["primary_format"] in {"implementation", "sql_query", "data_manipulation"}:
                self.assertNotEqual("rubric_only", item["evaluation"]["strategy"])

    def test_list_and_show_do_not_disclose_private_fields(self):
        listed = self.cli("list", "--format", "json")
        shown = self.cli("show", "q-python-003", "--format", "json")
        self.assertEqual(0, listed.returncode, listed.stderr)
        self.assertEqual(0, shown.returncode, shown.stderr)
        for forbidden in ("expected_concepts", "rubric", "hints", "follow_ups", "evaluator_ref", "objective_criteria"):
            self.assertNotIn(forbidden, listed.stdout)
            self.assertNotIn(forbidden, shown.stdout)
        self.assertIn("count_words", shown.stdout)

    def test_scaffold_is_safe_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            first = self.cli("scaffold", "q-python-003", "--output", directory)
            second = self.cli("scaffold", "q-python-003", "--output", directory)
            text = (Path(directory) / "solution.py").read_text(encoding="utf-8")
            self.assertEqual(0, first.returncode)
            self.assertNotEqual(0, second.returncode)
            self.assertIn("def count_words(words)", text)
            self.assertNotIn("case-insensitive", text)
            self.assertNotIn("rubric", text.lower())

    def test_python_evaluation_pass_fail_error_and_timeout(self):
        with tempfile.TemporaryDirectory() as directory:
            passing = self.write(directory, "passing.py", "def count_words(words):\n    result = {}\n    for word in words:\n        if word:\n            key = word.lower()\n            result[key] = result.get(key, 0) + 1\n    return result\n")
            failing = self.write(directory, "failing.py", "def count_words(words):\n    return {}\n")
            broken = self.write(directory, "broken.py", "raise RuntimeError('broken import')\n")
            hanging = self.write(directory, "hanging.py", "def count_words(words):\n    while True: pass\n")
            self.assertEqual("passed", evidence_for("q-python-003", passing)["status"])
            failed = evidence_for("q-python-003", failing)
            self.assertEqual("failed", failed["status"])
            self.assertEqual("zero_points", failed["rubric_constraints"][0]["scoring_constraint"])
            self.assertEqual("error", evidence_for("q-python-003", broken)["status"])
            self.assertEqual("timeout", evidence_for("q-python-003", hanging, timeout=0.2)["status"])

    def test_sql_evaluation_pass_and_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            passing = self.write(directory, "pass.sql", "SELECT c.id, c.name FROM customers c LEFT JOIN orders o ON o.customer_id=c.id WHERE o.id IS NULL")
            failing = self.write(directory, "fail.sql", "SELECT id, name FROM customers")
            self.assertEqual("passed", evidence_for("q-sql-001", passing)["status"])
            self.assertEqual("failed", evidence_for("q-sql-001", failing)["status"])

    def test_sql_rejects_writes_and_multiple_statements(self):
        with tempfile.TemporaryDirectory() as directory:
            destructive = self.write(directory, "answer.sql", "DELETE FROM customers")
            multiple = self.write(directory, "multiple.sql", "SELECT * FROM customers; SELECT * FROM orders")
            self.assertEqual("error", evidence_for("q-sql-001", destructive)["status"])
            self.assertEqual("error", evidence_for("q-sql-001", multiple)["status"])

    def test_numpy_evaluation_pass_and_fail(self):
        try:
            import numpy  # noqa: F401
        except ImportError:
            self.skipTest("NumPy optional dependency is unavailable")
        with tempfile.TemporaryDirectory() as directory:
            passing = self.write(directory, "pass.py", "def center_columns(x):\n    return x - x.mean(axis=0)\n")
            failing = self.write(directory, "fail.py", "def center_columns(x):\n    return x\n")
            self.assertEqual("passed", evidence_for("q-numpy-001", passing)["status"])
            self.assertEqual("failed", evidence_for("q-numpy-001", failing)["status"])

    def test_pandas_evaluation_pass_and_fail(self):
        try:
            import pandas  # noqa: F401
        except ImportError:
            self.skipTest("Pandas optional dependency is unavailable")
        with tempfile.TemporaryDirectory() as directory:
            passing = self.write(directory, "pass.py", "def filter_adults(df):\n    return df[(df['age'] >= 18) & df['country'].isin(['US','CA'])]\n")
            failing = self.write(directory, "fail.py", "def filter_adults(df):\n    return df\n")
            self.assertEqual("passed", evidence_for("q-pandas-002", passing)["status"])
            self.assertEqual("failed", evidence_for("q-pandas-002", failing)["status"])

    def test_evidence_is_stable_and_schema_valid(self):
        try:
            import jsonschema
        except ImportError:
            self.skipTest("jsonschema test dependency is unavailable")
        with tempfile.TemporaryDirectory() as directory:
            submission = self.write(directory, "solution.py", "def count_words(words):\n    from collections import Counter\n    return dict(Counter(w.lower() for w in words if w))\n")
            first = evidence_for("q-python-003", submission)
            second = evidence_for("q-python-003", submission)
            self.assertEqual(first, second)
            schema = json.loads((ROOT / "schemas/evidence.schema.json").read_text(encoding="utf-8"))
            jsonschema.validate(first, schema)

    def test_question_records_validate_against_published_schema(self):
        try:
            import jsonschema
        except ImportError:
            self.skipTest("jsonschema test dependency is unavailable")
        schema = json.loads((ROOT / "schemas/question.schema.json").read_text(encoding="utf-8"))
        for question_id, record in questions(ROOT).items():
            with self.subTest(question_id=question_id):
                jsonschema.validate(record, schema)

    def test_rubric_only_requires_post_commit_review(self):
        with tempfile.TemporaryDirectory() as directory:
            answer = self.write(directory, "answer.md", "The generator is exhausted because it is a one-pass iterator.")
            with self.assertRaises(EvaluationError):
                evidence_for("q-python-002", answer)
            context = prepare("q-python-002", answer, None)
            self.assertTrue(context["answer_committed"])
            self.assertIn("rubric", context)

    def test_finalize_enforces_objective_zero_cap(self):
        with tempfile.TemporaryDirectory() as directory:
            submission = self.write(directory, "solution.py", "def count_words(words): return {}\n")
            evidence = evidence_for("q-python-003", submission)
            evidence_path = self.write(directory, "evidence.json", json.dumps(evidence))
            assessment = {"scores":[{"criterion_index":0,"awarded_points":1,"evidence":"Claimed."},{"criterion_index":1,"awarded_points":0,"evidence":"Failed."},{"criterion_index":2,"awarded_points":3,"evidence":"Complexity discussed."}],"summary":"","improvement":""}
            assessment_path = self.write(directory, "assessment.json", json.dumps(assessment))
            with self.assertRaises(ReviewError):
                finalize("q-python-003", assessment_path, evidence_path)
            assessment["scores"][0]["awarded_points"] = 0
            assessment_path.write_text(json.dumps(assessment), encoding="utf-8")
            result = finalize("q-python-003", assessment_path, evidence_path)
            self.assertEqual(3, result["score"])

    def test_resources_load_from_arbitrary_working_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.cli("validate", cwd=directory)
            shown = self.cli("show", "q-sql-001", cwd=directory)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual(0, shown.returncode, shown.stderr)

    def test_privacy_guard_accepts_release_tree(self):
        validate_privacy(ROOT)

    def test_privacy_guard_rejects_generic_local_and_generated_content(self):
        fixtures = (
            ("reference.pdf", b"artifact"),
            ("dataset.csv", b"value\n1\n"),
            (".env", b"TOKEN=fixture"),
            (".atl/cache.json", b"{}"),
            ("__pycache__/module.pyc", b"cache"),
            ("notes.txt", str(Path.home() / "local-file").encode()),
        )
        for name, content in fixtures:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
                with self.assertRaises(ValidationError):
                    validate_privacy(Path(directory))


if __name__ == "__main__":
    unittest.main()
