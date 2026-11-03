"""図で入力する画面：ヒアリングしながら、要素とつながりを図で登録する。

いま見ている要素を真ん中に置き、左に影響元、右に影響先（2段先まで）を並べる。
図で変えた内容は、そのたびに Excel と同じ検証を通して分析用のデータにする（影響分析にそのまま使える）。
計算（配置・データのまとめ・関係の自動選択など）は changescope/diagram.py にある。

図の部品（streamlit-flow）の注意：
- 部品の戻り値で図を上書きしない。図の内容は Python 側の一覧を正とし、戻り値は「クリックされた」
  「線が引かれた」という出来事としてだけ使う（timestamp が処理済みより新しいときだけ処理する）
- 図の状態は内容が変わったときだけ作り、session_state に保存して使い回す（毎回作ると点滅する）
"""

import uuid
from datetime import date
from html import escape

import pandas as pd
import streamlit as st
from streamlit_flow import streamlit_flow
from streamlit_flow.elements import StreamlitFlowEdge, StreamlitFlowNode
from streamlit_flow.layouts import LayeredLayout
from streamlit_flow.state import StreamlitFlowState

from changescope import diagram, models
from changescope.datasets import load_from_records, to_records
from changescope.excel_template import build_template
from changescope.theme import THEME
from changescope.ui import STATUS_LABELS, data_table, get_dataset, note, set_dataset

st.title("図で入力する")

# ---------- 見た目 ----------
NODE_W, NODE_H, ROW_GAP = 230, 58, 22
COLUMN_X = {"left": 0, "center": 420, "first": 880, "second": 1340}  # 線の上の文字が収まるよう、列の間を空ける
# 濃い色と差し色はテーマ（changescope/theme.py）に合わせる。規程の灰色・まとめたデータの青は、意味を表す色なので固定
NAVY, GOLD, RULE_GRAY, DATA_BLUE = THEME.primary, THEME.accent, "#8A94A6", "#2E5E8C"
BASE = {"borderRadius": "6px", "padding": "4px 10px", "fontSize": "13px", "lineHeight": "1.35",
        "width": f"{NODE_W}px", "height": f"{NODE_H}px", "boxSizing": "border-box", "display": "flex",
        "alignItems": "center", "justifyContent": "center", "overflow": "hidden"}
NEIGHBOR_STYLE = {**BASE, "background": NAVY, "color": "#FFFFFF", "border": f"2px solid {GOLD}", "fontWeight": "bold"}
UNCERTAIN_STYLE = {**NEIGHBOR_STYLE, "border": f"2px dashed {GOLD}"}  # 推定・未確認のつながりの相手
RULE_STYLE = {**BASE, "background": "#FFFFFF", "color": NAVY, "border": f"2px solid {RULE_GRAY}", "fontWeight": "bold"}
CENTER_H = 72
CENTER_STYLE = {**BASE, "background": GOLD, "color": NAVY, "border": f"3px solid {NAVY}", "fontWeight": "bold",
                "fontSize": "15px", "width": "260px", "height": f"{CENTER_H}px"}
EMPTY_STYLE = {**BASE, "background": "#F4F1E8", "color": "#8A94A6", "border": "1px dashed #DDD8CC"}
CANVAS_STYLE = {"border": f"2px solid {NAVY}", "borderRadius": "6px", "background": "#FFFFFF"}
VIEWS = ["つながりを入力する", "全体図（見る）"]
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


# 線をつなぐ ●（接続点）を大きくする。図の部品は別の枠（iframe）の中に描かれ、●の大きさを変える設定がないため、
# 外から部品の枠に CSS を1つ足す。部品の作り（.react-flow__handle という名前）に依存するので、部品を更新して
# 効かなくなっても、画面は動く（●が標準の6pxに戻るだけ）。枠は図を描き直すと作り直されるため、定期的に確かめる。
HANDLE_SIZE_PX = 15  # 標準の6pxの2.5倍
st.html(f"""<script>
if (!window.csHandleTimer) {{
  window.csHandleTimer = setInterval(() => {{
    for (const frame of document.querySelectorAll("iframe")) {{
      try {{
        const doc = frame.contentDocument;
        if (!doc || !doc.querySelector(".react-flow") || doc.getElementById("cs-handle-style")) continue;
        const style = doc.createElement("style");
        style.id = "cs-handle-style";
        style.textContent = `.react-flow__handle {{ width: {HANDLE_SIZE_PX}px; height: {HANDLE_SIZE_PX}px;
          background: {GOLD}; border: 2px solid #fff; box-shadow: 0 0 0 1px {NAVY}; }}`;
        doc.head.appendChild(style);
      }} catch (e) {{}}  // 別のサイトの枠には触れない（触れられない）
    }}
  }}, 500);
}}
</script>""", unsafe_allow_javascript=True)


# ---------- 図で編集しているデータ ----------
def start_editing(elements: list[dict], links: list[dict], tutorial: int | None) -> None:
    """図での編集を始める（前の編集状態は消す）。"""
    for key in [k for k in st.session_state if str(k).startswith("dg_")]:
        del st.session_state[key]
    st.session_state.update(dg_elements=elements, dg_links=links, dg_tutorial=tutorial, dg_trail=[],
                            dg_synced=get_dataset(), dg_view=VIEWS[0])
    if elements:
        # いちばんつながりの多い要素から見始める（図は、表示するときに作る）
        counts = {e["element_id"]: 0 for e in elements}
        for link in links:
            for end in (link["from_id"], link["to_id"]):
                counts[end] = counts.get(end, 0) + 1
        first = max(counts, key=counts.get)
        st.session_state.update(dg_center=first, dg_trail=[first])


def commit() -> None:
    """図での変更を、分析用のデータに反映する（Excelと同じ検証を通す）。"""
    if not links:
        # つながりが1本もないと分析できないため、分析用のデータは空にしておく
        st.session_state.pop("dataset", None)
        st.session_state.dg_synced = None
        return
    result = load_from_records(elements, links)
    if result.dataset is None:  # 画面側で確かめてから変えているので、通常は起きない
        st.session_state.dg_errors = result.errors
        return
    set_dataset(result.dataset)
    st.session_state.dg_synced = result.dataset
    st.session_state.pop("dg_errors", None)


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:6].upper()}"


def set_center(element_id: str) -> None:
    st.session_state.dg_center = element_id
    st.session_state.dg_flow = build_state(element_id)
    st.session_state.dg_trail = diagram.update_trail(st.session_state.get("dg_trail", []), element_id)


def type_options() -> list[str]:
    """種類の選択肢（もとからある種類＋データに含まれる、利用者が追加した種類）。"""
    extra = sorted({e["element_type"] for e in st.session_state.get("dg_elements", [])} - set(models.ELEMENT_TYPES))
    return [*models.ELEMENT_TYPES, *extra]


def relation_options() -> list[str]:
    extra = sorted({l["relation_type"] for l in st.session_state.get("dg_links", [])} - set(models.RELATION_TYPES))
    return [*models.RELATION_TYPES, *extra]


def name_error(name: str, element_id: str | None = None) -> str | None:
    name = name.strip()
    if not name:
        return "名前を入力してください。"
    if name in {e["name"] for e in elements if e["element_id"] != element_id}:
        return f"「{name}」はすでにあります。同じ名前の要素は登録できません。"
    return None


def add_element(name: str, element_type: str) -> str:
    element_id = new_id("E")
    elements.append({"element_id": element_id, "name": name.strip(), "element_type": element_type, "owner": ""})
    return element_id


def add_link(source: str, target: str, relation_type: str, status: str, evidence: str,
             direction: str = "one_way") -> None:
    links.append({"dependency_id": new_id("D"), "from_id": source, "to_id": target, "relation_type": relation_type,
                  "direction": direction, "evidence": evidence.strip() or diagram.NO_EVIDENCE, "status": status,
                  "note": ""})


# ---------- 図の部品に渡す形にする ----------
def edge_label(link: dict) -> dict:
    """線の上の文字（関係の種類・確認状態）。推定・未確認は金の地で目立たせ、まとめたデータは青い地にする。"""
    uncertain = link["status"] != "confirmed"
    background = GOLD if uncertain else DATA_BLUE if link.get("via") else NAVY
    relation = link["relation_type"] if link.get("via") else models.relation_type_label(link["relation_type"])
    return {"label": f"{relation}・{STATUS_LABELS.get(link['status'], link['status'])}", "label_show_bg": True,
            "label_style": {"fill": NAVY if uncertain else "#FFFFFF", "fontSize": 11, "fontWeight": 700},
            "label_bg_style": {"fill": background}}


def edge_style(link: dict) -> dict:
    """推定・未確認の線は点線（このツールでいちばん見つけたいもの）。規程とのつながりは灰色。"""
    rule = diagram.RULE in (types.get(link["from_id"]), types.get(link["to_id"]))
    color = RULE_GRAY if rule else GOLD
    arrow = {"type": "arrowclosed", "color": color, "width": 20, "height": 20}
    style = {"stroke": color, "strokeWidth": 2}
    if link["status"] != "confirmed":
        style.update(strokeDasharray="7 5", strokeWidth=2.5)
    return {"marker_end": arrow, "marker_start": arrow if link.get("direction") == "both" else {}, "style": style}


def box_label(element_id: str) -> str:
    return f"{names[element_id]}  \n{models.element_type_label(types[element_id])}"


def refresh_lookups() -> None:
    """名前・種類の対応表を、いまの要素の一覧に合わせる（要素を追加・変更した直後に図を作るため）。"""
    names.clear()
    names.update({e["element_id"]: e["name"] for e in st.session_state.dg_elements})
    types.clear()
    types.update({e["element_id"]: e["element_type"] for e in st.session_state.dg_elements})


def build_state(center: str) -> StreamlitFlowState:
    refresh_lookups()
    result = diagram.layout(st.session_state.dg_elements, st.session_state.dg_links, center,
                            st.session_state.get("dg_collapse", False))
    height = result.rows * (NODE_H + ROW_GAP) - ROW_GAP
    st.session_state.dg_height = max(260, height + 60)
    per_column = {c: sum(p.column == c for p in result.placements) + (1 if c in result.hidden else 0)
                  for c in COLUMN_X}
    nodes, node_of = [], {}
    for p in result.placements:
        if p.column == "center":
            nodes.append(StreamlitFlowNode(
                f"c:{center}", (COLUMN_X["center"], (height - CENTER_H) / 2), {"content": box_label(center)},
                node_type="default", source_position="right", target_position="left", draggable=False,
                selectable=True, connectable=True, style=dict(CENTER_STYLE)))
            node_of[center] = f"c:{center}"
            continue
        top = (height - (per_column[p.column] * (NODE_H + ROW_GAP) - ROW_GAP)) / 2
        if types[p.element_id] == diagram.RULE:
            style = RULE_STYLE
        elif p.link["status"] != "confirmed":
            style = UNCERTAIN_STYLE
        else:
            style = NEIGHBOR_STYLE
        nodes.append(StreamlitFlowNode(
            f"n:{p.element_id}", (COLUMN_X[p.column], top + p.row * (NODE_H + ROW_GAP)),
            {"content": box_label(p.element_id)}, node_type="default", source_position="right",
            target_position="left", draggable=False, selectable=True, connectable=True, style=dict(style)))
        node_of[p.element_id] = f"n:{p.element_id}"
    for column, count in result.hidden.items():
        top = (height - (per_column[column] * (NODE_H + ROW_GAP) - ROW_GAP)) / 2
        row = per_column[column] - 1
        nodes.append(StreamlitFlowNode(
            f"more:{column}", (COLUMN_X[column], top + row * (NODE_H + ROW_GAP)),
            {"content": f"ほか {count} 件  \n左の検索から選べます"}, node_type="default", draggable=False,
            selectable=False, connectable=False, style=dict(EMPTY_STYLE)))
    for column, label in (("left", "影響元はまだありません"), ("first", "影響先はまだありません")):
        if per_column[column] == 0:
            nodes.append(StreamlitFlowNode(
                f"empty:{column}", (COLUMN_X[column], (height - NODE_H) / 2), {"content": label},
                node_type="default", draggable=False, selectable=False, connectable=False, style=dict(EMPTY_STYLE)))
    edges = [StreamlitFlowEdge(f"edge:{l['dependency_id']}", node_of[l["from_id"]], node_of[l["to_id"]],
                               edge_type="default", **edge_style(l), **edge_label(l))
             for l in result.edges]
    return StreamlitFlowState(nodes=nodes, edges=edges)


def node_element(node_id: str) -> str:
    return node_id.split(":", 1)[1]


# ---------- 最初の画面：どのデータを図で扱うか ----------
dataset = get_dataset()
editing = "dg_elements" in st.session_state
if editing and dataset is not st.session_state.get("dg_synced"):
    # 「データ管理」で別のデータを読み込んだなど、図で編集していたものと分析用のデータが変わった
    st.info("分析用のデータが入れ替わったため、図での編集を最初からやり直します。")
    editing = False
    for key in [k for k in st.session_state if str(k).startswith("dg_")]:
        del st.session_state[key]

# 「文章・資料から作る」の「登録して図で直す」から来たときは、登録した要素を真ん中にして、すぐ開く
open_request = st.session_state.pop("open_in_diagram", None)
if open_request and dataset is not None:
    start_editing(*to_records(dataset), tutorial=None)
    if any(e["element_id"] == open_request for e in st.session_state.dg_elements):
        st.session_state.update(dg_center=open_request, dg_trail=[open_request])
    editing = True
if st.session_state.get("toast_after_open"):
    st.toast(st.session_state.pop("toast_after_open"))

if not editing:
    st.write("ヒアリングしながら、業務・システム・部門などのつながりを図で登録します。どちらから始めますか？")
    c1, c2 = st.columns(2)
    with c1, st.container(border=True):
        st.markdown("**新しく作る（はじめての方におすすめ）**")
        st.caption("何もない状態から、1つずつ案内に沿って作ります。要素を1つ → もう1つ → 2つの関係、の順に進みます。")
        if dataset is not None:
            st.caption("※ いま読み込んでいるデータは、分析に使われなくなります（Excelに保存していない内容は消えます）。")
        if st.button("新しく作る", type="primary", width="stretch"):
            st.session_state.pop("dataset", None)
            start_editing([], [], tutorial=1)
            st.rerun()
    with c2, st.container(border=True):
        if dataset is not None:
            source = "架空サンプルデータ" if dataset.source == "sample" else "読み込んでいるデータ"
            st.markdown(f"**{source}を図で見る・直す**")
            st.caption(f"要素 {len(dataset.elements)} 件・つながり {len(dataset.dependencies)} 本を、図で確認・追加・修正します。")
            if st.button("図で開く", width="stretch"):
                start_editing(*to_records(dataset), tutorial=None)
                st.rerun()
        else:
            st.markdown("**サンプルや自分のExcelを図で見る**")
            st.caption("先に「データ管理」でサンプルデータかExcelを読み込むと、ここから図で開けます。")
            st.page_link("pages/data.py", label="データ管理へ", icon=":material/folder_open:")
    st.caption("業務の流れを文章で書いて、AIに図のたたき台を作ってもらうこともできます（アクセスコード不要）。"
               "作ったたたき台は、この画面でマウスで直せます。")
    st.page_link("pages/extract.py", label="文章・資料から作る", icon=":material/auto_awesome:")
    st.stop()

elements: list[dict] = st.session_state.dg_elements
links: list[dict] = st.session_state.dg_links
names = {e["element_id"]: e["name"] for e in elements}
types = {e["element_id"]: e["element_type"] for e in elements}
connected = {l["from_id"] for l in links} | {l["to_id"] for l in links}
center = st.session_state.get("dg_center")
if center not in names:
    center = elements[0]["element_id"] if elements else None
if st.session_state.get("dg_toast"):
    st.toast(st.session_state.pop("dg_toast"))
for error in st.session_state.get("dg_errors", []):
    st.error(error)

note("<b>図で作った内容は、このページを閉じると消えます。</b>残したいときは、下の「Excelに保存する」を押してください。"
     "保存したExcelは、「データ管理」から読み込むと続きを編集できます。分析には、そのまま使えます（「影響分析」）。")
c_back, c_save, _ = st.columns([1, 1, 2])
if c_back.button("最初の画面に戻る", icon=":material/arrow_back:", width="stretch"):
    for key in [k for k in st.session_state if str(k).startswith("dg_")]:
        del st.session_state[key]
    st.rerun()
synced = st.session_state.get("dg_synced")
if synced is None:
    c_save.button("Excelに保存する", icon=":material/download:", disabled=True, width="stretch",
                  help="つながりを1本以上作ると保存できます。")
else:
    # Excelを作るのは、データが変わったときだけ（画面を更新するたびに作ると遅くなるため）
    if st.session_state.get("dg_excel_for") is not synced:
        st.session_state.dg_excel = build_template(synced.elements, synced.dependencies)
        st.session_state.dg_excel_for = synced
    c_save.download_button("Excelに保存する", st.session_state.dg_excel,
                           f"ChangeScope_図で作成_{date.today():%Y%m%d}.xlsx", XLSX_MIME, type="primary",
                           icon=":material/download:", width="stretch")


# ---------- ダイアログ ----------
def type_label(code: str) -> str:
    return models.element_type_label(code)


@st.dialog("つながりを追加", width="large", on_dismiss=lambda: st.session_state.update(dg_pending=None))
def add_links_dialog(side: str, question: diagram.Question | None = None) -> None:
    title = "影響元（この要素に影響を与えるもの）" if side == "in" else "影響先（この要素が変わると影響を受けるもの）"
    st.markdown(f"いま見ている要素：**{names[center]}**　→　追加するもの：**{title}**")
    # ヒアリングの質問：何を聞けばよいかの例を、追加しようとしたときだけ見せる（聞き漏れを防ぐ）
    examples = [q for q in diagram.QUESTIONS.get(types[center], []) if q.side == side]
    if examples:
        st.caption("たとえば、こんなことを聞いてみましょう（押すと、答えに合う種類を選んだ状態になります）")
        with st.container(horizontal=True, gap="small"):
            for q in examples:
                label = q.text + ("" if diagram.is_answered(q, center, links) else "（未回答）")
                if st.button(label, key=f"ask_{q.text}", type="primary" if q == question else "secondary"):
                    st.session_state.dg_pending = (side, q)
                    st.rerun()
    already = ({l["from_id"] for l in links if l["to_id"] == center} if side == "in"
               else {l["to_id"] for l in links if l["from_id"] == center})
    candidates = [e["element_id"] for e in elements if e["element_id"] != center and e["element_id"] not in already]
    type_codes = type_options()
    relation_codes = ["auto", *relation_options()]
    with st.form("dg_add_links_form"):
        st.markdown("**新しい要素を作ってつなぐ**（名前を1行に1つずつ書くと、まとめて作れます）")
        c1, c2 = st.columns([2, 1])
        new_names = c1.text_area("新しい要素の名前（1行に1つ）", height=100)
        new_type = c2.selectbox("種類", type_codes, format_func=type_label,
                                index=type_codes.index(question.element_type) if question else 0)
        picked = st.multiselect("または、登録済みの要素から選ぶ（複数選べます）", candidates,
                                format_func=lambda i: f"{names[i]}（{type_label(types[i])}）")
        relation = st.selectbox("関係の種類（「自動」は2つの要素の種類から選びます）", relation_codes,
                                index=relation_codes.index(question.relation_type) if question else 0,
                                format_func=lambda r: "（自動）" if r == "auto" else diagram.relation_option(r))
        c3, c4 = st.columns(2)
        direction = c3.radio("影響の向き", list(models.DIRECTIONS), format_func=models.DIRECTIONS.get, horizontal=True)
        status = c4.radio("確認状態", list(models.STATUSES), index=list(models.STATUSES).index("unconfirmed"),
                          format_func=STATUS_LABELS.get, horizontal=True)
        evidence = st.text_input("根拠（資料名・ヒアリング相手など）")
        b1, b2 = st.columns(2)
        add = b1.form_submit_button("追加", type="primary", width="stretch")
        cancel = b2.form_submit_button("やめる", width="stretch")
    if cancel:
        st.session_state.dg_pending = None
        st.rerun()
    if add:
        lines = list(dict.fromkeys(n.strip() for n in new_names.splitlines() if n.strip()))
        errors = [error for n in lines if (error := name_error(n))]
        if errors:
            st.error(errors[0])
            return
        targets = picked + [add_element(n, new_type) for n in lines]
        refresh_lookups()
        if not targets:
            st.error("新しい要素の名前を入力するか、登録済みの要素を選んでください。")
            return
        added = []
        for other in targets:
            source, target = (other, center) if side == "in" else (center, other)
            rel = relation if relation != "auto" else diagram.default_relation(types[source], types[target])
            add_link(source, target, rel, status, evidence, direction)
            added.append(diagram.reading(names[source], names[target], rel))
        commit()
        # 登録した内容を文章で知らせる（違っていたら、線をクリックして直せる）
        st.session_state.dg_toast = "追加しました：" + "／".join(added)
        st.session_state.dg_pending = None
        set_center(center)
        st.rerun()


@st.dialog("線をつなぐ", width="medium", on_dismiss=lambda: st.session_state.pop("dg_flow", None))
def draw_link_dialog(source: str, target: str) -> None:
    """図の上でドラッグして引いた線を、つながりとして登録する。"""
    st.markdown(f"**{names[source]}** → **{names[target]}**")
    st.caption("矢印は「左が変わると、右に影響する」向きです。")
    if any(l["from_id"] == source and l["to_id"] == target for l in links):
        st.info("この2つは、すでにこの向きでつながっています。")
        if st.button("閉じる"):
            set_center(center)
            st.rerun()
        return
    # 経由する流れにしたとき、いま見ている要素から直接引かれていた線（例：システム → 経理部）
    direct = diagram.direct_links_to_replace(links, center, source, target)
    codes = relation_options()
    relation = st.selectbox("関係の種類", codes, format_func=diagram.relation_option,
                            index=codes.index(diagram.default_relation(types[source], types[target])))
    st.info(diagram.reading(names[source], names[target], relation), icon=":material/menu_book:")
    with st.form("dg_draw_link_form"):
        status = st.radio("確認状態", list(models.STATUSES), index=list(models.STATUSES).index("assumed"),
                          format_func=STATUS_LABELS.get, horizontal=True,
                          captions=[diagram.STATUS_HELP[s] for s in models.STATUSES])
        evidence = st.text_input("根拠（任意）")
        remove_direct = False
        if direct:
            remove_direct = st.checkbox(
                f"「{names[center]} → {names[target]}」の直接の線を消す（「{names[source]}」を経由する流れにする）",
                value=True)
        b1, b2 = st.columns(2)
        add = b1.form_submit_button("つなぐ", type="primary", width="stretch")
        cancel = b2.form_submit_button("やめる", width="stretch")
    if add:
        add_link(source, target, relation, status, evidence)
        if remove_direct:
            for link in direct:
                links.remove(link)
        commit()
    if add or cancel:
        set_center(center)  # 引いた線は、登録した内容から図を作り直して表す（やめたときは消える）
        st.rerun()


@st.dialog("つながりを編集", width="medium")
def edit_link_dialog(dependency_id: str) -> None:
    link = next(l for l in links if l["dependency_id"] == dependency_id)
    st.markdown(f"影響元 **{names[link['from_id']]}** → 影響先 **{names[link['to_id']]}**")
    codes = relation_options()
    relation = st.selectbox("関係の種類", codes, index=codes.index(link["relation_type"]),
                            format_func=diagram.relation_option)
    st.info(diagram.reading(names[link["from_id"]], names[link["to_id"]], relation), icon=":material/menu_book:")
    with st.form("dg_edit_link_form"):
        c1, c2 = st.columns(2)
        directions, statuses = list(models.DIRECTIONS), list(models.STATUSES)
        direction = c1.radio("影響の向き", directions, index=directions.index(link["direction"]),
                             format_func=models.DIRECTIONS.get, horizontal=True)
        status = c2.radio("確認状態", statuses, index=statuses.index(link["status"]),
                          format_func=STATUS_LABELS.get, horizontal=True)
        evidence = st.text_input("根拠", value=link["evidence"])
        swap = st.checkbox("影響元と影響先を入れ替える")
        b1, b2 = st.columns(2)
        update = b1.form_submit_button("この内容で更新", type="primary", width="stretch")
        delete = b2.form_submit_button("このつながりを削除", width="stretch")
    if update:
        link.update(relation_type=relation, direction=direction, status=status,
                    evidence=evidence.strip() or diagram.NO_EVIDENCE)
        if swap:
            link["from_id"], link["to_id"] = link["to_id"], link["from_id"]
    elif delete:
        links.remove(link)
    if update or delete:
        commit()
        set_center(center)
        st.rerun()


@st.dialog("要素を編集", width="medium")
def edit_element_dialog(element_id: str) -> None:
    element = next(e for e in elements if e["element_id"] == element_id)
    count = sum(element_id in (l["from_id"], l["to_id"]) for l in links)
    st.caption(f"この要素のつながり：{count}本")
    type_codes = type_options()
    # 責任部門・担当は、影響を受ける部門（関係者）や見落としやすい影響の判定に使う
    owners = ["", *[e["element_id"] for e in elements if e["element_type"] in diagram.PEOPLE and e is not element]]
    owner = element.get("owner", "")
    with st.form("dg_edit_element_form"):
        name = st.text_input("名前", value=element["name"])
        element_type = st.selectbox("種類", type_codes, index=type_codes.index(element["element_type"]),
                                    format_func=type_label)
        owner = st.selectbox("責任部門・担当", owners, index=owners.index(owner) if owner in owners else 0,
                             format_func=lambda i: names.get(i, "（なし）") if i else "（なし）",
                             help="誰に影響するか・見落としやすい影響の判定に使います。部門や担当者を先に登録すると選べます。")
        b1, b2 = st.columns(2)
        update = b1.form_submit_button("この内容で更新", type="primary", width="stretch")
        delete = b2.form_submit_button("この要素を削除", width="stretch")
    if update:
        if error := name_error(name, element_id):
            st.error(error)
            return
        element.update(name=name.strip(), element_type=element_type, owner=owner)
    elif delete:
        elements.remove(element)
        links[:] = [l for l in links if element_id not in (l["from_id"], l["to_id"])]
        for e in elements:  # 削除した要素を責任部門にしていた要素は、責任部門を空にする
            if e.get("owner") == element_id:
                e["owner"] = ""
    if update or delete:
        commit()
        if delete:
            st.session_state.pop("dg_center", None)
            st.session_state.pop("dg_flow", None)
        else:
            set_center(element_id)
        st.rerun()


# ---------- チュートリアル（新しく作る）：1画面に1つのことだけを案内する ----------
def tutorial_box(node_id: str, label: str, x: float, style: dict, node_type: str = "default",
                 connectable: bool = False) -> StreamlitFlowNode:
    # 箱の高さが違っても上下の中央がそろうよう、真ん中の要素の箱との差の半分だけ下げる
    y = (CENTER_H - int(style["height"].removesuffix("px"))) / 2
    return StreamlitFlowNode(node_id, (x, y), {"content": label}, node_type=node_type, source_position="right",
                             target_position="left", draggable=False, selectable=False, connectable=connectable,
                             style=dict(style))


def connect_state(drawn: bool) -> StreamlitFlowState:
    """ステップ3の図。左の箱は右端の●だけ、右の箱は左端の●だけにして、左→右にしか線を引けないようにする。"""
    first, second = elements[0]["element_id"], elements[1]["element_id"]
    nodes = [tutorial_box("t1", box_label(first), 0, CENTER_STYLE, "input", not drawn),
             tutorial_box("t2", box_label(second), 420, NEIGHBOR_STYLE, "output", not drawn)]
    edges = []
    if drawn:
        arrow = {"type": "arrowclosed", "color": GOLD, "width": 20, "height": 20}
        edges.append(StreamlitFlowEdge("te", "t1", "t2", edge_type="default", marker_end=arrow,
                                       style={"stroke": GOLD, "strokeWidth": 2}))
    return StreamlitFlowState(nodes=nodes, edges=edges)


def tutorial_figure(step: int) -> None:
    """チュートリアル中の図。今のステップで必要な箱だけを置く。"""
    nodes = []
    if elements:
        nodes.append(tutorial_box("t1", box_label(elements[0]["element_id"]), 0, CENTER_STYLE))
    if step == 2:
        nodes.append(tutorial_box("t2", "次の要素がここに入ります", 420, EMPTY_STYLE))
    if len(elements) >= 2:
        nodes.append(tutorial_box("t2", box_label(elements[1]["element_id"]), 420, NEIGHBOR_STYLE))
    if not nodes:
        nodes.append(tutorial_box("t0", "最初の要素がここに入ります", 0, EMPTY_STYLE))
    edges = [StreamlitFlowEdge("te", "t1", "t2", edge_type="default", **edge_style(links[0]),
                               **edge_label(links[0]))] if links else []
    key = f"dg_tutorial_flow_{step}_{len(elements)}_{len(links)}"
    if st.session_state.get("dg_tut_figure_key") != key:  # 内容が変わったときだけ作る（毎回作ると点滅する）
        st.session_state.dg_tut_figure_key = key
        st.session_state.dg_tut_figure = StreamlitFlowState(nodes=nodes, edges=edges)
    streamlit_flow(key, st.session_state.dg_tut_figure, height=180, fit_view=True, allow_new_edges=False,
                   show_controls=False, allow_zoom=False, pan_on_drag=False, hide_watermark=True, style=CANVAS_STYLE)


step = st.session_state.get("dg_tutorial")
if step:
    st.progress(min(step, 3) / 3, text=f"ステップ {min(step, 3)} / 3")
    type_codes = type_options()
    if step == 1:
        st.markdown("### まず、変えたいものを1つ登録しましょう")
        st.write("これから変更を考えているシステムや業務を1つ書きます。図の真ん中に置かれ、ここからつながりを広げていきます。")
        tutorial_figure(1)
        with st.form("dg_tutorial_1"):
            name = st.text_input("名前", placeholder="例：勤怠管理システム")
            element_type = st.selectbox("種類", type_codes, index=type_codes.index("system"), format_func=type_label,
                                        help="業務・システム・データ・部門などの区別です。迷ったら近いものを選んでください。")
            if st.form_submit_button("登録して次へ", type="primary"):
                if error := name_error(name):
                    st.error(error)
                else:
                    st.session_state.dg_center = add_element(name, element_type)
                    st.session_state.dg_tutorial = 2
                    st.rerun()
    elif step == 2:
        first = elements[0]
        hint, example, example_type = diagram.NEXT_EXAMPLE.get(first["element_type"], ("関係するもの", "", "process"))
        st.markdown("### 次に、それとつながるものを1つ登録しましょう")
        st.write(f"「{first['name']}」が変わると、影響を受けるものは何ですか？たとえば **{hint}** を考えてみてください。")
        tutorial_figure(2)
        with st.form("dg_tutorial_2"):
            name = st.text_input("名前", placeholder=f"例：{example}" if example else "")
            element_type = st.selectbox("種類", type_codes, index=type_codes.index(example_type), format_func=type_label)
            if st.form_submit_button("登録して次へ", type="primary"):
                if error := name_error(name):
                    st.error(error)
                else:
                    add_element(name, element_type)
                    st.session_state.dg_tutorial = 3
                    st.rerun()
    elif step == 3:
        first, second = elements[0], elements[1]
        st.markdown("### 最後に、2つの関係を設定しましょう")
        drawn = st.session_state.get("dg_tut_drawn", False)
        if "dg_tut_state" not in st.session_state:  # 1回だけ作る（毎回作ると、ドラッグ中の線が消える）
            st.session_state.dg_tut_state = connect_state(drawn)
        if not drawn:
            st.write(f"「{first['name']}」が変わると「{second['name']}」に影響するので、線でつなぎます。"
                     "**左の箱の右端にある ● から、右の箱の左端の ● までドラッグ**してください。")
        event = streamlit_flow("dg_tutorial_connect", st.session_state.dg_tut_state, height=180, fit_view=True,
                               allow_new_edges=not drawn, show_controls=False, allow_zoom=False, pan_on_drag=False,
                               hide_watermark=True, style=CANVAS_STYLE)
        if not drawn and event.timestamp > st.session_state.get("dg_tut_last", 0):
            st.session_state.dg_tut_last = event.timestamp
            if any(e.source == "t1" and e.target == "t2" for e in event.edges):
                st.session_state.dg_tut_drawn = True
                st.session_state.dg_tut_state = connect_state(True)
                st.rerun()
        if not drawn:
            if st.button("うまく線を引けないときは、ここを押す"):
                st.session_state.dg_tut_drawn = True
                st.session_state.dg_tut_state = connect_state(True)
                st.rerun()
            st.stop()
        st.write(f"線がつながりました。矢印は「左が変わると、右に影響する」向きです。"
                 f"「{first['name']}」と「{second['name']}」は、どのような関係ですか？")
        codes = relation_options()
        relation = st.radio("関係の種類", codes, format_func=diagram.relation_option,
                            index=codes.index(diagram.default_relation(first["element_type"], second["element_type"])))
        st.info(diagram.reading(first["name"], second["name"], relation), icon=":material/menu_book:")
        with st.form("dg_tutorial_3"):
            status = st.radio("確認状態（この関係を確かめたか）", list(models.STATUSES),
                              index=list(models.STATUSES).index("assumed"), format_func=STATUS_LABELS.get,
                              horizontal=True, captions=[diagram.STATUS_HELP[s] for s in models.STATUSES])
            evidence = st.text_input("根拠（任意）", placeholder="例：人事部へのヒアリング、システム仕様書")
            if st.form_submit_button("関係を設定する", type="primary"):
                add_link(first["element_id"], second["element_id"], relation, status, evidence)
                commit()
                st.session_state.dg_tutorial = 4
                st.rerun()
    else:
        first, second = elements[0], elements[1]
        st.success("はじめてのつながりができました。")
        tutorial_figure(4)
        st.markdown(
            f"- **「{first['name']}」を変えると、「{second['name']}」に影響する**、という1本のつながりです。\n"
            "- これが、Excelの依存関係シートの1行に当たります。\n"
            "- この調子で、つながりを1本ずつ増やしていくと、変更の影響を分析できるようになります。"
            "（いまの2つだけでも、「影響分析」で分析できます）"
        )
        st.markdown("**次の画面では**、ある要素を真ん中に置き、左に影響元（その要素に影響を与えるもの）、"
                    "右に影響先（その要素が変わると影響を受けるもの）を並べて表示します。"
                    "上の「＋ 影響元を追加」「＋ 影響先を追加」か、箱から箱へ線を引いて、つながりを増やしてください。")
        if st.button("続けて作る", type="primary"):
            st.session_state.dg_tutorial = None
            st.session_state.dg_trail = []
            st.session_state.dg_coach = second["element_id"]  # 次の画面で「この箱をクリックしてみましょう」と案内する
            set_center(first["element_id"])
            st.rerun()
    st.stop()


# ---------- 画面 ----------
def element_label(element_id: str) -> str:
    return names[element_id] + ("" if element_id in connected else "・未接続")


def pick_from_list(key: str) -> None:
    if st.session_state[key]:
        set_center(st.session_state[key])


list_col, main_col = st.columns([1, 3.4], gap="large")
with list_col:
    # 見る要素を切り替えられることに気づいてもらうため、紺の帯で目立たせ、選ぶ場所を枠で囲む
    now = f"<div class='pick-now'>いま見ている：<b>{escape(names[center])}</b></div>" if center in names else ""
    st.markdown(
        "<div class='pick-head'><div class='pick-title'>見る要素を切り替える</div>"
        "<div class='pick-text'>ここで選ぶと、その要素が図の真ん中に来ます。図の箱をクリックしても切り替わります。</div>"
        f"{now}</div>"
        "<style>"
        f".pick-head{{background:{NAVY};border-top:3px solid {GOLD};border-radius:6px;padding:12px 14px;"
        "margin-bottom:8px}"
        ".pick-title{color:#fff;font-weight:700;font-size:1.05rem;letter-spacing:.04em}"
        f".pick-title::before{{content:'▼ ';color:{GOLD}}}"
        ".pick-text{color:#C9CFDB;font-size:.85rem;line-height:1.7;margin-top:4px}"
        ".pick-now{color:#fff;font-size:.85rem;margin-top:8px;padding-top:8px;border-top:1px solid rgba(255,255,255,.2)}"
        f".pick-now b{{color:{GOLD}}}"
        "</style>",
        unsafe_allow_html=True)
    with st.container(border=True):
        # 要素が増えても探せるよう、1つの検索欄にまとめる（文字を入れると候補が絞られる）
        type_order = type_options()
        ordered = sorted(names, key=lambda i: (type_order.index(types[i]), names[i]))
        st.session_state["dg_search"] = None  # 選んだら空に戻す（いま見ている要素は上の帯に出ている）
        st.selectbox("名前で探す", ordered, key="dg_search", index=None, placeholder="名前を入力して選ぶ",
                     format_func=lambda i: f"{element_label(i)}（{type_label(types[i])}）",
                     on_change=pick_from_list, args=("dg_search",))
        isolated = diagram.isolated(elements, links)
        if isolated:  # 線がつながっていない要素は、登録漏れの目印なので、すぐ選べるように並べる
            st.caption("まだつながっていない要素")
            for element_id in isolated:
                if st.button(names[element_id], key=f"dg_pick_{element_id}", width="stretch",
                             type="primary" if element_id == center else "secondary"):
                    set_center(element_id)
                    st.rerun()
    with st.expander("要素を追加"):
        with st.form("dg_add_element", clear_on_submit=True):
            name = st.text_input("名前")
            element_type = st.selectbox("種類", type_options(), format_func=type_label)
            if st.form_submit_button("追加して、この要素のつながりを見る", type="primary"):
                if error := name_error(name):
                    st.error(error)
                else:
                    element_id = add_element(name, element_type)
                    commit()
                    set_center(element_id)
                    st.rerun()

with main_col:
    # 全体図で箱を選んだら入力の図へ戻れるよう、タブではなく選択式にする。
    # 部品を表示したあとでは値を変えられないため、切り替えの予約（dg_view_next）を表示の前に反映する
    if "dg_view_next" in st.session_state:
        st.session_state.dg_view = st.session_state.pop("dg_view_next")
    st.segmented_control("表示", VIEWS, key="dg_view", label_visibility="collapsed")
    view = st.session_state.get("dg_view") or VIEWS[0]
    if center is None:
        st.info("左の「要素を追加」から、変更したいもの（例：勤怠管理システム）を登録してください。")
        st.stop()
    if "dg_flow" not in st.session_state or st.session_state.get("dg_center") != center:
        set_center(center)

    if view == VIEWS[0]:
        c1, c2, c3 = st.columns(3)
        if c1.button("＋ 影響元を追加", width="stretch"):
            st.session_state.dg_pending = ("in", None)
        # 要素名は入力された文字なので、エスケープしてから埋め込む
        c2.markdown(f"<div style='text-align:center;color:{NAVY};line-height:1.4'>"
                    "<div style='font-size:.8rem;color:#5A6478'>いま見ている要素</div>"
                    f"<div style='font-weight:700'>{escape(names[center])}"
                    f"<span style='font-size:.8rem;font-weight:400'>（{escape(type_label(types[center]))}）</span>"
                    "</div></div>", unsafe_allow_html=True)
        if c3.button("＋ 影響先を追加", width="stretch"):
            st.session_state.dg_pending = ("out", None)

        trail = [t for t in st.session_state.get("dg_trail", []) if t in names]
        if len(trail) > 1:
            with st.container(horizontal=True, vertical_alignment="center", gap="small"):
                st.caption("たどった順：")
                for i, element_id in enumerate(trail[-6:]):
                    if i:
                        st.caption("›")
                    if element_id == center:
                        st.button(names[element_id], key=f"dg_trail_{element_id}", type="primary", disabled=True)
                    elif st.button(names[element_id], key=f"dg_trail_{element_id}"):
                        set_center(element_id)
                        st.rerun()

        coach = st.session_state.get("dg_coach")
        if coach in names and coach != center:
            st.info(f"**やってみましょう：** 図の右にある「{names[coach]}」の箱をクリックしてください。"
                    f"「{names[coach]}」を真ん中にして、そのつながりを見られます。", icon=":material/touch_app:")
        elif coach == center:
            st.success(f"切り替わりました。いまは「{names[center]}」を真ん中にして見ています。"
                       "左の箱をクリックするか、上の「たどった順」で戻れます。"
                       "この方法で、つながりを1つずつたどりながら、ヒアリングを進めていきます。")
            st.session_state.dg_coach = None  # 1回表示したら終わり（次の操作で消える）

        st.toggle("データをまとめて表示する", key="dg_collapse",
                  on_change=lambda: st.session_state.pop("dg_flow", None),  # 切り替えたら図を作り直す
                  help="データの箱を、線の上の名前（青い地）にまとめます。登録の内容は変わりません。"
                       "データと規程のつながりは、そのデータのつながりを見ると表示されます。")
        # 操作の役割を分けて書く（同じことをする方法が複数あると迷うため）
        st.markdown(
            "<div style='font-size:.85rem;line-height:1.8;color:#3A4458'>"
            "<b>つながりを増やす</b>　図にある箱どうし → 箱の右端の ● から相手の左端の ● へドラッグ　／　"
            "新しい要素・図にない要素 → 上の「＋ 影響元を追加」「＋ 影響先を追加」<br>"
            "<b>見る要素を変える</b>　箱をクリック　／　<b>つながりを直す</b>　線をクリック　／　"
            "<b>名前・種類・責任部門の変更、削除</b>　真ん中の箱をクリック</div>",
            unsafe_allow_html=True)

        if "dg_flow" not in st.session_state:
            set_center(center)
        drawn_ids = {e.id for e in st.session_state.dg_flow.edges}
        event = streamlit_flow(
            "dg_ego_flow", st.session_state.dg_flow, height=st.session_state.dg_height, fit_view=True,
            get_node_on_click=True, get_edge_on_click=True, allow_new_edges=True,
            show_controls=False, allow_zoom=False, pan_on_drag=False, hide_watermark=True, style=CANVAS_STYLE,
        )
        if event.timestamp > st.session_state.get("dg_last_event", 0):
            st.session_state.dg_last_event = event.timestamp
            new_edges = [e for e in event.edges if e.id not in drawn_ids]
            selected = event.selected_id
            # 出来事を1回処理したら図を作り直し、部品に残った選択状態や仮の線を消す（同じ出来事を二度処理しないため）。
            # 出来事がないときに作り直すと、作り直し → 部品が新しい状態を返す → また作り直す、と繰り返してしまう
            if new_edges or selected:
                st.session_state.dg_flow = build_state(center)
            if new_edges:
                draw_link_dialog(node_element(new_edges[0].source), node_element(new_edges[0].target))
            elif selected and selected.startswith("edge:via:"):
                set_center(selected.split(":")[2])  # まとめたデータの線は、そのデータのつながりを開く
                st.rerun()
            elif selected and selected.startswith("edge:"):
                edit_link_dialog(selected.split(":", 1)[1])
            elif selected and selected.startswith("c:"):
                edit_element_dialog(center)
            elif selected and selected.startswith("n:"):
                set_center(node_element(selected))  # 箱のクリックで、その要素のつながりにすぐ切り替える
                st.rerun()

        # 凡例：色と線の意味（説明文の中に埋もれさせない）
        def sample_line(color: str, dashed: bool) -> str:
            dash = "stroke-dasharray='7 5'" if dashed else ""
            return (f"<svg width='34' height='10'><line x1='0' y1='5' x2='34' y2='5' stroke='{color}' "
                    f"stroke-width='2.5' {dash}/></svg>")
        chip = "display:inline-block;width:14px;height:14px;border-radius:3px;vertical-align:-2px;margin-right:4px"
        st.markdown(
            "<div style='display:flex;flex-wrap:wrap;gap:4px 18px;font-size:.8rem;color:#3A4458'>"
            f"<span><span style='{chip};background:{GOLD};border:2px solid {NAVY}'></span>いま見ている要素</span>"
            f"<span>{sample_line(GOLD, False)} 確認済</span>"
            f"<span>{sample_line(GOLD, True)} <b>推定・未確認（確認が必要）</b></span>"
            f"<span>{sample_line(RULE_GRAY, False)} 規程とのつながり</span>"
            f"<span><span style='{chip};background:{DATA_BLUE}'></span>まとめたデータ</span>"
            "</div>", unsafe_allow_html=True)

        if st.session_state.get("dg_pending"):
            add_links_dialog(*st.session_state.dg_pending)

        st.markdown("#### この要素のつながり（Excelの依存関係シートの行に相当）")
        mine = [l for l in links if center in (l["from_id"], l["to_id"])]
        if mine:
            data_table(pd.DataFrame({
                "影響元": [names[l["from_id"]] for l in mine],
                "影響先": [names[l["to_id"]] for l in mine],
                "関係の種類": [models.relation_type_label(l["relation_type"]) for l in mine],
                "向き": [models.DIRECTIONS.get(l["direction"], l["direction"]) for l in mine],
                "確認状態": [STATUS_LABELS.get(l["status"], l["status"]) for l in mine],
                "根拠": [l["evidence"] for l in mine],
            }))
        else:
            st.write("この要素には、まだつながりがありません。上の「＋ 影響元を追加」「＋ 影響先を追加」から始めてください。")

    else:
        # ---------- 全体図（見るための図。配置は部品の自動配置で計算する） ----------
        scope = st.radio("範囲", ["全体", f"「{names[center]}」のまわり（2段まで）"], horizontal=True)
        shown = set(names)
        if scope != "全体":
            shown = {center}
            for _ in range(2):  # 向きに関係なく、つながりを2段たどる
                shown |= {l["to_id"] for l in links if l["from_id"] in shown}
                shown |= {l["from_id"] for l in links if l["to_id"] in shown}
        nodes = []
        for element_id in shown:
            if element_id == center:
                style = dict(CENTER_STYLE, width=f"{NODE_W}px", height=f"{NODE_H}px", fontSize="13px")
            elif element_id not in connected:
                style = {**BASE, "background": "#FFFFFF", "color": NAVY, "border": "2px dashed #C0392B"}
            elif types[element_id] == diagram.RULE:
                style = dict(RULE_STYLE)
            else:
                style = dict(NEIGHBOR_STYLE)
            label = box_label(element_id) + ("・未接続" if element_id not in connected else "")
            nodes.append(StreamlitFlowNode(f"all:{element_id}", (0, 0), {"content": label}, node_type="default",
                                           source_position="right", target_position="left", draggable=False,
                                           selectable=True, connectable=False, style=style))
        edges = [StreamlitFlowEdge(f"alledge:{l['dependency_id']}", f"all:{l['from_id']}", f"all:{l['to_id']}",
                                   edge_type="default", **edge_style(l))
                 for l in links if l["from_id"] in shown and l["to_id"] in shown]
        key = f"dg_overview_{scope}_{len(shown)}_{len(edges)}_{center}"  # 範囲やデータが変わったら作り直す
        if st.session_state.get("dg_overview_key") != key:
            st.session_state.dg_overview_key = key
            st.session_state.dg_overview = StreamlitFlowState(nodes=nodes, edges=edges)
        st.caption("配置は自動で計算しています（左から右へ影響が流れる）。マウスのホイールか左下のボタンで拡大縮小、"
                   "ドラッグで移動できます。箱をクリックすると、その要素のつながりを表示する画面に戻ります。"
                   "赤い点線の枠は未接続の要素、金色はいま見ている要素、点線は推定・未確認のつながりです。")
        event = streamlit_flow(
            "dg_overview_flow", st.session_state.dg_overview, height=560, fit_view=True,
            layout=LayeredLayout(direction="right", node_node_spacing=30, node_layer_spacing=70),
            get_node_on_click=True, allow_new_edges=False, show_controls=True, allow_zoom=True, min_zoom=0.2,
            pan_on_drag=True, hide_watermark=True, style=CANVAS_STYLE,
        )
        if event.timestamp > st.session_state.get("dg_last_overview_event", 0) and event.selected_id:
            st.session_state.dg_last_overview_event = event.timestamp
            if event.selected_id.startswith("all:"):
                set_center(event.selected_id.split(":", 1)[1])
                st.session_state.dg_view_next = VIEWS[0]
                st.session_state.pop("dg_overview_key", None)
                st.rerun()
