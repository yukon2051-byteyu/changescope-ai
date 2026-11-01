"""変更影響の探索エンジン。

検証済みの要素・依存関係からグラフ（点と線の構造）を作り、変更対象から影響が伝わる要素を
幅優先探索（近い要素から順に広げていく探索）で抽出する。AIは使わず、結果には必ず
「どの依存関係をたどったか」という経路を付ける。

- 1段目の要素 = 直接影響、2段目以降 = 間接影響
- 一度たどった要素は再訪しないため、循環参照があっても無限ループしない
- 最大段数で探索を打ち切り、その先にも影響がありうる場合は記録する
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

import networkx as nx
import pandas as pd

from changescope import models

DEFAULT_MAX_DEPTH = 3

# 影響度スコアの「近さ」の点数（段数 → 点）。表にない段数は1点
PROXIMITY_POINTS = {1: 6, 2: 4, 3: 2}

# 確認状態の確かさの順位（小さいほど不確か）。経路の中で最も不確かな状態をその影響の状態とする
_STATUS_RANK = {"unconfirmed": 0, "assumed": 1, "confirmed": 2}


@dataclass
class Step:
    """経路の1区間（ある依存関係を1本たどったこと）。"""

    dependency_id: str
    from_id: str
    to_id: str
    relation_type: str
    evidence: str
    status: str
    reversed: bool  # 双方向の関係を逆向きにたどった場合 True
    note: str = ""


@dataclass
class ImpactItem:
    """影響を受ける要素1件。"""

    element_id: str
    name: str
    element_type: str
    depth: int
    path: list[Step]
    spread: int = 0  # 波及数：この要素を経由して影響が伝わる要素の数
    extra_paths: int = 0  # 複数経路：最短経路以外にも影響を受けるつながりの数

    @property
    def proximity(self) -> int:
        """近さの点数。変更対象に近いほど高い。"""
        return PROXIMITY_POINTS.get(self.depth, 1)

    @property
    def score(self) -> int:
        """影響度 ＝ 近さ ＋ 波及数 ＋ 複数経路。確からしさ（確認状態）は別の軸として含めない。"""
        return self.proximity + self.spread + self.extra_paths

    @property
    def level(self) -> str:
        return "direct" if self.depth == 1 else "indirect"

    @property
    def path_status(self) -> str:
        """経路上で最も不確かな確認状態。1本でも未確認の関係を通れば、その影響は未確認扱い。"""
        return min((s.status for s in self.path), key=_STATUS_RANK.__getitem__)


@dataclass
class ImpactResult:
    targets: list[str]
    impacts: list[ImpactItem] = field(default_factory=list)
    unknown_targets: list[str] = field(default_factory=list)
    # 最大段数で打ち切った先に、まだ影響がありうる要素
    beyond_max_depth: list[str] = field(default_factory=list)

    @property
    def direct(self) -> list[ImpactItem]:
        return [i for i in self.impacts if i.level == "direct"]

    @property
    def indirect(self) -> list[ImpactItem]:
        return [i for i in self.impacts if i.level == "indirect"]


def build_graph(elements: pd.DataFrame, dependencies: pd.DataFrame) -> nx.MultiDiGraph:
    """要素と依存関係からグラフを作る。

    同じ2要素の間に種類の違う関係が複数ありうるため、MultiDiGraph（向きあり・複数の線を許す）を使う。
    双方向（both）の関係は、逆向きの線も追加する。
    """
    graph = nx.MultiDiGraph()
    for _, row in elements.iterrows():
        owner = row.get("owner", "")
        graph.add_node(row["element_id"], name=row["name"], element_type=row["element_type"],
                       owner=owner if isinstance(owner, str) else "")

    # 検証済みデータが前提だが、念のため存在しない要素への線は追加しない
    for _, row in dependencies.sort_values("dependency_id").iterrows():
        if row["from_id"] not in graph or row["to_id"] not in graph:
            continue
        attrs = {
            "dependency_id": row["dependency_id"],
            "relation_type": row["relation_type"],
            "evidence": row["evidence"],
            "status": row["status"],
            "note": row.get("note", ""),
        }
        graph.add_edge(row["from_id"], row["to_id"], key=row["dependency_id"], reversed=False, **attrs)
        if row["direction"] == "both":
            graph.add_edge(row["to_id"], row["from_id"], key=row["dependency_id"] + "~r", reversed=True, **attrs)
    return graph


def analyze_impact(graph: nx.MultiDiGraph, target_ids: list[str], max_depth: int = DEFAULT_MAX_DEPTH) -> ImpactResult:
    """変更対象から影響が伝わる要素を探索する。各要素には最短の経路を1本記録する。"""
    if max_depth < 1:
        raise ValueError("max_depth は1以上を指定してください。")

    result = ImpactResult(targets=list(target_ids))
    starts = [t for t in dict.fromkeys(target_ids) if t in graph]
    result.unknown_targets = [t for t in target_ids if t not in graph]

    # 変更対象そのものは影響一覧に含めない（深さ0として訪問済みにする）
    paths: dict[str, list[Step]] = {t: [] for t in starts}
    queue = deque(starts)
    beyond = set()

    while queue:
        current = queue.popleft()
        depth = len(paths[current])
        # 結果を毎回同じ順番にするため、依存関係IDの順にたどる
        edges = sorted(graph.out_edges(current, keys=True, data=True), key=lambda e: e[2])
        for _, neighbor, _, data in edges:
            if neighbor in paths:
                continue  # 訪問済み（循環参照・合流）はたどらない
            if depth >= max_depth:
                beyond.add(neighbor)
                continue
            step = Step(
                dependency_id=data["dependency_id"],
                from_id=current,
                to_id=neighbor,
                relation_type=data["relation_type"],
                evidence=data["evidence"],
                status=data["status"],
                reversed=data["reversed"],
                note=data["note"],
            )
            paths[neighbor] = paths[current] + [step]
            queue.append(neighbor)

    # 波及数：各影響の経路の途中にある要素ごとに、経由して影響が伝わった件数を数える
    spread = {element_id: 0 for element_id in paths}
    for path in paths.values():
        for step in path[:-1]:
            spread[step.to_id] += 1

    affected = set(paths)
    for element_id, path in paths.items():
        if not path:
            continue
        node = graph.nodes[element_id]
        # 複数経路：変更対象・影響範囲の要素のうち、この要素へ線がつながっている要素の数（最短経路の1本を除く）
        sources = {u for u, _ in graph.in_edges(element_id) if u in affected and u != element_id}
        result.impacts.append(
            ImpactItem(element_id, node["name"], node["element_type"], len(path), path,
                       spread=spread[element_id], extra_paths=max(0, len(sources) - 1))
        )
    # 影響の大きい順。同点なら近い順、種類、IDの順
    result.impacts.sort(key=lambda i: (-i.score, i.depth, i.element_type, i.element_id))
    result.beyond_max_depth = sorted(beyond - set(paths))
    return result


def step_label(step: Step) -> str:
    """経路1区間の関係名。双方向の関係を逆向きにたどった場合は、元の関係名に「双方向」と付ける。"""
    if step.reversed:
        return f"{models.RELATION_TYPES.get(step.relation_type, step.relation_type)}・双方向"
    return models.RELATION_TARGET_LABELS.get(step.relation_type, step.relation_type)


def describe_path(graph: nx.MultiDiGraph, item: ImpactItem) -> str:
    """影響の理由を人が読める文にする。例：勤怠管理業務 → 人事部（担当）"""
    parts = [graph.nodes[item.path[0].from_id]["name"]]
    for step in item.path:
        parts.append(f"{graph.nodes[step.to_id]['name']}（{step_label(step)}）")
    return " → ".join(parts)
