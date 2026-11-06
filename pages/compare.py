"""変更案を比べる画面：共通の目的に照らして、2つの変更案の範囲・影響・判断前に確認することを並べて示す（AIは使わない）。

どちらの案が良いかは決めない。目的への適合性は判定せず、登録データから分かることと、分からないことを分けて示す。
計算は changescope/compare.py にある。
"""

from html import escape

import pandas as pd
import streamlit as st

from changescope.assessment import METRIC_DEFINITIONS, UNCERTAIN_ZERO_NOTE, uncertain_label
from changescope.compare import Goal, OptionInput, compare, comparison_key
from changescope.datasets import load_option_pairs
from changescope.matcher import find_candidates
from changescope.report import comparison_report
from changescope.ui import (
    data_table, element_label, get_dataset, no_data_actions, note, remember_inputs, restore_inputs, section, show_mode_banner,
)

st.title("変更案を比べる")
dataset = get_dataset()
show_mode_banner(dataset)
if dataset is None:
    no_data_actions("変更案の比較")
    st.stop()

note("共通の目的に対して、2つの変更案の<b>対応範囲の違い</b>と<b>判断前に確認すること</b>を並べます。"
     "<b>どちらが良いかは決めません。</b>影響範囲が狭い案が、目的を満たすとは限らないためです。")
MAX_INPUT_CHARS = 1000
SIDES = {"a": "A案", "b": "B案"}
OPTION_FIELDS = ["name", "text", "targets", "cost", "period", "approach", "expected", "premise"]
INPUT_KEYS = ["cp_goal", "cp_success"] + [f"cp_{side}_{field}" for side in SIDES for field in OPTION_FIELDS]
pairs = load_option_pairs() if dataset.source == "sample" else None


def fill_pair(row) -> None:
    """入力例のボタン：共通の目的と、2つの案の名前・変更内容・変更対象を入れる。"""
    st.session_state.cp_goal, st.session_state.cp_success = row["goal"], row["success"]
    for side in SIDES:
        st.session_state[f"cp_{side}_name"] = row[f"{side}_name"]
        st.session_state[f"cp_{side}_text"] = row[f"{side}_text"]
        targets = [t for t in str(row[f"{side}_targets"]).split(";") if t]
        st.session_state[f"cp_{side}_targets"] = targets
        st.session_state[f"cp_{side}_last"] = find_candidates(row[f"{side}_text"], dataset.elements)
        for key in ("cost", "period", "approach", "expected", "premise"):
            st.session_state[f"cp_{side}_{key}"] = ""
    st.session_state.pop("cp_result", None)
    st.session_state.pop("cp_key", None)


restore_inputs("cp_inputs")
if request := st.session_state.pop("compare_request", None):
    # 影響分析の「別の変更案と比較する」から来たとき：分析した内容をA案に入れる。同じ変更対象の入力例があれば、それを使う
    match = None
    if pairs is not None:
        same = pairs[pairs["a_targets"] == ";".join(request["targets"])]
        match = None if same.empty else same.iloc[0]
    if match is not None:
        fill_pair(match)
    else:
        st.session_state.cp_a_text = request["text"]
        st.session_state.cp_a_targets = list(request["targets"])
        st.session_state.cp_a_last = find_candidates(request["text"], dataset.elements)

# ---------- 1. 共通の目的 ----------
st.markdown("### 1. 共通の目的")
if pairs is not None:
    st.caption("入力例（クリックすると、目的と2つの案が入ります）")
    columns = st.columns(len(pairs))
    for column, (_, row) in zip(columns, pairs.iterrows()):
        column.button(row["title"], key=f"cp_pair_{row['pair_id']}", on_click=fill_pair, args=(row,), width="stretch")
purpose = st.text_input("解決したい課題／達成したい目的（任意）", key="cp_goal", max_chars=200,
                        placeholder="例：勤怠の締め作業の負担を減らしたい")
success = st.text_input("成功条件（任意）", key="cp_success", max_chars=200, placeholder="例：締め作業の時間を現状の半分にしたい")
if pairs is not None and purpose.strip() in set(pairs["goal"]):
    st.caption("この目的と成功条件は、サンプル用の架空の設定です。")
elif not purpose.strip():
    st.caption("目的が未入力でも比較できます。その場合、目的への適合性は「未評価」と表示します。")
goal = Goal(purpose.strip(), success.strip())

# ---------- 2. 2つの案 ----------
st.markdown("### 2. 2つの変更案を入力")
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
        with st.expander("補足（目的への対応・期待する効果・前提）"):
            approach = st.text_input("目的にどう対応する案か", key=f"cp_{side}_approach")
            expected = st.text_input("期待する効果と根拠", key=f"cp_{side}_expected",
                                     help="入力された内容は「入力された見込み」と表示し、ツールでは検証しません。")
            premise = st.text_input("前提条件／制約", key=f"cp_{side}_premise")
        inputs[side] = OptionInput(label, text, list(targets), cost.strip(), period.strip(), approach.strip(),
                                   expected.strip(), premise.strip())
remember_inputs("cp_inputs", INPUT_KEYS + ["cp_a_last", "cp_b_last"])

current_key = comparison_key(goal, inputs["a"], inputs["b"], id(dataset.graph))
ready = all(option.targets for option in inputs.values())
if st.button("比べる", type="primary", icon=":material/compare_arrows:", disabled=not ready):
    st.session_state.cp_result = compare(dataset.graph, inputs["a"], inputs["b"], goal=goal)
    st.session_state.cp_titles = titles
    st.session_state.cp_key = current_key
if not ready:
    st.caption("2つの案の両方で、変更対象を1つ以上選んでください（変更内容に要素の名前を書くと、自動で選ばれます）。")

result = st.session_state.get("cp_result")
if result is None:
    st.stop()

# ---------- 3. 結果 ----------
st.divider()
a_name, b_name = result.a.option.name, result.b.option.name  # A案・B案
title = st.session_state.get("cp_titles", {"a": a_name, "b": b_name})
stale = st.session_state.get("cp_key") != current_key
st.markdown("### 比較結果")
if stale:
    # 条件を変えたあとに、古い結果を新しい結果として見せない
    st.warning("条件が変更されています。下の結果は前回の条件です。もう一度「比べる」を押すと更新されます。", icon=":material/history:")

section("SUMMARY", "比較の要約")
note("<br>".join(escape(line) for line in result.summary))

section("KEY DIFFERENCES", "重要な違い")
data_table(pd.DataFrame({
    "観点": [r.viewpoint for r in result.differences],
    title["a"]: [r.a.split("\n") for r in result.differences],
    title["b"]: [r.b.split("\n") for r in result.differences],
}))

section("BEFORE YOU DECIDE", "判断前に確認すること")
st.caption("目的に対応する確認と、登録された依存関係から抽出した確認を分けています。重要なものから順に並べています。")
data_table(pd.DataFrame({
    "区分": [c.kind for c in result.checks],
    "確認事項": [c.item for c in result.checks],
    "なぜ判断に必要か": [c.why for c in result.checks],
    "確認先": [c.contact for c in result.checks],
    "対象案": [c.target for c in result.checks],
    "確認の根拠": [c.basis for c in result.checks],
}))

section("COMPARISON TABLE", "比較表")
st.caption(f"{result.max_depth}段先までたどった結果です。件数の差は違いを示すだけで、少ない案が優れているという意味ではありません。")
data_table(pd.DataFrame({
    "観点": [r.viewpoint for r in result.rows],
    title["a"]: [r.a for r in result.rows],
    title["b"]: [r.b for r in result.rows],
    "違い": [r.difference for r in result.rows],
}))
if not (result.a.uncertain and result.b.uncertain):
    st.caption(f"{uncertain_label(0)}は、{UNCERTAIN_ZERO_NOTE}")
with st.expander("指標の定義"):
    st.markdown("\n".join(f"- **{name}**：{meaning}" for name, meaning in METRIC_DEFINITIONS))


def split_table(split) -> None:
    if not (split.only_a or split.only_b or split.both):
        st.write("どちらの案にもありません。")
        return
    data_table(pd.DataFrame({
        f"{a_name}だけ（{len(split.only_a)}）": [split.only_a or ["なし"]],
        f"{b_name}だけ（{len(split.only_b)}）": [split.only_b or ["なし"]],
        f"両方（{len(split.both)}）": [split.both or ["なし"]],
    }))


with st.expander("詳細な差分と根拠（Aだけ・Bだけ・両方）", icon=":material/list:"):
    st.caption(f"「{a_name}だけ」は、今回の登録データと分析条件で、{a_name}にのみ影響候補として抽出されたものです。"
               f"{b_name}で対応が不要になるという意味ではありません。")
    tabs = st.tabs(["要確認のつながり", "関係する部門・担当", "見落としやすい影響", "確認すべき観点", "変更対象と影響先"])
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
        st.caption("変更対象と影響先を合わせたものです。")
        split_table(result.elements)

# ---------- 次の操作 ----------
source = dataset.source


def report_pdf() -> bytes:
    """PDFレポート。ボタンを押したときだけ作る。"""
    return comparison_report(result, title, source)


def open_analysis(option_result, option_title: str) -> None:
    """この案の条件を引き継いで、影響分析を開く（再入力は不要。比較の条件と結果は残る）。"""
    st.session_state.analysis_request = {"text": option_result.option.text, "targets": list(option_result.option.targets),
                                         "depth": result.max_depth, "title": option_title}
    st.switch_page("pages/analysis.py")


section("NEXT", "次の操作")
if stale:
    st.caption("下の操作は、前回の条件の結果に対するものです。")
c1, c2, c3 = st.columns(3)
if c1.button("A案を詳しく分析する", key="cp_analyze_a", icon=":material/search:", width="stretch"):
    open_analysis(result.a, title["a"])
if c2.button("B案を詳しく分析する", key="cp_analyze_b", icon=":material/search:", width="stretch"):
    open_analysis(result.b, title["b"])
c3.download_button("比較結果をPDFでダウンロード", report_pdf, "ChangeScope_変更案の比較レポート.pdf", "application/pdf",
                   icon=":material/picture_as_pdf:", type="primary", width="stretch", disabled=stale,
                   help="要約・重要な違い・確認事項・比較表を、1つのPDFにします。")
