#!/usr/bin/env python3
"""Local AnyRouter daily check-in.

This is intentionally shaped like the local AgentRouter launcher:
it reads local accounts from accounts.json, appends a concise report to
checkin.log, and avoids GitHub Actions secrets for AnyRouter accounts.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx


ROOT = Path(__file__).resolve().parents[1]
ACCOUNTS_FILE = ROOT / 'accounts.json'
LOG_FILE = ROOT / 'checkin.log'

BASE_URL = os.getenv('ANYROUTER_BASE_URL', 'https://anyrouter.top').rstrip('/')
API_USER_HEADER = os.getenv('ANYROUTER_API_USER_HEADER', 'new-api-user')
BASE_HOST = urlparse(BASE_URL).hostname or 'anyrouter.top'

HEADERS = {
	'User-Agent': (
		'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
		'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'
	),
	'Accept': 'application/json, text/plain, */*',
	'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
	'Content-Type': 'application/json',
	'Origin': BASE_URL,
	'Referer': BASE_URL + '/console/personal',
	'X-Requested-With': 'XMLHttpRequest',
}


class WAFChallengeError(RuntimeError):
	"""Raised when AnyRouter returns a browser challenge instead of JSON."""


def log(handle: Any, message: str) -> None:
	line = f'{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}  {message}'
	print(line)
	handle.write(line + '\n')
	handle.flush()


def parse_cookies(cookies: dict[str, Any] | str | None) -> dict[str, str]:
	if isinstance(cookies, dict):
		return {str(k): str(v) for k, v in cookies.items() if v is not None}
	if not isinstance(cookies, str):
		return {}

	parsed: dict[str, str] = {}
	for item in cookies.split(';'):
		if '=' not in item:
			continue
		key, value = item.strip().split('=', 1)
		if key:
			parsed[key] = value
	return parsed


def env_bool(name: str, default: bool = False) -> bool:
	value = os.getenv(name)
	if value is None:
		return default
	return value.strip().lower() in {'1', 'true', 'yes', 'on'}


def load_accounts(path: Path = ACCOUNTS_FILE) -> list[dict[str, Any]]:
	raw = os.getenv('ANYROUTER_ACCOUNTS')
	if raw:
		data = json.loads(raw)
	elif path.exists():
		data = json.loads(path.read_text(encoding='utf-8-sig'))
	else:
		raise RuntimeError(f'No accounts configured. Create {path} or set ANYROUTER_ACCOUNTS.')

	if not isinstance(data, list) or not data:
		raise RuntimeError('AnyRouter accounts must be a non-empty JSON array.')

	for idx, account in enumerate(data, start=1):
		if not isinstance(account, dict):
			raise RuntimeError(f'Account {idx} must be a JSON object.')
		if not parse_cookies(account.get('cookies')) or not account.get('api_user'):
			raise RuntimeError(f'Account {idx} needs cookies and api_user.')
	return data


def is_waf_challenge(content_type: str, text: str) -> bool:
	if 'json' in content_type:
		return False
	lower = text.lower()
	return '<html' in lower and ('arg1' in lower or 'acw_' in lower or 'waf' in lower or 'cdn_sec' in lower)


def read_json(response: httpx.Response) -> dict[str, Any]:
	content_type = response.headers.get('content-type', '')
	text = response.text
	if 'json' not in content_type:
		message = f'non-JSON response (HTTP {response.status_code}): {text[:120]!r}'
		if is_waf_challenge(content_type, text):
			raise WAFChallengeError(message)
		raise RuntimeError(message)
	try:
		payload = response.json()
	except json.JSONDecodeError as exc:
		raise RuntimeError(f'invalid JSON response (HTTP {response.status_code}): {text[:120]!r}') from exc
	if not isinstance(payload, dict):
		raise RuntimeError(f'unexpected JSON response type: {type(payload).__name__}')
	return payload


def quota_display(user_data: dict[str, Any]) -> str:
	quota = user_data.get('quota')
	used = user_data.get('used_quota')
	if isinstance(quota, (int, float)):
		quota = f'${quota / 500000:.2f}'
	if isinstance(used, (int, float)):
		used = f'${used / 500000:.2f}'
	return f'balance={quota if quota is not None else "?"}, used={used if used is not None else "?"}'


def get_user_info(client: httpx.Client, headers: dict[str, str]) -> dict[str, Any]:
	response = client.get(f'{BASE_URL}/api/user/self', headers=headers)
	payload = read_json(response)
	if not payload.get('success'):
		raise RuntimeError(payload.get('message') or payload.get('msg') or 'failed to fetch user info')
	data = payload.get('data')
	return data if isinstance(data, dict) else {}


def sign_in(client: httpx.Client, headers: dict[str, str]) -> tuple[bool, str]:
	response = client.post(f'{BASE_URL}/api/user/sign_in', headers=headers, json={})
	payload = read_json(response)
	if payload.get('success') or payload.get('ret') == 1 or payload.get('code') == 0:
		return True, payload.get('message') or payload.get('msg') or 'checked in'

	message = str(payload.get('message') or payload.get('msg') or payload)
	already_checked = ('already' in message.lower()) or ('已' in message and '签' in message)
	return already_checked, message


def get_browser_cookies(account_name: str, cookies: dict[str, str], api_user: str) -> dict[str, str]:
	try:
		from playwright.sync_api import sync_playwright
	except Exception as exc:
		raise RuntimeError('Playwright is required for AnyRouter WAF challenge. Install playwright and chromium.') from exc

	headless = env_bool('ANYROUTER_HEADLESS', default=False)
	print(f'[PROCESSING] {account_name}: opening browser to pass AnyRouter WAF (headless={headless})')
	with tempfile.TemporaryDirectory() as temp_dir:
		with sync_playwright() as p:
			context = p.chromium.launch_persistent_context(
				user_data_dir=temp_dir,
				headless=headless,
				user_agent=HEADERS['User-Agent'],
				viewport={'width': 1366, 'height': 768},
				args=[
					'--disable-blink-features=AutomationControlled',
					'--disable-dev-shm-usage',
					'--disable-web-security',
					'--disable-features=VizDisplayCompositor',
				],
			)
			try:
				context.add_cookies(
					[
						{
							'name': name,
							'value': value,
							'domain': BASE_HOST,
							'path': '/',
							'secure': BASE_URL.startswith('https://'),
						}
						for name, value in cookies.items()
					]
				)
				context.set_extra_http_headers({API_USER_HEADER: api_user, 'Accept': HEADERS['Accept']})
				page = context.new_page()

				for url in (f'{BASE_URL}/login', f'{BASE_URL}/api/user/self', f'{BASE_URL}/api/user/self'):
					try:
						page.goto(url, wait_until='networkidle', timeout=45000)
						page.wait_for_timeout(2500)
					except Exception as exc:
						print(f'[INFO] {account_name}: browser probe failed: {str(exc)[:80]}')

				return {c['name']: c['value'] for c in context.cookies(BASE_URL) if c.get('value')}
			finally:
				context.close()


def check_with_cookies(account_name: str, api_user: str, cookies: dict[str, str]) -> tuple[bool, str]:
	headers = {**HEADERS, API_USER_HEADER: api_user}
	with httpx.Client(http2=True, timeout=30, headers=HEADERS, follow_redirects=True) as client:
		client.cookies.update(cookies)
		before = get_user_info(client, headers)
		success, message = sign_in(client, headers)
		after = get_user_info(client, headers)

	detail = f'{message}; {quota_display(after or before)}'
	return success, detail


def check_one(account: dict[str, Any]) -> tuple[bool, str]:
	api_user = str(account.get('api_user') or '')
	cookies = parse_cookies(account.get('cookies'))
	if not api_user or not cookies:
		return False, 'missing api_user/cookies'

	name = str(account.get('name') or api_user)
	last_error: Exception | None = None
	for attempt in range(2):
		try:
			return check_with_cookies(name, api_user, cookies)
		except WAFChallengeError:
			browser_cookies = get_browser_cookies(name, cookies, api_user)
			cookies = {**browser_cookies, **cookies}
			return check_with_cookies(name, api_user, cookies)
		except httpx.TransportError as exc:
			last_error = exc
			if attempt == 0:
				continue
			raise
	raise last_error or RuntimeError('check-in failed')


def main() -> int:
	try:
		accounts = load_accounts()
	except Exception as exc:
		print(f'FATAL: {exc}')
		return 1

	ok = 0
	with LOG_FILE.open('a', encoding='utf-8') as handle:
		log(handle, f'===== AnyRouter local check-in: {len(accounts)} account(s) =====')
		for idx, account in enumerate(accounts, start=1):
			name = account.get('name') or f'AnyRouter-{idx}'
			try:
				success, detail = check_one(account)
			except Exception as exc:
				success, detail = False, f'{type(exc).__name__}: {exc}'
			if success:
				ok += 1
				log(handle, f'  OK   {name}: {detail}')
			else:
				log(handle, f'  FAIL {name}: {detail}')
		log(handle, f'===== Done: {ok}/{len(accounts)} succeeded =====\n')

	return 0 if ok == len(accounts) else 2


if __name__ == '__main__':
	sys.exit(main())
