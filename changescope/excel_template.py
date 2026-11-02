"""Excelテンプレートの作成と読み込み。

業務部門の担当者がCSVの列名や区分値を覚えなくても記入できるよう、
日本語の見出し・選択肢のプルダウン・説明シート付きのExcelを提供する。
読み込み時は日本語の見出し・選択肢をCSVの形式に変換し、CSVと同じ検証処理に渡す。
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field

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
NAVY = "1F3260"  # 見出しの塗り（濃紺。黒に見えない明るさにする。Web画面のメインカラーと同じ）
_REQUIRED_FILL = PatternFill("solid", fgColor=NAVY)  # 必須の見出し：濃紺
_OPTIONAL_FILL = PatternFill("solid", fgColor="EEF1F3")  # 任意の見出し：薄いグレー
_REQUIRED_FONT = Font(name=FONT_NAME, bold=True, color="FFFFFF")
_OPTIONAL_FONT = Font(name=FONT_NAME, bold=True, color=INK)
GOLD = "B8963E"  # 差し色（金）
_HEADER_BORDER = Border(bottom=Side(style="medium", color=GOLD))
_BUILTIN_FILL = PatternFill("solid", fgColor="EEF1F3")  # 選択肢シートの、もとからある値（変更しない）
# 選択肢シートの説明欄（F・G列）：項目名は薄い黄緑、F・G列とも細い罫線で囲む（利用者の指定）
_GUIDE_LABEL_FILL = PatternFill("solid", fgColor="E4EFA0")
_THIN = Side(style="thin", color="404040")
_GUIDE_BORDER = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)
# 使い方シートの表の罫線（金色の細線。利用者の見本に合わせる）
_GOLD_THIN = Side(style="thin", color="E0B14A")
_GUIDE_ROW_BORDER = Border(left=_GOLD_THIN, right=_GOLD_THIN, top=_GOLD_THIN, bottom=_GOLD_THIN)

# 選択肢シートの見出し（列の位置で読み込むため、順番を変えない）
CHOICE_HEADERS = ("種類（行を追加できます）", "関係の種類（行を追加できます）",
                  "影響の向き（変更できません）", "確認状態（変更できません）")
_CHOICES_GUIDE = [
    ("このシートについて", "「要素」「依存関係」シートのプルダウンに出る選択肢の一覧です。"),
    ("追加できる列", "「種類」と「関係の種類」は、いちばん下の行の次に入力すると、新しい選択肢として使えます。"
                    "例：種類に「設備」「店舗」「取引先」、関係の種類に「保守する」「供給する」。"
                    f"1つ{models.MAX_CUSTOM_CHOICE_LENGTH}文字までです。"),
    ("変更しない値", "グレーの塗りの値は、もとからある選択肢です。分析の判定（関係者・見落としチェックなど）に使うため、"
                    "名前の変更・削除はしないでください。"),
    ("追加した値の扱い", "追加した種類・関係も、影響の探索（どこまで影響が広がるか）には使われます。"
                        "ただし「誰に影響するか」や「見落としチェック」の判定には使われません。"
                        "部門・担当者・データ・規程などは、もとからある種類で登録してください。"),
    ("変更できない列", "「影響の向き」と「確認状態」は、分析の仕組みそのものに使うため、変更・追加できません。"),
]

# 列幅：Excelの列幅は「標準フォントの数字1文字の幅」が単位。メイリオ11ptの数字の幅は 9px（96dpiで実測）
_DIGIT_WIDTH_PX = 9
FIRST_COLUMN_CM = 4.0
# Excelに出す列（IDは内部だけで使うため、Excelには出さない。古いExcelのID列は読み込める）
EXCEL_ELEMENT_COLUMNS = [c for c in models.ELEMENT_HEADERS_JA if c != "element_id"]
EXCEL_DEPENDENCY_COLUMNS = [c for c in models.DEPENDENCY_HEADERS_JA if c != "dependency_id"]
# 列幅（cm）。要素シートは列の名前で、選択肢シートは列記号で指定する
ELEMENT_WIDTHS_CM = {"description": 6.0}  # 説明
CHOICES_WIDTHS_CM = {"A": 5.6, "B": 7.0, "C": 6.0, "D": 5.61, "E": 0.5}


def column_letter(columns: list[str], column: str) -> str:
    """Excelに出す列の並びから、列記号（A, B, …）を返す。"""
    return chr(ord("A") + columns.index(column))


def cm_to_width(cm: float) -> float:
    """cmをExcelの列幅に換算する（96dpi基準。画面の拡大率により多少の誤差がある）。"""
    return round(cm / 2.54 * 96 / _DIGIT_WIDTH_PX, 2)


# 白紙テンプレートに入れる記入例（架空）。IDは空欄でよいことが伝わるよう空欄にし、要素は名前で指定する
_EXAMPLE_ELEMENTS = pd.DataFrame([
    {"element_id": "", "name": "経費精算システム", "element_type": "system",
     "description": "経費申請と承認を行うシステム", "owner": "経理部", "aliases": "経費システム"},
    {"element_id": "", "name": "経費精算業務", "element_type": "process",
     "description": "申請→上長承認→経理確認", "owner": "経理部", "aliases": "経費精算"},
    {"element_id": "", "name": "経理部", "element_type": "department",
     "description": "", "owner": "", "aliases": "経理"},
])
_EXAMPLE_DEPENDENCIES = pd.DataFrame([
    {"dependency_id": "", "from_id": "経費精算システム", "to_id": "経費精算業務", "relation_type": "uses",
     "direction": "both", "evidence": "経費精算システム操作マニュアル", "status": "confirmed",
     "note": "承認ルートはシステムの設定で管理"},
    {"dependency_id": "", "from_id": "経費精算業務", "to_id": "経理部", "relation_type": "performs",
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
    ("見出しの色", "濃紺の見出しは必須、薄いグレーの見出しは任意です。見出しの文字は変更しないでください。"),
    ("名前", "依存関係シートの「影響元」「影響先」や「責任部門・担当」は、要素の名前をプルダウンで選びます。"
            "同じ名前の要素は登録できません（例：「人事部（本社）」「人事部（工場）」のように区別します）。"
            "要素の名前を後から変えた場合は、依存関係シートの名前も直してください。"),
    ("影響の向き", "「影響元が変わると、影響先に対応や確認が必要になる」向きで登録します。\n"
                  "分析はこの向きにだけ影響をたどるため、逆に書くと影響を見落とします。"),
    ("向きの決め方", "「Aが変わったら、Bに対応や確認が必要になるか？」と考え、必要になるなら A が影響元、B が影響先です。\n"
                    "文の主語ではなく「変わったときに困るのはどちらか」で決めます。"),
    ("向きの例", "勤怠実績データ（影響元）→ 月次給与計算（影響先）／月次給与計算（影響元）→ 人事部（影響先、業務の担当）"),
    ("双方向", "どちらが変わっても相手に対応が必要になる場合だけ「双方向」にします。迷ったら一方向で登録してください。"),
    ("根拠", "その関係を何で確認したか（資料名・ヒアリング相手など）を必ず書きます。"),
    ("確認状態", "資料や関係者に確認済みなら「確認済」、推測なら「推定」、未確認なら「未確認」。\n"
                "未確認の関係も登録しておくと、確認が必要な事項として分析結果に表示されます。"),
    ("選択肢の追加", "「選択肢」シートの「種類」と「関係の種類」は、下に行を追加すると新しい値を使えます（例：設備、店舗、取引先）。\n"
                    "もとからある値は変更・削除しないでください。「影響の向き」と「確認状態」は変更できません。"),
    ("注意", "個人情報・機密情報は記入しないでください。"),
    ("", ""),
    ("【関係の種類】", "（影響元 → 影響先 の例）"),
    *[(label, example) for label, example in [
        ("データを提供する", "勤怠管理システム → 勤怠実績データ"),
        ("利用される", "勤怠実績データ → 月次給与計算（データは業務に利用される）"),
        ("システム連携する", "経費精算システム → 会計システム"),
        ("担当される", "月次給与計算 → 人事部（業務は担当部門・担当者に担当される）"),
        ("承認を受ける", "経費精算業務 → 承認者（課長）（業務は承認者の承認を受ける）"),
        ("規程に従う", "経費精算業務 → 経費規程"),
        ("帳票を作成する", "給与計算システム → 給与明細"),
        ("土台になる", "社内ファイルサーバー → 顧客管理Excel（保存場所としての土台になる）"),
    ]],
]


def _write_sheet(ws, df: pd.DataFrame, headers: dict[str, str], columns: list[str], required: list[str],
                 choices: dict[str, dict[str, str]]) -> None:
    headers = {c: headers[c] for c in columns}
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


def _add_list_validation(ws, column_letter: str, formula: str, max_rows: int, title: str,
                         error: str = "一覧から選んでください。") -> None:
    dv = DataValidation(type="list", formula1=formula, allow_blank=True, showErrorMessage=True,
                        errorTitle=title, error=error)
    dv.add(f"{column_letter}2:{column_letter}{max_rows + 1}")
    ws.add_data_validation(dv)


def build_template(elements: pd.DataFrame | None = None, dependencies: pd.DataFrame | None = None) -> bytes:
    """Excelテンプレートを作る。データを渡すとその内容入り（サンプルの記入例など）、省略すると記入例3行入り。"""
    elements = _EXAMPLE_ELEMENTS if elements is None else elements
    dependencies = _EXAMPLE_DEPENDENCIES if dependencies is None else dependencies
    # 利用者が名前で選べるよう、要素の指定（ID）を名前に置き換えて書き出す
    id_to_name = {i: n for i, n in zip(elements["element_id"], elements["name"]) if i}  # 空欄のIDは対応させない
    to_name = lambda v: id_to_name.get(v, v)  # noqa: E731
    elements = elements.assign(owner=elements.get("owner", pd.Series("", index=elements.index)).map(to_name))
    dependencies = dependencies.assign(from_id=dependencies["from_id"].map(to_name),
                                       to_id=dependencies["to_id"].map(to_name))

    wb = Workbook()
    _set_default_font(wb)
    guide = wb.active
    guide.title = GUIDE_SHEET
    for row in _GUIDE:
        # 空文字のセルがあると左のセルの文字がはみ出して表示されないため、空欄は None にする
        guide.append([value or None for value in row])
    guide.merge_cells("A1:B1")  # タイトルをB列にまたがって全文表示する
    guide["A1"].font = Font(name=FONT_NAME, bold=True, size=14, color="FFFFFF")
    guide["A1"].fill = PatternFill("solid", fgColor=NAVY)  # タイトル行は濃紺の塗りに白文字
    guide["A1"].alignment = Alignment(vertical="center")
    guide["A1"].border = guide["B1"].border = Border(bottom=Side(style="medium", color=GOLD))
    guide.row_dimensions[1].height = 30
    for row in guide.iter_rows(min_row=2):
        label, text = row[0], row[1]
        if isinstance(label.value, str) and label.value.startswith("【"):
            label.font = Font(name=FONT_NAME, bold=True, color=INK)  # 節の見出し（罫線なし）
            if text.value:
                text.font = Font(name=FONT_NAME, color=SUB_INK)
        elif label.value or text.value:
            # 手順・ルール・関係の種類の各行：A・B列を金色の細い罫線で囲む
            label.font = Font(name=FONT_NAME, bold=True, color=INK)  # 項目名
            label.alignment = Alignment(vertical="center")  # A列は上下中央揃え
            text.alignment = Alignment(wrap_text=True, vertical="center")
            label.border = text.border = _GUIDE_ROW_BORDER
    guide.column_dimensions["B"].width = 100

    ws_e = wb.create_sheet(ELEMENTS_SHEET)
    _write_sheet(ws_e, elements, models.ELEMENT_HEADERS_JA, EXCEL_ELEMENT_COLUMNS, models.ELEMENT_REQUIRED_COLUMNS,
                 models.ELEMENT_CHOICE_COLUMNS)
    ws_d = wb.create_sheet(DEPENDENCIES_SHEET)
    _write_sheet(ws_d, dependencies, models.DEPENDENCY_HEADERS_JA, EXCEL_DEPENDENCY_COLUMNS,
                 models.DEPENDENCY_REQUIRED_COLUMNS, models.DEPENDENCY_CHOICE_COLUMNS)

    # 選択肢シート（プルダウンの元になる一覧）
    ws_c = wb.create_sheet(CHOICES_SHEET)
    extra_types = [v for v in dict.fromkeys(elements["element_type"]) if v and v not in models.ELEMENT_TYPES]
    extra_relations = [v for v in dict.fromkeys(dependencies["relation_type"])
                       if v and v not in models.RELATION_TYPES]
    lists = [
        # (見出し, もとからある選択肢, 追加済みの選択肢, 追加できるか)
        (CHOICE_HEADERS[0], models.ELEMENT_TYPES, extra_types, True),
        (CHOICE_HEADERS[1], models.RELATION_TYPES, extra_relations, True),
        (CHOICE_HEADERS[2], models.DIRECTIONS, [], False),
        (CHOICE_HEADERS[3], models.STATUSES, [], False),
    ]
    for col, (title, choice, extras, addable) in enumerate(lists, start=1):
        header = ws_c.cell(row=1, column=col, value=title)
        header.font = _REQUIRED_FONT if addable else _OPTIONAL_FONT
        header.fill = _REQUIRED_FILL if addable else _OPTIONAL_FILL
        header.border = _HEADER_BORDER
        header.alignment = Alignment(horizontal="center", vertical="center")  # 見出しは左右中央揃え
        for r, label in enumerate(choice.values(), start=2):
            ws_c.cell(row=r, column=col, value=label).fill = _BUILTIN_FILL  # もとからある値（変更しない）
        for r, label in enumerate(extras, start=len(choice) + 2):
            ws_c.cell(row=r, column=col, value=label)  # 利用者が追加した値
        for r in range(2, len(choice) + len(extras) + 2):
            ws_c.cell(row=r, column=col).alignment = Alignment(vertical="center")  # 上下中央揃え
    for r, (label, text) in enumerate(_CHOICES_GUIDE, start=1):
        label_cell = ws_c.cell(row=r, column=6, value=label)
        label_cell.font = Font(name=FONT_NAME, bold=True, color=INK)
        label_cell.alignment = Alignment(vertical="center")  # 項目名は上下中央揃え
        label_cell.fill = _GUIDE_LABEL_FILL
        text_cell = ws_c.cell(row=r, column=7, value=text)
        text_cell.alignment = Alignment(wrap_text=True, vertical="top")
        label_cell.border = text_cell.border = _GUIDE_BORDER
    ws_c.column_dimensions["F"].width = 18
    ws_c.column_dimensions["G"].width = 70
    letters = {title: chr(ord("A") + i) for i, (title, *_rest) in enumerate(lists)}

    def choice_formula(title: str, choice: dict) -> str:
        letter = letters[title]
        if title in CHOICE_HEADERS[:2]:
            # 行を追加するとプルダウンにも自動で出るよう、入力されている行数に合わせて範囲を広げる
            return f"OFFSET('{CHOICES_SHEET}'!${letter}$2,0,0,COUNTA('{CHOICES_SHEET}'!${letter}:${letter})-1,1)"
        return f"'{CHOICES_SHEET}'!${letter}$2:${letter}${len(choice) + 1}"

    e = lambda column: column_letter(EXCEL_ELEMENT_COLUMNS, column)  # noqa: E731
    d = lambda column: column_letter(EXCEL_DEPENDENCY_COLUMNS, column)  # noqa: E731
    # 要素の名前の一覧。要素を追加するとプルダウンにも自動で出るよう、入力されている行数に合わせて広げる
    n = e("name")
    name_list = f"OFFSET('{ELEMENTS_SHEET}'!${n}$2,0,0,COUNTA('{ELEMENTS_SHEET}'!${n}:${n})-1,1)"
    pick_name = "「要素」シートに登録した名前から選んでください。"
    _add_list_validation(ws_e, e("element_type"), choice_formula(CHOICE_HEADERS[0], models.ELEMENT_TYPES),
                         MAX_ELEMENT_ROWS, "種類")
    _add_list_validation(ws_e, e("owner"), name_list, MAX_ELEMENT_ROWS, "責任部門・担当", pick_name)
    _add_list_validation(ws_d, d("from_id"), name_list, MAX_DEPENDENCY_ROWS, "影響元", pick_name)
    _add_list_validation(ws_d, d("to_id"), name_list, MAX_DEPENDENCY_ROWS, "影響先", pick_name)
    _add_list_validation(ws_d, d("relation_type"), choice_formula(CHOICE_HEADERS[1], models.RELATION_TYPES),
                         MAX_DEPENDENCY_ROWS, "関係の種類")
    _add_list_validation(ws_d, d("direction"), choice_formula(CHOICE_HEADERS[2], models.DIRECTIONS),
                         MAX_DEPENDENCY_ROWS, "影響の向き")
    _add_list_validation(ws_d, d("status"), choice_formula(CHOICE_HEADERS[3], models.STATUSES),
                         MAX_DEPENDENCY_ROWS, "確認状態")

    for ws in wb.worksheets:
        ws.sheet_view.showGridLines = False
        ws.column_dimensions["A"].width = cm_to_width(FIRST_COLUMN_CM)
    # 個別に指定した列幅（cm）。A列の共通設定のあとに設定し、上書きされないようにする
    for column, cm in ELEMENT_WIDTHS_CM.items():
        ws_e.column_dimensions[column_letter(EXCEL_ELEMENT_COLUMNS, column)].width = cm_to_width(cm)
    for letter, cm in CHOICES_WIDTHS_CM.items():
        ws_c.column_dimensions[letter].width = cm_to_width(cm)

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
    reverse.update({ja: en for ja, en in models.LEGACY_HEADERS_JA.items() if en in headers})
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
            if choice is models.RELATION_TYPES:
                label_to_code.update(models.LEGACY_RELATION_LABELS)  # 以前の名前で書かれたExcelも読めるように
            df[column] = df[column].map(lambda v: label_to_code.get(v, v))
    return df.to_csv(index=False).encode("utf-8"), []


@dataclass
class ParsedWorkbook:
    """Excelの読み込み結果。CSVの形式に変換したデータと、利用者が追加した選択肢。"""

    elements_csv: bytes | None = None
    dependencies_csv: bytes | None = None
    extra_types: frozenset[str] = frozenset()
    extra_relations: frozenset[str] = frozenset()
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _read_extra_choices(df: pd.DataFrame, column: int, builtin: dict[str, str], title: str,
                        result: ParsedWorkbook) -> frozenset[str]:
    """選択肢シートの1列から、利用者が追加した値を取り出す。もとからある値が消されていないかも確認する。"""
    if df.shape[1] <= column:
        return frozenset()
    values = [str(v).strip() for v in df.iloc[:, column] if str(v).strip()]
    legacy = models.LEGACY_RELATION_LABELS if builtin is models.RELATION_TYPES else {}
    present_codes = {legacy.get(v, v) for v in values} | {c for c, label in builtin.items() if label in values}
    for code, label in builtin.items():
        if code not in present_codes:
            result.warnings.append(
                f"シート「{CHOICES_SHEET}」の「{title}」に、もとからある選択肢「{label}」が見つかりません。"
                "もとからある選択肢は変更・削除しないでください（分析の判定には引き続き使えます）。"
            )
    extras = []
    for value in values:
        if value in builtin.values() or value in builtin or value in legacy:
            continue
        if len(value) > models.MAX_CUSTOM_CHOICE_LENGTH:
            result.errors.append(
                f"シート「{CHOICES_SHEET}」の「{title}」に追加した「{value[:20]}…」は長すぎます"
                f"（{models.MAX_CUSTOM_CHOICE_LENGTH}文字まで）。"
            )
            continue
        extras.append(value)
    return frozenset(extras)


def read_workbook(data: bytes) -> ParsedWorkbook:
    """Excelファイルを読み込み、CSVの形式に変換する。"""
    result = ParsedWorkbook()
    if not data:
        result.errors.append("ファイルが空です。")
        return result
    if len(data) > MAX_FILE_BYTES:
        result.errors.append(f"ファイルサイズが上限（{MAX_FILE_BYTES // 1_000_000}MB）を超えています。")
        return result
    try:
        sheets = pd.read_excel(io.BytesIO(data), sheet_name=None, dtype=str, keep_default_na=False,
                               engine="openpyxl")
    except Exception:  # 壊れたファイル・Excel以外のファイルなど
        result.errors.append("Excelファイルとして読み込めません。テンプレートを使って保存したファイルか確認してください。")
        return result

    missing = [s for s in (ELEMENTS_SHEET, DEPENDENCIES_SHEET) if s not in sheets]
    if missing:
        result.errors += [f"シート「{s}」が見つかりません。テンプレートのシート名を変更しないでください。" for s in missing]
        return result

    # 選択肢シート（ない場合は、もとからある選択肢だけを使う）
    if CHOICES_SHEET in sheets:
        choices = sheets[CHOICES_SHEET]
        result.extra_types = _read_extra_choices(choices, 0, models.ELEMENT_TYPES, "種類", result)
        result.extra_relations = _read_extra_choices(choices, 1, models.RELATION_TYPES, "関係の種類", result)

    result.elements_csv, e_errors = _sheet_to_csv(sheets[ELEMENTS_SHEET], models.ELEMENT_HEADERS_JA,
                                                  models.ELEMENT_CHOICE_COLUMNS, ELEMENTS_SHEET)
    result.dependencies_csv, d_errors = _sheet_to_csv(sheets[DEPENDENCIES_SHEET], models.DEPENDENCY_HEADERS_JA,
                                                      models.DEPENDENCY_CHOICE_COLUMNS, DEPENDENCIES_SHEET)
    result.errors += e_errors + d_errors
    return result
