#!/usr/bin/env python3
"""BMAPI daily check-in.

Configuration:
  - GitHub Actions: BMAPI_ACCOUNTS secret
  - Local: accounts.json next to this script, or BMAPI_ACCOUNTS

BMAPI_ACCOUNTS/accounts.json format:
  [{"name":"BMAPI-main","refresh_token":"...","access_token":"..."}]

refresh_token is preferred because password login is protected by hCaptcha.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
ACCOUNTS_FILE = HERE / "accounts.json"
LOG_FILE = HERE / "bmapi-checkin.log"

BASE_URL = os.getenv("BMAPI_BASE_URL", "https://bmapi.020212.xyz").rstrip("/")
API_BASE = f"{BASE_URL}/api/v1"
TIMEZONE = os.getenv("BMAPI_TIMEZONE", "Asia/Shanghai")


def log(handle: Any, message: str) -> None:
    line = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  {message}"
    print(line)
    if handle:
        handle.write(line + "\n")
        handle.flush()


def load_accounts() -> list[dict[str, Any]]:
    raw = os.getenv("BMAPI_ACCOUNTS")
    if raw:
        data = json.loads(raw)
    elif ACCOUNTS_FILE.exists():
        data = json.loads(ACCOUNTS_FILE.read_text(encoding="utf-8-sig"))
    else:
        raise RuntimeError("No accounts configured. Set BMAPI_ACCOUNTS or create accounts.json.")

    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list) or not data:
        raise RuntimeError("BMAPI_ACCOUNTS/accounts.json must be a non-empty JSON array.")
    for item in data:
        if not isinstance(item, dict):
            raise RuntimeError("Each account must be a JSON object.")
    return data


def unwrap(payload: Any) -> Any:
    if isinstance(payload, dict) and "code" in payload:
        if payload.get("code") == 0:
            return payload.get("data")
        raise RuntimeError(payload.get("message") or json.dumps(payload, ensure_ascii=False))
    return payload


class BMAPIClient:
    def __init__(self, access_token: str | None = None) -> None:
        self.access_token = access_token

    def request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        auth: bool = True,
    ) -> Any:
        url = f"{API_BASE}{path}"
        if method.upper() == "GET":
            query = urllib.parse.urlencode({"timezone": TIMEZONE})
            url = f"{url}?{query}"

        data = None
        if method.upper() != "GET":
            data = json.dumps(body if body is not None else {}).encode("utf-8")

        headers = {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh",
            "Content-Type": "application/json",
            "Origin": BASE_URL,
            "Referer": f"{BASE_URL}/dashboard",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            ),
        }
        if auth and self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"

        req = urllib.request.Request(url, data=data, headers=headers, method=method.upper())
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                text = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            text = exc.read().decode("utf-8", errors="replace")
            try:
                payload = json.loads(text)
                raise RuntimeError(payload.get("message") or text[:300]) from exc
            except json.JSONDecodeError as err:
                raise RuntimeError(f"HTTP {exc.code}: {text[:300]}") from err

        try:
            return unwrap(json.loads(text))
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Non-JSON response: {text[:300]!r}") from exc

    def refresh(self, refresh_token: str) -> dict[str, Any]:
        data = self.request("POST", "/auth/refresh", {"refresh_token": refresh_token}, auth=False)
        if not isinstance(data, dict) or not data.get("access_token"):
            raise RuntimeError("Refresh succeeded but no access_token was returned.")
        self.access_token = data["access_token"]
        return data

    def me(self) -> dict[str, Any]:
        data = self.request("GET", "/auth/me")
        return data if isinstance(data, dict) else {}

    def checkin_status(self) -> dict[str, Any]:
        data = self.request("GET", "/checkin/status")
        return data if isinstance(data, dict) else {}

    def checkin(self) -> dict[str, Any]:
        data = self.request("POST", "/checkin")
        return data if isinstance(data, dict) else {}


def check_one(account: dict[str, Any]) -> tuple[bool, str, dict[str, Any] | None]:
    refresh_token = account.get("refresh_token") or account.get("refreshToken")
    access_token = (
        account.get("access_token")
        or account.get("auth_token")
        or account.get("authToken")
        or account.get("token")
    )

    if not refresh_token and not access_token:
        return False, "missing refresh_token/access_token", None

    client = BMAPIClient(access_token=access_token)
    updated: dict[str, Any] | None = None

    if refresh_token:
        tokens = client.refresh(str(refresh_token))
        updated = {
            "access_token": tokens.get("access_token"),
            "refresh_token": tokens.get("refresh_token") or refresh_token,
        }

    user = client.me()
    status = client.checkin_status()
    if status.get("checked_in"):
        return True, f"already checked in, balance={user.get('balance')}", updated

    claimed = client.checkin()
    try:
        balance = client.me().get("balance")
    except Exception:
        balance = user.get("balance")

    reward = claimed.get("reward") or claimed.get("reward_template") or status.get("reward_template")
    return True, f"checked in, reward={reward}, balance={balance}", updated


def apply_updates(accounts: list[dict[str, Any]], updates: dict[int, dict[str, Any]]) -> None:
    for idx, tokens in updates.items():
        accounts[idx].update({k: v for k, v in tokens.items() if v})


def write_accounts(path: Path, accounts: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(accounts, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def maybe_write_updated_accounts(accounts: list[dict[str, Any]], updates: dict[int, dict[str, Any]]) -> None:
    if not updates:
        return
    apply_updates(accounts, updates)

    updated_file = os.getenv("BMAPI_UPDATED_ACCOUNTS_FILE")
    if updated_file:
        write_accounts(Path(updated_file), accounts)

    if os.getenv("BMAPI_WRITE_BACK", "1") not in {"1", "true", "TRUE", "yes"}:
        return
    if not ACCOUNTS_FILE.exists() or os.getenv("BMAPI_ACCOUNTS"):
        return
    write_accounts(ACCOUNTS_FILE, accounts)


def main() -> int:
    try:
        accounts = load_accounts()
    except Exception as exc:
        print(f"FATAL: {exc}")
        return 1

    updates: dict[int, dict[str, Any]] = {}
    ok = 0
    with LOG_FILE.open("a", encoding="utf-8") as handle:
        log(handle, f"===== BMAPI check-in: {len(accounts)} account(s) =====")
        for idx, account in enumerate(accounts):
            name = account.get("name") or account.get("email") or f"account-{idx + 1}"
            try:
                success, detail, updated = check_one(account)
            except Exception as exc:
                success, detail, updated = False, f"{type(exc).__name__}: {exc}", None

            if updated:
                updates[idx] = updated
            if success:
                ok += 1
                log(handle, f"  OK   {name}: {detail}")
            else:
                log(handle, f"  FAIL {name}: {detail}")
        log(handle, f"===== Done: {ok}/{len(accounts)} succeeded =====\n")

    maybe_write_updated_accounts(accounts, updates)
    return 0 if ok == len(accounts) else 2


if __name__ == "__main__":
    sys.exit(main())
