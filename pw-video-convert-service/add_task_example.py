#!/usr/bin/env python3
"""
Create a video conversion task via API.

Example:
    python3 add_task_example.py --input ~/video/in.mp4
    python3 add_task_example.py --input ~/video/in.mp4 --quality 7 --container mp4 --software
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

DEFAULT_BASE_URL = os.getenv("PW_CONV_HOST_URL") or "http://127.0.0.1:8000"


def add_task(base_url: str, payload: dict) -> dict:
    url = f"{base_url}/tasks"
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        try:
            detail = json.loads(body).get("detail", body)
        except json.JSONDecodeError:
            detail = body
        raise SystemExit(f"API error {e.code}: {detail}") from None
    except urllib.error.URLError as e:
        raise SystemExit(f"cannot reach {base_url}: {e.reason}") from None


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create a video conversion task via API"
    )
    parser.add_argument("--input", required=True, help="source video file")
    parser.add_argument(
        "--output", default=None,
        help="output subfolder, RELATIVE to the server output dir "
             "(default: the server output dir itself)",
    )
    parser.add_argument(
        "--quality", type=int, default=5, help="quality 1-10 (default: 5)",
    )
    parser.add_argument("--container", choices=["mkv", "mp4"], default="mkv")
    parser.add_argument(
        "--software", action="store_true", help="force software SVT-AV1",
    )
    parser.add_argument(
        "--url", default=DEFAULT_BASE_URL,
        help=f"API base url (default: {DEFAULT_BASE_URL})",
    )
    args = parser.parse_args()

    payload: dict = {
        "input": args.input,
        "quality": args.quality,
        "container": args.container,
        "software": args.software,
    }
    if args.output is not None:
        payload["output"] = args.output

    result = add_task(args.url.rstrip("/"), payload)
    print(f"created: uuid={result['uuid']} status={result['status']}")


if __name__ == "__main__":
    sys.exit(main())
