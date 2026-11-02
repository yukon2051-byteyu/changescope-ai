"""csv_validator のテスト。正常系に加え、入力ミス・不正データ（異常系）を確認する。"""

from changescope import csv_validator
from changescope.csv_validator import validate_dependencies, validate_elements

ELEMENTS_CSV = """element_id,name,element_type,description,owner,aliases
SYS-001,勤怠管理システム,system,打刻と勤怠集計,DEP-001,勤怠システム
DAT-001,勤怠実績データ,data,,,
PRC-001,月次給与計算,process,,,
DEP-001,人事部,department,,,
"""

ELEMENT_IDS = {"SYS-001", "DAT-001", "PRC-001", "DEP-001"}

DEP_HEADER = "dependency_id,from_id,to_id,relation_type,direction,evidence,status,note\n"


def deps_csv(*rows: str) -> bytes:
    return (DEP_HEADER + "\n".join(rows) + "\n").encode("utf-8")


# ---------- 要素CSV：正常系 ----------

def test_elements_valid():
    result = validate_elements(ELEMENTS_CSV.encode("utf-8"))
    assert result.ok
    assert len(result.data) == 4
    assert result.warnings == []


def test_elements_utf8_with_bom():
    result = validate_elements(ELEMENTS_CSV.encode("utf-8-sig"))
    assert result.ok
    assert "element_id" in result.data.columns  # BOMが列名に混ざらない


def test_elements_shift_jis_from_excel():
    result = validate_elements(ELEMENTS_CSV.encode("cp932"))
    assert result.ok
    assert result.data.loc[0, "name"] == "勤怠管理システム"


def test_elements_values_are_trimmed():
    csv = "element_id,name,element_type\n SYS-001 , 勤怠管理システム , system \n"
    result = validate_elements(csv.encode("utf-8"))
    assert result.ok
    assert result.data.loc[0, "element_id"] == "SYS-001"


# ---------- 要素CSV：異常系 ----------

def test_empty_file():
    result = validate_elements(b"")
    assert not result.ok
    assert result.data is None


def test_header_only():
    result = validate_elements(b"element_id,name,element_type\n")
    assert not result.ok


def test_file_too_large(monkeypatch):
    monkeypatch.setattr(csv_validator, "MAX_FILE_BYTES", 10)
    result = validate_elements(ELEMENTS_CSV.encode("utf-8"))
    assert not result.ok
    assert "ファイルサイズ" in result.errors[0].message


def test_unknown_encoding():
    result = validate_elements(b"element_id,name,element_type\n\x82\xff,a,system\n")
    assert not result.ok
    assert "文字コード" in result.errors[0].message


def test_missing_required_column():
    result = validate_elements("element_id,name\nSYS-001,勤怠\n".encode("utf-8"))
    assert not result.ok
    assert "element_type" in result.errors[0].message


def test_invalid_element_type_reports_row_number():
    csv = "element_id,name,element_type\nSYS-001,勤怠,system\nSYS-002,給与,システム\n"
    result = validate_elements(csv.encode("utf-8"))
    assert not result.ok
    assert result.errors[0].row == 3  # 見出し=1行目、2件目のデータ=3行目
    assert result.errors[0].column == "element_type"


def test_duplicate_element_id():
    csv = "element_id,name,element_type\nSYS-001,勤怠,system\nSYS-001,給与,system\n"
    result = validate_elements(csv.encode("utf-8"))
    assert not result.ok
    assert "重複" in result.errors[0].message


def test_empty_required_value():
    csv = "element_id,name,element_type\nSYS-001,,system\n"
    result = validate_elements(csv.encode("utf-8"))
    assert not result.ok
    assert result.errors[0].column == "name"


def test_cell_too_long():
    csv = "element_id,name,element_type\nSYS-001," + "あ" * 501 + ",system\n"
    result = validate_elements(csv.encode("utf-8"))
    assert not result.ok


def test_too_many_rows(monkeypatch):
    monkeypatch.setattr(csv_validator, "MAX_ELEMENT_ROWS", 3)
    result = validate_elements(ELEMENTS_CSV.encode("utf-8"))
    assert not result.ok


def test_blank_and_missing_element_ids_are_assigned():
    csv = "element_id,name,element_type\nE-002,勤怠,system\n,給与,system\n,人事部,department\n"
    result = validate_elements(csv.encode("utf-8"))
    assert result.ok
    assert list(result.data["element_id"]) == ["E-002", "E-001", "E-003"]  # 使われている番号は飛ばす

    no_id_column = validate_elements("name,element_type\n勤怠,system\n".encode("utf-8"))
    assert list(no_id_column.data["element_id"]) == ["E-001"]


def test_duplicate_names_are_error():
    csv = "name,element_type\n人事部,department\n人事部,department\n"
    result = validate_elements(csv.encode("utf-8"))
    assert not result.ok
    assert result.errors[0].row == 3 and result.errors[0].column == "name"


def test_owner_can_be_written_by_name():
    csv = "element_id,name,element_type,owner\nS1,勤怠,system,人事部\nD1,人事部,department,\nX1,帳票,document,総務課\n"
    owners = list(validate_elements(csv.encode("utf-8")).data["owner"])
    assert owners == ["D1", "", "総務課"]  # 登録された名前はIDに。未登録の名前はそのまま


def test_unknown_column_is_warning_only():
    csv = "element_id,name,element_type,memo\nSYS-001,勤怠,system,メモ\n"
    result = validate_elements(csv.encode("utf-8"))
    assert result.ok
    assert "memo" in result.warnings[0].message


# ---------- 依存関係CSV：正常系 ----------

def test_dependencies_valid():
    data = deps_csv(
        "D-001,SYS-001,DAT-001,provides_data,one_way,業務フロー図,confirmed,",
        "D-002,DAT-001,PRC-001,uses,one_way,人事部ヒアリング,unconfirmed,",
    )
    result = validate_dependencies(data, ELEMENT_IDS)
    assert result.ok
    assert len(result.data) == 2
    assert result.warnings == []


def test_dependencies_by_name_and_auto_ids():
    names = {"勤怠管理システム": "SYS-001", "勤怠実績データ": "DAT-001"}
    data = deps_csv(",勤怠管理システム,勤怠実績データ,provides_data,one_way,根拠,confirmed,")
    result = validate_dependencies(data, ELEMENT_IDS, name_to_id=names)
    assert result.ok
    row = result.data.iloc[0]
    assert (row["from_id"], row["to_id"], row["dependency_id"]) == ("SYS-001", "DAT-001", "D-001")


def test_name_and_id_references_to_same_edge_are_merged():
    names = {"勤怠管理システム": "SYS-001"}
    data = deps_csv(
        "D-001,SYS-001,DAT-001,provides_data,one_way,根拠A,confirmed,",
        "D-002,勤怠管理システム,DAT-001,provides_data,one_way,根拠B,confirmed,",
    )
    result = validate_dependencies(data, ELEMENT_IDS, name_to_id=names)
    assert len(result.data) == 1
    assert "勤怠管理システム → DAT-001" in result.warnings[0].message


def test_cycle_is_allowed_at_csv_stage():
    # 循環参照（A→B→A）はCSVとしては正しい。無限ループ対策はグラフ探索側で行う
    data = deps_csv(
        "D-001,SYS-001,DAT-001,provides_data,one_way,根拠,confirmed,",
        "D-002,DAT-001,SYS-001,uses,one_way,根拠,confirmed,",
    )
    assert validate_dependencies(data, ELEMENT_IDS).ok


# ---------- 依存関係CSV：異常系・不整合 ----------

def test_missing_reference_is_error():
    # 書き間違い1つで黙って影響が消えないよう、存在しない参照先は読み込みを止める
    data = deps_csv(
        "D-001,SYS-001,DAT-001,provides_data,one_way,根拠,confirmed,",
        "D-002,DAT-001,XXX-999,uses,one_way,根拠,confirmed,",
    )
    result = validate_dependencies(data, ELEMENT_IDS)
    assert not result.ok
    assert result.data is None
    assert (result.errors[0].row, result.errors[0].column) == (3, "to_id")
    assert "XXX-999" in result.errors[0].message


def test_duplicate_edge_is_merged_keeping_all_evidence():
    data = deps_csv(
        "D-001,SYS-001,DAT-001,provides_data,one_way,業務フロー図,unconfirmed,メモA",
        "D-002,SYS-001,DAT-001,provides_data,one_way,人事部ヒアリング,confirmed,",
    )
    result = validate_dependencies(data, ELEMENT_IDS)
    assert result.ok
    assert len(result.data) == 1
    merged = result.data.iloc[0]
    assert merged["dependency_id"] == "D-001"
    assert merged["evidence"] == "業務フロー図／人事部ヒアリング"  # 根拠が消えない
    assert merged["status"] == "confirmed"  # 最も確かな状態を採用
    assert merged["note"] == "メモA"
    assert "統合" in result.warnings[0].message
    assert "確認状態が異なる" in result.warnings[0].message


def test_merged_status_does_not_depend_on_row_order():
    rows = [
        "D-001,SYS-001,DAT-001,uses,one_way,根拠A,confirmed,",
        "D-002,SYS-001,DAT-001,uses,one_way,根拠B,assumed,",
        "D-003,SYS-001,DAT-001,uses,one_way,根拠C,unconfirmed,",
    ]
    forward = validate_dependencies(deps_csv(*rows), ELEMENT_IDS)
    backward = validate_dependencies(deps_csv(*reversed(rows)), ELEMENT_IDS)
    assert forward.data.iloc[0]["status"] == backward.data.iloc[0]["status"] == "confirmed"


def test_duplicate_edge_with_same_evidence_is_not_repeated():
    data = deps_csv(
        "D-001,SYS-001,DAT-001,uses,one_way,業務フロー図,confirmed,",
        "D-002,SYS-001,DAT-001,uses,one_way,業務フロー図,confirmed,",
    )
    merged = validate_dependencies(data, ELEMENT_IDS).data.iloc[0]
    assert merged["evidence"] == "業務フロー図"


def test_duplicate_edge_direction_prefers_both():
    data = deps_csv(
        "D-001,SYS-001,DAT-001,uses,one_way,根拠,confirmed,",
        "D-002,SYS-001,DAT-001,uses,both,根拠,confirmed,",
    )
    result = validate_dependencies(data, ELEMENT_IDS)
    assert result.data.iloc[0]["direction"] == "both"
    assert "方向が異なる" in result.warnings[0].message


def test_duplicate_merge_without_note_column():
    header = "dependency_id,from_id,to_id,relation_type,direction,evidence,status\n"
    data = (header + "D-001,SYS-001,DAT-001,uses,one_way,根拠A,confirmed\n"
            "D-002,SYS-001,DAT-001,uses,one_way,根拠B,confirmed\n").encode("utf-8")
    result = validate_dependencies(data, ELEMENT_IDS)
    assert result.ok
    assert result.data.iloc[0]["evidence"] == "根拠A／根拠B"


def test_same_pair_with_different_relation_is_not_duplicate():
    data = deps_csv(
        "D-001,SYS-001,DAT-001,provides_data,one_way,根拠,confirmed,",
        "D-002,SYS-001,DAT-001,depends_on,one_way,根拠,confirmed,",
    )
    result = validate_dependencies(data, ELEMENT_IDS)
    assert len(result.data) == 2


def test_self_reference_is_error():
    data = deps_csv("D-001,SYS-001,SYS-001,uses,one_way,根拠,confirmed,")
    result = validate_dependencies(data, ELEMENT_IDS)
    assert not result.ok


def test_duplicate_dependency_id_is_error():
    data = deps_csv(
        "D-001,SYS-001,DAT-001,provides_data,one_way,根拠,confirmed,",
        "D-001,DAT-001,PRC-001,uses,one_way,根拠,confirmed,",
    )
    assert not validate_dependencies(data, ELEMENT_IDS).ok


def test_invalid_direction_and_status():
    data = deps_csv("D-001,SYS-001,DAT-001,uses,forward,根拠,ok,")
    result = validate_dependencies(data, ELEMENT_IDS)
    assert not result.ok
    assert {e.column for e in result.errors} == {"direction", "status"}


def test_empty_evidence_is_error():
    data = deps_csv("D-001,SYS-001,DAT-001,uses,one_way,,confirmed,")
    result = validate_dependencies(data, ELEMENT_IDS)
    assert not result.ok
    assert result.errors[0].column == "evidence"
