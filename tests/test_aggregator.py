import gzip
import json
import unittest
from unittest.mock import patch

from tvbox_aggregator import (
    CheckResult,
    Channel,
    build_m3u,
    build_tvbox_config,
    contains_sensitive_data,
    load_candidates,
    parse_playlist,
    validate_stream,
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

    def test_parse_playlist(self):
        channels = parse_playlist(
            b'#EXTM3U\n#EXTINF:-1 group-title="News",Demo\nhttps://x/live.m3u8'
        )
        self.assertEqual(len(channels), 1)
        self.assertEqual(channels[0].name, "Demo")
        self.assertEqual(channels[0].group, "News")

    def test_build_m3u(self):
        value = build_m3u([Channel("Demo", "https://x/live.m3u8", group="News")])
        self.assertIn('group-title="新闻",Demo', value)
        self.assertIn("https://x/live.m3u8", value)

    def test_build_m3u_prefers_source_region_group(self):
        value = build_m3u(
            [
                Channel(
                    "Demo",
                    "https://x/live.m3u8",
                    group="General",
                    source="公开频道 China",
                )
            ]
        )
        self.assertIn('group-title="中国大陆",Demo', value)

    @patch("tvbox_aggregator.fetch")
    def test_stream_validation_follows_hls_to_media(self, mock_fetch):
        mock_fetch.side_effect = [
            CheckResult(
                True,
                10,
                "ok",
                b"#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1\nchild.m3u8",
                "https://example.test/master.m3u8",
            ),
            CheckResult(
                True,
                10,
                "ok",
                b"#EXTM3U\n#EXTINF:10,\nsegment.ts",
                "https://example.test/child.m3u8",
            ),
            CheckResult(
                True,
                10,
                "ok",
                b"\x47" + b"\x00" * 512,
                "https://example.test/segment.ts",
            ),
        ]
        result = validate_stream("https://example.test/master.m3u8", 1)
        self.assertTrue(result.ok)
        self.assertEqual(mock_fetch.call_count, 3)

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

    def test_verified_channels_use_merged_playlist(self):
        output, _ = build_tvbox_config(
            {
                "sites": [],
                "published_live_url": "https://example.test/live.m3u",
            },
            [],
            [Channel("Demo", "https://x/live.m3u8")],
        )
        self.assertEqual(output["lives"][0]["url"], "https://example.test/live.m3u")

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
