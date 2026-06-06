import gzip
import json
import unittest
from unittest.mock import patch

from tvbox_aggregator import (
    CheckResult,
    build_tvbox_config,
    contains_sensitive_data,
    load_candidates,
    score_result,
    validate_epg,
    validate_playlist,
    validate_tvbox_config,
)


class ValidationTests(unittest.TestCase):
    def test_accepts_tvbox_config(self):
        valid, _, parsed = validate_tvbox_config(b'{"sites": [], "lives": []}')
        self.assertTrue(valid)
        self.assertEqual(parsed["sites"], [])

    def test_rejects_credentials(self):
        valid, detail, _ = validate_tvbox_config(
            b'{"sites": [], "quark_cookie": "secret"}'
        )
        self.assertFalse(valid)
        self.assertIn("credentials", detail)

    def test_detects_nested_sensitive_value(self):
        self.assertTrue(
            contains_sensitive_data({"ext": {"header": "Authorization: abc"}})
        )

    def test_playlist_formats(self):
        valid, detail = validate_playlist(
            b"#EXTM3U\n#EXTINF:-1,Demo\nhttps://x/y"
        )
        self.assertTrue(valid)
        self.assertIn("1 channels", detail)
        self.assertTrue(validate_playlist("央视,http://example.test/live\n".encode())[0])

    def test_epg_gzip(self):
        xml = b'<?xml version="1.0"?><tv><channel id="demo"/></tv>'
        self.assertTrue(validate_epg(gzip.compress(xml))[0])


class RankingTests(unittest.TestCase):
    def test_score_rewards_streak_and_speed(self):
        fast = score_result(CheckResult(True, 100, "ok"), 5)
        slow = score_result(CheckResult(True, 3000, "ok"), 1)
        self.assertGreater(fast, slow)

    def test_build_selects_highest_scoring_config(self):
        reports = [
            {
                "name": "slow",
                "url": "https://example.test/slow.json",
                "kind": "tvbox_config",
                "ok": True,
                "latency_ms": 500,
                "detail": "ok",
                "success_streak": 1,
                "failure_streak": 0,
                "score": 10,
                "checked_at": "now",
                "_config": {"sites": [{"key": "slow"}]},
            },
            {
                "name": "stable",
                "url": "https://example.test/stable.json",
                "kind": "tvbox_config",
                "ok": True,
                "latency_ms": 600,
                "detail": "ok",
                "success_streak": 10,
                "failure_streak": 0,
                "score": 50,
                "checked_at": "now",
                "_config": {"sites": [{"key": "stable"}]},
            },
        ]
        output, status = build_tvbox_config({"sites": []}, reports)
        self.assertEqual(status["selected_config"], "stable")
        self.assertEqual(output["sites"][0]["key"], "stable")

    @patch("tvbox_aggregator.fetch")
    def test_catalog_discovery_expands_selected_records(self, mock_fetch):
        mock_fetch.return_value = CheckResult(
            True,
            10,
            "ok",
            json.dumps(
                [
                    {"code": "CN", "name": "China"},
                    {"code": "US", "name": "United States"},
                ]
            ).encode(),
        )
        config = {
            "catalog_discovery": [
                {
                    "url": "https://example.test/countries.json",
                    "include": ["CN"],
                    "playlist_template": "https://example.test/{code_lower}.m3u",
                }
            ]
        }
        candidates = load_candidates(config, 1)
        self.assertEqual(len(candidates["live_playlists"]), 1)
        self.assertEqual(
            candidates["live_playlists"][0]["url"],
            "https://example.test/cn.m3u",
        )


if __name__ == "__main__":
    unittest.main()
