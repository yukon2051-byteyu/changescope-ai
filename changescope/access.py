"""アクセスコードの確認。AI分析は、アクセスコードを知っている人だけが使える（費用の上限を守るため）。

アクセスコードは Streamlit の secrets（ローカルは .streamlit/secrets.toml、Git管理外）に
ACCESS_CODES = ["コード1", "コード2"] の形で書く。コードには書かない。
Hugging Face Spaces では secrets が環境変数で渡されるため、環境変数 ACCESS_CODES も読む
（["コード1", "コード2"] の形でも、「コード1,コード2」のカンマ区切りでもよい）。
利用記録には、アクセスコードそのものではなくハッシュ化した識別子だけを残す。
"""

from __future__ import annotations

import hmac
import json
import os

from changescope.usage_store import hash_user


def parse_codes(value) -> list[str]:
    """アクセスコードの一覧を読む。一覧（["a", "b"]）でも、文字列（'["a", "b"]' や 'a,b'）でもよい。"""
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("["):
            try:
                value = json.loads(text)
            except json.JSONDecodeError:
                value = text.strip("[]").replace('"', "").replace("'", "").split(",")
        else:
            value = text.split(",")
    return [str(c).strip() for c in value or [] if str(c).strip()]


def load_access_codes() -> list[str]:
    """secrets（Streamlit）から読み、なければ環境変数（Hugging Face Spaces）から読む。"""
    try:
        import streamlit as st

        codes = st.secrets.get("ACCESS_CODES")
        if codes:
            return parse_codes(codes)
    except Exception:  # secrets.toml がない場合など
        pass
    return parse_codes(os.environ.get("ACCESS_CODES", ""))


def check_access_code(code: str, valid_codes: list[str]) -> str | None:
    """正しいアクセスコードなら利用者の識別子（ハッシュ）を、誤りなら None を返す。"""
    code = (code or "").strip()
    if not code:
        return None
    # 文字の比較にかかる時間からコードを推測されないよう、hmac.compare_digest で比べる
    if any(hmac.compare_digest(code.encode("utf-8"), v.encode("utf-8")) for v in valid_codes):
        return hash_user(code)
    return None
