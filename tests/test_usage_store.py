"""利用記録の保存先（このPCのファイル／外部のデータベース）のテスト。外部のデータベースには実際にはつながない。"""

import dataclasses

import pytest

from changescope import usage_store
from changescope.ai_client import AIClient
from changescope.ai_settings import load_settings
from changescope.usage_store import UsageStore, UsageStoreUnavailable, hash_user, is_database_url, open_store

# だれも待ち受けていない場所（1番ポート）。すぐに「つながらない」になる
DOWN_URL = "postgresql://user:pass@127.0.0.1:1/usage"


def test_target_kind():
    assert is_database_url("postgresql://u:p@host/db") and is_database_url("postgres://u:p@host/db")
    assert not is_database_url("data/usage.db")
    assert UsageStore(DOWN_URL).is_remote and not UsageStore("data/usage.db").is_remote


def test_placeholders_are_converted_only_for_postgres():
    sql = "SELECT COUNT(*) FROM api_usage WHERE month = ? AND user_key = ?"
    assert UsageStore("data/usage.db")._sql(sql) == sql
    assert UsageStore(DOWN_URL)._sql(sql).endswith("month = %s AND user_key = %s")


def test_local_file_records_and_counts(tmp_path):
    store = UsageStore(tmp_path / "sub" / "usage.db")  # フォルダがなくても作る
    store.record("u1", "確認漏れ", "m", 100, 200, 0.01, "ok")
    store.record("u1", "確認漏れ", "m", 100, 0, 0.002, "timeout")
    assert store.user_calls("u1", "確認漏れ") == 1  # 失敗は回数に数えない
    assert store.feature_cost("確認漏れ") == pytest.approx(0.012)  # 費用には含める
    assert store.monthly().calls == 1


def test_unreachable_database_raises_a_clear_error():
    with pytest.raises(UsageStoreUnavailable, match="つながりません"):
        UsageStore(DOWN_URL).user_calls("u1", "確認漏れ")


def test_ai_stops_when_usage_cannot_be_checked():
    """記録先につながらないときは、AIを呼ばずに止める（上限が効かないまま呼ばない）。例外は出さない。"""
    calls = []
    fake = type("Fake", (), {"messages": type("M", (), {"create": lambda self, **k: calls.append(k)})()})()
    settings = dataclasses.replace(load_settings(), monthly_budget_usd=5.0)
    client = AIClient(settings, UsageStore(DOWN_URL), api_key="test", client=fake)
    result = client.call_json("テスト", "役割", "本文", {"type": "object"}, hash_user("code"), "本文")
    assert not result.ok and "データベースにつながらない" in result.message
    assert "AIを使わない分析結果は、そのまま表示しています" in result.message
    assert calls == []  # AIは呼んでいない（料金は発生しない）


def test_open_store_uses_database_url_when_set(monkeypatch, tmp_path):
    monkeypatch.setattr(usage_store, "database_url", lambda: DOWN_URL)
    assert open_store(tmp_path / "usage.db").is_remote
    monkeypatch.setattr(usage_store, "database_url", lambda: None)
    assert not open_store(tmp_path / "usage.db").is_remote


def test_database_url_falls_back_to_environment(monkeypatch):
    monkeypatch.undo()  # conftest で差し替えた database_url を元に戻して確かめる
    monkeypatch.setenv("USAGE_DATABASE_URL", DOWN_URL)
    monkeypatch.setattr("streamlit.secrets", {}, raising=False)
    assert usage_store.database_url() == DOWN_URL
