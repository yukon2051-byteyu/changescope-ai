"""CSVの読み込みと検証。

グラフ探索より前の「入口」で不正なデータを止める。方針は次の2つ。
- 形式の誤り（列不足・区分値の誤り・ID重複など）→ エラー。取り込みを止め、利用者に修正してもらう
- データの不整合（存在しない参照先・重複した依存関係）→ 警告。その行を除外・統合して取り込む
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field

import pandas as pd

from changescope import models

MAX_FILE_BYTES = 1_000_000  # 1MB
MAX_ELEMENT_ROWS = 1_000
MAX_DEPENDENCY_ROWS = 5_000
MAX_CELL_LENGTH = 500  # 1セルの最大文字数（AIへの入力量を抑えるためにも使う）

# 先に試す順。UTF-8（BOM付きも可）→ Excelが日本語環境で保存するShift_JIS（cp932）
ENCODINGS = ("utf-8-sig", "cp932")


@dataclass
class Issue:
    """検証で見つかった問題1件。row はCSVの行番号（見出し行=1、データ1行目=2）。"""

    message: str
    row: int | None = None
    column: str | None = None

    def __str__(self) -> str:
        place = []
        if self.row is not None:
            place.append(f"{self.row}行目")
        if self.column:
            place.append(f"列「{self.column}」")
        return f"{' '.join(place)}: {self.message}" if place else self.message


@dataclass
class ValidationResult:
    """検証結果。エラーが1件でもあれば data は None（取り込み不可）。"""

    data: pd.DataFrame | None
    errors: list[Issue] = field(default_factory=list)
    warnings: list[Issue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def _csv_row(index: int) -> int:
    """DataFrameの行番号（0始まり）をCSVの行番号に変換する。"""
    return index + 2


def read_csv(data: bytes) -> tuple[pd.DataFrame | None, list[Issue]]:
    """CSVのバイト列を読み込む。読めない場合は (None, エラー一覧) を返す。"""
    if not data:
        return None, [Issue("ファイルが空です。")]
    if len(data) > MAX_FILE_BYTES:
        return None, [Issue(f"ファイルサイズが上限（{MAX_FILE_BYTES // 1_000_000}MB）を超えています。")]

    text = None
    for encoding in ENCODINGS:
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        return None, [Issue("文字コードを判別できません。UTF-8またはShift_JISで保存してください。")]

    try:
        # すべて文字列として読み、空欄は "" にする（NaN を避ける）
        df = pd.read_csv(io.StringIO(text), dtype=str, keep_default_na=False)
    except (pd.errors.ParserError, pd.errors.EmptyDataError):
        return None, [Issue("CSVの形式として読み込めません。区切り文字や引用符を確認してください。")]

    df.columns = [str(c).strip() for c in df.columns]
    df = df.map(str.strip)
    if df.empty:
        return None, [Issue("データ行がありません。")]
    return df, []


def _check_columns_and_cells(
    df: pd.DataFrame,
    required: list[str],
    optional: list[str],
    max_rows: int,
    result: ValidationResult,
) -> bool:
    """列・行数・必須値・文字数を確認する。列が足りず以降の検証ができない場合は False。"""
    missing = [c for c in required if c not in df.columns]
    if missing:
        result.errors.append(Issue(f"必須の列がありません: {', '.join(missing)}"))
        return False

    unknown = [c for c in df.columns if c not in required + optional]
    if unknown:
        result.warnings.append(Issue(f"使用しない列は無視します: {', '.join(unknown)}"))

    if len(df) > max_rows:
        result.errors.append(Issue(f"行数が上限（{max_rows}行）を超えています（{len(df)}行）。"))

    for index, row in df.iterrows():
        for column in required:
            if row[column] == "":
                result.errors.append(Issue("必須の値が空です。", _csv_row(index), column))
        for column in df.columns:
            if len(row[column]) > MAX_CELL_LENGTH:
                result.errors.append(
                    Issue(f"文字数が上限（{MAX_CELL_LENGTH}文字）を超えています。", _csv_row(index), column)
                )
    return True


def _check_choice(df: pd.DataFrame, column: str, choices: dict[str, str], result: ValidationResult) -> None:
    """区分値が決められた選択肢の中にあるか確認する。"""
    allowed = ", ".join(choices)
    for index, value in df[column].items():
        if value and value not in choices:
            result.errors.append(
                Issue(f"「{value}」は使えません。次のいずれかを指定してください: {allowed}", _csv_row(index), column)
            )


def _check_duplicate_ids(df: pd.DataFrame, column: str, result: ValidationResult) -> None:
    duplicated = df[df[column].duplicated(keep="first") & (df[column] != "")]
    for index, value in duplicated[column].items():
        result.errors.append(Issue(f"ID「{value}」が重複しています。", _csv_row(index), column))


def validate_elements(data: bytes) -> ValidationResult:
    """要素CSVを検証する。"""
    df, read_errors = read_csv(data)
    result = ValidationResult(data=None, errors=read_errors)
    if df is None:
        return result

    if not _check_columns_and_cells(
        df, models.ELEMENT_REQUIRED_COLUMNS, models.ELEMENT_OPTIONAL_COLUMNS, MAX_ELEMENT_ROWS, result
    ):
        return result
    _check_choice(df, "element_type", models.ELEMENT_TYPES, result)
    _check_duplicate_ids(df, "element_id", result)

    if result.ok:
        result.data = df
    return result


def validate_dependencies(data: bytes, element_ids: set[str]) -> ValidationResult:
    """依存関係CSVを検証する。element_ids は検証済みの要素CSVに含まれるIDの集合。"""
    df, read_errors = read_csv(data)
    result = ValidationResult(data=None, errors=read_errors)
    if df is None:
        return result

    if not _check_columns_and_cells(
        df, models.DEPENDENCY_REQUIRED_COLUMNS, models.DEPENDENCY_OPTIONAL_COLUMNS, MAX_DEPENDENCY_ROWS, result
    ):
        return result
    _check_choice(df, "relation_type", models.RELATION_TYPES, result)
    _check_choice(df, "direction", models.DIRECTIONS, result)
    _check_choice(df, "status", models.STATUSES, result)
    _check_duplicate_ids(df, "dependency_id", result)

    for index, row in df.iterrows():
        if row["from_id"] and row["from_id"] == row["to_id"]:
            result.errors.append(Issue("from_id と to_id が同じです（自分自身への依存）。", _csv_row(index)))

    if not result.ok:
        return result

    # 存在しない要素を参照している行は、警告して除外する
    keep = []
    for index, row in df.iterrows():
        missing = [c for c in ("from_id", "to_id") if row[c] not in element_ids]
        for column in missing:
            result.warnings.append(
                Issue(f"要素「{row[column]}」は登録されていないため、この依存関係を除外します。", _csv_row(index), column)
            )
        keep.append(not missing)
    df = df[keep]

    # 同じ from・to・関係の種類の組み合わせは、最初の1行に統合する
    key = ["from_id", "to_id", "relation_type"]
    duplicated = df[df.duplicated(subset=key, keep="first")]
    for index, row in duplicated.iterrows():
        result.warnings.append(
            Issue(
                f"{row['from_id']} → {row['to_id']}（{row['relation_type']}）が重複しているため、最初の行に統合します。",
                _csv_row(index),
            )
        )
    result.data = df.drop_duplicates(subset=key, keep="first").reset_index(drop=True)
    return result
