"""「次にやること」のテスト。"""

import pandas as pd

from changescope.datasets import load_sample
from changescope.graph_engine import analyze_impact, build_graph
from changescope.next_actions import build_next_actions, find_uncertain_links
from changescope.stakeholders import find_stakeholders


def actions_for(graph, targets, max_depth=3):
    result = analyze_impact(graph, targets, max_depth)
    return build_next_actions(graph, result, find_stakeholders(graph, result))


def test_sample_scenario_a_actions_in_order():
    ds = load_sample()
    actions = actions_for(ds.graph, ["SYS-ATT"])
    titles = [a.title for a in actions]
    assert titles[0] == "変更対象の責任部門と、変更の方針を共有する"
    assert actions[0].items == ["人事部"]
    assert titles[1] == "要確認のつながりを確かめる（4件）"
    assert titles[2] == "見落としやすい影響を、その部門に共有する（5件）"
    assert actions[2].items == [
        "情報システム部：アカウント管理業務、メールサービス、システム管理者",
        "経理部：経理部、銀行振込サービス",
    ]
    assert titles[-1] == "確認した結果をデータに反映し、もう一度分析する"


def test_uncertain_links_sorted_by_affected_with_contacts():
    ds = load_sample()
    links = find_uncertain_links(ds.graph, analyze_impact(ds.graph, ["SYS-ATT"]))
    first = links[0]
    # 勤怠管理システム → 社内認証基盤（未確認）を確かめると、その先の3件の有無が分かる
    assert first.dependency_id == "D-006"
    assert first.affected == 3
    assert first.contacts == ["人事部", "情報システム部"]
    assert [link.affected for link in links] == sorted((link.affected for link in links), reverse=True)


def make_graph(owner="", status="confirmed"):
    e = pd.DataFrame([
        {"element_id": "S", "name": "システムS", "element_type": "system", "owner": owner},
        {"element_id": "P", "name": "業務P", "element_type": "process", "owner": ""},
        {"element_id": "DEP", "name": "部門", "element_type": "department", "owner": ""},
    ])
    d = pd.DataFrame([{"dependency_id": "1", "from_id": "S", "to_id": "P", "relation_type": "uses",
                       "direction": "one_way", "evidence": "根拠", "status": status}])
    return build_graph(e, d)


def test_missing_owner_asks_to_register_owner():
    actions = actions_for(make_graph(owner=""), ["S"])
    assert actions[0].title == "変更対象の責任部門を決めて登録する"


def test_no_uncertain_links_skips_that_action():
    titles = [a.title for a in actions_for(make_graph(owner="DEP"), ["S"])]
    assert not any(t.startswith("要確認") for t in titles)


def test_action_steps_escape_uploaded_text(monkeypatch):
    # アップロードされた要素名にHTMLが含まれていても、文字として表示される（実行されない）
    from changescope import ui
    from changescope.next_actions import Action

    captured = []
    monkeypatch.setattr(ui, "html", captured.append)
    ui.action_steps([Action("確認<b>", "説明", ["<script>alert(1)</script>"])])
    assert "<script>" not in captured[0]
    assert "&lt;script&gt;" in captured[0]


def test_data_table_shows_full_text_escaped(monkeypatch):
    from changescope import ui

    captured = []
    monkeypatch.setattr(ui, "html", captured.append)
    long_text = "とても長い説明" * 30
    ui.data_table(pd.DataFrame({"名前": ["<b>x</b>"], "理由": [["理由1", "理由2"]], "説明": [long_text]}))
    out = captured[0]
    assert long_text in out  # 省略せず全文を出す
    assert "&lt;b&gt;x&lt;/b&gt;" in out  # HTMLは文字として表示
    assert "理由1<br>理由2" in out  # リストは1項目ずつ改行


def test_beyond_max_depth_adds_action():
    ds = load_sample()
    titles = [a.title for a in actions_for(ds.graph, ["SYS-ATT"], max_depth=1)]
    assert "さらに先の影響を確認する" in titles
