"""以前の住所 /home で開かれたときの中継（メニューには出さない）。すぐにトップ画面へ切り替える。

画面のフォルダが pages/ だった頃は /home でホームが開けたため、その住所のブックマークや履歴から来ても
英語の「Page not found」を出さずにトップへ案内する。
"""

import streamlit as st

st.switch_page("views/top.py")
