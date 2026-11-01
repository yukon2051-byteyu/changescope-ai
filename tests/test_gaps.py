"""見落としチェックのテスト。"""

import pandas as pd

from changescope.datasets import load_sample
from changescope.gaps import PERSPECTIVE, REGISTRATION, find_gaps
from changescope.graph_engine import analyze_impact, build_graph


def make_graph(elements: list[tuple], edges: list[tuple]):
    """elements は (id, element_type, owner)、edges は (id, from, to, relation_type)。"""
    e = pd.DataFrame([{"element_id": i, "name": f"名{i}", "element_type": t, "owner": o} for i, t, o in elements])
    d = pd.DataFrame([
        {"dependency_id": i, "from_id": f, "to_id": t, "relation_type": r, "direction": "one_way",
         "evidence": "根拠", "status": "confirmed"} for i, f, t, r in edges
    ], columns=["dependency_id", "from_id", "to_id", "relation_type", "direction", "evidence", "status"])
    return build_graph(e, d)


def by_title(findings):
    return {f.title: f for f in findings}


def test_registration_gaps_detected():
    # S（責任部門あり）→ P（責任部門なし・担当なし）
    g = make_graph(
        [("HR", "department", ""), ("S", "system", "HR"), ("P", "process", "")],
        [("1", "S", "P", "uses")],
    )
    found = by_title(find_gaps(g, analyze_impact(g, ["S"])))
    assert found["責任部門が登録されていない要素"].items == ["名P"]
    assert found["責任部門が登録されていない要素"].kind == REGISTRATION
    assert found["担当が登録されていない業務"].items == ["名P"]


def test_no_registration_gaps_when_complete():
    g = make_graph(
        [("HR", "department", ""), ("S", "system", "HR"), ("P", "process", "HR")],
        [("1", "S", "P", "uses"), ("2", "P", "HR", "performs")],
    )
    kinds = {f.kind for f in find_gaps(g, analyze_impact(g, ["S"]))}
    assert REGISTRATION not in kinds


def test_rollback_always_for_system_change_but_not_for_department():
    g = make_graph([("HR", "department", ""), ("S", "system", "HR")], [])
    assert "切り戻し（元に戻す）計画" in by_title(find_gaps(g, analyze_impact(g, ["S"])))
    assert "切り戻し（元に戻す）計画" not in by_title(find_gaps(g, analyze_impact(g, ["HR"])))


def test_integration_partner_found_in_both_directions():
    g = make_graph(
        [("HR", "department", ""), ("S", "system", "HR"), ("A", "system", "HR"), ("B", "system", "HR")],
        [("1", "S", "A", "integrates_with"), ("2", "B", "S", "integrates_with")],
    )
    found = by_title(find_gaps(g, analyze_impact(g, ["S"])))
    assert sorted(found["システム連携の動作確認"].items) == ["名A", "名B"]


def test_sample_scenario_a_perspectives():
    ds = load_sample()
    found = by_title(find_gaps(ds.graph, analyze_impact(ds.graph, ["SYS-ATT"])))
    assert found["データの移行・引き継ぎ"].items == ["勤怠実績データ"]
    assert found["システム連携の動作確認"].items == ["給与計算システム", "社内認証基盤"]
    assert found["承認者・権限の設定"].items == ["承認者（課長）"]
    assert "就業規則" in found["社内規程との整合性"].items
    assert all(f.kind == PERSPECTIVE for f in found.values())  # お手本データなので登録の不足はない


def test_findings_list_escapes_names(monkeypatch):
    from changescope import ui
    from changescope.gaps import Finding

    captured = []
    monkeypatch.setattr(ui, "html", captured.append)
    ui.findings_list([Finding(REGISTRATION, "題", "説明", ["<img src=x onerror=alert(1)>"])])
    assert "<img" not in captured[0]


def test_sample_scenario_c_approvers_for_approval_flow_change():
    ds = load_sample()
    found = by_title(find_gaps(ds.graph, analyze_impact(ds.graph, ["PRC-EXP"])))
    assert set(found["承認者・権限の設定"].items) == {"承認者（課長）", "承認者（部長）", "経理確認担当"}
    assert {"経費規程", "職務権限規程"} <= set(found["社内規程との整合性"].items)
