"""ChangeScope AI の入口。画面（ページ）の一覧を定義して表示する。

起動方法：streamlit run app.py
"""

import streamlit as st

from changescope.ui import LOGO_PATH, WORDMARK_PATH, apply_global_style

st.set_page_config(page_title="ChangeScope AI", page_icon=str(LOGO_PATH), layout="wide")
apply_global_style()
# サイドバー上部の小さなブランド表示。サイドバーを畳んだときは、マークだけを左上に出す
st.logo(str(WORDMARK_PATH), icon_image=str(LOGO_PATH), size="large")

pages = [
    st.Page("views/top.py", title="ホーム", icon=":material/home:", default=True),
    st.Page("views/guide.py", title="使い方・用語について", icon=":material/menu_book:"),
    st.Page("views/data.py", title="データ管理", icon=":material/folder_open:"),
    st.Page("views/extract.py", title="文章・資料から作る", icon=":material/auto_awesome:"),
    st.Page("views/diagram.py", title="図で入力する", icon=":material/account_tree:"),
    st.Page("views/analysis.py", title="影響分析", icon=":material/troubleshoot:"),
    st.Page("views/compare.py", title="変更案を比べる", icon=":material/compare_arrows:"),
    # 以前の住所 /home の中継。メニューには出さない（ui.py の CSS で隠す）
    st.Page("views/home_alias.py", title="ホーム", url_path="home"),
]
st.navigation(pages).run()
