#!/usr/bin/env python3
"""Minimal MacCMS-compatible VOD API for TVBox."""

from __future__ import annotations

import argparse
import json
import math
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


CATALOG_PATH = Path("data/vod_catalog.json")
PAGE_SIZE = 20


def load_catalog(path: Path = CATALOG_PATH) -> list[dict]:
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def summary(item: dict) -> dict:
    return {
        "vod_id": item["id"],
        "vod_name": item["name"],
        "vod_pic": item.get("pic", ""),
        "vod_remarks": item.get("remarks") or item.get("year", ""),
    }


def detail(item: dict) -> dict:
    value = summary(item)
    value.update(
        {
            "type_name": item.get("type", "公共领域电影"),
            "vod_year": item.get("year", ""),
            "vod_area": "公开版权",
            "vod_content": item.get("description", ""),
            "vod_play_from": "Internet Archive",
            "vod_play_url": f"正片${item['play_url']}",
        }
    )
    return value


def api_response(params: dict[str, list[str]], catalog: list[dict]) -> dict:
    ac = params.get("ac", ["list"])[0]
    ids = params.get("ids", [""])[0]
    keyword = params.get("wd", [""])[0].strip().lower()
    type_id = params.get("t", [""])[0]
    page = max(1, int(params.get("pg", ["1"])[0] or 1))

    if ids:
        wanted = {value.strip() for value in ids.split(",") if value.strip()}
        items = [detail(item) for item in catalog if item["id"] in wanted]
        return {"code": 1, "msg": "数据列表", "page": 1, "pagecount": 1, "list": items}

    filtered = catalog
    if keyword:
        filtered = [
            item
            for item in catalog
            if keyword in item.get("name", "").lower()
            or keyword in item.get("description", "").lower()
        ]
    if type_id and type_id != "1":
        filtered = []

    start = (page - 1) * PAGE_SIZE
    page_items = filtered[start : start + PAGE_SIZE]
    response = {
        "code": 1,
        "msg": "数据列表",
        "page": page,
        "pagecount": max(1, math.ceil(len(filtered) / PAGE_SIZE)),
        "limit": PAGE_SIZE,
        "total": len(filtered),
        "list": [summary(item) for item in page_items],
    }
    if ac == "list" and not keyword and not type_id:
        response["class"] = [{"type_id": "1", "type_name": "公共领域电影"}]
    return response


def tvbox_config(api_base: str) -> dict:
    return {
        "wallpaper": "https://picsum.photos/1280/720",
        "sites": [
            {
                "key": "private_open_vod",
                "name": "私人点播库",
                "type": 1,
                "api": f"{api_base}/api/vod/",
                "searchable": 1,
                "quickSearch": 1,
                "filterable": 0,
            }
        ],
        "lives": [
            {
                "name": "墙内直连直播",
                "type": 0,
                "url": (
                    "https://raw.githubusercontent.com/"
                    "wangsu20M/tvbox/main/public/live.m3u"
                ),
                "playerType": 1,
                "epg": "https://worker-9dd4.onrender.com/guide.xml",
                "logo": "",
            }
        ],
    }


class VodHandler(BaseHTTPRequestHandler):
    catalog_path = CATALOG_PATH

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path in ("/", "/health"):
            body = {"ok": True, "items": len(load_catalog(self.catalog_path))}
        elif parsed.path == "/tvbox.json":
            forwarded_proto = self.headers.get("X-Forwarded-Proto", "http")
            forwarded_host = self.headers.get("X-Forwarded-Host", self.headers["Host"])
            body = tvbox_config(f"{forwarded_proto}://{forwarded_host}")
        elif parsed.path.rstrip("/") == "/api/vod":
            body = api_response(parse_qs(parsed.query), load_catalog(self.catalog_path))
        else:
            self.send_error(404)
            return
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args) -> None:
        print(f"{self.address_string()} - {format % args}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--catalog", type=Path, default=CATALOG_PATH)
    args = parser.parse_args()
    VodHandler.catalog_path = args.catalog
    server = ThreadingHTTPServer((args.host, args.port), VodHandler)
    print(f"VOD API listening on http://{args.host}:{args.port}/api/vod/")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
