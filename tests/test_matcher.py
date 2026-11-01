"""matcher（入力文からの変更対象候補の抽出）のテスト。"""

import pandas as pd
import pytest

from changescope.datasets import load_sample, load_scenarios
from changescope.matcher import find_candidates


def elements(*rows):
    return pd.DataFrame(rows, columns=["element_id", "name", "element_type", "aliases"])


def test_match_by_name_and_alias():
    df = elements(("S1", "勤怠管理システム", "system", "タイムカード"), ("D1", "人事部", "department", ""))
    assert find_candidates("タイムカードを廃止したい", df) == ["S1"]
    assert find_candidates("人事部の業務を変えたい", df) == ["D1"]


def test_shorter_match_inside_longer_match_is_dropped():
    # 「勤怠管理」（業務）は「勤怠管理システム」の一部なので候補にしない
    df = elements(("S1", "勤怠管理システム", "system", ""), ("P1", "勤怠管理業務", "process", "勤怠管理"))
    assert find_candidates("勤怠管理システムを変更したい", df) == ["S1"]


def test_separate_matches_are_all_kept_in_text_order():
    df = elements(("S1", "勤怠管理システム", "system", ""), ("S2", "給与計算システム", "system", ""))
    assert find_candidates("給与計算システムと勤怠管理システムを統合したい", df) == ["S2", "S1"]


def test_no_match_and_empty_aliases():
    df = elements(("S1", "会計システム", "system", None))
    assert find_candidates("新しいSaaSを入れたい", df) == []


@pytest.mark.parametrize("scenario_id", ["A", "B", "C", "D"])
def test_sample_scenarios_find_expected_target(scenario_id):
    scenarios = load_scenarios()
    row = scenarios[scenarios["scenario_id"] == scenario_id].iloc[0]
    assert find_candidates(row["input_text"], load_sample().elements) == [row["target_ids"]]
