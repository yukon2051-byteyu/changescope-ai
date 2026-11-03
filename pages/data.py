"""データ管理画面：サンプルデータ、または記入したExcelテンプレート（上級者はCSV）を読み込む。"""

import hashlib
from pathlib import Path

import pandas as pd
import streamlit as st

from changescope import excel_template, models, theme
from changescope.datasets import SAMPLE_DIR, load_from_csv, load_from_excel, load_sample
from changescope.excel_template import build_template
from changescope.ui import data_table, get_dataset, note, set_dataset, show_mode_banner, ui_label

MAX_SHOWN_ISSUES = 50
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def template_version() -> str:
    """テンプレートを作る処理・区分値・サンプルデータの目印。

    st.cache_data は、キャッシュした関数自体が変わらない限り、アプリを再起動するまで古い結果を返す。
    テンプレートを作る処理などが変わったら作り直すよう、関係するファイルの中身から目印を作り、引数に渡す。
    """
    files = [excel_template.__file__, models.__file__, theme.__file__,  # テーマを切り替えたら色も作り直す
             SAMPLE_DIR / "elements.csv", SAMPLE_DIR / "dependencies.csv"]
    return hashlib.sha256(b"".join(Path(f).read_bytes() for f in files)).hexdigest()


@st.cache_data
def blank_template(version: str) -> bytes:
    return build_template()


@st.cache_data
def sample_workbook(version: str) -> bytes:
    sample = load_sample()
    return build_template(sample.elements, sample.dependencies)


def show_load_errors(result) -> None:
    st.error(f"エラーが {len(result.errors)} 件あるため、読み込めませんでした。修正して再度アップロードしてください。")
    st.markdown("\n".join(f"- {e}" for e in result.errors[:MAX_SHOWN_ISSUES]))
    if len(result.errors) > MAX_SHOWN_ISSUES:
        st.caption(f"ほか {len(result.errors) - MAX_SHOWN_ISSUES} 件")


def finish_loading(dataset, where: str) -> None:
    """読み込みが終わったことを、押したボタンのすぐ下に出すための印を付けて、画面を更新する。"""
    set_dataset(dataset)
    st.session_state.data_loaded_at = where
    st.session_state.data_loaded_toast = True
    st.rerun()


def loaded_notice(where: str) -> None:
    """読み込みが終わったことと、次にやることを、押したボタンのすぐ下に目立たせて出す。"""
    dataset = get_dataset()
    if dataset is None or st.session_state.get("data_loaded_at") != where:
        return
    st.success(f"読み込みが完了しました（要素 {len(dataset.elements)}件・つながり {len(dataset.dependencies)}本）。"
               "次は「影響分析」で、変えたいことを入力して分析します。", icon=":material/check_circle:")
    c1, c2, _ = st.columns([1, 1, 1])
    if c1.button("影響分析へ進む", type="primary", icon=":material/arrow_forward:", width="stretch",
                 key=f"go_analysis_{where}"):
        st.switch_page("pages/analysis.py")
    if c2.button("図で開いて確認する", icon=":material/account_tree:", width="stretch", key=f"go_diagram_{where}"):
        st.switch_page("pages/diagram.py")


st.title("データ管理")
if st.session_state.pop("data_loaded_toast", False):
    st.toast("読み込みが完了しました", icon=":material/check_circle:")
show_mode_banner(get_dataset())
note("<b>登録のしかたは3つあります。</b>この画面では、Excelにまとめて書いて読み込みます。"
     f"図を見ながら1つずつ作りたいときは {ui_label('図で入力する')}（はじめての方におすすめ）、"
     f"文章からAIで図のたたき台を作りたいときは {ui_label('文章・資料から作る')} を使ってください。"
     "ここで読み込んだデータも、「図で入力する」で開いて確認・修正できます。")
c_link1, c_link2, _ = st.columns([1, 1, 2])
c_link1.page_link("pages/diagram.py", label="図で入力する", icon=":material/account_tree:")
c_link2.page_link("pages/extract.py", label="文章・資料から作る", icon=":material/auto_awesome:")

source = st.radio(
    "使用するデータ",
    ["sample", "own"],
    format_func={"sample": "まずはサンプルで試す", "own": "自社のデータを登録する"}.get,
    horizontal=True,
)

if source == "sample":
    st.write(
        "架空の会社「サンプル商事株式会社」の人事・経理・営業・情報システム部門のデータです。"
        "業務・システム・部門・データ・帳票・規程など57件と、それらのつながり（依存関係）75件を収録しています。"
    )
    if st.button("サンプルデータを読み込む", type="primary"):
        finish_loading(load_sample(), "sample")
    loaded_notice("sample")
else:
    st.warning(
        "個人情報・機密情報は記入しないでください。"
        "アップロードしたデータはこの画面を開いている間だけ使われ、サーバーには保存されません。"
    )

    with st.container(border=True):
        st.markdown("#### ① テンプレートをダウンロード")
        st.write(
            "Excelのテンプレートに、自社の業務・システム・部門などと、そのつながりを記入します。"
            "記入方法は、ファイル内の「使い方」シートに書いてあります。種類や確認状態はプルダウンで選べます。"
        )
        c1, c2 = st.columns(2)
        c1.download_button("白紙テンプレート（記入例3行入り）", blank_template(template_version()),
                           "ChangeScope_テンプレート.xlsx", XLSX_MIME, type="primary", width="stretch", icon=":material/download:")
        c2.download_button("記入済みの例（サンプル商事の全データ）", sample_workbook(template_version()),
                           "ChangeScope_記入例_サンプル商事.xlsx", XLSX_MIME, width="stretch",
                           icon=":material/download:")

    with st.container(border=True):
        st.markdown("#### ② 記入する")
        st.markdown(
            "- **「要素」シート**：業務・システム・部門・役割・データ・帳票・外部サービス・社内規程を1行ずつ\n"
            "- **「依存関係」シート**：「影響元が変わると影響先に影響が出る」向きで、つながりを1行ずつ\n"
            "- **根拠と確認状態**：その関係を何で確認したか。推測や未確認のものも登録しておくと、"
            "分析結果で「要確認」として表示されます"
        )

    with st.container(border=True):
        st.markdown("#### ③ アップロード")
        workbook = st.file_uploader("記入したExcelファイル（.xlsx）", type=["xlsx"])
        if st.button("検証して読み込む", type="primary", disabled=workbook is None):
            result = load_from_excel(workbook.getvalue())
            if result.dataset is None:
                show_load_errors(result)
            else:
                finish_loading(result.dataset, "excel")
        loaded_notice("excel")

    with st.expander("CSVで登録する（上級者向け）"):
        st.markdown(
            "**要素CSV** 必須列：`name`, `element_type`　任意列：`element_id`（空欄なら自動）, `description`, `owner`, `aliases`（「;」区切り）\n\n"
            "**依存関係CSV** 必須列：`from_id`, `to_id`, `relation_type`, `direction`, `evidence`, `status`　任意列：`dependency_id`（空欄なら自動）, `note`\n\n"
            "`from_id`・`to_id`・`owner` は、要素のIDでも名前でも指定できます。同じ名前の要素は登録できません。\n\n"
            "区分値は英語のコードで記入します（例：`system`, `uses`, `one_way`, `confirmed`）。一覧はExcelテンプレートの「選択肢」シートと同じです。"
        )
        c1, c2 = st.columns(2)
        c1.download_button("要素CSVの例", (SAMPLE_DIR / "elements.csv").read_bytes(), "elements.csv", "text/csv")
        c2.download_button("依存関係CSVの例", (SAMPLE_DIR / "dependencies.csv").read_bytes(), "dependencies.csv", "text/csv")
        elements_file = st.file_uploader("要素CSV", type=["csv"])
        dependencies_file = st.file_uploader("依存関係CSV", type=["csv"])
        if st.button("CSVを検証して読み込む", disabled=not (elements_file and dependencies_file)):
            result = load_from_csv(elements_file.getvalue(), dependencies_file.getvalue())
            if result.dataset is None:
                show_load_errors(result)
            else:
                finish_loading(result.dataset, "csv")
        loaded_notice("csv")

dataset = get_dataset()
if dataset is not None:
    st.divider()
    st.success(f"読み込み済み：要素 {len(dataset.elements)} 件・依存関係 {len(dataset.dependencies)} 件")
    if dataset.warnings:
        with st.expander(f"読み込み時の警告 {len(dataset.warnings)} 件（自動で除外・統合した内容）", expanded=True,
                     icon=":material/warning:"):
            st.markdown("\n".join(f"- {w}" for w in dataset.warnings[:MAX_SHOWN_ISSUES]))

    names = dict(zip(dataset.elements["element_id"], dataset.elements["name"]))
    tab1, tab2 = st.tabs(["要素一覧", "依存関係一覧"])
    with tab1:
        type_filter = st.multiselect(
            "種類で絞り込み",
            # もとからある8種類に、データ内で使われている追加の種類を加える
            list(dict.fromkeys([*models.ELEMENT_TYPES, *dataset.elements["element_type"]])),
            format_func=models.element_type_label,
        )
        elements = dataset.elements
        if type_filter:
            elements = elements[elements["element_type"].isin(type_filter)]
        data_table(
            pd.DataFrame({
                "名前": elements["name"],
                "種類": elements["element_type"].map(models.element_type_label),
                "責任部門・担当": elements.get("owner", pd.Series("", index=elements.index)).map(lambda o: names.get(o, o)),
                "説明": elements.get("description", ""),
            }),
        )
    with tab2:
        deps = dataset.dependencies
        data_table(
            pd.DataFrame({
                "影響元": deps["from_id"].map(names),
                "影響先": deps["to_id"].map(names),
                "関係": deps["relation_type"].map(models.relation_type_label),
                "向き": deps["direction"].map(models.DIRECTIONS),
                "確認状態": deps["status"].map(models.STATUSES),
                "根拠": deps["evidence"],
                "補足": deps.get("note", ""),
            }),
        )
    if st.button("影響分析へ進む", type="primary", icon=":material/arrow_forward:", key="go_analysis_bottom"):
        st.switch_page("pages/analysis.py")
