"""架空サンプルデータのテスト。デモで使うデータが検証を通り、4シナリオを分析できる状態か確認する。"""

from pathlib import Path

import networkx as nx
import pytest

from changescope.csv_validator import read_csv, validate_dependencies, validate_elements

SAMPLE_DIR = Path(__file__).resolve().parent.parent / "data" / "sample"


@pytest.fixture(scope="module")
def elements():
    result = validate_elements((SAMPLE_DIR / "elements.csv").read_bytes())
    assert result.ok, [str(e) for e in result.errors]
    return result


@pytest.fixture(scope="module")
def dependencies(elements):
    ids = set(elements.data["element_id"])
    result = validate_dependencies((SAMPLE_DIR / "dependencies.csv").read_bytes(), ids)
    assert result.ok, [str(e) for e in result.errors]
    return result


@pytest.fixture(scope="module")
def scenarios():
    df, errors = read_csv((SAMPLE_DIR / "scenarios.csv").read_bytes())
    assert not errors
    return df


def test_sample_has_no_errors_or_warnings(elements, dependencies):
    # デモ用データは「お手本」なので、警告（除外・統合）も出ない状態にしておく
    assert elements.warnings == []
    assert dependencies.warnings == []


def test_sample_covers_four_departments_and_all_element_types(elements):
    names = set(elements.data["name"])
    assert {"人事部", "経理部", "営業部", "情報システム部"} <= names
    assert set(elements.data["element_type"]) == {
        "process", "system", "department", "role", "data", "document", "external_service", "rule",
    }


def test_sample_includes_all_statuses(dependencies):
    # 確定情報と未確認事項を区別するデモのため、3種類の確認状態をすべて含める
    assert set(dependencies.data["status"]) == {"confirmed", "unconfirmed", "assumed"}


def test_sample_includes_a_cycle(dependencies):
    # 循環参照への対応をデモで示せるよう、現実的な循環（経費精算⇄会計）を含める
    graph = nx.DiGraph()
    graph.add_edges_from(zip(dependencies.data["from_id"], dependencies.data["to_id"]))
    assert not nx.is_directed_acyclic_graph(graph)


def test_every_element_is_connected(elements, dependencies):
    used = set(dependencies.data["from_id"]) | set(dependencies.data["to_id"])
    isolated = set(elements.data["element_id"]) - used
    assert isolated == set(), f"どこにもつながっていない要素: {isolated}"


def _reachable(dependencies, start: str) -> set[str]:
    """簡易的な到達確認（本番の探索エンジンはPhase 1-4で作成）。双方向の関係は逆向きもたどる。"""
    graph = nx.DiGraph()
    for _, row in dependencies.data.iterrows():
        graph.add_edge(row["from_id"], row["to_id"])
        if row["direction"] == "both":
            graph.add_edge(row["to_id"], row["from_id"])
    return nx.descendants(graph, start)


# 指示書4章の「想定される影響候補」のうち、登録データからたどれるべき要素
EXPECTED = {
    "A": {"SYS-PAY", "PRC-ATT", "ROL-EMP", "ROL-MGR", "DEP-HR", "RUL-WORK"},
    "B": {"DAT-CUST", "DAT-DEAL", "DOC-SALES-RPT", "DOC-CUST-LIST", "ROL-SALES-REP", "SYS-ACC"},
    "C": {"ROL-MGR", "ROL-DIRECTOR", "ROL-ACC-CHECK", "RUL-AUTH", "RUL-EXP", "SYS-EXP", "DEP-ACC", "DAT-AUDITLOG"},
    "D": {"DAT-ACL", "SYS-AD", "SYS-CUST-XLS", "PRC-BACKUP", "RUL-SEC", "PRC-ACCOUNT"},
}


@pytest.mark.parametrize("scenario_id", ["A", "B", "C", "D"])
def test_scenario_targets_reach_expected_impacts(scenario_id, elements, dependencies, scenarios):
    row = scenarios[scenarios["scenario_id"] == scenario_id].iloc[0]
    target = row["target_ids"]
    assert target in set(elements.data["element_id"])
    missing = EXPECTED[scenario_id] - _reachable(dependencies, target)
    assert missing == set(), f"シナリオ{scenario_id}で到達できない要素: {missing}"
