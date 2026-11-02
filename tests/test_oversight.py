"""確認漏れを見つけるAIのテスト。AIの回答は偽物（モック）で作る（料金がかからない）。"""

from types import SimpleNamespace

import pytest

from changescope.access import check_access_code
from changescope.ai_client import AIResult
from changescope.datasets import load_sample
from changescope.gaps import find_gaps
from changescope.graph_engine import analyze_impact
from changescope.insights import hard_to_notice
from changescope.oversight import (
    ESTIMATE, GUESS, REGISTERED, SCHEMA, build_prompt, find_oversights, load_sample_report, scrub_numbers, validate,
)
from changescope.stakeholders import find_stakeholders
from changescope.usage_store import hash_user

CHANGE = "現在の勤怠管理システムを新しいクラウドサービスに変更したい"


@pytest.fixture(scope="module")
def scenario_a():
    ds = load_sample()
    result = analyze_impact(ds.graph, ["SYS-ATT"])
    return ds.graph, result, find_stakeholders(ds.graph, result), find_gaps(ds.graph, result), hard_to_notice(ds.graph, result)


def finding(**overrides):
    base = {"title": "連携が未確認", "detail": "確認しないと給与計算が止まる", "viewpoint": "システム",
            "importance": "高", "contact": "情報システム部", "question": "連携方法は変わりますか？", "evidence_ids": []}
    return {**base, **overrides}


def raw_answer(findings):
    return {"findings": findings, "department_points": [], "risks": [], "hidden_costs": [], "approach": [],
            "unregistered": []}


# ---------- AIに渡す材料 ----------

def test_prompt_contains_numbered_links_people_and_wrapped_input(scenario_a):
    graph, result, people, gaps, hidden = scenario_a
    prompt = build_prompt(graph, result, CHANGE, people, gaps, hidden)
    assert "<user_input>" in prompt and CHANGE in prompt
    assert "D-006: 勤怠管理システム → 社内認証基盤" in prompt  # 番号つきのつながり
    assert "未確認" in prompt and "シングルサインオン利用の有無は要確認" in prompt  # 確認状態と補足
    assert "- 人事部" in prompt and "- 情報システム部" in prompt  # 確認先の候補


# ---------- 回答を確かめる ----------

def test_evidence_must_exist_to_be_registered(scenario_a):
    graph, result, *_ = scenario_a
    report = validate(raw_answer([
        finding(title="根拠あり", evidence_ids=["D-006", "D-999"]),  # D-999 は存在しない
        finding(title="根拠なし", evidence_ids=["D-999"]),
        finding(title="推測", evidence_ids=[]),
    ]), graph, result)
    by_title = {f.title: f for f in report.findings}
    assert by_title["根拠あり"].basis == REGISTERED
    assert len(by_title["根拠あり"].evidence) == 1 and by_title["根拠あり"].evidence[0].startswith("D-006")
    assert by_title["根拠なし"].basis == GUESS  # 存在しない番号だけなら推測扱い
    assert by_title["推測"].basis == GUESS


def test_contact_registered_or_candidate(scenario_a):
    graph, result, *_ = scenario_a
    report = validate(raw_answer([finding(contact="人事部（給与担当）"), finding(contact="総務課")]), graph, result)
    assert [f.contact_registered for f in report.findings] == [True, False]


def test_money_and_period_numbers_are_replaced():
    text = "並行稼働に3か月、費用は約200万円、作業は10人日。承認は3段階のまま"
    scrubbed = scrub_numbers(text)
    assert "3か月" not in scrubbed and "200万円" not in scrubbed and "10人日" not in scrubbed
    assert scrubbed.count(ESTIMATE) == 3
    assert "3段階" in scrubbed  # 費用・期間ではない数字は残す


def test_link_ids_in_text_are_replaced_with_names(scenario_a):
    # 画面ではIDを見せないため、文章中のD番号はつながりの名前にする
    graph, result, *_ = scenario_a
    report = validate(raw_answer([finding(
        detail="D-006で連携が未確認（D-003、D-001）。給与仕訳（D-021、推定）も確認。D-999は存在しない")]), graph, result)
    detail = report.findings[0].detail
    assert "D-" not in detail
    assert detail.startswith("「勤怠管理システム → 社内認証基盤」で連携が未確認。")
    assert "給与仕訳（推定）" in detail


def test_findings_sorted_by_importance_then_registered_first(scenario_a):
    graph, result, *_ = scenario_a
    report = validate(raw_answer([
        finding(title="低", importance="低"),
        finding(title="高・推測", importance="高"),
        finding(title="高・根拠", importance="高", evidence_ids=["D-006"]),
    ]), graph, result)
    assert [f.title for f in report.findings] == ["高・根拠", "高・推測", "低"]


def test_unregistered_excludes_existing_elements(scenario_a):
    graph, result, *_ = scenario_a
    raw = raw_answer([])
    raw["unregistered"] = [{"name": "人事部", "element_type": "部門", "reason": "既存"},
                           {"name": "打刻用の端末", "element_type": "外部サービス", "reason": "新システムで変わる"}]
    assert [u["name"] for u in validate(raw, graph, result).unregistered] == ["打刻用の端末"]


# ---------- 呼び出し全体 ----------

class FakeAIClient:
    def __init__(self, answer):
        self.answer, self.calls = answer, []

    def call_json(self, feature, system, prompt, schema, user_key, user_text=""):
        self.calls.append(SimpleNamespace(feature=feature, prompt=prompt, schema=schema, user_text=user_text))
        return self.answer


def test_find_oversights_success(scenario_a):
    graph, result, people, gaps, hidden = scenario_a
    client = FakeAIClient(AIResult(True, data=raw_answer([finding(evidence_ids=["D-006"])]),
                                   input_tokens=5000, output_tokens=3000, cost_usd=0.002))
    report, message = find_oversights(client, graph, result, CHANGE, people, gaps, hidden, "user")
    assert message == "" and report.findings[0].basis == REGISTERED
    assert report.cost_usd == 0.002
    assert client.calls[0].user_text == CHANGE  # 入力の長さの確認には、利用者の入力文だけを使う


def test_find_oversights_failure_returns_message(scenario_a):
    graph, result, people, gaps, hidden = scenario_a
    client = FakeAIClient(AIResult(False, message="AIの回答が時間内に返ってきませんでした。"))
    report, message = find_oversights(client, graph, result, CHANGE, people, gaps, hidden, "user")
    assert report is None and "時間内" in message


def test_schema_is_strict():
    # 回答の形の指定：すべての項目が必須で、決めた項目以外を入れさせない
    def check(node):
        if node.get("type") == "object":
            assert node["additionalProperties"] is False
            assert set(node["required"]) == set(node["properties"])
            for child in node["properties"].values():
                check(child)
        if node.get("type") == "array":
            check(node["items"])
    check(SCHEMA)


# ---------- 事前生成のサンプル・アクセスコード ----------

@pytest.mark.parametrize("scenario_id", ["A", "B", "C", "D"])
def test_sample_reports_load(scenario_id):
    sample = load_sample_report(scenario_id)
    report = sample.report
    assert sample.model and sample.generated_on
    assert report.findings and report.unregistered  # 確認漏れと未登録の推測が入っている
    assert all(f.basis in (REGISTERED, GUESS) for f in report.findings)
    assert all("D-" not in f.title + f.detail + f.question for f in report.findings)  # 文章にIDを見せない


def test_missing_sample_returns_none():
    assert load_sample_report("Z") is None


def test_access_code_check():
    codes = ["demo-2026"]
    assert check_access_code("demo-2026", codes) == hash_user("demo-2026")
    assert check_access_code(" demo-2026 ", codes) == hash_user("demo-2026")  # 前後の空白は無視
    assert check_access_code("wrong", codes) is None
    assert check_access_code("", codes) is None
    assert check_access_code("demo-2026", []) is None  # コードが設定されていなければ使えない
