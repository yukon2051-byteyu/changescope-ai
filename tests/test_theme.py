"""配色（テーマ）のテスト。切り替えられることと、紺と金に戻せることを確かめる。"""

from changescope import theme
from changescope.theme import THEMES, config_colors, css_variables, rewrite_config

SAMPLE_CONFIG = """# コメントはそのまま残る
[theme]
base = "light"
primaryColor = "#000000"
textColor = "#000000"

[theme.sidebar]
backgroundColor = "#000000"

[client]
toolbarMode = "minimal"
"""


def test_both_themes_define_every_color():
    for t in THEMES.values():
        for name, value in vars(t).items():
            if name not in ("label", "heading_font", "heading_font_url"):
                assert value.startswith("#") and len(value) == 7, (t.label, name, value)


def test_rewrite_config_changes_only_color_lines():
    text = rewrite_config(SAMPLE_CONFIG, THEMES["green_brass"])
    assert 'primaryColor = "#1E4A3D"' in text and 'backgroundColor = "#16302A"' in text
    assert "# コメントはそのまま残る" in text and 'toolbarMode = "minimal"' in text and 'base = "light"' in text


def test_switching_back_restores_navy_gold_exactly():
    # 深緑と真鍮にしてから紺と金に戻すと、紺と金の色に戻る（行き来しても崩れない）
    there = rewrite_config(SAMPLE_CONFIG, THEMES["green_brass"])
    back = rewrite_config(there, THEMES["navy_gold"])
    assert back == rewrite_config(SAMPLE_CONFIG, THEMES["navy_gold"])
    assert 'primaryColor = "#1F3260"' in back  # 変更前の紺と金の設定と同じ色


def test_config_file_matches_active_theme():
    # 設定ファイルの色が、いま選んでいるテーマと一致している（切り替えのコマンドを使い忘れていない）
    text = theme.CONFIG_PATH.read_text(encoding="utf-8")
    assert rewrite_config(text, theme.THEME) == text
    assert len(config_colors(theme.THEME)) == 16


def test_css_variables_follow_theme():
    css = css_variables(THEMES["green_brass"])
    assert "--cs-navy: #16302A" in css and "Shippori Mincho B1" in css
    assert "--cs-heading-font: inherit" in css_variables(THEMES["navy_gold"])  # 紺と金は本文と同じ書体
