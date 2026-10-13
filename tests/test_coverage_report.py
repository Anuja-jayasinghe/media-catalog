import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "coverage_report.py"
SPEC = importlib.util.spec_from_file_location("coverage_report", MODULE_PATH)
report = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(report)


class CoverageReportTests(unittest.TestCase):
    def test_small_smoke_run_cannot_claim_coverage_target(self):
        fixture = [{"media_type": "movie", "query": "Dune", "expected_id": 42, "bucket": "ambiguous"}]
        result = {("movie", "Dune", 42): {"match_rank": 1}}
        summary = report.summarize(fixture, result)
        self.assertEqual(summary["overall"]["top_5_percent"], 100)
        self.assertFalse(summary["complete_180_fixture"])
        self.assertEqual(summary["status"], "insufficient_or_below_target")

    def test_missing_result_and_provider_error_are_reported(self):
        fixture = [{"media_type": "game", "query": "One", "expected_id": 1, "bucket": "indie"},
                   {"media_type": "game", "query": "Two", "expected_id": 2, "bucket": "indie"}]
        result = {("game", "One", 1): {"error": "HTTP 429"}}
        summary = report.summarize(fixture, result)
        self.assertEqual(summary["missing_results"], ["game:Two"])
        self.assertEqual(summary["errors"], ["game:One:1"])
        self.assertEqual(summary["overall"]["top_5"], 0)

    def test_same_query_can_grade_two_different_works(self):
        fixture = [{"media_type": "movie", "query": "Dune", "expected_id": 1, "bucket": "ambiguous"},
                   {"media_type": "movie", "query": "Dune", "expected_id": 2, "bucket": "ambiguous"}]
        results = {("movie", "Dune", 1): {"match_rank": 1},
                   ("movie", "Dune", 2): {"match_rank": 4}}
        summary = report.summarize(fixture, results)
        self.assertEqual(summary["overall"]["top_5"], 2)


if __name__ == "__main__":
    unittest.main()
