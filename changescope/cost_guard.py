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


def check(settings: AISettings, store: UsageStore, user_key: str | None, user_text: str = "",
          feature: str = "", max_chars: int | None = None, feature_budget_usd: float | None = None) -> Decision:
    """AIを呼び出してよいかを判断する。

    user_text : 利用者が入力した文（長さの確認に使う）
    feature   : 機能名。1人あたりの回数は機能ごとに数える（月の回数の上限は全機能の合計）
    max_chars : この機能で入力できる最大文字数（省略すると、変更内容の上限 max_input_chars）
    feature_budget_usd : この機能だけの月の予算（アクセスコードなしで使える機能に使う）。全体の予算とは別に確かめる。
                         指定したときは、1日の回数の上限（全員の合計 free_daily_limit）も確かめる。
                         アクセスコードなしでは1人を確実に区別できないため、1人に使い切られても翌日には他の人が使えるようにする
    """
    if not user_key:
        return Decision(False, "AI分析にはアクセスコードが必要です。")
    limit = max_chars or settings.max_input_chars
    if len(user_text) > limit:
        return Decision(False, f"入力が長すぎます（{len(user_text)}文字）。{limit}文字以内にしてください。")

    usage = store.monthly()
    stop_at = settings.monthly_budget_usd * settings.stop_ratio
    if usage.cost_usd >= stop_at:
        return Decision(False, "今月のAI利用の予算に達したため、AI分析を停止しています。AIを使わない分析はそのまま使えます。")
    if feature_budget_usd is not None and store.feature_cost(feature) >= feature_budget_usd * settings.stop_ratio:
        return Decision(False, f"今月の「{feature}」の無料分の予算に達したため、停止しています。"
                               "来月またお試しください（サンプルは引き続き見られます）。")
    if feature_budget_usd is not None and store.feature_calls_on(feature) >= settings.free_daily_limit:
        return Decision(False, f"今日の「{feature}」は、全員で{settings.free_daily_limit}回の上限に達しました。"
                               "明日またお試しください（サンプルは引き続き見られます）。")
    if usage.calls >= settings.monthly_call_limit:
        return Decision(False, "今月のAI分析の回数の上限に達しました。AIを使わない分析はそのまま使えます。")
    if store.user_calls(user_key, feature) >= settings.per_user_monthly_limit:
        name = f"「{feature}」" if feature else "AI分析"
        return Decision(False, f"今月の{name}は、1人{settings.per_user_monthly_limit}回までです。来月またお試しください。")
    return Decision(True)
