"""分析結果から「次にやること」を作る（AIを使わず、登録データだけから決める）。

結果を見た人が迷わないよう、具体的な相手と確認事項まで示す。順番は実務の進め方に合わせる。
1. 変更対象の責任部門と方針を共有する
2. 要確認のつながりを確かめる（1件確かめると有無がはっきりする影響が多い順）
3. 見落としやすい影響（他部門・2段以上先）を、その部門に共有する
4. 影響の大きい要素について、責任部門に影響内容を確認する
5. 見落としチェックの項目を、変更計画・テスト計画に入れる
6. （段数の上限より先がある場合）さらに先の影響を確認する
7. 確認結果をデータに反映して、もう一度分析する
"""

from __future__ import annotations

from dataclasses import dataclass, field

import networkx as nx

from changescope import models
from changescope.graph_engine import ImpactResult, step_label
from changescope.gaps import REGISTRATION, Finding
from changescope.insights import department_of, hard_to_notice
from changescope.stakeholders import PERSON_TYPES, Stakeholder

TOP_IMPACTS = 3
MAX_ITEMS = 5
MAX_NAMES_PER_DEPARTMENT = 4


@dataclass
class Action:
    title: str
    detail: str
    items: list[str] = field(default_factory=list)
    # 要確認のつながり。重要なため、画面では1本ずつ枠で囲んで目立たせて表示する
    links: list["UncertainLink"] = field(default_factory=list)


@dataclass
class UncertainLink:
    """推定・未確認のつながり1本と、それを確かめると有無がはっきりする影響。

    1本のつながりが未確認だと、その先にある要素はすべて「要確認」になる。
    そのため、確かめるつながりの本数（本）と、要確認の影響の数（件）は一致しない。
    """

    dependency_id: str
    text: str  # 例：勤怠管理システム → 社内認証基盤（連携先）
    status: str
    note: str
    evidence: str
    contacts: list[str]
    affected_names: list[str] = field(default_factory=list)  # 確かめると有無がはっきりする影響（要素名）

    @property
    def affected(self) -> int:
        return len(self.affected_names)


def _contact_names(graph: nx.MultiDiGraph, element_ids: list[str]) -> list[str]:
    """要素の責任部門・担当の名前。部門・役割そのものなら自分自身。"""
    names = []
    for element_id in element_ids:
        node = graph.nodes[element_id]
        if node["element_type"] in PERSON_TYPES:
            names.append(node["name"])
            continue
        owner = node.get("owner", "")
        if owner in graph and graph.nodes[owner]["element_type"] in PERSON_TYPES:
            names.append(graph.nodes[owner]["name"])
        elif owner and owner not in graph:
            names.append(owner)  # 名前だけ書かれている担当
    return list(dict.fromkeys(names))


def find_uncertain_links(graph: nx.MultiDiGraph, result: ImpactResult) -> list[UncertainLink]:
    """影響の経路に含まれる推定・未確認のつながりを、関係する影響の多い順に返す。"""
    links: dict[str, UncertainLink] = {}
    for item in result.impacts:
        for step in item.path:
            if step.status == "confirmed":
                continue
            if step.dependency_id not in links:
                text = (f"{graph.nodes[step.from_id]['name']} → "
                        f"{graph.nodes[step.to_id]['name']}（{step_label(step)}）")
                links[step.dependency_id] = UncertainLink(
                    step.dependency_id, text, step.status, step.note, step.evidence,
                    _contact_names(graph, [step.from_id, step.to_id]),
                )
            links[step.dependency_id].affected_names.append(item.name)
    return sorted(links.values(), key=lambda link: (-link.affected, link.dependency_id))


def build_next_actions(graph: nx.MultiDiGraph, result: ImpactResult,
                       stakeholders: list[Stakeholder], gaps: list[Finding] | None = None) -> list[Action]:
    actions = []

    owners = [s.name for s in stakeholders if s.is_target_owner]
    if owners:
        actions.append(Action(
            "変更対象の責任部門と、変更の方針を共有する",
            "変更を進める前に、責任部門と目的・時期・範囲をすり合わせます。",
            [f"{name}" for name in owners],
        ))
    else:
        actions.append(Action(
            "変更対象の責任部門を決めて登録する",
            "変更対象に責任部門が登録されていません。誰が変更を判断するかを決め、"
            "Excelの「責任部門・担当」に記入してください。",
        ))

    links = find_uncertain_links(graph, result)
    if links:
        items = []
        if len(links) > MAX_ITEMS:
            items.append(f"ほか{len(links) - MAX_ITEMS}本（「要確認のつながり」タブで確認できます）")
        uncertain = sum(i.path_status != "confirmed" for i in result.impacts)
        actions.append(Action(
            f"要確認のつながりを確かめる（{len(links)}本）",
            "推定・未確認のつながりを、確認先の部門に事実確認します。"
            f"1本のつながりが未確認だと、その先にある要素はすべて要確認になるため、"
            f"この{len(links)}本を確かめれば、要確認の影響{uncertain}件の有無がまとめてはっきりします。"
            "上から順に確認すると、少ない確認で多くの影響の有無をはっきりさせられます。",
            items,
            links[:MAX_ITEMS],
        ))

    hidden = hard_to_notice(graph, result)
    if hidden:
        by_department: dict[str, list[str]] = {}
        for item in hidden:
            department = graph.nodes[department_of(graph, item.element_id)]["name"]
            by_department.setdefault(department, []).append(item.name)
        items = []
        for department, names in by_department.items():
            shown = "、".join(names[:MAX_NAMES_PER_DEPARTMENT])
            rest = f" ほか{len(names) - MAX_NAMES_PER_DEPARTMENT}件" if len(names) > MAX_NAMES_PER_DEPARTMENT else ""
            items.append(f"{department}：{shown}{rest}")
        actions.append(Action(
            f"見落としやすい影響を、その部門に共有する（{len(hidden)}件）",
            "変更対象の責任部門とは別の部門に、2段以上先で伝わる影響です。"
            "その部門は変更を知らない可能性が高いため、早めに共有して影響の有無を確認します。",
            items,
        ))

    top = result.impacts[:TOP_IMPACTS]
    if top:
        items = []
        for item in top:
            contacts = "、".join(_contact_names(graph, [item.element_id])) or "責任部門が未登録"
            items.append(f"{item.name}（影響度{item.score}）　確認先：{contacts}")
        actions.append(Action(
            "影響の大きい要素について、具体的な影響を確認する",
            "影響度の上位から、責任部門に「何が変わるか」「対応が必要か」を確認します。",
            items,
        ))

    if gaps:
        actions.append(Action(
            f"見落としチェックの項目を、変更計画・テスト計画に入れる（{len(gaps)}件）",
            "影響範囲から、変更時に忘れやすい確認事項と、登録が足りないデータを洗い出しています。"
            "「見落としチェック」タブで対象を確認し、計画に入れてください。",
            [f"{'【登録の不足】' if g.kind == REGISTRATION else ''}{g.title}" for g in gaps],
        ))

    if result.beyond_max_depth:
        actions.append(Action(
            "さらに先の影響を確認する",
            f"段数の上限より先にも{len(result.beyond_max_depth)}件の要素がつながっています。"
            "「何段先までたどるか」を増やして、もう一度分析してください。",
        ))

    actions.append(Action(
        "確認した結果をデータに反映し、もう一度分析する",
        "確認できたつながりはExcelの確認状態を「確認済」に、新しく分かったつながりは行を追加して、"
        "アップロードし直します。要確認が0件になっても、分かるのは「登録済みのつながりの中に未確認のものがない」"
        "ことだけです。登録していないつながり、たどった段数より先、情報が古くなったつながりは含まれません。",
    ))
    return actions
