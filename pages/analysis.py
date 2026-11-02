"""影響分析画面：変更内容を入力し、変更対象を確定して、直接・間接影響と根拠を表示する。"""

from html import escape

import pandas as pd
import streamlit as st

from changescope import models
from changescope.access import check_access_code, load_access_codes
from changescope.ai_client import AIClient, get_api_key
from changescope.ai_settings import load_settings, model_label
from changescope.assessment import assess
from changescope.datasets import load_scenarios
from changescope.graph_engine import (
    DEFAULT_MAX_DEPTH, PROXIMITY_POINTS, analyze_impact, describe_path, step_label,
)
from changescope.gaps import find_gaps
from changescope.insights import department_of, hard_to_notice, impact_tags, target_departments
from changescope.matcher import find_candidates
from changescope.next_actions import build_next_actions, find_uncertain_links
from changescope.oversight import ESTIMATE, REGISTERED, find_oversights, load_sample_report
from changescope.stakeholders import find_stakeholders
from changescope.ui import (
    STATUS_LABELS, action_steps, conclusion, data_table, element_label, findings_list, get_dataset, note,
    oversight_findings, section, show_mode_banner,
)
from changescope.usage_store import UsageStore

MAX_INPUT_CHARS = 1000
MAX_DEPTH_LIMIT = 8  # 選べる段数の上限

st.title("影響分析")
dataset = get_dataset()
show_mode_banner(dataset)
if dataset is None:
    st.page_link("pages/data.py", label="データ管理へ", icon=":material/folder_open:")
    st.stop()


def label(element_id: str) -> str:
    return element_label(dataset, element_id)


# ---------- 1. 変更内容 ----------
st.markdown("### 1. 変更内容を入力")
if dataset.source == "sample":
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
    "何段先までたどるか", 1, MAX_DEPTH_LIMIT, DEFAULT_MAX_DEPTH,
    help="段数を増やすと遠くの影響まで確認できますが、関係の薄い要素も増えます。",
)

if st.button("影響を分析する", type="primary", disabled=not targets):
    st.session_state.impact_result = analyze_impact(dataset.graph, targets, max_depth)
    st.session_state.impact_targets = list(targets)
    st.session_state.oversight = None  # 前の分析のAI結果は消す

result = st.session_state.get("impact_result")
if result is None:
    st.stop()

# ---------- 3. 結果 ----------
st.divider()
st.markdown("### 3. 影響分析結果")
st.write("変更対象：" + "、".join(label(t) for t in result.targets))
if st.session_state.get("impact_targets") != targets:
    st.caption("※ 変更対象が変更されています。もう一度「影響を分析する」を押すと結果が更新されます。")

uncertain = [i for i in result.impacts if i.path_status != "confirmed"]
stakeholders = find_stakeholders(dataset.graph, result)
tags = impact_tags(dataset.graph, result)
hidden = hard_to_notice(dataset.graph, result)
gaps = find_gaps(dataset.graph, result)
links = find_uncertain_links(dataset.graph, result)

if result.impacts:
    conclusion(assess(dataset.graph, result, stakeholders))

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("関係者", f"{len(stakeholders)} 件", help="影響を受ける部門・役割の数")
c2.metric("直接影響", f"{len(result.direct)} 件", help="変更対象と直接つながっている要素の数")
c3.metric("間接影響", f"{len(result.indirect)} 件", help="他の要素を経由して影響が伝わる要素の数")
c4.metric("見落とし注意", f"{len(hidden)} 件", help="変更対象の責任部門とは別の部門に、2段以上先で伝わる影響の数")
c5.metric("要確認", f"{len(uncertain)} 件",
          help="経路に「推定」または「未確認」のつながりを含む影響（要素）の数。確かめるつながりの本数とは違います")

if links:
    # 要確認の影響（件）と、確かめるつながり（本）の数が違う理由を、数字のすぐ下で説明する
    note(
        f"<b>要確認 {len(uncertain)}件と、確かめるつながり {len(links)}本の関係</b>　"
        "「要確認」は、影響を受ける<b>要素</b>の数です。1本のつながりが未確認だと、その先にある要素はすべて要確認になります。"
        f"そのため、<b>確かめるのはつながり {len(links)}本</b>で、それを確かめれば {len(uncertain)}件の影響の有無がまとめてはっきりします。"
        "一覧は、下の「要確認のつながり」タブで確認できます。"
    )

if not result.impacts:
    st.info("登録された依存関係からは、影響を受ける要素が見つかりませんでした。依存関係の登録漏れがないか確認してください。")
    st.stop()

section("NEXT ACTIONS", "次にやること")
st.caption("この分析結果をもとに、変更を安全に進めるための手順を上から順に示しています。")
action_steps(build_next_actions(dataset.graph, result, stakeholders, gaps))

# ---------- 4. AIで確認漏れを調べる ----------
section("AI CHECK", "AIで確認漏れを調べる")
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
with col_ai, st.container(border=True):
    st.markdown("**AIで分析する（アクセスコードが必要）**")
    if not access_codes:
        st.caption("この環境ではAI分析が設定されていません。サンプルをご覧ください。")
    else:
        code = st.text_input("アクセスコード", type="password", key="access_code")
        if not text.strip():
            st.caption("AIに渡すため、「変更したい内容」を入力してください。")
        if st.button("AIで確認漏れを調べる", type="primary", icon=":material/search:", disabled=not text.strip()):
            user_key = check_access_code(code, access_codes)
            if user_key is None:
                st.error("アクセスコードが正しくありません。")
            else:
                settings = load_settings()
                client = AIClient(settings, UsageStore(settings.usage_db), api_key=get_api_key())
                with st.spinner("AIが確認漏れを調べています（1分ほどかかります。画面を閉じずにお待ちください）"):
                    report, message = find_oversights(client, dataset.graph, result, text, stakeholders, gaps,
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
        "AIは組織全体を知りません。「登録情報にもとづく」は登録されたつながりを根拠にした指摘、"
        "「AIの推測」は根拠が登録データにない指摘です。どちらも確認先に聞いて確かめてください。"
        f"費用や期間の数字は、AIに作らせず「{ESTIMATE}」と表示します。"
    )
    registered = sum(f.basis == REGISTERED for f in report.findings)
    st.markdown(f"**確認漏れ {len(report.findings)}件**（登録情報にもとづく {registered}件・"
                f"AIの推測 {len(report.findings) - registered}件。重要度の高い順）")
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

section("DETAILS", "詳しい結果")

st.caption(
    "確認状態：確認済＝経路の依存関係がすべて確認済み　推定＝推定の関係を含む　"
    "未確認＝未確認の関係を含む（経路の中で最も不確かな状態を表示）"
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
        st.write("確かめる必要があるつながりはありません（経路のつながりはすべて確認済みです）。")
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
