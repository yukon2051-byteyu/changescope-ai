"""AI呼び出しの利用記録。費用と回数の監視に使う。

記録するのは日時・利用者（ハッシュ化した識別子）・機能・モデル・トークン数・費用・成否だけで、
入力文や分析内容は保存しない（利用者間でデータが混ざらないようにするため）。

保存先は2通り。
- 外部のデータベース（PostgreSQL。公開版は Neon の無料プラン）：secrets に USAGE_DATABASE_URL があるとき。
  公開先（Streamlit Community Cloud）ではアプリが休止するとファイルが消え、回数や予算の記録がリセットされるため
- このPCのファイル（SQLite）：USAGE_DATABASE_URL がないとき（ローカルで動かすとき）

外部のデータベースにつながらないときは例外を出す。AIを呼ぶ側（ai_client）はそれを受けて、AIの機能を止める
（記録できないまま呼ぶと、回数や予算の上限が効かなくなるため）。
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

CONNECT_TIMEOUT_SECONDS = 10  # 外部のデータベースが止まっている（Neon が休止から動き出す）ときの待ち時間

_COLUMNS = """
    created_at TEXT NOT NULL,
    month TEXT NOT NULL,
    user_key TEXT NOT NULL,
    feature TEXT NOT NULL,
    model TEXT NOT NULL,
    input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    cost_usd REAL NOT NULL,
    status TEXT NOT NULL
"""
_SCHEMA_SQLITE = f"CREATE TABLE IF NOT EXISTS api_usage (id INTEGER PRIMARY KEY AUTOINCREMENT, {_COLUMNS})"
_SCHEMA_POSTGRES = f"CREATE TABLE IF NOT EXISTS api_usage (id SERIAL PRIMARY KEY, {_COLUMNS})"


class UsageStoreUnavailable(Exception):
    """利用記録のデータベースにつながらない。"""


def hash_user(access_code: str) -> str:
    """アクセスコードをそのまま保存しないよう、ハッシュ化した識別子にする。"""
    return hashlib.sha256(access_code.encode("utf-8")).hexdigest()[:16]


def current_month(now: datetime | None = None) -> str:
    return (now or datetime.now()).strftime("%Y-%m")


def is_database_url(target: str) -> bool:
    return str(target).startswith(("postgres://", "postgresql://"))


@dataclass
class MonthlyUsage:
    month: str
    calls: int = 0
    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    calls_by_user: dict[str, int] = field(default_factory=dict)


class UsageStore:
    def __init__(self, target: str | Path):
        """target は、ファイルの場所（SQLite）か、外部のデータベースの接続先（postgresql://...）。

        つなぐのは、はじめて読み書きするときにする（画面を開いただけで外部につながないように）。
        """
        self.is_remote = is_database_url(str(target))
        self.target = str(target) if self.is_remote else Path(target)
        self._ready = False

    # ---------- つなぐ ----------
    @contextmanager
    def _connect(self):
        """データベースにつなぎ、終わったら確定して閉じる。つながらなければ UsageStoreUnavailable。"""
        try:
            if self.is_remote:
                import psycopg  # 外部のデータベースを使うときだけ読み込む

                conn = psycopg.connect(self.target, connect_timeout=CONNECT_TIMEOUT_SECONDS)
            else:
                self.target.parent.mkdir(parents=True, exist_ok=True)
                conn = sqlite3.connect(self.target)
        except Exception as e:  # 接続先の書き間違い・休止中・ネットワークの問題など
            raise UsageStoreUnavailable(f"利用記録のデータベースにつながりません（{type(e).__name__}）") from e
        try:
            if not self._ready:
                conn.execute(_SCHEMA_POSTGRES if self.is_remote else _SCHEMA_SQLITE)
                self._ready = True
            yield conn
            conn.commit()
        except UsageStoreUnavailable:
            raise
        except Exception as e:
            raise UsageStoreUnavailable(f"利用記録のデータベースを読み書きできません（{type(e).__name__}）") from e
        finally:
            conn.close()

    def _sql(self, sql: str) -> str:
        """SQLite の「?」を、PostgreSQL の「%s」に置き換える（値の埋め込み方の違い）。"""
        return sql.replace("?", "%s") if self.is_remote else sql

    def _one(self, sql: str, params: tuple):
        with self._connect() as conn:
            return conn.execute(self._sql(sql), params).fetchone()

    # ---------- 記録する・数える ----------
    def record(self, user_key: str, feature: str, model: str, input_tokens: int, output_tokens: int,
               cost_usd: float, status: str, now: datetime | None = None) -> None:
        now = now or datetime.now()
        with self._connect() as conn:
            conn.execute(
                self._sql("INSERT INTO api_usage (created_at, month, user_key, feature, model, input_tokens,"
                          " output_tokens, cost_usd, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"),
                (now.isoformat(timespec="seconds"), current_month(now), user_key, feature, model,
                 input_tokens, output_tokens, cost_usd, status),
            )

    def user_calls(self, user_key: str, feature: str, month: str | None = None) -> int:
        """その月に、その利用者がその機能を使った回数（成功した呼び出しだけ）。"""
        return self._one("SELECT COUNT(*) FROM api_usage WHERE month = ? AND user_key = ? AND feature = ? AND status = 'ok'",
                         (month or current_month(), user_key, feature))[0]

    def feature_cost(self, feature: str, month: str | None = None) -> float:
        """その月の、その機能の費用の合計（失敗した呼び出しも含む）。"""
        return float(self._one("SELECT COALESCE(SUM(cost_usd), 0) FROM api_usage WHERE month = ? AND feature = ?",
                               (month or current_month(), feature))[0])

    def monthly(self, month: str | None = None) -> MonthlyUsage:
        """その月の合計。

        - 費用・トークン数：失敗した呼び出しも含めてすべて合計する（料金が発生している場合があるため）
        - 回数：成功した呼び出しだけを数える（時間切れなど、利用者のせいではない失敗で回数を減らさないため）
        """
        month = month or current_month()
        usage = MonthlyUsage(month)
        with self._connect() as conn:
            cost, input_tokens, output_tokens = conn.execute(
                self._sql("SELECT COALESCE(SUM(cost_usd), 0), COALESCE(SUM(input_tokens), 0),"
                          " COALESCE(SUM(output_tokens), 0) FROM api_usage WHERE month = ?"), (month,),
            ).fetchone()
            usage.cost_usd, usage.input_tokens, usage.output_tokens = float(cost), int(input_tokens), int(output_tokens)
            for user_key, count in conn.execute(
                self._sql("SELECT user_key, COUNT(*) FROM api_usage WHERE month = ? AND status = 'ok' GROUP BY user_key"),
                (month,),
            ).fetchall():
                usage.calls_by_user[user_key] = count
        usage.calls = sum(usage.calls_by_user.values())
        return usage


def database_url() -> str | None:
    """外部のデータベースの接続先（Streamlit の secrets、なければ環境変数）。コードやGitには書かない。"""
    try:
        import streamlit as st

        url = st.secrets.get("USAGE_DATABASE_URL")
        if url:
            return str(url)
    except Exception:  # secrets.toml がない場合など
        pass
    return os.environ.get("USAGE_DATABASE_URL")


def open_store(local_path: str | Path) -> UsageStore:
    """利用記録の保存先を開く。外部のデータベースの接続先があればそれを、なければこのPCのファイルを使う。"""
    url = database_url()
    return UsageStore(url) if url else UsageStore(local_path)
