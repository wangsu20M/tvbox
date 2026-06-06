#!/usr/bin/env python3
"""Filter cloud-discovered streams using the current machine's direct network."""

from __future__ import annotations

import argparse
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.request import ProxyHandler, build_opener, install_opener

from tvbox_aggregator import build_m3u, parse_playlist, validate_stream


def disable_proxies() -> None:
    for name in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
    ):
        os.environ.pop(name, None)
    install_opener(build_opener(ProxyHandler({})))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=Path("public/candidates.m3u"))
    parser.add_argument("--output", type=Path, default=Path("public/live.m3u"))
    parser.add_argument("--timeout", type=float, default=7)
    parser.add_argument("--workers", type=int, default=32)
    args = parser.parse_args()

    disable_proxies()
    channels = parse_playlist(args.input.read_bytes())
    available = []
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        futures = {
            executor.submit(validate_stream, channel.url, args.timeout): channel
            for channel in channels
        }
        for future in as_completed(futures):
            result = future.result()
            if result.ok:
                channel = futures[future]
                if result.final_url:
                    channel.url = result.final_url
                available.append((channel, result.latency_ms))

    available.sort(key=lambda item: (item[1], item[0].group, item[0].name))
    args.output.write_text(
        build_m3u([item[0] for item in available]),
        encoding="utf-8",
        newline="\n",
    )
    print(f"direct_checked={len(channels)} direct_available={len(available)}")
    return 0 if available else 2


if __name__ == "__main__":
    raise SystemExit(main())
