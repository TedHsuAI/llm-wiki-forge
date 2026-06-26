#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import ssl
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


API_URL = "https://in-tgdswebapistage.taiwantaxi.com.tw/api/Core/Setting/GetSystemVariableSetting"
EXPECTED_FIELDS = ("VarGroup", "VarKey", "VarValue", "VarText", "Comment")


def _json_result(
    *,
    ok: bool,
    var_group: str,
    var_key: str,
    status: int | None = None,
    data: Any = None,
    error: str | None = None,
    raw_text: str | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "ok": ok,
        "request": {
            "url": API_URL,
            "VarGroup": var_group,
            "VarKey": var_key,
        },
        "status": status,
        "data": data,
    }
    if isinstance(data, dict):
        result["normalized"] = {field: data.get(field) for field in EXPECTED_FIELDS}
    if error:
        result["error"] = error
    if raw_text is not None:
        result["raw_text"] = raw_text[:4000]
    return result


def _result_state(data: Any) -> int | None:
    if not isinstance(data, dict):
        return None
    result = data.get("Result")
    if not isinstance(result, dict):
        return None
    state = result.get("State")
    try:
        return int(state)
    except (TypeError, ValueError):
        return None


def _post_setting(
    *,
    var_group: str,
    var_key: str,
    timeout: float,
    insecure: bool,
    body: bytes,
    content_type: str,
) -> tuple[int | None, str | None, str | None]:
    request = Request(
        API_URL,
        data=body,
        headers={
            "Accept": "application/json",
            "Content-Type": content_type,
            "User-Agent": "Hermes-TGDS-SystemVariableSkill/1.0",
        },
        method="POST",
    )
    context = ssl._create_unverified_context() if insecure else None
    try:
        with urlopen(request, timeout=timeout, context=context) as response:
            status = int(response.status)
            body = response.read().decode("utf-8-sig", errors="replace")
            return status, body, None
    except HTTPError as exc:
        body = exc.read().decode("utf-8-sig", errors="replace")
        return int(exc.code), body, f"HTTP {exc.code}: {exc.reason}"
    except URLError as exc:
        return None, None, f"URL error: {exc.reason}"
    except TimeoutError:
        return None, None, f"Request timed out after {timeout:g}s"
    except OSError as exc:
        return None, None, f"Request failed: {exc}"


def fetch_setting(var_group: str, var_key: str, *, timeout: float, insecure: bool = False) -> dict[str, Any]:
    payload = {"VarGroup": var_group, "VarKey": var_key}
    attempts = [
        (json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json"),
        (urlencode(payload).encode("utf-8"), "application/x-www-form-urlencoded"),
    ]
    last_status: int | None = None
    last_body: str | None = None
    last_error: str | None = None

    for body, content_type in attempts:
        status, response_body, error = _post_setting(
            var_group=var_group,
            var_key=var_key,
            timeout=timeout,
            insecure=insecure,
            body=body,
            content_type=content_type,
        )
        last_status, last_body, last_error = status, response_body, error
        if status is None:
            break
        if 200 <= status < 300 and response_body is not None:
            break

    if last_body is None:
        return _json_result(
            ok=False,
            var_group=var_group,
            var_key=var_key,
            status=last_status,
            error=last_error or "Request failed",
        )

    try:
        data = json.loads(last_body) if last_body.strip() else None
    except json.JSONDecodeError:
        return _json_result(
            ok=False,
            var_group=var_group,
            var_key=var_key,
            status=last_status,
            error=last_error or "Response was not valid JSON",
            raw_text=last_body,
        )
    state = _result_state(data)
    return _json_result(
        ok=last_status is not None and 200 <= last_status < 300 and data is not None and (state is None or state >= 0),
        var_group=var_group,
        var_key=var_key,
        status=last_status,
        data=data,
        error=last_error,
        raw_text=None if isinstance(data, dict) else last_body,
    )


def print_human(result: dict[str, Any]) -> None:
    request = result.get("request") or {}
    print(f"VarGroup: {request.get('VarGroup')}")
    print(f"VarKey: {request.get('VarKey')}")
    print(f"ok: {result.get('ok')}")
    if result.get("status") is not None:
        print(f"status: {result.get('status')}")
    normalized = result.get("normalized") or {}
    if normalized:
        for field in EXPECTED_FIELDS:
            print(f"{field}: {normalized.get(field)}")
    elif result.get("data") is not None:
        print(json.dumps(result.get("data"), ensure_ascii=False, indent=2))
    if result.get("error"):
        print(f"error: {result.get('error')}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fetch TGDS system variable setting from stage API")
    parser.add_argument("--var-group", required=True, help="SYS_Variables VarGroup")
    parser.add_argument("--var-key", required=True, help="SYS_Variables VarKey")
    parser.add_argument("--timeout", type=float, default=10.0, help="HTTP timeout seconds")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    parser.add_argument("--insecure", action="store_true", help="Disable TLS verification for local/VPN certificate issues")
    args = parser.parse_args(argv)

    var_group = args.var_group.strip()
    var_key = args.var_key.strip()
    if not var_group or not var_key:
        print("VarGroup and VarKey are required.", file=sys.stderr)
        return 2

    result = fetch_setting(var_group, var_key, timeout=max(1.0, min(args.timeout, 60.0)), insecure=args.insecure)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print_human(result)
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
