"""配色（テーマ）。画面・図・PDF・Excel の色を、ここ1か所で決める。

3つのテーマを持ち、ACTIVE_THEME で切り替える。
- "white_green"：白とトラッドグリーン（2026-11-03 に採用。三井住友銀行のサイトを参考に、白い地に深緑、若草色の細い線。
                 帯・結論・タブは淡い色の面にして、明るく、やわらかく。角は丸く）
- "green_brass"：深緑と真鍮（明朝の見出し。落ち着いた高級感。暗く固いという評価で、白とトラッドグリーンに変更）
- "navy_gold"  ：紺と金（最初のデザイン）

切り替えるときは、次のコマンドを1回実行する（このファイルの ACTIVE_THEME と、Streamlit の設定ファイル
.streamlit/config.toml の色を、まとめて書き換える）。実行したら、アプリを起動し直す。
    python -m changescope.theme white_green    # 白とトラッドグリーン
    python -m changescope.theme green_brass    # 深緑と真鍮
    python -m changescope.theme navy_gold      # 紺と金
Git には、変更前の状態に design-navy-gold という目印（タグ）を付けてある。
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

ACTIVE_THEME = "white_green"


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
    sidebar_bg: str = ""  # 左のメニューの地（空なら濃い色）
    sidebar_bg_2: str = ""  # 左のメニューの、選んでいる項目などの地（空なら濃い色の相手）
    sidebar_primary: str = ""  # 左のメニューの強調の色（空なら濃い地の上の差し色）
    base_radius: str = "small"  # Streamlit の部品（入力欄など）の角の丸み
    button_radius: str = "small"  # Streamlit のボタンの角の丸み（"full" で丸い形）
    # 画面の部品ごとの見た目（帯・結論・タブ・表の見出し・流れの図・角の丸み）。
    # 指定しない部品は、濃い色の面に白い文字（紺と金・深緑と真鍮の形）になる。指定できる名前は PART_DEFAULTS を参照
    parts: dict[str, str] = field(default_factory=dict)


# 画面の部品の見た目の標準（濃い色の面に白い文字）。テーマの parts で、部品ごとに置き換えられる
PART_DEFAULTS = {
    "accent-text": "var(--cs-gold)",  # 差し色の文字（小見出しの英字・番号・矢印など）
    "badge-warn-ink": "#fff",  # 差し色の地の印（「AIの推測」など）の文字
    "radius": "4px", "radius-lg": "6px", "pill": "3px", "shadow": "none",  # 角の丸み・影
    "hero-bg": "linear-gradient(135deg, var(--cs-navy) 0%, var(--cs-navy-2) 100%)", "hero-ink": "#fff",
    "hero-sub": "var(--cs-on-dark)", "hero-eyebrow": "var(--cs-gold-light)", "hero-rule": "var(--cs-gold)",
    # 上の帯の右の円の飾り（線・内側の輪・外側の輪）
    "hero-ring-line": "color-mix(in srgb, var(--cs-gold-light) 35%, transparent)",
    "hero-ring-1": "color-mix(in srgb, var(--cs-gold-light) 6%, transparent)",
    "hero-ring-2": "color-mix(in srgb, var(--cs-gold-light) 4%, transparent)",
    "concl-bg": "linear-gradient(135deg, var(--cs-navy) 0%, var(--cs-navy-2) 100%)", "concl-ink": "#fff",
    "concl-sub": "var(--cs-on-dark)", "concl-faint": "var(--cs-on-dark-faint)", "concl-strong": "var(--cs-gold-light)",
    "concl-first": "rgba(255,255,255,.08)", "concl-border": "0 solid transparent",
    "level-big-bg": "var(--cs-gold)", "level-big-ink": "var(--cs-navy)", "level-mid-bg": "var(--cs-gold-light)",
    "level-mid-ink": "var(--cs-navy)", "level-small-bg": "#fff", "level-small-ink": "var(--cs-navy)",
    "level-small-border": "0 solid transparent",
    "tabs-bg": "var(--cs-navy)", "tab-bg": "rgba(255,255,255,.06)", "tab-ink": "var(--cs-on-dark)",
    "tab-hover-bg": "rgba(255,255,255,.16)", "tab-hover-ink": "#fff", "tab-on-bg": "var(--cs-gold)",
    "tab-on-ink": "var(--cs-navy)",
    "th-bg": "var(--cs-navy)", "th-ink": "#fff",
    "flow-bg": "var(--cs-navy)", "flow-ink": "#fff", "flow-strong": "var(--cs-gold-light)", "flow-sub": "var(--cs-on-dark)",
}

# 図（図で入力する・文章から作るの図のたたき台）の色。CSS ではなく Python で図の部品に渡す。
# 指定しないテーマは、線と真ん中の箱に差し色、左の帯に濃い色を使う（diagram_color を参照）
DIAGRAM_PARTS = ("diagram-accent", "diagram-center-bg", "pick-bg", "pick-ink", "pick-sub", "pick-strong", "pick-line")

THEMES = {
    "white_green": Theme(
        label="白とトラッドグリーン", dark="#0E4F3A", dark_2="#13644A", primary="#0E4F3A", accent="#B9CF1C",
        accent_light="#D8E47A", ink="#18211F", sub="#5E6B66", line="#DCE5E1", table_line="#E3EAE6", paper="#FFFFFF",
        cream="#F6F9EC", bg="#FFFFFF", bg_2="#F1F5F3", on_dark="#CFE0D8", on_dark_faint="#9DB5AA", note_line="#E2EBC9",
        sidebar_text="#2F3B37", sidebar_border="#DCE5E1", link_bg="#E8F1EC", heading_font="", heading_font_url="",
        sidebar_bg="#F4F7F5", sidebar_bg_2="#E6EEEA", sidebar_primary="#0E4F3A",
        base_radius="medium", button_radius="full",
        parts={
            # 若草色（目立つ色）は細い線だけに使い、文字は深緑にする
            "accent-text": "#0E4F3A", "badge-warn-ink": "#18211F", "radius": "12px", "radius-lg": "14px", "pill": "999px",
            "shadow": "0 2px 6px rgba(15,60,45,.08)",
            "hero-bg": "#EEF4DA", "hero-ink": "#18211F", "hero-sub": "#4E5B56", "hero-eyebrow": "#0E4F3A",
            "hero-rule": "#B9CF1C",
            # 円の飾り：淡い黄緑の地に溶けないよう、落ち着いた緑で輪を重ねる
            "hero-ring-line": "rgba(111,154,46,.55)", "hero-ring-1": "rgba(111,154,46,.12)",
            "hero-ring-2": "rgba(111,154,46,.07)",
            "concl-bg": "#FFFFFF", "concl-ink": "#18211F", "concl-sub": "#4E5B56", "concl-faint": "#7A8781",
            "concl-strong": "#0E4F3A", "concl-first": "#F4F8EC", "concl-border": "1px solid #DCE5E1",
            "level-big-bg": "#0E4F3A", "level-big-ink": "#FFFFFF", "level-mid-bg": "#D8E47A", "level-mid-ink": "#18211F",
            "level-small-bg": "#FFFFFF", "level-small-ink": "#0E4F3A", "level-small-border": "1px solid #DCE5E1",
            "tabs-bg": "#EEF3F0", "tab-bg": "transparent", "tab-ink": "#3E4A46", "tab-hover-bg": "#E0EAE4",
            "tab-hover-ink": "#0E4F3A", "tab-on-bg": "#0E4F3A", "tab-on-ink": "#FFFFFF",
            "th-bg": "#EEF3F0", "th-ink": "#0E4F3A",
            "flow-bg": "#F1F6F3", "flow-ink": "#18211F", "flow-strong": "#0E4F3A", "flow-sub": "#4E5B56",
            # 図：若草色は線や箱に使うと強すぎるため、線は落ち着いた緑、真ん中の箱は淡い黄緑にする
            "diagram-accent": "#6F9A2E", "diagram-center-bg": "#EEF4DA",
            "pick-bg": "#F1F6F3", "pick-ink": "#0E4F3A", "pick-sub": "#4E5B56", "pick-strong": "#0E4F3A",
            "pick-line": "#DCE5E1",
        },
    ),
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


def diagram_color(name: str, theme: Theme = THEME) -> str:
    """図の色。テーマで指定がなければ、紺と金・深緑と真鍮の形（線と真ん中の箱は差し色、左の帯は濃い色）にする。"""
    defaults = {"diagram-accent": theme.accent, "diagram-center-bg": theme.accent, "pick-bg": theme.primary,
                "pick-ink": "#FFFFFF", "pick-sub": theme.on_dark, "pick-strong": theme.accent,
                "pick-line": "rgba(255,255,255,.2)"}
    return theme.parts.get(name, defaults[name])


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
        + "".join(f"  --cs-{name}: {value};\n" for name, value in {**PART_DEFAULTS, **theme.parts}.items()
                  if name in PART_DEFAULTS)
        + "}"
    )


# ---------- テーマの切り替え（python -m changescope.theme <名前>） ----------
CONFIG_PATH = Path(__file__).resolve().parent.parent / ".streamlit" / "config.toml"


def config_colors(theme: Theme) -> dict[tuple[str, str], str]:
    """Streamlit の設定ファイルに書く値（色と角の丸み）。(節, 項目) → 値。"""
    return {
        ("theme", "baseRadius"): theme.base_radius, ("theme", "buttonRadius"): theme.button_radius,
        ("theme", "primaryColor"): theme.primary, ("theme", "textColor"): theme.ink,
        ("theme", "backgroundColor"): theme.bg, ("theme", "secondaryBackgroundColor"): theme.bg_2,
        ("theme", "linkColor"): theme.primary, ("theme", "borderColor"): theme.line,
        ("theme", "dataframeBorderColor"): theme.table_line, ("theme", "dataframeHeaderBackgroundColor"): theme.bg_2,
        ("theme", "blueColor"): theme.primary, ("theme", "blueBackgroundColor"): theme.link_bg,
        ("theme", "blueTextColor"): theme.dark,
        ("theme.sidebar", "backgroundColor"): theme.sidebar_bg or theme.dark,
        ("theme.sidebar", "secondaryBackgroundColor"): theme.sidebar_bg_2 or theme.dark_2,
        ("theme.sidebar", "textColor"): theme.sidebar_text,
        ("theme.sidebar", "primaryColor"): theme.sidebar_primary or theme.accent_light,
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
