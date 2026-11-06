"""ホーム画面：製品の価値を短時間で伝え、すぐにサンプルを試せる入口。詳しい説明は「使い方・用語について」に置く。"""

import streamlit as st

from changescope.datasets import load_sample
from changescope.ui import data_entry, get_dataset, hero, html, set_dataset, text_link

hero(
    "CHANGE IMPACT ANALYSIS",
    "ChangeScope AI",
    "その変更は、組織のどこに影響するのか。",
    "業務・システム・部門・データ・社内規程のつながりをもとに、"
    "変更によって<b>誰に</b>・<b>どこに</b>影響が出るかを、<b>根拠</b>とともに示します。",
)

c1, c2, c3 = st.columns([1.15, 1.15, 0.7])
if c1.button("サンプルで試す（約3分）", key="home_sample", type="primary", icon=":material/play_arrow:", width="stretch"):
    set_dataset(load_sample())
    st.session_state.demo_prefill = True  # 最初の入力例を入れた状態で始める
    st.switch_page("pages/analysis.py")
c1.caption("架空の企業データで影響分析を体験")
if c2.button("変更案を比べる", key="home_compare", icon=":material/compare_arrows:", width="stretch"):
    if get_dataset() is None:  # データがなければサンプルで開く（入力例のボタンですぐに比べられる）
        set_dataset(load_sample())
    st.switch_page("pages/compare.py")
c2.caption("複数案の影響・未確認事項を比較")
with c3:
    text_link("pages/guide.py", "使い方を詳しく見る", "home_guide")

data_entry("home_prepare")

html('<div class="cs-home-head">ChangeScope AIで分かること</div>'
     '<div class="cs-facts"><div>影響を受ける部門・役割</div><div>影響が伝わる経路と根拠</div><div>確認が必要な事項</div></div>')

text_link("pages/guide.py", "詳しい使い方を見る", "home_guide_end")
