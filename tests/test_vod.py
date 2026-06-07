import unittest

from vod_catalog import select_video
from vod_service import api_response, tvbox_config


CATALOG = [
    {
        "id": "demo",
        "name": "Demo Film",
        "year": "2026",
        "remarks": "公共领域",
        "type": "公共领域电影",
        "description": "A demo",
        "pic": "https://example.test/demo.jpg",
        "play_url": "https://example.test/demo.mp4",
    }
]


class CatalogTests(unittest.TestCase):
    def test_selects_largest_original_mp4(self):
        selected = select_video(
            [
                {"name": "small.mp4", "size": "100", "source": "derivative"},
                {"name": "movie.mp4", "size": "1000", "source": "original"},
            ]
        )
        self.assertEqual(selected["name"], "movie.mp4")


class ApiTests(unittest.TestCase):
    def test_home_has_class_and_items(self):
        response = api_response({"ac": ["list"]}, CATALOG)
        self.assertEqual(response["class"][0]["type_name"], "公共领域电影")
        self.assertEqual(response["list"][0]["vod_name"], "Demo Film")

    def test_detail_has_play_url(self):
        response = api_response({"ac": ["detail"], "ids": ["demo"]}, CATALOG)
        self.assertIn("$https://example.test/demo.mp4", response["list"][0]["vod_play_url"])

    def test_search(self):
        response = api_response({"wd": ["film"]}, CATALOG)
        self.assertEqual(response["total"], 1)

    def test_tvbox_config_points_to_service(self):
        config = tvbox_config("https://vod.example.test")
        self.assertEqual(
            config["sites"][0]["api"],
            "https://vod.example.test/api/vod/",
        )
        self.assertTrue(config["lives"][0]["url"].endswith("/public/live.m3u"))


if __name__ == "__main__":
    unittest.main()
