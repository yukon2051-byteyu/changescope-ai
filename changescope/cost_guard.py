"""AIを呼び出す前の確認（費用を守る仕組み）。

呼び出す前に、入力の長さ・月の予算・月の回数・利用者ごとの回数を確かめ、超えていれば呼び出さない。
アプリ側の確認だけでは請求の上限は保証されないため、Claude Console 側でも月の上限を設定している。
"""

from __future__ import annotations

from dataclasses import dataclass

from changescope.ai_settings import AISettings
from changescope.usage_store import UsageStore


@dataclass
class Decision:
    allowed: bool
    reason: str = ""


def check(settings: AISettings, store: UsageStore, user_key: str | None, user_text: str = "") -> Decision:
    """AIを呼び出してよいかを判断する。user_text は利用者が入力した文（長さの確認に使う）。"""
    if not user_key:
        return Decision(False, "AI分析にはアクセスコードが必要です。")
    if len(user_text) > settings.max_input_chars:
        return Decision(False, f"入力が長すぎます（{len(user_text)}文字）。{settings.max_input_chars}文字以内にしてください。")

    usage = store.monthly()
    stop_at = settings.monthly_budget_usd * settings.stop_ratio
    if usage.cost_usd >= stop_at:
        return Decision(False, "今月のAI利用の予算に達したため、AI分析を停止しています。AIを使わない分析はそのまま使えます。")
    if usage.calls >= settings.monthly_call_limit:
        return Decision(False, "今月のAI分析の回数の上限に達しました。AIを使わない分析はそのまま使えます。")
    if usage.calls_by_user.get(user_key, 0) >= settings.per_user_monthly_limit:
        return Decision(False, f"今月のAI分析は、1人{settings.per_user_monthly_limit}回までです。来月またお試しください。")
    return Decision(True)
