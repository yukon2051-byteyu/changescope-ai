"""ホーム画面：システムの紹介と、はじめての人がすぐ試せる入口。"""

import streamlit as st

from changescope.datasets import load_sample
from changescope.ui import cards, hero, html, note, section, set_dataset, ui_label

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
    ("STEP 1", "データを用意する",
     "サンプルで試すか、自社の業務・システム・部門とそのつながりを登録します。"
     "登録は2通り：Excelにまとめて書く／「図で入力する」で1つずつ作る。"),
    ("STEP 2", "変更内容を入力する",
     "「勤怠管理システムをクラウドに変更したい」のように文章で入力し、分析の出発点を確定します。"),
    ("STEP 3", "影響と根拠を確認する",
     "誰に・どこに影響するか、どれくらい大きいか、その根拠は何かを確認します。"),
])

html(
    '<div class="cs-footer">影響の分析は、登録されたつながりをプログラムでたどって行います。'
    "AIを使うのは、分析結果の「AIで確認漏れを調べる」だけです。変更案の比較・PDFレポートは今後追加予定です。"
    "サンプルデータはすべて架空のものです。</div>"
)
