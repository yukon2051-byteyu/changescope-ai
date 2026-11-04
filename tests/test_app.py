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
    next(b for b in at.button if b.label == "サンプルデータを読み込む").click().run()
    assert not at.exception
    assert at.session_state["dataset"].source == "sample"
    assert any("要素 57 件" in s.value for s in at.success)
    # 押したボタンのすぐ下に、完了のお知らせと「影響分析へ進む」が出る
    assert any("読み込みが完了しました" in s.value for s in at.success)
    next(b for b in at.button if b.key == "go_analysis_sample").click().run()
    assert not at.exception
    assert any(t.value == "影響分析" for t in at.title)


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
    assert metrics["関係者"] == "7 件"
    assert metrics["見落とし注意"] == "5 件"
    assert metrics["要確認"] == "6 件"
    # 要確認（影響6件）と、確かめるつながり（4本）の差を説明し、一覧のタブを用意している
    assert any("要確認 6件と、確かめるつながり 4本の関係" in m.value for m in at.markdown)
    assert any(t.label == "要確認のつながり（4本）" for t in at.tabs)
    assert any("確かめるつながり" in m.value and "社内認証基盤" in m.value for m in at.markdown)
    assert at.slider[0].max == 8  # 8段までたどれる
    assert any("影響の広さは「大」です" in m.value and "まずやること" in m.value for m in at.markdown)
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
    wb[DEPENDENCIES_SHEET].append(["経費精算システム", "製造ライン1", "利用される", "一方向", "設備台帳", "確認済"])
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


def analyze_scenario_a(secrets=None) -> AppTest:
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30)
    at.session_state["dataset"] = load_sample()
    for key, value in (secrets or {}).items():
        at.secrets[key] = value
    at.run()
    at = at.switch_page("pages/analysis.py").run()
    at.button(key="scenario_A").click().run()
    next(b for b in at.button if b.label == "影響を分析する").click().run()
    return at


def test_analysis_page_shows_ai_sample_without_cost():
    # 入力例で分析すると、事前に生成したAIのサンプルを料金なしで見られる。サンプルであることを明示する
    at = analyze_scenario_a()
    next(b for b in at.button if b.label == "AIによる分析のサンプルを見る").click().run()
    assert not at.exception
    assert any("AIによる分析のサンプル" in m.value and "いま実行したAI分析ではありません" in m.value for m in at.markdown)
    cards = [m.value for m in at.markdown if 'class="cs-ai-card' in m.value]
    assert cards and "確認先：" in cards[0] and "登録済みのつながり" in cards[0]
    assert any(t.label.startswith("未登録の影響の推測") for t in at.tabs)


def test_analysis_page_wrong_access_code_does_not_call_ai():
    at = analyze_scenario_a({"ACCESS_CODES": ["right-code"]})
    at.text_input(key="access_code").set_value("wrong-code").run()
    next(b for b in at.button if b.label == "AIで確認漏れを調べる").click().run()
    assert not at.exception
    assert any("アクセスコードが正しくありません" in e.value for e in at.error)
    assert at.session_state["oversight"] is None


# ---------- 図で入力する ----------

def test_diagram_page_tutorial_creates_data_for_analysis():
    at = run_page("diagram.py")
    assert not at.exception
    next(b for b in at.button if b.label == "新しく作る").click().run()
    # つながりがないうちは、保存ボタンは押せない
    assert next(b for b in at.button if b.label == "Excelに保存する").disabled
    at.text_input[0].set_value("勤怠管理システム")
    next(b for b in at.button if b.label == "登録して次へ").click().run()
    at.text_input[0].set_value("勤怠実績データ")
    at.selectbox[0].set_value("data")
    next(b for b in at.button if b.label == "登録して次へ").click().run()
    next(b for b in at.button if b.label.startswith("うまく線を引けない")).click().run()
    assert at.radio[0].value == "provides_data"  # システム → データは自動で「データを提供する」
    assert any("「勤怠管理システム」は、「勤怠実績データ」を提供する" in i.value for i in at.info)
    next(b for b in at.button if b.label == "関係を設定する").click().run()
    assert not at.exception
    dataset = at.session_state["dataset"]
    assert dataset.source == "diagram" and len(dataset.dependencies) == 1
    assert dataset.dependencies.iloc[0]["evidence"] == "未記入（図で入力）"  # 根拠を書かなかったとき
    # つながりができると、Excelに保存できる
    assert [b.label for b in at.get("download_button")] == ["Excelに保存する"]
    next(b for b in at.button if b.label == "続けて作る").click().run()
    assert not at.exception
    assert any("やってみましょう" in i.value for i in at.info)

    # 作ったデータで、そのまま影響分析ができる
    at.switch_page("pages/analysis.py").run()
    at.multiselect[0].set_value([dataset.elements.iloc[0]["element_id"]]).run()
    next(b for b in at.button if b.label == "影響を分析する").click().run()
    assert not at.exception
    assert {m.label: m.value for m in at.metric}["直接影響"] == "1 件"


def test_diagram_page_opens_sample_and_follows_data_change():
    at = run_page("diagram.py", load_sample())
    next(b for b in at.button if b.label == "図で開く").click().run()
    assert not at.exception
    assert any("見る要素を切り替える" in m.value for m in at.markdown)
    assert any(t.value == "図で入力する" for t in at.title)
    # 検索で選ぶと、その要素が真ん中になる
    at.selectbox(key="dg_search").set_value("SYS-ATT").run()
    assert not at.exception and at.session_state["dg_center"] == "SYS-ATT"
    # 「データ管理」で別のデータを読み込んだら、図での編集は最初からやり直す
    at.session_state["dataset"] = load_sample()
    at.run()
    assert any("入れ替わった" in i.value for i in at.info)


def test_diagram_add_with_defaults_and_undo():
    # 相手の名前だけで追加でき（向き・確認状態・根拠は折りたたみ。未確認・未記入で登録）、直後に取り消せる（レビュー C05）
    at = run_page("diagram.py", load_sample())
    next(b for b in at.button if b.label == "図で開く").click().run()
    at.selectbox(key="dg_search").set_value("SYS-ATT").run()
    n_links, n_elements = len(at.session_state["dg_links"]), len(at.session_state["dg_elements"])
    next(b for b in at.button if b.label == "＋ 影響先を追加").click().run()
    assert any(e.label.startswith("詳細（向き・確認状態・根拠）") for e in at.expander)
    next(t for t in at.text_area if t.label.startswith("新しい要素の名前")).set_value("テスト用の新しい帳票")
    next(b for b in at.button if b.label == "追加").click().run()
    assert not at.exception
    added = at.session_state["dg_links"][-1]
    assert (added["status"], added["evidence"]) == ("unconfirmed", "未記入（図で入力）")
    assert any(s.value.startswith("追加しました：") for s in at.success)
    next(b for b in at.button if b.label == "取り消す").click().run()
    assert not at.exception
    assert len(at.session_state["dg_links"]) == n_links and len(at.session_state["dg_elements"]) == n_elements
    assert not [b for b in at.button if b.label == "取り消す"]


# ---------- 文章・資料から作る ----------

def test_extract_page_sample_candidates_open_in_diagram():
    at = run_page("extract.py", load_sample())
    assert not at.exception
    at.radio(key="ex_mode").set_value("document").run()
    next(b for b in at.button if b.label == "サンプルの資料で試す（料金なし）").click().run()
    assert not at.exception
    assert "勤怠管理システム" in at.text_area(key="ex_document").value  # サンプルの資料が入る
    assert any("AIによる候補のサンプル" in m.value for m in at.markdown)
    assert any(t.label.startswith("分からないこと") for t in at.tabs)
    before = len(at.session_state["dataset"].dependencies)
    next(b for b in at.button if b.label == "登録して図で直す").click().run()
    assert not at.exception
    after = at.session_state["dataset"]
    assert after.source == "diagram" and len(after.dependencies) > before
    added = after.dependencies[after.dependencies["evidence"].str.startswith("資料から抽出")]
    assert len(added) == len(after.dependencies) - before and set(added["status"]) == {"assumed"}  # AIの候補は「推定」
    # 「図で入力する」が、登録した要素を真ん中にして開く
    assert any(t.value == "図で入力する" for t in at.title)
    center = at.session_state["dg_center"]
    assert after.graph.nodes[center]["name"] == "打刻用ICカードリーダー"


def test_extract_page_text_mode_needs_no_access_code():
    # 文章で説明する：アクセスコードの入力欄がなく、残りの回数が表示される（AIは呼ばない）
    at = run_page("extract.py")
    assert not at.exception
    assert at.radio(key="ex_mode").value == "text"
    next(b for b in at.button if b.label == "例文を入れる").click().run()
    assert "CRM" in at.text_area(key="ex_text").value
    assert not [t for t in at.text_input if t.key == "ex_access_code"]
    assert any("あと 3 回使えます" in c.value for c in at.caption)
    assert not next(b for b in at.button if b.label == "AIで図のたたき台を作る").disabled


def test_extract_page_wrong_access_code_does_not_call_ai():
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30)
    at.secrets["ACCESS_CODES"] = ["right-code"]
    at.run()
    at = at.switch_page("pages/extract.py").run()
    at.radio(key="ex_mode").set_value("document").run()
    at.text_area(key="ex_document").set_value("勤怠管理システムは勤怠実績データを出力する。").run()
    at.text_input(key="ex_access_code").set_value("wrong-code").run()
    next(b for b in at.button if b.label == "AIで候補を作る").click().run()
    assert not at.exception
    assert any("アクセスコードが正しくありません" in e.value for e in at.error)
    assert "ex_result" not in at.session_state


# ---------- 変更案を比べる ----------

def test_compare_page_sample_pair():
    at = run_page("compare.py", load_sample())
    assert not at.exception
    at.button(key="cp_pair_A").click().run()  # 入力例：勤怠管理の見直し
    assert at.multiselect(key="cp_a_targets").value == ["SYS-ATT"]
    assert at.multiselect(key="cp_b_targets").value == ["PRC-ATT"]
    next(b for b in at.button if b.label == "比べる").click().run()
    assert not at.exception
    tables = [m.value for m in at.markdown if 'class="cs-table"' in m.value]
    assert any("A案の方が17件多い" in t for t in tables)
    assert any("要見積もり" in t for t in tables)  # 費用・期間は入力がなければ数字を作らない
    assert any("社内認証基盤" in t for t in tables)  # システムを入れ替える案だけにある要確認のつながり


def test_compare_page_needs_targets_for_both():
    at = run_page("compare.py", load_sample())
    at.text_area(key="cp_a_text").set_value("勤怠管理システムを入れ替える").run()
    assert next(b for b in at.button if b.label == "比べる").disabled  # B案の変更対象がまだない
    at.text_area(key="cp_b_text").set_value("経費精算業務を見直す").run()
    assert not next(b for b in at.button if b.label == "比べる").disabled


def test_analysis_and_compare_pages_offer_pdf():
    at = analyze_scenario_a()
    assert any(b.label == "PDFでダウンロード" for b in at.get("download_button"))
    at = run_page("compare.py", load_sample())
    at.button(key="cp_pair_A").click().run()
    next(b for b in at.button if b.label == "比べる").click().run()
    assert not at.exception
    assert any(b.label == "比較結果をPDFでダウンロード" for b in at.get("download_button"))


def test_guide_try_sample_button_opens_analysis():
    at = run_page("guide.py")
    at.button(key="guide_try_sample").click().run()
    assert not at.exception
    assert at.session_state["dataset"].source == "sample"
    assert any(t.value == "影響分析" for t in at.title)


def test_evidence_tab_shows_other_routes():
    # 要素ごとの根拠で、代表の経路以外にこの要素へ届くつながり（ほかの経路）を表示する（レビュー C06）
    at = analyze_scenario_a()
    box = next(s for s in at.selectbox if s.label.startswith("根拠を確認する要素"))
    box.select(next(o for o in box.options if "情報システム部" in o)).run()
    assert not at.exception
    assert any("ほかの経路（1本）" in m.value for m in at.markdown)


def test_ai_button_cannot_be_pressed_twice_while_running():
    # AIのボタンは、押されたあとの実行（AIを呼んでいる間）は押せない状態で表示する（二度押しで2回分の料金がかからないように）
    def page():
        import streamlit as st

        from changescope.ui import ai_button

        st.session_state.setdefault("calls", 0)
        if ai_button("AIで調べる", key="ai_test"):
            st.session_state.calls += 1

    at = AppTest.from_function(page).run()
    assert not at.button(key="ai_test").disabled
    at.button(key="ai_test").click().run()
    assert at.session_state.calls == 1 and at.button(key="ai_test").disabled  # 処理中は押せない
    at.run()
    assert at.session_state.calls == 1 and not at.button(key="ai_test").disabled  # 終わったら押せる


def test_guide_leads_to_own_data_registration():
    # 使い方の「自社データを用意する」から、データ管理を「自社のデータを登録する」を選んだ状態で開ける
    at = run_page("guide.py")
    at.button(key="guide_own_excel").click().run()
    assert not at.exception
    assert any(t.value == "データ管理" for t in at.title)
    assert at.radio(key="data_source").value == "own"
    assert any(b.label.startswith("白紙テンプレート") for b in at.get("download_button"))


def test_home_has_own_data_entry():
    at = run_page("home.py")
    assert not at.exception
    labels = [b.label for b in at.button]
    assert "図で入力する（はじめての方に）" in labels and "Excelで登録する" in labels


def test_analysis_tells_that_it_finished():
    # 結果はボタンの下に出て気づきにくいため、終わったことを知らせる（次の操作では出さない）
    at = analyze_scenario_a()
    assert any(s.value.startswith("分析が終わりました") for s in at.success)
    assert any("影響分析が終わりました" in t.value for t in at.toast)
    at.run()
    assert not any(s.value.startswith("分析が終わりました") for s in at.success)
