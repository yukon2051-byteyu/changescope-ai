"""Excelテンプレートの作成と読み込み。

業務部門の担当者がCSVの列名や区分値を覚えなくても記入できるよう、
日本語の見出し・選択肢のプルダウン・説明シート付きのExcelを提供する。
読み込み時は日本語の見出し・選択肢をCSVの形式に変換し、CSVと同じ検証処理に渡す。
"""

from __future__ import annotations

import io

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.worksheet.datavalidation import DataValidation

from changescope import models
from changescope.csv_validator import MAX_DEPENDENCY_ROWS, MAX_ELEMENT_ROWS, MAX_FILE_BYTES

ELEMENTS_SHEET = "要素"
DEPENDENCIES_SHEET = "依存関係"
CHOICES_SHEET = "選択肢"
GUIDE_SHEET = "使い方"

FONT_NAME = "メイリオ"
# 配色：白・薄いグレー基調、文字は濃紺、差し色に金（Web画面と同じ方針）
INK = "1E2A33"  # 本文・見出しの文字色（濃紺）
SUB_INK = "6B7780"  # 補足の文字色（グレー）
_REQUIRED_FILL = PatternFill("solid", fgColor=INK)  # 必須の見出し：濃紺
_OPTIONAL_FILL = PatternFill("solid", fgColor="EEF1F3")  # 任意の見出し：薄いグレー
_REQUIRED_FONT = Font(name=FONT_NAME, bold=True, color="FFFFFF")
_OPTIONAL_FONT = Font(name=FONT_NAME, bold=True, color=INK)
GOLD = "B8963E"  # 差し色（金）
_HEADER_BORDER = Border(bottom=Side(style="medium", color=GOLD))

# 列幅：Excelの列幅は「標準フォントの数字1文字の幅」が単位。メイリオ11ptの数字の幅は 9px（96dpiで実測）
_DIGIT_WIDTH_PX = 9
FIRST_COLUMN_CM = 4.0


def cm_to_width(cm: float) -> float:
    """cmをExcelの列幅に換算する（96dpi基準。画面の拡大率により多少の誤差がある）。"""
    return round(cm / 2.54 * 96 / _DIGIT_WIDTH_PX, 2)

# 白紙テンプレートに入れる記入例（架空）
_EXAMPLE_ELEMENTS = pd.DataFrame([
    {"element_id": "SYS-001", "name": "経費精算システム", "element_type": "system",
     "description": "経費申請と承認を行うシステム", "owner": "DEP-001", "aliases": "経費システム"},
    {"element_id": "PRC-001", "name": "経費精算業務", "element_type": "process",
     "description": "申請→上長承認→経理確認", "owner": "DEP-001", "aliases": "経費精算"},
    {"element_id": "DEP-001", "name": "経理部", "element_type": "department",
     "description": "", "owner": "", "aliases": "経理"},
])
_EXAMPLE_DEPENDENCIES = pd.DataFrame([
    {"dependency_id": "D-001", "from_id": "SYS-001", "to_id": "PRC-001", "relation_type": "uses",
     "direction": "both", "evidence": "経費精算システム操作マニュアル", "status": "confirmed",
     "note": "承認ルートはシステムの設定で管理"},
    {"dependency_id": "D-002", "from_id": "PRC-001", "to_id": "DEP-001", "relation_type": "performs",
     "direction": "one_way", "evidence": "経理部ヒアリング", "status": "unconfirmed", "note": ""},
])

_GUIDE = [
    ("ChangeScope AI データ記入テンプレート", ""),
    ("", ""),
    ("【記入の手順】", ""),
    ("1", "「要素」シートに、業務・システム・部門・データ・帳票・規程などを1行ずつ記入します。"),
    ("2", "「依存関係」シートに、要素どうしのつながりを1行ずつ記入します。"),
    ("3", "記入例の行は、自社の内容に書き換えるか削除してください。"),
    ("4", "保存したExcelファイルを、ChangeScope AIの「データ管理」画面でアップロードします。"),
    ("", ""),
    ("【大切なルール】", ""),
    ("影響の向き", "「影響元が変わると、影響先に影響が出る」向きで登録します。"
                  "例：勤怠管理システム（影響元）→ 月次給与計算（影響先）"),
    ("双方向", "どちらが変わっても相手に影響する場合は、影響の向きを「双方向」にします。"),
    ("根拠", "その関係を何で確認したか（資料名・ヒアリング相手など）を必ず書きます。"),
    ("確認状態", "資料や関係者に確認済みなら「確認済」、推測なら「推定」、未確認なら「未確認」。"
                "未確認の関係も登録しておくと、確認が必要な事項として分析結果に表示されます。"),
    ("見出しの色", "濃紺の見出しは必須、薄いグレーの見出しは任意です。見出しの文字は変更しないでください。"),
    ("要素ID", "重複しない記号を付けます（例：SYS-001）。依存関係シートではこのIDで要素を指定します。"),
    ("注意", "個人情報・機密情報は記入しないでください。"),
    ("", ""),
    ("【関係の種類】", "（影響元 → 影響先 の例）"),
    *[(label, example) for label, example in [
        ("データを提供する", "勤怠管理システム → 勤怠実績データ"),
        ("利用する", "勤怠実績データ → 月次給与計算（データを業務で使う）"),
        ("システム連携する", "経費精算システム → 会計システム"),
        ("業務を担当する", "月次給与計算 → 人事部（業務の担当部門・担当者）"),
        ("承認する", "経費精算業務 → 承認者（課長）"),
        ("規程に従う", "経費精算業務 → 経費規程"),
        ("帳票を作成する", "給与計算システム → 給与明細"),
        ("その他の依存", "社内ファイルサーバー → 顧客管理Excel（保存場所）"),
    ]],
]


def _write_sheet(ws, df: pd.DataFrame, headers: dict[str, str], required: list[str],
                 choices: dict[str, dict[str, str]]) -> None:
    ws.append([headers[c] for c in headers])
    ws.row_dimensions[1].height = 24
    for cell, column in zip(ws[1], headers):
        is_required = column in required
        cell.fill = _REQUIRED_FILL if is_required else _OPTIONAL_FILL
        cell.font = _REQUIRED_FONT if is_required else _OPTIONAL_FONT
        cell.border = _HEADER_BORDER
        cell.alignment = Alignment(vertical="center")
        ws.column_dimensions[cell.column_letter].width = max(14, len(headers[column]) * 2.2)
    for _, row in df.iterrows():
        values = []
        for column in headers:
            value = row.get(column, "")
            if column in choices:
                value = choices[column].get(value, value)  # 区分値は日本語で表示
            values.append(value)
        ws.append(values)
    ws.freeze_panes = "A2"


def _add_list_validation(ws, column_letter: str, formula: str, max_rows: int, title: str) -> None:
    dv = DataValidation(type="list", formula1=formula, allow_blank=True, showErrorMessage=True,
                        errorTitle=title, error="一覧から選んでください。")
    dv.add(f"{column_letter}2:{column_letter}{max_rows + 1}")
    ws.add_data_validation(dv)


def build_template(elements: pd.DataFrame | None = None, dependencies: pd.DataFrame | None = None) -> bytes:
    """Excelテンプレートを作る。データを渡すとその内容入り（サンプルの記入例など）、省略すると記入例3行入り。"""
    elements = _EXAMPLE_ELEMENTS if elements is None else elements
    dependencies = _EXAMPLE_DEPENDENCIES if dependencies is None else dependencies

    wb = Workbook()
    _set_default_font(wb)
    guide = wb.active
    guide.title = GUIDE_SHEET
    for row in _GUIDE:
        # 空文字のセルがあると左のセルの文字がはみ出して表示されないため、空欄は None にする
        guide.append([value or None for value in row])
    guide.merge_cells("A1:B1")  # タイトルをB列にまたがって全文表示する
    guide["A1"].font = Font(name=FONT_NAME, bold=True, size=14, color=INK)
    guide.row_dimensions[1].height = 30
    for row in guide.iter_rows(min_row=2):
        label, text = row[0], row[1]
        if isinstance(label.value, str) and label.value.startswith("【"):
            label.font = Font(name=FONT_NAME, bold=True, color=INK)  # 節の見出し
            for cell in row:
                cell.border = Border(bottom=Side(style="thin", color=GOLD))
            if text.value:
                text.font = Font(name=FONT_NAME, color=SUB_INK)
        elif label.value:
            label.font = Font(name=FONT_NAME, bold=True, color=INK)  # 項目名
        text.alignment = Alignment(wrap_text=True, vertical="top")
    guide.column_dimensions["B"].width = 100

    ws_e = wb.create_sheet(ELEMENTS_SHEET)
    _write_sheet(ws_e, elements, models.ELEMENT_HEADERS_JA, models.ELEMENT_REQUIRED_COLUMNS,
                 models.ELEMENT_CHOICE_COLUMNS)
    ws_d = wb.create_sheet(DEPENDENCIES_SHEET)
    _write_sheet(ws_d, dependencies, models.DEPENDENCY_HEADERS_JA, models.DEPENDENCY_REQUIRED_COLUMNS,
                 models.DEPENDENCY_CHOICE_COLUMNS)

    # 選択肢シート（プルダウンの元になる一覧）
    ws_c = wb.create_sheet(CHOICES_SHEET)
    lists = [
        ("種類", models.ELEMENT_TYPES),
        ("関係の種類", models.RELATION_TYPES),
        ("影響の向き", models.DIRECTIONS),
        ("確認状態", models.STATUSES),
    ]
    for col, (title, choice) in enumerate(lists, start=1):
        header = ws_c.cell(row=1, column=col, value=title)
        header.font = _OPTIONAL_FONT
        header.fill = _OPTIONAL_FILL
        header.border = _HEADER_BORDER
        ws_c.column_dimensions[header.column_letter].width = 22
        for r, label in enumerate(choice.values(), start=2):
            ws_c.cell(row=r, column=col, value=label)
    letters = {title: chr(ord("A") + i) for i, (title, _) in enumerate(lists)}

    def choice_formula(title: str, choice: dict) -> str:
        letter = letters[title]
        return f"'{CHOICES_SHEET}'!${letter}$2:${letter}${len(choice) + 1}"

    id_list = f"'{ELEMENTS_SHEET}'!$A$2:$A${MAX_ELEMENT_ROWS + 1}"
    _add_list_validation(ws_e, "C", choice_formula("種類", models.ELEMENT_TYPES), MAX_ELEMENT_ROWS, "種類")
    _add_list_validation(ws_e, "E", id_list, MAX_ELEMENT_ROWS, "責任部門・担当")
    _add_list_validation(ws_d, "B", id_list, MAX_DEPENDENCY_ROWS, "影響元の要素ID")
    _add_list_validation(ws_d, "C", id_list, MAX_DEPENDENCY_ROWS, "影響先の要素ID")
    _add_list_validation(ws_d, "D", choice_formula("関係の種類", models.RELATION_TYPES), MAX_DEPENDENCY_ROWS, "関係の種類")
    _add_list_validation(ws_d, "E", choice_formula("影響の向き", models.DIRECTIONS), MAX_DEPENDENCY_ROWS, "影響の向き")
    _add_list_validation(ws_d, "G", choice_formula("確認状態", models.STATUSES), MAX_DEPENDENCY_ROWS, "確認状態")

    for ws in wb.worksheets:
        ws.sheet_view.showGridLines = False
        ws.column_dimensions["A"].width = cm_to_width(FIRST_COLUMN_CM)

    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def _set_default_font(wb: Workbook) -> None:
    """ブックの標準フォントをメイリオにする。

    セルごとにフォントを設定すると、利用者が新しく入力するセルには反映されない。
    標準フォント（全セルが最初に参照するフォント）そのものを置き換える。
    openpyxl に公開された設定方法がないため、内部の一覧の先頭（標準フォント）を差し替えている。
    """
    default = Font(name=FONT_NAME, size=11, color=INK)
    wb._fonts[0] = default
    wb._named_styles["Normal"].font = default


def _sheet_to_csv(df: pd.DataFrame, headers: dict[str, str], choices: dict[str, dict[str, str]],
                  sheet: str) -> tuple[bytes | None, list[str]]:
    """日本語の見出し・選択肢をCSVの形式に変換する。"""
    reverse = {ja: en for en, ja in headers.items()}
    df = df.rename(columns=lambda c: reverse.get(str(c).strip(), str(c).strip()))
    missing = [headers[c] for c in headers if c not in df.columns and c in
               (models.ELEMENT_REQUIRED_COLUMNS + models.DEPENDENCY_REQUIRED_COLUMNS)]
    if missing:
        return None, [f"シート「{sheet}」に必須の見出しがありません: {', '.join(missing)}"]

    df = df.map(lambda v: str(v).strip())
    # 末尾の空行は無視する（途中の空行は、行番号がずれないよう残して検証でエラーにする）
    non_empty = (df != "").any(axis=1)
    if not non_empty.any():
        return None, [f"シート「{sheet}」にデータがありません。"]
    df = df.loc[: non_empty[non_empty].index[-1]]

    for column, choice in choices.items():
        if column in df.columns:
            label_to_code = {label: code for code, label in choice.items()}
            df[column] = df[column].map(lambda v: label_to_code.get(v, v))
    return df.to_csv(index=False).encode("utf-8"), []


def read_workbook(data: bytes) -> tuple[bytes | None, bytes | None, list[str]]:
    """Excelファイルを読み込み、(要素CSV, 依存関係CSV, エラー一覧) を返す。"""
    if not data:
        return None, None, ["ファイルが空です。"]
    if len(data) > MAX_FILE_BYTES:
        return None, None, [f"ファイルサイズが上限（{MAX_FILE_BYTES // 1_000_000}MB）を超えています。"]
    try:
        sheets = pd.read_excel(io.BytesIO(data), sheet_name=None, dtype=str, keep_default_na=False,
                               engine="openpyxl")
    except Exception:  # 壊れたファイル・Excel以外のファイルなど
        return None, None, ["Excelファイルとして読み込めません。テンプレートを使って保存したファイルか確認してください。"]

    missing = [s for s in (ELEMENTS_SHEET, DEPENDENCIES_SHEET) if s not in sheets]
    if missing:
        return None, None, [f"シート「{s}」が見つかりません。テンプレートのシート名を変更しないでください。" for s in missing]

    elements_csv, e_errors = _sheet_to_csv(sheets[ELEMENTS_SHEET], models.ELEMENT_HEADERS_JA,
                                           models.ELEMENT_CHOICE_COLUMNS, ELEMENTS_SHEET)
    dependencies_csv, d_errors = _sheet_to_csv(sheets[DEPENDENCIES_SHEET], models.DEPENDENCY_HEADERS_JA,
                                               models.DEPENDENCY_CHOICE_COLUMNS, DEPENDENCIES_SHEET)
    errors = e_errors + d_errors
    if errors:
        return None, None, errors
    return elements_csv, dependencies_csv, []
