"""分析に使うデータ一式（要素・依存関係・グラフ）の読み込み。

利用者がアップロードしたデータは画面のセッション（利用者ごとのメモリ）にだけ保持し、
ファイルやDBには保存しない。これにより利用者間でデータが混ざらない。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import networkx as nx
import pandas as pd

from changescope import models
from changescope.csv_validator import Issue, read_csv, validate_dependencies, validate_elements
from changescope.excel_template import DEPENDENCIES_SHEET, ELEMENTS_SHEET, read_workbook
from changescope.graph_engine import build_graph

SAMPLE_DIR = Path(__file__).resolve().parent.parent / "data" / "sample"


@dataclass
class Dataset:
    source: str  # "sample"（架空サンプル）・"upload"（利用者のExcel・CSV）・"diagram"（図・資料から作成・編集）
    elements: pd.DataFrame
    dependencies: pd.DataFrame
    graph: nx.MultiDiGraph
    warnings: list[str] = field(default_factory=list)


@dataclass
class LoadResult:
    dataset: Dataset | None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _format(issues: list[Issue], file_label: str, column_labels: dict[str, str]) -> list[str]:
    """問題を表示用の文にする。Excelの場合は列名を日本語の見出しに置き換える。"""
    return [f"{file_label} {Issue(i.message, i.row, column_labels.get(i.column, i.column))}" for i in issues]


def load_from_csv(elements_csv: bytes, dependencies_csv: bytes, source: str = "upload",
                  labels: tuple[str, str] = ("要素CSV", "依存関係CSV"),
                  column_labels: dict[str, str] | None = None,
                  extra_types: frozenset[str] = frozenset(),
                  extra_relations: frozenset[str] = frozenset()) -> LoadResult:
    """2つのCSVを検証して読み込む。エラーがあれば dataset は None。
    extra_types・extra_relations は、Excelの選択肢シートで利用者が追加した種類・関係の種類。"""
    column_labels = column_labels or {}
    elements = validate_elements(elements_csv, extra_types)
    errors = _format(elements.errors, labels[0], column_labels)
    warnings = _format(elements.warnings, labels[0], column_labels)
    if not elements.ok:
        return LoadResult(None, errors, warnings)

    name_to_id = dict(zip(elements.data["name"], elements.data["element_id"]))
    dependencies = validate_dependencies(dependencies_csv, set(elements.data["element_id"]), extra_relations,
                                         name_to_id)
    errors += _format(dependencies.errors, labels[1], column_labels)
    warnings += _format(dependencies.warnings, labels[1], column_labels)
    if not dependencies.ok:
        return LoadResult(None, errors, warnings)

    graph = build_graph(elements.data, dependencies.data)
    return LoadResult(Dataset(source, elements.data, dependencies.data, graph, warnings), errors, warnings)


def load_from_excel(data: bytes) -> LoadResult:
    """Excelテンプレートを読み込む。Excelの行番号とエラーの行番号は一致する（見出し=1行目）。"""
    parsed = read_workbook(data)
    if parsed.errors:
        return LoadResult(None, parsed.errors, parsed.warnings)
    result = load_from_csv(
        parsed.elements_csv, parsed.dependencies_csv,
        labels=(f"シート「{ELEMENTS_SHEET}」", f"シート「{DEPENDENCIES_SHEET}」"),
        column_labels={**models.ELEMENT_HEADERS_JA, **models.DEPENDENCY_HEADERS_JA},
        extra_types=parsed.extra_types,
        extra_relations=parsed.extra_relations,
    )
    # 選択肢シートの警告（もとからある選択肢が消されている など）を先頭に加える
    result.warnings[:0] = parsed.warnings
    # データ一式の警告は、読み込み結果の警告と同じリストのことがある（二重に追加しない）
    if result.dataset is not None and result.dataset.warnings is not result.warnings:
        result.dataset.warnings[:0] = parsed.warnings
    return result


def to_records(dataset: Dataset) -> tuple[list[dict], list[dict]]:
    """データ一式を、図で編集するための辞書のリスト（要素・依存関係）にする。"""
    return dataset.elements.to_dict("records"), dataset.dependencies.to_dict("records")


def load_from_records(elements: list[dict], dependencies: list[dict], source: str = "diagram") -> LoadResult:
    """図で編集した要素・依存関係を読み込む。

    Excel・CSVと同じ検証（名前の重複・存在しない参照先・区分値など）を必ず通すため、
    いったんCSVの形にしてから load_from_csv で読み込む。
    """
    element_columns = models.ELEMENT_REQUIRED_COLUMNS + models.ELEMENT_OPTIONAL_COLUMNS
    dependency_columns = models.DEPENDENCY_REQUIRED_COLUMNS + models.DEPENDENCY_OPTIONAL_COLUMNS

    def csv(records: list[dict], columns: list[str]) -> bytes:
        frame = pd.DataFrame(records).reindex(columns=columns).astype(object).fillna("")
        return frame.to_csv(index=False).encode("utf-8")

    # 利用者が追加した種類・関係の種類（Excelの選択肢シートで追加したもの）も、そのまま使えるようにする
    extra_types = frozenset(e["element_type"] for e in elements) - set(models.ELEMENT_TYPES)
    extra_relations = frozenset(d["relation_type"] for d in dependencies) - set(models.RELATION_TYPES)
    return load_from_csv(csv(elements, element_columns), csv(dependencies, dependency_columns), source=source,
                         labels=("要素", "つながり"), extra_types=extra_types, extra_relations=extra_relations)


def load_sample() -> Dataset:
    result = load_from_csv(
        (SAMPLE_DIR / "elements.csv").read_bytes(),
        (SAMPLE_DIR / "dependencies.csv").read_bytes(),
        source="sample",
    )
    if result.dataset is None:
        raise RuntimeError(f"サンプルデータが不正です: {result.errors}")
    return result.dataset


def load_scenarios() -> pd.DataFrame:
    df, errors = read_csv((SAMPLE_DIR / "scenarios.csv").read_bytes())
    if df is None:
        raise RuntimeError(f"シナリオデータが不正です: {errors}")
    return df
