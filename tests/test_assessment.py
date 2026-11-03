"""総合判定と結論のテスト。"""

import pandas as pd

from changescope.assessment import assess
from changescope.datasets import load_sample
from changescope.graph_engine import analyze_impact, build_graph
from changescope.stakeholders import find_stakeholders

DEPARTMENTS = [("D1", "department", ""), ("D2", "department", ""), ("D3", "department", "")]


def make_graph(elements: list[tuple], edges: list[tuple]):
    """elements は (id, element_type, owner)、edges は (id, from, to, status)。"""
    e = pd.DataFrame([{"element_id": i, "name": f"名{i}", "element_type": t, "owner": o} for i, t, o in elements])
    d = pd.DataFrame([
        {"dependency_id": i, "from_id": f, "to_id": t, "relation_type": "uses", "direction": "one_way",
         "evidence": "根拠", "status": s} for i, f, t, s in edges
    ], columns=["dependency_id", "from_id", "to_id", "relation_type", "direction", "evidence", "status"])
    return build_graph(e, d)


def assess_for(graph, targets):
    result = analyze_impact(graph, targets)
    return assess(graph, result, find_stakeholders(graph, result))


def test_level_by_number_of_departments():
    # 変更対象S（D1）から、D1・D2・D3 の要素へ影響する
    elements = DEPARTMENTS + [("S", "system", "D1"), ("A", "process", "D1"), ("B", "process", "D2"), ("C", "process", "D3")]
    small = make_graph(elements, [("1", "S", "A", "confirmed")])
    medium = make_graph(elements, [("1", "S", "A", "confirmed"), ("2", "S", "B", "confirmed")])
    large = make_graph(elements, [("1", "S", "A", "confirmed"), ("2", "S", "B", "confirmed"), ("3", "S", "C", "confirmed")])
    assert assess_for(small, ["S"]).level == "小"
    assert assess_for(medium, ["S"]).level == "中"
    assert assess_for(large, ["S"]).level == "大"


def test_first_step_names_owner_and_uncertain_links():
    g = make_graph(DEPARTMENTS + [("S", "system", "D1"), ("A", "process", "D1")], [("1", "S", "A", "unconfirmed")])
    a = assess_for(g, ["S"])
    assert a.first_step == ("まず、名D1と変更の方針を共有し、要確認のつながり1本を確かめてください"
                            "（「要確認のつながり」タブで一覧を確認できます）。")


def test_low_certainty_caution():
    g = make_graph(DEPARTMENTS + [("S", "system", "D1"), ("A", "process", "D1"), ("B", "process", "D1")],
                   [("1", "S", "A", "unconfirmed"), ("2", "S", "B", "confirmed")])
    assert "確定ではありません" in assess_for(g, ["S"]).caution  # 2件中1件（50%）が要確認

    confirmed = make_graph(DEPARTMENTS + [("S", "system", "D1"), ("A", "process", "D1")], [("1", "S", "A", "confirmed")])
    assert assess_for(confirmed, ["S"]).caution == ""


def test_all_confirmed_does_not_claim_completeness():
    # すべて確認済みでも、「登録済みの範囲」での判定だと示し、組織全体の漏れがないとは言わない（レビュー C01）
    from changescope.next_actions import build_next_actions

    g = make_graph(DEPARTMENTS + [("S", "system", "D1"), ("A", "process", "D1")], [("1", "S", "A", "confirmed")])
    a = assess_for(g, ["S"])
    assert "登録済みのつながりだけで判定" in a.basis
    result = analyze_impact(g, ["S"])
    texts = " ".join(f"{x.title} {x.detail}" for x in build_next_actions(g, result, find_stakeholders(g, result)))
    assert "漏れのない" not in texts and "登録していないつながり" in texts


def test_sample_scenarios():
    ds = load_sample()
    a = assess_for(ds.graph, ["SYS-ATT"])
    assert a.level == "大"
    assert a.headline == "影響範囲は「大」です。3部門・21件に影響が及ぶ可能性があります。"
    # 確かめる単位はつながり（本）。「次にやること」の本数とそろえる
    assert a.first_step.startswith("まず、人事部と変更の方針を共有し、要確認のつながり4本を確かめてください")
    assert "要確認の影響 6件（確認が必要なつながり 4本）" in a.basis
    assert assess_for(ds.graph, ["PRC-EXP"]).level == "中"


def test_conclusion_escapes_names(monkeypatch):
    from changescope import ui
    from changescope.assessment import Assessment

    captured = []
    monkeypatch.setattr(ui, "html", captured.append)
    ui.conclusion(Assessment("大", "見出し", "意味", "まず<script>x</script>", ["意識"], "根拠"))
    assert "<script>" not in captured[0]
