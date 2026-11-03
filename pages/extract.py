"""文章・資料から作る画面：文章や資料から、AIが要素とつながりの候補（図のたたき台）を作り、人が選んで登録する。

使い方は2つ。
- 文章で説明する：業務の流れを数行で書く。アクセスコードなしで使える（無料分の予算・1人の回数の範囲で）。
  文章から確定できないつながりも「AIの推測」として出し、「未確認」で登録する
- 資料を貼り付ける：説明書・一覧表・会議メモなど。アクセスコードが必要

AIが作ったものは「候補」で、そのまま登録しない。候補には根拠の文（文章からそのまま抜き出した文）が付き、
その文が本当に書いてあるかを Python で照合している。計算は changescope/extraction.py にある。
"""

import uuid
from html import escape

import pandas as pd
import streamlit as st
from streamlit_flow import streamlit_flow
from streamlit_flow.elements import StreamlitFlowEdge, StreamlitFlowNode
from streamlit_flow.layouts import LayeredLayout
from streamlit_flow.state import StreamlitFlowState

from changescope import diagram, models
from changescope.access import check_access_code, load_access_codes
from changescope.ai_client import STORE_DOWN_MESSAGE, AIClient, get_api_key
from changescope.ai_settings import load_settings, model_label
from changescope.datasets import load_from_records, to_records
from changescope.extraction import (
    FEATURE_TEXT, SAMPLE_DOCUMENT, SAMPLE_DOCUMENT_NAME, apply_candidates, extract, load_sample_result,
    mark_registered,
)
from changescope.ui import STATUS_LABELS, ai_button, ai_spinner, get_dataset, html, note, set_dataset, show_mode_banner
from changescope.theme import THEME, diagram_color
from changescope.usage_store import UsageStoreUnavailable, hash_user, open_store

st.title("文章・資料から作る")
show_mode_banner(get_dataset())
settings = load_settings()
store = open_store(settings.usage_db)  # 公開版は外部のデータベース、ローカルはファイル
note("業務の流れを文章で書くか、資料を貼り付けると、AIが<b>図のたたき台</b>（要素とつながりの候補）を作ります。"
     "<b>候補はそのまま登録しません。</b>根拠の文を見て登録するものを選び、「図で入力する」でマウスで直してください。")

dataset = get_dataset()
elements, links = to_records(dataset) if dataset is not None else ([], [])
EXAMPLE_TEXT = ("営業部がCRMを利用して顧客情報を管理している。CRMの受注データは販売管理システムに連携され、"
                "経理部が請求処理を行っている。")
MODES = {"text": f"文章で説明する（アクセスコード不要・{settings.max_free_text_chars:,}文字まで）",
         "document": f"資料を貼り付ける（アクセスコードが必要・{settings.max_document_chars:,}文字まで）"}
NAVY, GOLD, RULE_GRAY = THEME.primary, diagram_color("diagram-accent"), "#8A94A6"  # 図の色はテーマに合わせる


def reset_candidates() -> None:
    for key in ("ex_result", "ex_kind", "ex_info", "ex_source", "ex_preview_key", "ex_preview"):
        st.session_state.pop(key, None)


def free_user_key() -> str:
    """アクセスコードなしで使う人の識別子。画面を開いている間（セッション）ごとに数える。

    公開先（Streamlit Community Cloud）では、利用者のIPアドレスがアプリに届かない（中継サーバーのものになる）ことを
    2026-11-03 に確かめたため、IPアドレスでは数えない。開き直せば回数は戻るが、全員の1日の上限と無料分の予算で止まる。
    """
    st.session_state.setdefault("ex_session_id", uuid.uuid4().hex)
    return hash_user(f"session:{st.session_state.ex_session_id}")


def run_ai(text: str, name: str, user_key: str, mode: str) -> bool:
    """AIで候補を作る。うまくいったら True（失敗したときは理由を表示して False）。"""
    client = AIClient(settings, store, api_key=get_api_key())
    estimate = "30秒前後" if mode == "text" else "1分前後"
    with ai_spinner("AIが文章を読んで、図のたたき台を作っています", estimate):
        result, message = extract(client, text, name, elements, links, user_key, mode=mode)
    if result is None:
        st.warning(message)
        return False
    reset_candidates()
    st.session_state.update(ex_result=result, ex_kind="ai", ex_source=name,
                            ex_info={"model": settings.model, "yen": settings.to_yen(result.cost_usd)})
    return True


# ---------- 1. 文章・資料を入力 ----------
st.markdown("### 1. 文章を書く・資料を貼り付ける")
if dataset is None:
    st.caption("いまは何も登録されていません。選んだ候補で、新しくデータを作ります。")
else:
    st.caption(f"選んだ候補は、いま読み込んでいるデータ（要素 {len(elements)}件・つながり {len(links)}本）に追加します。")
mode = st.radio("使い方", list(MODES), format_func=MODES.get, horizontal=True, key="ex_mode",
                label_visibility="collapsed")

if mode == "text":
    st.button("例文を入れる", on_click=lambda: st.session_state.update(ex_text=EXAMPLE_TEXT))
    text = st.text_area("業務の流れ", key="ex_text", height=140, max_chars=settings.max_free_text_chars,
                        placeholder=f"例：{EXAMPLE_TEXT}")
    st.caption("誰が・どのシステムで・どのデータを・どこへ渡すか、を書くと、図にしやすくなります。"
               "文章からは確定できないつながりも、AIが「推測」として挙げます（「未確認」で登録されます）。"
               "個人情報・機密情報は書かないでください。")
    user_key = free_user_key()
    try:
        left = min(max(0, settings.per_user_monthly_limit - store.user_calls(user_key, FEATURE_TEXT)),
                   max(0, settings.free_daily_limit - store.feature_calls_on(FEATURE_TEXT)))
    except UsageStoreUnavailable:
        left = None  # 回数を確かめられないため、AIは使えなくする
    if ai_button("AIで図のたたき台を作る", key="ai_extract_text", type="primary", icon=":material/auto_awesome:",
                 disabled=not text.strip() or not left):
        if run_ai(text, "", user_key, "text"):
            st.rerun()  # 残りの回数の表示を更新する
    if left is None:
        st.caption(f"{STORE_DOWN_MESSAGE}時間をおいてお試しください。")
    else:
        st.caption(f"あと {left} 回使えます（1人{settings.per_user_monthly_limit}回まで・全員で1日"
                   f"{settings.free_daily_limit}回まで。費用はこのアプリの運営者が負担しています。"
                   "1回あたり約10〜20円の見込み）。")
else:
    if dataset is not None and dataset.source == "sample":
        if st.button("サンプルの資料で試す（料金なし）", icon=":material/description:"):
            st.session_state.ex_document = SAMPLE_DOCUMENT.read_text(encoding="utf-8")
            st.session_state.ex_name = SAMPLE_DOCUMENT_NAME
            result, info = load_sample_result(elements, links)
            reset_candidates()
            st.session_state.update(ex_result=result, ex_kind="sample", ex_info=info, ex_source=SAMPLE_DOCUMENT_NAME)
    else:
        st.caption("サンプルの資料で試すときは、先に「データ管理」でサンプルデータを読み込んでください（料金なし）。")
    source_name = st.text_input("資料の名前（根拠の欄に「資料から抽出（資料の名前）」と記録します）", key="ex_name",
                                placeholder="例：勤怠・給与業務の説明書")
    document = st.text_area("資料の文章", key="ex_document", height=240, max_chars=settings.max_document_chars,
                            placeholder="資料の文章や、Excelの表をコピーして貼り付けてください。"
                                        "個人情報・機密情報は貼り付けないでください。")
    access_codes = load_access_codes()
    with st.container(border=True):
        if not access_codes:
            st.caption("この環境では、資料からの作成（アクセスコードが必要）は設定されていません。")
        else:
            code = st.text_input("アクセスコード", type="password", key="ex_access_code")
            if ai_button("AIで候補を作る", key="ai_extract_document", type="primary", icon=":material/auto_awesome:",
                         disabled=not document.strip()):
                user_key = check_access_code(code, access_codes)
                if user_key is None:
                    st.error("アクセスコードが正しくありません。")
                else:
                    run_ai(document, source_name.strip(), user_key, "document")

result = st.session_state.get("ex_result")
if result is None:
    st.stop()
mark_registered(result, elements, links)  # データが変わっていても、「登録済み」の印をいまのデータに合わせる

# ---------- 2. 候補を選ぶ ----------
st.divider()
st.markdown("### 2. 図のたたき台を確かめ、登録するものを選ぶ")
info = st.session_state.get("ex_info", {})
if st.session_state.get("ex_kind") == "sample":
    note(f"<b>AIによる候補のサンプル</b>　架空の資料「{escape(info.get('document', ''))}」を、事前にAIで読み込んだ結果です"
         f"（{escape(info.get('generated_on', ''))}、{escape(model_label(info.get('model', '')))}）。"
         "いま実行したAIの結果ではありません。")
else:
    note(f"<b>AIによる候補</b>（{escape(model_label(info.get('model', '')))}）　今回の費用（試算）：約{info.get('yen', 0):.1f}円")


def link_state(link) -> str:
    if link.duplicate:
        return "登録済み"
    if link.inferred:
        return "未確認（AIの推測）"
    if not link.found:
        return "根拠が見つからない"
    if link.reversed_registered:
        return "逆向きが登録済み（どちらかの向きが誤りかも）"
    return "推定（文章に書いてある）"


def element_state(element) -> str:
    if element.existing_id:
        return "登録済み"
    return "新規" if element.found else "根拠が見つからない"


new_links = [l for l in result.links if not l.duplicate]
c1, c2, c3, c4 = st.columns(4)
c1.metric("要素の候補", f"{len(result.elements)} 件")
c2.metric("つながりの候補", f"{len(new_links)} 本", help="まだ登録されていないつながり（登録済みのものは除く）")
c3.metric("うちAIの推測", f"{sum(l.inferred for l in new_links)} 本",
          help="文章からは確定できず、AIが推測したつながり。「未確認」で登録し、図では点線になります")
c4.metric("分からないこと", f"{len(result.unclear)} 件", help="文章からは分からず、確認が必要なこと")

tab_links, tab_elements, tab_unclear = st.tabs([
    f"つながりの候補（{len(new_links)}）", f"要素の候補（{len(result.elements)}）", f"分からないこと（{len(result.unclear)}）",
])
with tab_links:
    st.caption("最初は、文章に書いてあるつながりと、AIの推測を選んだ状態にしています（根拠が見つからないものと登録済みは外しています）。"
               "書いてあるつながりは「推定」、AIの推測は「未確認」で登録します。")
    show_registered = st.toggle("登録済みのつながりも表示する", value=False)
    shown = [l for l in result.links if show_registered or not l.duplicate]
    links_table = st.data_editor(
        pd.DataFrame({
            "登録する": [(l.found or l.inferred) and not l.duplicate for l in shown],
            "つながり（読み方）": [diagram.reading(l.source, l.target, l.relation_type) for l in shown],
            "状態": [link_state(l) for l in shown],
            "根拠の文": [l.quote for l in shown],
        }),
        hide_index=True, width="stretch", key=f"ex_links_{show_registered}",
        disabled=["つながり（読み方）", "状態", "根拠の文"],
        column_config={"登録する": st.column_config.CheckboxColumn(width=110),
                       "つながり（読み方）": st.column_config.TextColumn(width="large"),
                       "根拠の文": st.column_config.TextColumn(width="large")},
    )
    chosen_links = [l for l, keep in zip(shown, links_table["登録する"]) if keep and not l.duplicate]
with tab_elements:
    st.caption("つながりを登録すると、その両端の要素も自動で登録されます。ここでは、つながりのない要素も登録したいときに選びます。"
               "種類が違っていたら直せます。名前を直したいときは、登録したあとに「図で入力する」で直してください。")
    type_labels = list(models.ELEMENT_TYPES.values())
    elements_table = st.data_editor(
        pd.DataFrame({
            "登録する": [e.found and not e.existing_id for e in result.elements],
            "名前": [e.name for e in result.elements],
            "種類": [models.element_type_label(e.element_type) for e in result.elements],
            "根拠の文": [e.quote for e in result.elements],
            "状態": [element_state(e) for e in result.elements],
        }),
        hide_index=True, width="stretch", key="ex_elements",
        disabled=["名前", "根拠の文", "状態"],
        column_config={"登録する": st.column_config.CheckboxColumn(width=110),
                       "種類": st.column_config.SelectboxColumn(options=type_labels, required=True),
                       "根拠の文": st.column_config.TextColumn(width="large")},
    )
    label_to_code = {label: code for code, label in models.ELEMENT_TYPES.items()}
    for candidate, label in zip(result.elements, elements_table["種類"]):
        candidate.element_type = label_to_code.get(label, candidate.element_type)  # 直した種類を使う
    chosen_elements = [e for e, keep in zip(result.elements, elements_table["登録する"]) if keep and not e.existing_id]
with tab_unclear:
    if result.unclear:
        st.caption("文章からは分からず、影響を調べるために確認が必要なことです。ヒアリングの質問として使ってください。")
        html("".join(
            f'<div class="cs-finding"><div class="cs-finding-title">{escape(u["point"])}</div>'
            f'<div class="cs-finding-items">確認先：{escape(u["ask"] or "未定")}</div></div>'
            for u in result.unclear))
    else:
        st.write("分からないことは、挙がりませんでした。")

# ---------- 図のたたき台（選んだつながりだけを描く。見るための図） ----------
st.markdown("#### 図のたたき台（選んだつながり）")
types = {e.name: e.element_type for e in result.elements}
types.update({e["name"]: e["element_type"] for e in elements})
names_in_draft = list(dict.fromkeys([n for l in chosen_links for n in (l.source, l.target)]
                                    + [e.name for e in chosen_elements]))
if not names_in_draft:
    st.caption("つながりの候補を選ぶと、ここに図が出ます。")
else:
    preview_key = tuple(sorted((l.source, l.target, l.relation_type) for l in chosen_links)) + tuple(names_in_draft)
    if st.session_state.get("ex_preview_key") != preview_key:  # 選び方が変わったときだけ作る（毎回作ると点滅する）
        node_id = {name: f"p{i}" for i, name in enumerate(names_in_draft)}
        nodes = [StreamlitFlowNode(
            node_id[name], (0, 0), {"content": f"{name}  \n{models.element_type_label(types.get(name, ''))}"},
            node_type="default", source_position="right", target_position="left", draggable=False, selectable=False,
            connectable=False,
            style={"background": "#FFFFFF" if types.get(name) == diagram.RULE else NAVY,
                   "color": NAVY if types.get(name) == diagram.RULE else "#FFFFFF",
                   "border": f"2px solid {RULE_GRAY if types.get(name) == diagram.RULE else GOLD}",
                   "borderRadius": "6px", "fontSize": "12px", "fontWeight": "bold", "width": "190px"})
            for name in names_in_draft]
        edges = []
        for i, l in enumerate(chosen_links):
            status = "unconfirmed" if l.inferred else "assumed"
            edges.append(StreamlitFlowEdge(
                f"e{i}", node_id[l.source], node_id[l.target], edge_type="default",
                marker_end={"type": "arrowclosed", "color": GOLD, "width": 18, "height": 18},
                style={"stroke": GOLD, "strokeWidth": 2.5, "strokeDasharray": "7 5"},
                label=f"{models.relation_type_label(l.relation_type)}・{STATUS_LABELS[status]}", label_show_bg=True,
                label_style={"fill": NAVY, "fontSize": 11, "fontWeight": 700},
                label_bg_style={"fill": "#F3E6C4" if l.inferred else GOLD}))
        st.session_state.ex_preview_key = preview_key
        st.session_state.ex_preview = StreamlitFlowState(nodes=nodes, edges=edges)
    st.caption("配置は自動です。AIの候補は確かめる前なので、すべて点線（推定・未確認）で表示します。"
               "マウスのホイールで拡大縮小、ドラッグで移動できます。")
    streamlit_flow(f"ex_preview_{len(preview_key)}", st.session_state.ex_preview, height=420, fit_view=True,
                   layout=LayeredLayout(direction="right", node_node_spacing=30, node_layer_spacing=90),
                   allow_new_edges=False, show_controls=True, allow_zoom=True, min_zoom=0.2, pan_on_drag=True,
                   hide_watermark=True, style={"border": f"2px solid {NAVY}", "borderRadius": "6px",
                                               "background": "#FFFFFF"})

# ---------- 3. 登録する ----------
st.divider()
st.markdown("### 3. 登録して、図で直す")
st.write(f"つながり **{len(chosen_links)}本**、要素 **{len(chosen_elements)}件** を登録します"
         "（つながりの両端の要素で、まだ登録されていないものも一緒に登録します）。"
         "登録すると「図で入力する」が開くので、マウスで直してください。")
if st.button("登録して図で直す", type="primary", icon=":material/account_tree:",
             disabled=not chosen_links):
    new_elements, new_link_records = apply_candidates(elements, links, chosen_elements, chosen_links,
                                                      st.session_state.get("ex_source", ""))
    loaded = load_from_records(new_elements, new_link_records)
    if loaded.dataset is None:
        st.error("登録できませんでした。")
        st.markdown("\n".join(f"- {e}" for e in loaded.errors[:20]))
    else:
        set_dataset(loaded.dataset)
        # 「図で入力する」を開いたとき、登録した最初の要素を真ん中にして開く
        first = next(e["element_id"] for e in new_elements if e["name"] == chosen_links[0].source)
        st.session_state.open_in_diagram = first
        st.session_state.toast_after_open = (f"要素 {len(new_elements) - len(elements)}件・"
                                             f"つながり {len(new_link_records) - len(links)}本を登録しました。")
        reset_candidates()
        st.switch_page("pages/diagram.py")
