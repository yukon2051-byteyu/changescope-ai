"""変更案を比べる画面：2つの変更案の影響範囲・関係する部門・要確認のつながりなどを並べて示す（AIは使わない）。

どちらの案が良いかは決めない。影響が小さい案が目的を満たすとは限らないため、判断の材料（違い）だけを示す。
計算は changescope/compare.py にある。
"""

import pandas as pd
import streamlit as st

from changescope.compare import OptionInput, compare
from changescope.datasets import load_option_pairs
from changescope.matcher import find_candidates
from changescope.report import comparison_report
from changescope.ui import data_table, element_label, get_dataset, note, section, show_mode_banner

st.title("変更案を比べる")
dataset = get_dataset()
show_mode_banner(dataset)
if dataset is None:
    st.page_link("pages/data.py", label="データ管理へ", icon=":material/folder_open:")
    st.stop()

note("2つの変更案（例：システムを入れ替える案と、手順だけを見直す案）の、<b>影響の広さ</b>と<b>まだ確認していないこと</b>の違いを並べます。"
     "<b>どちらが良いかは決めません。</b>影響が小さい案が、変更の目的を満たすとは限らないためです。判断の材料としてお使いください。")
MAX_INPUT_CHARS = 1000
SIDES = {"a": "A案", "b": "B案"}


def fill_pair(row) -> None:
    """入力例のボタン：2つの案の名前・変更内容・変更対象を入れる。"""
    for side in SIDES:
        st.session_state[f"cp_{side}_name"] = row[f"{side}_name"]
        st.session_state[f"cp_{side}_text"] = row[f"{side}_text"]
        targets = [t for t in str(row[f"{side}_targets"]).split(";") if t]
        st.session_state[f"cp_{side}_targets"] = targets
        st.session_state[f"cp_{side}_last"] = find_candidates(row[f"{side}_text"], dataset.elements)
        for key in ("cost", "period"):
            st.session_state[f"cp_{side}_{key}"] = ""
    st.session_state.pop("cp_result", None)


# ---------- 1. 2つの案を入力 ----------
st.markdown("### 1. 2つの変更案を入力")
if dataset.source == "sample":
    st.caption("入力例（クリックすると2つの案が入ります）")
    pairs = load_option_pairs()
    columns = st.columns(len(pairs))
    for column, (_, row) in zip(columns, pairs.iterrows()):
        column.button(row["title"], key=f"cp_pair_{row['pair_id']}", on_click=fill_pair, args=(row,), width="stretch")

inputs, titles = {}, {}
for column, (side, label) in zip(st.columns(2, gap="large"), SIDES.items()):
    with column, st.container(border=True):
        st.markdown(f"**{label}**")
        name = st.text_input("案の名前（任意）", key=f"cp_{side}_name", placeholder="例：システムを入れ替える")
        # 表の「違い」は「A案の方が〜」と読めるよう A案・B案 で書き、案の名前は見出しにだけ使う
        titles[side] = f"{label}（{name.strip()}）" if name.strip() else label
        text = st.text_area("変更内容", key=f"cp_{side}_text", max_chars=MAX_INPUT_CHARS, height=100,
                            placeholder="例：勤怠管理システムを新しいクラウドサービスに入れ替える")
        candidates = find_candidates(text, dataset.elements) if text.strip() else []
        # 変更内容が変わって候補が変わったときだけ、変更対象を候補で置き換える（利用者の手直しは残す）
        if st.session_state.get(f"cp_{side}_last") != candidates:
            st.session_state[f"cp_{side}_targets"] = candidates
            st.session_state[f"cp_{side}_last"] = candidates
        targets = st.multiselect("変更対象（手を入れるもの。複数選べます）", list(dataset.elements["element_id"]),
                                 key=f"cp_{side}_targets", format_func=lambda i: element_label(dataset, i))
        c1, c2 = st.columns(2)
        cost = c1.text_input("費用（任意）", key=f"cp_{side}_cost", placeholder="空欄なら「要見積もり」")
        period = c2.text_input("期間（任意）", key=f"cp_{side}_period", placeholder="空欄なら「要見積もり」")
        inputs[side] = OptionInput(label, text, list(targets), cost.strip(), period.strip())

ready = all(option.targets for option in inputs.values())
if st.button("比べる", type="primary", icon=":material/compare_arrows:", disabled=not ready):
    st.session_state.cp_result = compare(dataset.graph, inputs["a"], inputs["b"])
    st.session_state.cp_titles = titles
if not ready:
    st.caption("2つの案の両方で、変更対象を1つ以上選んでください（変更内容に要素の名前を書くと、自動で選ばれます）。")

result = st.session_state.get("cp_result")
if result is None:
    st.stop()

# ---------- 2. 結果 ----------
st.divider()
a_name, b_name = result.a.option.name, result.b.option.name  # A案・B案
title = st.session_state.get("cp_titles", {"a": a_name, "b": b_name})
st.markdown("### 2. 比較結果")
uncertain_a, uncertain_b = len(result.a.uncertain), len(result.b.uncertain)
note(f"<b>関係する要素</b>は {a_name} {len(result.a.involved)}件・{b_name} {len(result.b.involved)}件、"
     f"<b>まだ確認していないつながり</b>は {a_name} {uncertain_a}本・{b_name} {uncertain_b}本です。"
     "確認していないつながりが多い案は、実施前のヒアリングに時間がかかります。"
     "案を選ぶ前に、下の「要確認のつながり」を確認先に問い合わせると、判断の精度が上がります。")
data_table(pd.DataFrame({
    "観点": [r.viewpoint for r in result.rows],
    title["a"]: [r.a for r in result.rows],
    title["b"]: [r.b for r in result.rows],
    "違い": [r.difference for r in result.rows],
}))

source = dataset.source


def report_pdf() -> bytes:
    """PDFレポート。ボタンを押したときだけ作る。"""
    return comparison_report(result, title, source)


st.download_button("比較結果をPDFでダウンロード", report_pdf, "ChangeScope_変更案の比較レポート.pdf", "application/pdf",
                   icon=":material/picture_as_pdf:", type="primary",
                   help="比較表と、Aだけ・Bだけ・両方の一覧を、1つのPDFにします。")

section("DIFFERENCES", "どこが違うか（Aだけ・Bだけ・両方）")
st.caption(f"「{a_name}だけ」に出るものは、{b_name}を選べば対応や確認が不要になるものです。「両方」に出るものは、どちらの案でも必要です。")


def split_table(split) -> None:
    if not (split.only_a or split.only_b or split.both):
        st.write("どちらの案にもありません。")
        return
    data_table(pd.DataFrame({
        f"{a_name}だけ（{len(split.only_a)}）": [split.only_a or ["なし"]],
        f"{b_name}だけ（{len(split.only_b)}）": [split.only_b or ["なし"]],
        f"両方（{len(split.both)}）": [split.both or ["なし"]],
    }))


tabs = st.tabs(["要確認のつながり", "関係する部門・担当", "見落としやすい影響", "確認すべき観点", "関係する要素"])
with tabs[0]:
    st.caption("推定・未確認のつながりです。確かめないと、影響があるかどうかがはっきりしません。")
    split_table(result.uncertain)
with tabs[1]:
    split_table(result.stakeholders)
with tabs[2]:
    st.caption("変更対象の責任部門とは別の部門に、2段以上先で伝わる影響です。")
    split_table(result.hidden)
with tabs[3]:
    st.caption("データ移行・連携・規程・切り戻しなど、変更時に忘れやすい確認事項です。")
    split_table(result.gaps)
with tabs[4]:
    st.caption("手を入れる要素と、影響を受ける要素を合わせたものです。")
    split_table(result.elements)

st.caption("それぞれの案の詳しい影響と根拠、AIによる確認漏れの調査は、「影響分析」で案ごとに分析してください。")
st.page_link("pages/analysis.py", label="影響分析", icon=":material/troubleshoot:")
