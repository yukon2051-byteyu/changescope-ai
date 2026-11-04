"""アクセスコードの読み方のテスト。Hugging Face Spaces では secrets が環境変数で渡される。"""

from changescope.access import load_access_codes, parse_codes


def test_parse_codes_accepts_list_and_strings():
    assert parse_codes(["a", " b ", ""]) == ["a", "b"]
    assert parse_codes('["a", "b"]') == ["a", "b"]  # secrets.toml と同じ書き方を環境変数に入れたとき
    assert parse_codes("a, b,") == ["a", "b"]  # カンマ区切り
    assert parse_codes("") == [] and parse_codes(None) == []


def test_load_access_codes_falls_back_to_environment(monkeypatch):
    monkeypatch.setattr("streamlit.secrets", {}, raising=False)  # secrets.toml がない（Hugging Face Spaces）
    monkeypatch.setenv("ACCESS_CODES", '["code-1", "code-2"]')
    assert load_access_codes() == ["code-1", "code-2"]
    monkeypatch.delenv("ACCESS_CODES")
    assert load_access_codes() == []
