"""配色（テーマ）。画面・図・PDF・Excel の色を、ここ1か所で決める。

2つのテーマを持ち、ACTIVE_THEME で切り替える。
- "green_brass"：深緑と真鍮（2026-11-03 に採用。落ち着いた高級感。真鍮色は細い線・選択中のタブ・小さな印だけに使う）
- "navy_gold"  ：紺と金（それまでのデザイン）

切り替えるときは、次のコマンドを1回実行する（このファイルの ACTIVE_THEME と、Streamlit の設定ファイル
.streamlit/config.toml の色を、まとめて書き換える）。実行したら、アプリを起動し直す。
    python -m changescope.theme navy_gold      # 紺と金に戻す
    python -m changescope.theme green_brass    # 深緑と真鍮にする
Git には、変更前の状態に design-navy-gold という目印（タグ）を付けてある。
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

ACTIVE_THEME = "green_brass"


@dataclass(frozen=True)
class Theme:
    label: str
    dark: str  # 主役の濃い色（帯・見出しの地・タブの帯・表の見出し）
    dark_2: str  # 濃い色のグラデーションの相手
    primary: str  # ボタン・図の箱・Excel の見出しの濃い色（濃い色より少し明るい）
    accent: str  # 差し色（細い線・選択中のタブ・小さな印）
    accent_light: str  # 濃い地の上の差し色
    ink: str  # 本文の文字
    sub: str  # 補足の文字
    line: str  # 罫線
    table_line: str  # 表の罫線（Streamlit の表）
    paper: str  # カード・表の地
    cream: str  # 注記の地
    bg: str  # ページの地
    bg_2: str  # 入力欄などの地（Streamlit の secondaryBackgroundColor）
    on_dark: str  # 濃い地の上の補足の文字
    on_dark_faint: str  # 濃い地の上の、さらに控えめな文字
    note_line: str  # 注記の枠
    sidebar_text: str  # 左のメニューの文字
    sidebar_border: str  # 左のメニューの区切り線
    link_bg: str  # Streamlit の「青」系の部品の地（お知らせなど）
    heading_font: str  # 日本語の見出しの書体（CSS の font-family。空なら本文と同じ）
    heading_font_url: str  # 見出しの書体を読み込む Google Fonts の URL（空なら読み込まない）


THEMES = {
    "green_brass": Theme(
        label="深緑と真鍮", dark="#16302A", dark_2="#234238", primary="#1E4A3D", accent="#A8874F", accent_light="#CDB07A",
        ink="#1F2622", sub="#5B655F", line="#DED7C6", table_line="#E3DCCB", paper="#FFFDF8", cream="#F7F3E8", bg="#F5F2EA", bg_2="#ECE6D8",
        on_dark="#B9C7BF", on_dark_faint="#8FA399", note_line="#E5DAC0", sidebar_text="#E3DCCB",
        sidebar_border="#2B4A40", link_bg="#E4ECE7",
        heading_font="'Shippori Mincho B1', 'Yu Mincho', serif",
        heading_font_url="https://fonts.googleapis.com/css2?family=Shippori+Mincho+B1:wght@600;700&display=swap",
    ),
    "navy_gold": Theme(
        label="紺と金", dark="#14213D", dark_2="#22365F", primary="#1F3260", accent="#B8963E", accent_light="#D9C08A",
        ink="#1B2433", sub="#5E6675", line="#DDD8CC", table_line="#E4E0D5", paper="#FFFFFF", cream="#FBF8EF", bg="#F8F7F3", bg_2="#EFECE4",
        on_dark="#C9CFDB", on_dark_faint="#9AA4B8", note_line="#E9DFC4", sidebar_text="#E9E4D6",
        sidebar_border="#2C406B", link_bg="#E8ECF4",
        heading_font="", heading_font_url="",
    ),
}
THEME = THEMES[ACTIVE_THEME]


def rgb(hex_color: str) -> tuple[int, int, int]:
    """#RRGGBB を (R, G, B) にする（PDF で使う）。"""
    value = hex_color.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def bare(hex_color: str) -> str:
    """#RRGGBB を RRGGBB にする（Excel で使う）。"""
    return hex_color.lstrip("#").upper()


def css_variables(theme: Theme = THEME) -> str:
    """画面の CSS で使う色の名前（--cs-...）の定義。"""
    return (
        ":root {\n"
        f"  --cs-navy: {theme.dark}; --cs-navy-2: {theme.dark_2}; --cs-gold: {theme.accent};"
        f" --cs-gold-light: {theme.accent_light};\n"
        f"  --cs-ink: {theme.ink}; --cs-sub: {theme.sub}; --cs-line: {theme.line}; --cs-paper: {theme.paper};"
        f" --cs-cream: {theme.cream}; --cs-bg: {theme.bg};\n"
        f"  --cs-on-dark: {theme.on_dark}; --cs-on-dark-faint: {theme.on_dark_faint}; --cs-note-line: {theme.note_line};\n"
        f"  --cs-heading-font: {theme.heading_font or 'inherit'};\n"
        "}"
    )


# ---------- テーマの切り替え（python -m changescope.theme <名前>） ----------
CONFIG_PATH = Path(__file__).resolve().parent.parent / ".streamlit" / "config.toml"


def config_colors(theme: Theme) -> dict[tuple[str, str], str]:
    """Streamlit の設定ファイルに書く色。(節, 項目) → 色。"""
    return {
        ("theme", "primaryColor"): theme.primary, ("theme", "textColor"): theme.ink,
        ("theme", "backgroundColor"): theme.bg, ("theme", "secondaryBackgroundColor"): theme.bg_2,
        ("theme", "linkColor"): theme.primary, ("theme", "borderColor"): theme.line,
        ("theme", "dataframeBorderColor"): theme.table_line, ("theme", "dataframeHeaderBackgroundColor"): theme.bg_2,
        ("theme", "blueColor"): theme.primary, ("theme", "blueBackgroundColor"): theme.link_bg,
        ("theme", "blueTextColor"): theme.dark,
        ("theme.sidebar", "backgroundColor"): theme.dark, ("theme.sidebar", "secondaryBackgroundColor"): theme.dark_2,
        ("theme.sidebar", "textColor"): theme.sidebar_text, ("theme.sidebar", "primaryColor"): theme.accent_light,
        ("theme.sidebar", "borderColor"): theme.sidebar_border,
    }


def rewrite_config(text: str, theme: Theme) -> str:
    """設定ファイルの文章のうち、色の行だけを書き換える（ほかの行やコメントはそのまま）。"""
    section = ""
    lines = []
    colors = config_colors(theme)
    for line in text.splitlines():
        header = re.match(r"\s*\[([^\]]+)\]", line)
        if header:
            section = header.group(1).strip()
        key = re.match(r"\s*(\w+)\s*=", line)
        if key and (section, key.group(1)) in colors:
            line = f'{key.group(1)} = "{colors[(section, key.group(1))]}"'
        lines.append(line)
    return "\n".join(lines) + "\n"


def switch(name: str) -> None:
    if name not in THEMES:
        raise SystemExit(f"テーマの名前が違います。次のどれかを指定してください：{', '.join(THEMES)}")
    CONFIG_PATH.write_text(rewrite_config(CONFIG_PATH.read_text(encoding="utf-8"), THEMES[name]), encoding="utf-8")
    source = Path(__file__)
    text = source.read_text(encoding="utf-8")
    source.write_text(re.sub(r'^ACTIVE_THEME = ".*"$', f'ACTIVE_THEME = "{name}"', text, count=1, flags=re.M),
                      encoding="utf-8")
    print(f"テーマを「{THEMES[name].label}」に切り替えました。アプリを起動し直してください。")


if __name__ == "__main__":
    switch(sys.argv[1] if len(sys.argv) > 1 else "")
