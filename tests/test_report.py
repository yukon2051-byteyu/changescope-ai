"""PDFレポートのテスト。日本語を含むPDFが作れることと、AIの結果のあり・なしの両方で作れることを確かめる。"""

import pytest

from changescope.assessment import assess
from changescope.compare import OptionInput, compare
from changescope.datasets import load_sample
from changescope.gaps import find_gaps
from changescope.graph_engine import analyze_impact
from changescope.insights import hard_to_notice
from changescope.next_actions import build_next_actions, find_uncertain_links
from changescope.oversight import load_sample_report
from changescope.report import FONT_DIR, analysis_report, comparison_report
from changescope.stakeholders import find_stakeholders


@pytest.fixture(scope="module")
def graph():
    return load_sample().graph


def make_analysis(graph, oversight=None, targets=("SYS-ATT",)):
    result = analyze_impact(graph, list(targets))
    people, gaps = find_stakeholders(graph, result), find_gaps(graph, result)
    return analysis_report(graph, "sample", "勤怠管理システムを変更したい", result, assess(graph, result, people),
                           build_next_actions(graph, result, people, gaps), people, find_uncertain_links(graph, result),
                           hard_to_notice(graph, result), gaps, oversight, 3)


def test_fonts_are_bundled_with_license():
    names = {p.name for p in FONT_DIR.iterdir()}
    assert {"BIZUDPGothic-Regular.ttf", "BIZUDPGothic-Bold.ttf", "OFL.txt"} <= names


def test_analysis_report_is_a_pdf_with_japanese_font(graph):
    pdf = make_analysis(graph)
    assert pdf.startswith(b"%PDF-")
    assert b"BIZUDPGothic" in pdf  # 日本語フォントが埋め込まれている（文字化けしない）
    assert len(pdf) < 2_000_000  # 使った文字だけを埋め込むので小さい


def test_analysis_report_with_ai_oversight_is_longer(graph):
    sample = load_sample_report("A")
    with_ai = make_analysis(graph, {"kind": "sample", "report": sample.report, "label": "AIによる分析のサンプル。"})
    assert len(with_ai) > len(make_analysis(graph))  # AIの確認漏れの節が加わる


def test_comparison_report(graph):
    result = compare(graph, OptionInput("A案", "システムを入れ替える", ["SYS-ATT"]),
                     OptionInput("B案", "手順だけを見直す", ["PRC-ATT"]))
    pdf = comparison_report(result, {"a": "A案（入れ替える）", "b": "B案（手順だけ）"}, "upload")
    assert pdf.startswith(b"%PDF-") and b"BIZUDPGothic" in pdf
