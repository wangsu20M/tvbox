#!/usr/bin/env python3
"""Build a small open-license VOD catalog from Internet Archive metadata."""

from __future__ import annotations

import argparse
import html
import json
import re
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


USER_AGENT = "tvbox-source-keeper/1.0"
SEARCH_URL = "https://archive.org/advancedsearch.php"
METADATA_URL = "https://archive.org/metadata/{identifier}"


def fetch_json(url: str, timeout: float = 20) -> Any:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def plain_text(value: Any) -> str:
    if isinstance(value, list):
        value = " ".join(str(item) for item in value)
    text = re.sub(r"<[^>]+>", " ", html.unescape(str(value or "")))
    return re.sub(r"\s+", " ", text).strip()


def select_video(files: list[dict[str, Any]]) -> dict[str, Any] | None:
    candidates = []
    for file in files:
        name = str(file.get("name", ""))
        if not name.lower().endswith(".mp4"):
            continue
        if any(token in name.lower() for token in ("sample", "thumb", "trailer")):
            continue
        size = int(file.get("size", 0) or 0)
        source = str(file.get("source", ""))
        candidates.append((source != "original", -size, file))
    candidates.sort(key=lambda item: (item[0], item[1]))
    return candidates[0][2] if candidates else None


def build_catalog(rows: int = 24) -> list[dict[str, Any]]:
    query = "mediatype:movies AND licenseurl:*publicdomain*"
    params = [
        ("q", query),
        ("fl[]", "identifier"),
        ("fl[]", "title"),
        ("fl[]", "year"),
        ("fl[]", "description"),
        ("fl[]", "licenseurl"),
        ("sort[]", "downloads desc"),
        ("rows", str(rows * 2)),
        ("page", "1"),
        ("output", "json"),
    ]
    search = fetch_json(f"{SEARCH_URL}?{urllib.parse.urlencode(params)}")
    catalog = []
    for document in search.get("response", {}).get("docs", []):
        identifier = str(document.get("identifier", "")).strip()
        if not identifier:
            continue
        metadata = fetch_json(METADATA_URL.format(identifier=identifier))
        item_metadata = metadata.get("metadata", {})
        license_url = str(
            item_metadata.get("licenseurl") or document.get("licenseurl") or ""
        )
        if "publicdomain" not in license_url.lower():
            continue
        video = select_video(metadata.get("files", []))
        if not video:
            continue
        filename = str(video["name"])
        catalog.append(
            {
                "id": identifier,
                "name": plain_text(item_metadata.get("title") or document.get("title")),
                "year": plain_text(item_metadata.get("date") or document.get("year")),
                "remarks": "公共领域",
                "type": "公共领域电影",
                "description": plain_text(
                    item_metadata.get("description") or document.get("description")
                ),
                "pic": f"https://archive.org/services/img/{identifier}",
                "play_url": (
                    "https://archive.org/download/"
                    f"{urllib.parse.quote(identifier)}/{urllib.parse.quote(filename)}"
                ),
                "source_url": f"https://archive.org/details/{identifier}",
                "license_url": license_url,
            }
        )
        if len(catalog) >= rows:
            break
    return catalog


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("data/vod_catalog.json"))
    parser.add_argument("--rows", type=int, default=24)
    args = parser.parse_args()
    catalog = build_catalog(args.rows)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"vod_items={len(catalog)}")
    return 0 if catalog else 2


if __name__ == "__main__":
    raise SystemExit(main())
