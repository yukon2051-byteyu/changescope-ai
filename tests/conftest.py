"""テスト全体の共通の準備。"""

import pytest

from changescope import usage_store


@pytest.fixture(autouse=True)
def local_usage_store(monkeypatch):
    """テストでは、secrets に外部のデータベースの接続先があっても、このPCのファイルに記録する（本物の記録を汚さない）。"""
    monkeypatch.setattr(usage_store, "database_url", lambda: None)
