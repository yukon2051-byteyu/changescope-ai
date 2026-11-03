"""複数の画面で共通に使う表示部品。"""

from __future__ import annotations

from html import escape

import pandas as pd
import streamlit as st

from changescope import models
from changescope.datasets import Dataset
from changescope.theme import THEME, css_variables

STATUS_LABELS = {
    "confirmed": "確認済",
    "assumed": "推定",
    "unconfirmed": "未確認",
}

# データを入れ替えたときに消す、分析中の状態
_ANALYSIS_KEYS = ["targets", "_last_candidates", "impact_result", "impact_targets", "change_text"]


def set_dataset(dataset: Dataset) -> None:
    """分析に使うデータを入れ替え、前のデータでの分析結果を消す。"""
    st.session_state.dataset = dataset
    for key in _ANALYSIS_KEYS:
        st.session_state.pop(key, None)


def get_dataset() -> Dataset | None:
    return st.session_state.get("dataset")


def element_label(dataset: Dataset, element_id: str) -> str:
    node = dataset.graph.nodes[element_id]
    return f"{node['name']}（{models.element_type_label(node['element_type'])}）"


def show_mode_banner(dataset: Dataset | None) -> None:
    """どのデータ・どの方式で分析しているかを常に表示し、サンプルと実データの混同を防ぐ。"""
    if dataset is None:
        st.info("データが読み込まれていません。「データ管理」でサンプルデータかExcelテンプレートを読み込んでください。")
        return
    source = {"sample": "架空サンプルデータ（サンプル商事株式会社）",
              "diagram": "画面で作成・編集したデータ（図で入力する・資料から作る）"}.get(dataset.source, "アップロードしたデータ")
    st.info(f"**データ：** {source}　｜　**分析方式：** AIなし（登録された依存関係のみで分析）")


# ---------- 装飾（濃い色と差し色。色は changescope/theme.py で決める） ----------
# 部品のHTMLはすべてこのファイル内の固定文言から作る。利用者の入力値は埋め込まない。
# CSS の中の色は var(--cs-...) の名前で書き、実際の色は theme.css_variables() が決める（テーマを切り替えられるように）

_FONT_IMPORTS = "".join(
    f"@import url('{url}');\n"
    for url in ("https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@500;600&display=swap",
                THEME.heading_font_url) if url
)

_GLOBAL_CSS = "<style>\n" + _FONT_IMPORTS + css_variables() + """
/* 日本語の見出しの書体（テーマで明朝などに変えられる。指定がなければ本文と同じ） */
.stApp h1, .stApp h2, .stApp h3, .cs-hero-lead, .cs-section-title, .cs-conclusion-headline,
.cs-card-title, .cs-step-title { font-family: var(--cs-heading-font); }
/* 上部の余白を詰める：ヘッダーを透明にし、本文を画面の上端近くから始める。
   ヘッダーは本文の上に重なるため、ボタン以外はクリックを通す。右上のメニューは淡い地色で見やすくする */
[data-testid="stHeader"] { background: transparent; pointer-events: none; }
[data-testid="stHeader"] button, [data-testid="stHeader"] a, [data-testid="stToolbar"] { pointer-events: auto; }
[data-testid="stToolbar"] { background: color-mix(in srgb, var(--cs-bg) 92%, transparent); border-radius: 4px; }
/* 左のメニューを少し細くして（標準は300px）、本文とタブの帯を広く使う */
[data-testid="stSidebar"] { width: 260px !important; min-width: 260px !important; }
[data-testid="stMainBlockContainer"] { padding-top: 0.25rem !important; padding-left: 2.5rem !important; padding-right: 2.5rem !important; }  /* 左右の余白を詰めて、本文を広く使う */

.stApp h3 { border-left: 4px solid var(--cs-gold); padding-left: 12px; letter-spacing: .04em; }
[data-testid="stMetric"] {
  background: var(--cs-paper); border: 1px solid var(--cs-line); border-top: 3px solid var(--cs-gold);
  border-radius: 4px; padding: 14px 18px;
}
[data-testid="stMain"] [data-testid="stPageLink"] a {
  background: var(--cs-paper); border: 1px solid var(--cs-navy-2); border-radius: 4px; padding: 10px 14px;
}
[data-testid="stMain"] [data-testid="stPageLink"] a:hover { background: var(--cs-navy); }
[data-testid="stMain"] [data-testid="stPageLink"] a:hover * { color: #fff !important; }

.cs-hero {
  position: relative; overflow: hidden; border-radius: 6px; padding: 20px 48px 18px;
  background: linear-gradient(135deg, var(--cs-navy) 0%, var(--cs-navy-2) 100%);
  border-bottom: 3px solid var(--cs-gold); color: #fff; margin-bottom: 8px;
}
.cs-hero::after {
  content: ""; position: absolute; right: -80px; top: -80px; width: 320px; height: 320px;
  border: 1px solid color-mix(in srgb, var(--cs-gold-light) 35%, transparent); border-radius: 50%;
  box-shadow: 0 0 0 40px color-mix(in srgb, var(--cs-gold-light) 6%, transparent),
              0 0 0 80px color-mix(in srgb, var(--cs-gold-light) 4%, transparent);
}
.cs-eyebrow { color: var(--cs-gold); letter-spacing: .24em; font-size: .78rem; font-weight: 700; }
.cs-hero .cs-eyebrow { color: var(--cs-gold-light); }
.cs-hero-title {
  font-family: 'Cormorant Garamond', serif; font-size: 3.2rem; font-weight: 600; line-height: 1.1;
  margin: 10px 0 18px; color: #fff; letter-spacing: .02em;
}
.cs-hero-lead { font-size: 1.3rem; font-weight: 700; letter-spacing: .06em; margin-bottom: 10px; }
.cs-hero-sub { color: var(--cs-on-dark); line-height: 1.9; }
.cs-hero-rule { width: 56px; height: 2px; background: var(--cs-gold); margin: 0 0 18px; }

.cs-section { margin: 36px 0 14px; }
.cs-section-title { font-size: 1.35rem; font-weight: 700; color: var(--cs-ink); letter-spacing: .06em; margin-top: 4px; }

.cs-cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 16px; }
.cs-card {
  background: var(--cs-paper); border: 1px solid var(--cs-line); border-top: 3px solid var(--cs-gold);
  border-radius: 4px; padding: 20px 22px;
}
.cs-card-num { font-family: 'Cormorant Garamond', serif; color: var(--cs-gold); font-size: 1.9rem; line-height: 1; }
.cs-card-title { font-weight: 700; color: var(--cs-navy); margin: 8px 0 6px; letter-spacing: .04em; }
.cs-card-text { color: var(--cs-sub); font-size: .92rem; line-height: 1.8; }

.cs-note {
  background: var(--cs-cream); border: 1px solid var(--cs-note-line); border-left: 4px solid var(--cs-gold);
  border-radius: 4px; padding: 14px 18px; line-height: 1.9; color: var(--cs-ink); margin: 12px 0;
}
.cs-note b { color: var(--cs-navy); }

.cs-step { display: flex; gap: 16px; padding: 16px 0; border-bottom: 1px solid var(--cs-line); }
.cs-step:last-child { border-bottom: none; }
.cs-step-num {
  flex: 0 0 36px; height: 36px; border-radius: 50%; background: var(--cs-navy); color: var(--cs-gold-light);
  display: flex; align-items: center; justify-content: center; font-weight: 700;
}
.cs-step-title { font-weight: 700; color: var(--cs-navy); margin-bottom: 4px; letter-spacing: .04em; }
.cs-step-text { color: var(--cs-ink); line-height: 1.9; font-size: .95rem; }
.cs-step-text .cs-ui { background: var(--cs-navy); color: #fff; border-radius: 3px; padding: 1px 8px; font-size: .85rem; white-space: nowrap; }

.cs-actions {
  background: var(--cs-paper); border: 1px solid var(--cs-line); border-left: 4px solid var(--cs-gold);
  border-radius: 4px; padding: 4px 22px; margin: 8px 0 16px;
}
.cs-action-list { margin: 6px 0 0 0; padding-left: 1.2em; color: var(--cs-sub); font-size: .9rem; }
.cs-action-list li { margin: 2px 0; }
.cs-step-main { flex: 1; min-width: 0; }

/* 要確認のつながり：重要なため1本ずつ枠で囲んで目立たせる */
.cs-link-cards { margin-top: 10px; display: flex; flex-direction: column; gap: 8px; }
.cs-link-card {
  background: var(--cs-cream); border: 1px solid var(--cs-note-line); border-left: 5px solid var(--cs-gold);
  border-radius: 4px; padding: 10px 14px;
}
.cs-link-unconfirmed { border-left-color: #A6741A; }
.cs-link-head { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.cs-link-status {
  background: var(--cs-navy); color: var(--cs-gold-light); font-size: .78rem; font-weight: 700;
  padding: 2px 10px; border-radius: 3px; white-space: nowrap;
}
.cs-link-unconfirmed .cs-link-status { background: #A6741A; color: #fff; }
.cs-link-text { font-weight: 700; color: var(--cs-navy); font-size: 1.02rem; }
.cs-link-meta { margin-top: 6px; color: var(--cs-ink); font-size: .92rem; }
.cs-link-meta b { color: var(--cs-navy); }
.cs-link-arrow { color: var(--cs-gold); margin: 0 8px; }
.cs-link-count { font-weight: 700; color: var(--cs-navy); font-size: 1.05rem; margin: 0 2px; }
.cs-link-note { margin-top: 4px; color: var(--cs-sub); font-size: .85rem; }

.cs-conclusion {
  background: linear-gradient(135deg, var(--cs-navy) 0%, var(--cs-navy-2) 100%); color: #fff;
  border-radius: 6px; border-bottom: 3px solid var(--cs-gold); padding: 20px 28px; margin: 8px 0 18px;
}
.cs-conclusion .cs-eyebrow { color: var(--cs-gold-light); }
.cs-conclusion-head { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; margin: 8px 0 6px; }
.cs-level { font-weight: 700; padding: 4px 14px; border-radius: 3px; letter-spacing: .08em; white-space: nowrap; }
.cs-level-大 { background: var(--cs-gold); color: var(--cs-navy); }
.cs-level-中 { background: var(--cs-gold-light); color: var(--cs-navy); }
.cs-level-小 { background: #fff; color: var(--cs-navy); }
.cs-conclusion-headline { font-size: 1.2rem; font-weight: 700; letter-spacing: .04em; }
.cs-conclusion-meaning { color: var(--cs-on-dark); margin-bottom: 12px; }
.cs-conclusion-first {
  background: rgba(255,255,255,.08); border-left: 3px solid var(--cs-gold); padding: 10px 14px;
  border-radius: 3px; line-height: 1.8;
}
.cs-conclusion-first b { color: var(--cs-gold-light); margin-right: 12px; }
.cs-conclusion-caution { margin-top: 10px; color: var(--cs-gold-light); font-size: .92rem; line-height: 1.8; }
.cs-conclusion-label { margin-top: 14px; color: var(--cs-gold-light); font-weight: 700; font-size: .9rem; }
.cs-conclusion-stance { margin: 4px 0 0; padding-left: 1.2em; line-height: 1.9; }
.cs-conclusion-basis { margin-top: 12px; color: var(--cs-on-dark-faint); font-size: .8rem; }

.cs-finding {
  background: var(--cs-paper); border: 1px solid var(--cs-line); border-radius: 4px; padding: 14px 18px; margin: 10px 0;
}
.cs-finding-head { display: flex; align-items: center; gap: 10px; margin-bottom: 6px; }
.cs-finding-title { font-weight: 700; color: var(--cs-navy); letter-spacing: .04em; }
.cs-finding-detail { color: var(--cs-ink); line-height: 1.8; font-size: .93rem; }
.cs-finding-items { color: var(--cs-sub); font-size: .9rem; margin-top: 6px; line-height: 1.8; }
.cs-badge, .cs-badge-warn { font-size: .75rem; padding: 2px 8px; border-radius: 3px; white-space: nowrap; }
.cs-badge { background: var(--cs-navy); color: var(--cs-gold-light); }
.cs-badge-warn { background: var(--cs-gold); color: #fff; }

.cs-ai-card {
  background: var(--cs-paper); border: 1px solid var(--cs-line); border-left: 4px solid var(--cs-line);
  border-radius: 4px; padding: 14px 18px; margin: 10px 0;
}
.cs-ai-高 { border-left-color: var(--cs-navy); }
.cs-ai-中 { border-left-color: var(--cs-gold); }
.cs-ai-imp { font-size: .75rem; font-weight: 700; color: var(--cs-navy); white-space: nowrap; }
.cs-ai-view { font-size: .75rem; color: var(--cs-sub); border: 1px solid var(--cs-line); padding: 1px 8px; border-radius: 3px; }
.cs-ai-ask { background: var(--cs-cream); border-radius: 3px; padding: 10px 14px; margin-top: 10px; }
.cs-ai-ask-to { font-weight: 700; color: var(--cs-navy); font-size: .9rem; }
.cs-ai-q { color: var(--cs-ink); line-height: 1.8; margin-top: 4px; }
.cs-ai-q::before { content: "質問　"; color: var(--cs-gold); font-weight: 700; }
.cs-ai-cand { margin-left: 8px; font-size: .75rem; font-weight: 400; color: var(--cs-gold); }
.cs-finding-items ul { margin: 4px 0 0; padding-left: 1.2em; }

.cs-flow { display: flex; flex-wrap: wrap; align-items: stretch; gap: 8px; margin: 12px 0; }
.cs-flow-box {
  flex: 1 1 150px; background: var(--cs-navy); color: #fff; border-radius: 4px; padding: 14px 16px;
  border-bottom: 3px solid var(--cs-gold);
}
.cs-flow-box b { color: var(--cs-gold-light); display: block; margin-bottom: 4px; }
.cs-flow-box span { color: var(--cs-on-dark); font-size: .85rem; line-height: 1.7; }
.cs-flow-arrow { align-self: center; color: var(--cs-gold); font-size: 1.4rem; }

.cs-table { border-collapse: collapse; width: 100%; background: var(--cs-paper); font-size: .92rem; }
.cs-table th { background: var(--cs-navy); color: #fff; text-align: left; padding: 8px 12px; font-weight: 500; }
.cs-table td { border-bottom: 1px solid var(--cs-line); padding: 8px 12px; vertical-align: top; line-height: 1.7;
  overflow-wrap: anywhere; }
.cs-table-wrap { overflow: auto; border: 1px solid var(--cs-line); border-radius: 4px; margin: 6px 0 12px; }
.cs-table-wrap .cs-table th { position: sticky; top: 0; z-index: 1; white-space: nowrap; }
.cs-table .cs-num-col { text-align: right; white-space: nowrap; }

/* タブ：紺の帯に白系の文字。選んでいるタブは金の地に紺の文字にして、タブがあることと、どれを選んでいるかを分かりやすくする。
   Streamlit 1.66 のタブは、並び＝role="tablist"、1つのタブ＝data-testid="stTab"、選択中＝data-selected の印が付く
   （以前の版の data-baseweb="tab" では効かない。Streamlit を更新したら、ここが効いているか画面で確かめる） */
.stTabs [role="tablist"] {
  margin-top: 18px !important; background: var(--cs-navy) !important; border-radius: 6px; padding: 6px !important;
  gap: 6px !important; flex-wrap: nowrap !important; overflow-x: auto !important;  /* とても狭い画面だけ横にずらして見る */
}
.stTabs [role="tablist"]::after { display: none !important; }  /* 元の下線 */
.stTabs [data-testid="stTabsScrollLeft"], .stTabs [data-testid="stTabsScrollRight"] { display: none !important; }
/* タブは1行に並べ、帯の幅を均等に分ける。1つずつ薄い地を付け、隙間（6px）をはさんで別々のタブに見せる。
   文字の大きさは画面の幅に合わせて変え（11.5〜15px）、1行に収める。
   いちばんタブの多い影響分析の結果（7つ・件数つき）でも、幅1,280px以上の画面で1行に収まることを確認済み */
.stTabs [data-testid="stTab"] {
  flex: 1 1 auto; justify-content: center; min-width: max-content;  /* 文字の長さに合わせ、余りを均等に分ける */
  background: rgba(255,255,255,.06) !important; color: var(--cs-on-dark) !important;
  border-radius: 4px; padding: 0 6px !important; transition: background .15s;
}
.stTabs [data-testid="stTab"] p { color: inherit !important; font-size: clamp(.72rem, .88vw, .95rem); white-space: nowrap; }
.stTabs [data-testid="stTab"]:hover { background: rgba(255,255,255,.16) !important; color: #fff !important; }
.stTabs [data-testid="stTab"][data-selected] { background: var(--cs-gold) !important; color: var(--cs-navy) !important; }
.stTabs [data-testid="stTab"][data-selected] p { font-weight: 700; }
.stTabs .react-aria-SelectionIndicator { display: none !important; }  /* 元の選択中の下線 */
.cs-footer { color: var(--cs-sub); font-size: .82rem; margin-top: 40px; padding-top: 14px; border-top: 1px solid var(--cs-line); }
</style>
"""


def apply_global_style() -> None:
    """全画面共通のスタイルを読み込む（app.py から1回呼ぶ）。"""
    st.markdown(_GLOBAL_CSS, unsafe_allow_html=True)


def html(markup: str) -> None:
    st.markdown(markup, unsafe_allow_html=True)


def hero(eyebrow: str, title: str, lead: str, sub: str) -> None:
    html(
        f'<div class="cs-hero"><div class="cs-eyebrow">{eyebrow}</div>'
        f'<div class="cs-hero-title">{title}</div><div class="cs-hero-rule"></div>'
        f'<div class="cs-hero-lead">{lead}</div><div class="cs-hero-sub">{sub}</div></div>'
    )


def section(eyebrow: str, title: str) -> None:
    html(f'<div class="cs-section"><div class="cs-eyebrow">{eyebrow}</div>'
         f'<div class="cs-section-title">{title}</div></div>')


def cards(items: list[tuple[str, str, str]]) -> None:
    """(番号やラベル, 見出し, 本文) のカードを横に並べる。"""
    body = "".join(
        f'<div class="cs-card"><div class="cs-card-num">{num}</div>'
        f'<div class="cs-card-title">{title}</div><div class="cs-card-text">{text}</div></div>'
        for num, title, text in items
    )
    html(f'<div class="cs-cards">{body}</div>')


def note(markup: str) -> None:
    html(f'<div class="cs-note">{markup}</div>')


def steps(items: list[tuple[str, str]]) -> None:
    """番号付きの手順。(見出し, 本文HTML) のリスト。"""
    body = "".join(
        f'<div class="cs-step"><div class="cs-step-num">{n}</div><div>'
        f'<div class="cs-step-title">{title}</div><div class="cs-step-text">{text}</div></div></div>'
        for n, (title, text) in enumerate(items, start=1)
    )
    html(body)


def flow(items: list[tuple[str, str]]) -> None:
    """処理の流れ図。(見出し, 説明) のリストを矢印でつなぐ。"""
    parts = [f'<div class="cs-flow-box"><b>{t}</b><span>{d}</span></div>' for t, d in items]
    html(f'<div class="cs-flow">{"<div class=cs-flow-arrow>›</div>".join(parts)}</div>')


def table(headers: list[str], rows: list[list[str]]) -> None:
    head = "".join(f"<th>{h}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>" for row in rows)
    html(f'<table class="cs-table"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>')


def data_table(df: pd.DataFrame, numeric_columns: tuple[str, ...] = (), max_height: int = 560) -> None:
    """長い文章もセル内で折り返して全文を表示する表。

    st.dataframe はセル内で折り返せず、長い文章が途中で切れるため、HTMLの表で表示する。
    値がリストのセルは1項目ずつ改行して表示する。アップロードされたデータを含むため、すべてエスケープする。
    行が多い場合は表の中でスクロールし、見出し行は固定する。
    """
    def cell(value) -> str:
        if isinstance(value, list):
            return "<br>".join(escape(str(v)) for v in value)
        return escape("" if value is None else str(value))

    head = "".join(
        f'<th class="cs-num-col">{escape(c)}</th>' if c in numeric_columns else f"<th>{escape(c)}</th>"
        for c in df.columns
    )
    rows = "".join(
        "<tr>" + "".join(
            f'<td class="cs-num-col">{cell(v)}</td>' if c in numeric_columns else f"<td>{cell(v)}</td>"
            for c, v in zip(df.columns, row)
        ) + "</tr>"
        for row in df.itertuples(index=False)
    )
    html(f'<div class="cs-table-wrap" style="max-height:{max_height}px">'
         f'<table class="cs-table"><thead><tr>{head}</tr></thead><tbody>{rows}</tbody></table></div>')


def action_steps(actions) -> None:
    """「次にやること」を番号付きで表示する。

    要素名などアップロードされたデータを含むため、すべてエスケープしてからHTMLに埋め込む
    （データに書かれたHTMLやスクリプトが画面で実行されないようにする）。
    """
    body = ""
    for n, action in enumerate(actions, start=1):
        items = "".join(f"<li>{escape(item)}</li>" for item in action.items)
        body += (
            f'<div class="cs-step"><div class="cs-step-num">{n}</div><div class="cs-step-main">'
            f'<div class="cs-step-title">{escape(action.title)}</div>'
            f'<div class="cs-step-text">{escape(action.detail)}'
            f'{_link_cards(action.links)}'
            f'{f"<ul class=cs-action-list>{items}</ul>" if items else ""}</div></div></div>'
        )
    html(f'<div class="cs-actions">{body}</div>')


def _link_cards(links) -> str:
    """要確認のつながりを、1本ずつ枠で囲んで目立たせる（つながり・確認状態・確認先・はっきりする影響の件数）。"""
    cards = ""
    for link in links:
        status = models.STATUSES[link.status]
        contacts = "、".join(link.contacts) if link.contacts else "責任部門が未登録"
        note_line = f'<div class="cs-link-note">補足：{escape(link.note)}</div>' if link.note else ""
        cards += (
            f'<div class="cs-link-card cs-link-{escape(link.status)}">'
            f'<div class="cs-link-head"><span class="cs-link-status">{escape(status)}</span>'
            f'<span class="cs-link-text">{escape(link.text)}</span></div>'
            f'<div class="cs-link-meta">確認先：<b>{escape(contacts)}</b>'
            f'<span class="cs-link-arrow">→</span>確かめると<span class="cs-link-count">{link.affected}件</span>'
            f'の影響の有無がはっきりする</div>{note_line}</div>'
        )
    return f'<div class="cs-link-cards">{cards}</div>' if cards else ""


def conclusion(assessment) -> None:
    """分析結果の結論（総合判定・まずやること・意識すること）を、結果のいちばん上に表示する。

    責任部門の名前などアップロードされたデータを含むため、すべてエスケープする。
    """
    a = assessment
    stance = "".join(f"<li>{escape(s)}</li>" for s in a.stance)
    caution = f'<div class="cs-conclusion-caution">{escape(a.caution)}</div>' if a.caution else ""
    html(
        f'<div class="cs-conclusion">'
        f'<div class="cs-eyebrow">CONCLUSION</div>'
        f'<div class="cs-conclusion-head"><span class="cs-level cs-level-{escape(a.level)}">影響 {escape(a.level)}</span>'
        f'<span class="cs-conclusion-headline">{escape(a.headline)}</span></div>'
        f'<div class="cs-conclusion-meaning">{escape(a.meaning)}</div>'
        f'<div class="cs-conclusion-first"><b>まずやること</b>{escape(a.first_step)}</div>'
        f'{caution}'
        f'<div class="cs-conclusion-label">意識すること</div><ul class="cs-conclusion-stance">{stance}</ul>'
        f'<div class="cs-conclusion-basis">{escape(a.basis)}</div>'
        f'</div>'
    )


def findings_list(findings) -> None:
    """見落としチェックの結果を表示する。登録データの名前を含むため、すべてエスケープする。"""
    body = ""
    for f in findings:
        kind_class = "cs-badge-warn" if f.kind == "登録の不足" else "cs-badge"
        items = "、".join(escape(i) for i in f.items)
        body += (
            f'<div class="cs-finding"><div class="cs-finding-head"><span class="{kind_class}">{escape(f.kind)}</span>'
            f'<span class="cs-finding-title">{escape(f.title)}</span></div>'
            f'<div class="cs-finding-detail">{escape(f.detail)}</div>'
            f'{f"<div class=cs-finding-items>対象：{items}</div>" if items else ""}</div>'
        )
    html(body)


def oversight_findings(findings) -> None:
    """AIが見つけた確認漏れを、1件ずつカードで表示する（確認先・質問文・根拠つき）。

    AIの回答と登録データの名前を含むため、すべてエスケープする。
    「登録情報にもとづく」と「AIの推測」は色を変えて区別する。
    """
    body = ""
    for f in findings:
        basis_class = "cs-badge" if f.basis == "登録情報にもとづく" else "cs-badge-warn"
        contact = escape(f.contact) + ("" if f.contact_registered else '<span class="cs-ai-cand">未登録の部門候補</span>')
        evidence = "".join(f"<li>{escape(e)}</li>" for e in f.evidence)
        body += (
            f'<div class="cs-ai-card cs-ai-{escape(f.importance)}"><div class="cs-finding-head">'
            f'<span class="cs-ai-imp">重要度 {escape(f.importance)}</span>'
            f'<span class="{basis_class}">{escape(f.basis)}</span>'
            f'<span class="cs-ai-view">{escape(f.viewpoint)}</span></div>'
            f'<div class="cs-finding-title">{escape(f.title)}</div>'
            f'<div class="cs-finding-detail">{escape(f.detail)}</div>'
            f'<div class="cs-ai-ask"><div class="cs-ai-ask-to">確認先：{contact}</div>'
            f'<div class="cs-ai-q">{escape(f.question)}</div></div>'
            f'{f"<div class=cs-finding-items>根拠にしたつながり<ul>{evidence}</ul></div>" if evidence else ""}'
            "</div>"
        )
    html(body)


def ui_label(text: str) -> str:
    """画面上のボタン名などを、本文中で目立たせる。"""
    return f'<span class="cs-ui">{text}</span>'
