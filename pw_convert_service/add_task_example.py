#!/usr/bin/env python3
"""
WIP add task via API

Exmaple:
    python3 add_task.py
    python3 add_task.py --duration 30
    python3 add_task.py --duration 15 --fail-at 40
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_BASE_URL = os.genenv('PW_CONV_HOST_URL') or "http://127.0.0.1:8000"


def add_task(base_url: str, duration: float, fail_at: int | None) -> dict:
    params = {"duration_sec": str(duration)}
    if fail_at is not None:
        params["fail_at"] = str(fail_at)
    url = f"{base_url}/tasks?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, method="POST")
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
    parser = argparse.ArgumentParser(description="Create a test task via API")
    parser.add_argument("--duration", type=float, default=10.0, help="duration_sec (default: 10)")
    parser.add_argument("--fail-at", type=int, default=None, help="fail on progress 5-95")
    parser.add_argument("--url", default=DEFAULT_BASE_URL, help=f"API base url (default: {DEFAULT_BASE_URL})")
    args = parser.parse_args()

    if args.duration <= 0:
        raise SystemExit("--duration must be > 0")
    if args.fail_at is not None and not 5 <= args.fail_at <= 95:
        raise SystemExit("--fail-at must be between 5 and 95")

    result = add_task(args.url.rstrip("/"), args.duration, args.fail_at)
    print(f"created: uuid={result['uuid']} status={result['status']}")


if __name__ == "__main__":
    sys.exit(main())
