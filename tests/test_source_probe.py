import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "source_probe.py"
SPEC = importlib.util.spec_from_file_location("source_probe", MODULE_PATH)
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


class ProbeTests(unittest.TestCase):
    def test_fixture_is_valid(self):
        items = probe.fixtures(probe.FIXTURE)
        self.assertEqual(len(items), 9)
        self.assertEqual({item["media_type"] for item in items}, {"movie", "tv", "game"})

    def test_tmdb_search_extracts_only_summary_fields(self):
        item = {"media_type": "tv", "query": "Breaking Bad"}
        payload = {"results": [{"id": 1396, "name": "Breaking Bad", "first_air_date": "2008-01-20", "overview": "unused"}]}
        with patch.dict(probe.os.environ, {"TMDB_READ_TOKEN": "test-token"}), patch.object(probe, "request_json", return_value=payload) as request:
            result = probe.tmdb_search(item)
        self.assertEqual(result, [{"id": 1396, "title": "Breaking Bad", "year": 2008, "rank": 1}])
        self.assertIn("/search/tv?", request.call_args.args[0])

    def test_igdb_search_escapes_quotes_and_extracts_year(self):
        item = {"media_type": "game", "query": 'Game "One"'}
        payload = [{"id": 42, "name": 'Game "One"', "first_release_date": 1483228800, "summary": "unused"}]
        with patch.dict(probe.os.environ, {"TWITCH_CLIENT_ID": "test-id"}), patch.object(probe, "request_json", return_value=payload) as request:
            result = probe.igdb_search(item, "test-token")
        self.assertEqual(result, [{"id": 42, "title": 'Game "One"', "year": 2017, "rank": 1}])
        self.assertIn(b'Game \\"One\\"', request.call_args.kwargs["data"])


if __name__ == "__main__":
    unittest.main()
