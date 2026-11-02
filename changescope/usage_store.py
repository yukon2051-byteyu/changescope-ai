"""AI呼び出しの利用記録（SQLite）。費用と回数の監視に使う。

記録するのは日時・利用者（ハッシュ化した識別子）・機能・モデル・トークン数・費用・成否だけで、
入力文や分析内容は保存しない（利用者間でデータが混ざらないようにするため）。
公開版（Streamlit Community Cloud）ではファイルが消えるため、Phase 4 で外部のデータベースに移す。
"""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS api_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    month TEXT NOT NULL,
    user_key TEXT NOT NULL,
    feature TEXT NOT NULL,
    model TEXT NOT NULL,
    input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    cost_usd REAL NOT NULL,
    status TEXT NOT NULL
)
"""


def hash_user(access_code: str) -> str:
    """アクセスコードをそのまま保存しないよう、ハッシュ化した識別子にする。"""
    return hashlib.sha256(access_code.encode("utf-8")).hexdigest()[:16]


def current_month(now: datetime | None = None) -> str:
    return (now or datetime.now()).strftime("%Y-%m")


@dataclass
class MonthlyUsage:
    month: str
    calls: int = 0
    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    calls_by_user: dict[str, int] = field(default_factory=dict)


class UsageStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def record(self, user_key: str, feature: str, model: str, input_tokens: int, output_tokens: int,
               cost_usd: float, status: str, now: datetime | None = None) -> None:
        now = now or datetime.now()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO api_usage (created_at, month, user_key, feature, model, input_tokens, output_tokens,"
                " cost_usd, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (now.isoformat(timespec="seconds"), current_month(now), user_key, feature, model,
                 input_tokens, output_tokens, cost_usd, status),
            )

    def monthly(self, month: str | None = None) -> MonthlyUsage:
        """その月の合計。

        - 費用・トークン数：失敗した呼び出しも含めてすべて合計する（料金が発生している場合があるため）
        - 回数：成功した呼び出しだけを数える（時間切れなど、利用者のせいではない失敗で回数を減らさないため）
        """
        month = month or current_month()
        usage = MonthlyUsage(month)
        with self._connect() as conn:
            usage.cost_usd, usage.input_tokens, usage.output_tokens = conn.execute(
                "SELECT COALESCE(SUM(cost_usd), 0), COALESCE(SUM(input_tokens), 0), COALESCE(SUM(output_tokens), 0)"
                " FROM api_usage WHERE month = ?", (month,),
            ).fetchone()
            for user_key, count in conn.execute(
                "SELECT user_key, COUNT(*) FROM api_usage WHERE month = ? AND status = 'ok' GROUP BY user_key",
                (month,),
            ):
                usage.calls_by_user[user_key] = count
            usage.calls = sum(usage.calls_by_user.values())
        return usage
