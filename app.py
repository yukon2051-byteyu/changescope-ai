"""ChangeScope AI の入口。画面（ページ）の一覧を定義して表示する。

起動方法：streamlit run app.py
"""

import streamlit as st

from changescope.ui import LOGO_PATH, apply_global_style

st.set_page_config(page_title="ChangeScope AI", page_icon=str(LOGO_PATH), layout="wide")
apply_global_style()

pages = [
    st.Page("pages/home.py", title="ホーム", icon=":material/home:", default=True),
    st.Page("pages/guide.py", title="使い方・用語について", icon=":material/menu_book:"),
    st.Page("pages/data.py", title="データ管理", icon=":material/folder_open:"),
    st.Page("pages/extract.py", title="文章・資料から作る", icon=":material/auto_awesome:"),
    st.Page("pages/diagram.py", title="図で入力する", icon=":material/account_tree:"),
    st.Page("pages/analysis.py", title="影響分析", icon=":material/troubleshoot:"),
    st.Page("pages/compare.py", title="変更案を比べる", icon=":material/compare_arrows:"),
]
st.navigation(pages).run()
