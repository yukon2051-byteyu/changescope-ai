"""ホーム画面：システムの紹介と、はじめての人がすぐ試せる入口。"""

import streamlit as st

from changescope.datasets import load_sample
from changescope.ui import cards, data_preparation, hero, html, note, section, set_dataset, ui_label

hero(
    "CHANGE IMPACT ANALYSIS",
    "ChangeScope AI",
    "その変更は、組織のどこに影響するのか。",
    "業務・システム・部門・データ・社内規程のつながりをもとに、"
    "変更によって<b>誰に</b>・<b>どこに</b>影響が出るかを、<b>根拠</b>とともに示します。",
)

note(
    "<b>はじめての方へ</b>　最初に覚えることはありません。"
    f"下の {ui_label('サンプルで試す')} を押すと、架空の会社のデータが読み込まれ、分析画面が開きます。"
    "あとは入力例のボタンを押して分析するだけです（約3分）。"
)


c1, c2, _ = st.columns([1, 1, 2])
if c1.button("サンプルで試す", type="primary", icon=":material/play_arrow:", width="stretch"):
    set_dataset(load_sample())
    st.switch_page("pages/analysis.py")
c2.page_link("pages/guide.py", label="使い方を詳しく見る", icon=":material/menu_book:")

section("WHAT TO DO", "目的から選ぶ")
c1, c2 = st.columns(2)
with c1, st.container(border=True):
    st.markdown("#### A. 変更の影響を調べる")
    st.write("変更による影響範囲やリスクを洗い出す")
    st.page_link("pages/analysis.py", label="影響分析を開く", icon=":material/search:")
with c2, st.container(border=True):
    st.markdown("#### B. 複数の変更案を比べる")
    st.write("各案の影響やリスクを比較して検討する")
    st.page_link("pages/compare.py", label="変更案を比べる", icon=":material/compare_arrows:")

data_preparation("home_prepare")

section("WHAT YOU CAN DO", "できること")
cards([
    ("01", "誰に影響するかが分かる",
     "影響を受ける部門・役割を、変更対象の責任部門を先頭に、影響の大きい順で一覧にします。"),
    ("02", "なぜ影響するかをたどれる",
     "「勤怠管理システム → 勤怠実績データ → 月次給与計算」のように、影響が伝わる経路と根拠資料を確認できます。"),
    ("03", "確認が必要なことが分かる",
     "推定や未確認の情報を含む影響を「要確認」として区別し、関係者に確認すべき点を明らかにします。"),
])

section("HOW IT WORKS", "利用の流れ")
cards([
    ("STEP 1", "分析用Excelを準備",
     "Excelで直接作成するか、図から変換するか、文章からAIで生成します。"),
    ("STEP 2", "Excelをアップロード",
     "「データ管理」で読み込みます。記入内容は自動でチェックされます。"),
    ("STEP 3", "変更影響を分析",
     "変更内容を文章で入力し、誰に・どこに影響するかを根拠とともに確認します。"),
    ("STEP 4", "必要に応じて変更案を比較",
     "2つの変更案の違いを並べて検討します。結果はPDFで持ち帰れます。"),
])

html(
    '<div class="cs-footer">影響の分析は、登録されたつながりをプログラムでたどって行います。'
    "AIを使うのは、「AIで確認漏れを調べる」と「文章・資料から作る」だけです。結果はPDFで持ち帰れます。"
    "サンプルデータはすべて架空のものです。</div>"
)
