"""ホーム画面：何が分かるツールで、どこから始めるかを1画面で伝える入口。詳しい説明は「使い方・用語について」に置く。"""

import streamlit as st

from changescope.datasets import load_sample
from changescope.ui import data_entry, get_dataset, home_hero, set_dataset, text_link

home_hero()

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
