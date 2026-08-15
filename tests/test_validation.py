from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from collections import Counter
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from interview_coach.bank import get_question, questions
from interview_coach.cli import create_scaffold, flat_scaffold_filename, main, scaffold_text
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

    def test_scaffold_creates_exact_path_and_preserves_existing_content(self):
        with tempfile.TemporaryDirectory() as directory:
            first = self.cli("scaffold", "q-python-003", "--output", directory)
            path = Path(first.stdout.strip())
            original = path.read_text(encoding="utf-8")
            second = self.cli("scaffold", "q-python-003", "--output", directory)
            self.assertEqual(0, first.returncode, first.stderr)
            self.assertEqual((Path(directory) / "solution.py").resolve(), path)
            self.assertEqual(0, second.returncode, second.stderr)
            self.assertEqual(first.stdout, second.stdout)
            self.assertEqual(original, path.read_text(encoding="utf-8"))
            path.write_text("learner work\n", encoding="utf-8")
            third = self.cli("scaffold", "q-python-003", "--output", directory)
            self.assertEqual(0, third.returncode, third.stderr)
            self.assertEqual("learner work\n", path.read_text(encoding="utf-8"))

    def test_flat_scaffold_maps_contracts_to_sibling_question_files(self):
        cases = {
            "q-python-003": "q-python-003.py",
            "q-sql-002": "q-sql-002.sql",
            "q-ml-004": "q-ml-004.md",
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for question_id, filename in cases.items():
                with self.subTest(question_id=question_id):
                    result = self.cli("scaffold", question_id, "--output", directory, "--flat")
                    self.assertEqual(0, result.returncode, result.stderr)
                    self.assertEqual((root / filename).resolve(), Path(result.stdout.strip()))
            self.assertEqual(set(cases.values()), {path.name for path in root.iterdir()})
            self.assertTrue(all(path.is_file() for path in root.iterdir()))

    def test_flat_retry_reopens_exact_path_and_preserves_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            first = self.cli("scaffold", "q-python-003", "--output", directory, "--flat")
            path = Path(first.stdout.strip())
            learner_bytes = b"def count_words(words):\n    return {'kept': 1}\n"
            path.write_bytes(learner_bytes)
            retry = self.cli("scaffold", "q-python-003", "--output", directory, "--flat")
            self.assertEqual(0, retry.returncode, retry.stderr)
            self.assertEqual(first.stdout, retry.stdout)
            self.assertEqual(learner_bytes, path.read_bytes())
            self.assertEqual([path], [item.resolve() for item in Path(directory).iterdir()])

    def test_flat_empty_file_gets_template_and_nonempty_file_is_preserved(self):
        question = get_question("q-sql-002")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "q-sql-002.sql"
            path.touch()
            self.assertEqual(path.resolve(), create_scaffold(question, Path(directory), flat=True))
            self.assertIn("SELECT or WITH", path.read_text(encoding="utf-8"))
            path.write_bytes(b"SELECT 1;\n")
            create_scaffold(question, Path(directory), flat=True)
            self.assertEqual(b"SELECT 1;\n", path.read_bytes())

    def test_flat_scaffold_rejects_unsafe_ids_paths_symlinks_and_type_collisions(self):
        question = get_question("q-python-003")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            wrong_type = root / "q-python-003.sql"
            wrong_type.touch()
            with self.assertRaises(EvaluationError):
                create_scaffold(question, root, flat=True)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            destination = root / "q-python-003.py"
            target = root / "target.py"
            target.touch()
            destination.symlink_to(target)
            with self.assertRaises(EvaluationError):
                create_scaffold(question, root, flat=True)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "q-python-003.py").mkdir()
            with self.assertRaises(EvaluationError):
                create_scaffold(question, root, flat=True)
        unsafe = json.loads(json.dumps(question))
        unsafe["id"] = "../q-python-003"
        with self.assertRaises(EvaluationError):
            flat_scaffold_filename(unsafe)
        with self.assertRaises(EvaluationError):
            create_scaffold(question, Path("workspace/../escape"), flat=True)

    def test_assessment_scaffold_isolated_from_practice_and_refuses_prior_answer(self):
        question = get_question("q-python-003")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            practice = root / "q-python-003.py"
            practice.write_bytes(b"private practice answer\n")
            assessment = create_scaffold(question, root, flat=True, assessment=True)
            self.assertEqual((root / "assessment-q-python-003.py").resolve(), assessment)
            self.assertNotIn("private practice answer", assessment.read_text(encoding="utf-8"))
            self.assertEqual(b"private practice answer\n", practice.read_bytes())
            assessment.write_bytes(b"active assessment answer\n")
            with self.assertRaisesRegex(EvaluationError, "fresh assessment workspace"):
                create_scaffold(question, root, flat=True, assessment=True)

    def test_scaffold_populates_empty_file_and_rejects_unsafe_collisions(self):
        question = get_question("q-python-003")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            empty = root / "solution.py"
            empty.touch()
            self.assertEqual(empty.resolve(), create_scaffold(question, root))
            self.assertIn("def count_words(words)", empty.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "solution.py").mkdir()
            with self.assertRaises(EvaluationError):
                create_scaffold(question, root)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "not-a-directory"
            output.write_text("collision", encoding="utf-8")
            with self.assertRaises(EvaluationError):
                create_scaffold(question, output)
        with tempfile.TemporaryDirectory() as directory:
            unsafe = json.loads(json.dumps(question))
            unsafe["evaluation"]["submission_contract"]["filename"] = "../escape.py"
            with self.assertRaises(EvaluationError):
                create_scaffold(unsafe, Path(directory))

    def test_scaffold_open_uses_exact_vscode_argument_array(self):
        with tempfile.TemporaryDirectory() as directory:
            stdout = StringIO()
            with mock.patch("interview_coach.cli.subprocess.run") as run, redirect_stdout(stdout):
                run.return_value = subprocess.CompletedProcess([], 0, "", "")
                result = main(["scaffold", "q-python-003", "--output", directory, "--open"])
            path = (Path(directory) / "solution.py").resolve()
            self.assertEqual(0, result)
            self.assertEqual(f"{path}\n", stdout.getvalue())
            run.assert_called_once_with(["code", "-r", str(path)], capture_output=True, text=True, check=False, shell=False)

    def test_flat_scaffold_open_uses_exact_vscode_argument_array(self):
        with tempfile.TemporaryDirectory() as directory:
            stdout = StringIO()
            with mock.patch("interview_coach.cli.subprocess.run") as run, redirect_stdout(stdout):
                run.return_value = subprocess.CompletedProcess([], 0, "", "")
                result = main(["scaffold", "q-sql-002", "--output", directory, "--flat", "--open"])
            path = (Path(directory) / "q-sql-002.sql").resolve()
            self.assertEqual(0, result)
            self.assertEqual(f"{path}\n", stdout.getvalue())
            run.assert_called_once_with(["code", "-r", str(path)], capture_output=True, text=True, check=False, shell=False)

    def test_scaffold_editor_failures_are_non_fatal_and_actionable(self):
        failures = (
            FileNotFoundError("code not found"),
            subprocess.CompletedProcess([], 1, "", "editor failed"),
        )
        for failure in failures:
            with self.subTest(failure=type(failure).__name__), tempfile.TemporaryDirectory() as directory:
                stdout, stderr = StringIO(), StringIO()
                behavior = {"side_effect": failure} if isinstance(failure, OSError) else {"return_value": failure}
                with mock.patch("interview_coach.cli.subprocess.run", **behavior), redirect_stdout(stdout), redirect_stderr(stderr):
                    result = main(["scaffold", "q-python-003", "--output", directory, "--flat", "--open"])
                path = (Path(directory) / "q-python-003.py").resolve()
                self.assertEqual(0, result)
                self.assertEqual(f"{path}\n", stdout.getvalue())
                self.assertTrue(path.is_file())
                self.assertIn(str(path), stderr.getvalue())
                self.assertIn("code -r", stderr.getvalue())
                self.assertIn("Install 'code' command in PATH", stderr.getvalue())

    def test_all_submission_contracts_have_safe_solution_free_scaffolds(self):
        expected = {
            "python_module": ("solution.py", ".py", "NotImplementedError"),
            "sql_query": ("answer.sql", ".sql", "SELECT or WITH"),
            "answer_text": ("answer.md", ".md", "reasoning"),
        }
        seen = set()
        for question_id, question in questions(ROOT).items():
            with self.subTest(question_id=question_id):
                contract = question["evaluation"]["submission_contract"]
                filename, suffix, marker = expected[contract["kind"]]
                text = scaffold_text(question)
                seen.add(contract["kind"])
                self.assertEqual(filename, contract["filename"])
                self.assertEqual(suffix, Path(filename).suffix)
                self.assertIn(marker, text)
                for forbidden in ("expected_concepts", "rubric", "hints", "follow_ups", "evaluator_ref", "case-insensitive"):
                    self.assertNotIn(forbidden, text.lower())
        self.assertEqual(set(expected), seen)

    def test_skill_and_docs_require_one_scaffold_per_current_question(self):
        skill = (ROOT / "skills/technical-interview-coach/SKILL.md").read_text(encoding="utf-8")
        workflow = (ROOT / "docs/workflows.md").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        combined = "\n".join((skill, workflow, readme)).lower()
        for required in ("--flat", "workspace/", "same flat", "i am finished", "not a git commit", "do not precreate"):
            self.assertIn(required, combined)
        self.assertIn("practice start", skill.lower())
        self.assertIn("assessment auto-advance", skill.lower())
        for prohibited in ("reset scaffold after failure", "write feedback into learner code"):
            self.assertIn(prohibited, combined)
        self.assertNotIn("submissions/<session-id>/<question-id>", combined)

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

    def test_privacy_guard_scans_untracked_and_ignored_files_but_skips_git_internals(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            (root / ".gitignore").write_text("*.pdf\n", encoding="utf-8")
            (root / ".git" / "internal.pdf").write_bytes(b"git control data")
            validate_privacy(root)
            for name in (".env", "ignored.pdf"):
                with self.subTest(name=name):
                    path = root / name
                    path.write_bytes(b"prohibited")
                    if name == "ignored.pdf":
                        self.assertEqual(0, subprocess.run(["git", "-C", str(root), "check-ignore", "-q", name]).returncode)
                    with self.assertRaisesRegex(ValidationError, re.escape(name)):
                        validate_privacy(root)
                    path.unlink()


if __name__ == "__main__":
    unittest.main()
