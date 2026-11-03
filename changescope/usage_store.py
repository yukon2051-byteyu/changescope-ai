"""AI呼び出しの利用記録。費用と回数の監視に使う。

記録するのは日時・利用者（ハッシュ化した識別子）・機能・モデル・トークン数・費用・成否だけで、
入力文や分析内容は保存しない（利用者間でデータが混ざらないようにするため）。

保存先は2通り。
- 外部のデータベース（PostgreSQL。公開版は Neon の無料プラン）：secrets に USAGE_DATABASE_URL があるとき。
  公開先（Streamlit Community Cloud）ではアプリが休止するとファイルが消え、回数や予算の記録がリセットされるため
- このPCのファイル（SQLite）：USAGE_DATABASE_URL がないとき（ローカルで動かすとき）

外部のデータベースにつながらないときは例外を出す。AIを呼ぶ側（ai_client）はそれを受けて、AIの機能を止める
（記録できないまま呼ぶと、回数や予算の上限が効かなくなるため）。

同時に使われても上限を超えないよう、AIを呼ぶ前に「予約」の行を入れ、終わったら実際の費用で「精算」する
（レビュー X01）。確認と予約は locked() の中で、同時に1つだけ行う。精算されないまま RESERVATION_MINUTES を
過ぎた予約（途中でアプリが落ちた場合など）は数えない。
時刻は日本時間で記録する（公開先のサーバーは世界標準時のため。日・月の切り替わりを日本時間の0時にそろえる）。
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

CONNECT_TIMEOUT_SECONDS = 10  # 外部のデータベースが止まっている（Neon が休止から動き出す）ときの待ち時間
RESERVED = "reserved"  # 予約中（AIの回答を待っている）の行の status
RESERVATION_MINUTES = 10  # これより古い予約は数えない（精算されないまま残った予約で、止まったままにしない）
_LOCK_ID = 20261103  # PostgreSQL の「ロック」の番号（このアプリの利用記録用）
_JST = ZoneInfo("Asia/Tokyo")
# 数える行：予約中でない行と、まだ新しい予約（? には「予約の有効期限の時刻」を入れる）
_ACTIVE = "(status <> 'reserved' OR created_at >= ?)"
_COUNTED = "(status = 'ok' OR (status = 'reserved' AND created_at >= ?))"  # 回数に数える行

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


def now_jst() -> datetime:
    """いまの日本時間（時差の情報は外す。記録の文字列を日本時間でそろえるため）。"""
    return datetime.now(_JST).replace(tzinfo=None)


def current_month(now: datetime | None = None) -> str:
    return (now or now_jst()).strftime("%Y-%m")


def _fresh_since(now: datetime | None = None) -> str:
    """これより新しい予約だけを数える、という境目の時刻。"""
    return ((now or now_jst()) - timedelta(minutes=RESERVATION_MINUTES)).isoformat(timespec="seconds")


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
        self._local = threading.local()  # locked() の中で使い続ける接続（同時の処理どうしで混ざらないよう、スレッドごと）

    # ---------- つなぐ ----------
    @contextmanager
    def _connect(self):
        """データベースにつなぎ、終わったら確定して閉じる。つながらなければ UsageStoreUnavailable。

        locked() の中では、ロックを持った同じ接続を使う（確定と閉じるのは locked() が行う）。
        """
        held = getattr(self._local, "held", None)
        if held is not None:
            yield held
            return
        try:
            if self.is_remote:
                import psycopg  # 外部のデータベースを使うときだけ読み込む

                conn = psycopg.connect(self.target, connect_timeout=CONNECT_TIMEOUT_SECONDS)
            else:
                self.target.parent.mkdir(parents=True, exist_ok=True)
                conn = sqlite3.connect(self.target, timeout=CONNECT_TIMEOUT_SECONDS)
        except Exception as e:  # 接続先の書き間違い・休止中・ネットワークの問題など
            raise UsageStoreUnavailable(f"利用記録のデータベースにつながりません（{type(e).__name__}）") from e
        try:
            if not self._ready:
                conn.execute(_SCHEMA_POSTGRES if self.is_remote else _SCHEMA_SQLITE)
                conn.commit()
                self._ready = True
            yield conn
            conn.commit()
        except UsageStoreUnavailable:
            raise
        except Exception as e:
            raise UsageStoreUnavailable(f"利用記録のデータベースを読み書きできません（{type(e).__name__}）") from e
        finally:
            conn.close()

    @contextmanager
    def locked(self):
        """この中の確認と予約を、同時に1つだけ行う（2人が同時に上限の確認を通らないように）。

        PostgreSQL はロック（pg_advisory_xact_lock。確定すると外れる）、SQLite は書き込みの予約（BEGIN IMMEDIATE）を使う。
        """
        with self._connect() as conn:
            if self.is_remote:
                conn.execute("SELECT pg_advisory_xact_lock(%s)", (_LOCK_ID,))
            else:
                conn.execute("BEGIN IMMEDIATE")
            self._local.held = conn
            try:
                yield
            finally:
                self._local.held = None

    def _sql(self, sql: str) -> str:
        """SQLite の「?」を、PostgreSQL の「%s」に置き換える（値の埋め込み方の違い）。"""
        return sql.replace("?", "%s") if self.is_remote else sql

    def _one(self, sql: str, params: tuple):
        with self._connect() as conn:
            return conn.execute(self._sql(sql), params).fetchone()

    # ---------- 記録する・予約する・精算する ----------
    def _insert(self, user_key: str, feature: str, model: str, input_tokens: int, output_tokens: int,
                cost_usd: float, status: str, now: datetime | None) -> int:
        now = now or now_jst()
        with self._connect() as conn:
            return conn.execute(
                self._sql("INSERT INTO api_usage (created_at, month, user_key, feature, model, input_tokens,"
                          " output_tokens, cost_usd, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING id"),
                (now.isoformat(timespec="seconds"), current_month(now), user_key, feature, model,
                 input_tokens, output_tokens, cost_usd, status),
            ).fetchone()[0]

    def record(self, user_key: str, feature: str, model: str, input_tokens: int, output_tokens: int,
               cost_usd: float, status: str, now: datetime | None = None) -> None:
        self._insert(user_key, feature, model, input_tokens, output_tokens, cost_usd, status, now)

    def reserve(self, user_key: str, feature: str, model: str, estimated_cost_usd: float,
                now: datetime | None = None) -> int:
        """AIを呼ぶ前に「予約中」の行を入れ、その番号を返す。費用は多めの見込み額で数えておく。"""
        return self._insert(user_key, feature, model, 0, 0, estimated_cost_usd, RESERVED, now)

    def settle(self, reservation_id: int, input_tokens: int, output_tokens: int, cost_usd: float, status: str) -> None:
        """予約の行を、実際のトークン数・費用・結果に書き換える（精算）。"""
        with self._connect() as conn:
            conn.execute(self._sql("UPDATE api_usage SET input_tokens = ?, output_tokens = ?, cost_usd = ?, status = ?"
                                   " WHERE id = ?"), (input_tokens, output_tokens, cost_usd, status, reservation_id))

    # ---------- 数える（新しい予約も含める） ----------
    def user_calls(self, user_key: str, feature: str, month: str | None = None) -> int:
        """その月に、その利用者がその機能を使った回数（成功した呼び出しと、回答を待っている予約）。"""
        return self._one(f"SELECT COUNT(*) FROM api_usage WHERE month = ? AND user_key = ? AND feature = ? AND {_COUNTED}",
                         (month or current_month(), user_key, feature, _fresh_since()))[0]

    def feature_calls_on(self, feature: str, day: str | None = None) -> int:
        """その日（日本時間）に、その機能が使われた回数（全員の合計。成功と予約）。day は「2026-11-03」の形。"""
        day = day or now_jst().strftime("%Y-%m-%d")
        return self._one(f"SELECT COUNT(*) FROM api_usage WHERE created_at LIKE ? AND feature = ? AND {_COUNTED}",
                         (f"{day}%", feature, _fresh_since()))[0]

    def feature_cost(self, feature: str, month: str | None = None) -> float:
        """その月の、その機能の費用の合計（失敗した呼び出しと、予約の見込み額も含む）。"""
        return float(self._one(f"SELECT COALESCE(SUM(cost_usd), 0) FROM api_usage WHERE month = ? AND feature = ?"
                               f" AND {_ACTIVE}", (month or current_month(), feature, _fresh_since()))[0])

    def monthly(self, month: str | None = None) -> MonthlyUsage:
        """その月の合計。

        - 費用・トークン数：失敗した呼び出しも含めてすべて合計する（料金が発生している場合があるため）。
          回答を待っている予約は、見込み額で含める
        - 回数：成功した呼び出しと予約を数える（時間切れなど、利用者のせいではない失敗で回数を減らさないため）
        """
        month = month or current_month()
        since = _fresh_since()
        usage = MonthlyUsage(month)
        with self._connect() as conn:
            cost, input_tokens, output_tokens = conn.execute(
                self._sql("SELECT COALESCE(SUM(cost_usd), 0), COALESCE(SUM(input_tokens), 0),"
                          f" COALESCE(SUM(output_tokens), 0) FROM api_usage WHERE month = ? AND {_ACTIVE}"),
                (month, since),
            ).fetchone()
            usage.cost_usd, usage.input_tokens, usage.output_tokens = float(cost), int(input_tokens), int(output_tokens)
            for user_key, count in conn.execute(
                self._sql(f"SELECT user_key, COUNT(*) FROM api_usage WHERE month = ? AND {_COUNTED} GROUP BY user_key"),
                (month, since),
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
