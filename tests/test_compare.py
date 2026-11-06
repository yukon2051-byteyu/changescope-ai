"""変更案A・Bの比較のテスト（AIは使わない）。"""

import pytest

from changescope.compare import ESTIMATE, NO_CONTACT, Goal, OptionInput, compare, comparison_key, difference, split
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
    assert rows["影響範囲と主要な影響先"].difference == "A案の方が17件多い"
    assert rows["影響範囲と主要な影響先"].a.startswith("影響先21件（直接7件・間接14件）")  # 影響分析の21件と同じ定義
    assert rows["未確認のつながり"].b == "登録された関係のうち未確認0本"  # 0本を安全・確認不要と書かない
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
    rows = {r.viewpoint: r for r in result.rows}
    assert rows["費用"].a == "入力値：約300万円（ユーザー申告）" and rows["期間"].a == "入力値：6か月（ユーザー申告）"
    assert rows["費用"].b == ESTIMATE == rows["期間"].b == "未入力・要見積もり"  # 入力がなければ数字を作らない


def test_sample_option_pairs_show_differences(graph):
    pairs = load_option_pairs()
    assert list(pairs["pair_id"]) == ["A", "B", "C", "D"]
    for _, row in pairs.iterrows():
        result = compare(graph, option(row["a_name"], row["a_targets"].split(";")),
                         option(row["b_name"], row["b_targets"].split(";")))
        rows = {r.viewpoint: r for r in result.rows}
        assert rows["影響範囲と主要な影響先"].difference != "同じ"  # 入力例は、違いが分かる組み合わせにしている
        assert row["goal"] and row["success"]  # 比較の入力例には共通の目的がある
        assert all(t in graph for t in [*result.a.option.targets, *result.b.option.targets])


# ---------- 判断の材料（要約・重要な違い・確認事項） ----------

GOAL = Goal("勤怠の締め作業の負担を減らしたい", "締め作業の時間を現状の半分にしたい")


def attendance(graph, goal=None):
    return compare(graph, OptionInput("A案", "システムを入れ替える", ["SYS-ATT"]),
                   OptionInput("B案", "手順だけを見直す", ["PRC-ATT"]), goal=goal)


def test_summary_tells_scope_not_only_counts(graph):
    summary = " ".join(attendance(graph, GOAL).summary)
    assert "情報システム「勤怠管理システム」" in summary and "業務プロセス「勤怠管理業務」" in summary
    assert "給与計算システム" in summary and "社内認証基盤" in summary
    assert "B案は登録データ上の影響範囲が狭い一方" in summary and "未評価" in summary


def test_fit_is_never_judged_without_evidence(graph):
    no_goal = attendance(graph)
    rows = {r.viewpoint: r for r in no_goal.rows}
    assert rows["目的への適合性／評価状況"].a == rows["目的への適合性／評価状況"].b == "未評価（目的が未入力）"
    with_goal = attendance(graph, GOAL)
    assert {r.viewpoint: r for r in with_goal.rows}["目的への適合性／評価状況"].a.startswith("未評価")
    text = " ".join([*with_goal.summary, *[f"{r.a} {r.b}" for r in with_goal.rows]])
    for word in ("効率化できる", "安い", "短期間", "おすすめ", "優れている", "安全"):
        assert word not in text  # 効果や優劣を推定しない


def test_expected_effect_is_shown_as_input(graph):
    result = compare(graph, OptionInput("A案", "入替", ["SYS-ATT"], expected="集計の手作業がなくなる"),
                     OptionInput("B案", "手順", ["PRC-ATT"]), goal=GOAL)
    row = {r.viewpoint: r for r in result.rows}["目的への適合性／評価状況"]
    assert "入力された見込み：集計の手作業がなくなる" in row.a and row.a.startswith("未評価")
    assert any("見込み" in c.item and c.target == "A案" for c in result.checks)


def test_checks_are_ordered_and_separated_by_kind(graph):
    checks = attendance(graph, GOAL).checks
    assert [c.kind for c in checks] == sorted((c.kind for c in checks), key=["目的", "費用・期間", "依存関係"].index)
    assert any(c.kind == "依存関係" and "社内認証基盤" in c.item and "情報システム部" in c.contact for c in checks)
    assert all(c.contact == NO_CONTACT for c in checks if c.kind == "費用・期間")  # 架空の確認先を補わない


def test_swapping_options_keeps_meaning(graph):
    ab = attendance(graph, GOAL)
    ba = compare(graph, OptionInput("A案", "手順だけを見直す", ["PRC-ATT"]),
                 OptionInput("B案", "システムを入れ替える", ["SYS-ATT"]), goal=GOAL)
    assert (ab.elements.only_a, ab.elements.only_b, ab.elements.both) == (ba.elements.only_b, ba.elements.only_a, ba.elements.both)
    assert len(ab.checks) == len(ba.checks)
    assert any("A案は登録データ上の影響範囲が狭い" in line for line in ba.summary)


def test_same_targets_explain_same_counts(graph):
    result = compare(graph, OptionInput("A案", "クラウドへ", ["SYS-ATT"]), OptionInput("B案", "オンプレで更新", ["SYS-ATT"]))
    assert result.same_targets
    assert "変更内容の文章が違っても同じ件数" in result.summary[0]
    assert {r.viewpoint: r for r in result.rows}["影響範囲と主要な影響先"].difference == "同じ"


def test_comparison_key_changes_with_conditions():
    a, b = OptionInput("A案", "x", ["S"]), OptionInput("B案", "y", ["T"])
    key = comparison_key(Goal("目的"), a, b, 1)
    assert key == comparison_key(Goal("目的"), a, b, 1)
    assert key != comparison_key(Goal("別"), a, b, 1) and key != comparison_key(Goal("目的"), a, b, 2)
