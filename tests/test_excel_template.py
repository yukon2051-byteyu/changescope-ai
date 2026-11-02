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


def headers(ws) -> list:
    return [c.value for c in ws[1]]


def test_blank_template_structure():
    wb = open_book(build_template())
    assert wb.sheetnames == [GUIDE_SHEET, ELEMENTS_SHEET, DEPENDENCIES_SHEET, CHOICES_SHEET]
    ws = wb[ELEMENTS_SHEET]
    assert headers(ws)[:2] == ["名前", "種類"]
    assert ws["B2"].value == "情報システム"  # 区分値は日本語で表示される
    # 種類の列にプルダウン（入力規則）が設定されている
    assert any("B2" in str(dv.sqref) for dv in ws.data_validations.dataValidation)


def test_ids_are_not_shown_in_excel():
    # IDは内部だけで使う。利用者が意識しなくてよいよう、どのシートにも出さない
    wb = open_book(build_template(load_sample().elements, load_sample().dependencies))
    for ws in wb.worksheets:
        text = " ".join(str(c.value) for row in ws.iter_rows() for c in row if c.value)
        assert "要素ID" not in text and "依存関係ID" not in text
    assert headers(wb[DEPENDENCIES_SHEET])[:2] == ["影響元", "影響先"]
    assert wb[DEPENDENCIES_SHEET]["A2"].value == "勤怠管理システム"  # サンプルも名前で書かれている


def test_template_appearance():
    wb = open_book(build_template())
    for ws in wb.worksheets:
        assert ws.sheet_view.showGridLines is False
        assert ws["A1"].font.name == "メイリオ"
        assert ws["Z100"].font.name == "メイリオ"  # 未入力のセルも標準フォントがメイリオ
    for name in (GUIDE_SHEET, ELEMENTS_SHEET, DEPENDENCIES_SHEET):
        assert wb[name].column_dimensions["A"].width == cm_to_width(4.0) == 16.8  # A列＝4cm
    header_colors = {c.fill.fgColor.rgb for c in wb[ELEMENTS_SHEET][1]}
    assert not any(color.endswith("C55A11") for color in header_colors)  # 以前のオレンジは使わない
    assert wb[ELEMENTS_SHEET]["A1"].fill.fgColor.rgb.endswith("1F3260")  # 必須の見出し（名前）は濃紺（黒に見える色は使わない）
    assert wb[ELEMENTS_SHEET].column_dimensions["C"].width == cm_to_width(6.0)  # 説明列＝6cm

    choices = wb[CHOICES_SHEET]
    assert [choices.column_dimensions[c].width for c in "ABCDE"] == [
        cm_to_width(cm) for cm in (5.6, 7.0, 6.0, 5.61, 0.5)
    ]
    assert all(choices.cell(row=1, column=c).alignment.horizontal == "center" for c in range(1, 5))
    # A〜D列は上下中央揃え
    for column in range(1, 5):
        for row in range(1, 4):
            assert choices.cell(row=row, column=column).alignment.vertical == "center"
    assert choices["F1"].alignment.vertical == "center"
    for row in range(1, 6):  # 説明欄：F列は薄い黄緑、F・G列は罫線で囲む
        assert choices.cell(row=row, column=6).fill.fgColor.rgb.endswith("E4EFA0")
        for column in (6, 7):
            border = choices.cell(row=row, column=column).border
            assert all(side.style == "thin" for side in (border.left, border.right, border.top, border.bottom))
    guide = wb[GUIDE_SHEET]
    assert "A1:B1" in {str(r) for r in guide.merged_cells.ranges}  # タイトルがB列まで表示される
    # 見出し行のB列は空欄（空文字だとA列の文字がはみ出して表示されない）
    assert all(row[1].value != "" for row in guide.iter_rows())


def test_blank_template_can_be_loaded_as_is():
    # 記入例のままアップロードしても読み込める（＝記入例が正しい形式になっている）
    result = load_from_excel(build_template())
    assert result.dataset is not None, result.errors
    elements = result.dataset.elements
    assert len(elements) == 3
    assert list(elements["element_id"]) == ["E-001", "E-002", "E-003"]  # 内部のIDは自動で付く
    assert elements.loc[0, "owner"] == "E-003"  # 責任部門は名前（経理部）で書いても、内部ではIDにそろう
    deps = result.dataset.dependencies
    assert deps.loc[0, "relation_type"] == "uses"  # 日本語→コードに変換
    assert (deps.loc[0, "from_id"], deps.loc[0, "to_id"]) == ("E-001", "E-002")  # 名前→ID
    assert list(deps["dependency_id"]) == ["D-001", "D-002"]
    assert result.warnings == []


def test_sample_round_trip():
    sample = load_sample()
    result = load_from_excel(build_template(sample.elements, sample.dependencies))
    assert result.dataset is not None, result.errors
    assert len(result.dataset.elements) == 57
    assert len(result.dataset.dependencies) == 75
    assert result.warnings == []


def test_error_uses_japanese_column_and_excel_row():
    wb = open_book(build_template())
    wb[ELEMENTS_SHEET]["A3"] = None  # 2件目の「名前」を空にする（Excelの3行目）
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
    wb[ELEMENTS_SHEET]["B1"] = "タイプ"
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
    assert headers(ws)[:4] == ["種類（行を追加できます）", "関係の種類（行を追加できます）",
                               "影響の向き（変更できません）", "確認状態（変更できません）"]
    guide = " ".join(str(c.value) for c in ws["G"] if c.value)
    assert "追加" in guide and "変更・削除はしないでください" in guide
    # 種類のプルダウンは、行を追加すると自動で広がる
    dv_formulas = [dv.formula1 for dv in open_book(build_template())[ELEMENTS_SHEET].data_validations.dataValidation]
    assert any("OFFSET" in f and "COUNTA" in f for f in dv_formulas)


def test_custom_type_and_relation_can_be_used():
    wb = open_book(build_template())
    add_custom_choices(wb, types=["設備"], relations=["保守する"])
    wb[ELEMENTS_SHEET].append(["製造ライン1", "設備"])
    wb[DEPENDENCIES_SHEET].append(["経費精算業務", "製造ライン1", "保守する", "一方向", "設備台帳", "確認済"])
    result = load_from_excel(save(wb))
    assert result.dataset is not None, result.errors
    assert "設備" in set(result.dataset.elements["element_type"])
    assert "保守する" in set(result.dataset.dependencies["relation_type"])


def test_custom_type_not_added_to_choices_is_error():
    wb = open_book(build_template())
    wb[ELEMENTS_SHEET].append(["製造ライン1", "設備"])
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
    wb[ELEMENTS_SHEET].append(["製造ライン1", "設備"])
    first = load_from_excel(save(wb)).dataset
    # 書き出したExcelの選択肢シートに、追加した種類が残っている → もう一度読み込める
    again = load_from_excel(build_template(first.elements, first.dependencies))
    assert again.dataset is not None, again.errors
    assert "設備" in [c.value for c in open_book(build_template(first.elements, first.dependencies))[CHOICES_SHEET]["A"]]


# ---------- 名前で選ぶ ----------

def test_dropdowns_list_element_names():
    wb = open_book(build_template())
    formulas = {str(dv.sqref).split(":")[0]: dv.formula1 for dv in wb[DEPENDENCIES_SHEET].data_validations.dataValidation}
    for cell in ("A2", "B2"):  # 影響元・影響先は、要素シートの「名前」列（A列）から選ぶ
        assert "'要素'!$A$2" in formulas[cell] and "COUNTA" in formulas[cell]
    assert wb[DEPENDENCIES_SHEET]["A2"].value == "経費精算システム"  # 記入例は名前で書かれている


def test_legacy_headers_with_ids_still_load():
    # 以前のテンプレート（ID列あり、見出し「影響元の要素ID」、IDで指定）で作ったファイルも読み込める
    wb = open_book(build_template())
    ws_e, ws_d = wb[ELEMENTS_SHEET], wb[DEPENDENCIES_SHEET]
    ws_e.insert_cols(1)
    ws_e["A1"] = "要素ID"
    for row, element_id in zip(range(2, 5), ["SYS-001", "PRC-001", "DEP-001"]):
        ws_e.cell(row=row, column=1, value=element_id)
    ws_e["E1"], ws_e["E2"], ws_e["E3"] = "責任部門・担当（要素ID）", "DEP-001", "DEP-001"
    ws_d.insert_cols(1)
    ws_d["A1"], ws_d["A2"], ws_d["A3"] = "依存関係ID", "D-001", "D-002"
    ws_d["B1"], ws_d["C1"] = "影響元の要素ID", "影響先の要素ID"
    ws_d["B2"], ws_d["C2"], ws_d["B3"], ws_d["C3"] = "SYS-001", "PRC-001", "PRC-001", "DEP-001"
    result = load_from_excel(save(wb))
    assert result.dataset is not None, result.errors
    assert list(result.dataset.elements["element_id"]) == ["SYS-001", "PRC-001", "DEP-001"]
    assert len(result.dataset.dependencies) == 2


def test_unknown_name_in_dependency_is_error():
    wb = open_book(build_template())
    wb[DEPENDENCIES_SHEET]["B3"] = "経理課"  # 影響先に、登録されていない名前（書き間違い）
    result = load_from_excel(save(wb))
    assert result.dataset is None
    # Excelの行番号と日本語の列名で、直す場所が分かる
    assert any("経理課" in e and "3行目" in e and "影響先" in e and "書き間違い" in e for e in result.errors)


def test_duplicate_names_are_error():
    wb = open_book(build_template())
    wb[ELEMENTS_SHEET].append(["経理部", "部門"])
    result = load_from_excel(save(wb))
    assert result.dataset is None
    assert any("経理部" in e and "重複" in e for e in result.errors)


def test_not_an_excel_file():
    result = load_from_excel(b"this is not excel")
    assert result.dataset is None
    assert "Excelファイルとして読み込めません" in result.errors[0]


def test_empty_file():
    assert load_from_excel(b"").dataset is None
