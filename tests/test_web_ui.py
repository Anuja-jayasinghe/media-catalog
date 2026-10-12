import json
import unittest
from unittest.mock import patch

from scripts import web_ui


class WebUITests(unittest.TestCase):
    def test_movie_response_is_parsed_without_exposing_token(self):
        raw = {"page": 1, "results": [{"id": 438631, "title": "Dune", "release_date": "2021-09-15", "overview": "A journey", "poster_path": "/poster.jpg"}], "total_results": 1}
        with patch.dict(web_ui.os.environ, {"TMDB_READ_TOKEN": "private-tmdb-token"}), patch.object(web_ui.probe, "request_json", return_value=raw) as request:
            result = web_ui.search_catalog("movie", " Dune ")
        self.assertEqual(result["response"], raw)
        self.assertEqual(result["parsed"][0]["year"], 2021)
        self.assertEqual(result["parsed"][0]["title"], "Dune")
        self.assertEqual(result["request"]["query"]["query"], "Dune")
        self.assertNotIn("private-tmdb-token", json.dumps(result))
        self.assertIn("/search/movie?", request.call_args.args[0])

    def test_game_request_body_and_response_are_inspectable_without_credentials(self):
        raw = [{"id": 113112, "name": "Hades", "first_release_date": 1600300800, "summary": "Escape", "platforms": [{"name": "PC"}]}]
        with patch.dict(web_ui.os.environ, {"TWITCH_CLIENT_ID": "private-client-id"}), patch.object(web_ui.TOKENS, "get", return_value="private-access-token"), patch.object(web_ui.probe, "request_json", return_value=raw) as request:
            result = web_ui.search_catalog("game", 'Hades "One"')
        self.assertEqual(result["response"], raw)
        self.assertEqual(result["parsed"][0]["platforms"], ["PC"])
        self.assertEqual(result["parsed"][0]["year"], 2020)
        self.assertIn('search "Hades \\"One\\"";', result["request"]["body"])
        self.assertEqual(request.call_args.kwargs["data"].decode(), result["request"]["body"])
        for secret in ("private-client-id", "private-access-token"):
            self.assertNotIn(secret, json.dumps(result))

    def test_invalid_input_does_not_contact_providers(self):
        with patch.object(web_ui.probe, "request_json") as request:
            for media_type, query in (("unknown", "Dune"), ("movie", ""), ("game", "x" * 121)):
                with self.assertRaises(ValueError):
                    web_ui.search_catalog(media_type, query)
        request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
