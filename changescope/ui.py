"""複数の画面で共通に使う表示部品。"""

from __future__ import annotations

import base64
from html import escape
from pathlib import Path

import pandas as pd
import streamlit as st

from changescope import models
from changescope.datasets import Dataset, load_sample
from changescope.theme import THEME, css_variables

STATUS_LABELS = {
    "confirmed": "確認済",
    "assumed": "推定",
    "unconfirmed": "未確認",
}

# データを入れ替えたときに消す、分析中の状態
_ANALYSIS_KEYS = ["targets", "_last_candidates", "impact_result", "impact_targets", "change_text", "impact_text",
                  "impact_depth", "analysis_inputs", "analysis_from", "show_details", "demo_pdf_saved", "just_analyzed",
                  "cp_inputs", "cp_result", "cp_titles", "cp_key"]


def restore_inputs(name: str) -> None:
    """ほかのページへ移ると Streamlit は入力欄の値を捨てるため、控えから戻す（入力欄を置く前に呼ぶ）。"""
    for key, value in st.session_state.get(name, {}).items():
        st.session_state.setdefault(key, value)


def remember_inputs(name: str, keys: list[str]) -> None:
    """入力欄の値の控えを残す。"""
    st.session_state[name] = {key: st.session_state[key] for key in keys if key in st.session_state}


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
                "https://fonts.googleapis.com/css2?family=Manrope:wght@700;800&display=swap",
                THEME.heading_font_url) if url
)

_GLOBAL_CSS = "<style>\n" + _FONT_IMPORTS + css_variables() + """
/* 日本語の見出しの書体（テーマで明朝などに変えられる。指定がなければ本文と同じ） */
.stApp h1, .stApp h2, .stApp h3, .cs-hero-lead, .cs-section-title, .cs-conclusion-headline,
.cs-card-title, .cs-step-title { font-family: var(--cs-heading-font); }
/* 上部の余白を詰める：ヘッダーを透明にし、本文を画面の上端近くから始める。
   ヘッダーは本文の上に重なるため、ボタン以外はクリックを通す。右上のメニューは淡い地色で見やすくする */
[data-testid="stHeader"] { background: transparent; pointer-events: none; }
/* 上余白（全ページ共通）：ヘッダーとサイドバーの開閉ボタンの領域を 44px にし、ボタンの下端（36px）から 24px 下の
   60px から、メニューの先頭の行と本文を始める。ページごとの余白は持たない（すべてここで決める） */
[data-testid="stHeader"], [data-testid="stSidebarHeader"] { height: 2.75rem !important; min-height: 2.75rem !important; }
[data-testid="stSidebarHeader"] { margin-bottom: 0 !important; padding-top: 0 !important; padding-bottom: 0 !important; }
/* 本文の上には全ページ共通の見えない部品（スタイルの読み込みなど）があり 32px ずれるため、余白は 28px。
   メニューは 44px のヘッダーの下に 12px 空けて、先頭の行の上端を本文と同じ 60px にする */
[data-testid="stSidebarNav"] { margin-top: 14px !important; }
[data-testid="stHeader"] button, [data-testid="stHeader"] a, [data-testid="stToolbar"] { pointer-events: auto; }
/* 右上の道具（公開先では Fork・GitHub の印）には背景を付けない。公開先ではこの欄が横幅いっぱいに広がり、
   背景を付けると本文の上の部分が半透明の帯で覆われて、文字が見切れたように見える（2026-11-03 に発生） */
[data-testid="stToolbar"] { background: transparent; }
/* 左のメニューを少し細くして（標準は300px）、本文とタブの帯を広く使う */
[data-testid="stSidebar"] { width: 260px !important; min-width: 260px !important; }
[data-testid="stMainBlockContainer"] { padding-top: 1.75rem !important; padding-left: 2.5rem !important; padding-right: 2.5rem !important; }  /* 左右の余白を詰めて、本文を広く使う */
/* 本文の幅は1200pxで止め、それより広い画面では中央に寄せる（大きな画面で横に間延びしないように） */
[data-testid="stMainBlockContainer"] { max-width: 1200px !important; margin-left: auto !important; margin-right: auto !important; }

.stApp h3 { letter-spacing: .03em; font-weight: 700; }
/* 全画面で、本文の先頭（ページの見出し）の上端を、左のメニューの先頭の行にそろえる */
.stApp h1 { padding-top: 0 !important; margin-top: 0 !important; }
[data-testid="stMetric"] {
  background: var(--cs-paper); border: 1px solid var(--cs-line);
  border-radius: var(--cs-radius); padding: 14px 18px; box-shadow: var(--cs-shadow);
}
/* 要確認の数は、アンバー系の色と文言を一緒に使う（色だけに頼らない） */
.st-key-metric_uncertain [data-testid="stMetricValue"] { color: #9A6A00; }
.st-key-metric_uncertain [data-testid="stMetric"] { background: #FFF8E6; border-color: #F0D9A0; }
[data-testid="stMain"] [data-testid="stPageLink"] a {
  background: var(--cs-paper); border: 1px solid var(--cs-navy-2); border-radius: var(--cs-pill); padding: 10px 18px;
}
[data-testid="stMain"] [data-testid="stPageLink"] a:hover { background: var(--cs-navy); }
[data-testid="stMain"] [data-testid="stPageLink"] a:hover * { color: #fff !important; }

.cs-hero {
  position: relative; overflow: hidden; border-radius: var(--cs-radius-lg); padding: 20px 48px 18px;
  background: var(--cs-hero-bg); border: 1px solid var(--cs-line); border-bottom: 3px solid var(--cs-hero-rule);
  color: var(--cs-hero-ink); margin-bottom: 16px; box-shadow: var(--cs-shadow);
}
.cs-hero::after {
  content: ""; position: absolute; right: -80px; top: -80px; width: 320px; height: 320px;
  border: 1px solid var(--cs-hero-ring-line); border-radius: 50%;
  box-shadow: 0 0 0 40px var(--cs-hero-ring-1), 0 0 0 80px var(--cs-hero-ring-2);
}
.cs-eyebrow { color: var(--cs-accent-text); letter-spacing: .24em; font-size: .78rem; font-weight: 700; }
.cs-hero .cs-eyebrow { color: var(--cs-hero-eyebrow); }
.cs-hero-title {
  font-family: 'Cormorant Garamond', serif; font-size: 3.2rem; font-weight: 600; line-height: 1.1;
  margin: 10px 0 18px; color: var(--cs-hero-ink); letter-spacing: .02em;
}
.cs-hero-lead { font-size: 1.3rem; font-weight: 700; letter-spacing: .06em; margin-bottom: 10px; }
.cs-hero-sub { color: var(--cs-hero-sub); line-height: 1.9; }
.cs-hero-rule { width: 56px; height: 2px; background: var(--cs-hero-rule); margin: 0 0 18px; }

.cs-section { margin: 26px 0 10px; }
.cs-section-title { font-size: 1.35rem; font-weight: 700; color: var(--cs-ink); letter-spacing: .06em; margin-top: 4px; }

.cs-cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 16px; }
.cs-card {
  background: var(--cs-paper); border: 1px solid var(--cs-line); border-top: 3px solid var(--cs-gold);
  border-radius: var(--cs-radius); padding: 20px 22px; box-shadow: var(--cs-shadow);
}
.cs-card-num { font-family: 'Cormorant Garamond', serif; color: var(--cs-accent-text); font-size: 1.9rem; line-height: 1; }
.cs-card-title { font-weight: 700; color: var(--cs-navy); margin: 8px 0 6px; letter-spacing: .04em; }
.cs-card-text { color: var(--cs-sub); font-size: .92rem; line-height: 1.8; }

.cs-note {
  background: var(--cs-cream); border: 1px solid var(--cs-note-line); border-left: 4px solid var(--cs-gold);
  border-radius: var(--cs-radius); padding: 14px 18px; line-height: 1.9; color: var(--cs-ink); margin: 12px 0;
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
.cs-step-text .cs-ui { background: var(--cs-navy); color: #fff; border-radius: var(--cs-pill); padding: 1px 8px; font-size: .85rem; white-space: nowrap; }

.cs-actions {
  background: var(--cs-paper); border: 1px solid var(--cs-line); border-left: 4px solid var(--cs-gold);
  border-radius: var(--cs-radius); padding: 4px 22px; margin: 8px 0 16px; box-shadow: var(--cs-shadow);
}
.cs-action-list { margin: 6px 0 0 0; padding-left: 1.2em; color: var(--cs-sub); font-size: .9rem; }
.cs-action-list li { margin: 2px 0; }
.cs-step-main { flex: 1; min-width: 0; }

/* 要確認のつながり：重要なため1本ずつ枠で囲んで目立たせる */
.cs-link-cards { margin-top: 10px; display: flex; flex-direction: column; gap: 8px; }
.cs-link-card {
  background: var(--cs-cream); border: 1px solid var(--cs-note-line); border-left: 5px solid var(--cs-gold);
  border-radius: var(--cs-radius); padding: 10px 14px;
}
.cs-link-unconfirmed { border-left-color: #A6741A; }
.cs-link-head { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.cs-link-status {
  background: var(--cs-navy); color: var(--cs-gold-light); font-size: .78rem; font-weight: 700;
  padding: 2px 10px; border-radius: var(--cs-pill); white-space: nowrap;
}
.cs-link-unconfirmed .cs-link-status { background: #A6741A; color: #fff; }
.cs-link-text { font-weight: 700; color: var(--cs-navy); font-size: 1.02rem; }
.cs-link-meta { margin-top: 6px; color: var(--cs-ink); font-size: .92rem; }
.cs-link-meta b { color: var(--cs-navy); }
.cs-link-arrow { color: var(--cs-accent-text); margin: 0 8px; }
.cs-link-count { font-weight: 700; color: var(--cs-navy); font-size: 1.05rem; margin: 0 2px; }
.cs-link-note { margin-top: 4px; color: var(--cs-sub); font-size: .85rem; }

.cs-conclusion {
  background: var(--cs-concl-bg); color: var(--cs-concl-ink); border: var(--cs-concl-border);
  border-radius: var(--cs-radius-lg); border-bottom: 3px solid var(--cs-gold); padding: 20px 28px; margin: 8px 0 18px;
  box-shadow: var(--cs-shadow);
}
.cs-conclusion .cs-eyebrow { color: var(--cs-concl-strong); }
.cs-conclusion-head { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; margin: 8px 0 6px; }
.cs-level { font-weight: 700; padding: 4px 14px; border-radius: var(--cs-pill); letter-spacing: .08em; white-space: nowrap; }
.cs-level-大 { background: var(--cs-level-big-bg); color: var(--cs-level-big-ink); }
.cs-level-中 { background: var(--cs-level-mid-bg); color: var(--cs-level-mid-ink); }
.cs-level-小 { background: var(--cs-level-small-bg); color: var(--cs-level-small-ink); border: var(--cs-level-small-border); }
.cs-conclusion-headline { font-size: 1.2rem; font-weight: 700; letter-spacing: .04em; }
.cs-conclusion-meaning { color: var(--cs-concl-sub); margin-bottom: 12px; }
.cs-conclusion-first {
  background: var(--cs-concl-first); border-left: 3px solid var(--cs-gold); padding: 10px 14px;
  border-radius: var(--cs-radius); line-height: 1.8;
}
.cs-conclusion-first b { color: var(--cs-concl-strong); margin-right: 12px; }
.cs-conclusion-caution { margin-top: 10px; color: var(--cs-concl-strong); font-size: .92rem; line-height: 1.8; }
.cs-conclusion-label { margin-top: 14px; color: var(--cs-concl-strong); font-weight: 700; font-size: .9rem; }
.cs-conclusion-stance { margin: 4px 0 0; padding-left: 1.2em; line-height: 1.9; }
.cs-conclusion-basis { margin-top: 12px; color: var(--cs-concl-faint); font-size: .8rem; }

.cs-finding {
  background: var(--cs-paper); border: 1px solid var(--cs-line); border-radius: var(--cs-radius); padding: 14px 18px;
  margin: 10px 0; box-shadow: var(--cs-shadow);
}
.cs-finding-head { display: flex; align-items: center; gap: 10px; margin-bottom: 6px; }
.cs-finding-title { font-weight: 700; color: var(--cs-navy); letter-spacing: .04em; }
.cs-finding-detail { color: var(--cs-ink); line-height: 1.8; font-size: .93rem; }
.cs-finding-items { color: var(--cs-sub); font-size: .9rem; margin-top: 6px; line-height: 1.8; }
.cs-badge, .cs-badge-warn, .cs-badge-general { font-size: .75rem; padding: 2px 10px; border-radius: var(--cs-pill); white-space: nowrap; }
.cs-badge { background: var(--cs-navy); color: var(--cs-gold-light); }
.cs-badge-warn { background: var(--cs-gold); color: var(--cs-badge-warn-ink); }
/* 一般的な確認の観点：登録データに根拠がない指摘。意味を表す色なので、テーマによらず灰青で固定 */
.cs-badge-general { background: #E6EAF0; color: #33415C; border: 1px solid #C9D1DC; }
/* 「AIで確認漏れを調べる」：このツールの中核なので、枠とボタンをほかより目立たせる（色はテーマで決める） */
.st-key-ai_check_panel { background: var(--cs-ai-panel-bg) !important; border: 2px solid var(--cs-ai-panel-border) !important;
  box-shadow: 0 4px 14px rgba(15,60,45,.12); }
.st-key-ai_oversight button { background: var(--cs-ai-button-bg) !important; color: var(--cs-ai-button-ink) !important;
  border: none !important; min-height: 3.1rem; padding: 0 1.8rem !important;
  box-shadow: 0 0 0 3px var(--cs-ai-button-ring), 0 6px 16px rgba(15,60,45,.25) !important; transition: filter .15s; }
.st-key-ai_oversight button p { font-size: 1.08rem !important; font-weight: 700 !important; color: inherit !important; }
.st-key-ai_oversight button:hover { filter: brightness(1.12); }
.st-key-ai_oversight button:disabled { opacity: .5; box-shadow: none !important; }

.cs-ai-card {
  background: var(--cs-paper); border: 1px solid var(--cs-line); border-left: 4px solid var(--cs-line);
  border-radius: var(--cs-radius); padding: 14px 18px; margin: 10px 0; box-shadow: var(--cs-shadow);
}
.cs-ai-高 { border-left-color: var(--cs-navy); }
.cs-ai-中 { border-left-color: var(--cs-gold); }
.cs-ai-imp { font-size: .75rem; font-weight: 700; color: var(--cs-navy); white-space: nowrap; }
.cs-ai-view { font-size: .75rem; color: var(--cs-sub); border: 1px solid var(--cs-line); padding: 1px 8px; border-radius: 3px; }
.cs-ai-ask { background: var(--cs-cream); border-radius: var(--cs-radius); padding: 10px 14px; margin-top: 10px; }
.cs-ai-ask-to { font-weight: 700; color: var(--cs-navy); font-size: .9rem; }
.cs-ai-q { color: var(--cs-ink); line-height: 1.8; margin-top: 4px; }
.cs-ai-q::before { content: "質問　"; color: var(--cs-accent-text); font-weight: 700; }
.cs-ai-cand { margin-left: 8px; font-size: .75rem; font-weight: 400; color: var(--cs-accent-text); }
.cs-finding-items ul { margin: 4px 0 0; padding-left: 1.2em; }

.cs-flow { display: flex; flex-wrap: wrap; align-items: stretch; gap: 8px; margin: 12px 0; }
.cs-flow-box {
  flex: 1 1 150px; background: var(--cs-flow-bg); color: var(--cs-flow-ink); border-radius: var(--cs-radius); padding: 14px 16px;
  border-bottom: 3px solid var(--cs-gold);
}
.cs-flow-box b { color: var(--cs-flow-strong); display: block; margin-bottom: 4px; }
.cs-flow-box span { color: var(--cs-flow-sub); font-size: .85rem; line-height: 1.7; }
.cs-flow-arrow { align-self: center; color: var(--cs-accent-text); font-size: 1.4rem; }

.cs-table { border-collapse: collapse; width: 100%; background: var(--cs-paper); font-size: .92rem; }
.cs-table th { background: var(--cs-th-bg); color: var(--cs-th-ink); text-align: left; padding: 8px 12px; font-weight: 500; }
.cs-table td { border-bottom: 1px solid var(--cs-line); padding: 8px 12px; vertical-align: top; line-height: 1.7;
  overflow-wrap: anywhere; }
.cs-table-wrap { overflow: auto; border: 1px solid var(--cs-line); border-radius: var(--cs-radius); margin: 6px 0 12px; }
.cs-table-wrap .cs-table th { position: sticky; top: 0; z-index: 1; white-space: nowrap; }
.cs-table .cs-num-col { text-align: right; white-space: nowrap; }

/* タブ：帯の上に並べ、選んでいるタブは色の地にして、タブがあることと、どれを選んでいるかを分かりやすくする（色はテーマで決める）。
   Streamlit 1.66 のタブは、並び＝role="tablist"、1つのタブ＝data-testid="stTab"、選択中＝data-selected の印が付く
   （以前の版の data-baseweb="tab" では効かない。Streamlit を更新したら、ここが効いているか画面で確かめる） */
.stTabs [role="tablist"] {
  margin-top: 18px !important; background: var(--cs-tabs-bg) !important; border-radius: var(--cs-radius-lg); padding: 6px !important;
  gap: 6px !important; flex-wrap: nowrap !important; overflow-x: auto !important;  /* とても狭い画面だけ横にずらして見る */
}
.stTabs [role="tablist"]::after { display: none !important; }  /* 元の下線 */
.stTabs [data-testid="stTabsScrollLeft"], .stTabs [data-testid="stTabsScrollRight"] { display: none !important; }
/* タブは1行に並べ、帯の幅を均等に分ける。1つずつ薄い地を付け、隙間（6px）をはさんで別々のタブに見せる。
   文字の大きさは画面の幅に合わせて変え（11.5〜15px）、1行に収める。
   いちばんタブの多い影響分析の結果（7つ・件数つき）でも、幅1,280px以上の画面で1行に収まることを確認済み */
.stTabs [data-testid="stTab"] {
  flex: 1 1 auto; justify-content: center; min-width: max-content;  /* 文字の長さに合わせ、余りを均等に分ける */
  background: var(--cs-tab-bg) !important; color: var(--cs-tab-ink) !important;
  border-radius: var(--cs-pill); padding: 0 6px !important; transition: background .15s;
}
.stTabs [data-testid="stTab"] p { color: inherit !important; font-size: clamp(.72rem, .88vw, .8rem); white-space: nowrap; }
.stTabs [data-testid="stTab"]:hover { background: var(--cs-tab-hover-bg) !important; color: var(--cs-tab-hover-ink) !important; }
.stTabs [data-testid="stTab"][data-selected] { background: var(--cs-tab-on-bg) !important; color: var(--cs-tab-on-ink) !important; }
.stTabs [data-testid="stTab"][data-selected] p { font-weight: 700; }
.stTabs .react-aria-SelectionIndicator { display: none !important; }  /* 元の選択中の下線 */
/* 分析用データの準備：3つの方法から、共通の到達点（Excelの読み込み）へ流れを示す */
.cs-prep-arrow { text-align: center; color: var(--cs-navy); font-weight: 700; margin: 8px 0 12px; }
.cs-prep-mark { display: block; font-size: 1.6rem; line-height: 1.2; }
.cs-prep-text { min-height: 3.6em; line-height: 1.8; margin-bottom: 12px; }
@media (max-width: 640px) {
  .cs-prep-text { min-height: 0; }
  /* スマートフォン：帯の余白を詰め、見出しが単語の途中で折り返されないようにする */
  .cs-hero { padding: 16px 20px 14px; }
  .cs-hero h1, .cs-hero-title { font-size: 2.1rem !important; }
  /* 流れの図は縦に並べ、矢印も下向きにする */
  .cs-flow { flex-direction: column; }
  .cs-flow-box { flex: none; }
  .cs-flow-arrow { transform: rotate(90deg); line-height: 1; }
  /* タブは折り返して、すべて見えるようにする */
  .stTabs [role="tablist"] { flex-wrap: wrap !important; height: auto !important; overflow: visible !important; }
  .stTabs [data-testid="stTab"] { min-height: 2.2rem; }
  .stTabs [data-testid="stTab"] p { font-size: .8rem; }
}
[class*="st-key-excel_goal_"] { background: var(--cs-ai-panel-bg) !important; border: 2px solid var(--cs-ai-panel-border) !important; }
/* ホーム：短い見出し・3つの要点・文字だけのリンク。サンプルのボタンをいちばん目立たせる */
.cs-home-head { font-size: 1.12rem; font-weight: 700; color: var(--cs-ink); margin: 6px 0 0; }
/* ホームのヒーロー：左に説明と分かること、右に小さな関係図（ヒーローの高さを増やさない） */
/* 上の内側余白は 8px（ロゴと製品名を上寄りに見せる。外枠の上端はメニューの先頭の行とそろえたまま） */
.cs-home-hero { display: flex; gap: 28px; align-items: center; padding: 8px 32px 16px; margin-bottom: 12px; }
.cs-home-hero-main { flex: 1 1 auto; position: relative; z-index: 1; }
/* 製品名：ロゴ（48px）＋サンセリフ。読み込めないときは OS のサンセリフに切り替わる */
.cs-brand { display: flex; align-items: center; flex-wrap: wrap; gap: 6px 12px; margin: 0 0 14px; }
.cs-brand img { width: 48px; height: 48px; flex: none; }  /* 製品名（44px）と縦の中央をそろえる */
.cs-brand-name { font-family: 'Manrope', 'Inter', 'Segoe UI', 'Helvetica Neue', Arial, sans-serif; font-size: 2.75rem;
  font-weight: 700; line-height: 1.05; letter-spacing: -.015em; color: var(--cs-ink); }
.cs-brand-name span { color: #344C25; }
.cs-brand-tag { font-size: .85rem; font-weight: 600; color: var(--cs-sub); border-left: 1px solid var(--cs-line);
  padding-left: 12px; margin-left: 2px; }
.cs-home-hero .cs-hero-lead { font-size: 1.2rem; margin-bottom: 4px; }
.cs-home-hero .cs-hero-sub { line-height: 1.7; font-size: .95rem; }
.cs-home-facts { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-top: 8px; }
.cs-home-facts b { font-size: .85rem; color: var(--cs-sub); margin-right: 2px; }
.cs-home-facts span { background: var(--cs-cream); border: 1px solid var(--cs-note-line); border-radius: var(--cs-pill);
  padding: 4px 12px; font-size: .9rem; font-weight: 600; color: var(--cs-ink); }
.cs-mini-map { flex: 0 0 210px; position: relative; z-index: 1; display: flex; flex-direction: column; align-items: center; }
.cs-mini-node { width: 100%; text-align: center; background: #fff; border: 1px solid var(--cs-line); border-radius: 8px;
  padding: 6px 8px; font-size: .85rem; font-weight: 600; color: var(--cs-ink); }
.cs-mini-node small { margin-left: 6px; font-size: .72rem; font-weight: 700; }
.cs-mini-start { background: var(--cs-gold); border-color: var(--cs-gold); color: var(--cs-ink); }
.cs-mini-line { width: 1px; height: 14px; background: var(--cs-sub); }
.cs-mini-caption { margin-top: 6px; font-size: .75rem; color: var(--cs-sub); }
@media (max-width: 640px) {
  .cs-home-hero { flex-direction: column; align-items: stretch; padding: 16px 18px; }
  .cs-brand-name { font-size: 1.75rem; }
  .cs-brand-tag { flex-basis: 100%; border-left: none; padding-left: 0; margin-left: 0; }
  .cs-brand img { width: 38px; height: 38px; }
  .cs-mini-map { flex: none; }
}
.cs-home-lead { font-size: .95rem; color: var(--cs-sub); margin-bottom: 8px; }
.cs-home-note { text-align: center; font-size: .9rem; color: var(--cs-sub); margin-top: -6px; padding-bottom: 14px; }
.cs-facts { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 10px; margin: 8px 0 14px; }
.cs-facts div { background: var(--cs-cream); border-left: 3px solid var(--cs-gold); border-radius: var(--cs-radius);
  padding: 10px 14px; font-size: .95rem; font-weight: 500; color: var(--cs-ink); }
.st-key-home_sample button { min-height: 2.9rem; box-shadow: 0 0 0 3px var(--cs-ai-button-ring); }
.st-key-home_sample button p { font-size: 1.08rem !important; font-weight: 700 !important; }
.st-key-home_compare button { min-height: 2.9rem; }
[class*="st-key-text_link_home_guide"]:not([class*="_end"]) { padding-top: .9rem; }
.st-key-home_prepare_upload button { border: 1.5px solid var(--cs-navy) !important; font-weight: 700; }
[class*="st-key-text_link_"] { gap: 0 !important; }
[data-testid="stMain"] [class*="st-key-text_link_"] [data-testid="stPageLink"] a {
  background: transparent !important; border: none !important; padding: 0 !important; min-height: 0 !important; box-shadow: none !important; }
[data-testid="stMain"] [class*="st-key-text_link_"] [data-testid="stPageLink"] a * {
  color: var(--cs-navy) !important; text-decoration: underline; font-size: .95rem; }
/* サンプル体験の進行と終わりの表示。状態は色だけでなく文字（完了・いまここ）でも示す */
.cs-demo-steps { display: flex; flex-wrap: wrap; align-items: center; gap: 6px 8px; margin: 4px 0 10px; font-size: .92rem; }
.cs-demo-step { padding: 5px 12px; border-radius: var(--cs-pill); border: 1px solid var(--cs-line); color: var(--cs-sub); background: var(--cs-paper); }
.cs-demo-step small { margin-left: 6px; font-size: .75rem; font-weight: 700; }
.cs-demo-done { background: var(--cs-cream); color: var(--cs-navy); border-color: var(--cs-gold); }
.cs-demo-now { background: var(--cs-navy); color: #fff; border-color: var(--cs-navy); font-weight: 700; }
.cs-demo-arrow { color: var(--cs-sub); }
.cs-demo-end { background: var(--cs-ai-panel-bg); border: 2px solid var(--cs-ai-panel-border); border-radius: var(--cs-radius-lg);
  padding: 16px 20px; margin: 14px 0 10px; line-height: 1.8; color: var(--cs-ink); }
.cs-demo-badge { display: inline-block; background: var(--cs-gold); color: var(--cs-ink); font-weight: 700; font-size: .8rem;
  border-radius: var(--cs-pill); padding: 2px 12px; margin-bottom: 6px; }
.cs-demo-end-title { font-size: 1.15rem; font-weight: 700; color: var(--cs-navy); margin-bottom: 4px; }
.cs-conclusion-risk { display: block; font-size: .85rem; color: var(--cs-concl-faint); margin-top: 2px; }
.cs-demo-end-note { font-size: .88rem; color: var(--cs-sub); margin-top: 4px; }
.cs-option-card { background: var(--cs-paper); border: 1px solid var(--cs-line); border-radius: var(--cs-radius-lg);
  padding: 14px 18px; box-shadow: var(--cs-shadow); height: 100%; }
.cs-option-title { font-size: 1.05rem; font-weight: 700; color: var(--cs-navy); margin-bottom: 6px; }
.cs-option-label { font-size: .8rem; font-weight: 700; color: var(--cs-sub); margin-top: 10px; }
.cs-option-line { font-size: .93rem; line-height: 1.7; color: var(--cs-ink); }
.cs-action-overview { margin: 4px 0 8px 1.2rem; line-height: 1.9; color: var(--cs-ink); }
.cs-page-hero { padding: 14px 32px 16px; }
.cs-page-title { font-family: 'Manrope', 'Inter', 'Segoe UI', 'Helvetica Neue', Arial, var(--cs-heading-font), sans-serif;
  font-size: 2.25rem; font-weight: 700; line-height: 1.2; letter-spacing: -.01em; color: var(--cs-ink); margin-bottom: 6px;
  position: relative; z-index: 1; }
.cs-page-hero .cs-hero-sub { position: relative; z-index: 1; }
/* サイドバー上部の小さなブランド表示（44px のヘッダーの中に置き、メニューの位置は動かさない） */
[data-testid="stSidebarHeader"] [data-testid="stSidebarLogo"], [data-testid="stSidebarHeader"] img { height: 28px !important; max-width: 170px; }
.cs-reference { margin: 36px 0 6px; padding-top: 22px; border-top: 1px solid var(--cs-line); }
.cs-subsection { font-size: 1.08rem; font-weight: 700; color: var(--cs-navy); margin: 22px 0 6px;
  padding-left: 10px; border-left: 3px solid var(--cs-gold); }
.cs-footer { color: var(--cs-sub); font-size: .82rem; margin-top: 40px; padding-top: 14px; border-top: 1px solid var(--cs-line); }
</style>
"""


# Hugging Face のページの中（huggingface.co/spaces/...）では、アプリの枠が iframe-resizer で中身の高さまで伸び、
# 外側のページごとスクロールするため、サイドバーが流れていく。枠の高さを画面に合わせて止め、本文だけをスクロールさせる。
# 枠の外の画面の大きさが変わると getPageInfo がまた呼ばれる。枠の外から開いたとき（parentIFrame がない）は何もしない
_FIT_FRAME_SCRIPT = """<script>
if (!window.csFitFrame) {
  window.csFitFrame = true;
  let tries = 0;
  const timer = setInterval(() => {
    tries += 1;
    const frame = window.parentIFrame;
    if (!frame) {
      if (tries > 40) clearInterval(timer);
      return;
    }
    clearInterval(timer);
    frame.autoResize(false);
    frame.getPageInfo(info => frame.size(Math.max(400, info.clientHeight - Math.max(0, info.offsetTop - info.scrollTop))));
  }, 250);
}
</script>"""


def apply_global_style() -> None:
    """全画面共通のスタイルを読み込む（app.py から1回呼ぶ）。"""
    st.markdown(_GLOBAL_CSS, unsafe_allow_html=True)
    st.html(_FIT_FRAME_SCRIPT, unsafe_allow_javascript=True)


def html(markup: str) -> None:
    st.markdown(markup, unsafe_allow_html=True)


def hero(eyebrow: str, title: str, lead: str, sub: str) -> None:
    html(
        f'<div class="cs-hero"><div class="cs-eyebrow">{eyebrow}</div>'
        f'<div class="cs-hero-title">{title}</div><div class="cs-hero-rule"></div>'
        f'<div class="cs-hero-lead">{lead}</div><div class="cs-hero-sub">{sub}</div></div>'
    )


def section(eyebrow: str, title: str) -> None:
    """見出し。eyebrow（小さな英字の札）は空にすると出さない（結果画面では日本語の見出しだけにする）。"""
    label = f'<div class="cs-eyebrow">{eyebrow}</div>' if eyebrow else ""
    html(f'<div class="cs-section">{label}<div class="cs-section-title">{title}</div></div>')


def reference_heading(title: str) -> None:
    """サンプル体験の「詳しい結果を見る」で開く参考の見出し。上に区切り線を付け、体験の本編と分ける。"""
    html(f'<div class="cs-reference"><div class="cs-section-title">{title}</div></div>')


def subsection(title: str) -> None:
    """参考の見出しの中の小見出し（親の見出しより小さくする）。"""
    html(f'<div class="cs-subsection">{title}</div>')


def page_hero(title: str, sub: str) -> None:
    """トップ以外のページの見出しカード。製品名と同じ系統のサンセリフで、製品名より一段小さくする。"""
    html(f'<div class="cs-hero cs-page-hero"><div class="cs-page-title">{title}</div><div class="cs-hero-sub">{sub}</div></div>')


# 製品のマーク（トップの製品名の左とファビコンで使う）。画面には文字列として埋め込む
LOGO_PATH = Path(__file__).resolve().parent.parent / "assets" / "changescope-logo.svg"
WORDMARK_PATH = LOGO_PATH.with_name("changescope-wordmark.svg")  # サイドバー上部の、マーク＋製品名
_LOGO_URI = "data:image/svg+xml;base64," + base64.b64encode(LOGO_PATH.read_bytes()).decode("ascii")


def home_hero() -> None:
    """ホームのヒーロー。左に製品名・説明・分かること3項目、右に架空サンプルの小さな関係図。"""
    facts = "".join(f"<span>{t}</span>" for t in ("影響を受ける部門・役割", "影響経路と根拠", "確認が必要な事項"))
    nodes = [("勤怠管理システム", "変更", True), ("給与計算システム", "", False), ("経理部", "", False)]
    chain = '<div class="cs-mini-line"></div>'.join(
        f'<div class="cs-mini-node{" cs-mini-start" if start else ""}">{name}'
        f'{f"<small>{tag}</small>" if tag else ""}</div>' for name, tag, start in nodes)
    html(
        '<div class="cs-hero cs-home-hero"><div class="cs-home-hero-main">'
        f'<div class="cs-brand"><img src="{_LOGO_URI}" alt="">'
        '<div class="cs-brand-name">ChangeScope <span>AI</span></div>'
        '<div class="cs-brand-tag">変更影響分析</div></div>'
        '<div class="cs-hero-lead">その変更は、組織のどこに影響するのか。</div>'
        '<div class="cs-hero-sub">業務・システム・部門・データ・社内規程のつながりから、<br>変更の影響を'
        '<b>根拠</b>とともに示します。</div>'
        f'<div class="cs-home-facts"><b>分かること</b>{facts}</div></div>'
        f'<div class="cs-mini-map" aria-label="架空サンプルの影響の経路">{chain}'
        '<div class="cs-mini-caption">架空サンプル</div></div></div>'
    )


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


def conclusion(assessment, first_label: str = "まずやること") -> None:
    """分析結果の結論（総合判定・まずやること・意識すること）を、結果のいちばん上に表示する。

    責任部門の名前などアップロードされたデータを含むため、すべてエスケープする。
    """
    a = assessment
    stance = "".join(f"<li>{escape(s)}</li>" for s in a.stance)
    caution = f'<div class="cs-conclusion-caution">{escape(a.caution)}</div>' if a.caution else ""
    html(
        f'<div class="cs-conclusion">'
        f'<div class="cs-eyebrow">結論</div>'
        f'<div class="cs-conclusion-head"><span class="cs-level cs-level-{escape(a.level)}">影響の広さ {escape(a.level)}</span>'
        f'<span class="cs-conclusion-headline">{escape(a.headline)}</span></div>'
        f'<div class="cs-conclusion-meaning">{escape(a.meaning)}'
        '<span class="cs-conclusion-risk">リスクの大きさ：未評価（損失や業務停止の影響は評価していません）</span></div>'
        f'<div class="cs-conclusion-first"><b>{escape(first_label)}</b>{escape(a.first_step)}</div>'
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
    根拠の種類（登録済みのつながり・一般的な確認の観点・AIの推測）は色を変えて区別する。
    番号が実在しても指摘の内容が正しいとは限らないため、登録済みのつながりにも「内容は確認先に確かめる」と添える。
    """
    from changescope.oversight import GENERAL, REGISTERED

    body = ""
    for f in findings:
        basis_class = {REGISTERED: "cs-badge", GENERAL: "cs-badge-general"}.get(f.basis, "cs-badge-warn")
        contact = escape(f.contact) + ("" if f.contact_registered else '<span class="cs-ai-cand">未登録の部門候補</span>')
        evidence = "".join(f"<li>{escape(e)}</li>" for e in f.evidence)
        evidence_label = ("根拠にしたつながり（番号は照合済み。指摘の内容が正しいかは確認先に確かめてください）"
                          if f.basis == REGISTERED else "関連するつながり")
        body += (
            f'<div class="cs-ai-card cs-ai-{escape(f.importance)}"><div class="cs-finding-head">'
            f'<span class="cs-ai-imp">重要度 {escape(f.importance)}</span>'
            f'<span class="{basis_class}">{escape(f.basis)}</span>'
            f'<span class="cs-ai-view">{escape(f.viewpoint)}</span></div>'
            f'<div class="cs-finding-title">{escape(f.title)}</div>'
            f'<div class="cs-finding-detail">{escape(f.detail)}</div>'
            f'<div class="cs-ai-ask"><div class="cs-ai-ask-to">確認先：{contact}</div>'
            f'<div class="cs-ai-q">{escape(f.question)}</div></div>'
            f'{f"<div class=cs-finding-items>{evidence_label}<ul>{evidence}</ul></div>" if evidence else ""}'
            "</div>"
        )
    html(body)


AI_BUSY_KEY = "ai_busy"  # 押されたAIボタンの key（次の実行の最初に読んで消す）


def ai_button(label: str, key: str, disabled: bool = False, **kwargs) -> bool:
    """AIを呼ぶボタン。押されたら True を返す。二度押しで料金と回数が2回分かからないようにする。

    押されると、まず「押された」とだけ記録して画面を描き直す。描き直した画面ではボタン（とほかのAIボタン）を
    押せない状態で表示し、そのあとでAIを呼ぶ。AIの処理中に同じボタンを押すことはできない。
    """
    busy = st.session_state.pop(AI_BUSY_KEY, None)
    st.button(label, key=key, disabled=disabled or busy is not None,
              on_click=lambda: st.session_state.update({AI_BUSY_KEY: key}), **kwargs)
    return busy == key


def ai_spinner(task: str, estimate: str):
    """AIを待つ間の表示。経過時間・目安の時間・画面を離れたときのことを示す。"""
    return st.spinner(f"{task}（目安：{estimate}。画面を閉じたり、ほかのページへ移ったりすると、"
                      "結果は表示されません。料金はかかります）", show_time=True)


def open_upload(scroll: bool = False) -> None:
    """データ管理を「自社のデータを登録する」を選んだ状態で開く。scroll なら「③ アップロード」まで移動する。"""
    st.session_state.data_source = "own"
    st.session_state.data_scroll_upload = scroll
    st.switch_page("pages/data.py")


def data_preparation(key: str) -> None:
    """分析用データ（Excel）を準備する入口。ホームと使い方から使う。

    3つの作成方法は同じ重みで並べ（初心者向けなどの区別はしない）、共通の到達点の「読み込み」だけを目立たせる。
    """
    section("PREPARE DATA", "分析用データを準備する")
    st.write("分析にはExcelファイルを使用します。Excelは以下の3つの方法で準備できます。")
    ways = [
        ("① Excelで作成", "テンプレートに入力して、そのままアップロード", "Excelを準備する", "table_view", "excel"),
        ("② 図から作成", "画面上で関係図を描き、Excelに変換", "図を作成する", "account_tree", "diagram"),
        ("③ 文章からAIで作成", "業務内容を文章で伝え、Excelの下書きを生成", "AIで作成する", "auto_awesome", "text"),
    ]
    for column, (title, text, label, icon, way) in zip(st.columns(3), ways):
        with column, st.container(border=True):
            st.markdown(f"#### {title}")
            html(f'<div class="cs-prep-text">{text}</div>')  # 文の長さが違っても、3枚の高さをそろえる
            if st.button(label, key=f"{key}_{way}", icon=f":material/{icon}:", width="stretch"):
                if way == "excel":
                    open_upload()
                st.switch_page("pages/diagram.py" if way == "diagram" else "pages/extract.py")
    html('<div class="cs-prep-arrow"><span class="cs-prep-mark">↓</span>どの方法でも最終的にExcelファイルを作成</div>')
    with st.container(border=True, key=f"excel_goal_{key}"):
        if st.button("Excelを読み込んで分析開始", key=f"{key}_upload", type="primary", icon=":material/upload_file:",
                     width="stretch"):
            open_upload(scroll=True)
    st.page_link("pages/compare.py", label="読み込み後は変更案も比べられます",
                 icon=":material/compare_arrows:")


def data_entry(key: str) -> None:
    """自分のデータで分析する入口の短い版（ホーム用）。説明はツールチップと遷移先に置く。"""
    html('<div class="cs-home-head">自分のデータで分析する</div>'
         '<div class="cs-home-lead">Excelを直接用意するか、図・文章からExcelを作成できます（いずれもExcel形式に統一）。</div>')
    ways = [
        ("Excelで作成", "テンプレートに入力して、そのままアップロード", "table_view", "excel"),
        ("図から作成", "画面上で関係図を描き、Excelに変換", "account_tree", "diagram"),
        ("文章からAIで作成", "業務内容を文章で伝え、Excelの下書きを生成", "auto_awesome", "text"),
    ]
    for column, (label, help_text, icon, way) in zip(st.columns(3), ways):
        if column.button(label, key=f"{key}_{way}", icon=f":material/{icon}:", help=help_text, width="stretch"):
            if way == "excel":
                open_upload()
            st.switch_page("pages/diagram.py" if way == "diagram" else "pages/extract.py")
    if st.button("Excelをアップロードして分析開始", key=f"{key}_upload", icon=":material/upload_file:", width="stretch"):
        open_upload(scroll=True)


def text_link(page: str, label: str, key: str) -> None:
    """ボタンに見えない、文字だけのリンク。"""
    with st.container(key=f"text_link_{key}"):
        st.page_link(page, label=label)


def no_data_actions(purpose: str) -> None:
    """データが読み込まれていないときの案内。行き止まりにせず、次の操作を選べるようにする。"""
    st.write(f"{purpose}には、分析用データが必要です。サンプルで試すか、Excelを準備して読み込んでください。")
    c1, c2 = st.columns(2)
    if c1.button("サンプルデータで試す", key="no_data_sample", type="primary", icon=":material/play_arrow:",
                 width="stretch"):
        set_dataset(load_sample())
        st.rerun()
    if c2.button("分析用データを準備する", key="no_data_prepare", icon=":material/upload_file:", width="stretch"):
        open_upload()


def action_overview(actions) -> None:
    """対応手順の要点（見出しだけ）。詳細は折りたたみで見せる。"""
    items = "".join(f"<li>{escape(a.title)}</li>" for a in actions)
    html(f'<ol class="cs-action-overview">{items}</ol>')


DEMO_STEPS = ["変更を入力", "影響を確認", "デモ完了"]


def demo_progress(done: int) -> None:
    """サンプル体験の進行。done は完了したステップの数（3で体験完了）。色だけに頼らず、文字でも状態を示す。"""
    parts = []
    for n, label in enumerate(DEMO_STEPS, start=1):
        if n <= done:
            state, mark = ("now" if n == done == len(DEMO_STEPS) else "done"), "完了"
        else:
            state, mark = ("now", "いまここ") if n == done + 1 else ("todo", "")
        badge = f"<small>{mark}</small>" if mark else ""
        parts.append(f'<span class="cs-demo-step cs-demo-{state}">{"①②③"[n - 1]} {label}{badge}</span>')
    html(f'<div class="cs-demo-steps">{"<span class=cs-demo-arrow>→</span>".join(parts)}</div>')


def demo_end_card(summary: str, saved: bool) -> None:
    """サンプル体験の終わりの表示。体験の終わりと、実際の案件の確認・対応の完了を混同させない。"""
    extra = "PDFを保存しました。" if saved else ""
    html(f'<div class="cs-demo-end"><span class="cs-demo-badge">デモ完了</span>'
         f'<div class="cs-demo-end-title">サンプル体験はここまでです</div>'
         f'<div>{escape(summary)}</div>'
         f'<div class="cs-demo-end-note">{extra}架空の会社のデータによる体験です。実際の案件では、関係者への確認と対応が必要です。</div></div>')


def option_card(title: str, items: list[tuple[str, list[str]]]) -> None:
    """比較の各案の要約カード。項目は両案で同じ順にする。入力や登録データを含むため、すべてエスケープする。"""
    body = "".join(f'<div class="cs-option-label">{escape(label)}</div>'
                   + "".join(f'<div class="cs-option-line">{escape(line)}</div>' for line in lines) for label, lines in items)
    html(f'<div class="cs-option-card"><div class="cs-option-title">{escape(title)}</div>{body}</div>')


def ui_label(text: str) -> str:
    """画面上のボタン名などを、本文中で目立たせる。"""
    return f'<span class="cs-ui">{text}</span>'
