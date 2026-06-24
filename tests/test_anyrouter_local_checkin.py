import json

from scripts.anyrouter_local_checkin import is_waf_challenge, load_accounts, parse_cookies


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


def test_detects_anyrouter_waf_html_challenge():
	html = "<html><script>var arg1='ABC';</script></html>"

	assert is_waf_challenge('text/html', html)
	assert not is_waf_challenge('application/json', html)
