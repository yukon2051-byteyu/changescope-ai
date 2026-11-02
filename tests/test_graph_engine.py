"""graph_engine のテスト。特に循環参照・双方向・存在しない要素・段数制限を確認する。"""

from pathlib import Path

import pandas as pd
import pytest

from changescope.csv_validator import validate_dependencies, validate_elements
from changescope.graph_engine import analyze_impact, build_graph, describe_path


def make_graph(element_ids: list[str], edges: list[tuple]):
    """テスト用の小さなグラフを作る。edges は (id, from, to, direction, status) のタプル。"""
    elements = pd.DataFrame(
        {"element_id": element_ids, "name": [f"要素{e}" for e in element_ids], "element_type": "system"}
    )
    dependencies = pd.DataFrame(
        [
            {"dependency_id": d, "from_id": f, "to_id": t, "relation_type": "uses",
             "direction": direction, "evidence": f"根拠{d}", "status": status}
            for d, f, t, direction, status in edges
        ],
        columns=["dependency_id", "from_id", "to_id", "relation_type", "direction", "evidence", "status"],
    )
    return build_graph(elements, dependencies)


def depths(result) -> dict[str, int]:
    return {i.element_id: i.depth for i in result.impacts}


# ---------- 基本 ----------

def test_direct_and_indirect():
    # A → B → C → D
    g = make_graph(list("ABCD"), [
        ("1", "A", "B", "one_way", "confirmed"),
        ("2", "B", "C", "one_way", "confirmed"),
        ("3", "C", "D", "one_way", "confirmed"),
    ])
    result = analyze_impact(g, ["A"])
    assert depths(result) == {"B": 1, "C": 2, "D": 3}
    assert [i.element_id for i in result.direct] == ["B"]
    assert [i.element_id for i in result.indirect] == ["C", "D"]


def test_one_way_is_not_followed_backwards():
    g = make_graph(list("AB"), [("1", "A", "B", "one_way", "confirmed")])
    assert analyze_impact(g, ["B"]).impacts == []


def test_both_direction_is_followed_backwards():
    g = make_graph(list("AB"), [("1", "A", "B", "both", "confirmed")])
    result = analyze_impact(g, ["B"])
    assert depths(result) == {"A": 1}
    assert result.impacts[0].path[0].reversed is True


def test_path_records_evidence():
    g = make_graph(list("ABC"), [
        ("1", "A", "B", "one_way", "confirmed"),
        ("2", "B", "C", "one_way", "confirmed"),
    ])
    item = next(i for i in analyze_impact(g, ["A"]).impacts if i.element_id == "C")
    assert [s.dependency_id for s in item.path] == ["1", "2"]
    assert [s.evidence for s in item.path] == ["根拠1", "根拠2"]
    assert describe_path(g, item) == "要素A → 要素B（利用先） → 要素C（利用先）"


def test_describe_reversed_step():
    g = make_graph(list("AB"), [("1", "A", "B", "both", "confirmed")])
    item = analyze_impact(g, ["B"]).impacts[0]
    assert describe_path(g, item) == "要素B → 要素A（利用される・双方向）"


def test_shortest_path_is_used():
    # A → B → C と A → C の両方がある場合、C は直接影響
    g = make_graph(list("ABC"), [
        ("1", "A", "B", "one_way", "confirmed"),
        ("2", "B", "C", "one_way", "confirmed"),
        ("3", "A", "C", "one_way", "confirmed"),
    ])
    assert depths(analyze_impact(g, ["A"]))["C"] == 1


# ---------- 循環参照・異常系 ----------

def test_cycle_does_not_loop_forever():
    # A → B → C → A（循環）
    g = make_graph(list("ABC"), [
        ("1", "A", "B", "one_way", "confirmed"),
        ("2", "B", "C", "one_way", "confirmed"),
        ("3", "C", "A", "one_way", "confirmed"),
    ])
    result = analyze_impact(g, ["A"])
    assert depths(result) == {"B": 1, "C": 2}  # 変更対象Aは影響一覧に含まれない


def test_both_direction_chain_does_not_loop():
    g = make_graph(list("ABC"), [
        ("1", "A", "B", "both", "confirmed"),
        ("2", "B", "C", "both", "confirmed"),
    ])
    assert depths(analyze_impact(g, ["B"])) == {"A": 1, "C": 1}


def test_unknown_target_is_reported_not_crashed():
    g = make_graph(list("AB"), [("1", "A", "B", "one_way", "confirmed")])
    result = analyze_impact(g, ["A", "ZZZ"])
    assert result.unknown_targets == ["ZZZ"]
    assert depths(result) == {"B": 1}


def test_isolated_target_has_no_impacts():
    g = make_graph(list("AB"), [])
    result = analyze_impact(g, ["A"])
    assert result.impacts == []
    assert result.unknown_targets == []


def test_dependency_to_missing_element_is_ignored():
    g = make_graph(list("AB"), [
        ("1", "A", "B", "one_way", "confirmed"),
        ("2", "A", "X", "one_way", "confirmed"),  # X は要素に存在しない
    ])
    assert "X" not in g
    assert depths(analyze_impact(g, ["A"])) == {"B": 1}


def test_invalid_max_depth():
    g = make_graph(list("A"), [])
    with pytest.raises(ValueError):
        analyze_impact(g, ["A"], max_depth=0)


# ---------- 段数制限・複数対象・確認状態 ----------

def test_max_depth_stops_and_reports_beyond():
    g = make_graph(list("ABCD"), [
        ("1", "A", "B", "one_way", "confirmed"),
        ("2", "B", "C", "one_way", "confirmed"),
        ("3", "C", "D", "one_way", "confirmed"),
    ])
    result = analyze_impact(g, ["A"], max_depth=2)
    assert depths(result) == {"B": 1, "C": 2}
    assert result.beyond_max_depth == ["D"]


def test_multiple_targets():
    # A と C を同時に変更。B は A の、D は C の直接影響。C は変更対象なので影響一覧に出ない
    g = make_graph(list("ABCD"), [
        ("1", "A", "B", "one_way", "confirmed"),
        ("2", "A", "C", "one_way", "confirmed"),
        ("3", "C", "D", "one_way", "confirmed"),
    ])
    assert depths(analyze_impact(g, ["A", "C"])) == {"B": 1, "D": 1}


def test_path_status_is_weakest_on_the_path():
    g = make_graph(list("ABC"), [
        ("1", "A", "B", "one_way", "unconfirmed"),
        ("2", "B", "C", "one_way", "confirmed"),
    ])
    item = next(i for i in analyze_impact(g, ["A"]).impacts if i.element_id == "C")
    assert item.path_status == "unconfirmed"


def test_result_order_is_stable():
    edges = [("1", "A", "B", "one_way", "confirmed"), ("2", "A", "C", "one_way", "confirmed"),
             ("3", "B", "D", "one_way", "confirmed"), ("4", "C", "D", "one_way", "confirmed")]
    first = analyze_impact(make_graph(list("ABCD"), edges), ["A"])
    second = analyze_impact(make_graph(list("ABCD"), list(reversed(edges))), ["A"])
    assert [(i.element_id, [s.dependency_id for s in i.path]) for i in first.impacts] == \
           [(i.element_id, [s.dependency_id for s in i.path]) for i in second.impacts]


# ---------- サンプルデータでの確認 ----------

SAMPLE_DIR = Path(__file__).resolve().parent.parent / "data" / "sample"


@pytest.fixture(scope="module")
def sample_graph():
    elements = validate_elements((SAMPLE_DIR / "elements.csv").read_bytes()).data
    deps = validate_dependencies((SAMPLE_DIR / "dependencies.csv").read_bytes(), set(elements["element_id"])).data
    return build_graph(elements, deps)


def test_sample_scenario_a(sample_graph):
    result = analyze_impact(sample_graph, ["SYS-ATT"])
    d = depths(result)
    assert d["SYS-PAY"] == 1          # 勤怠→給与のシステム連携は直接影響
    assert d["PRC-PAY"] == 2          # 月次給与計算は間接影響
    assert d["RUL-WORK"] == 2         # 就業規則は勤怠管理業務を経由して間接影響
    pay = next(i for i in result.impacts if i.element_id == "PRC-PAY")
    assert "勤怠管理システム" in describe_path(sample_graph, pay)


def test_sample_scenario_c_includes_cycle(sample_graph):
    # 経費精算⇄会計の循環があっても正常に終了する
    result = analyze_impact(sample_graph, ["PRC-EXP"])
    d = depths(result)
    assert d["ROL-DIRECTOR"] == 1
    assert d["SYS-EXP"] == 1          # 双方向の関係を逆向きにたどる
    assert d["SYS-ACC"] == 2
    assert "PRC-EXP" not in d
