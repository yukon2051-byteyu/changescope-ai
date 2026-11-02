"""アクセスコードの確認。AI分析は、アクセスコードを知っている人だけが使える（費用の上限を守るため）。

アクセスコードは Streamlit の secrets（ローカルは .streamlit/secrets.toml、Git管理外）に
ACCESS_CODES = ["コード1", "コード2"] の形で書く。コードには書かない。
利用記録には、アクセスコードそのものではなくハッシュ化した識別子だけを残す。
"""

from __future__ import annotations

import hmac

from changescope.usage_store import hash_user


def load_access_codes() -> list[str]:
    try:
        import streamlit as st

        codes = st.secrets.get("ACCESS_CODES", [])
    except Exception:  # secrets.toml がない場合など
        return []
    return [str(c) for c in codes if str(c).strip()]


def check_access_code(code: str, valid_codes: list[str]) -> str | None:
    """正しいアクセスコードなら利用者の識別子（ハッシュ）を、誤りなら None を返す。"""
    code = (code or "").strip()
    if not code:
        return None
    # 文字の比較にかかる時間からコードを推測されないよう、hmac.compare_digest で比べる
    if any(hmac.compare_digest(code.encode("utf-8"), v.encode("utf-8")) for v in valid_codes):
        return hash_user(code)
    return None
