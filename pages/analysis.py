"""影響分析画面：変更内容を入力し、変更対象を確定して、直接・間接影響と根拠を表示する。"""

from html import escape

import pandas as pd
import streamlit as st

from changescope import models
from changescope.access import check_access_code, load_access_codes
from changescope.ai_client import AIClient, get_api_key
from changescope.ai_settings import load_settings, model_label
from changescope.assessment import UNCERTAIN_ZERO_NOTE, affected_departments, assess, uncertain_label
from changescope.datasets import load_scenarios
from changescope.graph_engine import (
    DEFAULT_MAX_DEPTH, PROXIMITY_POINTS, analyze_impact, describe_path, step_label,
)
from changescope.gaps import find_gaps
from changescope.insights import department_of, hard_to_notice, impact_tags, target_departments
from changescope.matcher import find_candidates
from changescope.next_actions import build_next_actions, find_uncertain_links
from changescope.oversight import ESTIMATE, SOURCES, find_oversights, load_sample_report
from changescope.report import analysis_report
from changescope.stakeholders import find_stakeholders
from changescope.ui import (
    STATUS_LABELS, action_overview, action_steps, ai_button, ai_spinner, conclusion, data_table, demo_end_card, demo_progress,
    element_label, findings_list, get_dataset, no_data_actions, note, open_upload, oversight_findings, remember_inputs,
    restore_inputs, section, show_mode_banner,
)
from changescope.usage_store import open_store

MAX_INPUT_CHARS = 1000
MAX_DEPTH_LIMIT = 8  # 選べる段数の上限
INPUT_KEYS = ["change_text", "targets", "max_depth"]

st.title("影響分析")
dataset = get_dataset()
show_mode_banner(dataset)
if dataset is None:
    no_data_actions("影響分析")
    st.stop()
demo = dataset.source == "sample"  # サンプル体験（自分のデータの分析には、進行と終わりの表示を出さない）


def label(element_id: str) -> str:
    return element_label(dataset, element_id)


def run_analysis() -> None:
    """分析を実行する。入力欄を畳んだ状態で結果を出すため、画面を描く前（ボタンの処理）で行う。"""
    state = st.session_state
    state.impact_result = analyze_impact(dataset.graph, state.targets, state.max_depth)
    state.impact_targets = list(state.targets)
    state.impact_text = state.get("change_text", "")
    state.impact_depth = state.max_depth
    state.oversight = None  # 前の分析のAI結果は消す
    state.analysis_count = state.get("analysis_count", 0) + 1
    state.just_analyzed = True
    state.demo_pdf_saved = False
    state.show_details = False


restore_inputs("analysis_inputs")
st.session_state.setdefault("max_depth", DEFAULT_MAX_DEPTH)
if request := st.session_state.pop("analysis_request", None):
    # 「A案を詳しく分析する」から来たとき：比較の条件を引き継いで、再入力なしで分析する
    st.session_state.update(change_text=request["text"], targets=list(request["targets"]), max_depth=request["depth"],
                            _last_candidates=find_candidates(request["text"], dataset.elements),
                            analysis_from=request["title"])
    run_analysis()
if st.session_state.pop("demo_prefill", False) and not st.session_state.get("change_text"):
    st.session_state.change_text = load_scenarios().iloc[0]["input_text"]  # サンプルで試す：最初の入力例を入れておく

result = st.session_state.get("impact_result")
just_analyzed = st.session_state.pop("just_analyzed", False)
if just_analyzed:
    st.toast("影響分析が終わりました。結果を表示しています。", icon=":material/check_circle:")

if demo and result is None:
    demo_progress(0)
    current = st.session_state.get("change_text", "")
    titles = dict(zip(load_scenarios()["input_text"], load_scenarios()["title"]))
    subject = f"「{titles[current]}」が" if current in titles else "変更が"
    note(f"<b>サンプル体験</b>　{escape(subject)}、どの部門・業務に影響するかを体験します。"
         "「影響を分析する」を押すだけです。AIやPDFを使わなくても、体験は完了します。")

# 分析のあとは入力欄を畳み、結果を主役にする。入力欄は残るので、値は消えない（分析のたびに畳み直す）
inputs = (st.container() if result is None
          else st.expander("入力内容を変更する", icon=":material/edit:", key=f"analysis_inputs_{st.session_state.analysis_count}"))
with inputs:
    # ---------- 1. 変更内容 ----------
    st.markdown("### 1. 変更内容を入力")
    if demo:
        st.caption("入力例（クリックすると入力欄に入ります）")
        scenarios = load_scenarios()
        columns = st.columns(len(scenarios))
        for column, (_, row) in zip(columns, scenarios.iterrows()):
            column.button(
                row["title"],
                key=f"scenario_{row['scenario_id']}",
                on_click=lambda text=row["input_text"]: st.session_state.update(change_text=text),
                width="stretch",
            )

    text = st.text_area(
        "変更したい内容",
        key="change_text",
        max_chars=MAX_INPUT_CHARS,
        placeholder="例：現在の勤怠管理システムを新しいクラウドサービスに変更したい",
    )

    # ---------- 2. 変更対象の確定 ----------
    st.markdown("### 2. 変更対象を確定")
    candidates = find_candidates(text, dataset.elements) if text.strip() else []
    # 入力文が変わって候補が変わったときだけ、選択欄を候補で置き換える（利用者の手修正は残す）
    if st.session_state.get("_last_candidates") != candidates:
        st.session_state.targets = candidates
        st.session_state._last_candidates = candidates

    targets = st.multiselect(
        "変更対象（分析の出発点）",
        list(dataset.elements["element_id"]),
        key="targets",
        format_func=label,
        help="入力文に含まれる要素名・別名から候補を自動で選びます。分析の出発点になるため、必ず確認してください。",
    )
    if text.strip() and not candidates:
        st.warning("入力文から登録済みの要素を見つけられませんでした。変更対象を一覧から選んでください。")
    elif candidates:
        st.caption("入力文から候補を自動で選びました。誤りがあれば修正してください。")

    max_depth = st.slider(
        "何段先までたどるか", 1, MAX_DEPTH_LIMIT, key="max_depth",
        help="段数を増やすと遠くの影響まで確認できますが、関係の薄い要素も増えます。",
    )

    st.button("影響を分析する", type="primary", disabled=not targets, on_click=run_analysis)
remember_inputs("analysis_inputs", INPUT_KEYS)

if result is None:
    st.stop()

# ---------- 3. 結果 ----------
analyzed_text = st.session_state.get("impact_text", "")
analyzed_depth = st.session_state.get("impact_depth", max_depth)
stale = (st.session_state.get("impact_targets") != targets or analyzed_text != text or analyzed_depth != max_depth)
st.markdown("### 影響分析の結果")
if just_analyzed:
    # 結果の見出しまでスクロールする。分析した直後だけ動かす（画面の更新のたびに戻らないように）
    st.html(f"""<script data-run="{st.session_state.analysis_count}">
setTimeout(() => {{
  const heading = [...document.querySelectorAll("h3")].find(h => h.innerText.startsWith("影響分析の結果"));
  if (heading) heading.scrollIntoView({{behavior: "smooth", block: "start"}});
}}, 400);
</script>""", unsafe_allow_javascript=True)
if stale:
    st.warning("入力内容が変更されています。下の結果は前回の条件です。もう一度「影響を分析する」を押すと更新されます。",
               icon=":material/history:")
else:
    if demo:
        demo_progress(3)  # 基本の結果が出たら体験は完了（PDF・AI・比較は任意）。結果の冒頭に完了を示す
    st.success("分析が完了しました。", icon=":material/check_circle:")
st.write("変更対象：" + "、".join(label(t) for t in result.targets) + f"　／　{analyzed_depth}段先までたどった結果")
if st.session_state.get("analysis_from") and st.button("変更案の比較に戻る", icon=":material/arrow_back:"):
    st.session_state.pop("analysis_from", None)
    st.switch_page("pages/compare.py")

uncertain = [i for i in result.impacts if i.path_status != "confirmed"]
stakeholders = find_stakeholders(dataset.graph, result)
tags = impact_tags(dataset.graph, result)
hidden = hard_to_notice(dataset.graph, result)
gaps = find_gaps(dataset.graph, result)
links = find_uncertain_links(dataset.graph, result)
departments = affected_departments(dataset.graph, result)
assessment = assess(dataset.graph, result, stakeholders)

# ---------- 第1層：結論・主要な発見・体験の終わり ----------
if result.impacts:
    conclusion(assessment, "実務でまず行うこと" if demo else "まずやること")

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("影響先", f"{len(result.impacts)} 件", help=f"変更対象を除く、影響が届く要素の数（直接{len(result.direct)}件・間接{len(result.indirect)}件）")
c2.metric("影響を受ける部門", f"{len(departments)} 部門", help="変更対象と影響先が属する部門の数。影響の広さ（大・中・小）の判定に使います")
c3.metric("関係者", f"{len(stakeholders)} 件", help="確認や調整の相手になる部門と役割を合わせた件数。部門の数とは別の値です")
c4.metric("見落とし注意", f"{len(hidden)} 件", help="変更対象の責任部門とは別の部門に、2段以上先で伝わる影響の数")
with c5.container(key="metric_uncertain"):
    st.metric("要確認のつながり", f"{len(links)} 本", help="登録された関係のうち、確認状態が推定・未確認のもの")
if links:
    st.caption(f"つながり{len(links)}本を確かめると、要確認の影響{len(uncertain)}件の有無がまとめてはっきりします。")
else:
    st.caption(f"{uncertain_label(0)}です。{UNCERTAIN_ZERO_NOTE}")

if not result.impacts:
    st.info("登録された依存関係からは、影響を受ける要素が見つかりませんでした。依存関係の登録漏れがないか確認してください。")
    st.stop()

actions = build_next_actions(dataset.graph, result, stakeholders, gaps)


def oversight_part() -> dict | None:
    """PDFに載せるAIの結果。いまの分析と同じ変更対象でAIを使ったときだけ載せる。"""
    saved = st.session_state.get("oversight")
    if not saved or saved["targets"] != result.targets:
        return None
    if saved["kind"] == "sample":
        title = f"AIによる分析のサンプル（事前に生成、{saved['generated_on']}、{model_label(saved['model'])}）。"
    else:
        title = f"AIによる分析結果（{model_label(load_settings().model)}）。"
    return {"kind": saved["kind"], "report": saved["report"], "label": title}


def report_pdf() -> bytes:
    """PDFレポート。ボタンを押したときだけ作る（作るのに数秒かかるため、画面を更新するたびには作らない）。"""
    return analysis_report(dataset.graph, dataset.source, analyzed_text, result, assessment, actions, stakeholders, links,
                           hidden, gaps, oversight_part(), analyzed_depth)


def mark_saved() -> None:
    st.session_state.demo_pdf_saved = True


if demo:
    subject = "、".join(dataset.graph.nodes[t]["name"] for t in result.targets)
    found = f"事実確認が必要な{len(links)}本のつながり" if links else "登録された関係のうち未確認が0本であること"
    demo_end_card(f"{subject}の変更が、{len(departments)}部門・{len(result.impacts)}件に影響する可能性と、{found}を確認できました。",
                  st.session_state.get("demo_pdf_saved", False))
    if st.button("自分の案件で試す", key="demo_own", type="primary", icon=":material/upload_file:", width="stretch"):
        open_upload()
    st.caption("任意の追加操作")
    c1, c2, c3 = st.columns(3)
    c1.download_button("結果をPDFで保存", report_pdf, "ChangeScope_影響分析レポート.pdf", "application/pdf", key="demo_pdf",
                       icon=":material/picture_as_pdf:", width="stretch", on_click=mark_saved)
    if c2.button("別の変更案と比較する", key="demo_compare", icon=":material/compare_arrows:", width="stretch"):
        st.session_state.compare_request = {"text": analyzed_text, "targets": list(result.targets)}
        st.switch_page("pages/compare.py")
    if c3.button("詳しい結果を見る", key="demo_details", icon=":material/expand_more:", width="stretch"):
        st.session_state.show_details = True

# ---------- 第2層：実務での対応手順・AI・PDF ----------
section("", "実際の案件での対応手順")
st.caption("ここからは、実務でこの結果を使う場合の対応例です。")
action_overview(actions)
with st.expander("手順の詳細を見る"):
    action_steps(actions)

# ---------- 4. AIで確認漏れを調べる ----------
section("", "AIによる追加確認（任意）")
st.caption(
    "上の結果は、登録されたつながりをプログラムでたどったものです。AIは、この結果をもとに"
    "「変更の前にまだ確認していないこと」と「誰に何を聞けばよいか」を挙げます。"
)


def sample_scenario_id() -> str | None:
    """サンプルデータで、入力例と同じ変更対象を分析しているときだけ、そのシナリオの番号を返す。"""
    if dataset.source != "sample":
        return None
    for _, row in load_scenarios().iterrows():
        if sorted(str(row["target_ids"]).split(";")) == sorted(result.targets):
            return row["scenario_id"]
    return None


scenario_id = sample_scenario_id()
access_codes = load_access_codes()
col_sample, col_ai = st.columns(2)
with col_sample, st.container(border=True):
    st.markdown("**サンプルを見る（料金なし）**")
    if scenario_id:
        st.caption("この入力例を、事前にAIで分析した結果を表示します。")
        if st.button("AIによる分析のサンプルを見る", icon=":material/description:"):
            sample = load_sample_report(scenario_id)
            st.session_state.oversight = {"kind": "sample", "targets": result.targets, "report": sample.report,
                                          "model": sample.model, "generated_on": sample.generated_on}
    else:
        st.caption("サンプルデータの入力例（4つのボタン）で分析すると、事前にAIで分析した結果を見られます。")
with col_ai, st.container(border=True, key="ai_check_panel"):
    st.markdown("**AIで分析する（アクセスコードが必要）**")
    if not access_codes:
        st.caption("この環境ではAI分析が設定されていません。サンプルをご覧ください。")
    else:
        code = st.text_input("アクセスコード", type="password", key="access_code")
        if not analyzed_text.strip():
            st.caption("AIに渡すため、「変更したい内容」を入力してから分析してください。")
        if ai_button("AIで確認漏れを調べる", key="ai_oversight", type="primary", icon=":material/search:",
                     disabled=not analyzed_text.strip(), width="stretch"):
            user_key = check_access_code(code, access_codes)
            if user_key is None:
                st.error("アクセスコードが正しくありません。")
            else:
                settings = load_settings()
                client = AIClient(settings, open_store(settings.usage_db), api_key=get_api_key())
                with ai_spinner("AIが確認漏れを調べています", "1分前後"):
                    report, message = find_oversights(client, dataset.graph, result, analyzed_text, stakeholders, gaps,
                                                      hidden, user_key)
                if report is None:
                    st.warning(message)
                else:
                    st.session_state.oversight = {"kind": "ai", "targets": result.targets, "report": report,
                                                  "yen": settings.to_yen(report.cost_usd)}

oversight = st.session_state.get("oversight")
if oversight and oversight["targets"] == result.targets:
    report = oversight["report"]
    if oversight["kind"] == "sample":
        note(f"<b>AIによる分析のサンプル</b>　事前にAIで生成した結果です（{escape(oversight['generated_on'])}、"
             f"{escape(model_label(oversight['model']))}）。いま実行したAI分析ではありません。"
             "AIの回答は毎回少しずつ異なるため、同じ内容で分析しても結果が変わることがあります。")
    else:
        note(f"<b>AIによる分析結果</b>（{escape(model_label(load_settings().model))}）　"
             f"今回の費用（試算）：約{oversight['yen']:.1f}円")
    st.caption(
        "AIは組織全体を知りません。指摘には根拠の種類を付けています。「登録済みのつながり」は登録されたつながりを根拠にした指摘"
        "（つながりの番号が実在することは確かめていますが、指摘の内容が正しいかまでは確かめていません）、"
        "「一般的な確認の観点」は法令・契約・データ移行など変更の種類から一般的に確認すべきこと、"
        "「AIの推測」は登録されていないものを推測した指摘です。どれも確認先に聞いて確かめてください。"
        f"費用や期間の数字は、AIに作らせず「{ESTIMATE}」と表示します。"
    )
    counts = {s: sum(f.basis == s for f in report.findings) for s in SOURCES}
    st.markdown(f"**確認漏れ {len(report.findings)}件**（"
                + "・".join(f"{s} {n}件" for s, n in counts.items()) + "。重要度の高い順）")
    oversight_findings(report.findings)

    ai_tabs = st.tabs(["部門別の調整ポイント", "トラブルの予測", "見落としがちな費用", "推奨する進め方",
                       f"未登録の影響の推測（{len(report.unregistered)}）"])
    with ai_tabs[0]:
        data_table(pd.DataFrame({
            "部門・担当": [d["department"] + ("" if d["registered"] else "（未登録の部門候補）")
                       for d in report.department_points],
            "調整ポイント": [[f"・{p['viewpoint']}：{p['content']}" for p in d["points"]] for d in report.department_points],
        }))
    with ai_tabs[1]:
        data_table(pd.DataFrame({
            "起こりうるトラブル": [r["scenario"] for r in report.risks],
            "起きる条件": [r["condition"] for r in report.risks],
            "影響が広がる先": [r["spread_to"] for r in report.risks],
            "予防策": [r["prevention"] for r in report.risks],
        }))
    with ai_tabs[2]:
        st.caption(f"金額はAIに作らせていません。必要な費用は見積もりで確認してください（{ESTIMATE}）。")
        data_table(pd.DataFrame({
            "費用の項目": [c["item"] for c in report.hidden_costs],
            "見落としやすい理由": [c["detail"] for c in report.hidden_costs],
        }))
    with ai_tabs[3]:
        data_table(pd.DataFrame({
            "段階": [a["step"] for a in report.approach],
            "内容": [a["detail"] for a in report.approach],
        }))
    with ai_tabs[4]:
        st.caption("登録データにはないが、関係しそうな要素のAIの推測です。実在すれば、Excelに追加して分析し直してください。")
        data_table(pd.DataFrame({
            "要素の候補": [u["name"] for u in report.unregistered],
            "種類": [u["element_type"] for u in report.unregistered],
            "理由": [u["reason"] for u in report.unregistered],
        }))

# ---------- PDFレポート ----------
if not demo:  # サンプル体験では、体験の終わりの表示から保存する
    section("", "PDFで持ち帰る")
    st.caption("結論・対応手順・関係者・要確認のつながり・見落とし・影響の一覧を、1つのPDFにします。"
               + ("上の「AIで確認漏れを調べる」の結果も載せます。" if oversight_part() else
                  "「AIで確認漏れを調べる」の結果を表示してから押すと、それも載せます。"))
    st.download_button("PDFでダウンロード", report_pdf, "ChangeScope_影響分析レポート.pdf", "application/pdf",
                       icon=":material/picture_as_pdf:", type="primary")

# ---------- 第3層：詳しい結果 ----------
show_details = st.session_state.get("show_details", False)
details = st.expander("詳しい結果（一覧・経路・計算方法・根拠）", expanded=show_details, icon=":material/list:",
                      key=f"analysis_details_{show_details}")
if show_details:
    st.html("""<script>
setTimeout(() => {
  const heading = [...document.querySelectorAll("summary")].find(h => h.innerText.includes("詳しい結果"));
  if (heading) heading.scrollIntoView({behavior: "smooth", block: "start"});
}, 400);
</script>""", unsafe_allow_javascript=True)
with details:

    st.caption(
        "確認状態：確認済＝確認済みの関係だけで届く経路がある　推定＝どの経路にも推定以下の関係を含む　"
        "未確認＝どの経路にも未確認の関係を含む"
    )
    with st.expander("影響度の計算方法"):
        st.markdown(
            f"影響度 ＝ **近さ** ＋ **波及数** ＋ **複数経路**（大きいほど影響が大きい。上から影響の大きい順に表示）\n\n"
            f"- **近さ**：変更対象から1段目＝{PROXIMITY_POINTS[1]}点、2段目＝{PROXIMITY_POINTS[2]}点、"
            f"3段目＝{PROXIMITY_POINTS[3]}点、それより先＝1点\n"
            "- **波及数**：その要素を経由して、さらに影響が伝わる要素の数（1件＝1点）\n"
            "- **複数経路**：最短の経路以外にも、影響範囲の要素から何本つながっているか（1本＝1点）\n\n"
            "確認状態（確からしさ）は影響の大きさとは別の軸として、点数には含めていません。"
        )

    LEVEL_LABELS = {"direct": "直接", "indirect": "間接"}


    def department_name(element_id: str) -> str:
        department = department_of(dataset.graph, element_id)
        return dataset.graph.nodes[department]["name"] if department else ""


    def impact_table(items) -> pd.DataFrame:
        return pd.DataFrame({
            "影響度": [i.score for i in items],
            "注目": [tags.get(i.element_id, "") for i in items],
            "影響を受ける要素": [i.name for i in items],
            "種類": [models.element_type_label(i.element_type) for i in items],
            "所属部門": [department_name(i.element_id) for i in items],
            "区分": [f"{LEVEL_LABELS[i.level]}（{i.depth}段）" for i in items],
            "確認状態": [STATUS_LABELS[i.path_status] for i in items],
            "影響の経路": [describe_path(dataset.graph, i) for i in items],
        })


    def stakeholder_table(items) -> pd.DataFrame:
        return pd.DataFrame({
            "関係者": [s.name for s in items],
            "種類": [s.type_label for s in items],
            "所属": [s.department for s in items],
            "影響度（最大）": [s.max_score for s in items],
            "確認状態": [STATUS_LABELS[s.status] for s in items],
            # 理由はすべて、1行に1つずつ表示する
            "影響する理由": [[f"・{r.text}（{STATUS_LABELS[r.status]}）" for r in s.reasons] for s in items],
        })


    tab0, tab_links, tab_hidden, tab_gaps, tab1, tab2, tab3 = st.tabs([
        f"誰に影響するか（{len(stakeholders)}）", f"要確認のつながり（{len(links)}本）",
        f"見落としやすい影響（{len(hidden)}）", f"見落としチェック（{len(gaps)}）",
        f"直接影響（{len(result.direct)}）", f"間接影響（{len(result.indirect)}）", "要素ごとの根拠",
    ])
    with tab0:
        if stakeholders:
            st.caption(
                "変更対象の責任部門を先頭に、影響度の大きい順に表示します。"
                "部門・役割そのものが影響範囲に含まれる場合と、責任を持つ要素が影響を受ける場合を集めています。"
            )
            data_table(stakeholder_table(stakeholders), numeric_columns=("影響度（最大）",))
        else:
            st.info("登録データからは、影響を受ける部門・役割が見つかりませんでした。要素の責任部門（owner）が登録されているか確認してください。")
    with tab_links:
        if links:
            first = links[0]
            examples = "、".join(first.affected_names[:3]) + (" など" if first.affected > 3 else "")
            # 例の文には登録データの名前が入るため、エスケープしてから表示する
            note(
                "推定・未確認のつながりの一覧です。<b>1本のつながりが未確認だと、その先にある要素はすべて要確認</b>になります。"
                f"例えば「{escape(first.text)}」を確かめると、{escape(examples)}の"
                f"{first.affected}件の影響の有無がはっきりします。"
                "確かめると分かることが多い順に並んでいるので、上から確認先に問い合わせてください。"
            )
            data_table(pd.DataFrame({
                "確かめるつながり": [link.text for link in links],
                "確認状態": [STATUS_LABELS[link.status] for link in links],
                "確認先": ["、".join(link.contacts) or "責任部門が未登録" for link in links],
                "有無がはっきりする影響": [[f"{link.affected}件："] + link.affected_names for link in links],
                "補足": [link.note for link in links],
                "根拠": [link.evidence for link in links],
            }))
        else:
            st.write("登録済みのつながりの範囲では、確かめる必要があるつながりはありません（経路のつながりはすべて確認済みです）。"
                     "登録していないつながり、たどった段数より先、情報が古くなったつながりは含まれません。")
    with tab_hidden:
        st.caption(
            "変更対象の責任部門とは別の部門に、2段以上先で伝わる影響です。"
            "変更を担当する部門からは見えにくく、直接のつながりだけを調べても出てこないため、事前の調査で漏れやすい影響です。"
        )
        if hidden:
            data_table(impact_table(hidden).drop(columns=["注目"]), numeric_columns=("影響度",))
        elif not target_departments(dataset.graph, result):
            st.info("変更対象の責任部門が登録されていないため、判定できません。要素の「責任部門・担当」を登録してください。")
        else:
            st.write("見落としやすい影響はありません。")
    with tab_gaps:
        st.caption(
            "「登録の不足」は、分析の範囲で登録が足りないデータです。"
            "「確認すべき観点」は、影響範囲に含まれる要素の種類から、変更時に忘れやすい確認事項を対象つきで示しています。"
            "変更計画やテスト計画に入れてください。"
        )
        if gaps:
            findings_list(gaps)
        else:
            st.write("見落としチェックで指摘する項目はありません。")
    with tab1:
        st.caption("注目：他部門＝変更対象の責任部門とは別の部門の要素　見落としやすい＝他部門の要素で、2段以上先にあるもの")
        data_table(impact_table(result.direct), numeric_columns=("影響度",))
    with tab2:
        st.caption("注目：他部門＝変更対象の責任部門とは別の部門の要素　見落としやすい＝他部門の要素で、2段以上先にあるもの")
        if result.indirect:
            data_table(impact_table(result.indirect), numeric_columns=("影響度",))
        else:
            st.write("間接影響はありません。")
    with tab3:
        chosen = st.selectbox(
            "根拠を確認する要素（影響の大きい順）",
            result.impacts,
            format_func=lambda i: f"{STATUS_LABELS[i.path_status]}　{i.name}（{LEVEL_LABELS[i.level]}・影響度{i.score}）",
        )
        st.markdown(f"**なぜ影響するのか：** {describe_path(dataset.graph, chosen)}")
        for n, step in enumerate(chosen.path, start=1):
            with st.container(border=True):
                st.markdown(
                    f"**{n}. {dataset.graph.nodes[step.from_id]['name']} → "
                    f"{dataset.graph.nodes[step.to_id]['name']}**（{step_label(step)}）"
                )
                st.markdown(
                    f"- 根拠：{step.evidence}\n"
                    f"- 確認状態：{STATUS_LABELS[step.status]}"
                    + (f"\n- 補足：{step.note}" if step.note else "")
                )
        if chosen.path_status != min((s.status for s in chosen.path), key=["unconfirmed", "assumed", "confirmed"].index):
            st.caption(f"上の経路には確かめていないつながりがありますが、別の経路でも影響が届くため、"
                       f"この要素の確認状態は「{STATUS_LABELS[chosen.path_status]}」です。")
        if chosen.other_links:
            st.markdown(f"**ほかの経路（{len(chosen.other_links)}本）：** 影響範囲の中から、この要素へほかにも届くつながりです。")
            data_table(pd.DataFrame({
                "つながり": [f"{dataset.graph.nodes[s.from_id]['name']} → {dataset.graph.nodes[s.to_id]['name']}"
                         f"（{step_label(s)}）" for s in chosen.other_links],
                "確認状態": [STATUS_LABELS[s.status] for s in chosen.other_links],
                "根拠": [s.evidence for s in chosen.other_links],
            }))
