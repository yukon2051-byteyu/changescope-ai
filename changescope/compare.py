"""変更案A・Bの比較（3つの柱の③）。AIは使わず、各案の影響分析の結果を並べる。

各案について、影響分析・関係者・要確認のつながり・見落としやすい影響・見落としチェックを計算し、
6つの観点で比べる。あわせて、関係する要素・部門・要確認のつながりを「Aだけ・Bだけ・両方」に分ける。
費用・期間は、利用者の入力があればそのまま表示し、なければ「要見積もり」とする（数字を作らない）。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import networkx as nx

from changescope.assessment import Assessment, assess
from changescope.gaps import Finding, find_gaps
from changescope.graph_engine import DEFAULT_MAX_DEPTH, ImpactItem, ImpactResult, analyze_impact
from changescope.insights import hard_to_notice
from changescope.next_actions import UncertainLink, find_uncertain_links
from changescope.stakeholders import Stakeholder, find_stakeholders

ESTIMATE = "要見積もり"


@dataclass
class OptionInput:
    name: str  # 案の名前（例：A案）
    text: str  # 変更内容
    targets: list[str]  # 変更対象の要素ID
    cost: str = ""  # 費用（任意。書かなければ「要見積もり」）
    period: str = ""  # 期間（任意）


@dataclass
class OptionResult:
    option: OptionInput
    result: ImpactResult
    stakeholders: list[Stakeholder]
    assessment: Assessment
    uncertain: list[UncertainLink]
    hidden: list[ImpactItem]
    gaps: list[Finding]

    @property
    def involved(self) -> set[str]:
        """この案で手を入れる要素と、影響を受ける要素（両方を合わせて「関係する要素」とする）。"""
        return set(self.result.targets) | {i.element_id for i in self.result.impacts}


@dataclass
class Split:
    """「Aだけ・Bだけ・両方」に分けた一覧（表示用の名前）。"""
    only_a: list[str] = field(default_factory=list)
    only_b: list[str] = field(default_factory=list)
    both: list[str] = field(default_factory=list)


@dataclass
class Row:
    viewpoint: str
    a: str
    b: str
    difference: str  # 例：B案の方が3件多い


@dataclass
class Comparison:
    a: OptionResult
    b: OptionResult
    rows: list[Row]
    elements: Split
    stakeholders: Split
    uncertain: Split
    hidden: Split
    gaps: Split


def analyze_option(graph: nx.MultiDiGraph, option: OptionInput, max_depth: int = DEFAULT_MAX_DEPTH) -> OptionResult:
    result = analyze_impact(graph, option.targets, max_depth)
    stakeholders = find_stakeholders(graph, result)
    return OptionResult(option, result, stakeholders, assess(graph, result, stakeholders),
                        find_uncertain_links(graph, result), hard_to_notice(graph, result), find_gaps(graph, result))


def split(a: dict[str, str], b: dict[str, str]) -> Split:
    """キー（要素IDなど）で比べ、表示用の名前で「Aだけ・Bだけ・両方」に分ける。"""
    return Split(only_a=sorted(a[k] for k in a.keys() - b.keys()),
                 only_b=sorted(b[k] for k in b.keys() - a.keys()),
                 both=sorted(a[k] for k in a.keys() & b.keys()))


def difference(a_count: int, b_count: int, a_name: str, b_name: str, unit: str) -> str:
    if a_count == b_count:
        return "同じ"
    more, fewer = (b_name, a_name) if b_count > a_count else (a_name, b_name)
    return f"{more}の方が{abs(b_count - a_count)}{unit}多い"


def compare(graph: nx.MultiDiGraph, a: OptionInput, b: OptionInput, max_depth: int = DEFAULT_MAX_DEPTH) -> Comparison:
    ra, rb = analyze_option(graph, a, max_depth), analyze_option(graph, b, max_depth)
    name = lambda element_id: graph.nodes[element_id]["name"]  # noqa: E731

    def count_row(viewpoint: str, a_count: int, b_count: int, unit: str, a_text: str = "", b_text: str = "") -> Row:
        return Row(viewpoint, a_text or f"{a_count}{unit}", b_text or f"{b_count}{unit}",
                   difference(a_count, b_count, a.name, b.name, unit))

    def scope(r: OptionResult) -> str:
        return (f"{len(r.involved)}件・広さ{r.assessment.level}（手を入れる{len(r.result.targets)}件・"
                f"直接{len(r.result.direct)}件・間接{len(r.result.indirect)}件）")

    rows = [
        # 手を入れる要素も含めて数える（変更対象を増やすと、その要素は「影響を受ける側」から「手を入れる側」に移るため）
        count_row("関係する要素（影響範囲）", len(ra.involved), len(rb.involved), "件", scope(ra), scope(rb)),
        count_row("関係する部門・担当", len(ra.stakeholders), len(rb.stakeholders), "件"),
        count_row("要確認のつながり（確かめる必要があるもの）", len(ra.uncertain), len(rb.uncertain), "本"),
        count_row("見落としやすい影響（別の部門に遠回りで伝わる）", len(ra.hidden), len(rb.hidden), "件"),
        count_row("確認すべき観点（見落としチェック）", len(ra.gaps), len(rb.gaps), "項目"),
        Row("費用・期間", f"費用：{a.cost or ESTIMATE}／期間：{a.period or ESTIMATE}",
            f"費用：{b.cost or ESTIMATE}／期間：{b.period or ESTIMATE}",
            "入力された値をそのまま表示（このツールでは計算しない）"),
    ]
    return Comparison(
        ra, rb, rows,
        elements=split({e: name(e) for e in ra.involved}, {e: name(e) for e in rb.involved}),
        stakeholders=split({s.name: s.name for s in ra.stakeholders}, {s.name: s.name for s in rb.stakeholders}),
        uncertain=split({l.dependency_id: l.text for l in ra.uncertain}, {l.dependency_id: l.text for l in rb.uncertain}),
        hidden=split({i.element_id: i.name for i in ra.hidden}, {i.element_id: i.name for i in rb.hidden}),
        gaps=split({g.title: g.title for g in ra.gaps}, {g.title: g.title for g in rb.gaps}),
    )
