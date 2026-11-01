"""ChangeScope AI の入口。画面（ページ）の一覧を定義して表示する。

起動方法：streamlit run app.py
"""

import streamlit as st

from changescope.ui import apply_global_style

st.set_page_config(page_title="ChangeScope AI", page_icon=":material/hub:", layout="wide")
apply_global_style()

pages = [
    st.Page("pages/home.py", title="ホーム", icon=":material/home:", default=True),
    st.Page("pages/guide.py", title="使い方・用語について", icon=":material/menu_book:"),
    st.Page("pages/data.py", title="データ管理", icon=":material/folder_open:"),
    st.Page("pages/analysis.py", title="影響分析", icon=":material/troubleshoot:"),
]
st.navigation(pages).run()
