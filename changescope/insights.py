"""見落としやすい影響の判定（AIを使わず、登録データだけから決める）。

- 他部門の影響    ：影響を受ける要素の所属部門が、変更対象の責任部門と異なる
- 見落としやすい影響：他部門の影響のうち、2段以上先（間接影響）にあるもの

変更を担当する部門から遠く、Excelのフィルター1回（直接のつながり）でも出てこないため、
事前の調査で最も漏れやすい。
"""

from __future__ import annotations

import networkx as nx

from changescope.graph_engine import ImpactItem, ImpactResult

CROSS_DEPARTMENT = "他部門"
HARD_TO_NOTICE = "見落としやすい"


def department_of(graph: nx.MultiDiGraph, element_id: str) -> str | None:
    """要素の所属部門（部門の要素ID）。部門ならそれ自身、役割や他の要素は責任部門・担当をたどる。"""
    seen = set()
    current = element_id
    while current in graph and current not in seen:
        seen.add(current)
        node = graph.nodes[current]
        if node["element_type"] == "department":
            return current
        current = node.get("owner", "")  # 責任部門・担当（役割なら、その所属部門へさらにたどる）
    return None


def target_departments(graph: nx.MultiDiGraph, result: ImpactResult) -> set[str]:
    return {d for t in result.targets if t in graph and (d := department_of(graph, t))}


def impact_tags(graph: nx.MultiDiGraph, result: ImpactResult) -> dict[str, str]:
    """影響ごとの注目ラベル（要素ID → 「見落としやすい」または「他部門」）。該当しない要素は含まない。

    変更対象の責任部門が分からない場合は、他部門かどうかを判断できないため空にする。
    """
    home = target_departments(graph, result)
    if not home:
        return {}
    tags = {}
    for item in result.impacts:
        department = department_of(graph, item.element_id)
        if department is None or department in home:
            continue
        tags[item.element_id] = HARD_TO_NOTICE if item.level == "indirect" else CROSS_DEPARTMENT
    return tags


def hard_to_notice(graph: nx.MultiDiGraph, result: ImpactResult) -> list[ImpactItem]:
    """見落としやすい影響を、影響の大きい順（分析結果の順）に返す。"""
    tags = impact_tags(graph, result)
    return [i for i in result.impacts if tags.get(i.element_id) == HARD_TO_NOTICE]
