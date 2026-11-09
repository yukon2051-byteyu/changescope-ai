"""変更案A・Bの比較（3つの柱の③）。AIは使わず、各案の影響分析の結果と入力された内容から、判断の材料を作る。

比較結果は次の順に使う：要約 → 重要な違い → 判断前に確認すること → 比較表 → 「Aだけ・Bだけ・両方」の差分。
すべて、登録データの分析結果と利用者の入力から作る。登録データから分かることと、分からないことを次のように分ける。

- 目的への適合性は判定しない。変更対象の種類や影響件数から効果を推定せず、常に「未評価」と示す
- 利用者が書いた期待効果は「入力された見込み」、費用・期間は「入力値（ユーザー申告）」と示す。なければ数字を作らない
- 影響件数が少ない案を優位に見せない。総合点やおすすめ順位は作らない
- 確認先は登録データにある部門・担当だけを使い、なければ「確認先未設定」とする
"""

from __future__ import annotations

from dataclasses import astuple, dataclass, field

import networkx as nx

from changescope.assessment import Assessment, affected_departments, assess, uncertain_label
from changescope.gaps import Finding, find_gaps
from changescope.graph_engine import DEFAULT_MAX_DEPTH, ImpactItem, ImpactResult, analyze_impact
from changescope.insights import hard_to_notice
from changescope.models import element_type_label
from changescope.next_actions import UncertainLink, find_uncertain_links
from changescope.stakeholders import Stakeholder, find_stakeholders

ESTIMATE = "未入力・要見積もり"
UNEVALUATED = "未評価"
NO_CONTACT = "確認先未設定"
MAX_NAMES = 4  # 文章の中に並べる名前の上限（超えた分は件数で示す）
# 重要な違いで、影響先をまとめて見せる区分（要素の種類ごと）
GROUPS = [("業務", ("process",)), ("システム", ("system", "external_service")), ("部門・役割", ("department", "role")),
          ("データ・帳票", ("data", "document")), ("規程", ("rule",))]
# 判断前に確認することの並び順
GOAL, COST, DEPENDENCY = "目的", "費用・期間", "依存関係"
KIND_ORDER = {GOAL: 0, COST: 1, DEPENDENCY: 2}


@dataclass
class Goal:
    purpose: str = ""  # 解決したい課題／達成したい目的
    success: str = ""  # 成功条件（任意）


@dataclass
class OptionInput:
    name: str  # 案の名前（例：A案）
    text: str  # 変更内容
    targets: list[str]  # 変更対象の要素ID
    cost: str = ""  # 費用（任意。書かなければ「未入力・要見積もり」）
    period: str = ""  # 期間（任意）
    approach: str = ""  # 目的にどう対応する案か（任意）
    expected: str = ""  # 期待する効果と根拠（任意）
    premise: str = ""  # 前提条件／制約（任意）


@dataclass
class OptionResult:
    option: OptionInput
    result: ImpactResult
    stakeholders: list[Stakeholder]
    assessment: Assessment
    uncertain: list[UncertainLink]
    hidden: list[ImpactItem]
    gaps: list[Finding]
    departments: list[str] = field(default_factory=list)  # 影響を受ける部門の名前

    @property
    def involved(self) -> set[str]:
        """変更対象と影響先を合わせた要素。差分の一覧だけで使う（影響先の件数とは別の値）。"""
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
    difference: str  # 例：B案の方が3件多い。数で比べられない行は「—」


@dataclass
class Check:
    """判断前に確認すること。"""
    item: str
    why: str
    contact: str
    target: str  # A案・B案の名前、または「共通」
    basis: str
    kind: str  # 目的・費用・期間・依存関係（目的の確認と、依存関係からの確認を区別する）


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
    goal: Goal = field(default_factory=Goal)
    summary: list[str] = field(default_factory=list)
    differences: list[Row] = field(default_factory=list)
    checks: list[Check] = field(default_factory=list)
    max_depth: int = DEFAULT_MAX_DEPTH
    same_targets: bool = False
    cards: dict[str, list[tuple[str, list[str]]]] = field(default_factory=dict)  # 各案の要約（"a"・"b" → [(項目, 行)]）


def analyze_option(graph: nx.MultiDiGraph, option: OptionInput, max_depth: int = DEFAULT_MAX_DEPTH) -> OptionResult:
    result = analyze_impact(graph, option.targets, max_depth)
    stakeholders = find_stakeholders(graph, result)
    departments = sorted(graph.nodes[d]["name"] for d in affected_departments(graph, result))
    return OptionResult(option, result, stakeholders, assess(graph, result, stakeholders),
                        find_uncertain_links(graph, result), hard_to_notice(graph, result), find_gaps(graph, result),
                        departments)


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


def names_text(names: list[str], limit: int = MAX_NAMES, unit: str = "件") -> str:
    """名前を「、」でつなぐ。多いときは先頭だけ出し、残りを件数で示す。"""
    shown = "、".join(names[:limit])
    return f"{shown} ほか{len(names) - limit}{unit}" if len(names) > limit else shown


def comparison_key(goal: Goal, a: OptionInput, b: OptionInput, data_id: int) -> tuple:
    """比較の条件の目印。条件が変わったら、表示中の結果が古いと分かるようにする。"""
    return (astuple(goal), astuple(a), astuple(b), data_id)


def _scope(graph: nx.MultiDiGraph, targets: list[str]) -> str:
    """変更する範囲の説明。例：情報システム「勤怠管理システム」"""
    return "、".join(f"{element_type_label(graph.nodes[t]['element_type'])}「{graph.nodes[t]['name']}」" for t in targets)


def _only_in(result: OptionResult, other: OptionResult) -> list[ImpactItem]:
    """この案だけの影響先（影響の大きい順）。もう一方で変更対象や影響先になっているものは除く。"""
    return [i for i in result.result.impacts if i.element_id not in other.involved]


def _grouped(items: list[ImpactItem]) -> str:
    """影響先を種類ごとにまとめた文。"""
    parts = []
    for label, types in GROUPS:
        names = [i.name for i in items if i.element_type in types]
        if names:
            parts.append(f"{label}：{names_text(names, 3)}")
    return "／".join(parts)


def _effect_status(option: OptionInput, goal: Goal) -> tuple[str, str]:
    """目的への効果について（分かっていること, 分からないこと）。登録データからは効果を判定しない。"""
    known = f"入力された見込み：{option.expected}" if option.expected else "入力された見込みはありません"
    if option.approach:
        known += f"／目的への対応（入力）：{option.approach}"
    unknown = (f"「{goal.purpose}」を達成できるかは未評価です" if goal.purpose
               else "目的が未入力のため、適合性は未評価です")
    return known, unknown


def _fit_status(option: OptionInput, goal: Goal) -> str:
    if not goal.purpose:
        return f"{UNEVALUATED}（目的が未入力）"
    if option.expected:
        return f"{UNEVALUATED}（入力された見込み：{option.expected}。根拠の確認が必要）"
    return f"{UNEVALUATED}（効果の見込みが未入力）"


def _missing(option: OptionInput, goal: Goal, uncertain: int) -> list[str]:
    """判断に不足している情報。"""
    items = [] if goal.purpose else ["目的"]
    if not goal.success:
        items.append("成功条件")
    if not option.expected:
        items.append("期待する効果と根拠")
    if not option.cost:
        items.append("費用")
    if not option.period:
        items.append("期間")
    if uncertain:
        items.append(f"要確認のつながり{uncertain}本の確認結果")
    return items


def build_summary(graph: nx.MultiDiGraph, a: OptionResult, b: OptionResult, goal: Goal, same_targets: bool) -> list[str]:
    """比較の要約。件数の読み上げではなく、どこまで変更する案か、対応範囲がどう違うかを示す。"""
    name_a, name_b = a.option.name, b.option.name
    if same_targets:
        lines = [f"2つの案の変更対象は同じです（{_scope(graph, a.option.targets)}）。"
                 "件数は変更対象とつながりから計算するため、変更内容の文章が違っても同じ件数になります。"
                 "違いは、入力された内容と確認事項で比べてください。"]
    else:
        lines = [f"大きな違いは、変更する範囲です。{name_a}は{_scope(graph, a.option.targets)}を、"
                 f"{name_b}は{_scope(graph, b.option.targets)}を変更します。"]
        for option, other in ((a, b), (b, a)):
            only = _only_in(option, other)
            if only:
                lines.append(f"{option.option.name}では、{names_text([i.name for i in only], 3)}"
                             f"（この案だけの影響候補 {len(only)}件）への影響確認が必要です。")
    n_a, n_b = len(a.result.impacts), len(b.result.impacts)
    if not goal.purpose:
        lines.append("目的が未入力のため、どちらの案が目的に合うかは未評価です。")
    elif n_a == n_b:
        lines.append(f"どちらの案でも、「{goal.purpose}」を達成できるかは未評価です。")
    else:
        narrow = name_a if n_a < n_b else name_b
        lines.append(f"{narrow}は登録データ上の影響範囲が狭い一方、この案で「{goal.purpose}」を達成できるかは未評価です。"
                     "影響範囲の広さだけでは、案の良し悪しは決まりません。")
    return lines


def build_differences(graph: nx.MultiDiGraph, a: OptionResult, b: OptionResult, goal: Goal) -> list[Row]:
    """重要な違い。件数と具体名を組み合わせて対比する。"""
    def added(r: OptionResult, other: OptionResult) -> str:
        only = _only_in(r, other)
        return f"{len(only)}件　{_grouped(only)}" if only else "この案だけの影響候補はありません"

    def checks(r: OptionResult) -> str:
        if not r.uncertain:
            return uncertain_label(0)
        return f"{len(r.uncertain)}本：{names_text([l.text for l in r.uncertain], 2, '本')}"

    def actions(r: OptionResult) -> list[str]:
        partners = [s.name for s in r.stakeholders]
        lines = [f"確定（入力された変更）：{names_text([graph.nodes[t]['name'] for t in r.option.targets])}"]
        if partners:
            lines.append(f"調整の候補：{names_text(partners)}")
        if r.gaps:
            lines.append(f"確認が必要な作業の候補：{names_text([g.title for g in r.gaps], 3)}")
        return lines

    def effect(r: OptionResult) -> list[str]:
        known, unknown = _effect_status(r.option, goal)
        return [f"分かっていること：{known}", f"分からないこと：{unknown}"]

    return [
        Row("変更する対象と範囲", _scope(graph, a.option.targets), _scope(graph, b.option.targets), "—"),
        Row("追加で影響候補に含まれるもの", added(a, b), added(b, a), "—"),
        Row("実施前に確認が必要な事項", checks(a), checks(b), "—"),
        Row("必要な対応・調整の候補", "\n".join(actions(a)), "\n".join(actions(b)), "—"),
        Row("目的への効果", "\n".join(effect(a)), "\n".join(effect(b)), "—"),
    ]


def build_card(graph: nx.MultiDiGraph, r: OptionResult, goal: Goal, checks: list[Check]) -> list[tuple[str, list[str]]]:
    """各案の要約。両案で同じ順に、変更対象・主な影響先・最初に確認すること・対応・目的への効果を示す。"""
    impacts = r.result.impacts
    main = [f"{len(impacts)}件（直接{len(r.result.direct)}件・間接{len(r.result.indirect)}件）"]
    if impacts:
        main.append(_grouped(impacts))
    mine = [c for c in checks if c.target in (r.option.name, "共通")]
    first = [c for c in mine if c.kind == DEPENDENCY][:2] or [c for c in mine if c.kind == GOAL][:2]
    first_lines = [f"{c.item}（確認先：{c.contact}）" for c in first] or ["登録データからは、追加の確認事項は抽出されていません"]
    partners = [s.name for s in r.stakeholders]
    known, unknown = _effect_status(r.option, goal)
    return [
        ("変更対象", [_scope(graph, r.option.targets)]),
        ("主な影響先", main),
        ("最初に確認すること", first_lines),
        ("対応", [f"確定（入力された変更）：{names_text([graph.nodes[t]['name'] for t in r.option.targets])}の変更",
                  f"確認・調整の候補：{names_text(partners) if partners else '登録データにありません'}"]),
        ("目的への効果の評価状況", [unknown, known]),
    ]


def _owners(r: OptionResult) -> str:
    """確認先：変更対象の責任部門（登録データにあるものだけ）。"""
    return "、".join(s.name for s in r.stakeholders if s.is_target_owner) or NO_CONTACT


def build_checks(a: OptionResult, b: OptionResult, goal: Goal) -> list[Check]:
    """判断前に確認すること。重要なものから順に並べる。目的の確認と、依存関係からの確認を区別する。"""
    name_a, name_b = a.option.name, b.option.name
    found: list[Check] = []
    if not goal.purpose:
        found.append(Check("比較の目的と成功条件は何か", "目的がないと、どちらの案が合うかを判断できないため",
                           NO_CONTACT, "共通", "目的が未入力", GOAL))
    for r in (a, b):
        name = r.option.name
        if goal.purpose:
            found.append(Check(f"{name}で「{goal.purpose}」を達成できるか",
                               "目的への適合性は、登録データからは判定できないため", _owners(r), name, "入力された目的", GOAL))
        if goal.success:
            found.append(Check(f"{name}で成功条件「{goal.success}」を満たせるか",
                               "成功条件を満たすかは、登録データからは判定できないため", _owners(r), name, "入力された成功条件", GOAL))
        if r.option.expected:
            found.append(Check(f"{name}の見込み「{r.option.expected}」は確かか", "ユーザーが入力した見込みで、検証されていないため",
                               _owners(r), name, "入力された見込み", GOAL))
        if r.option.premise:
            found.append(Check(f"{name}の前提「{r.option.premise}」は成り立つか", "前提が崩れると、案の評価が変わるため",
                               _owners(r), name, "入力された前提条件", GOAL))

    missing = {key: [r.option.name for r in (a, b) if not getattr(r.option, key)] for key in ("cost", "period")}
    for key, label in (("cost", "導入費用・運用費用はいくらか"), ("period", "移行期間はどれくらいか")):
        names = missing[key]
        if names:
            found.append(Check(label if len(names) == 2 else f"{names[0]}の{label}", "費用・期間は、このツールでは計算しないため",
                               NO_CONTACT, "共通" if len(names) == 2 else names[0], "未入力", COST))

    links: dict[str, tuple[UncertainLink, list[str]]] = {}
    for r in (a, b):
        for link in r.uncertain:
            links.setdefault(link.dependency_id, (link, []))[1].append(r.option.name)
    ordered = sorted(links.values(), key=lambda item: (-item[0].affected, item[0].dependency_id))
    for link, names in ordered:
        found.append(Check(f"「{link.text}」は事実か", f"未確認のままだと、{link.affected}件の影響の有無が確定しないため",
                           "、".join(link.contacts) or NO_CONTACT, "共通" if len(names) == 2 else names[0],
                           f"登録された関係（{'未確認' if link.status == 'unconfirmed' else '推定'}）：{link.evidence}", DEPENDENCY))
    return sorted(found, key=lambda c: KIND_ORDER[c.kind])


def compare(graph: nx.MultiDiGraph, a: OptionInput, b: OptionInput, max_depth: int = DEFAULT_MAX_DEPTH,
            goal: Goal | None = None) -> Comparison:
    goal = goal or Goal()
    ra, rb = analyze_option(graph, a, max_depth), analyze_option(graph, b, max_depth)
    name = lambda element_id: graph.nodes[element_id]["name"]  # noqa: E731
    same_targets = sorted(a.targets) == sorted(b.targets)

    def count_row(viewpoint: str, a_count: int, b_count: int, unit: str, a_text: str, b_text: str) -> Row:
        return Row(viewpoint, a_text, b_text, difference(a_count, b_count, a.name, b.name, unit))

    def scope(r: OptionResult) -> str:
        return (f"影響先{len(r.result.impacts)}件（直接{len(r.result.direct)}件・間接{len(r.result.indirect)}件）"
                f"／影響の広さ {r.assessment.level}")

    def level_items(items: list[ImpactItem]) -> str:
        return f"{len(items)}件" + (f"：{names_text([i.name for i in items], 3)}" if items else "")

    def departments(r: OptionResult) -> str:
        return f"{len(r.departments)}部門" + (f"：{names_text(r.departments)}" if r.departments else "")

    def people(r: OptionResult) -> str:
        return f"{len(r.stakeholders)}件" + (f"：{names_text([s.name for s in r.stakeholders])}" if r.stakeholders else "")

    def hidden(r: OptionResult) -> str:
        return f"{len(r.hidden)}件" + (f"：{names_text([i.name for i in r.hidden], 3)}" if r.hidden else "")

    def actions(r: OptionResult) -> str:
        return f"{len(r.gaps)}項目" + (f"：{names_text([g.title for g in r.gaps], 3)}" if r.gaps else "")

    def declared(value: str) -> str:
        return f"入力値：{value}（ユーザー申告）" if value else ESTIMATE

    def targets(r: OptionResult) -> str:
        return f"{len(r.option.targets)}件：{names_text([name(t) for t in r.option.targets])}"

    def missing(r: OptionResult) -> str:
        return "、".join(_missing(r.option, goal, len(r.uncertain)))

    rows = [
        Row("目的への適合性／評価状況", _fit_status(a, goal), _fit_status(b, goal), "—"),
        count_row("変更する対象", len(a.targets), len(b.targets), "件", targets(ra), targets(rb)),
        count_row("影響先（直接＋間接）", len(ra.result.impacts), len(rb.result.impacts), "件", scope(ra), scope(rb)),
        count_row("　うち直接の影響先", len(ra.result.direct), len(rb.result.direct), "件",
                  level_items(ra.result.direct), level_items(rb.result.direct)),
        count_row("　うち間接の影響先", len(ra.result.indirect), len(rb.result.indirect), "件",
                  level_items(ra.result.indirect), level_items(rb.result.indirect)),
        count_row("影響を受ける部門", len(ra.departments), len(rb.departments), "部門", departments(ra), departments(rb)),
        count_row("関係者（部門・役割）", len(ra.stakeholders), len(rb.stakeholders), "件", people(ra), people(rb)),
        count_row("未確認のつながり", len(ra.uncertain), len(rb.uncertain), "本",
                  uncertain_label(len(ra.uncertain)), uncertain_label(len(rb.uncertain))),
        count_row("見落としやすい影響", len(ra.hidden), len(rb.hidden), "件", hidden(ra), hidden(rb)),
        count_row("必要な対応・調整の候補", len(ra.gaps), len(rb.gaps), "項目", actions(ra), actions(rb)),
        Row("リスクの大きさ", "未評価（損失・業務停止の影響は評価していません）",
            "未評価（損失・業務停止の影響は評価していません）", "—"),
        Row("費用", declared(a.cost), declared(b.cost), "—"),
        Row("期間", declared(a.period), declared(b.period), "—"),
        Row("判断に不足している情報", missing(ra), missing(rb), "—"),
    ]
    checks = build_checks(ra, rb, goal)
    return Comparison(
        ra, rb, rows,
        elements=split({e: name(e) for e in ra.involved}, {e: name(e) for e in rb.involved}),
        stakeholders=split({s.name: s.name for s in ra.stakeholders}, {s.name: s.name for s in rb.stakeholders}),
        uncertain=split({l.dependency_id: l.text for l in ra.uncertain}, {l.dependency_id: l.text for l in rb.uncertain}),
        hidden=split({i.element_id: i.name for i in ra.hidden}, {i.element_id: i.name for i in rb.hidden}),
        gaps=split({g.title: g.title for g in ra.gaps}, {g.title: g.title for g in rb.gaps}),
        goal=goal,
        summary=build_summary(graph, ra, rb, goal, same_targets),
        differences=build_differences(graph, ra, rb, goal),
        checks=checks,
        max_depth=max_depth,
        same_targets=same_targets,
        cards={"a": build_card(graph, ra, goal, checks), "b": build_card(graph, rb, goal, checks)},
    )
