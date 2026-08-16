#!/usr/bin/env python3
"""Verify each FastAPI Swagger page works through the gateway prefix."""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request


BASE = "http://localhost"
SERVICES = {
    "auth": "auth-service",
    "domain": "domain-service",
    "agent": "agent-service",
}


def fetch(path: str) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(f"{BASE}{path}", timeout=10) as response:
            return response.status, response.read().decode()
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode(errors="replace")


def main() -> int:
    failures: list[str] = []

    for service, title in SERVICES.items():
        prefix = f"/api/{service}"
        docs_status, docs = fetch(f"{prefix}/docs")
        expected_target = f"url: '{prefix}/openapi.json'"
        if docs_status != 200:
            failures.append(f"{service}: docs returned HTTP {docs_status}")
        elif expected_target not in docs:
            failures.append(
                f"{service}: Swagger targets the wrong schema URL; expected {expected_target!r}"
            )

        schema_status, raw_schema = fetch(f"{prefix}/openapi.json")
        if schema_status != 200:
            failures.append(f"{service}: OpenAPI schema returned HTTP {schema_status}")
            continue
        try:
            schema = json.loads(raw_schema)
        except json.JSONDecodeError as error:
            failures.append(f"{service}: OpenAPI response is not JSON: {error}")
            continue
        if not schema.get("openapi"):
            failures.append(f"{service}: OpenAPI response has no version field")
        if schema.get("info", {}).get("title") != title:
            failures.append(f"{service}: OpenAPI response has the wrong service title")

    if failures:
        for failure in failures:
            print(f"FAIL {failure}", file=sys.stderr)
        return 1

    print("PASS Swagger docs and OpenAPI schemas work through all gateway prefixes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
