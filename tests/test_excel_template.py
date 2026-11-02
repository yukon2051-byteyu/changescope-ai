"""Excelテンプレートの作成・読み込みのテスト。"""

import io

from openpyxl import load_workbook

from changescope.datasets import load_from_excel, load_sample
from changescope.excel_template import (
    CHOICES_SHEET, DEPENDENCIES_SHEET, ELEMENTS_SHEET, GUIDE_SHEET, build_template, cm_to_width,
)


def open_book(data: bytes):
    return load_workbook(io.BytesIO(data))


def save(wb) -> bytes:
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def test_blank_template_structure():
    wb = open_book(build_template())
    assert wb.sheetnames == [GUIDE_SHEET, ELEMENTS_SHEET, DEPENDENCIES_SHEET, CHOICES_SHEET]
    ws = wb[ELEMENTS_SHEET]
    assert [c.value for c in ws[1]][:3] == ["要素ID", "名前", "種類"]
    assert ws["C2"].value == "情報システム"  # 区分値は日本語で表示される
    # 種類の列にプルダウン（入力規則）が設定されている
    assert any("C2" in str(dv.sqref) for dv in ws.data_validations.dataValidation)


def test_template_appearance():
    wb = open_book(build_template())
    for ws in wb.worksheets:
        assert ws.sheet_view.showGridLines is False
        assert ws["A1"].font.name == "メイリオ"
        assert ws["Z100"].font.name == "メイリオ"  # 未入力のセルも標準フォントがメイリオ
        assert ws.column_dimensions["A"].width == cm_to_width(4.0) == 16.8  # A列＝4cm
    header_colors = {c.fill.fgColor.rgb for c in wb[ELEMENTS_SHEET][1]}
    assert not any(color.endswith("C55A11") for color in header_colors)  # 以前のオレンジは使わない
    assert wb[ELEMENTS_SHEET]["A1"].fill.fgColor.rgb.endswith("1F3260")  # 必須の見出しは濃紺（黒に見える色は使わない）
    guide = wb[GUIDE_SHEET]
    assert "A1:B1" in {str(r) for r in guide.merged_cells.ranges}  # タイトルがB列まで表示される
    # 見出し行のB列は空欄（空文字だとA列の文字がはみ出して表示されない）
    assert all(row[1].value != "" for row in guide.iter_rows())


def test_blank_template_can_be_loaded_as_is():
    # 記入例のままアップロードしても読み込める（＝記入例が正しい形式になっている）
    result = load_from_excel(build_template())
    assert result.dataset is not None, result.errors
    assert len(result.dataset.elements) == 3
    assert result.dataset.dependencies.loc[0, "relation_type"] == "uses"  # 日本語→コードに変換


def test_sample_round_trip():
    sample = load_sample()
    result = load_from_excel(build_template(sample.elements, sample.dependencies))
    assert result.dataset is not None, result.errors
    assert len(result.dataset.elements) == 57
    assert len(result.dataset.dependencies) == 75
    assert result.warnings == []


def test_error_uses_japanese_column_and_excel_row():
    wb = open_book(build_template())
    wb[ELEMENTS_SHEET]["B3"] = None  # 2件目の「名前」を空にする（Excelの3行目）
    result = load_from_excel(save(wb))
    assert result.dataset is None
    assert any("シート「要素」" in e and "3行目" in e and "名前" in e for e in result.errors), result.errors


def test_trailing_empty_rows_are_ignored_but_middle_empty_row_is_error():
    wb = open_book(build_template())
    ws = wb[ELEMENTS_SHEET]
    ws["A10"] = ""  # 末尾の空セル
    assert load_from_excel(save(wb)).dataset is not None

    ws.insert_rows(3)  # 途中に空行
    result = load_from_excel(save(wb))
    assert result.dataset is None
    assert any("3行目" in e for e in result.errors)


def test_missing_sheet():
    wb = open_book(build_template())
    del wb[DEPENDENCIES_SHEET]
    result = load_from_excel(save(wb))
    assert result.dataset is None
    assert "依存関係" in result.errors[0]


def test_renamed_header():
    wb = open_book(build_template())
    wb[ELEMENTS_SHEET]["C1"] = "タイプ"
    result = load_from_excel(save(wb))
    assert result.dataset is None
    assert "種類" in result.errors[0]


# ---------- 選択肢の追加（種類・関係の種類は追加できる） ----------

def add_custom_choices(wb, types=(), relations=()):
    ws = wb[CHOICES_SHEET]
    for column, values in ((1, types), (2, relations)):
        row = ws.max_row + 1
        while ws.cell(row=row - 1, column=column).value is None:  # その列の最終行の次
            row -= 1
        for offset, value in enumerate(values):
            ws.cell(row=row + offset, column=column, value=value)


def test_choices_sheet_explains_what_can_be_changed():
    ws = open_book(build_template())[CHOICES_SHEET]
    headers = [c.value for c in ws[1]][:4]
    assert headers == ["種類（行を追加できます）", "関係の種類（行を追加できます）",
                       "影響の向き（変更できません）", "確認状態（変更できません）"]
    guide = " ".join(str(c.value) for c in ws["G"] if c.value)
    assert "追加" in guide and "変更・削除はしないでください" in guide
    # 種類のプルダウンは、行を追加すると自動で広がる
    dv_formulas = [dv.formula1 for dv in open_book(build_template())[ELEMENTS_SHEET].data_validations.dataValidation]
    assert any("OFFSET" in f and "COUNTA" in f for f in dv_formulas)


def test_custom_type_and_relation_can_be_used():
    wb = open_book(build_template())
    add_custom_choices(wb, types=["設備"], relations=["保守する"])
    wb[ELEMENTS_SHEET].append(["EQ-001", "製造ライン1", "設備"])
    wb[DEPENDENCIES_SHEET].append(["D-003", "PRC-001", "EQ-001", "保守する", "一方向", "設備台帳", "確認済"])
    result = load_from_excel(save(wb))
    assert result.dataset is not None, result.errors
    assert "設備" in set(result.dataset.elements["element_type"])
    assert "保守する" in set(result.dataset.dependencies["relation_type"])


def test_custom_type_not_added_to_choices_is_error():
    wb = open_book(build_template())
    wb[ELEMENTS_SHEET].append(["EQ-001", "製造ライン1", "設備"])
    result = load_from_excel(save(wb))
    assert result.dataset is None
    assert any("設備" in e for e in result.errors)


def test_deleted_builtin_choice_is_warning():
    wb = open_book(build_template())
    wb[CHOICES_SHEET]["A3"] = "ITシステム"  # もとからある「情報システム」を書き換えた
    result = load_from_excel(save(wb))
    assert result.dataset is not None  # 読み込みは続ける
    assert any("情報システム" in w and "変更・削除しないでください" in w for w in result.warnings)


def test_too_long_custom_choice_is_error():
    wb = open_book(build_template())
    add_custom_choices(wb, types=["あ" * 21])
    result = load_from_excel(save(wb))
    assert result.dataset is None
    assert any("長すぎます" in e for e in result.errors)


def test_custom_choices_round_trip():
    wb = open_book(build_template())
    add_custom_choices(wb, types=["設備"])
    wb[ELEMENTS_SHEET].append(["EQ-001", "製造ライン1", "設備"])
    first = load_from_excel(save(wb)).dataset
    # 書き出したExcelの選択肢シートに、追加した種類が残っている → もう一度読み込める
    again = load_from_excel(build_template(first.elements, first.dependencies))
    assert again.dataset is not None, again.errors
    assert "設備" in [c.value for c in open_book(build_template(first.elements, first.dependencies))[CHOICES_SHEET]["A"]]


def test_not_an_excel_file():
    result = load_from_excel(b"this is not excel")
    assert result.dataset is None
    assert "Excelファイルとして読み込めません" in result.errors[0]


def test_empty_file():
    assert load_from_excel(b"").dataset is None
