"""関係者抽出と影響度スコアのテスト。"""

import pandas as pd

from changescope.datasets import load_sample
from changescope.graph_engine import analyze_impact, build_graph
from changescope.stakeholders import find_stakeholders


def make_graph(elements: list[tuple], edges: list[tuple]):
    """elements は (id, element_type, owner)、edges は (id, from, to, relation_type)。"""
    e = pd.DataFrame([{"element_id": i, "name": f"名{i}", "element_type": t, "owner": o} for i, t, o in elements])
    d = pd.DataFrame([
        {"dependency_id": i, "from_id": f, "to_id": t, "relation_type": r, "direction": "one_way",
         "evidence": "根拠", "status": "confirmed"} for i, f, t, r in edges
    ])
    return build_graph(e, d)


# ---------- 影響度スコア ----------

def test_score_components():
    # S → D → P1, S → D → P2, S → P1（P1は2本つながる）
    g = make_graph(
        [("S", "system", ""), ("D", "data", ""), ("P1", "process", ""), ("P2", "process", "")],
        [("1", "S", "D", "provides_data"), ("2", "D", "P1", "uses"), ("3", "D", "P2", "uses"), ("4", "S", "P1", "uses")],
    )
    items = {i.element_id: i for i in analyze_impact(g, ["S"]).impacts}
    assert (items["D"].proximity, items["D"].spread, items["D"].extra_paths) == (6, 1, 0)  # P2が経由
    assert (items["P1"].proximity, items["P1"].extra_paths) == (6, 1)  # S と D の2本
    assert items["P2"].score == 4


def test_impacts_are_sorted_by_score_desc():
    result = analyze_impact(load_sample().graph, ["SYS-ATT"])
    scores = [i.score for i in result.impacts]
    assert scores == sorted(scores, reverse=True)
    assert result.impacts[0].element_id == "PRC-ATT"  # 勤怠管理業務（近さ6＋波及4＋複数経路1）


# ---------- 関係者 ----------

def test_target_owner_comes_first():
    g = make_graph(
        [("S", "system", "DEP-A"), ("P", "process", "DEP-B"), ("DEP-A", "department", ""), ("DEP-B", "department", "")],
        [("1", "S", "P", "uses")],
    )
    people = find_stakeholders(g, analyze_impact(g, ["S"]))
    assert [p.element_id for p in people] == ["DEP-A", "DEP-B"]
    assert people[0].is_target_owner
    assert "責任を持つ「名P」" in people[1].reasons[0].text


def test_impacted_department_reason_uses_relation():
    g = make_graph([("P", "process", ""), ("DEP", "department", "")], [("1", "P", "DEP", "performs")])
    person = find_stakeholders(g, analyze_impact(g, ["P"]))[0]
    assert person.reasons[0].text == "「名P」の担当（直接影響）"


def test_role_shows_department_and_owner_is_not_reason():
    g = make_graph(
        [("P", "process", ""), ("R", "role", "DEP"), ("DEP", "department", "")],
        [("1", "P", "R", "approves")],
    )
    people = find_stakeholders(g, analyze_impact(g, ["P"]))
    assert [(p.element_id, p.department) for p in people] == [("R", "名DEP")]


def test_unregistered_owner_name_is_listed():
    g = make_graph([("S", "system", ""), ("D", "data", "総務課")], [("1", "S", "D", "provides_data")])
    person = find_stakeholders(g, analyze_impact(g, ["S"]))[0]
    assert (person.name, person.type_label) == ("総務課", "未登録")


def test_owner_that_is_not_a_person_is_ignored():
    g = make_graph([("S", "system", ""), ("D", "data", "S")], [("1", "S", "D", "provides_data")])
    assert find_stakeholders(g, analyze_impact(g, ["S"])) == []


def test_sample_scenario_c_stakeholders():
    ds = load_sample()
    people = {p.element_id: p for p in find_stakeholders(ds.graph, analyze_impact(ds.graph, ["PRC-EXP"]))}
    assert people["DEP-ACC"].is_target_owner  # 経費精算業務の責任部門＝経理部
    assert {"ROL-MGR", "ROL-DIRECTOR", "ROL-ACC-CHECK", "DEP-AUDIT"} <= set(people)
