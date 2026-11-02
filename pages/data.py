"""データ管理画面：サンプルデータ、または記入したExcelテンプレート（上級者はCSV）を読み込む。"""

import pandas as pd
import streamlit as st

from changescope import models
from changescope.datasets import SAMPLE_DIR, load_from_csv, load_from_excel, load_sample
from changescope.excel_template import build_template
from changescope.ui import data_table, get_dataset, set_dataset, show_mode_banner

MAX_SHOWN_ISSUES = 50
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@st.cache_data
def blank_template() -> bytes:
    return build_template()


@st.cache_data
def sample_workbook() -> bytes:
    sample = load_sample()
    return build_template(sample.elements, sample.dependencies)


def show_load_errors(result) -> None:
    st.error(f"エラーが {len(result.errors)} 件あるため、読み込めませんでした。修正して再度アップロードしてください。")
    st.markdown("\n".join(f"- {e}" for e in result.errors[:MAX_SHOWN_ISSUES]))
    if len(result.errors) > MAX_SHOWN_ISSUES:
        st.caption(f"ほか {len(result.errors) - MAX_SHOWN_ISSUES} 件")


st.title("データ管理")
show_mode_banner(get_dataset())

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
        set_dataset(load_sample())
        st.rerun()
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
        c1.download_button("白紙テンプレート（記入例3行入り）", blank_template(),
                           "ChangeScope_テンプレート.xlsx", XLSX_MIME, type="primary", width="stretch", icon=":material/download:")
        c2.download_button("記入済みの例（サンプル商事の全データ）", sample_workbook(),
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
                set_dataset(result.dataset)
                st.rerun()

    with st.expander("CSVで登録する（上級者向け）"):
        st.markdown(
            "**要素CSV** 必須列：`element_id`, `name`, `element_type`　任意列：`description`, `owner`, `aliases`（「;」区切り）\n\n"
            "**依存関係CSV** 必須列：`dependency_id`, `from_id`, `to_id`, `relation_type`, `direction`, `evidence`, `status`　任意列：`note`\n\n"
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
                set_dataset(result.dataset)
                st.rerun()

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
                "ID": elements["element_id"],
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
                "ID": deps["dependency_id"],
                "影響元": deps["from_id"].map(names),
                "影響先": deps["to_id"].map(names),
                "関係": deps["relation_type"].map(models.relation_type_label),
                "向き": deps["direction"].map(models.DIRECTIONS),
                "確認状態": deps["status"].map(models.STATUSES),
                "根拠": deps["evidence"],
                "補足": deps.get("note", ""),
            }),
        )
    st.page_link("pages/analysis.py", label="影響分析へ進む", icon=":material/troubleshoot:")
