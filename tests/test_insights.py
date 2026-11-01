"""見落としやすい影響の判定のテスト。"""

import pandas as pd

from changescope.datasets import load_sample
from changescope.graph_engine import analyze_impact, build_graph
from changescope.insights import (
    CROSS_DEPARTMENT, HARD_TO_NOTICE, department_of, hard_to_notice, impact_tags,
)


def make_graph(elements: list[tuple], edges: list[tuple]):
    """elements は (id, element_type, owner)、edges は (id, from, to)。"""
    e = pd.DataFrame([{"element_id": i, "name": f"名{i}", "element_type": t, "owner": o} for i, t, o in elements])
    d = pd.DataFrame([
        {"dependency_id": i, "from_id": f, "to_id": t, "relation_type": "uses", "direction": "one_way",
         "evidence": "根拠", "status": "confirmed"} for i, f, t in edges
    ], columns=["dependency_id", "from_id", "to_id", "relation_type", "direction", "evidence", "status"])
    return build_graph(e, d)


BASE = [("HR", "department", ""), ("IT", "department", ""), ("ROLE", "role", "IT")]


def test_department_of_follows_owner_and_role():
    g = make_graph(BASE + [("S", "system", "ROLE"), ("D", "data", "")], [])
    assert department_of(g, "HR") == "HR"          # 部門はそれ自身
    assert department_of(g, "S") == "IT"           # 責任担当（役割）の所属部門をたどる
    assert department_of(g, "D") is None           # 責任部門が未登録


def test_department_of_stops_on_owner_loop():
    g = make_graph([("A", "role", "B"), ("B", "role", "A")], [])
    assert department_of(g, "A") is None  # 役割どうしが互いを指していても止まる


def test_tags_direct_cross_and_indirect_hard_to_notice():
    # 変更対象S（人事部）→ P1（人事部）→ P2（情報システム部）、S → P3（情報システム部）
    g = make_graph(
        BASE + [("S", "system", "HR"), ("P1", "process", "HR"), ("P2", "process", "IT"), ("P3", "process", "IT")],
        [("1", "S", "P1"), ("2", "P1", "P2"), ("3", "S", "P3")],
    )
    tags = impact_tags(g, analyze_impact(g, ["S"]))
    assert tags == {"P2": HARD_TO_NOTICE, "P3": CROSS_DEPARTMENT}  # 同じ部門のP1は対象外


def test_no_tags_when_target_department_unknown():
    g = make_graph(BASE + [("S", "system", ""), ("P", "process", "IT")], [("1", "S", "P")])
    assert impact_tags(g, analyze_impact(g, ["S"])) == {}


def test_sample_scenario_d_file_server_reaches_sales_and_hr():
    ds = load_sample()
    hidden = hard_to_notice(ds.graph, analyze_impact(ds.graph, ["SYS-FS"]))
    departments = {department_of(ds.graph, i.element_id) for i in hidden}
    assert {"DEP-SALES", "DEP-HR"} <= departments  # 情報システム部の変更が営業部・人事部に及ぶ
    assert all(i.level == "indirect" for i in hidden)
