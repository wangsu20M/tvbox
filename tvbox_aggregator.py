#!/usr/bin/env python3
"""Build a stable TVBox configuration from explicitly trusted public sources."""

from __future__ import annotations

import argparse
import gzip
import ipaddress
import json
import os
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


USER_AGENT = "tvbox-source-keeper/1.0 (+https://github.com/)"
SENSITIVE_RE = re.compile(
    r"(cookie|authorization|refresh[_-]?token|access[_-]?token|"
    r"quark[_-]?(cookie|token)|uc[_-]?(cookie|token)|baidu[_-]?(cookie|token)|"
    r"pan[_-]?cookie)",
    re.IGNORECASE,
)
SUPPORTED_SCHEMES = {"http", "https"}


@dataclass
class CheckResult:
    ok: bool
    latency_ms: int
    detail: str
    content: bytes = b""
    final_url: str = ""


@dataclass
class Channel:
    name: str
    url: str
    metadata: str = ""
    group: str = ""


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def contains_sensitive_data(value: Any) -> bool:
    if isinstance(value, dict):
        return any(
            SENSITIVE_RE.search(str(key)) or contains_sensitive_data(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(contains_sensitive_data(item) for item in value)
    if isinstance(value, str):
        return bool(SENSITIVE_RE.search(value))
    return False


def public_http_url(url: str) -> tuple[bool, str]:
    try:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in SUPPORTED_SCHEMES or not parsed.hostname:
            return False, "only public http/https URLs are allowed"
        addresses = socket.getaddrinfo(parsed.hostname, parsed.port or 443)
        for address in addresses:
            ip = ipaddress.ip_address(address[4][0])
            if not ip.is_global:
                return False, f"non-public address rejected: {ip}"
    except (OSError, ValueError) as exc:
        return False, f"URL resolution failed: {exc}"
    return True, ""


def fetch(url: str, timeout: float, max_bytes: int = 2_000_000) -> CheckResult:
    allowed, reason = public_http_url(url)
    if not allowed:
        return CheckResult(False, 0, reason)

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json, application/xml, text/plain, */*",
            "Range": f"bytes=0-{max_bytes - 1}",
        },
    )
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            content = response.read(max_bytes + 1)
            latency = round((time.monotonic() - started) * 1000)
            if len(content) > max_bytes:
                return CheckResult(False, latency, "response exceeds size limit")
            return CheckResult(
                True,
                latency,
                f"HTTP {response.status}",
                content,
                response.geturl(),
            )
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        latency = round((time.monotonic() - started) * 1000)
        return CheckResult(False, latency, str(exc))


def decode_text(content: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            pass
    return content.decode("utf-8", errors="replace")


def validate_tvbox_config(content: bytes) -> tuple[bool, str, dict[str, Any] | None]:
    try:
        value = json.loads(decode_text(content))
    except json.JSONDecodeError as exc:
        return False, f"invalid JSON: {exc}", None
    if not isinstance(value, dict):
        return False, "root must be a JSON object", None
    if not any(key in value for key in ("sites", "lives", "spider", "parses")):
        return False, "not a recognizable TVBox configuration", None
    if contains_sensitive_data(value):
        return False, "configuration appears to contain account credentials", None
    return True, "valid TVBox JSON", value


def validate_playlist(content: bytes) -> tuple[bool, str]:
    text = decode_text(content).strip()
    if not text:
        return False, "empty playlist"
    if text.startswith("#EXTM3U") and "#EXTINF" in text:
        count = sum(1 for line in text.splitlines() if line.lstrip().startswith("#EXTINF"))
        return True, f"valid M3U playlist ({count} channels)"
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    count = sum(1 for line in lines if "," in line and "://" in line)
    if count:
        return True, f"valid TVBox text playlist ({count} channels)"
    return False, "unrecognized playlist format"


def parse_playlist(content: bytes, default_group: str = "") -> list[Channel]:
    text = decode_text(content)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    channels: list[Channel] = []
    pending_metadata = ""
    pending_name = ""
    pending_group = default_group
    for line in lines:
        if line.startswith("#EXTINF"):
            pending_metadata = line
            pending_name = line.rsplit(",", 1)[-1].strip() or "Unnamed"
            group_match = re.search(r'group-title="([^"]*)"', line, re.IGNORECASE)
            pending_group = (
                group_match.group(1).strip() if group_match else default_group
            )
            continue
        if line.startswith("#"):
            continue
        if "://" in line and pending_metadata:
            channels.append(
                Channel(pending_name, line, pending_metadata, pending_group)
            )
            pending_metadata = ""
            pending_name = ""
            pending_group = default_group
            continue
        if "," in line and "://" in line:
            name, url = line.split(",", 1)
            channels.append(
                Channel(name.strip() or "Unnamed", url.strip(), "", default_group)
            )
    return channels


def validate_stream(url: str, timeout: float, depth: int = 0) -> CheckResult:
    if "|" in url:
        return CheckResult(False, 0, "custom-header stream skipped")
    result = fetch(url, timeout, max_bytes=128_000)
    if not result.ok or not result.content:
        return result
    sample = result.content[:16_000]
    text = decode_text(sample).lstrip()
    if text.startswith("#EXTM3U"):
        media_urls = [
            line.strip()
            for line in text.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        if not media_urls:
            return CheckResult(False, result.latency_ms, "HLS manifest has no media URI")
        if depth >= 2:
            return CheckResult(False, result.latency_ms, "HLS nesting is too deep")
        child_url = urllib.parse.urljoin(result.final_url or url, media_urls[0])
        child = validate_stream(child_url, timeout, depth + 1)
        if child.ok:
            return CheckResult(
                True,
                result.latency_ms + child.latency_ms,
                "reachable HLS media segment",
                final_url=result.final_url or url,
            )
        return CheckResult(False, result.latency_ms + child.latency_ms, child.detail)
    if sample.startswith((b"\x47", b"\x00\x00\x00", b"FLV", b"RIFF", b"\x1aE\xdf\xa3")) or b"ftyp" in sample[:32]:
        return CheckResult(
            True, result.latency_ms, "reachable media stream", final_url=result.final_url
        )
    return CheckResult(False, result.latency_ms, "response is not recognized media")


def check_streams(
    reports: list[dict[str, Any]],
    timeout: float,
    workers: int,
    max_total: int,
    max_per_playlist: int,
) -> tuple[list[Channel], dict[str, Any]]:
    candidates: list[Channel] = []
    seen_urls: set[str] = set()
    for report in sorted(
        (item for item in reports if item["ok"] and item["kind"] == "live_playlist"),
        key=lambda item: (-item["score"], item["name"]),
    ):
        playlist = report.get("_playlist", b"")
        parsed = parse_playlist(playlist, report["name"])
        parsed = [
            channel
            for channel in parsed
            if "[geo-blocked]" not in channel.name.lower()
        ]
        selected = parsed[:max_per_playlist] if max_per_playlist > 0 else parsed
        for channel in selected:
            if channel.url not in seen_urls:
                candidates.append(channel)
                seen_urls.add(channel.url)
            if max_total > 0 and len(candidates) >= max_total:
                break
        if max_total > 0 and len(candidates) >= max_total:
            break

    checked = 0
    available: list[tuple[Channel, CheckResult]] = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        futures = {
            executor.submit(validate_stream, channel.url, timeout): channel
            for channel in candidates
        }
        for future in as_completed(futures):
            checked += 1
            result = future.result()
            if result.ok:
                channel = futures[future]
                if result.final_url:
                    channel.url = result.final_url
                available.append((channel, result))
    available.sort(key=lambda item: (item[1].latency_ms, item[0].group, item[0].name))
    return [item[0] for item in available], {
        "streams_checked": checked,
        "streams_available": len(available),
    }


def build_m3u(channels: list[Channel]) -> str:
    lines = ["#EXTM3U"]
    for channel in channels:
        if channel.metadata:
            metadata = channel.metadata
        else:
            escaped_group = channel.group.replace('"', "'")
            metadata = (
                f'#EXTINF:-1 group-title="{escaped_group}",{channel.name}'
            )
        lines.extend((metadata, channel.url))
    return "\n".join(lines) + "\n"


def validate_epg(content: bytes) -> tuple[bool, str]:
    try:
        if content.startswith(b"\x1f\x8b"):
            content = gzip.decompress(content)
    except (gzip.BadGzipFile, OSError) as exc:
        return False, f"invalid gzip: {exc}"
    sample = decode_text(content[:100_000]).lstrip()
    if "<tv" in sample[:10_000] and ("<channel" in sample or "<programme" in sample):
        return True, "valid XMLTV document"
    return False, "unrecognized XMLTV format"


def normalize_entry(entry: dict[str, Any], kind: str) -> dict[str, Any]:
    normalized = {
        "name": str(entry.get("name", "")).strip(),
        "url": str(entry.get("url", "")).strip(),
        "enabled": bool(entry.get("enabled", True)),
        "kind": kind,
    }
    if "epg" in entry:
        normalized["epg"] = str(entry["epg"]).strip()
    if "logo" in entry:
        normalized["logo"] = str(entry["logo"]).strip()
    return normalized


def load_candidates(config: dict[str, Any], timeout: float) -> dict[str, list[dict[str, Any]]]:
    result = {
        "tvbox_configs": [
            normalize_entry(item, "tvbox_config")
            for item in config.get("tvbox_configs", [])
        ],
        "live_playlists": [
            normalize_entry(item, "live_playlist")
            for item in config.get("live_playlists", [])
        ],
        "epg_sources": [
            normalize_entry(item, "epg")
            for item in config.get("epg_sources", [])
        ],
    }

    for feed in config.get("discovery_feeds", []):
        if not feed.get("enabled", True):
            continue
        response = fetch(str(feed.get("url", "")), timeout)
        if not response.ok:
            continue
        try:
            discovered = json.loads(decode_text(response.content))
        except json.JSONDecodeError:
            continue
        if not isinstance(discovered, dict) or contains_sensitive_data(discovered):
            continue
        for key, kind in (
            ("tvbox_configs", "tvbox_config"),
            ("live_playlists", "live_playlist"),
            ("epg_sources", "epg"),
        ):
            for item in discovered.get(key, []):
                if isinstance(item, dict):
                    result[key].append(normalize_entry(item, kind))

    for catalog in config.get("catalog_discovery", []):
        if not catalog.get("enabled", True):
            continue
        response = fetch(str(catalog.get("url", "")), timeout)
        if not response.ok:
            continue
        try:
            records = json.loads(decode_text(response.content))
        except json.JSONDecodeError:
            continue
        if not isinstance(records, list):
            continue
        code_field = str(catalog.get("code_field", "code"))
        name_field = str(catalog.get("name_field", "name"))
        template = str(catalog.get("playlist_template", ""))
        include = {str(value).lower() for value in catalog.get("include", [])}
        prefix = str(catalog.get("name_prefix", "")).strip()
        epg = str(catalog.get("epg", "")).strip()
        for record in records:
            if not isinstance(record, dict):
                continue
            code = str(record.get(code_field, "")).strip()
            if not code or (include and code.lower() not in include):
                continue
            url = template.replace("{code}", code).replace(
                "{code_lower}", code.lower()
            )
            item = {
                "name": f"{prefix} {record.get(name_field, code)}".strip(),
                "url": url,
                "enabled": True,
            }
            if epg:
                item["epg"] = epg
            result["live_playlists"].append(
                normalize_entry(item, "live_playlist")
            )

    for key in result:
        unique: dict[str, dict[str, Any]] = {}
        for item in result[key]:
            if item["enabled"] and item["name"] and item["url"]:
                unique[item["url"]] = item
        result[key] = list(unique.values())
    return result


def score_result(result: CheckResult, streak: int) -> float:
    if not result.ok:
        return 0.0
    latency_points = max(0.0, 40.0 - min(result.latency_ms, 8_000) / 200.0)
    reliability_points = min(max(streak, 1), 30) * 2.0
    return round(latency_points + reliability_points, 2)


def check_candidates(
    candidates: dict[str, list[dict[str, Any]]],
    previous: dict[str, Any],
    timeout: float,
    workers: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    reports: list[dict[str, Any]] = []
    state: dict[str, Any] = {"updated_at": utc_now(), "sources": {}}
    validators = {
        "tvbox_config": validate_tvbox_config,
        "live_playlist": validate_playlist,
        "epg": validate_epg,
    }

    all_entries = (
        candidates["tvbox_configs"]
        + candidates["live_playlists"]
        + candidates["epg_sources"]
    )
    previous_sources = previous.get("sources", {})
    def check_one(entry: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        response = fetch(entry["url"], timeout)
        parsed_config = None
        if response.ok:
            validation = validators[entry["kind"]](response.content)
            valid, detail = validation[0], validation[1]
            if entry["kind"] == "tvbox_config":
                parsed_config = validation[2]
        else:
            valid, detail = False, response.detail

        old = previous_sources.get(entry["url"], {})
        streak = int(old.get("success_streak", 0)) + 1 if valid else 0
        failures = 0 if valid else int(old.get("failure_streak", 0)) + 1
        checked = {
            **entry,
            "ok": valid,
            "latency_ms": response.latency_ms,
            "detail": detail,
            "success_streak": streak,
            "failure_streak": failures,
            "score": score_result(response if valid else CheckResult(False, 0, detail), streak),
            "checked_at": state["updated_at"],
        }
        channel_match = re.search(r"\((\d+) channels\)", detail)
        if channel_match:
            checked["channel_count"] = int(channel_match.group(1))
        if parsed_config is not None:
            checked["_config"] = parsed_config
        if valid and entry["kind"] == "live_playlist":
            checked["_playlist"] = response.content
        source_state = {
            key: checked[key]
            for key in (
                "ok",
                "latency_ms",
                "detail",
                "success_streak",
                "failure_streak",
                "score",
                "checked_at",
            )
        }
        return checked, source_state

    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        futures = {executor.submit(check_one, entry): entry for entry in all_entries}
        for future in as_completed(futures):
            checked, source_state = future.result()
            reports.append(checked)
            state["sources"][checked["url"]] = source_state
    return reports, state


def build_tvbox_config(
    base: dict[str, Any],
    reports: list[dict[str, Any]],
    verified_channels: list[Channel] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    good = [item for item in reports if item["ok"]]
    configs = sorted(
        (item for item in good if item["kind"] == "tvbox_config"),
        key=lambda item: (-item["score"], item["latency_ms"], item["name"]),
    )
    playlists = sorted(
        (item for item in good if item["kind"] == "live_playlist"),
        key=lambda item: (-item["score"], item["latency_ms"], item["name"]),
    )
    epgs = sorted(
        (item for item in good if item["kind"] == "epg"),
        key=lambda item: (-item["score"], item["latency_ms"], item["name"]),
    )

    output = dict(base)
    output.pop("published_live_url", None)
    selected_config = None
    if configs:
        selected_config = configs[0]
        output.update(selected_config["_config"])

    if verified_channels:
        live_url = str(
            base.get(
                "published_live_url",
                "https://raw.githubusercontent.com/wangsu20M/tvbox/main/public/live.m3u",
            )
        )
        output["lives"] = [
            {
                "name": f"每日验证直播 ({len(verified_channels)})",
                "type": 0,
                "url": live_url,
                "playerType": 1,
                "epg": epgs[0]["url"] if epgs else "",
                "logo": "",
            }
        ]
    elif playlists:
        default_epg = epgs[0]["url"] if epgs else ""
        output["lives"] = [
            {
                "name": item["name"],
                "type": 0,
                "url": item["url"],
                "playerType": 1,
                "epg": item.get("epg") or default_epg,
                "logo": item.get("logo", ""),
            }
            for item in playlists
        ]

    public_reports = [
        {
            key: value
            for key, value in item.items()
            if key not in ("_config", "_playlist")
        }
        for item in sorted(
            reports,
            key=lambda item: (
                not item["ok"],
                -item["score"],
                item["kind"],
                item["name"],
            ),
        )
    ]
    status = {
        "updated_at": utc_now(),
        "selected_config": selected_config["name"] if selected_config else None,
        "counts": {
            "checked": len(reports),
            "available": len(good),
            "configs": len(configs),
            "live_playlists": len(playlists),
            "epg_sources": len(epgs),
            "channels_listed": sum(
                int(item.get("channel_count", 0)) for item in playlists
            ),
        },
        "sources": public_reports,
    }
    return output, status


def build_index(status: dict[str, Any]) -> str:
    counts = status["counts"]
    rows = "\n".join(
        "<tr>"
        f"<td>{item['name']}</td><td>{item['kind']}</td>"
        f"<td>{'可用' if item['ok'] else '不可用'}</td>"
        f"<td>{item['latency_ms']} ms</td><td>{item['score']}</td>"
        "</tr>"
        for item in status["sources"]
    )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>TVBox Source Keeper</title>
  <style>
    body {{ font: 16px/1.5 system-ui,sans-serif; max-width: 960px; margin: 40px auto; padding: 0 20px; color: #172033; }}
    code {{ background: #eef2f7; padding: 3px 6px; border-radius: 5px; }}
    table {{ width: 100%; border-collapse: collapse; margin-top: 24px; }}
    th,td {{ text-align: left; border-bottom: 1px solid #dce3ec; padding: 10px; }}
  </style>
</head>
<body>
  <h1>TVBox Source Keeper</h1>
  <p>最后更新：{status['updated_at']}</p>
  <p>已检查 {counts['checked']} 个候选，当前可用 {counts['available']} 个。</p>
  <p>可用播放列表共登记 {counts.get('channels_listed', 0)} 个频道条目。</p>
  <p>TVBox 固定配置地址：<code>tvbox.json</code></p>
  <table>
    <thead><tr><th>名称</th><th>类型</th><th>状态</th><th>延迟</th><th>评分</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
</body>
</html>
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidates", type=Path, default=Path("config/candidates.json"))
    parser.add_argument("--base", type=Path, default=Path("config/base.json"))
    parser.add_argument("--state", type=Path, default=Path("data/state.json"))
    parser.add_argument("--output", type=Path, default=Path("public"))
    parser.add_argument(
        "--timeout", type=float, default=float(os.environ.get("CHECK_TIMEOUT", "12"))
    )
    parser.add_argument(
        "--workers", type=int, default=int(os.environ.get("CHECK_WORKERS", "12"))
    )
    parser.add_argument(
        "--stream-workers",
        type=int,
        default=int(os.environ.get("STREAM_CHECK_WORKERS", "32")),
    )
    args = parser.parse_args()

    candidate_config = read_json(args.candidates, {})
    base = read_json(args.base, {})
    previous = read_json(args.state, {})
    candidates = load_candidates(candidate_config, args.timeout)
    reports, state = check_candidates(
        candidates, previous, args.timeout, args.workers
    )
    stream_config = candidate_config.get("stream_check", {})
    verified_channels, stream_status = check_streams(
        reports,
        float(stream_config.get("timeout", 7)),
        args.stream_workers,
        int(stream_config.get("max_total", 800)),
        int(stream_config.get("max_per_playlist", 100)),
    )
    output, status = build_tvbox_config(base, reports, verified_channels)
    status["counts"].update(stream_status)

    write_json(args.state, state)
    write_json(args.output / "tvbox.json", output)
    write_json(args.output / "status.json", status)
    (args.output / "live.m3u").write_text(
        build_m3u(verified_channels), encoding="utf-8", newline="\n"
    )
    (args.output / "index.html").write_text(
        build_index(status), encoding="utf-8", newline="\n"
    )
    print(
        f"checked={status['counts']['checked']} "
        f"available={status['counts']['available']} "
        f"selected={status['selected_config'] or 'base'}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
