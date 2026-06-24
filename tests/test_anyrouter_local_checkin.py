import json

from scripts.anyrouter_local_checkin import load_accounts, parse_cookies


def test_parse_cookie_header_string():
	assert parse_cookies('session=abc; theme=dark') == {'session': 'abc', 'theme': 'dark'}


def test_load_accounts_from_local_file_when_env_missing(tmp_path, monkeypatch):
	accounts_file = tmp_path / 'accounts.json'
	accounts_file.write_text(
		json.dumps([{'name': 'AnyRouter-local', 'cookies': {'session': 'abc'}, 'api_user': '123'}]),
		encoding='utf-8',
	)
	monkeypatch.delenv('ANYROUTER_ACCOUNTS', raising=False)

	accounts = load_accounts(accounts_file)

	assert accounts == [{'name': 'AnyRouter-local', 'cookies': {'session': 'abc'}, 'api_user': '123'}]
