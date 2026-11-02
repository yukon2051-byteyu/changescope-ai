"""画面の動作テスト。StreamlitのAppTestでブラウザなしに画面を動かし、エラーが出ないことを確認する。"""

import re
from pathlib import Path

from streamlit.testing.v1 import AppTest

from changescope.datasets import load_sample

ROOT = Path(__file__).resolve().parent.parent


def run_page(name: str, dataset=None) -> AppTest:
    """本番と同じく app.py（ページ一覧の定義）から起動し、指定のページに切り替える。"""
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30)
    if dataset is not None:
        at.session_state["dataset"] = dataset
    at.run()
    return at.switch_page(f"pages/{name}").run()


def test_home_page():
    at = run_page("home.py")
    assert not at.exception
    assert any("ChangeScope AI" in m.value for m in at.markdown)


def test_home_sample_button_opens_analysis_with_sample():
    # ホームの「サンプルで試す」1回で、サンプルが読み込まれ分析画面に移る
    at = run_page("home.py")
    next(b for b in at.button if b.label == "サンプルで試す").click().run()
    assert not at.exception
    assert at.session_state["dataset"].source == "sample"
    assert any("影響分析" == t.value for t in at.title)


def test_guide_page():
    at = run_page("guide.py")
    assert not at.exception
    labels = [t.label for t in at.tabs]
    assert labels[0] == "はじめに"
    assert labels[1] == "サンプルで試す"
    assert labels[-1] == "用語について"
    assert all("用語集" not in m.value for m in at.markdown)


def test_data_page_loads_sample():
    at = run_page("data.py")
    assert not at.exception
    at.button[0].click().run()  # 「サンプルデータを読み込む」
    assert not at.exception
    assert at.session_state["dataset"].source == "sample"
    assert any("要素 57 件" in s.value for s in at.success)


def test_data_page_own_data_shows_template_steps():
    at = run_page("data.py")
    at.radio[0].set_value("own").run()
    assert not at.exception
    assert any("① テンプレートをダウンロード" in m.value for m in at.markdown)


def test_analysis_page_without_data_shows_guide():
    at = run_page("analysis.py")
    assert not at.exception
    assert "データが読み込まれていません" in at.info[0].value


def test_analysis_page_scenario_a_flow():
    at = run_page("analysis.py", load_sample())
    assert not at.exception

    # 入力例ボタン（シナリオA）→ 入力欄に文章が入り、変更対象の候補が自動で選ばれる
    at.button(key="scenario_A").click().run()
    assert "勤怠管理システム" in at.text_area[0].value
    assert at.multiselect[0].value == ["SYS-ATT"]

    # 「影響を分析する」→ 結果が表示される
    next(b for b in at.button if b.label == "影響を分析する").click().run()
    assert not at.exception
    metrics = {m.label: m.value for m in at.metric}
    assert metrics["直接影響"] == "7 件"
    assert metrics["間接影響"] == "14 件"
    assert metrics["影響を受ける関係者"] == "7 件"
    assert metrics["見落としやすい"] == "5 件"
    assert at.slider[0].max == 8  # 8段までたどれる
    assert any("影響範囲は「大」です" in m.value and "まずやること" in m.value for m in at.markdown)
    assert any(t.label.startswith("見落としチェック") for t in at.tabs)
    assert any("データの移行・引き継ぎ" in m.value for m in at.markdown)
    assert any("次にやること" in m.value for m in at.markdown)
    assert any("変更対象の責任部門と、変更の方針を共有する" in m.value for m in at.markdown)
    # 直接影響の表（影響の大きい順）。長い文章も切れずに表示されるHTMLの表で表示している
    tables = [m.value for m in at.markdown if 'class="cs-table"' in m.value and "<th>注目</th>" in m.value]
    scores = [int(s) for s in re.findall(r'<td class="cs-num-col">(\d+)</td>', tables[0])]
    assert len(scores) == 7
    assert scores == sorted(scores, reverse=True)
    assert not at.dataframe  # 文章が切れる st.dataframe は使わない


def test_analysis_page_with_custom_type():
    # 利用者が追加した種類（設備）を含むデータでも、分析画面が動く
    import io

    from openpyxl import load_workbook

    from changescope.datasets import load_from_excel
    from changescope.excel_template import CHOICES_SHEET, DEPENDENCIES_SHEET, ELEMENTS_SHEET, build_template

    wb = load_workbook(io.BytesIO(build_template()))
    wb[CHOICES_SHEET]["A10"] = "設備"
    wb[ELEMENTS_SHEET].append(["製造ライン1", "設備", "", "経理部"])
    wb[DEPENDENCIES_SHEET].append(["経費精算システム", "製造ライン1", "利用する", "一方向", "設備台帳", "確認済"])
    buffer = io.BytesIO()
    wb.save(buffer)
    dataset = load_from_excel(buffer.getvalue()).dataset

    at = run_page("analysis.py", dataset)
    system_id = dataset.elements.set_index("name").loc["経費精算システム", "element_id"]
    at.multiselect[0].set_value([system_id]).run()
    next(b for b in at.button if b.label == "影響を分析する").click().run()
    assert not at.exception
    assert any("製造ライン1" in m.value and "設備" in m.value for m in at.markdown)


def test_analysis_page_unknown_text_warns():
    at = run_page("analysis.py", load_sample())
    at.text_area[0].input("新しいチャットツールを入れたい").run()
    assert not at.exception
    assert any("見つけられませんでした" in w.value for w in at.warning)
