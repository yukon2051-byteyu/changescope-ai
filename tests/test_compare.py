"""変更案A・Bの比較のテスト（AIは使わない）。"""

import pytest

from changescope.compare import ESTIMATE, OptionInput, compare, difference, split
from changescope.datasets import load_option_pairs, load_sample


@pytest.fixture(scope="module")
def graph():
    return load_sample().graph


def option(name, targets, cost="", period=""):
    return OptionInput(name, f"{name}の変更内容", targets, cost, period)


def test_split_and_difference():
    result = split({"1": "勤怠", "2": "給与"}, {"2": "給与", "3": "人事"})
    assert (result.only_a, result.only_b, result.both) == (["勤怠"], ["人事"], ["給与"])
    assert difference(3, 5, "A案", "B案", "件") == "B案の方が2件多い"
    assert difference(4, 1, "A案", "B案", "本") == "A案の方が3本多い"
    assert difference(2, 2, "A案", "B案", "件") == "同じ"


def test_compare_system_replacement_vs_procedure_change(graph):
    # A：勤怠管理システムを入れ替える ／ B：勤怠管理業務の手順だけを見直す
    result = compare(graph, option("A案", ["SYS-ATT"]), option("B案", ["PRC-ATT"]))
    rows = {r.viewpoint: r for r in result.rows}
    assert rows["関係する要素（影響範囲）"].difference == "A案の方が17件多い"
    assert rows["要確認のつながり（確かめる必要があるもの）"].b == "0本"
    # 要確認のつながりは、システムを入れ替える案だけにある（社内認証基盤との連携の確認など）
    assert any("社内認証基盤" in text for text in result.uncertain.only_a) and not result.uncertain.only_b
    assert "情報システム部" in result.stakeholders.only_a
    assert "勤怠管理業務" in result.elements.both  # B案で手を入れる要素は、A案では影響を受ける側
    assert len(result.a.involved) == 22 and len(result.b.involved) == 5


def test_target_counts_as_involved_when_moved_to_changed_side(graph):
    # 変更対象を増やすと、その要素は「影響を受ける側」から「手を入れる側」に移る。関係する要素の数は減らない
    result = compare(graph, option("A案", ["SYS-ATT"]), option("B案", ["SYS-ATT", "SYS-PAY"]))
    assert "SYS-PAY" in result.a.involved and "SYS-PAY" in result.b.involved
    assert len(result.b.involved) >= len(result.a.involved)


def test_cost_and_period_are_never_calculated(graph):
    result = compare(graph, option("A案", ["SYS-ATT"], cost="約300万円", period="6か月"), option("B案", ["PRC-ATT"]))
    cost_row = result.rows[-1]
    assert cost_row.viewpoint == "費用・期間"
    assert cost_row.a == "費用：約300万円／期間：6か月"  # 入力された値はそのまま
    assert cost_row.b == f"費用：{ESTIMATE}／期間：{ESTIMATE}"  # 入力がなければ数字を作らない


def test_sample_option_pairs_show_differences(graph):
    pairs = load_option_pairs()
    assert list(pairs["pair_id"]) == ["A", "B", "C", "D"]
    for _, row in pairs.iterrows():
        result = compare(graph, option(row["a_name"], row["a_targets"].split(";")),
                         option(row["b_name"], row["b_targets"].split(";")))
        assert result.rows[0].difference != "同じ"  # 入力例は、違いが分かる組み合わせにしている
        assert all(t in graph for t in [*result.a.option.targets, *result.b.option.targets])
