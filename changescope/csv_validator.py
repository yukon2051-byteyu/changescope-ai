"""CSVの読み込みと検証。

グラフ探索より前の「入口」で不正なデータを止める。方針は次の2つ。
- 形式の誤り（列不足・区分値の誤り・ID重複・名前の重複）と、存在しない参照先 → エラー。
  取り込みを止め、利用者に修正してもらう（参照先の書き間違いを黙って除外すると、影響を見落とすため）
- 重複した依存関係 → 警告。根拠を残して1行に統合して取り込む
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


def _check_choice(df: pd.DataFrame, column: str, choices: dict[str, str], result: ValidationResult,
                  extras: frozenset[str] = frozenset()) -> None:
    """区分値が決められた選択肢（と、利用者が追加した選択肢）の中にあるか確認する。"""
    allowed = ", ".join([*choices, *sorted(extras)])
    for index, value in df[column].items():
        if value and value not in choices and value not in extras:
            result.errors.append(
                Issue(f"「{value}」は使えません。次のいずれかを指定してください: {allowed}", _csv_row(index), column)
            )


def _check_duplicate_ids(df: pd.DataFrame, column: str, result: ValidationResult) -> None:
    duplicated = df[df[column].duplicated(keep="first") & (df[column] != "")]
    for index, value in duplicated[column].items():
        result.errors.append(Issue(f"ID「{value}」が重複しています。", _csv_row(index), column))


def _assign_missing_ids(df: pd.DataFrame, column: str, prefix: str) -> pd.DataFrame:
    """IDが空欄の行に、使われていない番号のIDを付ける（例：E-001）。行の順に付けるので、毎回同じIDになる。"""
    if column not in df.columns:
        df = df.assign(**{column: ""})
    used = set(df[column])
    number = 0
    ids = []
    for value in df[column]:
        if not value:
            number += 1
            while f"{prefix}-{number:03d}" in used:
                number += 1
            value = f"{prefix}-{number:03d}"
            used.add(value)
        ids.append(value)
    return df.assign(**{column: ids})


def _check_duplicate_names(df: pd.DataFrame, result: ValidationResult) -> None:
    """依存関係や責任部門を名前で指定できるよう、同じ名前の要素は登録できないようにする。"""
    duplicated = df[df["name"].duplicated(keep="first") & (df["name"] != "")]
    for index, value in duplicated["name"].items():
        result.errors.append(Issue(
            f"名前「{value}」が重複しています。同じ名前の要素は登録できません"
            "（例：「人事部（本社）」「人事部（工場）」のように区別してください）。",
            _csv_row(index), "name",
        ))


def resolve_reference(value: str, element_ids: set[str], name_to_id: dict[str, str]) -> str:
    """要素の指定（IDまたは名前）をIDにそろえる。IDとして登録されていればID、名前ならそのID、どちらでもなければそのまま。"""
    if value in element_ids:
        return value
    return name_to_id.get(value, value)


def validate_elements(data: bytes, extra_types: frozenset[str] = frozenset()) -> ValidationResult:
    """要素CSVを検証する。extra_types は利用者が追加した種類（Excelの選択肢シートで追加したもの）。"""
    df, read_errors = read_csv(data)
    result = ValidationResult(data=None, errors=read_errors)
    if df is None:
        return result

    if not _check_columns_and_cells(
        df, models.ELEMENT_REQUIRED_COLUMNS, models.ELEMENT_OPTIONAL_COLUMNS, MAX_ELEMENT_ROWS, result
    ):
        return result
    _check_choice(df, "element_type", models.ELEMENT_TYPES, result, extra_types)
    if "element_id" in df.columns:
        _check_duplicate_ids(df, "element_id", result)
    _check_duplicate_names(df, result)
    if not result.ok:
        return result

    df = _assign_missing_ids(df, "element_id", "E")
    # 責任部門・担当は名前でも書けるため、登録された要素の名前ならIDにそろえる（それ以外の文字はそのまま）
    if "owner" in df.columns:
        ids = set(df["element_id"])
        name_to_id = dict(zip(df["name"], df["element_id"]))
        df = df.assign(owner=df["owner"].map(lambda v: resolve_reference(v, ids, name_to_id)))
    result.data = df
    return result


def validate_dependencies(data: bytes, element_ids: set[str],
                          extra_relations: frozenset[str] = frozenset(),
                          name_to_id: dict[str, str] | None = None) -> ValidationResult:
    """依存関係CSVを検証する。element_ids は検証済みの要素CSVに含まれるIDの集合。
    extra_relations は利用者が追加した関係の種類（Excelの選択肢シートで追加したもの）。
    name_to_id は要素の名前→IDの対応。影響元・影響先は名前でもIDでも指定できる。"""
    name_to_id = name_to_id or {}
    id_to_name = {v: k for k, v in name_to_id.items()}
    df, read_errors = read_csv(data)
    result = ValidationResult(data=None, errors=read_errors)
    if df is None:
        return result

    if not _check_columns_and_cells(
        df, models.DEPENDENCY_REQUIRED_COLUMNS, models.DEPENDENCY_OPTIONAL_COLUMNS, MAX_DEPENDENCY_ROWS, result
    ):
        return result
    _check_choice(df, "relation_type", models.RELATION_TYPES, result, extra_relations)
    _check_choice(df, "direction", models.DIRECTIONS, result)
    _check_choice(df, "status", models.STATUSES, result)
    if "dependency_id" in df.columns:
        _check_duplicate_ids(df, "dependency_id", result)

    # 影響元・影響先は名前でもIDでも書けるため、IDにそろえる
    for column in ("from_id", "to_id"):
        df[column] = df[column].map(lambda v: resolve_reference(v, element_ids, name_to_id))

    for index, row in df.iterrows():
        if row["from_id"] and row["from_id"] == row["to_id"]:
            result.errors.append(Issue("影響元と影響先が同じです（自分自身への依存）。", _csv_row(index)))

    if not result.ok:
        return result
    df = _assign_missing_ids(df, "dependency_id", "D")

    # 存在しない要素を参照している行はエラーにする。
    # 黙って除外すると、書き間違い1つで影響を見落とすため（このツールで最も避けたい失敗）
    for index, row in df.iterrows():
        for column in ("from_id", "to_id"):
            if row[column] not in element_ids:
                result.errors.append(Issue(
                    f"要素「{row[column]}」は登録されていません。名前の書き間違いや、"
                    "要素シートでの名前の変更がないか確認してください。", _csv_row(index), column,
                ))
    if not result.ok:
        return result

    result.data = _merge_duplicate_edges(df, result, id_to_name)
    return result


# 確認状態の確かさの順位（大きいほど確か）
_STATUS_RANK = {"unconfirmed": 0, "assumed": 1, "confirmed": 2}


def _join_unique(values: pd.Series) -> str:
    """空欄と重複を除き、出現順に「／」でつなぐ。"""
    return "／".join(dict.fromkeys(v for v in values if v))


def _merge_duplicate_edges(df: pd.DataFrame, result: ValidationResult,
                           id_to_name: dict[str, str] | None = None) -> pd.DataFrame:
    """同じ from・to・関係の種類の行を1行に統合する。根拠を失わないよう、情報は合わせて残す。

    - 根拠・補足：重複を除いてつなぐ
    - 確認状態：最も確かなものを採用（確認済 ＞ 推定 ＞ 未確認）
    - 方向：1行でも双方向があれば双方向（影響の見落としを防ぐため広く取る）
    - dependency_id：最初の行のIDを使う
    """
    key = ["from_id", "to_id", "relation_type"]
    if "note" not in df.columns:
        df = df.assign(note="")

    merged_rows = []
    for _, group in df.groupby(key, sort=False):
        first = group.iloc[0].copy()
        if len(group) > 1:
            first["evidence"] = _join_unique(group["evidence"])
            first["note"] = _join_unique(group["note"])
            first["status"] = max(group["status"], key=_STATUS_RANK.__getitem__)
            first["direction"] = "both" if (group["direction"] == "both").any() else "one_way"

            rows = "、".join(str(_csv_row(i)) for i in group.index)
            names = id_to_name or {}
            message = (f"{names.get(first['from_id'], first['from_id'])} → {names.get(first['to_id'], first['to_id'])}"
                       f"（{models.relation_type_label(first['relation_type'])}）が重複しているため統合しました（{rows}行目）。")
            if group["status"].nunique() > 1:
                message += f"確認状態が異なるため「{first['status']}」を採用しました。内容を確認してください。"
            if group["direction"].nunique() > 1:
                message += "方向が異なるため「both」を採用しました。"
            result.warnings.append(Issue(message, _csv_row(group.index[1])))
        merged_rows.append(first)

    return pd.DataFrame(merged_rows).reset_index(drop=True)
