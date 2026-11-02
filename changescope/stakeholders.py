"""影響を受ける関係者（部門・役割）を、登録された依存関係と責任部門から抽出する。

関係者になる理由は3種類。
- target_owner：変更対象の責任部門・担当（変更を主導・判断する立場）
- impacted    ：部門・役割そのものが影響範囲に含まれる（例：業務の担当部門、承認者）
- owner       ：責任を持つ要素が影響を受ける（例：給与計算システムの責任部門）
"""

from __future__ import annotations

from dataclasses import dataclass, field

import networkx as nx

from changescope import models
from changescope.graph_engine import ImpactResult, step_label

PERSON_TYPES = {"department", "role"}
_STATUS_RANK = {"unconfirmed": 0, "assumed": 1, "confirmed": 2}
_KIND_ORDER = {"target_owner": 0, "impacted": 1, "owner": 2}


@dataclass
class Reason:
    kind: str
    text: str
    related_id: str
    score: int  # 関係する影響の影響度（変更対象の所管は0）
    status: str


@dataclass
class Stakeholder:
    element_id: str  # 未登録の担当（ownerに名前だけ書かれている場合）は ""
    name: str
    element_type: str  # department / role / ""（未登録）
    department: str = ""  # 役割の場合の所属部門名
    reasons: list[Reason] = field(default_factory=list)

    @property
    def type_label(self) -> str:
        return models.element_type_label(self.element_type) if self.element_type else "未登録"

    @property
    def is_target_owner(self) -> bool:
        return any(r.kind == "target_owner" for r in self.reasons)

    @property
    def max_score(self) -> int:
        return max(r.score for r in self.reasons)

    @property
    def status(self) -> str:
        """理由の中で最も不確かな確認状態。1つでも推定・未確認があれば確認が必要。"""
        return min((r.status for r in self.reasons), key=_STATUS_RANK.__getitem__)


def find_stakeholders(graph: nx.MultiDiGraph, result: ImpactResult) -> list[Stakeholder]:
    """影響分析の結果から関係者の一覧を作る。重要な順（変更対象の所管 → 影響度の高い順）に並べる。"""
    found: dict[str, Stakeholder] = {}

    def add(key: str, reason: Reason) -> None:
        if key not in found:
            if key in graph:
                node = graph.nodes[key]
                owner = node.get("owner", "")
                department = graph.nodes[owner]["name"] if node["element_type"] == "role" and owner in graph else ""
                found[key] = Stakeholder(key, node["name"], node["element_type"], department)
            else:
                found[key] = Stakeholder("", key, "")
        reasons = found[key].reasons
        if not any(r.kind == reason.kind and r.related_id == reason.related_id for r in reasons):
            reasons.append(reason)

    def owner_key(element_id: str) -> str | None:
        """要素の責任部門・担当。部門・役割として登録されていれば要素ID、名前だけなら名前を返す。"""
        owner = graph.nodes[element_id].get("owner", "")
        if not owner:
            return None
        if owner in graph and graph.nodes[owner]["element_type"] not in PERSON_TYPES:
            return None  # 部門・役割以外が書かれている場合は関係者にしない
        return owner

    for target in result.targets:
        if target in graph and (key := owner_key(target)):
            add(key, Reason("target_owner", f"変更対象「{graph.nodes[target]['name']}」の責任部門・担当",
                            target, 0, "confirmed"))

    for item in result.impacts:
        level = "直接" if item.level == "direct" else "間接"
        if item.element_type in PERSON_TYPES:
            last = item.path[-1]
            text = f"「{graph.nodes[last.from_id]['name']}」の{step_label(last)}（{level}影響）"
            add(item.element_id, Reason("impacted", text, last.from_id, item.score, item.path_status))
        # 役割の責任部門は「所属」を表すので、責任の理由にはしない（所属部門として表示する）
        if item.element_type != "role" and (key := owner_key(item.element_id)):
            if key != item.element_id:
                add(key, Reason("owner", f"責任を持つ「{item.name}」が{level}影響を受ける",
                                item.element_id, item.score, item.path_status))

    stakeholders = list(found.values())
    for s in stakeholders:
        s.reasons.sort(key=lambda r: (_KIND_ORDER[r.kind], -r.score))
    stakeholders.sort(key=lambda s: (not s.is_target_owner, -s.max_score, -len(s.reasons), s.name))
    return stakeholders
