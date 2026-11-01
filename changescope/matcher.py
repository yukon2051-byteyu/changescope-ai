"""入力文から変更対象の候補要素を見つける（AIを使わない無料の処理）。

要素名と別名（aliases、「;」区切り）が入力文に含まれるかを調べる。
「勤怠管理システム」と「勤怠管理」のように、長い一致の一部にすぎない短い一致は候補から外す。
最終的な変更対象は、この候補をもとに利用者が確定する。
"""

from __future__ import annotations

import pandas as pd


def _keywords(row: pd.Series) -> list[str]:
    aliases = row.get("aliases", "")
    if not isinstance(aliases, str):  # 空欄が NaN（欠損値）になっている場合
        aliases = ""
    words = [row["name"]] + [a.strip() for a in aliases.split(";")]
    return [w for w in dict.fromkeys(words) if w]


def find_candidates(text: str, elements: pd.DataFrame) -> list[str]:
    """入力文に名前・別名が現れる要素のIDを、文中の出現順に返す。"""
    matches = []  # (開始位置, 終了位置, 要素ID)
    for _, row in elements.iterrows():
        for word in _keywords(row):
            start = text.find(word)
            while start != -1:
                matches.append((start, start + len(word), row["element_id"]))
                start = text.find(word, start + 1)

    def is_covered(m: tuple[int, int, str]) -> bool:
        # 別の要素の、より長い一致の中に完全に含まれているか
        return any(o[2] != m[2] and o[0] <= m[0] and m[1] <= o[1] and (o[1] - o[0]) > (m[1] - m[0])
                   for o in matches)

    kept = sorted((m for m in matches if not is_covered(m)), key=lambda m: m[0])
    return list(dict.fromkeys(m[2] for m in kept))
